"""StayOrder routes: filing (with auto-postponement side effect) and release.

Filing on a terminal case -> ERR_INVALID_CASE_STATE. A SCHEDULED sale at
filing time is auto-postponed exactly 30 days (consuming one of the notice's
three postponements); when the count is already 3 the sale and the NOTS are
VOIDED and the case rewinds SALE_SCHEDULED -> NOD_RECORDED (PRD §3.7).
"""
from flask import Blueprint, request

import db
from db import stamp_new, touch, now_iso
from errors import err_invalid_case_state, err_stay_not_active, err_invalid_request
from middleware import require_roles
from response import success_object, success_list, parse_pagination
from services.domain import (get_case, get_stay, view, case_stays,
                             recompute_hold, TERMINAL_CASE_STATES)
from services.validate import get_body, check_unknown, req_enum, req_string, req_datetime_raw
from services.workflow import apply_stay_auto_postponement

bp = Blueprint("stays", __name__)

STAY_TYPES = ("BANKRUPTCY_CHAPTER_7", "BANKRUPTCY_CHAPTER_11",
              "BANKRUPTCY_CHAPTER_13", "LITIGATION_HOLD")


@bp.route("/api/foreclosure-cases/<case_id>/stay-orders", methods=["POST"], strict_slashes=False)
@require_roles("CaseManager")
def file_stay(user_id, role, case_id):
    case = get_case(case_id)
    body = get_body()
    check_unknown(body, {"stay_type", "court_case_number", "filed_at"})
    stay_type = req_enum(body, "stay_type", STAY_TYPES)
    court_case_number = req_string(body, "court_case_number")
    filed_raw, filed_at = req_datetime_raw(body, "filed_at")
    # clock consistency (§2.5): filed_at must not lie in the future
    if filed_at > db.now_dt():
        raise err_invalid_request("filed_at must not lie in the future")
    if case["lifecycle_status"] in TERMINAL_CASE_STATES:
        raise err_invalid_case_state("stay filing requires a non-terminal case")
    stay = {
        "foreclosure_case_id": case["id"],
        "stay_type": stay_type,
        "court_case_number": court_case_number,
        "filed_at": filed_raw,
        "status": "ACTIVE",
        "released_at": None,
        "release_court_order_reference": None,
    }
    stamp_new(stay)
    db.stay_orders[stay["id"]] = stay
    recompute_hold(case)
    # mechanical side effect on a waiting sale (consumes a postponement or
    # voids the notice machinery on overflow)
    apply_stay_auto_postponement(case, stay_type)
    touch(case)
    return success_object(view(stay), status=201)


@bp.route("/api/foreclosure-cases/<case_id>/stay-orders", methods=["GET"], strict_slashes=False)
@require_roles("TrusteeAdmin", "CaseManager", "Beneficiary")
def list_stays(user_id, role, case_id):
    get_case(case_id)
    items = case_stays(case_id)
    status = request.args.get("status")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    limit, offset = parse_pagination(request.args)
    page = [view(s) for s in items[offset:offset + limit]]
    return success_list(page, limit, offset, len(items))


@bp.route("/api/stay-orders/<stay_id>/release", methods=["POST"], strict_slashes=False)
@require_roles("CaseManager")
def release_stay(user_id, role, stay_id):
    stay = get_stay(stay_id)
    body = get_body()
    check_unknown(body, {"release_court_order_reference"})
    reference = req_string(body, "release_court_order_reference")
    if stay["status"] != "ACTIVE":
        raise err_stay_not_active()
    stay["status"] = "RELEASED"
    stay["released_at"] = now_iso()
    stay["release_court_order_reference"] = reference
    touch(stay)
    case = get_case(stay["foreclosure_case_id"])
    recompute_hold(case)
    touch(case)
    return success_object(view(stay))
