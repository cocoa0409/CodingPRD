"""Settlement-run + commission-statement routes."""
from flask import Blueprint, request

import lookups
import serialize
import validate
import services.settlement as settle_svc
from db import store
from errors import err
from middleware import authenticate, authorize
from response import ok_array, ok_object
from util import parse_iso

bp = Blueprint("settlement", __name__)


# --------------------------------------------------------------------------- #
# Settlement runs
# --------------------------------------------------------------------------- #
@bp.route("/settlement-runs", methods=["POST"])
def create_run():
    _, role = authenticate()
    authorize(role, {"SettlementOfficer"})
    body = validate.get_body()
    atm_id = validate.require_str(body, "atm_id")
    window_start = validate.require_str(body, "window_start")
    window_end = validate.require_str(body, "window_end")
    lookups.atm(store, atm_id)
    if parse_iso(window_start) is None or parse_iso(window_end) is None:
        raise err("ERR_INVALID_REQUEST", "window must be ISO 8601 instants.")
    run = {
        "atm_id": atm_id,
        "window_start": window_start,
        "window_end": window_end,
        "withdrawal_count": 0,
        "surcharge_revenue_cents": 0,
        "interchange_revenue_cents": 0,
        "network_fee_cents": 0,
        "net_operator_revenue_cents": 0,
        "status": "DRAFT",
    }
    store.stamp_new(run)
    store.settlement_runs[run["id"]] = run
    return ok_object(store.clock, serialize.settlement_run(run), 201)


@bp.route("/settlement-runs/<rid>", methods=["GET"])
def get_run(rid):
    _, role = authenticate()
    authorize(role, {"PlatformAdmin", "SettlementOfficer"})
    run = lookups.settlement_run(store, rid)
    return ok_object(store.clock, serialize.settlement_run(run))


@bp.route("/settlement-runs", methods=["GET"])
def list_runs():
    _, role = authenticate()
    authorize(role, {"PlatformAdmin", "SettlementOfficer"})
    limit, offset = validate.parse_pagination(request.args)
    atm_id = request.args.get("atm_id")
    items = store.sorted_values(store.settlement_runs)
    if atm_id is not None:
        items = [r for r in items if r["atm_id"] == atm_id]
    page, total = validate.paginate([serialize.settlement_run(r) for r in items], limit, offset)
    return ok_array(store.clock, page, limit, offset, total)


@bp.route("/settlement-runs/<rid>/settle", methods=["POST"])
def settle_run(rid):
    _, role = authenticate()
    authorize(role, {"SettlementOfficer"})
    run = lookups.settlement_run(store, rid)
    # State guard (priority 6) — SETTLED is terminal.
    if run["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Run is not DRAFT.")
    atm = lookups.atm(store, run["atm_id"])
    # Preconditions: ERR_NO_FEE_DISCLOSURE (11) then ERR_TXN_ALREADY_SETTLED (18).
    settle_svc.check_can_settle(store, run, atm)
    settle_svc.settle(store, run, atm)
    return ok_object(store.clock, serialize.settlement_run(run))


# --------------------------------------------------------------------------- #
# Commission statements
# --------------------------------------------------------------------------- #
@bp.route("/commission-statements/<cid>", methods=["GET"])
def get_statement(cid):
    _, role = authenticate()
    authorize(role, {"PlatformAdmin", "SettlementOfficer"})
    s = lookups.commission_statement(store, cid)
    return ok_object(store.clock, serialize.commission_statement(s))


@bp.route("/commission-statements", methods=["GET"])
def list_statements():
    _, role = authenticate()
    authorize(role, {"PlatformAdmin", "SettlementOfficer"})
    limit, offset = validate.parse_pagination(request.args)
    settlement_run_id = request.args.get("settlement_run_id")
    site_merchant_id = request.args.get("site_merchant_id")
    items = store.sorted_values(store.commission_statements)
    if settlement_run_id is not None:
        items = [s for s in items if s["settlement_run_id"] == settlement_run_id]
    if site_merchant_id is not None:
        items = [s for s in items if s["site_merchant_id"] == site_merchant_id]
    page, total = validate.paginate(
        [serialize.commission_statement(s) for s in items], limit, offset)
    return ok_array(store.clock, page, limit, offset, total)


@bp.route("/commission-statements/<cid>/pay", methods=["POST"])
def pay_statement(cid):
    _, role = authenticate()
    authorize(role, {"SettlementOfficer"})
    s = lookups.commission_statement(store, cid)
    # State guard (priority 6).
    if s["status"] != "ACCRUED":
        raise err("ERR_INVALID_STATE", "Statement is not ACCRUED.")
    # ERR_MERCHANT_SUSPENDED (priority 19).
    merchant = store.site_merchants.get(s["site_merchant_id"])
    if merchant is None or merchant["payout_status"] != "ACTIVE":
        raise err("ERR_MERCHANT_SUSPENDED", "Merchant payout is suspended.")
    s["status"] = "PAID"
    store.touch(s)
    return ok_object(store.clock, serialize.commission_statement(s))


@bp.route("/commission-statements/<cid>/void", methods=["POST"])
def void_statement(cid):
    _, role = authenticate()
    authorize(role, {"SettlementOfficer"})
    s = lookups.commission_statement(store, cid)
    if s["status"] != "ACCRUED":
        raise err("ERR_INVALID_STATE", "Statement is not ACCRUED.")
    # Voiding frees ceiling headroom: month-to-date excludes VOIDED statements,
    # so simply flipping status to VOIDED removes this commission from MTD.
    s["status"] = "VOIDED"
    store.touch(s)
    return ok_object(store.clock, serialize.commission_statement(s))
