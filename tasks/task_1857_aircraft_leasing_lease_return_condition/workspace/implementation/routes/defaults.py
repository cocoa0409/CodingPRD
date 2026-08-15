"""Default cases: declare, list, cure, authorize-repossession, execute-repossession."""
from datetime import datetime, timedelta

from flask import Blueprint, g

from db import CLOCK, STORE, base_entity, fmt_clock, touch
from errors import (
    ERR_CURE_DEADLINE_NOT_PASSED,
    ERR_SOD_VIOLATION,
    ApiError,
    invalid_state,
    not_found,
)
from middleware import require_roles
from response import paginated, success
from services.cascades import open_default_case, release_aircraft_slots
from validators import get_body, req_int, req_str

bp = Blueprint("defaults", __name__)

DEFAULT_READ_ROLES = ("LessorAdmin", "CreditOfficer", "LegalApprover", "FinanceManager")


def get_case_or_404(case_id):
    c = STORE["default_cases"].get(case_id)
    if c is None:
        raise not_found("Default case not found")
    return c


@bp.post("/leasing/leases/<lease_id>/default-cases")
@require_roles("CreditOfficer")
def declare_default(lease_id):
    lease = STORE["leases"].get(lease_id)
    if lease is None:
        raise not_found("Lease not found")
    b = get_body()
    reason = req_str(b, "reason")
    cure_period_days = req_int(b, "cure_period_days", min_v=0)
    if lease["status"] not in ("ACTIVE", "RETURN_INITIATED"):
        raise invalid_state(
            "Default may be declared only on an ACTIVE or RETURN_INITIATED lease"
        )
    if open_default_case(lease["id"]) is not None:
        raise invalid_state("An open default case already exists for this lease")

    declared_at = CLOCK.now()
    cure_deadline = declared_at + timedelta(days=cure_period_days)
    c = base_entity()
    c.update(
        {
            "lease_id": lease["id"],
            "reason": reason,
            "cure_period_days": cure_period_days,
            "declared_at": fmt_clock(declared_at),
            "cure_deadline": fmt_clock(cure_deadline),
            "declared_by": g.user_id,
            "status": "DECLARED",
        }
    )
    STORE["default_cases"][c["id"]] = c
    lease["status"] = "DEFAULTED"
    touch(lease)
    return success(c, status=201)


@bp.get("/leasing/leases/<lease_id>/default-cases")
@require_roles(*DEFAULT_READ_ROLES)
def list_default_cases(lease_id):
    lease = STORE["leases"].get(lease_id)
    if lease is None:
        raise not_found("Lease not found")
    items = [c for c in STORE["default_cases"].values() if c["lease_id"] == lease["id"]]
    items.sort(key=lambda c: c["created_at"])
    return paginated(items)


@bp.post("/leasing/default-cases/<case_id>/cure")
@require_roles("CreditOfficer")
def cure_default(case_id):
    c = get_case_or_404(case_id)
    if c["status"] != "DECLARED":
        raise invalid_state("Only a DECLARED default case can be cured")
    c["status"] = "CURED"
    touch(c)
    lease = STORE["leases"][c["lease_id"]]
    if lease["status"] == "DEFAULTED":
        lease["status"] = "ACTIVE"
        touch(lease)
    return success(c)


@bp.post("/leasing/default-cases/<case_id>/authorize-repossession")
@require_roles("LegalApprover")
def authorize_repossession(case_id):
    c = get_case_or_404(case_id)
    if c["status"] != "DECLARED":
        raise invalid_state("Only a DECLARED default case can be authorized for repossession")
    deadline = datetime.fromisoformat(c["cure_deadline"].replace("Z", "+00:00"))
    if not (CLOCK.now() > deadline):
        raise ApiError(
            ERR_CURE_DEADLINE_NOT_PASSED,
            "The logical clock is not strictly after the cure deadline",
            409,
        )
    if g.user_id == c["declared_by"]:
        raise ApiError(
            ERR_SOD_VIOLATION,
            "The repossession authorizer must differ from the default declarer",
            409,
        )
    c["status"] = "REPOSSESSION_AUTHORIZED"
    touch(c)
    return success(c)


@bp.post("/leasing/default-cases/<case_id>/execute-repossession")
@require_roles("LessorAdmin")
def execute_repossession(case_id):
    c = get_case_or_404(case_id)
    if c["status"] != "REPOSSESSION_AUTHORIZED":
        raise invalid_state(
            "Only a REPOSSESSION_AUTHORIZED default case can be executed"
        )
    c["status"] = "REPOSSESSED"
    touch(c)

    lease = STORE["leases"][c["lease_id"]]
    # Cascade link 1: lease DEFAULTED -> TERMINATED.
    if lease["status"] == "DEFAULTED":
        lease["status"] = "TERMINATED"
        touch(lease)
    # Cascade link 2: aircraft ON_LEASE -> REPOSSESSED.
    aircraft = STORE["aircraft"].get(lease["aircraft_id"])
    if aircraft is not None and aircraft["status"] == "ON_LEASE":
        aircraft["status"] = "REPOSSESSED"
        touch(aircraft)
        # Cascade link 3: release non-terminal transition slots.
        release_aircraft_slots(aircraft["id"])
    # Conditional cascade: cancel any non-terminal return case of this lease.
    for case in STORE["return_cases"].values():
        if case["lease_id"] == lease["id"] and case["status"] not in (
            "SETTLED",
            "CANCELLED",
        ):
            case["status"] = "CANCELLED"
            touch(case)
    return success(c)
