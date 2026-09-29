"""ClientContract lifecycle endpoints (PRD 3.1)."""
from flask import Blueprint, g

import cascades
from core import (ApiError, DB, ROLE_CLIENT_SPONSOR, ROLE_OPERATOR_ADMIN, bad_request, body,
                 created, get_or_404, new_record, now, ok, opt_int, req_date, req_enum,
                 req_int, req_num, req_str, require, scope_contract, upd, view, where)
from guards import CONTRACT_TERMINAL, invalid_transition, terminal

bp = Blueprint("contracts", __name__)

FEE_STRUCTURES = ("MANAGEMENT_FEE", "COST_PLUS")
STAFFING_MODELS = ("OPERATOR_EMPLOYED", "CLIENT_EMPLOYED", "HYBRID")


def _fee_terms_ok(fee_structure, management_fee_cents, not_to_exceed_cents):
    if fee_structure == "MANAGEMENT_FEE":
        return management_fee_cents is not None and not_to_exceed_cents is None
    return not_to_exceed_cents is not None and management_fee_cents is None


def _check_fee_terms(fee_structure, management_fee_cents, not_to_exceed_cents):
    if not _fee_terms_ok(fee_structure, management_fee_cents, not_to_exceed_cents):
        raise ApiError("ERR_FEE_TERMS_INVALID", 422)


def _site_code_taken(site_code, exclude_id=None):
    for contract in DB.all("contract"):
        if contract["id"] == exclude_id:
            continue
        if contract["site_code"] == site_code and contract["status"] != "WITHDRAWN":
            return True
    return False


def _read_terms(data):
    fee_structure = req_enum(data, "fee_structure", FEE_STRUCTURES)
    staffing_model = req_enum(data, "staffing_model", STAFFING_MODELS)
    management_fee_cents = opt_int(data, "management_fee_cents", minimum=0)
    not_to_exceed_cents = opt_int(data, "not_to_exceed_cents", minimum=1)
    budgeted_staff_fte = req_num(data, "budgeted_staff_fte", exclusive_min=0, max_decimals=2)
    participation_target_pct = req_int(data, "participation_target_pct", 1, 100)
    term_start_on = req_date(data, "term_start_on")
    term_end_on = req_date(data, "term_end_on")
    if term_end_on <= term_start_on:
        raise bad_request("term_end_on must be strictly after term_start_on")
    return {
        "fee_structure": fee_structure,
        "staffing_model": staffing_model,
        "management_fee_cents": management_fee_cents,
        "not_to_exceed_cents": not_to_exceed_cents,
        "budgeted_staff_fte": budgeted_staff_fte,
        "participation_target_pct": participation_target_pct,
        "term_start_on": term_start_on,
        "term_end_on": term_end_on,
    }


def _new_contract(client_name, site_code, terms, supersedes_contract_id=None):
    return new_record("contract", {
        "client_name": client_name,
        "site_code": site_code,
        "fee_structure": terms["fee_structure"],
        "staffing_model": terms["staffing_model"],
        "management_fee_cents": terms["management_fee_cents"],
        "not_to_exceed_cents": terms["not_to_exceed_cents"],
        "budgeted_staff_fte": terms["budgeted_staff_fte"],
        "participation_target_pct": terms["participation_target_pct"],
        "term_start_on": terms["term_start_on"],
        "term_end_on": terms["term_end_on"],
        "supersedes_contract_id": supersedes_contract_id,
        "status": "DRAFT",
        "revision_round": 0,
        "ytd_billed_cents": 0,
        "pending_penalty_cents": 0,
        "uncovered_session_count": 0,
        "eligible_member_count": 0,
        "approved_at": None,
    })


@bp.post("/client-contracts")
def create_contract():
    require(ROLE_OPERATOR_ADMIN)
    data = body()
    client_name = req_str(data, "client_name", 1, 120)
    site_code = req_str(data, "site_code", 1, 40)
    terms = _read_terms(data)
    _check_fee_terms(terms["fee_structure"], terms["management_fee_cents"],
                     terms["not_to_exceed_cents"])
    if _site_code_taken(site_code):
        raise ApiError("ERR_SITE_CODE_CONFLICT", 409)
    contract = _new_contract(client_name, site_code, terms)
    return created(view(contract))


@bp.post("/client-contracts/<cid>/submit")
def submit_contract(cid):
    require(ROLE_OPERATOR_ADMIN)
    body()
    contract = get_or_404("contract", cid)
    terminal(contract["status"] in CONTRACT_TERMINAL)
    if contract["status"] != "DRAFT":
        invalid_transition()
    _check_fee_terms(contract["fee_structure"], contract["management_fee_cents"],
                     contract["not_to_exceed_cents"])
    has_manager = False
    for staff in where("staff", contract_id=contract["id"]):
        if staff["role_type"] == "SITE_MANAGER" and staff["duty_status"] == "ACTIVE_DUTY":
            has_manager = True
            break
    if not has_manager:
        raise ApiError("ERR_SITE_MANAGER_REQUIRED", 422)
    upd(contract, status="PENDING_CLIENT_APPROVAL")
    return ok(view(contract))


@bp.post("/client-contracts/<cid>/client-decision")
def client_decision(cid):
    require(ROLE_CLIENT_SPONSOR)
    contract = get_or_404("contract", cid)
    scope_contract(contract["id"])
    data = body()
    decision = req_enum(data, "decision", ("APPROVE", "RETURN"))
    terminal(contract["status"] in CONTRACT_TERMINAL)
    if contract["status"] != "PENDING_CLIENT_APPROVAL":
        raise ApiError("ERR_CONTRACT_NOT_PENDING", 409)
    if decision == "APPROVE":
        upd(contract, status="ACTIVE", approved_at=now())
        cascades.contract_open_rooms_on_approval(contract)
    else:
        upd(contract, status="DRAFT",
            revision_round=(contract.get("revision_round") or 0) + 1)
    return ok(view(contract))


@bp.post("/client-contracts/<cid>/service-status")
def service_status(cid):
    require(ROLE_OPERATOR_ADMIN)
    contract = get_or_404("contract", cid)
    data = body()
    action = req_enum(data, "action", ("SUSPEND", "RESUME", "TERMINATE"))
    terminal(contract["status"] in CONTRACT_TERMINAL)
    status = contract["status"]
    if action == "SUSPEND":
        if status != "ACTIVE":
            invalid_transition()
        upd(contract, status="SUSPENDED")
        cascades.contract_stand_down(contract)
    elif action == "RESUME":
        if status != "SUSPENDED":
            invalid_transition()
        upd(contract, status="ACTIVE")
        cascades.contract_resume(contract)
    else:
        if status == "DRAFT":
            upd(contract, status="WITHDRAWN")
        elif status in ("ACTIVE", "SUSPENDED"):
            if cascades.has_open_invoices(contract["id"]):
                raise ApiError("ERR_OPEN_INVOICES", 409)
            upd(contract, status="TERMINATED")
            if status == "ACTIVE":
                cascades.contract_stand_down(contract)
            cascades.contract_terminate_people(contract)
        else:
            invalid_transition()
    return ok(view(contract))


@bp.post("/client-contracts/<cid>/amendments")
def create_amendment(cid):
    require(ROLE_OPERATOR_ADMIN)
    contract = get_or_404("contract", cid)
    data = body()
    terms = _read_terms(data)
    terminal(contract["status"] in CONTRACT_TERMINAL)
    if contract["status"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError("ERR_AMENDMENT_NOT_ALLOWED", 409)
    _check_fee_terms(terms["fee_structure"], terms["management_fee_cents"],
                     terms["not_to_exceed_cents"])
    amendment = _new_contract(contract["client_name"], contract["site_code"], terms,
                              supersedes_contract_id=contract["id"])
    return created(view(amendment))
