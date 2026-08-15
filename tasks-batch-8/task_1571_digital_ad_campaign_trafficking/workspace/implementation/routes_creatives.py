"""Routes: creatives (upload, QA loop, tagging, activation, archive)."""
from flask import Blueprint, request

from core import (
    db, envelope_ok, paginate, sorted_items, require_role, ANY_ROLE, get_body,
    req_str, req_int, req_enum,
    err_not_found, err_invalid_state, err_tag_required,
    err_fraud_hold, err_line_item_not_live,
    stamp_new, touch,
)
from domain import creative_view, get_creative, get_li

bp = Blueprint("creatives", __name__)

CREATIVE_ACTIONS = ("SUBMIT_QA", "PASS_QA", "FAIL_QA", "REVISE", "TAG", "ACTIVATE", "ARCHIVE")


@bp.route("/creatives", methods=["POST"])
def create_creative():
    require_role("Trafficker")
    body = get_body()
    li_id = req_str(body, "line_item_id")
    name = req_str(body, "name")
    asset_url = req_str(body, "asset_url")
    width = req_int(body, "width", minimum=1)
    height = req_int(body, "height", minimum=1)
    li = get_li(li_id)
    if li is None:
        raise err_not_found("Line item not found")
    c = {
        "line_item_id": li_id,
        "name": name,
        "asset_url": asset_url,
        "width": width,
        "height": height,
        "ad_tag": None,
        "qa_failure_reason": None,
        "status": "UPLOADED",
    }
    stamp_new(c)
    db.creatives[c["id"]] = c
    return envelope_ok(creative_view(c), status=201)


@bp.route("/creatives", methods=["GET"])
def list_creatives():
    require_role(*ANY_ROLE)
    items = list(db.creatives.values())
    li_id = request.args.get("line_item_id")
    status = request.args.get("status")
    if li_id is not None:
        items = [c for c in items if c["line_item_id"] == li_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    return paginate([creative_view(c) for c in sorted_items(items)])


@bp.route("/creatives/<cid>", methods=["GET"])
def get_one_creative(cid):
    require_role(*ANY_ROLE)
    c = get_creative(cid)
    if c is None:
        raise err_not_found("Creative not found")
    return envelope_ok(creative_view(c), status=200)


@bp.route("/creatives/<cid>/transition", methods=["POST"])
def creative_transition(cid):
    require_role("Trafficker")
    body = get_body()
    action = req_enum(body, "action", CREATIVE_ACTIONS)
    c = get_creative(cid)
    if c is None:
        raise err_not_found("Creative not found")
    status = c["status"]

    if action == "SUBMIT_QA":
        if status != "UPLOADED":
            raise err_invalid_state("SUBMIT_QA requires status UPLOADED")
        c["status"] = "IN_QA"

    elif action == "PASS_QA":
        if status != "IN_QA":
            raise err_invalid_state("PASS_QA requires status IN_QA")
        c["status"] = "QA_PASSED"

    elif action == "FAIL_QA":
        if status != "IN_QA":
            raise err_invalid_state("FAIL_QA requires status IN_QA")
        reason = body.get("qa_failure_reason")
        if not isinstance(reason, str) or not reason.strip():
            raise err_tag_required("FAIL_QA requires a non-empty qa_failure_reason")
        c["qa_failure_reason"] = reason
        c["status"] = "QA_FAILED"

    elif action == "REVISE":
        if status != "QA_FAILED":
            raise err_invalid_state("REVISE requires status QA_FAILED")
        c["qa_failure_reason"] = None
        c["status"] = "IN_QA"

    elif action == "TAG":
        if status != "QA_PASSED":
            raise err_invalid_state("TAG requires status QA_PASSED")
        tag = body.get("ad_tag")
        if not isinstance(tag, str) or not tag.strip():
            raise err_tag_required("TAG requires a non-empty ad_tag")
        c["ad_tag"] = tag
        c["status"] = "TAGGED"

    elif action == "ACTIVATE":
        if status != "TAGGED":
            raise err_invalid_state("ACTIVATE requires status TAGGED")
        li = get_li(c["line_item_id"])
        if li["fraud_posture"] != "CLEAR":
            raise err_fraud_hold()
        if li["status"] != "LIVE":
            raise err_line_item_not_live()
        c["status"] = "LIVE"

    elif action == "ARCHIVE":
        if status == "ARCHIVED":
            raise err_invalid_state("Creative is already ARCHIVED")
        c["status"] = "ARCHIVED"

    touch(c)
    return envelope_ok(creative_view(c), status=200)
