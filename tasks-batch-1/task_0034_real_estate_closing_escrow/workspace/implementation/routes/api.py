"""Flask routes — every endpoint listed in PRD §4 / SCAFFOLD §1.5.

Auth (priority 1/2) is enforced via the @require_roles decorator. Body shape /
business / fiscal validations happen inside the service modules in the same
order as SCAFFOLD §1.4.
"""
from __future__ import annotations

from flask import Blueprint, request

from auth import require_roles
from clock import CLOCK, parse_iso
from db import DB_INSTANCE
from errors import ERR_INVALID_REQUEST, err
from lookup import (
    get_agreement_or_404,
    get_ccr_or_404,
    get_cd_or_404,
    get_deposit_or_404,
    get_disbursement_or_404,
    get_escrow_or_404,
    get_exchange_or_404,
    get_title_policy_or_404,
    get_title_search_or_404,
    get_user_or_404,
    get_wire_or_404,
)
from response import list_ok, ok
from serialize import (
    serialize_ccr_review,
    serialize_closing_disclosure,
    serialize_disbursement,
    serialize_earnest_money_deposit,
    serialize_escrow_account,
    serialize_exchange_account,
    serialize_purchase_agreement,
    serialize_title_insurance_policy,
    serialize_title_search,
    serialize_user,
    serialize_wire_instruction,
)
from services import (
    ccr as ccr_svc,
    closing_disclosure as cd_svc,
    disbursement as disb_svc,
    earnest as earnest_svc,
    exchange as exchange_svc,
    purchase_agreement as agreement_svc,
    title as title_svc,
    users as users_svc,
    wire as wire_svc,
)
from validation import get_json_body, parse_pagination

bp = Blueprint("api", __name__)


# ---------------------------------------------------------------------------
# PurchaseAgreement
# ---------------------------------------------------------------------------


@bp.route("/purchase-agreements", methods=["POST"])
@require_roles("EscrowOfficer")
def create_purchase_agreement():
    body = get_json_body()
    a = agreement_svc.create_purchase_agreement(body)
    return ok(serialize_purchase_agreement(a), 201)


@bp.route("/purchase-agreements/<aid>", methods=["GET"])
@require_roles("EscrowOfficer", "TitleAgent", "ComplianceOfficer")
def get_purchase_agreement(aid):
    a = get_agreement_or_404(aid)
    return ok(serialize_purchase_agreement(a))


@bp.route("/purchase-agreements", methods=["GET"])
@require_roles("EscrowOfficer", "TitleAgent", "ComplianceOfficer")
def list_purchase_agreements():
    limit, offset = parse_pagination()
    filters = {
        "status": request.args.get("status"),
        "exchange_account_id": request.args.get("exchange_account_id"),
    }
    items = agreement_svc.list_purchase_agreements(filters)
    page = items[offset : offset + limit]
    return list_ok([serialize_purchase_agreement(x) for x in page], limit, offset, len(items))


@bp.route("/purchase-agreements/<aid>/activate", methods=["POST"])
@require_roles("EscrowOfficer")
def activate_agreement(aid):
    a = agreement_svc.activate(aid)
    return ok(serialize_purchase_agreement(a))


@bp.route("/purchase-agreements/<aid>/clear-to-close", methods=["POST"])
@require_roles("ComplianceOfficer")
def clear_to_close(aid):
    a = agreement_svc.clear_to_close(aid)
    return ok(serialize_purchase_agreement(a))


@bp.route("/purchase-agreements/<aid>/close", methods=["POST"])
@require_roles("EscrowOfficer")
def close_agreement(aid):
    a = agreement_svc.close_agreement(aid)
    return ok(serialize_purchase_agreement(a))


@bp.route("/purchase-agreements/<aid>/terminate", methods=["POST"])
@require_roles("EscrowOfficer")
def terminate_agreement(aid):
    body = get_json_body()
    a = agreement_svc.terminate(aid, body)
    return ok(serialize_purchase_agreement(a))


# ---------------------------------------------------------------------------
# EscrowAccount
# ---------------------------------------------------------------------------


@bp.route("/escrow-accounts/<eid>", methods=["GET"])
@require_roles("EscrowOfficer", "ComplianceOfficer")
def get_escrow(eid):
    e = get_escrow_or_404(eid)
    return ok(serialize_escrow_account(e))


@bp.route("/escrow-accounts", methods=["GET"])
@require_roles("EscrowOfficer", "ComplianceOfficer")
def list_escrows():
    limit, offset = parse_pagination()
    items = list(DB_INSTANCE.escrow_accounts.values())
    if request.args.get("agreement_id"):
        items = [e for e in items if e["agreement_id"] == request.args.get("agreement_id")]
    if request.args.get("escrow_officer_id"):
        items = [e for e in items if e["escrow_officer_id"] == request.args.get("escrow_officer_id")]
    if request.args.get("status"):
        items = [e for e in items if e["status"] == request.args.get("status")]
    items.sort(key=lambda e: e["created_at"])
    page = items[offset : offset + limit]
    return list_ok([serialize_escrow_account(x) for x in page], limit, offset, len(items))


# ---------------------------------------------------------------------------
# EarnestMoneyDeposit
# ---------------------------------------------------------------------------


@bp.route("/earnest-money-deposits", methods=["POST"])
@require_roles("EscrowOfficer")
def create_deposit():
    body = get_json_body()
    d = earnest_svc.create_deposit(body)
    return ok(serialize_earnest_money_deposit(d), 201)


@bp.route("/earnest-money-deposits/<did>/confirm", methods=["POST"])
@require_roles("EscrowOfficer")
def confirm_deposit(did):
    body = get_json_body()
    d = earnest_svc.confirm_deposit(did, body)
    return ok(serialize_earnest_money_deposit(d))


@bp.route("/earnest-money-deposits", methods=["GET"])
@require_roles("EscrowOfficer", "ComplianceOfficer")
def list_deposits():
    limit, offset = parse_pagination()
    items = earnest_svc.list_deposits({
        "escrow_account_id": request.args.get("escrow_account_id"),
        "status": request.args.get("status"),
    })
    page = items[offset : offset + limit]
    return list_ok([serialize_earnest_money_deposit(x) for x in page], limit, offset, len(items))


@bp.route("/earnest-money-deposits/<did>", methods=["GET"])
@require_roles("EscrowOfficer", "ComplianceOfficer")
def get_deposit(did):
    d = get_deposit_or_404(did)
    return ok(serialize_earnest_money_deposit(d))


# ---------------------------------------------------------------------------
# TitleSearch
# ---------------------------------------------------------------------------


@bp.route("/title-searches", methods=["POST"])
@require_roles("TitleAgent")
def create_title_search():
    body = get_json_body()
    t = title_svc.create_title_search(body)
    return ok(serialize_title_search(t), 201)


@bp.route("/title-searches/<tid>/complete", methods=["POST"])
@require_roles("TitleAgent")
def complete_title_search(tid):
    body = get_json_body()
    t = title_svc.complete_title_search(tid, body)
    return ok(serialize_title_search(t))


@bp.route("/title-searches/<tid>/resolve", methods=["POST"])
@require_roles("TitleAgent")
def resolve_title_search(tid):
    body = get_json_body()
    t = title_svc.resolve_title_search(tid, body)
    return ok(serialize_title_search(t))


@bp.route("/title-searches", methods=["GET"])
@require_roles("TitleAgent", "EscrowOfficer", "ComplianceOfficer")
def list_title_searches():
    limit, offset = parse_pagination()
    items = title_svc.list_title_searches({
        "agreement_id": request.args.get("agreement_id"),
        "status": request.args.get("status"),
    })
    page = items[offset : offset + limit]
    return list_ok([serialize_title_search(x) for x in page], limit, offset, len(items))


@bp.route("/title-searches/<tid>", methods=["GET"])
@require_roles("TitleAgent", "EscrowOfficer", "ComplianceOfficer")
def get_title_search(tid):
    t = get_title_search_or_404(tid)
    return ok(serialize_title_search(t))


# ---------------------------------------------------------------------------
# TitleInsurancePolicy
# ---------------------------------------------------------------------------


@bp.route("/title-insurance-policies", methods=["POST"])
@require_roles("TitleAgent")
def issue_title_policy():
    body = get_json_body()
    p = title_svc.issue_title_policy(body)
    return ok(serialize_title_insurance_policy(p), 201)


@bp.route("/title-insurance-policies/<pid>", methods=["GET"])
@require_roles("TitleAgent", "EscrowOfficer", "ComplianceOfficer")
def get_title_policy(pid):
    p = get_title_policy_or_404(pid)
    return ok(serialize_title_insurance_policy(p))


@bp.route("/title-insurance-policies", methods=["GET"])
@require_roles("TitleAgent", "EscrowOfficer", "ComplianceOfficer")
def list_title_policies():
    limit, offset = parse_pagination()
    items = title_svc.list_title_policies({
        "title_search_id": request.args.get("title_search_id"),
        "status": request.args.get("status"),
    })
    page = items[offset : offset + limit]
    return list_ok([serialize_title_insurance_policy(x) for x in page], limit, offset, len(items))


# ---------------------------------------------------------------------------
# CCRReview
# ---------------------------------------------------------------------------


@bp.route("/ccr-reviews", methods=["POST"])
@require_roles("ComplianceOfficer")
def create_ccr():
    body = get_json_body()
    c = ccr_svc.create_ccr(body)
    return ok(serialize_ccr_review(c), 201)


@bp.route("/ccr-reviews", methods=["GET"])
@require_roles("ComplianceOfficer", "EscrowOfficer")
def list_ccrs():
    limit, offset = parse_pagination()
    items = ccr_svc.list_ccrs({"agreement_id": request.args.get("agreement_id")})
    page = items[offset : offset + limit]
    return list_ok([serialize_ccr_review(x) for x in page], limit, offset, len(items))


@bp.route("/ccr-reviews/<cid>", methods=["GET"])
@require_roles("ComplianceOfficer", "EscrowOfficer")
def get_ccr(cid):
    c = get_ccr_or_404(cid)
    return ok(serialize_ccr_review(c))


# ---------------------------------------------------------------------------
# ClosingDisclosure
# ---------------------------------------------------------------------------


@bp.route("/closing-disclosures", methods=["POST"])
@require_roles("EscrowOfficer")
def create_cd():
    body = get_json_body()
    cd = cd_svc.create_cd(body)
    return ok(serialize_closing_disclosure(cd), 201)


@bp.route("/closing-disclosures/<cid>/deliver", methods=["POST"])
@require_roles("EscrowOfficer")
def deliver_cd(cid):
    cd = cd_svc.deliver_cd(cid)
    return ok(serialize_closing_disclosure(cd))


@bp.route("/closing-disclosures/<cid>/reissue", methods=["POST"])
@require_roles("EscrowOfficer")
def reissue_cd(cid):
    body = get_json_body()
    cd = cd_svc.reissue_cd(cid, body)
    return ok(serialize_closing_disclosure(cd))


@bp.route("/closing-disclosures/<cid>/acknowledge", methods=["POST"])
@require_roles("EscrowOfficer")
def acknowledge_cd(cid):
    cd = cd_svc.acknowledge_cd(cid)
    return ok(serialize_closing_disclosure(cd))


@bp.route("/closing-disclosures/<cid>", methods=["GET"])
@require_roles("EscrowOfficer", "ComplianceOfficer")
def get_cd(cid):
    cd = get_cd_or_404(cid)
    return ok(serialize_closing_disclosure(cd))


@bp.route("/closing-disclosures", methods=["GET"])
@require_roles("EscrowOfficer", "ComplianceOfficer")
def list_cds():
    limit, offset = parse_pagination()
    items = cd_svc.list_cds({
        "agreement_id": request.args.get("agreement_id"),
        "status": request.args.get("status"),
    })
    page = items[offset : offset + limit]
    return list_ok([serialize_closing_disclosure(x) for x in page], limit, offset, len(items))


# ---------------------------------------------------------------------------
# WireInstruction
# ---------------------------------------------------------------------------


@bp.route("/wire-instructions", methods=["POST"])
@require_roles("EscrowOfficer")
def create_wire():
    body = get_json_body()
    w = wire_svc.create_wire(body)
    return ok(serialize_wire_instruction(w), 201)


@bp.route("/wire-instructions/<wid>/callback-verify", methods=["POST"])
@require_roles("EscrowOfficer")
def callback_verify(wid):
    body = get_json_body()
    w = wire_svc.callback_verify(wid, body)
    return ok(serialize_wire_instruction(w))


@bp.route("/wire-instructions/<wid>/lock", methods=["POST"])
@require_roles("ComplianceOfficer")
def lock_wire(wid):
    w = wire_svc.lock_wire(wid)
    return ok(serialize_wire_instruction(w))


@bp.route("/wire-instructions/<wid>/reject", methods=["POST"])
@require_roles("ComplianceOfficer")
def reject_wire(wid):
    w = wire_svc.reject_wire(wid)
    return ok(serialize_wire_instruction(w))


@bp.route("/wire-instructions/<wid>", methods=["GET"])
@require_roles("EscrowOfficer", "ComplianceOfficer")
def get_wire(wid):
    w = get_wire_or_404(wid)
    return ok(serialize_wire_instruction(w))


@bp.route("/wire-instructions", methods=["GET"])
@require_roles("EscrowOfficer", "ComplianceOfficer")
def list_wires():
    limit, offset = parse_pagination()
    items = wire_svc.list_wires({
        "agreement_id": request.args.get("agreement_id"),
        "party": request.args.get("party"),
        "status": request.args.get("status"),
    })
    page = items[offset : offset + limit]
    return list_ok([serialize_wire_instruction(x) for x in page], limit, offset, len(items))


# ---------------------------------------------------------------------------
# Disbursement
# ---------------------------------------------------------------------------


@bp.route("/disbursements", methods=["POST"])
@require_roles("EscrowOfficer")
def create_disbursement():
    body = get_json_body()
    d = disb_svc.create_disbursement(body)
    return ok(serialize_disbursement(d), 201)


@bp.route("/disbursements", methods=["GET"])
@require_roles("EscrowOfficer", "ComplianceOfficer")
def list_disbursements():
    limit, offset = parse_pagination()
    items = disb_svc.list_disbursements({
        "escrow_account_id": request.args.get("escrow_account_id"),
        "wire_instruction_id": request.args.get("wire_instruction_id"),
        "status": request.args.get("status"),
    })
    page = items[offset : offset + limit]
    return list_ok([serialize_disbursement(x) for x in page], limit, offset, len(items))


@bp.route("/disbursements/<did>", methods=["GET"])
@require_roles("EscrowOfficer", "ComplianceOfficer")
def get_disbursement(did):
    d = get_disbursement_or_404(did)
    return ok(serialize_disbursement(d))


# ---------------------------------------------------------------------------
# ExchangeAccount
# ---------------------------------------------------------------------------


@bp.route("/exchange-accounts", methods=["POST"])
@require_roles("EscrowOfficer")
def create_exchange():
    body = get_json_body()
    x = exchange_svc.create_exchange(body)
    return ok(serialize_exchange_account(x), 201)


@bp.route("/exchange-accounts/<xid>/identify", methods=["POST"])
@require_roles("EscrowOfficer")
def identify_exchange(xid):
    body = get_json_body()
    x = exchange_svc.identify(xid, body)
    return ok(serialize_exchange_account(x))


@bp.route("/exchange-accounts/<xid>", methods=["GET"])
@require_roles("EscrowOfficer", "ComplianceOfficer")
def get_exchange(xid):
    x = exchange_svc.fetch(xid)
    return ok(serialize_exchange_account(x))


@bp.route("/exchange-accounts", methods=["GET"])
@require_roles("EscrowOfficer", "ComplianceOfficer")
def list_exchanges():
    limit, offset = parse_pagination()
    items = exchange_svc.list_exchanges({"status": request.args.get("status")})
    page = items[offset : offset + limit]
    return list_ok([serialize_exchange_account(x) for x in page], limit, offset, len(items))


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------


@bp.route("/users", methods=["POST"])
@require_roles("ComplianceOfficer")
def create_user():
    body = get_json_body()
    u = users_svc.create_user(body)
    return ok(serialize_user(u), 201)


@bp.route("/users/<uid>", methods=["GET"])
@require_roles("EscrowOfficer", "TitleAgent", "ComplianceOfficer")
def get_user(uid):
    u = get_user_or_404(uid)
    return ok(serialize_user(u))


@bp.route("/users", methods=["GET"])
@require_roles("ComplianceOfficer")
def list_users():
    limit, offset = parse_pagination()
    items = users_svc.list_users({"role": request.args.get("role")})
    page = items[offset : offset + limit]
    return list_ok([serialize_user(x) for x in page], limit, offset, len(items))


# ---------------------------------------------------------------------------
# Clock control (test-driving endpoints, PRD §3.8)
# ---------------------------------------------------------------------------


@bp.route("/_clock/set", methods=["POST"])
@require_roles("ComplianceOfficer")
def clock_set():
    body = get_json_body()
    iso = body.get("to_iso8601")
    if not isinstance(iso, str) or iso == "":
        raise err(ERR_INVALID_REQUEST, "to_iso8601 must be a non-empty ISO 8601 string")
    try:
        instant = parse_iso(iso)
    except ValueError as exc:
        raise err(ERR_INVALID_REQUEST, "to_iso8601 must be ISO 8601") from exc
    CLOCK.set(instant)
    return ok({})


@bp.route("/_clock/advance", methods=["POST"])
@require_roles("ComplianceOfficer")
def clock_advance():
    body = get_json_body()
    seconds = body.get("seconds")
    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)):
        raise err(ERR_INVALID_REQUEST, "seconds must be a number")
    CLOCK.advance(float(seconds))
    return ok({})
