import os
from flask import Flask, request

import errors
from errors import ApiError, err
from response import success, error_response
from db import db, new_common, touch
from middleware import authenticate, require_role, require_veteran_owner
from pagination import parse_pagination, paginate
import util
from util import parse_iso
import serialize
import services
import calculations as calc

app = Flask(__name__)


# ===========================================================================
# Error handling
# ===========================================================================

@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_NOT_FOUND", "Resource not found.", 404)


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_NOT_FOUND", "Method not allowed.", 404)


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    return error_response("ERR_INVALID_REQUEST", f"Unexpected error: {e}", 422)


def get_json():
    """Parse the request JSON body, defaulting to {} for empty bodies on action
    endpoints. Malformed JSON -> ERR_INVALID_REQUEST."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise err(errors.ERR_INVALID_REQUEST, "Malformed JSON body.")
    if body is None:
        return {}
    return body


# ===========================================================================
# Existence helpers (validation priority 3 — ERR_NOT_FOUND)
# ===========================================================================

def fetch_or_404(collection, rid, label="Resource"):
    rec = collection.get(rid)
    if rec is None:
        raise err(errors.ERR_NOT_FOUND, f"{label} not found.")
    return rec


def fetch_body_fk(collection, value, label):
    """Resolve a body-supplied FK (priority 3 existence). value must already be
    a present string; existence failure -> ERR_NOT_FOUND."""
    rec = collection.get(value)
    if rec is None:
        raise err(errors.ERR_NOT_FOUND, f"Referenced {label} does not exist.")
    return rec


# ===========================================================================
# Generic list helper
# ===========================================================================

def do_list(collection, serializer, filters=None):
    limit, offset = parse_pagination()
    items = list(collection.values())
    if filters:
        for field, value in filters.items():
            if value is not None:
                items = [r for r in items if r.get(field) == value]
    page, meta = paginate(items, limit, offset)
    return success([serializer(r) for r in page], status=200, pagination=meta)


# ===========================================================================
# Veteran
# ===========================================================================

@app.route("/veterans", methods=["POST"])
def create_veteran():
    _, role = authenticate()
    require_role(role, {"ClaimsAdmin"})
    body = util.require_body(get_json())

    full_name = util.req_str(body, "full_name", 1, 500)
    file_number = util.req_str(body, "file_number", 1, 500)
    total_days = util.req_int(body, "total_active_duty_days", 0)
    discharged = util.opt_bool(body, "discharged_for_service_disability", False)

    # uniqueness (priority 5): file_number unique across veterans.
    for v in db.veterans.values():
        if v["file_number"] == file_number:
            raise err(errors.ERR_DUPLICATE_FILE_NUMBER, "file_number already exists.")

    rec = new_common()
    rec.update({
        "full_name": full_name,
        "file_number": file_number,
        "total_active_duty_days": total_days,
        "discharged_for_service_disability": discharged,
        "combined_rating_pct": 0,
        "provisional_combined_rating_pct": 0,
        "gi_bill_tier_pct": calc.gi_bill_tier(total_days, discharged),
        "monthly_compensation_cents": 0,
        "voc_rehab_entitlement_months": 48,
        "award_status": "DRAFT",
    })
    db.veterans[rec["id"]] = rec
    return success(serialize.veteran_out(rec), status=201)


@app.route("/veterans/<vid>", methods=["GET"])
def get_veteran(vid):
    user_id, role = authenticate()
    rec = fetch_or_404(db.veterans, vid, "Veteran")
    require_veteran_owner(role, user_id, rec["id"])
    return success(serialize.veteran_out(rec), status=200)


@app.route("/veterans", methods=["GET"])
def list_veterans():
    _, role = authenticate()
    require_role(role, {"ClaimsAdmin", "RatingSpecialist"})
    return do_list(db.veterans, serialize.veteran_out, {
        "file_number": request.args.get("file_number"),
    })


@app.route("/veterans/<vid>", methods=["PATCH"])
def update_veteran(vid):
    _, role = authenticate()
    require_role(role, {"ClaimsAdmin"})
    rec = fetch_or_404(db.veterans, vid, "Veteran")
    body = util.require_body(get_json())

    total_days = util.opt_int(body, "total_active_duty_days", 0, default=None)
    discharged = body.get("discharged_for_service_disability")
    if discharged is not None and not isinstance(discharged, bool):
        raise err(errors.ERR_INVALID_REQUEST, "discharged_for_service_disability must be a boolean.")

    # OCC (priority 7): expected_veteran_version must match (PRD §2.6 lists only
    # activate-award/certify/grant/deny; PATCH is not version-guarded, but the
    # endpoint table declares expected_veteran_version as input). The PRD §2.6
    # explicitly says endpoints not named in that subsection perform no
    # concurrency check, so we do NOT enforce OCC on PATCH.

    if total_days is not None:
        rec["total_active_duty_days"] = total_days
    if discharged is not None:
        rec["discharged_for_service_disability"] = discharged

    rec["gi_bill_tier_pct"] = calc.gi_bill_tier(
        rec["total_active_duty_days"], rec["discharged_for_service_disability"]
    )
    touch(rec)  # recompute is a mutation: refresh updated_at + version
    return success(serialize.veteran_out(rec), status=200)


@app.route("/veterans/<vid>/activate-award", methods=["POST"])
def activate_award(vid):
    _, role = authenticate()
    require_role(role, {"ClaimsAdmin"})
    rec = fetch_or_404(db.veterans, vid, "Veteran")
    body = util.require_body(get_json())
    expected = util.req_int(body, "expected_veteran_version")

    # state (priority 6): activation permitted only from DRAFT or SUSPENDED.
    if rec["award_status"] not in ("DRAFT", "SUSPENDED"):
        raise err(errors.ERR_INVALID_STATE, "Award is not DRAFT or SUSPENDED.")
    # OCC (priority 7)
    if expected != rec["version"]:
        raise err(errors.ERR_STALE_VERSION, "Stale veteran version.")
    # business: compensable rating (priority 16)
    if rec["combined_rating_pct"] <= 0:
        raise err(errors.ERR_NO_COMPENSABLE_RATING, "Veteran has no compensable rating.")

    rec["award_status"] = "ACTIVE"
    touch(rec)
    return success(serialize.veteran_out(rec), status=200)


@app.route("/veterans/<vid>/suspend-award", methods=["POST"])
def suspend_award(vid):
    _, role = authenticate()
    require_role(role, {"ClaimsAdmin"})
    rec = fetch_or_404(db.veterans, vid, "Veteran")
    # state (priority 6): suspension permitted only from ACTIVE.
    if rec["award_status"] != "ACTIVE":
        raise err(errors.ERR_INVALID_STATE, "Award is not ACTIVE.")
    rec["award_status"] = "SUSPENDED"
    touch(rec)
    return success(serialize.veteran_out(rec), status=200)


@app.route("/veterans/<vid>/compensation-summary", methods=["GET"])
def compensation_summary(vid):
    user_id, role = authenticate()
    rec = fetch_or_404(db.veterans, vid, "Veteran")
    require_veteran_owner(role, user_id, rec["id"])
    summary = {
        "combined_rating_pct": rec["combined_rating_pct"],
        "provisional_combined_rating_pct": rec["provisional_combined_rating_pct"],
        "monthly_compensation_cents": rec["monthly_compensation_cents"],
        "gi_bill_tier_pct": rec["gi_bill_tier_pct"],
        "active_dependent_count": services.active_dependent_count(rec["id"]),
        "voc_rehab_entitlement_months": rec["voc_rehab_entitlement_months"],
    }
    return success(summary, status=200)


# ===========================================================================
# Dependent
# ===========================================================================

@app.route("/veterans/<vid>/dependents", methods=["POST"])
def add_dependent(vid):
    user_id, role = authenticate()
    require_role(role, {"ClaimsAdmin", "Veteran"})
    # ownership (priority 2) needs the veteran id from the path.
    require_veteran_owner(role, user_id, vid)
    veteran = fetch_or_404(db.veterans, vid, "Veteran")
    body = util.require_body(get_json())

    relationship = util.req_enum(body, "relationship", {"SPOUSE", "CHILD", "PARENT"})
    in_school = util.opt_bool(body, "in_school_18_to_23", False)

    rec = new_common(with_version=False)
    rec.update({
        "veteran_id": vid,
        "relationship": relationship,
        "in_school_18_to_23": in_school,
        "status": "ACTIVE",
    })
    db.dependents[rec["id"]] = rec

    # recompute compensation + bump veteran version (PRD §3.2).
    services.recompute_monthly_compensation(veteran)
    touch(veteran)
    return success(serialize.dependent_out(rec), status=201)


@app.route("/veterans/<vid>/dependents", methods=["GET"])
def list_veteran_dependents(vid):
    user_id, role = authenticate()
    require_role(role, {"ClaimsAdmin", "RatingSpecialist", "Veteran"})
    require_veteran_owner(role, user_id, vid)
    fetch_or_404(db.veterans, vid, "Veteran")
    status = request.args.get("status")
    return do_list(db.dependents, serialize.dependent_out, {
        "veteran_id": vid,
        "status": status,
    })


@app.route("/dependents/<did>", methods=["GET"])
def get_dependent(did):
    user_id, role = authenticate()
    rec = fetch_or_404(db.dependents, did, "Dependent")
    require_veteran_owner(role, user_id, rec["veteran_id"])
    return success(serialize.dependent_out(rec), status=200)


@app.route("/dependents", methods=["GET"])
def list_dependents():
    user_id, role = authenticate()
    require_role(role, {"ClaimsAdmin", "RatingSpecialist", "Veteran"})
    veteran_id = request.args.get("veteran_id")
    # A Veteran may only list their own dependents.
    if role == "Veteran":
        require_veteran_owner(role, user_id, veteran_id if veteran_id else user_id)
        veteran_id = user_id
    return do_list(db.dependents, serialize.dependent_out, {
        "veteran_id": veteran_id,
        "status": request.args.get("status"),
    })


@app.route("/veterans/<vid>/dependents/<did>/remove", methods=["POST"])
def remove_dependent(vid, did):
    user_id, role = authenticate()
    require_role(role, {"ClaimsAdmin", "Veteran"})
    require_veteran_owner(role, user_id, vid)
    # left-to-right existence (priority 3): veteran first, then dependent.
    veteran = fetch_or_404(db.veterans, vid, "Veteran")
    dep = fetch_or_404(db.dependents, did, "Dependent")
    # nested ownership: dependent must belong to this veteran.
    if dep["veteran_id"] != vid:
        raise err(errors.ERR_NOT_FOUND, "Dependent does not belong to this veteran.")

    dep["status"] = "REMOVED"
    services.recompute_monthly_compensation(veteran)
    touch(veteran)
    return success(serialize.dependent_out(dep), status=200)


# ===========================================================================
# Claim
# ===========================================================================

@app.route("/claims", methods=["POST"])
def create_claim():
    user_id, role = authenticate()
    require_role(role, {"ClaimsAdmin", "Veteran"})
    body = util.require_body(get_json())

    veteran_id = body.get("veteran_id")
    if not isinstance(veteran_id, str) or not veteran_id:
        raise err(errors.ERR_INVALID_REQUEST, "veteran_id must be a string.")
    # ownership (priority 2) precedes existence (priority 3): a Veteran may only
    # file a claim under their own id.
    require_veteran_owner(role, user_id, veteran_id)
    fetch_body_fk(db.veterans, veteran_id, "veteran")

    claim_type = util.req_enum(body, "claim_type", {"ORIGINAL", "INCREASE", "SECONDARY"})
    received_date = util.req_datetime(body, "received_date")

    rec = new_common()
    rec.update({
        "veteran_id": veteran_id,
        "claim_type": claim_type,
        "received_date": body["received_date"],
        "status": "SUBMITTED",
        "remand_count": 0,
    })
    db.claims[rec["id"]] = rec
    return success(serialize.claim_out(rec), status=201)


@app.route("/claims/<cid>", methods=["GET"])
def get_claim(cid):
    user_id, role = authenticate()
    rec = fetch_or_404(db.claims, cid, "Claim")
    require_veteran_owner(role, user_id, rec["veteran_id"])
    return success(serialize.claim_out(rec), status=200)


@app.route("/claims", methods=["GET"])
def list_claims():
    user_id, role = authenticate()
    require_role(role, {"ClaimsAdmin", "RatingSpecialist", "Veteran"})
    veteran_id = request.args.get("veteran_id")
    if role == "Veteran":
        require_veteran_owner(role, user_id, veteran_id if veteran_id else user_id)
        veteran_id = user_id
    return do_list(db.claims, serialize.claim_out, {
        "veteran_id": veteran_id,
        "status": request.args.get("status"),
    })


@app.route("/claims/<cid>/open-development", methods=["POST"])
def open_development(cid):
    _, role = authenticate()
    require_role(role, {"ClaimsAdmin"})
    rec = fetch_or_404(db.claims, cid, "Claim")
    # state (priority 6): permitted from SUBMITTED or REMANDED.
    if rec["status"] not in ("SUBMITTED", "REMANDED"):
        raise err(errors.ERR_INVALID_STATE, "Claim is not SUBMITTED or REMANDED.")
    # business (priority 8): at least one condition references this claim.
    conds = services.conditions_for_claim(cid)
    if len(conds) == 0:
        raise err(errors.ERR_CLAIM_HAS_NO_CONDITIONS, "Claim has no conditions.")
    rec["status"] = "DEVELOPMENT"
    touch(rec)
    return success(serialize.claim_out(rec), status=200)


@app.route("/claims/<cid>/rate", methods=["POST"])
def rate_claim(cid):
    _, role = authenticate()
    require_role(role, {"RatingSpecialist"})
    rec = fetch_or_404(db.claims, cid, "Claim")
    # state (priority 6)
    if rec["status"] != "DEVELOPMENT":
        raise err(errors.ERR_INVALID_STATE, "Claim is not in DEVELOPMENT.")
    # business (priority 9): every condition must carry a valid proposed rating.
    conds = services.conditions_for_claim(cid)
    for c in conds:
        pr = c["proposed_rating_pct"]
        if pr is None or not isinstance(pr, int) or pr < 0 or pr > 100 or pr % 10 != 0:
            raise err(errors.ERR_CONDITION_UNRATED, "A condition lacks a valid proposed rating.")

    rec["status"] = "RATED"
    touch(rec)
    # refresh provisional combined rating (provisional variant).
    veteran = db.veterans.get(rec["veteran_id"])
    if veteran is not None:
        services.recompute_provisional_rating(veteran, rated_claim_id=cid)
        touch(veteran)
    return success(serialize.claim_out(rec), status=200)


@app.route("/claims/<cid>/grant", methods=["POST"])
def grant_claim(cid):
    _, role = authenticate()
    require_role(role, {"ClaimsAdmin"})
    rec = fetch_or_404(db.claims, cid, "Claim")
    body = util.require_body(get_json())
    expected = util.req_int(body, "expected_claim_version")
    # state (priority 6)
    if rec["status"] != "RATED":
        raise err(errors.ERR_INVALID_STATE, "Claim is not RATED.")
    # OCC (priority 7)
    if expected != rec["version"]:
        raise err(errors.ERR_STALE_VERSION, "Stale claim version.")

    # Cascade in order (PRD §3.4).
    conds = services.conditions_for_claim(cid)
    for c in conds:
        c["service_connection"] = "SERVICE_CONNECTED"
        c["final_rating_pct"] = c["proposed_rating_pct"]
        touch(c)
    rec["status"] = "GRANTED"

    veteran = db.veterans.get(rec["veteran_id"])
    if veteran is not None:
        services.recompute_combined_rating(veteran)        # hop 1->2
        services.recompute_monthly_compensation(veteran)   # hop 2->3
        services.recompute_provisional_rating(veteran)
        touch(veteran)

    touch(rec)  # increments Claim.version by 1
    return success(serialize.claim_out(rec), status=200)


@app.route("/claims/<cid>/deny", methods=["POST"])
def deny_claim(cid):
    _, role = authenticate()
    require_role(role, {"ClaimsAdmin"})
    rec = fetch_or_404(db.claims, cid, "Claim")
    body = util.require_body(get_json())
    expected = util.req_int(body, "expected_claim_version")
    # state (priority 6)
    if rec["status"] != "RATED":
        raise err(errors.ERR_INVALID_STATE, "Claim is not RATED.")
    # OCC (priority 7)
    if expected != rec["version"]:
        raise err(errors.ERR_STALE_VERSION, "Stale claim version.")

    conds = services.conditions_for_claim(cid)
    for c in conds:
        c["service_connection"] = "NOT_CONNECTED"
        c["final_rating_pct"] = 0
        touch(c)
    rec["status"] = "DENIED"

    veteran = db.veterans.get(rec["veteran_id"])
    if veteran is not None:
        services.recompute_provisional_rating(veteran)
        touch(veteran)

    touch(rec)  # increments Claim.version by 1
    return success(serialize.claim_out(rec), status=200)


@app.route("/claims/<cid>/remand", methods=["POST"])
def remand_claim(cid):
    _, role = authenticate()
    require_role(role, {"ClaimsAdmin"})
    rec = fetch_or_404(db.claims, cid, "Claim")
    # state (priority 6): permitted from RATED or DENIED.
    if rec["status"] not in ("RATED", "DENIED"):
        raise err(errors.ERR_INVALID_STATE, "Claim is not RATED or DENIED.")
    # appeal cap (priority 10)
    if rec["remand_count"] >= calc.MAX_REMANDS:
        raise err(errors.ERR_APPEAL_EXHAUSTED, "Appeal rounds exhausted.")

    from_denied = rec["status"] == "DENIED"
    rec["status"] = "REMANDED"
    rec["remand_count"] += 1

    if from_denied:
        # reopen every condition for fresh re-adjudication.
        conds = services.conditions_for_claim(cid)
        for c in conds:
            c["service_connection"] = "PROPOSED"
            c["final_rating_pct"] = 0
            touch(c)
        veteran = db.veterans.get(rec["veteran_id"])
        if veteran is not None:
            services.recompute_combined_rating(veteran)
            services.recompute_monthly_compensation(veteran)
            services.recompute_provisional_rating(veteran)
            touch(veteran)

    touch(rec)
    return success(serialize.claim_out(rec), status=200)


@app.route("/claims/<cid>/close", methods=["POST"])
def close_claim(cid):
    _, role = authenticate()
    require_role(role, {"ClaimsAdmin"})
    rec = fetch_or_404(db.claims, cid, "Claim")
    # state (priority 6): permitted from GRANTED or DENIED.
    if rec["status"] not in ("GRANTED", "DENIED"):
        raise err(errors.ERR_INVALID_STATE, "Claim is not GRANTED or DENIED.")
    rec["status"] = "CLOSED"
    touch(rec)
    return success(serialize.claim_out(rec), status=200)


# ===========================================================================
# Condition
# ===========================================================================

@app.route("/claims/<cid>/conditions", methods=["POST"])
def add_condition(cid):
    _, role = authenticate()
    require_role(role, {"ClaimsAdmin", "RatingSpecialist"})
    # left-to-right existence (priority 3): claim first.
    claim = fetch_or_404(db.claims, cid, "Claim")
    body = util.require_body(get_json())

    veteran_id = body.get("veteran_id")
    if not isinstance(veteran_id, str) or not veteran_id:
        raise err(errors.ERR_INVALID_REQUEST, "veteran_id must be a string.")
    fetch_body_fk(db.veterans, veteran_id, "veteran")

    diagnostic_code = util.req_str(body, "diagnostic_code", 1, 500)
    body_side = util.opt_enum(body, "body_side", {"LEFT", "RIGHT", "NONE"}, "NONE")
    is_extremity = util.opt_bool(body, "is_extremity", False)
    proposed = util.req_int(body, "proposed_rating_pct", 0, 100)
    if proposed % 10 != 0:
        raise err(errors.ERR_INVALID_REQUEST, "proposed_rating_pct must be a multiple of 10.")

    rec = new_common()
    rec.update({
        "veteran_id": veteran_id,
        "claim_id": cid,
        "diagnostic_code": diagnostic_code,
        "body_side": body_side,
        "is_extremity": is_extremity,
        "proposed_rating_pct": proposed,
        "final_rating_pct": 0,
        "service_connection": "PROPOSED",
    })
    db.conditions[rec["id"]] = rec
    return success(serialize.condition_out(rec), status=201)


@app.route("/conditions", methods=["GET"])
def list_conditions():
    user_id, role = authenticate()
    require_role(role, {"ClaimsAdmin", "RatingSpecialist", "Veteran"})
    veteran_id = request.args.get("veteran_id")
    if role == "Veteran":
        require_veteran_owner(role, user_id, veteran_id if veteran_id else user_id)
        veteran_id = user_id
    return do_list(db.conditions, serialize.condition_out, {
        "veteran_id": veteran_id,
        "claim_id": request.args.get("claim_id"),
        "service_connection": request.args.get("service_connection"),
    })


@app.route("/conditions/<cid>", methods=["GET"])
def get_condition(cid):
    user_id, role = authenticate()
    rec = fetch_or_404(db.conditions, cid, "Condition")
    require_veteran_owner(role, user_id, rec["veteran_id"])
    return success(serialize.condition_out(rec), status=200)


@app.route("/conditions/<cid>", methods=["PATCH"])
def update_condition(cid):
    _, role = authenticate()
    require_role(role, {"RatingSpecialist"})
    rec = fetch_or_404(db.conditions, cid, "Condition")
    body = util.require_body(get_json())

    # state (priority 6): permitted only while the parent claim is in DEVELOPMENT.
    claim = db.claims.get(rec["claim_id"])
    if claim is None or claim["status"] != "DEVELOPMENT":
        raise err(errors.ERR_INVALID_STATE, "Parent claim is not in DEVELOPMENT.")

    if "proposed_rating_pct" in body and body["proposed_rating_pct"] is not None:
        proposed = util.req_int(body, "proposed_rating_pct", 0, 100)
        if proposed % 10 != 0:
            raise err(errors.ERR_INVALID_REQUEST, "proposed_rating_pct must be a multiple of 10.")
        rec["proposed_rating_pct"] = proposed
    if "body_side" in body and body["body_side"] is not None:
        rec["body_side"] = util.req_enum(body, "body_side", {"LEFT", "RIGHT", "NONE"})
    if "is_extremity" in body and body["is_extremity"] is not None:
        rec["is_extremity"] = util.req_bool(body, "is_extremity")

    touch(rec)
    return success(serialize.condition_out(rec), status=200)


# ===========================================================================
# School
# ===========================================================================

@app.route("/schools", methods=["POST"])
def create_school():
    _, role = authenticate()
    require_role(role, {"ClaimsAdmin"})
    body = util.require_body(get_json())

    name = util.req_str(body, "name", 1, 500)
    is_public = util.req_bool(body, "is_public")
    rate = util.req_int(body, "monthly_housing_rate_cents", 0)
    yr_participant = util.opt_bool(body, "yellow_ribbon_participant", False)
    yr_max = util.opt_int(body, "yellow_ribbon_max_contribution_cents", 0, default=0)
    yr_slots = util.opt_int(body, "yellow_ribbon_slots_total", 0, default=0)

    rec = new_common()
    rec.update({
        "name": name,
        "is_public": is_public,
        "yellow_ribbon_participant": yr_participant,
        "yellow_ribbon_max_contribution_cents": yr_max,
        "yellow_ribbon_slots_total": yr_slots,
        "yellow_ribbon_slots_used": 0,
        "monthly_housing_rate_cents": rate,
    })
    db.schools[rec["id"]] = rec
    return success(serialize.school_out(rec), status=201)


@app.route("/schools/<sid>", methods=["GET"])
def get_school(sid):
    authenticate()
    rec = fetch_or_404(db.schools, sid, "School")
    return success(serialize.school_out(rec), status=200)


# ===========================================================================
# Enrollment
# ===========================================================================

@app.route("/enrollments", methods=["POST"])
def create_enrollment():
    user_id, role = authenticate()
    require_role(role, {"Veteran", "SchoolCertifyingOfficial"})
    body = util.require_body(get_json())

    veteran_id = body.get("veteran_id")
    if not isinstance(veteran_id, str) or not veteran_id:
        raise err(errors.ERR_INVALID_REQUEST, "veteran_id must be a string.")
    # ownership (priority 2) precedes existence: a Veteran submits only their own.
    require_veteran_owner(role, user_id, veteran_id)
    veteran = fetch_body_fk(db.veterans, veteran_id, "veteran")

    school_id = body.get("school_id")
    if not isinstance(school_id, str) or not school_id:
        raise err(errors.ERR_INVALID_REQUEST, "school_id must be a string.")
    school = fetch_body_fk(db.schools, school_id, "school")

    term_start = util.req_datetime(body, "term_start")
    term_end = util.req_datetime(body, "term_end")
    credit_hours = util.req_number(body, "credit_hours", 0, strict_min=True)
    full_time = util.req_number(body, "full_time_credit_hours", 0, strict_min=True)
    tuition = util.opt_int(body, "tuition_charged_cents", 0, default=0)
    requests_yr = util.opt_bool(body, "requests_yellow_ribbon", False)

    rop = calc.rate_of_pursuit(credit_hours, full_time)
    est_mha = calc.housing_allowance(
        school["monthly_housing_rate_cents"], veteran["gi_bill_tier_pct"], rop
    )

    rec = new_common()
    rec.update({
        "veteran_id": veteran_id,
        "school_id": school_id,
        "term_start": body["term_start"],
        "term_end": body["term_end"],
        "credit_hours": credit_hours,
        "full_time_credit_hours": full_time,
        "tuition_charged_cents": tuition,
        "requests_yellow_ribbon": requests_yr,
        "rate_of_pursuit_pct": rop,
        "monthly_housing_allowance_cents": 0,
        "estimated_mha_cents": est_mha,
        "yellow_ribbon_match_cents": 0,
        "status": "SUBMITTED",
    })
    db.enrollments[rec["id"]] = rec
    return success(serialize.enrollment_out(rec), status=201)


@app.route("/enrollments/<eid>", methods=["GET"])
def get_enrollment(eid):
    user_id, role = authenticate()
    rec = fetch_or_404(db.enrollments, eid, "Enrollment")
    require_veteran_owner(role, user_id, rec["veteran_id"])
    return success(serialize.enrollment_out(rec), status=200)


@app.route("/enrollments", methods=["GET"])
def list_enrollments():
    user_id, role = authenticate()
    require_role(role, {"ClaimsAdmin", "RatingSpecialist", "Veteran", "SchoolCertifyingOfficial"})
    veteran_id = request.args.get("veteran_id")
    if role == "Veteran":
        require_veteran_owner(role, user_id, veteran_id if veteran_id else user_id)
        veteran_id = user_id
    return do_list(db.enrollments, serialize.enrollment_out, {
        "veteran_id": veteran_id,
        "school_id": request.args.get("school_id"),
        "status": request.args.get("status"),
    })


def _intervals_overlap(a_start, a_end, b_start, b_end):
    """Half-open intervals [start, end). They overlap iff they share interior
    time: a_start < b_end and b_start < a_end (touching endpoints do not
    overlap) (PRD §3.12)."""
    return a_start < b_end and b_start < a_end


@app.route("/enrollments/<eid>/certify", methods=["POST"])
def certify_enrollment(eid):
    _, role = authenticate()
    require_role(role, {"SchoolCertifyingOfficial"})
    rec = fetch_or_404(db.enrollments, eid, "Enrollment")
    body = util.require_body(get_json())
    expected = util.req_int(body, "expected_enrollment_version")

    # state (priority 6)
    if rec["status"] != "SUBMITTED":
        raise err(errors.ERR_INVALID_STATE, "Enrollment is not SUBMITTED.")
    # OCC (priority 7) — checked before the remaining business guards per §3.15.
    if expected != rec["version"]:
        raise err(errors.ERR_STALE_VERSION, "Stale enrollment version.")

    veteran = db.veterans.get(rec["veteran_id"])
    school = db.schools.get(rec["school_id"])

    # GI Bill eligibility (priority 11)
    if veteran is None or veteran["gi_bill_tier_pct"] <= 0:
        raise err(errors.ERR_NO_GI_BILL_ELIGIBILITY, "Veteran is not GI Bill eligible.")

    # term overlap with any other CERTIFIED enrollment for same veteran (priority 12)
    my_start = parse_iso(rec["term_start"])
    my_end = parse_iso(rec["term_end"])
    for other in db.enrollments.values():
        if other["id"] == rec["id"]:
            continue
        if other["veteran_id"] != rec["veteran_id"]:
            continue
        if other["status"] != "CERTIFIED":
            continue
        o_start = parse_iso(other["term_start"])
        o_end = parse_iso(other["term_end"])
        if _intervals_overlap(my_start, my_end, o_start, o_end):
            raise err(errors.ERR_ENROLLMENT_OVERLAP, "Term overlaps an existing CERTIFIED enrollment.")

    # Yellow Ribbon availability (priority 13)
    yr_granted = False
    if rec["requests_yellow_ribbon"]:
        if not school["yellow_ribbon_participant"] or \
                school["yellow_ribbon_slots_used"] >= school["yellow_ribbon_slots_total"]:
            raise err(errors.ERR_YELLOW_RIBBON_UNAVAILABLE, "No Yellow Ribbon slot available.")
        yr_granted = True

    # All guards passed — apply side effects.
    rec["status"] = "CERTIFIED"
    rec["rate_of_pursuit_pct"] = calc.rate_of_pursuit(rec["credit_hours"], rec["full_time_credit_hours"])
    rec["monthly_housing_allowance_cents"] = calc.housing_allowance(
        school["monthly_housing_rate_cents"], veteran["gi_bill_tier_pct"], rec["rate_of_pursuit_pct"]
    )
    if yr_granted:
        rec["yellow_ribbon_match_cents"] = calc.yellow_ribbon_match(
            rec["tuition_charged_cents"], school["yellow_ribbon_max_contribution_cents"],
            veteran["gi_bill_tier_pct"]
        )
        school["yellow_ribbon_slots_used"] += 1
        rec["_yr_slot_consumed"] = True
        touch(school)
    touch(rec)
    return success(serialize.enrollment_out(rec), status=200)


@app.route("/enrollments/<eid>/complete", methods=["POST"])
def complete_enrollment(eid):
    _, role = authenticate()
    require_role(role, {"SchoolCertifyingOfficial"})
    rec = fetch_or_404(db.enrollments, eid, "Enrollment")
    if rec["status"] != "CERTIFIED":
        raise err(errors.ERR_INVALID_STATE, "Enrollment is not CERTIFIED.")
    rec["status"] = "COMPLETED"
    touch(rec)
    return success(serialize.enrollment_out(rec), status=200)


@app.route("/enrollments/<eid>/cancel", methods=["POST"])
def cancel_enrollment(eid):
    user_id, role = authenticate()
    require_role(role, {"Veteran"})
    rec = fetch_or_404(db.enrollments, eid, "Enrollment")
    require_veteran_owner(role, user_id, rec["veteran_id"])
    # state (priority 6): permitted only from SUBMITTED or CERTIFIED.
    if rec["status"] not in ("SUBMITTED", "CERTIFIED"):
        raise err(errors.ERR_INVALID_STATE, "Enrollment is not SUBMITTED or CERTIFIED.")

    from_certified = rec["status"] == "CERTIFIED"
    rec["status"] = "CANCELLED"
    if from_certified:
        rec["monthly_housing_allowance_cents"] = 0
        # restore Yellow Ribbon slot if one was consumed.
        if rec["yellow_ribbon_match_cents"] > 0:
            school = db.schools.get(rec["school_id"])
            if school is not None:
                school["yellow_ribbon_slots_used"] = max(0, school["yellow_ribbon_slots_used"] - 1)
                touch(school)
            rec["yellow_ribbon_match_cents"] = 0
        rec["_yr_slot_consumed"] = False
    touch(rec)
    return success(serialize.enrollment_out(rec), status=200)


# ===========================================================================
# VocRehabPlan
# ===========================================================================

@app.route("/voc-rehab-plans", methods=["POST"])
def create_voc_rehab_plan():
    user_id, role = authenticate()
    require_role(role, {"ClaimsAdmin", "Veteran"})
    body = util.require_body(get_json())

    veteran_id = body.get("veteran_id")
    if not isinstance(veteran_id, str) or not veteran_id:
        raise err(errors.ERR_INVALID_REQUEST, "veteran_id must be a string.")
    require_veteran_owner(role, user_id, veteran_id)
    fetch_body_fk(db.veterans, veteran_id, "veteran")

    planned_months = util.req_number(body, "planned_months", 0, strict_min=True)
    track = util.req_enum(body, "track",
                          {"REEMPLOYMENT", "EMPLOYMENT_THROUGH_LONG_TERM", "SELF_EMPLOYMENT"})

    rec = new_common()
    rec.update({
        "veteran_id": veteran_id,
        "planned_months": planned_months,
        "track": track,
        "status": "PROPOSED",
    })
    db.voc_rehab_plans[rec["id"]] = rec
    return success(serialize.voc_rehab_plan_out(rec), status=201)


@app.route("/voc-rehab-plans/<pid>", methods=["GET"])
def get_voc_rehab_plan(pid):
    user_id, role = authenticate()
    rec = fetch_or_404(db.voc_rehab_plans, pid, "VocRehabPlan")
    require_veteran_owner(role, user_id, rec["veteran_id"])
    return success(serialize.voc_rehab_plan_out(rec), status=200)


@app.route("/voc-rehab-plans", methods=["GET"])
def list_voc_rehab_plans():
    user_id, role = authenticate()
    require_role(role, {"ClaimsAdmin", "Veteran"})
    veteran_id = request.args.get("veteran_id")
    if role == "Veteran":
        require_veteran_owner(role, user_id, veteran_id if veteran_id else user_id)
        veteran_id = user_id
    return do_list(db.voc_rehab_plans, serialize.voc_rehab_plan_out, {
        "veteran_id": veteran_id,
        "status": request.args.get("status"),
    })


@app.route("/voc-rehab-plans/<pid>/approve", methods=["POST"])
def approve_voc_rehab_plan(pid):
    _, role = authenticate()
    require_role(role, {"ClaimsAdmin"})
    rec = fetch_or_404(db.voc_rehab_plans, pid, "VocRehabPlan")
    # state (priority 6)
    if rec["status"] != "PROPOSED":
        raise err(errors.ERR_INVALID_STATE, "Plan is not PROPOSED.")
    veteran = db.veterans.get(rec["veteran_id"])
    # ineligible rating (priority 14)
    if veteran is None or veteran["combined_rating_pct"] < calc.VOC_REHAB_MIN_RATING:
        raise err(errors.ERR_VOC_REHAB_INELIGIBLE, "Veteran does not meet the minimum rating.")
    # entitlement exhausted (priority 15)
    if rec["planned_months"] > veteran["voc_rehab_entitlement_months"]:
        raise err(errors.ERR_ENTITLEMENT_EXHAUSTED, "Planned months exceed remaining entitlement.")

    rec["status"] = "APPROVED"
    veteran["voc_rehab_entitlement_months"] -= rec["planned_months"]
    touch(veteran)
    touch(rec)
    return success(serialize.voc_rehab_plan_out(rec), status=200)


@app.route("/voc-rehab-plans/<pid>/complete", methods=["POST"])
def complete_voc_rehab_plan(pid):
    _, role = authenticate()
    require_role(role, {"ClaimsAdmin"})
    rec = fetch_or_404(db.voc_rehab_plans, pid, "VocRehabPlan")
    if rec["status"] != "APPROVED":
        raise err(errors.ERR_INVALID_STATE, "Plan is not APPROVED.")
    rec["status"] = "COMPLETED"
    touch(rec)
    return success(serialize.voc_rehab_plan_out(rec), status=200)


@app.route("/voc-rehab-plans/<pid>/reject", methods=["POST"])
def reject_voc_rehab_plan(pid):
    _, role = authenticate()
    require_role(role, {"ClaimsAdmin"})
    rec = fetch_or_404(db.voc_rehab_plans, pid, "VocRehabPlan")
    if rec["status"] != "PROPOSED":
        raise err(errors.ERR_INVALID_STATE, "Plan is not PROPOSED.")
    rec["status"] = "REJECTED"
    touch(rec)
    return success(serialize.voc_rehab_plan_out(rec), status=200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))

    # Avoid a startup-blocking DNS timeout. Both Flask's app.run() banner
    # (get_interface_ip) and the stdlib HTTPServer.server_bind() (socket.getfqdn)
    # try to resolve this host's .local name when binding to 0.0.0.0. On a machine
    # whose hostname does not resolve, that lookup blocks ~5s on a DNS timeout
    # BEFORE the listener is serving. Under per-test-server isolation the runner
    # only grants a 15s restart budget, so that 5s tax — compounded by the CPU
    # contention of 8 concurrent rounds — pushes some restarts past the deadline,
    # producing "could not be restarted" errors. socket.getfqdn is only used to
    # populate a cosmetic server_name, so short-circuit it to keep bind instant.
    import socket as _socket

    _socket.getfqdn = lambda name="": (name or "localhost")

    from werkzeug.serving import make_server

    httpd = make_server("0.0.0.0", port, app, threaded=True)
    httpd.serve_forever()
