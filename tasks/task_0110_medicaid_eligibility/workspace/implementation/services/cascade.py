"""Cross-aggregate cascades: emergency declarations, clock advance, sweep."""

from core.clock import CLOCK
from core.store import STORE
from services.mutations import bump
from services.projections import (
    emergency_status,
    state_emergency_continuous_active,
    list_enrollments_of_household,
)


def covers_state(decl: dict, state_code: str) -> bool:
    """Return True iff the declaration's scope covers state_code."""
    if decl["scope"] == "FEDERAL":
        return True
    if decl["scope"] == "STATE" and decl.get("state_code") == state_code:
        return True
    return False


def emergency_arrival_cascade(decl: dict):
    """A new EmergencyDeclaration was just created. For every Enrollment
    whose household's state is covered AND whose coverage_status is ACTIVE
    or REDETERMINATION_DUE: flip to CONTINUOUS_COVERAGE. Withdraw any
    associated PENDING redetermination."""
    if emergency_status(decl) != "ACTIVE":
        return
    affected_households = set()
    for enrollment in list(STORE.enrollments.values()):
        applicant = STORE.applicants.get(enrollment["applicant_id"])
        if applicant is None:
            continue
        household = STORE.households.get(applicant["household_id"])
        if household is None:
            continue
        if not covers_state(decl, household["state_code"]):
            continue
        prev_status = enrollment["coverage_status"]
        if prev_status not in ("ACTIVE", "REDETERMINATION_DUE"):
            continue
        enrollment["coverage_status"] = "CONTINUOUS_COVERAGE"
        bump(enrollment)
        affected_households.add(household["id"])
        # If the enrollment was REDETERMINATION_DUE: any PENDING redet → WITHDRAWN
        if prev_status == "REDETERMINATION_DUE":
            for r in list(STORE.redeterminations.values()):
                if r["enrollment_id"] == enrollment["id"] and r["status"] == "PENDING":
                    r["status"] = "WITHDRAWN"
                    bump(r)
    for hid in affected_households:
        h = STORE.households.get(hid)
        if h is not None:
            bump(h)


def expire_emergencies_and_revert(prev_clock):
    """After /_clock/advance: any declaration whose expires_at <= new clock_now
    transitions to EXPIRED. For every CONTINUOUS_COVERAGE enrollment whose
    state is no longer covered by any ACTIVE declaration, revert to ACTIVE.
    """
    # Expiration is computed lazily by emergency_status(); nothing to write
    # for the declaration itself. But we must revert affected enrollments.
    affected_households = set()
    for enrollment in list(STORE.enrollments.values()):
        if enrollment["coverage_status"] != "CONTINUOUS_COVERAGE":
            continue
        applicant = STORE.applicants.get(enrollment["applicant_id"])
        if applicant is None:
            continue
        household = STORE.households.get(applicant["household_id"])
        if household is None:
            continue
        if state_emergency_continuous_active(household["state_code"]):
            continue
        enrollment["coverage_status"] = "ACTIVE"
        bump(enrollment)
        affected_households.add(household["id"])
    for hid in affected_households:
        h = STORE.households.get(hid)
        if h is not None:
            bump(h)


def redetermination_sweep():
    """For every ACTIVE Enrollment with redetermination_due_at <= clock_now:
    transition to REDETERMINATION_DUE and create a PENDING Redetermination.
    Returns the list of created redetermination IDs.
    """
    from core.store import gen_id
    from core.timeutils import parse_iso
    from services.mutations import stamp_create

    now = CLOCK.now()
    created = []
    affected_households = set()
    for enrollment in list(STORE.enrollments.values()):
        if enrollment["coverage_status"] != "ACTIVE":
            continue
        due_at_str = enrollment["redetermination_due_at"]
        try:
            due_at = parse_iso(due_at_str, "redetermination_due_at")
        except Exception:
            continue
        if due_at > now:
            continue
        enrollment["coverage_status"] = "REDETERMINATION_DUE"
        bump(enrollment)
        # Create PENDING Redetermination
        rid = gen_id()
        row = {
            "id": rid,
            "enrollment_id": enrollment["id"],
            "due_date": due_at_str,
            "_due_date_dt": due_at,
            "status": "PENDING",
            "new_snapshot_magi": None,
            "new_snapshot_fpl_percent": None,
            "decision": None,
        }
        stamp_create(row)
        STORE.redeterminations[rid] = row
        created.append(rid)
        applicant = STORE.applicants.get(enrollment["applicant_id"])
        if applicant is not None:
            affected_households.add(applicant["household_id"])
    for hid in affected_households:
        h = STORE.households.get(hid)
        if h is not None:
            bump(h)
    return created
