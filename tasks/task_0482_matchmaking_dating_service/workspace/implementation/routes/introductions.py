from flask import Blueprint, request

import errors
from db import db, new_id
from middleware import authenticate, require_roles, require_member_owner
from response import success_object, success_array
from services.common import (
    get_json_body, require_str, require_int, require_enum, require_bool, opt_bool,
    opt_str, stamp_create, touch, parse_pagination, paginate, sort_by_created,
)
from services.compute import (
    serialize_introduction, serialize_feedback, guarantee_for_member,
    reconcile_member, committed_consumed_for_member,
)
from services.calculations import (
    compatibility_score, gender_satisfies, age_in_band, age_years,
    COMPATIBILITY_THRESHOLD,
)
from services.transitions import close_introduction

bp = Blueprint("introductions", __name__)

ALL_ROLES = ("BillingAdmin", "Matchmaker", "ScreeningOfficer", "Member")


def _get_intro_or_404(intro_id):
    i = db.introductions.get(intro_id)
    if not i:
        raise errors.not_found("ERR_INTRODUCTION_NOT_FOUND")
    return i


def _pref_for(member_id):
    for p in db.preferences.values():
        if p["member_id"] == member_id:
            return p
    return None


def _has_flagged_check(member_id):
    for c in db.background_checks.values():
        if c["member_id"] == member_id and c["status"] == "COMPLETED" and c["result"] == "FLAGGED":
            return True
    return False


# ---------------------------------------------------------------------------
# Suggest introduction (PRD §3.4) — densest validation pipeline (classes 6-12)
# ---------------------------------------------------------------------------
@bp.route("/introductions", methods=["POST"])
def suggest_introduction():
    principal = authenticate()
    require_roles(principal, ("Matchmaker",))
    body = get_json_body()
    member_a_id = require_str(body, "member_a_id")
    member_b_id = require_str(body, "member_b_id")
    win_back = opt_bool(body, "win_back_promo", False)
    expected_a_version = require_int(body, "expected_member_a_version")

    # (4) body well-formed already validated above.

    # (6) referential integrity: distinct, existing members; plan archived n/a here
    if member_a_id == member_b_id:
        raise errors.unprocessable("ERR_SELF_INTRODUCTION")
    member_a = db.members.get(member_a_id)
    member_b = db.members.get(member_b_id)
    if not member_a or not member_b:
        # both parties must be distinct existing members (class 6, 422)
        raise errors.unprocessable("ERR_NOT_INTRODUCTION_PARTY")

    reconcile_member(member_a)
    reconcile_member(member_b)

    # (5) state: a frozen member cannot have new suggestions raised
    if member_a["status"] == "FROZEN" or member_b["status"] == "FROZEN":
        raise errors.conflict("ERR_MEMBER_FROZEN")

    # (7) safety / eligibility
    # eligibility: both ACTIVE with APPROVED screening
    for m in (member_a, member_b):
        if m["status"] != "ACTIVE" or m["screening_decision"] != "APPROVED":
            raise errors.unprocessable("ERR_MEMBER_NOT_ELIGIBLE")

    pref_a = _pref_for(member_a_id)
    pref_b = _pref_for(member_b_id)
    if pref_a is None or pref_b is None:
        # preferences required for mutual satisfaction; absence => mismatch
        raise errors.unprocessable("ERR_PREFERENCE_MISMATCH")

    age_a = age_years(member_a)
    age_b = age_years(member_b)
    gender_ok = (
        gender_satisfies(member_b["gender"], pref_a["seeking_gender"])
        and gender_satisfies(member_a["gender"], pref_b["seeking_gender"])
    )
    age_ok = age_in_band(age_b, pref_a) and age_in_band(age_a, pref_b)
    if not (gender_ok and age_ok):
        raise errors.unprocessable("ERR_PREFERENCE_MISMATCH")

    # dealbreaker: neither party carries a tag appearing in the other's
    # dealbreaker_tags among their own attribute_weights keys
    a_keys = set(pref_a["attribute_weights"].keys())
    b_keys = set(pref_b["attribute_weights"].keys())
    if any(tag in b_keys for tag in pref_a["dealbreaker_tags"]) or \
       any(tag in a_keys for tag in pref_b["dealbreaker_tags"]):
        raise errors.unprocessable("ERR_DEALBREAKER")

    # background flagged
    if _has_flagged_check(member_a_id) or _has_flagged_check(member_b_id):
        raise errors.unprocessable("ERR_BACKGROUND_FLAGGED")

    # (9) compatibility threshold
    score = compatibility_score(member_a, member_b, pref_a, pref_b)
    if score < COMPATIBILITY_THRESHOLD:
        raise errors.unprocessable("ERR_COMPATIBILITY_TOO_LOW")

    # determine base cost (PRD §3.4)
    membership_a = db.memberships.get(member_a.get("active_membership_id"))
    plan_a = db.membership_plans.get(membership_a["plan_id"]) if membership_a else None
    if win_back:
        base_cost = 0
    elif plan_a and plan_a["priority_match_enabled"]:
        base_cost = 2
    else:
        base_cost = 1

    _, remaining_forecast = guarantee_for_member(member_a)

    # (11) guarantee pool sufficiency: unless win-back (cost 0), the actually-
    # consumed cost (capped at the forecast pool, never overdrawing) must not
    # exceed forecast remaining. Because the consume is capped to
    # min(base_cost, forecast), the only way a non-win-back suggestion can be
    # exhausted is an empty pool (forecast == 0): PRD §3.4 says a priority
    # suggestion with one forecast credit "consumes 1 (capped) and leaves 0".
    if not win_back and remaining_forecast <= 0:
        raise errors.guarantee_exhausted()

    # (12) OCC
    if expected_a_version != member_a["version"]:
        raise errors.stale_version()

    # consume credits (capped, never overdraw)
    consumed = min(base_cost, remaining_forecast)
    if win_back:
        consumed = 0

    iid = new_id()
    intro = {
        "id": iid,
        "member_a_id": member_a_id,
        "member_b_id": member_b_id,
        "compatibility_score": float(score),
        "credits_consumed": consumed,
        "a_response": "PENDING",
        "b_response": "PENDING",
        "status": "SUGGESTED",
        "win_back_promo": win_back,
        "_was_mutual": False,
    }
    stamp_create(intro)
    db.introductions[iid] = intro

    # forecast decremented implicitly via aggregation; bump member_a version
    touch(member_a)
    return success_object(serialize_introduction(intro), 201)


@bp.route("/introductions", methods=["GET"])
def list_introductions():
    principal = authenticate()
    require_roles(principal, ALL_ROLES)
    member_a_id = request.args.get("member_a_id")
    member_b_id = request.args.get("member_b_id")
    status = request.args.get("status")
    limit, offset = parse_pagination()
    records = list(db.introductions.values())
    if member_a_id:
        records = [i for i in records if i["member_a_id"] == member_a_id]
    if member_b_id:
        records = [i for i in records if i["member_b_id"] == member_b_id]
    if status:
        records = [i for i in records if i["status"] == status]
    records = sort_by_created(records)
    page, total = paginate(records, limit, offset)
    return success_array([serialize_introduction(i) for i in page], limit, offset, total)


@bp.route("/introductions/<intro_id>", methods=["GET"])
def get_introduction(intro_id):
    principal = authenticate()
    require_roles(principal, ALL_ROLES)
    intro = _get_intro_or_404(intro_id)
    if principal.role == "Member":
        if principal.user_id not in (intro["member_a_id"], intro["member_b_id"]):
            raise errors.forbidden()
    return success_object(serialize_introduction(intro))


# ---------------------------------------------------------------------------
# Respond (PRD §3.5) — quorum-of-two negotiation
# ---------------------------------------------------------------------------
@bp.route("/introductions/<intro_id>/respond", methods=["POST"])
def respond_introduction(intro_id):
    principal = authenticate()
    require_roles(principal, ("Member",))
    intro = _get_intro_or_404(intro_id)
    body = get_json_body()
    response = require_enum(body, "response", ("ACCEPTED", "DECLINED"))
    expected_version = require_int(body, "expected_introduction_version")

    acting_id = principal.user_id
    # (2) ownership: a Member may act only on an introduction they are a party to
    # (PRD §2.1). Per §2.8 the ownership check (ERR_FORBIDDEN, class 2) masks the
    # referential party check (ERR_NOT_INTRODUCTION_PARTY, class 6) because the
    # responder is the acting member itself.
    if acting_id not in (intro["member_a_id"], intro["member_b_id"]):
        raise errors.forbidden()

    member = db.members.get(acting_id)
    if member:
        reconcile_member(member)

    # (5) state checks
    if intro["status"] not in ("SUGGESTED", "ONE_SIDED"):
        raise errors.conflict("ERR_INVALID_INTRODUCTION_STATE")

    is_a = acting_id == intro["member_a_id"]
    prior_response = intro["a_response"] if is_a else intro["b_response"]
    if prior_response != "PENDING":
        raise errors.conflict("ERR_ALREADY_RESPONDED")

    # acting member must be ACTIVE; frozen blocked
    if member and member["status"] == "FROZEN":
        raise errors.conflict("ERR_MEMBER_FROZEN")

    # (12) OCC
    if expected_version != intro["version"]:
        raise errors.stale_version()

    # apply
    if is_a:
        intro["a_response"] = response
    else:
        intro["b_response"] = response

    if response == "DECLINED":
        intro["status"] = "DECLINED"
        # refund: declined excluded from sums automatically (status filter)
        touch(intro)
    else:
        # ACCEPTED
        both_accepted = intro["a_response"] == "ACCEPTED" and intro["b_response"] == "ACCEPTED"
        if both_accepted:
            intro["status"] = "MUTUAL"
            intro["_was_mutual"] = True
            touch(intro)
            # commit credits -> may FULFILL membership (bubble-up)
            member_a = db.members.get(intro["member_a_id"])
            if member_a:
                membership = db.memberships.get(member_a.get("active_membership_id"))
                if membership and membership["status"] == "ACTIVE":
                    committed = committed_consumed_for_member(member_a["id"])
                    if committed >= membership["guaranteed_introductions"]:
                        membership["status"] = "FULFILLED"
                        touch(membership)
        else:
            intro["status"] = "ONE_SIDED"
            touch(intro)
    return success_object(serialize_introduction(intro))


# ---------------------------------------------------------------------------
# Close (PRD §3.5)
# ---------------------------------------------------------------------------
@bp.route("/introductions/<intro_id>/close", methods=["POST"])
def close_introduction_route(intro_id):
    principal = authenticate()
    require_roles(principal, ("Matchmaker",))
    intro = _get_intro_or_404(intro_id)
    if intro["status"] not in ("SUGGESTED", "ONE_SIDED", "MUTUAL"):
        raise errors.conflict("ERR_INVALID_INTRODUCTION_STATE")
    close_introduction(intro)
    return success_object(serialize_introduction(intro))


# ---------------------------------------------------------------------------
# Feedback (PRD §3.6)
# ---------------------------------------------------------------------------
@bp.route("/introductions/<intro_id>/feedback", methods=["POST"])
def submit_feedback(intro_id):
    principal = authenticate()
    require_roles(principal, ("Member",))
    intro = _get_intro_or_404(intro_id)
    body = get_json_body()
    author_member_id = require_str(body, "author_member_id")
    rating = require_int(body, "rating")
    continue_interest = require_bool(body, "continue_interest")
    comments = opt_str(body, "comments", "")
    if rating < 1 or rating > 5:
        raise errors.invalid_request("rating must be 1..5.")

    # ownership: the Member must be a party (and author must be themselves)
    if principal.user_id not in (intro["member_a_id"], intro["member_b_id"]):
        raise errors.forbidden()

    # referential: author must be a party
    if author_member_id not in (intro["member_a_id"], intro["member_b_id"]):
        raise errors.unprocessable("ERR_NOT_INTRODUCTION_PARTY")

    fid = new_id()
    feedback = {
        "id": fid,
        "introduction_id": intro_id,
        "author_member_id": author_member_id,
        "rating": rating,
        "continue_interest": continue_interest,
        "comments": comments,
    }
    stamp_create(feedback)
    db.feedback[fid] = feedback
    return success_object(serialize_feedback(feedback), 201)


@bp.route("/introductions/<intro_id>/feedback", methods=["GET"])
def list_feedback(intro_id):
    principal = authenticate()
    require_roles(principal, ALL_ROLES)
    intro = _get_intro_or_404(intro_id)
    if principal.role == "Member" and principal.user_id not in (intro["member_a_id"], intro["member_b_id"]):
        raise errors.forbidden()
    limit, offset = parse_pagination()
    records = [f for f in db.feedback.values() if f["introduction_id"] == intro_id]
    records = sort_by_created(records)
    page, total = paginate(records, limit, offset)
    return success_array([serialize_feedback(f) for f in page], limit, offset, total)
