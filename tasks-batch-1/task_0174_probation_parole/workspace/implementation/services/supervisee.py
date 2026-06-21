"""Supervisee lifecycle transitions and their cascades (PRD §3.1, §3.7, §3.8, §3.9)."""
import db
from errors import (
    ApiError,
    ERR_INVALID_STATE,
    ERR_OUTSTANDING_BALANCE,
)
from services.common import recompute_balances


def cascade_conditions(supervisee, from_statuses, to_status):
    """Transition the supervisee's conditions in `from_statuses` to `to_status`.

    Each touched condition gets its own version bump and timestamp refresh
    (PRD §2.10)."""
    for c in db.conditions.values():
        if c.get("supervisee_id") != supervisee["id"]:
            continue
        if c["status"] in from_statuses:
            c["status"] = to_status
            db.touch(c)


def auto_file_violation(supervisee, violation_class, officer_id, source_drug_test_id=None):
    """Mint a FILED violation as a cascade side effect (abscond / missed check-in)."""
    rec = db.common_create_fields(versioned=True)
    rec.update(
        {
            "supervisee_id": supervisee["id"],
            "filed_by_officer_id": officer_id,
            "violation_class": violation_class,
            "source_drug_test_id": source_drug_test_id,
            "points": 0,
            "status": "FILED",
            "sustained_by_actor_id": None,
        }
    )
    db.violations[rec["id"]] = rec
    return rec


# ---- Lifecycle transitions ----------------------------------------------
def activate(supervisee):
    if supervisee["status"] != "INTAKE":
        raise ApiError(*ERR_INVALID_STATE, "Supervisee is not in INTAKE.")
    # Require at least one ADOPTED risk assessment (PRD §3.1).
    has_adopted = any(
        ra.get("supervisee_id") == supervisee["id"] and ra["assessment_status"] == "ADOPTED"
        for ra in db.risk_assessments.values()
    )
    if not has_adopted:
        raise ApiError(*ERR_INVALID_STATE, "No adopted risk assessment.")
    supervisee["status"] = "ACTIVE"
    db.touch(supervisee)
    return supervisee


def abscond(supervisee, officer_id):
    if supervisee["status"] != "ACTIVE":
        raise ApiError(*ERR_INVALID_STATE, "Supervisee is not ACTIVE.")
    supervisee["status"] = "ABSCONDED"
    auto_file_violation(supervisee, "ABSCOND", officer_id)
    db.touch(supervisee)
    return supervisee


def return_to_supervision(supervisee):
    if supervisee["status"] != "ABSCONDED":
        raise ApiError(*ERR_INVALID_STATE, "Supervisee is not ABSCONDED.")
    supervisee["status"] = "ACTIVE"
    db.touch(supervisee)
    return supervisee


def refer_revocation(supervisee):
    status = supervisee["status"]
    if status == "ACTIVE":
        if supervisee["cumulative_violation_points"] < 12:
            raise ApiError(
                *ERR_INVALID_STATE,
                "Cumulative violation points below revocation-referral threshold.",
            )
    elif status == "ABSCONDED":
        pass  # absconders may be referred regardless of point total
    else:
        raise ApiError(*ERR_INVALID_STATE, "Supervisee is not ACTIVE or ABSCONDED.")
    supervisee["status"] = "REVOCATION_PENDING"
    db.touch(supervisee)
    return supervisee


def revoke(supervisee):
    if supervisee["status"] != "REVOCATION_PENDING":
        raise ApiError(*ERR_INVALID_STATE, "Supervisee is not REVOCATION_PENDING.")
    supervisee["status"] = "REVOKED"
    # Cascade PROPOSED/ACTIVE conditions -> SUSPENDED (PRD §3.7).
    cascade_conditions(supervisee, ("PROPOSED", "ACTIVE"), "SUSPENDED")
    db.touch(supervisee)
    return supervisee


def reinstate(supervisee):
    if supervisee["status"] != "REVOCATION_PENDING":
        raise ApiError(*ERR_INVALID_STATE, "Supervisee is not REVOCATION_PENDING.")
    supervisee["status"] = "ACTIVE"
    db.touch(supervisee)
    return supervisee


def complete(supervisee):
    if supervisee["status"] != "ACTIVE":
        raise ApiError(*ERR_INVALID_STATE, "Supervisee is not ACTIVE.")
    # Recompute balances to the present moment before the gate.
    recompute_balances(supervisee)
    if supervisee["restitution_balance_cents"] != 0 or supervisee["fee_balance_cents"] != 0:
        raise ApiError(*ERR_OUTSTANDING_BALANCE, "Outstanding balance must be zero.")
    # No FILED or APPEALED violations (state check).
    for v in db.violations.values():
        if v.get("supervisee_id") == supervisee["id"] and v["status"] in ("FILED", "APPEALED"):
            raise ApiError(*ERR_INVALID_STATE, "Open violations remain.")
    supervisee["status"] = "COMPLETED"
    cascade_conditions(supervisee, ("ACTIVE",), "SATISFIED")
    db.touch(supervisee)
    return supervisee
