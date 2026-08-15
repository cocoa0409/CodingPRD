"""Item endpoints: CRUD, lifecycle actions, security posture actions."""
from flask import Blueprint, request

from db import db, next_seq
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_DUPLICATE_CODE,
    ERR_ITEM_NOT_IN_DRAFT,
    ERR_NOT_ITEM_AUTHOR,
    ERR_STANDARD_NOT_ACTIVE,
    ERR_STALE_VERSION,
    ERR_ITEM_NOT_IN_STATS_REVIEW,
    ERR_ITEM_NOT_OPERATIONAL,
    ERR_ITEM_NOT_EXPOSED,
    ERR_NO_FINAL_STATS,
    ERR_ITEM_STATS_NOT_PASSING,
    ERR_ITEM_ON_ACTIVE_FORM,
)
from middleware import authorized, ALL_ROLES
from response import success_object
from routes.helpers import public, list_response, get_one
from services.common import touch
from services.forms import retire_item, mark_compromised
from services.grants import check_grant, caller_may
from services.review import cascade_item_terminal_variants
from util import new_id, now_ts
from validate import (
    get_body, req_str, opt_str, req_enum, req_int, opt_int, req_obj, opt_obj,
    opt_str_list, require_path_resource, require_body_ref,
)

bp = Blueprint("items", __name__)

ITEM_TYPES = ["MC", "MS", "EBSR", "TE", "CR"]
ACTIVE_FORM_STATUSES = ("ASSEMBLED", "EQUATED", "PUBLISHED")


def _new_item(body, caller):
    program_id = req_str(body, "program_id")
    item_code = req_str(body, "item_code")
    primary_standard_id = req_str(body, "primary_standard_id")
    secondary_standard_ids = opt_str_list(body, "secondary_standard_ids", default=[])
    if len(secondary_standard_ids) > 3:
        raise_error(ERR_INVALID_REQUEST, "secondary_standard_ids may hold at most 3 entries")
    item_type = req_enum(body, "item_type", ITEM_TYPES)
    stimulus_html = req_str(body, "stimulus_html")
    options_json = req_obj(body, "options_json")
    max_score_points = req_int(body, "max_score_points", minimum=1, maximum=6)
    exposure_cap = opt_int(body, "exposure_cap", default=3, minimum=0)

    require_body_ref("assessment_programs", program_id, "program_id")
    require_body_ref("content_standards", primary_standard_id, "primary_standard_id")

    for it in db["items"].values():
        if it["program_id"] == program_id and it["item_code"] == item_code:
            raise_error(ERR_DUPLICATE_CODE, f"item_code {item_code} already exists in program")

    now = now_ts()
    rec = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "program_id": program_id,
        "item_code": item_code,
        "primary_standard_id": primary_standard_id,
        "secondary_standard_ids": secondary_standard_ids,
        "item_type": item_type,
        "stimulus_html": stimulus_html,
        "options_json": options_json,
        "max_score_points": max_score_points,
        "author_user_id": caller.user_id,
        "status": "DRAFT",
        "security_posture": "UNSECURED",
        "content_review_outcome": "PENDING",
        "bias_review_outcome": "PENDING",
        "revision_cycle_count": 0,
        "field_test_attempt_count": 0,
        "operational_exposure_count": 0,
        "exposure_cap": exposure_cap,
        "retired_at": None,
        "retirement_reason": None,
        "p_value_provisional": None,
        "p_value_final": None,
        "point_biserial_provisional": None,
        "point_biserial_final": None,
        "_seq": next_seq(),
    }
    db["items"][rec["id"]] = rec
    return rec


@bp.post("/api/items")
def create_item():
    caller = authorized(["ItemWriter"])
    body = get_body()
    rec = _new_item(body, caller)
    return success_object(public(rec), status=201)


@bp.get("/api/items")
def list_items():
    caller = authorized(ALL_ROLES)
    filters = {
        "program_id": request.args.get("program_id"),
        "primary_standard_id": request.args.get("primary_standard_id"),
        "status": request.args.get("status"),
        "security_posture": request.args.get("security_posture"),
    }

    def hide_secured(rec):
        # SECURED items are hidden from callers lacking an active ITEM_READ grant.
        if rec["security_posture"] != "SECURED":
            return True
        return caller_may(caller, rec["program_id"], "ITEM_READ")

    return list_response("items", filters, exclude=hide_secured)


@bp.get("/api/items/<itemId>")
def get_item(itemId):
    caller = authorized(ALL_ROLES)
    rec = require_path_resource("items", itemId)
    if rec["security_posture"] == "SECURED":
        check_grant(caller, rec["program_id"], "ITEM_READ")
    return get_one(rec)


@bp.put("/api/items/<itemId>")
def update_item(itemId):
    caller = authorized(["ItemWriter"])
    rec = require_path_resource("items", itemId)
    body = get_body()
    if rec["status"] != "DRAFT":
        raise_error(ERR_ITEM_NOT_IN_DRAFT, "item content may only be edited while in DRAFT")
    if rec["author_user_id"] != caller.user_id:
        raise_error(ERR_NOT_ITEM_AUTHOR, "only the item's author may edit it")
    check_grant(caller, rec["program_id"], "ITEM_WRITE")

    if "stimulus_html" in body:
        rec["stimulus_html"] = req_str(body, "stimulus_html")
    if "options_json" in body:
        rec["options_json"] = req_obj(body, "options_json")
    if "max_score_points" in body:
        rec["max_score_points"] = req_int(body, "max_score_points", minimum=1, maximum=6)
    if "primary_standard_id" in body:
        psid = req_str(body, "primary_standard_id")
        require_body_ref("content_standards", psid, "primary_standard_id")
        rec["primary_standard_id"] = psid
    if "secondary_standard_ids" in body:
        ssids = opt_str_list(body, "secondary_standard_ids", default=[])
        if len(ssids) > 3:
            raise_error(ERR_INVALID_REQUEST, "secondary_standard_ids may hold at most 3 entries")
        rec["secondary_standard_ids"] = ssids
    touch(rec)
    return success_object(public(rec))


@bp.post("/api/items/<itemId>/submit")
def submit_item(itemId):
    caller = authorized(["ItemWriter"])
    rec = require_path_resource("items", itemId)
    body = get_body()
    expected = req_int(body, "expected_item_version")
    if expected != rec["version"]:
        raise_error(ERR_STALE_VERSION, "expected_item_version does not match the item's current version")
    if rec["status"] != "DRAFT":
        raise_error(ERR_ITEM_NOT_IN_DRAFT, "item must be in DRAFT to submit")
    if rec["author_user_id"] != caller.user_id:
        raise_error(ERR_NOT_ITEM_AUTHOR, "only the item's author may submit it")
    standard = db["content_standards"].get(rec["primary_standard_id"])
    if (
        standard is None
        or standard["status"] != "ACTIVE"
        or standard["program_id"] != rec["program_id"]
    ):
        raise_error(ERR_STANDARD_NOT_ACTIVE, "primary standard is not an ACTIVE standard in the item's program")
    check_grant(caller, rec["program_id"], "ITEM_WRITE")

    # DRAFT -> SUBMITTED, auto-promoted immediately to CONTENT_REVIEW.
    rec["status"] = "CONTENT_REVIEW"
    rec["content_review_outcome"] = "PENDING"
    rec["bias_review_outcome"] = "PENDING"
    touch(rec)
    return success_object(public(rec))


@bp.post("/api/items/<itemId>/discard")
def discard_item(itemId):
    caller = authorized(["ItemWriter"])
    rec = require_path_resource("items", itemId)
    get_body()
    if rec["status"] != "DRAFT":
        raise_error(ERR_ITEM_NOT_IN_DRAFT, "item must be in DRAFT to discard")
    if rec["author_user_id"] != caller.user_id:
        raise_error(ERR_NOT_ITEM_AUTHOR, "only the item's author may discard it")
    check_grant(caller, rec["program_id"], "ITEM_WRITE")

    rec["status"] = "REJECTED"
    rec["retirement_reason"] = "MANUAL"
    cascade_item_terminal_variants(rec)
    touch(rec)
    return success_object(public(rec))


def _most_recent_final_stat(item_id):
    """Most recent FINAL row by its window's end_utc (creation order breaks ties)."""
    best = None
    best_end = None
    for stat in db["item_statistics"].values():
        if stat["item_id"] != item_id or stat["stats_kind"] != "FINAL":
            continue
        window = db["field_test_windows"].get(stat["window_id"])
        if window is None:
            continue
        end_dt = window["_end_dt"]
        if best_end is None or end_dt > best_end or (end_dt == best_end and stat.get("_seq", 0) > best.get("_seq", 0)):
            best_end = end_dt
            best = stat
    return best


@bp.post("/api/items/<itemId>/approve-operational")
def approve_operational(itemId):
    caller = authorized(["Psychometrician"])
    rec = require_path_resource("items", itemId)
    get_body()
    if rec["status"] != "STATS_REVIEW":
        raise_error(ERR_ITEM_NOT_IN_STATS_REVIEW, "item must be in STATS_REVIEW")
    check_grant(caller, rec["program_id"], "ITEM_WRITE")
    final_stat = _most_recent_final_stat(itemId)
    if final_stat is None:
        raise_error(ERR_NO_FINAL_STATS, "item has no FINAL ItemStatistic row")
    if final_stat["pass_flag"] != "PASS":
        raise_error(ERR_ITEM_STATS_NOT_PASSING, "most recent FINAL ItemStatistic pass_flag is not PASS")

    rec["status"] = "OPERATIONAL"
    touch(rec)
    return success_object(public(rec))


@bp.post("/api/items/<itemId>/retire")
def retire(itemId):
    caller = authorized(["Psychometrician", "SecurityOfficer"])
    rec = require_path_resource("items", itemId)
    get_body()
    program = db["assessment_programs"].get(rec["program_id"])
    check_grant(caller, rec["program_id"], "ITEM_WRITE")

    if caller.role == "Psychometrician":
        if rec["status"] != "STATS_REVIEW":
            raise_error(ERR_ITEM_NOT_IN_STATS_REVIEW, "item must be in STATS_REVIEW for stats-fail retirement")
        final_stat = _most_recent_final_stat(itemId)
        if final_stat is None:
            raise_error(ERR_NO_FINAL_STATS, "item has no FINAL ItemStatistic row")
        if final_stat["pass_flag"] not in ("FAIL_BORDERLINE", "FAIL_SEVERE"):
            raise_error(ERR_ITEM_STATS_NOT_PASSING, "most recent FINAL pass_flag is not FAIL_BORDERLINE/FAIL_SEVERE")
        retire_item(rec, program, "STATISTICAL_FAIL")
    else:  # SecurityOfficer manual retirement from OPERATIONAL
        if rec["status"] != "OPERATIONAL":
            raise_error(ERR_ITEM_NOT_OPERATIONAL, "item must be OPERATIONAL for manual retirement")
        for slot in db["form_item_slots"].values():
            if slot["item_id"] != rec["id"]:
                continue
            form = db["test_forms"].get(slot["form_id"])
            if form is not None and form["status"] in ACTIVE_FORM_STATUSES:
                raise_error(ERR_ITEM_ON_ACTIVE_FORM, "item is referenced by a slot on a non-archived form")
        reason = (
            "OVER_EXPOSED"
            if rec["operational_exposure_count"] >= rec["exposure_cap"]
            else "MANUAL"
        )
        retire_item(rec, program, reason)
    return success_object(public(rec))


@bp.post("/api/items/<itemId>/mark-compromised")
def compromise(itemId):
    caller = authorized(["SecurityOfficer"])
    rec = require_path_resource("items", itemId)
    get_body()
    if rec["security_posture"] != "EXPOSED":
        raise_error(ERR_ITEM_NOT_EXPOSED, "item security_posture must be EXPOSED to mark compromised")
    if rec["status"] != "OPERATIONAL":
        raise_error(ERR_ITEM_NOT_OPERATIONAL, "item must be OPERATIONAL to mark compromised")
    check_grant(caller, rec["program_id"], "ITEM_WRITE")
    program = db["assessment_programs"].get(rec["program_id"])
    mark_compromised(rec, program)
    return success_object(public(rec))
