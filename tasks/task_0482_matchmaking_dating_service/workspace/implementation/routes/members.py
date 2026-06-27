from flask import Blueprint, request

import errors
from db import db, new_id
from middleware import authenticate, require_roles, require_member_owner
from response import success_object, success_array
from services.common import (
    get_json_body, require_str, require_enum, require_int, require_bool,
    opt_str, stamp_create, touch, parse_pagination, paginate, sort_by_created,
    parse_iso,
)
from services.compute import (
    serialize_member, serialize_screening, serialize_preference, reconcile_member,
)
from services.transitions import exit_member

bp = Blueprint("members", __name__)

ALL_ROLES = ("BillingAdmin", "Matchmaker", "ScreeningOfficer", "Member")
OPERATOR_ROLES = ("BillingAdmin", "Matchmaker", "ScreeningOfficer")
GENDERS = ("MALE", "FEMALE", "NONBINARY")
SEEKING = ("MALE", "FEMALE", "NONBINARY", "ANY")


def _get_member_or_404(member_id):
    m = db.members.get(member_id)
    if not m:
        raise errors.not_found("ERR_MEMBER_NOT_FOUND")
    return m


# ---------------------------------------------------------------------------
# Member registration / listing / get / exit
# ---------------------------------------------------------------------------
@bp.route("/members", methods=["POST"])
def register_member():
    principal = authenticate()
    require_roles(principal, ("ScreeningOfficer", "Matchmaker"))
    body = get_json_body()
    email = require_str(body, "email")
    full_name = require_str(body, "full_name")
    birth_date = require_str(body, "birth_date")
    parse_iso(birth_date)  # validate format
    city = require_str(body, "city")
    gender = require_enum(body, "gender", GENDERS)

    # email unique among non-EXITED members
    for m in db.members.values():
        if m["email"] == email and m["status"] != "EXITED":
            raise errors.invalid_request("Email already in use.")

    mid = new_id()
    member = {
        "id": mid,
        "email": email,
        "full_name": full_name,
        "birth_date": birth_date,
        "city": city,
        "gender": gender,
        "status": "PROSPECT",
        "screening_decision": "NONE",
        "active_membership_id": None,
        "wallet_credit_cents": 0,
        "frozen_days_total": 0,
    }
    stamp_create(member)
    db.members[mid] = member
    return success_object(serialize_member(member), 201)


@bp.route("/members", methods=["GET"])
def list_members():
    principal = authenticate()
    require_roles(principal, OPERATOR_ROLES)
    status = request.args.get("status")
    limit, offset = parse_pagination()
    records = list(db.members.values())
    for m in records:
        reconcile_member(m)
    if status:
        records = [m for m in records if m["status"] == status]
    records = sort_by_created(records)
    page, total = paginate(records, limit, offset)
    return success_array([serialize_member(m) for m in page], limit, offset, total)


@bp.route("/members/<member_id>", methods=["GET"])
def get_member(member_id):
    principal = authenticate()
    require_roles(principal, ALL_ROLES)
    member = _get_member_or_404(member_id)
    require_member_owner(principal, member_id)
    reconcile_member(member)
    return success_object(serialize_member(member))


@bp.route("/members/<member_id>/exit", methods=["POST"])
def member_exit(member_id):
    principal = authenticate()
    require_roles(principal, ("BillingAdmin",))
    member = _get_member_or_404(member_id)
    reconcile_member(member)
    if member["status"] not in ("ACTIVE", "FROZEN"):
        raise errors.conflict("ERR_MEMBER_NOT_EXITABLE")
    exit_member(member)
    return success_object(serialize_member(member))


# ---------------------------------------------------------------------------
# Screenings
# ---------------------------------------------------------------------------
@bp.route("/members/<member_id>/screenings", methods=["POST"])
def open_screening(member_id):
    principal = authenticate()
    require_roles(principal, ("ScreeningOfficer",))
    member = _get_member_or_404(member_id)
    body = get_json_body()
    score = require_int(body, "questionnaire_score")
    identity_verified = require_bool(body, "identity_verified")
    if score < 0 or score > 100:
        raise errors.invalid_request("questionnaire_score must be 0..100.")
    if member["status"] != "PROSPECT":
        raise errors.conflict("ERR_MEMBER_NOT_PROSPECT")

    sid = new_id()
    screening = {
        "id": sid,
        "member_id": member_id,
        "questionnaire_score": score,
        "identity_verified": identity_verified,
        "decision": "PENDING",
        "decision_note": "",
        "status": "PENDING",
    }
    stamp_create(screening)
    db.screenings[sid] = screening
    member["status"] = "SCREENING"
    touch(member)
    return success_object(serialize_screening(screening), 201)


@bp.route("/members/<member_id>/screenings", methods=["GET"])
def list_screenings(member_id):
    principal = authenticate()
    require_roles(principal, OPERATOR_ROLES)
    _get_member_or_404(member_id)
    limit, offset = parse_pagination()
    records = [s for s in db.screenings.values() if s["member_id"] == member_id]
    records = sort_by_created(records)
    page, total = paginate(records, limit, offset)
    return success_array([serialize_screening(s) for s in page], limit, offset, total)


@bp.route("/members/<member_id>/screenings/<screening_id>/decide", methods=["POST"])
def decide_screening(member_id, screening_id):
    principal = authenticate()
    require_roles(principal, ("ScreeningOfficer",))
    member = _get_member_or_404(member_id)
    screening = db.screenings.get(screening_id)
    if not screening or screening["member_id"] != member_id:
        raise errors.not_found("ERR_SCREENING_NOT_FOUND")
    body = get_json_body()
    decision = require_enum(body, "decision", ("APPROVED", "REJECTED"))
    note = opt_str(body, "decision_note", "")
    if screening["decision"] != "PENDING":
        raise errors.conflict("ERR_SCREENING_ALREADY_DECIDED")

    screening["decision"] = decision
    screening["status"] = decision
    screening["decision_note"] = note
    touch(screening)

    if decision == "APPROVED":
        member["screening_decision"] = "APPROVED"
        # status flips to ACTIVE only on membership activation
        touch(member)
    else:
        member["screening_decision"] = "REJECTED"
        member["status"] = "EXITED"
        touch(member)
    return success_object(serialize_screening(screening))


# ---------------------------------------------------------------------------
# Preferences (idempotent upsert)
# ---------------------------------------------------------------------------
@bp.route("/members/<member_id>/preferences", methods=["PUT"])
def upsert_preferences(member_id):
    principal = authenticate()
    require_roles(principal, ("Member", "Matchmaker"))
    member = _get_member_or_404(member_id)
    require_member_owner(principal, member_id)
    body = get_json_body()
    seeking_gender = require_enum(body, "seeking_gender", SEEKING)
    min_age = require_int(body, "min_age")
    max_age = require_int(body, "max_age")
    max_distance_band = require_int(body, "max_distance_band")
    attribute_weights = body.get("attribute_weights")
    if attribute_weights is None or not isinstance(attribute_weights, dict):
        raise errors.invalid_request("attribute_weights must be an object.")
    for k, v in attribute_weights.items():
        if isinstance(v, bool) or not isinstance(v, int) or v < 0 or v > 100:
            raise errors.invalid_request("attribute_weights values must be integers 0..100.")
    dealbreaker_tags = body.get("dealbreaker_tags", [])
    if dealbreaker_tags is None:
        dealbreaker_tags = []
    if not isinstance(dealbreaker_tags, list) or any(not isinstance(t, str) for t in dealbreaker_tags):
        raise errors.invalid_request("dealbreaker_tags must be an array of strings.")
    if min_age < 18:
        raise errors.invalid_request("min_age must be >= 18.")
    if max_age < min_age:
        raise errors.invalid_request("max_age must be >= min_age.")
    if max_distance_band < 0 or max_distance_band > 3:
        raise errors.invalid_request("max_distance_band must be 0..3.")

    existing = None
    for p in db.preferences.values():
        if p["member_id"] == member_id:
            existing = p
            break

    if existing:
        existing["seeking_gender"] = seeking_gender
        existing["min_age"] = min_age
        existing["max_age"] = max_age
        existing["max_distance_band"] = max_distance_band
        existing["attribute_weights"] = attribute_weights
        existing["dealbreaker_tags"] = dealbreaker_tags
        touch(existing)
        return success_object(serialize_preference(existing))

    pid = new_id()
    pref = {
        "id": pid,
        "member_id": member_id,
        "seeking_gender": seeking_gender,
        "min_age": min_age,
        "max_age": max_age,
        "max_distance_band": max_distance_band,
        "attribute_weights": attribute_weights,
        "dealbreaker_tags": dealbreaker_tags,
    }
    stamp_create(pref)
    db.preferences[pid] = pref
    return success_object(serialize_preference(pref))


@bp.route("/members/<member_id>/preferences", methods=["GET"])
def get_preferences(member_id):
    principal = authenticate()
    require_roles(principal, ALL_ROLES)
    _get_member_or_404(member_id)
    require_member_owner(principal, member_id)
    records = [p for p in db.preferences.values() if p["member_id"] == member_id]
    records = sort_by_created(records)
    # array of 0 or 1; not paginated per PRD (returns the row(s))
    limit, offset = parse_pagination()
    page, total = paginate(records, limit, offset)
    return success_array([serialize_preference(p) for p in page], limit, offset, total)
