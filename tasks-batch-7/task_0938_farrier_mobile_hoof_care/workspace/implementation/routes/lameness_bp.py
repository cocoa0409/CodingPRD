"""Lameness cases and therapeutic prescriptions (PRD 3.6)."""

from flask import Blueprint

from core.auth import authenticate, require_client_owner
from core.constants import (
    LAMENESS_MAX_SEVERITY,
    LAMENESS_MIN_SEVERITY,
    LIMBS,
    MAX_PRESCRIBED_CYCLE_WEEKS,
    MIN_PRESCRIBED_CYCLE_WEEKS,
    PRESCRIPTION_MAX_DURATION_DAYS,
)
from core.errors import ApiError
from core.store import db, order_key
from core.timeutil import clock, day_difference, parse_iso_date
from core.validate import (
    bad,
    body,
    enum,
    in_range,
    no_duplicates,
    out_of_range,
    req_date,
    req_int,
    req_list,
)
from domain.lameness import qualifies_for_hold, recompute_hold
from domain.lookup import guard_lameness_case, guard_prescription, must, must_ref
from domain.scheduling import refresh_next_due

from ._common import listing, single

bp = Blueprint("lameness", __name__)

CASE_READ_ROLES = ("PlatformAdmin", "Dispatcher", "Farrier", "ClientUser", "Veterinarian")


@bp.post("/lameness-cases")
def create_case():
    authenticate(("ClientUser", "Veterinarian"))
    data = body()
    horse = must_ref("horses", data.get("horse_id"))
    if horse is None:
        bad("Field horse_id is required.")
    require_client_owner(horse["client_id"])
    reported_on = req_date(data, "reported_on")
    severity = req_int(data, "severity")
    in_range(severity, LAMENESS_MIN_SEVERITY, LAMENESS_MAX_SEVERITY, "severity")

    hold_applied = qualifies_for_hold(severity)
    case = db.mint(
        "lameness_cases",
        {
            "horse_id": horse["id"],
            "reported_on": reported_on,
            "severity": severity,
            "status": "OPEN",
            "hold_applied": hold_applied,
        },
    )
    if hold_applied and recompute_hold(horse, run_chain=True):
        db.touch(horse)
    return single(case, 201)


@bp.get("/lameness-cases")
def list_cases():
    return listing("lameness_cases", {"horse_id": "horse_id", "status": "status"}, CASE_READ_ROLES)


@bp.get("/lameness-cases/<case_id>")
def read_case(case_id):
    authenticate(CASE_READ_ROLES)
    case = must("lameness_cases", case_id)
    guard_lameness_case(case)
    return single(case)


@bp.post("/lameness-cases/<case_id>/resolve")
def resolve_case(case_id):
    authenticate(("Veterinarian",))
    case = must("lameness_cases", case_id)
    if case["status"] not in ("OPEN", "PRESCRIBED"):
        raise ApiError("ERR_INVALID_STATE")
    horse = db.get("horses", case["horse_id"])
    horse_changed = False
    if case["status"] == "PRESCRIBED":
        actives = [
            p
            for p in db.vet_prescriptions.values()
            if p["lameness_case_id"] == case["id"] and p["status"] == "ACTIVE"
        ]
        for prescription in sorted(actives, key=order_key):
            prescription["status"] = "REVOKED"
            db.touch(prescription)
        if horse is not None and horse.get("active_prescription_id") is not None:
            for prescription in actives:
                if horse["active_prescription_id"] == prescription["id"]:
                    horse["active_prescription_id"] = None
                    horse_changed = True
    case["status"] = "RESOLVED"
    if horse is not None and recompute_hold(horse):
        horse_changed = True
    if horse_changed:
        db.touch(horse)
    db.touch(case)
    return single(case)


@bp.post("/lameness-cases/<case_id>/reopen")
def reopen_case(case_id):
    authenticate(("Veterinarian",))
    case = must("lameness_cases", case_id)
    if case["status"] != "RESOLVED":
        raise ApiError("ERR_INVALID_STATE")
    case["status"] = "OPEN"
    horse = db.get("horses", case["horse_id"])
    # Reopening is deliberately NOT a re-run of the lameness chain: nothing is
    # blocked, detached or released.  The hold is felt only prospectively.
    if horse is not None and recompute_hold(horse, run_chain=False):
        db.touch(horse)
    db.touch(case)
    return single(case)


# --------------------------------------------------------------------------
# Therapeutic prescriptions
# --------------------------------------------------------------------------
@bp.post("/vet-prescriptions")
def create_prescription():
    authenticate(("Veterinarian",))
    data = body()
    case = must_ref("lameness_cases", data.get("lameness_case_id"))
    if case is None:
        bad("Field lameness_case_id is required.")
    issued_on = req_date(data, "issued_on")
    expires_on = req_date(data, "expires_on")
    limb_scope = req_list(data, "limb_scope")
    cycle_weeks = req_int(data, "prescribed_cycle_weeks")
    for token in limb_scope:
        if not isinstance(token, str):
            bad("limb_scope must contain limb tokens.")
    no_duplicates(limb_scope, "limb_scope")
    for token in limb_scope:
        enum(token, LIMBS, "limb_scope")
    in_range(
        cycle_weeks,
        MIN_PRESCRIBED_CYCLE_WEEKS,
        MAX_PRESCRIBED_CYCLE_WEEKS,
        "prescribed_cycle_weeks",
    )
    issued = parse_iso_date(issued_on)
    expires = parse_iso_date(expires_on)
    if expires < issued:
        out_of_range("expires_on must be on or after issued_on.")
    if day_difference(expires, issued) > PRESCRIPTION_MAX_DURATION_DAYS:
        out_of_range(
            "expires_on may be at most %d days after issued_on." % PRESCRIPTION_MAX_DURATION_DAYS
        )

    prescription = db.mint(
        "vet_prescriptions",
        {
            "lameness_case_id": case["id"],
            "horse_id": case["horse_id"],
            "issued_on": issued_on,
            "expires_on": expires_on,
            "limb_scope": list(limb_scope),
            "prescribed_cycle_weeks": cycle_weeks,
            "status": "DRAFT",
        },
    )
    return single(prescription, 201)


@bp.get("/vet-prescriptions")
def list_prescriptions():
    return listing(
        "vet_prescriptions",
        {"lameness_case_id": "lameness_case_id", "horse_id": "horse_id", "status": "status"},
        CASE_READ_ROLES,
    )


@bp.get("/vet-prescriptions/<prescription_id>")
def read_prescription(prescription_id):
    authenticate(CASE_READ_ROLES)
    prescription = must("vet_prescriptions", prescription_id)
    guard_prescription(prescription)
    return single(prescription)


@bp.post("/vet-prescriptions/<prescription_id>/activate")
def activate_prescription(prescription_id):
    authenticate(("Veterinarian",))
    prescription = must("vet_prescriptions", prescription_id)
    data = body()
    expected = req_int(data, "expected_lameness_case_version")
    case = db.get("lameness_cases", prescription["lameness_case_id"])
    if case is None or expected != case["version"]:
        raise ApiError("ERR_STALE_CASE_VERSION")
    if prescription["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE")
    if parse_iso_date(prescription["expires_on"]) < clock.today:
        raise ApiError("ERR_INVALID_STATE")

    siblings = [
        p
        for p in db.vet_prescriptions.values()
        if p["lameness_case_id"] == case["id"]
        and p["status"] == "ACTIVE"
        and p["id"] != prescription["id"]
    ]
    for sibling in sorted(siblings, key=order_key):
        sibling["status"] = "SUPERSEDED"
        db.touch(sibling)

    prescription["status"] = "ACTIVE"
    db.touch(prescription)

    horse = db.get("horses", prescription["horse_id"])
    if horse is not None:
        horse["active_prescription_id"] = prescription["id"]
        # The therapeutic cycle only has a base date once the horse has a
        # last_completed_on; otherwise next_due_on stays null.
        refresh_next_due(horse)
        db.touch(horse)
    if case["status"] == "OPEN":
        case["status"] = "PRESCRIBED"
    db.touch(case)
    return single(prescription)


@bp.post("/vet-prescriptions/<prescription_id>/revoke")
def revoke_prescription(prescription_id):
    authenticate(("Veterinarian",))
    prescription = must("vet_prescriptions", prescription_id)
    if prescription["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE")
    prescription["status"] = "REVOKED"
    db.touch(prescription)
    horse = db.get("horses", prescription["horse_id"])
    if horse is not None:
        changed = False
        if horse.get("active_prescription_id") == prescription["id"]:
            horse["active_prescription_id"] = None
            changed = True
        if refresh_next_due(horse):
            changed = True
        if changed:
            db.touch(horse)
    return single(prescription)
