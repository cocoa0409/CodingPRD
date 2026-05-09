"""Allocation selector (PRD §3.4) and clock-advance sweeps (PRD §2.5)."""
from db import db
from common import stamp_update
from services.calc import (
    FAMILY_SIZE_TOLERANCE,
    compute_monthly_effective_rent,
)
from services.sync import emit_audit_eligibility_change


# --------------------------------------------------------------------- #
# Allocation candidate selection (PRD §3.4)
# --------------------------------------------------------------------- #

def select_application_for_unit(program: dict, unit: dict) -> dict | None:
    """Return the single Application that wins the three-layer ranking, or None
    if the candidate set is empty.
    """
    apartment_type = unit.get("apartment_type")
    bedroom_count = int(unit.get("bedroom_count", 0))
    accessibility_compliant = bool(unit.get("accessibility_compliant"))
    allowed_sizes = FAMILY_SIZE_TOLERANCE.get(apartment_type, set())

    candidates: list[dict] = []
    for app in db.applications.values():
        if app.get("housing_program_id") != program["id"]:
            continue
        if app.get("status") != "QUEUED":
            continue
        family_size = int(app.get("family_size", 0))
        if family_size not in allowed_sizes:
            continue
        # Accessibility filter is one-sided
        if not accessibility_compliant and bool(app.get("requires_accessibility")):
            continue
        candidates.append(app)

    if not candidates:
        return None

    # Three-layer sort
    #   1. queue_score DESC
    #   2. (only when unit is accessible) requires_accessibility DESC
    #   3. tie_break_key ASC
    def sort_key(app: dict):
        score = int(app.get("queue_score", 0))
        ra = 1 if bool(app.get("requires_accessibility")) else 0
        # When the unit is NOT accessible, layer-2 must not affect ordering;
        # set it to a constant so it's a no-op tiebreaker.
        layer2 = ra if accessibility_compliant else 0
        tie_key = app.get("tie_break_key") or ""
        # Negate score & layer2 to sort DESC via natural ASC sort
        return (-score, -layer2, tie_key)

    candidates.sort(key=sort_key)
    return candidates[0]


# --------------------------------------------------------------------- #
# Clock-advance sweeps (PRD §2.5)
# --------------------------------------------------------------------- #

def run_clock_sweeps(program: dict, *, actor_user_id: str) -> None:
    """After advancing program.current_period_index, expire reductions whose
    validity has been reached, and exit applications whose grace period has
    elapsed (cascading to contract + housing unit).
    """
    cpi = int(program["current_period_index"])
    program_id = program["id"]
    grace = int(program.get("grace_period_length", 6))

    # Sweep 1 — RentReduction FINAL_APPROVED → EXPIRED
    affected_contracts: set[str] = set()
    for rr in list(db.rent_reductions.values()):
        if rr.get("status") != "FINAL_APPROVED":
            continue
        ve = rr.get("validity_end_period")
        if ve is None:
            continue
        if cpi >= int(ve):
            rr["status"] = "EXPIRED"
            stamp_update(rr)
            affected_contracts.add(rr.get("contract_id"))
    for cid in affected_contracts:
        c = db.contracts.get(cid)
        if not c:
            continue
        new_rent = compute_monthly_effective_rent(c, current_period_index=cpi)
        if new_rent != c.get("monthly_effective_rent_cents"):
            c["monthly_effective_rent_cents"] = new_rent
            stamp_update(c)

    # Sweep 2 — Application EXIT_PENDING → EXITED when grace period elapsed
    for app in list(db.applications.values()):
        if app.get("housing_program_id") != program_id:
            continue
        if app.get("status") != "EXIT_PENDING":
            continue
        trigger = app.get("exit_trigger_period")
        if trigger is None:
            continue
        if cpi >= int(trigger) + grace:
            _do_exit(app, program=program, actor_user_id=actor_user_id,
                     current_period_index=cpi)


def _do_exit(application: dict, *, program: dict, actor_user_id: str,
             current_period_index: int) -> None:
    """Perform the EXIT_PENDING → EXITED transition + cascades."""
    program_id = program["id"]
    before_status = application.get("status")
    application["status"] = "EXITED"
    stamp_update(application)

    # Find the active (or most recent) contract for this application & terminate it
    contract = _find_contract_for_application(application["id"])
    if contract:
        before_c = contract.get("status")
        if before_c != "TERMINATED":
            contract["status"] = "TERMINATED"
            contract["termination_period"] = current_period_index
            stamp_update(contract)
            # Expire all non-REJECTED reductions on the contract
            for rr in list(db.rent_reductions.values()):
                if rr.get("contract_id") != contract.get("id"):
                    continue
                if rr.get("status") not in {"REJECTED", "EXPIRED"}:
                    rr["status"] = "EXPIRED"
                    stamp_update(rr)
        # Housing unit → AVAILABLE
        unit = db.housing_units.get(contract.get("housing_unit_id"))
        if unit and unit.get("status") != "AVAILABLE":
            unit["status"] = "AVAILABLE"
            stamp_update(unit)

    emit_audit_eligibility_change(
        program_id=program_id,
        subject_type="APPLICATION",
        subject_id=application["id"],
        actor_user_id=actor_user_id,
        before={"status": before_status},
        after={"status": "EXITED"},
        note="exit finalized",
        current_period_index=current_period_index,
    )


def _find_contract_for_application(app_id: str) -> dict | None:
    """Return the (single) contract on this application, or None."""
    for c in db.contracts.values():
        if c.get("application_id") == app_id:
            return c
    return None


# --------------------------------------------------------------------- #
# Manual finalize-exit (PRD §3.7)
# --------------------------------------------------------------------- #

def manual_finalize_exit(application: dict, *, program: dict,
                         actor_user_id: str) -> None:
    """Drive the same EXIT_PENDING → EXITED transition for one application,
    enforcing the grace-period-elapsed precondition.
    """
    from errors import api_error
    cpi = int(program["current_period_index"])
    grace = int(program.get("grace_period_length", 6))
    trigger = application.get("exit_trigger_period")
    if trigger is None or cpi < int(trigger) + grace:
        raise api_error("ERR_GRACE_PERIOD_NOT_ELAPSED",
                        "Grace period has not yet elapsed")
    _do_exit(application, program=program, actor_user_id=actor_user_id,
             current_period_index=cpi)
