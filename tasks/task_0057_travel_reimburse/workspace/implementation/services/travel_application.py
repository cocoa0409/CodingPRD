"""Business logic for TravelApplication: chain computation, approvals, etc."""

from __future__ import annotations

from decimal import Decimal

from db import STORE
from errors import (
    APIError, ERR_INVALID_STATE, ERR_NOT_CURRENT_APPROVER, ERR_NO_ACTIVE_STANDARD,
    ERR_REFERENCE_INVALID,
)
from services.standards import find_active_standard
from utils import CLOCK, parse_ts


AMOUNT_DEPT_THRESHOLD = Decimal("5000.00")
AMOUNT_GM_THRESHOLD = Decimal("30000.00")
BUDGET_OVERRUN_FACTOR = Decimal("1.20")


def compute_required_chain(*, estimated_budget: Decimal, travel_scope: str, urgent: bool) -> list[str]:
    """Per §3.2 / calc travel_application_required_chain."""
    chain: list[str] = ["SUPERVISOR"]
    if estimated_budget > AMOUNT_DEPT_THRESHOLD or travel_scope == "OVERSEAS":
        chain.append("DEPT_HEAD")
    chain.append("FINANCE")
    if estimated_budget > AMOUNT_GM_THRESHOLD or travel_scope == "OVERSEAS":
        chain.append("GM")
    # Urgent expedites only DOMESTIC: drop DEPT_HEAD
    if urgent and travel_scope == "DOMESTIC" and "DEPT_HEAD" in chain:
        chain.remove("DEPT_HEAD")
    return chain


# Mapping from API roles to chain step names
ROLE_TO_CHAIN_STEP = {
    "Supervisor": "SUPERVISOR",
    "DeptHead": "DEPT_HEAD",
    "Finance": "FINANCE",
    "GeneralManager": "GM",
}


# Status order under TravelApplication approval flow
APP_STATUS_ORDER = [
    "SUBMITTED",
    "SUPERVISOR_APPROVED",
    "DEPT_HEAD_APPROVED",
    "FINANCE_APPROVED",
    "GM_APPROVED",
    "APPROVED",
]


def consumed_steps_for_app_status(status: str) -> list[str]:
    """Return list of consumed chain steps based on current application status."""
    if status == "SUBMITTED":
        return []
    if status == "SUPERVISOR_APPROVED":
        return ["SUPERVISOR"]
    if status == "DEPT_HEAD_APPROVED":
        return ["SUPERVISOR", "DEPT_HEAD"]
    if status == "FINANCE_APPROVED":
        # Consumed everything up through finance.
        # In the chain, only steps that are *in* required_chain count;
        # finance_approved means SUPERVISOR (and possibly DEPT_HEAD) + FINANCE consumed.
        return ["SUPERVISOR", "DEPT_HEAD", "FINANCE"]
    if status == "GM_APPROVED":
        return ["SUPERVISOR", "DEPT_HEAD", "FINANCE", "GM"]
    return []


def next_chain_step(app: dict) -> str | None:
    """Compute the next unconsumed chain step for this app's current status.
    Returns the step name or None if chain is exhausted."""
    chain: list[str] = app.get("required_chain") or []
    consumed = consumed_steps_for_app_status(app["status"])
    # Filter consumed by what's actually in chain (because DEPT_HEAD may be absent)
    for step in chain:
        if step in consumed:
            continue
        return step
    return None


def bump(row: dict) -> None:
    """Refresh updated_at and increment version on a mutable resource."""
    row["updated_at"] = CLOCK.now_iso()
    row["version"] = row.get("version", 0) + 1


def pin_standard_version(app: dict) -> int:
    """Resolve and pin the active ExpenseStandard.version for this application
    at the moment of submit. For OVERSEAS travel_scope, the city_tier lookup is
    OVERSEAS; else it's the destination_tier."""
    tier = "OVERSEAS" if app["travel_scope"] == "OVERSEAS" else app["destination_tier"]
    applicant = STORE.employees.get(app["applicant_id"])
    if not applicant:
        # Shouldn't happen because submit validates applicant exists; raise as reference invalid
        raise APIError(ERR_REFERENCE_INVALID, "Applicant not found", 422)
    level = applicant["employee_level"]
    standard = find_active_standard(CLOCK.now(), city_tier=tier, employee_level=level)
    if standard is None:
        raise APIError(ERR_NO_ACTIVE_STANDARD,
                        f"No active ExpenseStandard for ({tier}, {level})",
                        422)
    return standard["version"]


def recompute_total_booked_cost(app: dict) -> Decimal:
    """Sum cost of ACTIVE segments under the application; round to 2dp half-up."""
    from utils import round_money
    total = Decimal("0.00")
    for seg in STORE.itinerary_segments.values():
        if seg["application_id"] != app["id"]:
            continue
        if seg["status"] != "ACTIVE":
            continue
        total += seg["cost"]
    total = round_money(total)
    app["total_booked_cost"] = total
    return total


def has_active_segments(app_id: str) -> bool:
    for seg in STORE.itinerary_segments.values():
        if seg["application_id"] == app_id and seg["status"] == "ACTIVE":
            return True
    return False


def assert_current_approver(app: dict, role: str, user_id: str) -> str:
    """Check that the acting role+id matches the current chain step.
    Returns the step name; raises ERR_NOT_CURRENT_APPROVER otherwise."""
    expected_step = next_chain_step(app)
    actor_step = ROLE_TO_CHAIN_STEP.get(role)
    if expected_step is None or actor_step != expected_step:
        raise APIError(ERR_NOT_CURRENT_APPROVER,
                        "Acting role is not the current chain step's approver",
                        403)
    # Supervisor must match applicant.supervisor_id
    if role == "Supervisor":
        applicant = STORE.employees.get(app["applicant_id"])
        if not applicant or applicant.get("supervisor_id") != user_id:
            raise APIError(ERR_NOT_CURRENT_APPROVER,
                            "Acting Supervisor is not the applicant's supervisor",
                            403)
    return expected_step
