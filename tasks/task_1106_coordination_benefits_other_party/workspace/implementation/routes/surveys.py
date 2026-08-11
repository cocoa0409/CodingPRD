"""Member survey endpoints."""

from datetime import timedelta

from flask import Blueprint, request

from db import stores, now_dt, now_iso, iso_fmt, new_id
from errors import (
    raise_err, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_SURVEY_EXPIRED,
    ERR_MEMBER_DISENROLLED, ERR_INVALID_REQUEST,
)
from helpers import base_record, touch, get_or_404, body, req_str, paginate
from middleware import require_roles, check_member_self_ownership
from response import success

bp = Blueprint("surveys", __name__)


def _get_nested_survey(mid, sid):
    get_or_404(stores["members"], mid, "member")
    s = stores["surveys"].get(sid)
    if s is None or s.get("member_id") != mid:
        raise_err(ERR_NOT_FOUND, "survey does not exist or does not belong to member")
    return s


@bp.route("/cob/members/<mid>/member-surveys", methods=["POST"])
def send_survey(mid):
    require_roles("COBAnalyst", "EligibilityAnalyst")
    member = get_or_404(stores["members"], mid, "member")
    if member.get("status") != "ENROLLED":
        raise_err(ERR_MEMBER_DISENROLLED, "Operation requires Member.status == ENROLLED")
    now = now_dt()
    rec = base_record()
    rec.update({
        "member_id": mid,
        "sent_at": iso_fmt(now),
        "due_at": iso_fmt(now + timedelta(days=30)),
        "response_payload": None,
        "responded_at": None,
        "status": "SENT",
    })
    stores["surveys"][rec["id"]] = rec
    return success(rec, status=201)


@bp.route("/cob/members/<mid>/member-surveys", methods=["GET"])
def list_surveys(mid):
    require_roles("PlatformAdmin", "COBAnalyst", "EligibilityAnalyst", "MemberSelf")
    get_or_404(stores["members"], mid, "member")
    items = [s for s in stores["surveys"].values() if s.get("member_id") == mid]
    status = request.args.get("status")
    if status:
        items = [s for s in items if s.get("status") == status]
    return paginate(items)


@bp.route("/cob/members/<mid>/member-surveys/<sid>", methods=["GET"])
def get_survey(mid, sid):
    require_roles("PlatformAdmin", "COBAnalyst", "EligibilityAnalyst", "MemberSelf")
    s = _get_nested_survey(mid, sid)
    return success(s)


@bp.route("/cob/members/<mid>/member-surveys/<sid>/respond", methods=["POST"])
def respond_survey(mid, sid):
    user_id, role = require_roles("MemberSelf")
    s = _get_nested_survey(mid, sid)
    member = stores["members"][mid]
    if member.get("status") != "ENROLLED":
        raise_err(ERR_MEMBER_DISENROLLED, "Operation requires Member.status == ENROLLED")
    if s.get("status") != "SENT":
        raise_err(ERR_INVALID_STATE, "Survey is not in SENT")
    # Ownership check
    check_member_self_ownership(user_id, role, mid)
    # Temporal check: current clock <= due_at
    from db import parse_iso
    if now_dt() > parse_iso(s["due_at"]):
        raise_err(ERR_SURVEY_EXPIRED, "Survey response attempted after due_at")
    data = body()
    payload = req_str(data, "response_payload")
    s["response_payload"] = payload
    s["responded_at"] = now_iso()
    s["status"] = "RESPONDED"
    touch(s)
    touch(member)
    # Auto-create lead with source=MEMBER_SURVEY
    lead = base_record()
    lead.update({
        "member_id": mid,
        "source": "MEMBER_SURVEY",
        "raw_payload": payload,
        "received_at": now_iso(),
        "disposition": "RECEIVED",
    })
    stores["leads"][lead["id"]] = lead
    return success(s)
