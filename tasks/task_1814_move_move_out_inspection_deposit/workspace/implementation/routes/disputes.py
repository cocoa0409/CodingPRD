"""Dispute endpoints (PRD §3.6): open, counter, accept, escalate, court."""
from datetime import timedelta

from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_AWARD_EXCEEDS_DISPUTED,
    ERR_DISPUTE_ALREADY_OPEN,
    ERR_DISPUTE_AMOUNT_INVALID,
    ERR_DISPUTE_WINDOW_CLOSED,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE_TRANSITION,
    ERR_STATEMENT_NOT_DISPUTABLE,
)
from middleware import authorized, check_tenant_ownership
from response import success_object
from routes.helpers import get_one, list_response
from services.calculations import court_resolution_settlement, small_claims_exposure
from services.core import (
    active_dispute_for, evaluate_settlement, jurisdiction_for_tenancy,
    new_record, public, recompute_statement_refund_due, recompute_tenancy_money,
    touch,
)
from util import CLOCK, parse_datetime
from validate import get_body, req_int, req_str, require_body_ref, require_path_resource

bp = Blueprint("disputes", __name__)


@bp.post("/pm/disputes")
def create_dispute():
    caller = authorized(["Tenant"])
    body = get_body()
    statement_id = req_str(body, "statement_id")
    disputed_amount_cents = req_int(body, "disputed_amount_cents", non_negative=True)
    reason = req_str(body, "reason")
    statement = require_body_ref("statements", statement_id, "statement_id")
    # Ownership: the acting tenant's identity must equal the statement's tenancy.
    check_tenant_ownership(caller, statement["tenancy_id"])
    # Priority 5: the target statement must be ISSUED or DISPUTED.
    if statement["status"] not in ("ISSUED", "DISPUTED"):
        raise_error(ERR_STATEMENT_NOT_DISPUTABLE,
                    "dispute target statement is not ISSUED or DISPUTED")
    tenancy = db["tenancies"].get(statement["tenancy_id"])
    jur = jurisdiction_for_tenancy(tenancy)
    # Priority 6: the creation date must fall on or before the issuance date
    # plus dispute_window_days.
    window_last = parse_datetime(statement["issued_at"]).date() + timedelta(
        days=jur["dispute_window_days"]
    )
    if CLOCK.today() > window_last:
        raise_error(ERR_DISPUTE_WINDOW_CLOSED,
                    "dispute opened after issued date + dispute_window_days")
    # Priority 8: at most one active dispute per statement.
    if active_dispute_for(statement["id"]) is not None:
        raise_error(ERR_DISPUTE_ALREADY_OPEN,
                    "an active dispute already exists for the statement")
    # Priority 10: the disputed portion must be in [1, deduction_total_cents].
    if not (1 <= disputed_amount_cents <= statement["deduction_total_cents"]):
        raise_error(ERR_DISPUTE_AMOUNT_INVALID,
                    "disputed_amount_cents outside [1, deduction_total_cents]")
    rec = new_record("disputes", {
        "statement_id": statement["id"],
        "tenancy_id": statement["tenancy_id"],
        "disputed_amount_cents": disputed_amount_cents,
        "reason": reason,
        "counter_amount_cents": None,
        "exposure_cents": None,
        "status": "OPEN",
    })
    # Opening a dispute pushes an ISSUED statement to DISPUTED.
    if statement["status"] == "ISSUED":
        statement["status"] = "DISPUTED"
        touch(statement)
    return success_object(public(rec), status=201)


@bp.get("/pm/disputes/<rid>")
def get_dispute(rid):
    return get_one("disputes", rid)


@bp.get("/pm/disputes")
def list_disputes():
    return list_response("disputes", {
        "statement_id": request.args.get("statement_id"),
        "tenancy_id": request.args.get("tenancy_id"),
        "status": request.args.get("status"),
    })


@bp.post("/pm/disputes/<rid>/counter")
def counter_dispute(rid):
    authorized(["PropertyManager"])
    body = get_body()
    counter = req_int(body, "counter_amount_cents", non_negative=True)
    dispute = require_path_resource("disputes", rid)
    if dispute["status"] != "OPEN":
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"counter requires an OPEN dispute, got {dispute['status']}")
    if counter > dispute["disputed_amount_cents"]:
        raise_error(ERR_INVALID_REQUEST,
                    "counter_amount_cents exceeds the disputed amount")
    dispute["counter_amount_cents"] = counter
    dispute["status"] = "MANAGER_COUNTERED"
    touch(dispute)
    return success_object(public(dispute))


@bp.post("/pm/disputes/<rid>/close_agreed")
def close_agreed_dispute(rid):
    caller = authorized(["Tenant"])
    get_body()
    dispute = require_path_resource("disputes", rid)
    check_tenant_ownership(caller, dispute["tenancy_id"])
    if dispute["status"] != "MANAGER_COUNTERED":
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"close_agreed requires MANAGER_COUNTERED, got {dispute['status']}")
    statement = db["statements"].get(dispute["statement_id"])
    # The un-kept remainder of the disputed portion is released back.
    released_delta = dispute["disputed_amount_cents"] - dispute["counter_amount_cents"]
    statement["released_cents"] += released_delta
    statement["status"] = "ISSUED"
    recompute_statement_refund_due(statement)
    touch(statement)
    dispute["status"] = "CLOSED_AGREED"
    touch(dispute)
    tenancy = db["tenancies"].get(dispute["tenancy_id"])
    recompute_tenancy_money(tenancy["id"])
    touch(tenancy)
    evaluate_settlement(statement)
    return success_object(public(dispute))


@bp.post("/pm/disputes/<rid>/escalate")
def escalate_dispute(rid):
    caller = authorized(["Tenant"])
    get_body()
    dispute = require_path_resource("disputes", rid)
    check_tenant_ownership(caller, dispute["tenancy_id"])
    if dispute["status"] not in ("OPEN", "MANAGER_COUNTERED"):
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"escalate requires OPEN or MANAGER_COUNTERED, got {dispute['status']}")
    statement = db["statements"].get(dispute["statement_id"])
    tenancy = db["tenancies"].get(dispute["tenancy_id"])
    jur = jurisdiction_for_tenancy(tenancy)
    dispute["exposure_cents"] = small_claims_exposure(dispute, statement, jur)
    dispute["status"] = "ESCALATED_SMALL_CLAIMS"
    touch(dispute)
    return success_object(public(dispute))


@bp.post("/pm/disputes/<rid>/resolve_court")
def resolve_court_dispute(rid):
    authorized(["PropertyManager"])
    body = get_body()
    awarded = req_int(body, "awarded_amount_cents", non_negative=True)
    dispute = require_path_resource("disputes", rid)
    if dispute["status"] != "ESCALATED_SMALL_CLAIMS":
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"resolve_court requires ESCALATED_SMALL_CLAIMS, got {dispute['status']}")
    if awarded > dispute["disputed_amount_cents"]:
        raise_error(ERR_AWARD_EXCEEDS_DISPUTED,
                    "awarded_amount_cents exceeds the disputed amount")
    statement = db["statements"].get(dispute["statement_id"])
    tenancy = db["tenancies"].get(dispute["tenancy_id"])
    jur = jurisdiction_for_tenancy(tenancy)
    penalty_cents = court_resolution_settlement(dispute, statement, jur, awarded)
    # The awarded portion is released back to the tenant.
    statement["released_cents"] += awarded
    statement["status"] = "ISSUED"
    recompute_statement_refund_due(statement)
    touch(statement)
    dispute["status"] = "COURT_RESOLVED"
    touch(dispute)
    if penalty_cents > 0:
        # Late statements manufacture an automatic PENALTY disbursement in
        # SENT; penalty money lives outside the deposit ledger.
        new_record("disbursements", {
            "tenancy_id": tenancy["id"],
            "statement_id": statement["id"],
            "kind": "PENALTY",
            "amount_cents": penalty_cents,
            "payee_name": tenancy["tenant_display_name"],
            "sent_at": CLOCK.now_iso(),
            "cashed_at": None,
            "escheatment_reference": None,
            "status": "SENT",
        })
    recompute_tenancy_money(tenancy["id"])
    touch(tenancy)
    evaluate_settlement(statement)
    return success_object(public(dispute))
