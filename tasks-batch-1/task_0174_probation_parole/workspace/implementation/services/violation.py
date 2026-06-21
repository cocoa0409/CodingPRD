"""Violation adjudication: sustain (sanction cascade) and appeal (PRD §3.5)."""
import db
from calculations import VIOLATION_POINTS, sanction_for
from errors import (
    ApiError,
    ERR_INVALID_STATE,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_SUPERVISEE_CLOSED,
)
from services.common import (
    TERMINAL_SUPERVISEE_STATES,
    recompute_cumulative_points,
)


def sustain(supervisee, violation, acting_actor_id):
    """FILED -> SUSTAINED: assign points, recompute cumulative, auto-create a
    Sanction from the matrix, possibly flip supervisee to REVOCATION_PENDING.

    Validation order (PRD §3.5): state (FILED) -> closed-supervisee guard ->
    segregation of duties.  Note: SCAFFOLD §1.4 lists the closed-supervisee
    guard ahead of segregation-of-duties; the PRD prose pins state-FILED first,
    then closed-supervisee, then segregation-of-duties.
    """
    if violation["status"] != "FILED":
        raise ApiError(*ERR_INVALID_STATE, "Violation is not FILED.")
    if supervisee["status"] in TERMINAL_SUPERVISEE_STATES:
        raise ApiError(*ERR_SUPERVISEE_CLOSED, "Supervisee case is closed.")
    if acting_actor_id == violation["filed_by_officer_id"]:
        raise ApiError(
            *ERR_SEGREGATION_OF_DUTIES,
            "The sustaining actor may not be the filing officer.",
        )

    # 1. Assign points by class.
    points = VIOLATION_POINTS[violation["violation_class"]]
    violation["points"] = points
    violation["status"] = "SUSTAINED"
    violation["sustained_by_actor_id"] = acting_actor_id

    # 2. Full recompute of cumulative points over SUSTAINED violations.
    recompute_cumulative_points(supervisee)
    post_cumulative = supervisee["cumulative_violation_points"]

    # 3. Select and auto-create a Sanction from the matrix.
    sanction_type, imposed_days = sanction_for(violation["violation_class"], post_cumulative)
    sanc = db.common_create_fields(versioned=True)
    sanc.update(
        {
            "violation_id": violation["id"],
            "sanction_type": sanction_type,
            "imposed_days": imposed_days,
            "status": "IMPOSED",
        }
    )
    db.sanctions[sanc["id"]] = sanc

    # 4. If the sanction is a revocation referral and supervisee was ACTIVE,
    #    flip ACTIVE -> REVOCATION_PENDING (depth-3 cross-entity cascade).
    if sanction_type == "REVOCATION_REFERRAL" and supervisee["status"] == "ACTIVE":
        supervisee["status"] = "REVOCATION_PENDING"

    # 5. Bump versions.
    db.touch(violation)
    db.touch(supervisee)
    return violation


def dismiss(violation):
    if violation["status"] != "FILED":
        raise ApiError(*ERR_INVALID_STATE, "Violation is not FILED.")
    violation["status"] = "DISMISSED"
    db.touch(violation)
    return violation


def appeal(supervisee, violation):
    """SUSTAINED -> APPEALED: compensating reversal of points and sanction."""
    if violation["status"] != "SUSTAINED":
        raise ApiError(*ERR_INVALID_STATE, "Violation is not SUSTAINED.")
    violation["status"] = "APPEALED"

    # Recompute cumulative over remaining SUSTAINED violations (falls by points).
    recompute_cumulative_points(supervisee)

    # Vacate any sanction tied to this violation.
    for sanc in db.sanctions.values():
        if sanc.get("violation_id") == violation["id"] and sanc["status"] != "VACATED":
            sanc["status"] = "VACATED"
            db.touch(sanc)

    # If supervisee is still REVOCATION_PENDING and cumulative now below the
    # threshold, revert REVOCATION_PENDING -> ACTIVE (depth-2 compensation).
    if (
        supervisee["status"] == "REVOCATION_PENDING"
        and supervisee["cumulative_violation_points"] < 12
    ):
        supervisee["status"] = "ACTIVE"

    db.touch(violation)
    db.touch(supervisee)
    return violation
