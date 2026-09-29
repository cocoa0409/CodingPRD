"""Counsellors and the individual-counselling waitlist (§3.5)."""

from flask import Blueprint, request

from core import calc
from core.auth import (authenticate, own_counseling_referral,
                       own_counseling_referral_strict)
from core.envelope import created, listing, ok
from core.errors import ApiError
from core.shape import (CLOSE_REASONS, LICENSE_TYPES, LOSS_TYPES, URGENCIES, body,
                        req_array, req_enum, req_int, req_str)
from core.store import public, store
from services import derive
from services.state import must_exist, require_participant_active, transition

bp = Blueprint("counselors", __name__)


@bp.route("/bereavement/counselors", methods=["POST"])
def create_counselor():
    authenticate(["ProgramDirector"])
    data = body()
    full_name = req_str(data, "full_name")
    license_type = req_enum(data, "license_type", LICENSE_TYPES)
    specialties = req_array(data, "specialties", LOSS_TYPES)
    caseload_cap = req_int(data, "caseload_cap", 1)
    weekly_capacity = req_int(data, "weekly_capacity_minutes", 0)
    rec = store.create("Counselor", {
        "full_name": full_name,
        "license_type": license_type,
        "specialties": specialties,
        "caseload_cap": caseload_cap,
        "weekly_capacity_minutes": weekly_capacity,
        "active_caseload": 0,
        "committed_minutes": 0,
        "status": "ACTIVE",
    })
    return created(public(rec))


@bp.route("/bereavement/counselors/<cid>", methods=["GET"])
def read_counselor(cid):
    authenticate(["ProgramDirector", "IntakeCoordinator", "Counselor"])
    return ok(public(must_exist("Counselor", cid)))


@bp.route("/bereavement/counselors/<cid>/deactivate", methods=["POST"])
def deactivate_counselor(cid):
    authenticate(["ProgramDirector"])
    counselor = must_exist("Counselor", cid)
    body()
    transition(counselor, {"ACTIVE"})
    counselor["status"] = "INACTIVE"
    counselor["active_caseload"] = 0
    counselor["committed_minutes"] = 0

    for referral in store.find("CounselingReferral", counselor_id=cid):
        if referral["status"] != "ASSIGNED":
            continue
        referral["status"] = "WAITLISTED"
        referral["counselor_id"] = None
        referral["assigned_at"] = None
        referral["waitlisted_at"] = store.now_iso()
        participant = store.get("Participant", referral["participant_id"])
        if participant is not None:
            participant["waitlist_reentry_count"] += 1
            if participant["waitlist_reentry_count"] >= 2:
                derive.apply_tier(participant, calc.escalate_tier(participant["risk_tier"]))
            store.touch(participant)
        derive.recompute_queue_priority(referral)
        store.touch(referral)

    store.touch(counselor)
    return ok(public(counselor))


@bp.route("/bereavement/counseling-referrals", methods=["POST"])
def create_counseling_referral():
    authenticate(["IntakeCoordinator", "Counselor"])
    data = body()
    participant_id = req_str(data, "participant_id")
    minutes = req_int(data, "requested_minutes_per_week", 1)
    urgency = req_enum(data, "urgency", URGENCIES)
    specialty = req_enum(data, "required_specialty", LOSS_TYPES)

    participant = must_exist("Participant", participant_id)
    require_participant_active(participant)

    rec = store.create("CounselingReferral", {
        "participant_id": participant_id,
        "counselor_id": None,
        "requested_minutes_per_week": minutes,
        "urgency": urgency,
        "required_specialty": specialty,
        "status": "WAITLISTED",
        "queue_priority": 0,
        "waitlisted_at": store.now_iso(),
        "assigned_at": None,
        "close_reason": None,
    })
    derive.recompute_queue_priority(rec)
    if participant["service_status"] == "ASSESSED":
        participant["service_status"] = "ACTIVE"
        store.touch(participant)
    return created(public(rec))


@bp.route("/bereavement/counseling-referrals/<rid>", methods=["GET"])
def read_counseling_referral(rid):
    ctx = authenticate(["IntakeCoordinator", "ProgramDirector", "Counselor"])
    rec = must_exist("CounselingReferral", rid)
    own_counseling_referral(ctx, rec)
    return ok(public(rec))


@bp.route("/bereavement/counseling-referrals", methods=["GET"])
def list_counseling_referrals():
    authenticate(["IntakeCoordinator", "ProgramDirector", "Counselor"])
    rows = store.all("CounselingReferral")
    for key in ("participant_id", "counselor_id", "status"):
        value = request.args.get(key)
        if value:
            rows = [r for r in rows if r[key] == value]
    rows = sorted(rows, key=lambda r: (-r["queue_priority"], r["waitlisted_at"] or "",
                                       r["created_at"], r["_seq"]))
    return listing(rows, public)


@bp.route("/bereavement/counseling-referrals/<rid>/assign", methods=["POST"])
def assign_counseling_referral(rid):
    authenticate(["IntakeCoordinator"])
    referral = must_exist("CounselingReferral", rid)
    data = body()
    counselor_id = req_str(data, "counselor_id")
    expected_version = req_int(data, "expected_counselor_version")

    counselor = must_exist("Counselor", counselor_id)
    if expected_version != counselor["version"]:
        raise ApiError("ERR_STALE_COUNSELOR_VERSION", "The counselor version has moved.")

    transition(referral, {"WAITLISTED"})
    if counselor["status"] != "ACTIVE":
        raise ApiError("ERR_COUNSELOR_NOT_ACTIVE", "The counselor is not ACTIVE.")

    if referral["required_specialty"] not in counselor["specialties"]:
        raise ApiError("ERR_SPECIALTY_MISMATCH", "The counselor lacks the required specialty.")

    if counselor["active_caseload"] + 1 > counselor["caseload_cap"]:
        raise ApiError("ERR_COUNSELOR_CASELOAD_EXCEEDED", "The caseload cap would be exceeded.")
    if counselor["committed_minutes"] + referral["requested_minutes_per_week"] > counselor["weekly_capacity_minutes"]:
        raise ApiError("ERR_COUNSELOR_CAPACITY_EXCEEDED", "The weekly minute budget would be exceeded.")

    referral["status"] = "ASSIGNED"
    referral["counselor_id"] = counselor_id
    referral["assigned_at"] = store.now_iso()
    store.touch(referral)
    derive.recompute_counselor(counselor)
    store.touch(counselor)
    return ok(public(referral))


@bp.route("/bereavement/counseling-referrals/<rid>/close", methods=["POST"])
def close_counseling_referral(rid):
    ctx = authenticate(["IntakeCoordinator", "Counselor"])
    referral = must_exist("CounselingReferral", rid)
    own_counseling_referral_strict(ctx, referral)
    data = body()
    reason = req_enum(data, "close_reason", CLOSE_REASONS)
    transition(referral, {"ASSIGNED"})
    counselor_id = referral["counselor_id"]
    referral["status"] = "CLOSED"
    referral["close_reason"] = reason
    store.touch(referral)
    counselor = store.get("Counselor", counselor_id) if counselor_id else None
    if counselor is not None:
        derive.recompute_counselor(counselor)
        store.touch(counselor)
    return ok(public(referral))
