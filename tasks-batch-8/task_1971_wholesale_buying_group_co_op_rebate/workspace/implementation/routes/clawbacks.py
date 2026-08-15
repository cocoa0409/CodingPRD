"""ClawbackCase administration (PRD §3.7)."""

from flask import Blueprint, request

from db import store, touch, public
from errors import err_not_found, err_state, err_not_owner
from middleware import require_roles, body_json, req_str
from response import success_object, success_list, parse_pagination, paginate
from services import lifecycle

bp = Blueprint("clawbacks", __name__)

READ_ROLES = ("CoopAdmin", "FinanceOfficer", "MemberRep")


def get_case_or_404(case_id):
    case = store.clawbacks.get(case_id)
    if case is None:
        raise err_not_found("ClawbackCase not found")
    return case


def _arg(name):
    v = request.args.get(name)
    return v if v not in (None, "") else None


@bp.route("/coop/clawback-cases/<case_id>", methods=["GET"])
@require_roles(*READ_ROLES)
def get_case(uid, role, case_id):
    return success_object(public(get_case_or_404(case_id)), code=200)


@bp.route("/coop/clawback-cases", methods=["GET"])
@require_roles(*READ_ROLES)
def list_cases(uid, role):
    limit, offset = parse_pagination()
    items = list(store.clawbacks.values())
    member_id = _arg("member_id")
    if member_id is not None:
        items = [c for c in items if c["member_id"] == member_id]
    status = _arg("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    trigger = _arg("trigger_reason")
    if trigger is not None:
        items = [c for c in items if c["trigger_reason"] == trigger]
    page, total = paginate(items, limit, offset)
    return success_list([public(c) for c in page], limit, offset, total)


@bp.route("/coop/clawback-cases/<case_id>/notify", methods=["POST"])
@require_roles("CoopAdmin")
def notify(uid, role, case_id):
    case = get_case_or_404(case_id)
    if case["status"] != "OPEN":
        raise err_state("Only an OPEN clawback case can be notified")
    case["status"] = "NOTIFIED"
    touch(case)
    return success_object(public(case), code=200)


@bp.route("/coop/clawback-cases/<case_id>/dispute", methods=["POST"])
@require_roles("MemberRep")
def dispute(uid, role, case_id):
    case = get_case_or_404(case_id)
    body = body_json(required=True)
    note = req_str(body, "dispute_note")
    if case["status"] != "NOTIFIED":
        raise err_state("Only a NOTIFIED clawback case can be disputed")
    if case["member_id"] != uid:
        raise err_not_owner("MemberRep may only dispute their own member's clawback cases")
    case["dispute_note"] = note
    case["status"] = "DISPUTED"
    touch(case)
    return success_object(public(case), code=200)


@bp.route("/coop/clawback-cases/<case_id>/resolve", methods=["POST"])
@require_roles("CoopAdmin")
def resolve(uid, role, case_id):
    case = get_case_or_404(case_id)
    if case["status"] not in ("NOTIFIED", "DISPUTED"):
        raise err_state("Only a NOTIFIED or DISPUTED clawback case can be resolved")
    lifecycle.resolve_clawback(case)
    return success_object(public(case), code=200)


@bp.route("/coop/clawback-cases/<case_id>/waive", methods=["POST"])
@require_roles("CoopAdmin")
def waive(uid, role, case_id):
    case = get_case_or_404(case_id)
    if case["status"] not in ("NOTIFIED", "DISPUTED"):
        raise err_state("Only a NOTIFIED or DISPUTED clawback case can be waived")
    case["status"] = "WAIVED"
    touch(case)
    return success_object(public(case), code=200)
