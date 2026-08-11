"""RoyaltyStatement and AdvanceInstallment endpoints."""
from decimal import Decimal

from flask import Blueprint

from core import (DB, F, ERR_BOOKS, ERR_DEAL_NOT_LIVE, ERR_FUTURE, ERR_STATE,
                  ERR_VAR_UNRESOLVED, ERR_VAR_WITHIN, fail, get_ref, get_scoped,
                  guard, list_response, new_record, parse_body, public,
                  success, touch)
from domain import (AUDIT_TOLERANCE_CENTS, commission_pct_for_deal, floor_dec,
                    reconcile_statement_fields)

bp = Blueprint("royalties", __name__)

ALL = ("AgencyAdmin", "Agent", "ContractsManager", "RoyaltiesAccountant")
RA = "RoyaltiesAccountant"


# -------------------------------------------------------- royalty statements ----
@bp.route("/royalty-statements", methods=["POST"])
def create_statement():
    guard(RA)
    data = parse_body([
        F("deal_id", "str", required=True),
        F("period_index", "int", required=True, lo=0),
        F("units_hardcover", "int", required=True, lo=0),
        F("units_trade", "int", required=True, lo=0),
        F("units_ebook", "int", required=True, lo=0),
        F("net_receipts_hardcover_cents", "int", required=True, lo=0),
        F("net_receipts_trade_cents", "int", required=True, lo=0),
        F("net_receipts_ebook_cents", "int", required=True, lo=0),
        F("publisher_reported_royalty_cents", "int", required=True, lo=0),
    ])
    deal = get_ref("deals", data["deal_id"], None)
    agency = DB["agencies"].get(deal["agency_id"])
    if agency is not None and data["period_index"] > agency["period_index"]:
        fail(ERR_FUTURE, 409, "statement period_index is in the future")
    closed = agency["books_closed_through_period_index"] if agency else None
    if closed is not None and data["period_index"] <= closed:
        fail(ERR_BOOKS, 409, "statement period is covered by closed books")
    rec = new_record()
    rec.update({
        "agency_id": deal["agency_id"],
        "deal_id": deal["id"],
        "period_index": data["period_index"],
        "units_hardcover": data["units_hardcover"],
        "units_trade": data["units_trade"],
        "units_ebook": data["units_ebook"],
        "net_receipts_hardcover_cents": data["net_receipts_hardcover_cents"],
        "net_receipts_trade_cents": data["net_receipts_trade_cents"],
        "net_receipts_ebook_cents": data["net_receipts_ebook_cents"],
        "publisher_reported_royalty_cents":
            data["publisher_reported_royalty_cents"],
        "gross_royalty_cents": None,
        "agency_commission_cents": None,
        "author_net_cents": None,
        "variance_cents": None,
        "status": "RECEIVED",
    })
    DB["royalty_statements"][rec["id"]] = rec
    return success(public(rec), 201)


@bp.route("/royalty-statements/<statementId>", methods=["GET"])
def get_statement(statementId):
    ctx = guard(*ALL)
    return success(public(get_scoped("royalty_statements", statementId, ctx)))


@bp.route("/royalty-statements", methods=["GET"])
def list_statements():
    ctx = guard(*ALL)
    return list_response("royalty_statements", ctx, {
        "agency_id": "str", "status": "str", "deal_id": "str",
        "period_index": "int",
    })


def _live_deal_for(stmt):
    deal = DB["deals"].get(stmt["deal_id"])
    if deal is None or deal["status"] not in ("EXECUTED", "ACTIVE"):
        fail(ERR_DEAL_NOT_LIVE, 409, "deal is not EXECUTED or ACTIVE")
    return deal


@bp.route("/royalty-statements/<statementId>/reconcile", methods=["POST"])
def reconcile_statement(statementId):
    ctx = guard(RA)
    parse_body([])
    stmt = get_scoped("royalty_statements", statementId, ctx)
    if stmt["status"] != "RECEIVED":
        fail(ERR_STATE, 409, "statement is not RECEIVED")
    deal = _live_deal_for(stmt)
    _, net = reconcile_statement_fields(stmt)
    stmt["status"] = "RECONCILED"
    touch(stmt)
    new_earned = min(deal["advance_cents"],
                     deal["advance_earned_out_cents"] + net)
    if new_earned != deal["advance_earned_out_cents"]:
        deal["advance_earned_out_cents"] = new_earned
        touch(deal)
    return success(public(stmt))


@bp.route("/royalty-statements/<statementId>/open-audit", methods=["POST"])
def open_audit(statementId):
    ctx = guard(RA)
    parse_body([])
    stmt = get_scoped("royalty_statements", statementId, ctx)
    if stmt["status"] not in ("RECONCILED", "AUDIT_RESOLVED"):
        fail(ERR_STATE, 409,
             "statement is not RECONCILED or AUDIT_RESOLVED")
    if abs(stmt["variance_cents"]) <= AUDIT_TOLERANCE_CENTS:
        fail(ERR_VAR_WITHIN, 409, "variance is within audit tolerance")
    agency = DB["agencies"].get(stmt["agency_id"])
    closed = agency["books_closed_through_period_index"] if agency else None
    if closed is not None and stmt["period_index"] <= closed:
        fail(ERR_BOOKS, 409, "statement period is covered by closed books")
    stmt["status"] = "AUDIT_OPEN"
    touch(stmt)
    return success(public(stmt))


@bp.route("/royalty-statements/<statementId>/resolve-audit", methods=["POST"])
def resolve_audit(statementId):
    ctx = guard(RA)
    data = parse_body([
        F("net_receipts_hardcover_cents", "int", required=True, lo=0),
        F("net_receipts_trade_cents", "int", required=True, lo=0),
        F("net_receipts_ebook_cents", "int", required=True, lo=0),
    ])
    stmt = get_scoped("royalty_statements", statementId, ctx)
    if stmt["status"] != "AUDIT_OPEN":
        fail(ERR_STATE, 409, "statement is not AUDIT_OPEN")
    old_net = stmt["author_net_cents"]
    stmt["net_receipts_hardcover_cents"] = data["net_receipts_hardcover_cents"]
    stmt["net_receipts_trade_cents"] = data["net_receipts_trade_cents"]
    stmt["net_receipts_ebook_cents"] = data["net_receipts_ebook_cents"]
    deal, new_net = reconcile_statement_fields(stmt)
    stmt["status"] = "AUDIT_RESOLVED"
    touch(stmt)
    delta = new_net - (old_net or 0)
    new_earned = min(deal["advance_cents"],
                     max(0, deal["advance_earned_out_cents"] + delta))
    if new_earned != deal["advance_earned_out_cents"]:
        deal["advance_earned_out_cents"] = new_earned
        touch(deal)
    return success(public(stmt))


@bp.route("/royalty-statements/<statementId>/clear", methods=["POST"])
def clear_statement(statementId):
    ctx = guard(RA)
    parse_body([])
    stmt = get_scoped("royalty_statements", statementId, ctx)
    if stmt["status"] not in ("RECONCILED", "AUDIT_RESOLVED"):
        fail(ERR_STATE, 409,
             "statement is not RECONCILED or AUDIT_RESOLVED")
    if abs(stmt["variance_cents"]) > AUDIT_TOLERANCE_CENTS:
        fail(ERR_VAR_UNRESOLVED, 409, "variance exceeds audit tolerance")
    stmt["status"] = "CLEARED"
    touch(stmt)
    return success(public(stmt))


# ------------------------------------------------------- advance installments ----
@bp.route("/advance-installments/<installmentId>", methods=["GET"])
def get_installment(installmentId):
    ctx = guard(*ALL)
    return success(public(get_scoped("advance_installments", installmentId,
                                     ctx)))


@bp.route("/advance-installments", methods=["GET"])
def list_installments():
    ctx = guard(*ALL)
    return list_response("advance_installments", ctx, {
        "agency_id": "str", "status": "str", "deal_id": "str",
        "milestone": "str",
    })


@bp.route("/advance-installments/<installmentId>/mark-paid", methods=["POST"])
def mark_installment_paid(installmentId):
    ctx = guard(RA)
    parse_body([])
    inst = get_scoped("advance_installments", installmentId, ctx)
    if inst["status"] not in ("SCHEDULED", "DUE", "LATE"):
        fail(ERR_STATE, 409, "installment is not payable from its state")
    deal = DB["deals"].get(inst["deal_id"])
    if deal is None or deal["status"] not in ("EXECUTED", "ACTIVE"):
        fail(ERR_DEAL_NOT_LIVE, 409, "deal is not EXECUTED or ACTIVE")
    agency = DB["agencies"].get(inst["agency_id"])
    pct = commission_pct_for_deal(deal)
    inst["agency_commission_cents"] = floor_dec(
        Decimal(inst["amount_cents"]) * pct)
    inst["paid_period_index"] = agency["period_index"] if agency else None
    inst["status"] = "PAID"
    touch(inst)
    if deal["status"] == "EXECUTED":
        deal["status"] = "ACTIVE"
        touch(deal)
    return success(public(inst))
