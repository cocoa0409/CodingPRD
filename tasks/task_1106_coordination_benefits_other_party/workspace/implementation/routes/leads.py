"""Other-coverage lead endpoints."""

from flask import Blueprint, request

from db import stores, now_iso
from errors import raise_err, ERR_NOT_FOUND, ERR_INVALID_STATE
from helpers import base_record, touch, get_or_404, body, req_str, req_enum, paginate
from middleware import require_roles
from response import success

bp = Blueprint("leads", __name__)

SOURCES = ("MEMBER_SURVEY", "DATA_MATCH_CMS", "CLAIM_INDICATION", "ELIGIBILITY_MATCH")


def _get_nested_lead(mid, lid):
    get_or_404(stores["members"], mid, "member")
    lead = stores["leads"].get(lid)
    if lead is None or lead.get("member_id") != mid:
        raise_err(ERR_NOT_FOUND, "lead does not exist or does not belong to member")
    return lead


@bp.route("/cob/members/<mid>/other-coverage-leads", methods=["POST"])
def create_lead(mid):
    require_roles("COBAnalyst", "EligibilityAnalyst")
    get_or_404(stores["members"], mid, "member")
    data = body()
    source = req_enum(data, "source", SOURCES)
    raw_payload = req_str(data, "raw_payload")
    rec = base_record()
    rec.update({
        "member_id": mid,
        "source": source,
        "raw_payload": raw_payload,
        "received_at": now_iso(),
        "disposition": "RECEIVED",
    })
    stores["leads"][rec["id"]] = rec
    return success(rec, status=201)


@bp.route("/cob/members/<mid>/other-coverage-leads", methods=["GET"])
def list_leads(mid):
    require_roles("PlatformAdmin", "COBAnalyst", "EligibilityAnalyst", "MemberSelf")
    get_or_404(stores["members"], mid, "member")
    items = [l for l in stores["leads"].values() if l.get("member_id") == mid]
    disp = request.args.get("disposition")
    src = request.args.get("source")
    if disp:
        items = [l for l in items if l.get("disposition") == disp]
    if src:
        items = [l for l in items if l.get("source") == src]
    return paginate(items)


@bp.route("/cob/members/<mid>/other-coverage-leads/<lid>", methods=["GET"])
def get_lead(mid, lid):
    require_roles("PlatformAdmin", "COBAnalyst", "EligibilityAnalyst", "MemberSelf")
    lead = _get_nested_lead(mid, lid)
    return success(lead)


@bp.route("/cob/members/<mid>/other-coverage-leads/<lid>/mark-duplicate", methods=["POST"])
def mark_duplicate(mid, lid):
    require_roles("COBAnalyst")
    lead = _get_nested_lead(mid, lid)
    if lead.get("disposition") != "RECEIVED":
        raise_err(ERR_INVALID_STATE, "Lead is not in RECEIVED")
    lead["disposition"] = "REJECTED_DUPLICATE"
    touch(lead)
    return success(lead)


@bp.route("/cob/members/<mid>/other-coverage-leads/<lid>/reject", methods=["POST"])
def reject_lead(mid, lid):
    require_roles("COBAnalyst")
    lead = _get_nested_lead(mid, lid)
    if lead.get("disposition") != "RECEIVED":
        raise_err(ERR_INVALID_STATE, "Lead is not in RECEIVED")
    lead["disposition"] = "REJECTED_NO_COVERAGE"
    touch(lead)
    return success(lead)
