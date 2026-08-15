"""All API route handlers, registered on the shared Flask app."""

from datetime import timedelta
from decimal import Decimal

from flask import request

from app import app
from db import store, _parse_iso, _iso3
from errors import (
    err,
    ERR_NOT_FOUND,
    ERR_INVALID_STATE_TRANSITION,
    ERR_INVALID_REQUEST,
    ERR_FOREIGN_KEY_UNRESOLVABLE,
    ERR_CUSTOMER_SUSPENDED,
    ERR_ACCOUNT_RESTRICTED,
    ERR_TAX_YEAR_CLOSED,
    ERR_LOT_SCOPE_MISMATCH,
    ERR_INCOMPLETE_ACTION_PAYLOAD,
    ERR_INCOMPLETE_LOT_BASIS_DETAIL,
    ERR_LOT_ALLOCATION_MISMATCH,
    ERR_INSUFFICIENT_LOT_QUANTITY,
    ERR_SOD_VIOLATION,
    ERR_MISSING_SUPPORTING_DOC,
    ERR_CORRECTION_WINDOW_CLOSED,
    ERR_SUPERSEDE_TARGET_INVALID,
    ERR_TRANSFER_ALREADY_SUPERSEDED,
    ERR_TRANSFER_INSUFFICIENT_POSITION,
    ERR_TRANSFER_MISSING_LOT_DETAIL,
    ERR_FORM_FROZEN,
    ERR_ACCOUNT_HAS_OPEN_LOTS,
    ERR_CUSTOMER_HAS_OPEN_ACCOUNTS,
    ERR_PENDING_BASIS_REQUESTS,
    ERR_STALE_ACCOUNT_VERSION,
    ERR_STALE_LOT_VERSION,
    ERR_STALE_FORM_VERSION,
)
from middleware import require_roles, get_json_body, parse_pagination, customer_owns
from response import success_object, success_list
from services import (
    _touch, _new_entity, _dt, _iso, _round_half_up_cents,
    get_firm_or_404, get_customer_or_404, get_account_or_404,
    get_security_or_404, get_lot_or_404, get_disposition_or_404,
    get_corporate_action_or_404, get_transfer_statement_or_404,
    get_wash_sale_event_or_404, get_tax_form_or_404,
    get_basis_change_request_or_404,
    compute_covered_status, classify_term,
    settle_disposition, void_disposition, correct_disposition,
    aggregate_1099b, apply_corporate_action, freeze_expired_forms,
    _select_allocations, compute_realized_gain, detect_wash_sales,
    _validate_action_payload,
)


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------

def _serialize(entity):
    return dict(entity)


def _paginate(items, args):
    limit, offset = parse_pagination(args)
    items = sorted(items, key=lambda e: e["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return [_serialize(e) for e in page], limit, offset, total


def _filter_eq(items, field, value):
    if value is None:
        return items
    return [e for e in items if str(e.get(field)) == str(value)]


def _check_customer_scope(actor_uid, actor_role, entity, id_field="customer_id"):
    """Customer-role callers may only see their own resources."""
    if actor_role != "Customer":
        return
    cid = entity.get(id_field) or entity.get("id")
    if id_field == "customer_id":
        cid = entity.get("customer_id")
    if cid != actor_uid:
        raise err(ERR_NOT_FOUND, "Resource not found")


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    uid, role = require_roles(["FirmAdmin"])
    body = get_json_body()
    to_iso = body.get("to_iso8601")
    if not to_iso:
        raise err(ERR_INVALID_REQUEST, "to_iso8601 is required")
    store.set_clock(to_iso)
    freeze_expired_forms()
    return success_object({"current_utc": store.now_iso()})


# ---------------------------------------------------------------------------
# Firms
# ---------------------------------------------------------------------------

@app.route("/firms", methods=["POST"])
def create_firm():
    uid, role = require_roles(["FirmAdmin"])
    body = get_json_body()
    legal_name = body.get("legal_name")
    if not legal_name:
        raise err(ERR_INVALID_REQUEST, "legal_name is required")
    firm = _new_entity({
        "legal_name": legal_name,
        "tax_year_open": 2025,
        "wash_sale_window_days": 30,
        "correction_deadline_days": 1095,
    })
    store.firms[firm["id"]] = firm
    return success_object(_serialize(firm), 201)


@app.route("/firms/<firmId>", methods=["GET"])
def get_firm(firmId):
    uid, role = require_roles(["FirmAdmin", "TaxOps", "CustomerService", "Auditor", "Customer"])
    firm = get_firm_or_404(firmId)
    return success_object(_serialize(firm))


# ---------------------------------------------------------------------------
# Customers
# ---------------------------------------------------------------------------

@app.route("/firms/<firmId>/customers", methods=["POST"])
def create_customer(firmId):
    uid, role = require_roles(["FirmAdmin", "TaxOps"])
    firm = get_firm_or_404(firmId)
    body = get_json_body()
    tin = body.get("taxpayer_tin")
    name = body.get("display_name")
    if not tin or not name:
        raise err(ERR_INVALID_REQUEST, "taxpayer_tin and display_name are required")
    cust = _new_entity({
        "firm_id": firmId,
        "taxpayer_tin": tin,
        "display_name": name,
        "status": "ACTIVE",
        "wash_sale_scope_key": tin,
    })
    store.customers[cust["id"]] = cust
    return success_object(_serialize(cust), 201)


@app.route("/firms/<firmId>/customers", methods=["GET"])
def list_customers(firmId):
    uid, role = require_roles(["FirmAdmin", "TaxOps", "CustomerService", "Auditor"])
    firm = get_firm_or_404(firmId)
    items = [c for c in store.customers.values() if c["firm_id"] == firmId]
    items = _filter_eq(items, "status", request.args.get("status"))
    page, limit, offset, total = _paginate(items, request.args)
    return success_list(page, limit, offset, total)


@app.route("/firms/<firmId>/customers/<customerId>", methods=["GET"])
def get_customer(firmId, customerId):
    uid, role = require_roles(["FirmAdmin", "TaxOps", "CustomerService", "Auditor", "Customer"])
    firm = get_firm_or_404(firmId)
    cust = get_customer_or_404(firmId, customerId)
    _check_customer_scope(uid, role, cust, "customer_id")
    if role == "Customer" and uid != cust["id"]:
        raise err(ERR_NOT_FOUND, "Customer not found")
    return success_object(_serialize(cust))


@app.route("/firms/<firmId>/customers/<customerId>/suspend", methods=["POST"])
def suspend_customer(firmId, customerId):
    uid, role = require_roles(["FirmAdmin"])
    firm = get_firm_or_404(firmId)
    cust = get_customer_or_404(firmId, customerId)
    if cust["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE_TRANSITION, "Customer is not ACTIVE")
    cust["status"] = "SUSPENDED"
    _touch(cust)
    return success_object(_serialize(cust))


@app.route("/firms/<firmId>/customers/<customerId>/reinstate", methods=["POST"])
def reinstate_customer(firmId, customerId):
    uid, role = require_roles(["FirmAdmin"])
    firm = get_firm_or_404(firmId)
    cust = get_customer_or_404(firmId, customerId)
    if cust["status"] != "SUSPENDED":
        raise err(ERR_INVALID_STATE_TRANSITION, "Customer is not SUSPENDED")
    cust["status"] = "ACTIVE"
    _touch(cust)
    return success_object(_serialize(cust))


@app.route("/firms/<firmId>/customers/<customerId>/close", methods=["POST"])
def close_customer(firmId, customerId):
    uid, role = require_roles(["FirmAdmin"])
    firm = get_firm_or_404(firmId)
    cust = get_customer_or_404(firmId, customerId)
    if cust["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE_TRANSITION, "Customer is not ACTIVE")
    # Every account must be CLOSED
    for acct in store.accounts.values():
        if acct["customer_id"] == customerId and acct["status"] != "CLOSED":
            raise err(ERR_CUSTOMER_HAS_OPEN_ACCOUNTS,
                      "Every Account under this Customer must be CLOSED")
    # No pending basis change requests
    for r in store.basis_change_requests.values():
        if (r["customer_id"] == customerId
                and r["status"] in ("PENDING", "UNDER_REVIEW", "APPROVED")):
            raise err(ERR_PENDING_BASIS_REQUESTS,
                      "BasisChangeRequest is PENDING, UNDER_REVIEW, or APPROVED")
    cust["status"] = "CLOSED"
    _touch(cust)
    return success_object(_serialize(cust))


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------

@app.route("/firms/<firmId>/customers/<customerId>/accounts", methods=["POST"])
def create_account(firmId, customerId):
    uid, role = require_roles(["FirmAdmin", "TaxOps"])
    firm = get_firm_or_404(firmId)
    cust = get_customer_or_404(firmId, customerId)
    body = get_json_body()
    acct_num = body.get("account_number")
    acct_type = body.get("account_type")
    if not acct_num or not acct_type:
        raise err(ERR_INVALID_REQUEST, "account_number and account_type are required")
    if acct_type not in ("TAXABLE", "IRA", "ROTH_IRA"):
        raise err(ERR_INVALID_REQUEST, "account_type must be TAXABLE, IRA, or ROTH_IRA")
    method = body.get("default_disposal_method", "FIFO")
    if method not in ("FIFO", "LIFO", "HIFO", "SPECIFIC_ID"):
        raise err(ERR_INVALID_REQUEST, "default_disposal_method must be FIFO, LIFO, HIFO, or SPECIFIC_ID")
    acct = _new_entity({
        "firm_id": firmId,
        "customer_id": customerId,
        "account_number": acct_num,
        "account_type": acct_type,
        "default_disposal_method": method,
        "status": "OPEN",
    })
    store.accounts[acct["id"]] = acct
    return success_object(_serialize(acct), 201)


@app.route("/firms/<firmId>/customers/<customerId>/accounts", methods=["GET"])
def list_accounts_for_customer(firmId, customerId):
    uid, role = require_roles(["FirmAdmin", "TaxOps", "CustomerService", "Auditor", "Customer"])
    firm = get_firm_or_404(firmId)
    cust = get_customer_or_404(firmId, customerId)
    if role == "Customer" and uid != cust["id"]:
        raise err(ERR_NOT_FOUND, "Customer not found")
    items = [a for a in store.accounts.values()
             if a["firm_id"] == firmId and a["customer_id"] == customerId]
    items = _filter_eq(items, "status", request.args.get("status"))
    page, limit, offset, total = _paginate(items, request.args)
    return success_list(page, limit, offset, total)


@app.route("/firms/<firmId>/accounts/<accountId>", methods=["GET"])
def get_account(firmId, accountId):
    uid, role = require_roles(["FirmAdmin", "TaxOps", "CustomerService", "Auditor", "Customer"])
    firm = get_firm_or_404(firmId)
    acct = get_account_or_404(firmId, accountId)
    if role == "Customer" and uid != acct["customer_id"]:
        raise err(ERR_NOT_FOUND, "Account not found")
    return success_object(_serialize(acct))


@app.route("/firms/<firmId>/accounts/<accountId>/restrict", methods=["POST"])
def restrict_account(firmId, accountId):
    uid, role = require_roles(["FirmAdmin", "TaxOps"])
    firm = get_firm_or_404(firmId)
    acct = get_account_or_404(firmId, accountId)
    if acct["status"] != "OPEN":
        raise err(ERR_INVALID_STATE_TRANSITION, "Account is not OPEN")
    acct["status"] = "RESTRICTED"
    _touch(acct)
    return success_object(_serialize(acct))


@app.route("/firms/<firmId>/accounts/<accountId>/reopen", methods=["POST"])
def reopen_account(firmId, accountId):
    uid, role = require_roles(["FirmAdmin", "TaxOps"])
    firm = get_firm_or_404(firmId)
    acct = get_account_or_404(firmId, accountId)
    if acct["status"] != "RESTRICTED":
        raise err(ERR_INVALID_STATE_TRANSITION, "Account is not RESTRICTED")
    acct["status"] = "OPEN"
    _touch(acct)
    return success_object(_serialize(acct))


@app.route("/firms/<firmId>/accounts/<accountId>/close", methods=["POST"])
def close_account(firmId, accountId):
    uid, role = require_roles(["FirmAdmin", "TaxOps"])
    firm = get_firm_or_404(firmId)
    acct = get_account_or_404(firmId, accountId)
    if acct["status"] not in ("OPEN", "RESTRICTED"):
        raise err(ERR_INVALID_STATE_TRANSITION, "Account is not OPEN or RESTRICTED")
    for lot in store.tax_lots.values():
        if lot["account_id"] == accountId:
            if lot["lot_status"] not in ("FULLY_DISPOSED", "SUPERSEDED"):
                if Decimal(str(lot.get("quantity_remaining", 0))) > 0:
                    raise err(ERR_ACCOUNT_HAS_OPEN_LOTS,
                              "Account has lots with quantity_remaining > 0")
    acct["status"] = "CLOSED"
    _touch(acct)
    return success_object(_serialize(acct))


# ---------------------------------------------------------------------------
# Securities
# ---------------------------------------------------------------------------

@app.route("/firms/<firmId>/securities", methods=["POST"])
def create_security(firmId):
    uid, role = require_roles(["FirmAdmin", "TaxOps"])
    firm = get_firm_or_404(firmId)
    body = get_json_body()
    cusip = body.get("cusip")
    ticker = body.get("ticker")
    stype = body.get("security_type")
    eff_date = body.get("covered_security_effective_date")
    if not cusip or not ticker or not stype or not eff_date:
        raise err(ERR_INVALID_REQUEST,
                  "cusip, ticker, security_type, covered_security_effective_date are required")
    if stype not in ("EQUITY", "CORPORATE_BOND", "OPTION", "MUTUAL_FUND"):
        raise err(ERR_INVALID_REQUEST, "Invalid security_type")
    sec = _new_entity({
        "firm_id": firmId,
        "cusip": cusip,
        "ticker": ticker,
        "security_type": stype,
        "covered_security_effective_date": eff_date,
    })
    store.securities[sec["id"]] = sec
    return success_object(_serialize(sec), 201)


@app.route("/firms/<firmId>/securities/<securityId>", methods=["GET"])
def get_security(firmId, securityId):
    uid, role = require_roles(["FirmAdmin", "TaxOps", "CustomerService", "Auditor", "Customer"])
    firm = get_firm_or_404(firmId)
    sec = get_security_or_404(firmId, securityId)
    return success_object(_serialize(sec))


@app.route("/firms/<firmId>/securities", methods=["GET"])
def list_securities(firmId):
    uid, role = require_roles(["FirmAdmin", "TaxOps", "CustomerService", "Auditor", "Customer"])
    firm = get_firm_or_404(firmId)
    items = [s for s in store.securities.values() if s["firm_id"] == firmId]
    items = _filter_eq(items, "cusip", request.args.get("cusip"))
    items = _filter_eq(items, "security_type", request.args.get("security_type"))
    page, limit, offset, total = _paginate(items, request.args)
    return success_list(page, limit, offset, total)


# ---------------------------------------------------------------------------
# Tax Lots
# ---------------------------------------------------------------------------

@app.route("/firms/<firmId>/accounts/<accountId>/tax_lots", methods=["POST"])
def create_tax_lot(firmId, accountId):
    uid, role = require_roles(["FirmAdmin", "TaxOps", "CustomerService"])
    firm = get_firm_or_404(firmId)
    acct = get_account_or_404(firmId, accountId)
    body = get_json_body()

    sec_id = body.get("security_id")
    acq_date = body.get("acquisition_date")
    quantity = body.get("quantity")
    orig_basis = body.get("original_cost_basis_cents")
    kind = body.get("acquisition_kind", "PURCHASE")

    if not sec_id or not acq_date or quantity is None:
        raise err(ERR_INVALID_REQUEST,
                  "security_id, acquisition_date, quantity are required")

    # FK resolution
    sec = store.securities.get(sec_id)
    if sec is None or sec["firm_id"] != firmId:
        raise err(ERR_FOREIGN_KEY_UNRESOLVABLE,
                  "security_id does not resolve in this firm")

    if kind not in ("PURCHASE", "GIFT", "INHERITANCE", "TRANSFER_IN", "CORPORATE_ACTION_DERIVED"):
        raise err(ERR_INVALID_REQUEST, "Invalid acquisition_kind")

    # Kind-specific required fields
    gift_donor = body.get("gift_donor_basis_cents")
    gift_fmv = body.get("gift_fmv_cents_at_gift")
    inh_fmv = body.get("inherited_fmv_cents_at_death")

    if kind == "GIFT":
        if gift_donor is None or gift_fmv is None:
            raise err(ERR_INCOMPLETE_LOT_BASIS_DETAIL,
                      "GIFT requires gift_donor_basis_cents and gift_fmv_cents_at_gift")
    if kind == "INHERITANCE":
        if inh_fmv is None:
            raise err(ERR_INCOMPLETE_LOT_BASIS_DETAIL,
                      "INHERITANCE requires inherited_fmv_cents_at_death")

    if orig_basis is None and kind != "INHERITANCE":
        raise err(ERR_INVALID_REQUEST, "original_cost_basis_cents is required")

    # Compute covered status
    covered = compute_covered_status(kind, acq_date, sec)

    # Basis
    if kind == "INHERITANCE":
        adj_basis = inh_fmv
        if orig_basis is None:
            orig_basis = inh_fmv
    else:
        adj_basis = orig_basis

    lot = _new_entity({
        "firm_id": firmId,
        "account_id": accountId,
        "security_id": sec_id,
        "acquisition_date": acq_date,
        "quantity": quantity,
        "quantity_remaining": quantity,
        "original_cost_basis_cents": orig_basis,
        "adjusted_cost_basis_cents": adj_basis,
        "acquisition_kind": kind,
        "gift_donor_basis_cents": gift_donor,
        "gift_fmv_cents_at_gift": gift_fmv,
        "inherited_fmv_cents_at_death": inh_fmv,
        "holding_period_start": acq_date,
        "wash_sale_taint_basis_cents": 0,
        "covered_status": covered,
        "lot_status": "OPEN",
        "superseded_by_action_id": None,
    })
    store.tax_lots[lot["id"]] = lot
    return success_object(_serialize(lot), 201)


@app.route("/firms/<firmId>/tax_lots/<lotId>", methods=["GET"])
def get_tax_lot(firmId, lotId):
    uid, role = require_roles(["FirmAdmin", "TaxOps", "CustomerService", "Auditor", "Customer"])
    firm = get_firm_or_404(firmId)
    lot = get_lot_or_404(firmId, lotId)
    if role == "Customer":
        acct = store.accounts.get(lot["account_id"])
        if acct is None or uid != acct["customer_id"]:
            raise err(ERR_NOT_FOUND, "TaxLot not found")
    return success_object(_serialize(lot))


@app.route("/firms/<firmId>/accounts/<accountId>/tax_lots", methods=["GET"])
def list_tax_lots(firmId, accountId):
    uid, role = require_roles(["FirmAdmin", "TaxOps", "CustomerService", "Auditor", "Customer"])
    firm = get_firm_or_404(firmId)
    acct = get_account_or_404(firmId, accountId)
    if role == "Customer" and uid != acct["customer_id"]:
        raise err(ERR_NOT_FOUND, "Account not found")
    items = [l for l in store.tax_lots.values()
             if l["firm_id"] == firmId and l["account_id"] == accountId]
    items = _filter_eq(items, "security_id", request.args.get("security_id"))
    items = _filter_eq(items, "lot_status", request.args.get("lot_status"))
    items = _filter_eq(items, "covered_status", request.args.get("covered_status"))
    items = _filter_eq(items, "acquisition_kind", request.args.get("acquisition_kind"))
    page, limit, offset, total = _paginate(items, request.args)
    return success_list(page, limit, offset, total)


# ---------------------------------------------------------------------------
# Dispositions
# ---------------------------------------------------------------------------

@app.route("/firms/<firmId>/accounts/<accountId>/dispositions", methods=["POST"])
def create_disposition(firmId, accountId):
    uid, role = require_roles(["FirmAdmin", "TaxOps", "CustomerService"])
    firm = get_firm_or_404(firmId)
    acct = get_account_or_404(firmId, accountId)
    body = get_json_body()

    # Customer standing check
    cust = store.customers.get(acct["customer_id"])
    if cust and cust["status"] in ("SUSPENDED", "CLOSED"):
        raise err(ERR_CUSTOMER_SUSPENDED,
                  "Customer is SUSPENDED or CLOSED")

    # Account standing check
    if acct["status"] != "OPEN":
        raise err(ERR_ACCOUNT_RESTRICTED,
                  "Account is not OPEN")

    sec_id = body.get("security_id")
    trade_date = body.get("trade_date")
    settlement_date = body.get("settlement_date")
    quantity = body.get("quantity")
    proceeds = body.get("proceeds_cents")

    if not all([sec_id, trade_date, settlement_date, quantity is not None, proceeds is not None]):
        raise err(ERR_INVALID_REQUEST,
                  "security_id, trade_date, settlement_date, quantity, proceeds_cents are required")

    # FK resolution
    sec = store.securities.get(sec_id)
    if sec is None or sec["firm_id"] != firmId:
        raise err(ERR_FOREIGN_KEY_UNRESOLVABLE,
                  "security_id does not resolve in this firm")

    # Tax year check
    td = _dt(trade_date)
    tax_year_start = _dt(f"{firm['tax_year_open']}-01-01T00:00:00Z")
    if td < tax_year_start:
        raise err(ERR_TAX_YEAR_CLOSED,
                  f"trade_date is before {firm['tax_year_open']}-01-01")

    method = body.get("method", acct["default_disposal_method"])
    lot_allocations = body.get("lot_allocations")

    # Lot scope check for SPECIFIC_ID
    if method == "SPECIFIC_ID" and lot_allocations:
        for a in lot_allocations:
            lot = store.tax_lots.get(a.get("lot_id"))
            if lot is None:
                raise err(ERR_LOT_SCOPE_MISMATCH,
                          f"lot {a.get('lot_id')} not found")
            if lot["account_id"] != accountId or lot["security_id"] != sec_id:
                raise err(ERR_LOT_SCOPE_MISMATCH,
                          "SPECIFIC_ID lot not on this Account+Security")

    # Fiscal sanity
    if Decimal(str(quantity)) <= 0:
        raise err(ERR_INVALID_REQUEST, "quantity must be > 0")
    if proceeds < 0:
        raise err(ERR_INVALID_REQUEST, "proceeds_cents must be >= 0")
    if lot_allocations:
        for a in lot_allocations:
            if Decimal(str(a.get("quantity", 0))) <= 0:
                raise err(ERR_INVALID_REQUEST,
                          "per-allocation quantities must be > 0")

    # Allocation sum check for SPECIFIC_ID
    if method == "SPECIFIC_ID" and lot_allocations:
        total = sum(Decimal(str(a["quantity"])) for a in lot_allocations)
        if total != Decimal(str(quantity)):
            raise err(ERR_LOT_ALLOCATION_MISMATCH,
                      "sum(lot_allocations.quantity) != Disposition.quantity")

    disp = _new_entity({
        "firm_id": firmId,
        "account_id": accountId,
        "security_id": sec_id,
        "trade_date": trade_date,
        "settlement_date": settlement_date,
        "quantity": quantity,
        "proceeds_cents": proceeds,
        "method": method,
        "lot_allocations": lot_allocations,
        "status": "PENDING",
        "realized_gain_cents": 0,
        "is_wash_sale_flag": False,
        "wash_sale_disallowed_loss_cents": 0,
    })
    store.dispositions[disp["id"]] = disp
    return success_object(_serialize(disp), 201)


@app.route("/firms/<firmId>/dispositions/<dispositionId>", methods=["GET"])
def get_disposition(firmId, dispositionId):
    uid, role = require_roles(["FirmAdmin", "TaxOps", "CustomerService", "Auditor", "Customer"])
    firm = get_firm_or_404(firmId)
    disp = get_disposition_or_404(firmId, dispositionId)
    if role == "Customer":
        acct = store.accounts.get(disp["account_id"])
        if acct is None or uid != acct["customer_id"]:
            raise err(ERR_NOT_FOUND, "Disposition not found")
    return success_object(_serialize(disp))


@app.route("/firms/<firmId>/accounts/<accountId>/dispositions", methods=["GET"])
def list_dispositions(firmId, accountId):
    uid, role = require_roles(["FirmAdmin", "TaxOps", "CustomerService", "Auditor", "Customer"])
    firm = get_firm_or_404(firmId)
    acct = get_account_or_404(firmId, accountId)
    if role == "Customer" and uid != acct["customer_id"]:
        raise err(ERR_NOT_FOUND, "Account not found")
    items = [d for d in store.dispositions.values()
             if d["firm_id"] == firmId and d["account_id"] == accountId]
    items = _filter_eq(items, "security_id", request.args.get("security_id"))
    items = _filter_eq(items, "status", request.args.get("status"))
    tax_year = request.args.get("tax_year")
    if tax_year is not None:
        items = [d for d in items if _dt(d["trade_date"]).year == int(tax_year)]
    page, limit, offset, total = _paginate(items, request.args)
    return success_list(page, limit, offset, total)


@app.route("/firms/<firmId>/dispositions/<dispositionId>/settle", methods=["POST"])
def settle_disposition_route(firmId, dispositionId):
    uid, role = require_roles(["TaxOps"])
    firm = get_firm_or_404(firmId)
    disp = get_disposition_or_404(firmId, dispositionId)
    settle_disposition(disp, uid)
    return success_object(_serialize(disp))


@app.route("/firms/<firmId>/dispositions/<dispositionId>/void", methods=["POST"])
def void_disposition_route(firmId, dispositionId):
    uid, role = require_roles(["TaxOps"])
    firm = get_firm_or_404(firmId)
    disp = get_disposition_or_404(firmId, dispositionId)
    void_disposition(disp)
    return success_object(_serialize(disp))


@app.route("/firms/<firmId>/dispositions/<dispositionId>/correct", methods=["POST"])
def correct_disposition_route(firmId, dispositionId):
    uid, role = require_roles(["TaxOps"])
    firm = get_firm_or_404(firmId)
    disp = get_disposition_or_404(firmId, dispositionId)
    body = get_json_body(required=False) or {}
    correct_disposition(disp, body)
    return success_object(_serialize(disp))


@app.route("/firms/<firmId>/dispositions/<dispositionId>/preview_gain", methods=["GET"])
def preview_gain(firmId, dispositionId):
    uid, role = require_roles(["TaxOps", "CustomerService", "FirmAdmin"])
    firm = get_firm_or_404(firmId)
    disp = get_disposition_or_404(firmId, dispositionId)
    if disp["status"] != "PENDING":
        raise err(ERR_INVALID_STATE_TRANSITION,
                  "preview_gain requires a PENDING disposition")
    acct = store.accounts[disp["account_id"]]
    lots_by_id = {l["id"]: l for l in store.tax_lots.values() if l["firm_id"] == firmId}
    allocations, total_basis = _select_allocations(disp, acct, lots_by_id, preview=True)
    realized = compute_realized_gain(disp, allocations, total_basis)
    return success_object({
        "realized_gain_cents": realized,
        "allocations": [
            {"lot_id": a["lot_id"], "quantity": a["quantity"],
             "allocation_basis_cents": a["allocation_basis_cents"],
             "term": a["term"]}
            for a in allocations
        ],
    })


@app.route("/firms/<firmId>/dispositions/<dispositionId>/preview_wash_sale", methods=["GET"])
def preview_wash_sale(firmId, dispositionId):
    uid, role = require_roles(["TaxOps", "CustomerService", "FirmAdmin"])
    firm = get_firm_or_404(firmId)
    disp = get_disposition_or_404(firmId, dispositionId)
    if disp["status"] != "PENDING":
        raise err(ERR_INVALID_STATE_TRANSITION,
                  "preview_wash_sale requires a PENDING disposition")
    acct = store.accounts[disp["account_id"]]
    lots_by_id = {l["id"]: l for l in store.tax_lots.values() if l["firm_id"] == firmId}
    allocations, total_basis = _select_allocations(disp, acct, lots_by_id, preview=True)
    realized = compute_realized_gain(disp, allocations, total_basis)
    if realized >= 0:
        return success_object({"would_trigger": False, "candidate_lot_ids": []})
    # Same-account-only detection
    firm_obj = store.firms[firmId]
    half = firm_obj["wash_sale_window_days"]
    trade_dt = _dt(disp["trade_date"])
    window_start = trade_dt - timedelta(days=half)
    window_end = trade_dt + timedelta(days=half)
    sold_sec = store.securities[disp["security_id"]]
    candidate_ids = []
    for lot in store.tax_lots.values():
        if lot["firm_id"] != firmId or lot["account_id"] != disp["account_id"]:
            continue
        sec = store.securities.get(lot["security_id"])
        if sec is None or sec["cusip"] != sold_sec["cusip"]:
            continue
        acq = _dt(lot["acquisition_date"])
        if not (window_start <= acq <= window_end):
            continue
        if lot["lot_status"] not in ("OPEN", "PARTIALLY_DISPOSED"):
            continue
        sold_lot_ids = {a["lot_id"] for a in allocations}
        if lot["id"] in sold_lot_ids:
            continue
        candidate_ids.append(lot["id"])
    return success_object({
        "would_trigger": len(candidate_ids) > 0,
        "candidate_lot_ids": sorted(candidate_ids),
    })


# ---------------------------------------------------------------------------
# Corporate Actions
# ---------------------------------------------------------------------------

@app.route("/firms/<firmId>/securities/<securityId>/corporate_actions", methods=["POST"])
def create_corporate_action(firmId, securityId):
    uid, role = require_roles(["FirmAdmin", "TaxOps"])
    firm = get_firm_or_404(firmId)
    sec = get_security_or_404(firmId, securityId)
    body = get_json_body()
    at = body.get("action_type")
    eff = body.get("effective_date")
    if not at or not eff:
        raise err(ERR_INVALID_REQUEST, "action_type and effective_date are required")
    if at not in ("SPLIT", "REVERSE_SPLIT", "MERGER", "SPINOFF"):
        raise err(ERR_INVALID_REQUEST, "Invalid action_type")

    action = _new_entity({
        "firm_id": firmId,
        "security_id": securityId,
        "action_type": at,
        "effective_date": eff,
        "split_ratio_numerator": body.get("split_ratio_numerator"),
        "split_ratio_denominator": body.get("split_ratio_denominator"),
        "merger_acquirer_security_id": body.get("merger_acquirer_security_id"),
        "merger_cash_per_share_cents": body.get("merger_cash_per_share_cents"),
        "merger_shares_per_source_share": body.get("merger_shares_per_source_share"),
        "spinoff_cost_allocation_pct": body.get("spinoff_cost_allocation_pct"),
        "status": "ANNOUNCED",
    })

    # Validate payload consistency at creation
    _validate_action_payload(action)

    store.corporate_actions[action["id"]] = action
    return success_object(_serialize(action), 201)


@app.route("/firms/<firmId>/corporate_actions/<actionId>", methods=["GET"])
def get_corporate_action(firmId, actionId):
    uid, role = require_roles(["FirmAdmin", "TaxOps", "CustomerService", "Auditor", "Customer"])
    firm = get_firm_or_404(firmId)
    action = get_corporate_action_or_404(firmId, actionId)
    return success_object(_serialize(action))


@app.route("/firms/<firmId>/securities/<securityId>/corporate_actions", methods=["GET"])
def list_corporate_actions(firmId, securityId):
    uid, role = require_roles(["FirmAdmin", "TaxOps", "CustomerService", "Auditor", "Customer"])
    firm = get_firm_or_404(firmId)
    sec = get_security_or_404(firmId, securityId)
    items = [a for a in store.corporate_actions.values()
             if a["firm_id"] == firmId and a["security_id"] == securityId]
    items = _filter_eq(items, "status", request.args.get("status"))
    page, limit, offset, total = _paginate(items, request.args)
    return success_list(page, limit, offset, total)


@app.route("/firms/<firmId>/corporate_actions/<actionId>/apply", methods=["POST"])
def apply_corporate_action_route(firmId, actionId):
    uid, role = require_roles(["TaxOps"])
    firm = get_firm_or_404(firmId)
    action = get_corporate_action_or_404(firmId, actionId)
    apply_corporate_action(action)
    return success_object(_serialize(action))


@app.route("/firms/<firmId>/corporate_actions/<actionId>/cancel", methods=["POST"])
def cancel_corporate_action(firmId, actionId):
    uid, role = require_roles(["TaxOps"])
    firm = get_firm_or_404(firmId)
    action = get_corporate_action_or_404(firmId, actionId)
    if action["status"] != "ANNOUNCED":
        raise err(ERR_INVALID_STATE_TRANSITION,
                  "CorporateAction is not ANNOUNCED")
    action["status"] = "CANCELLED"
    _touch(action)
    return success_object(_serialize(action))


# ---------------------------------------------------------------------------
# Transfer Statements
# ---------------------------------------------------------------------------

@app.route("/firms/<firmId>/accounts/<accountId>/transfer_statements", methods=["POST"])
def create_transfer_statement(firmId, accountId):
    uid, role = require_roles(["TaxOps", "FirmAdmin"])
    firm = get_firm_or_404(firmId)
    acct = get_account_or_404(firmId, accountId)
    body = get_json_body()

    direction = body.get("direction")
    counterparty = body.get("counterparty_firm_name")
    sec_id = body.get("security_id")
    quantity = body.get("quantity")
    transfer_date = body.get("transfer_date")

    if not all([direction, counterparty, sec_id, quantity is not None, transfer_date]):
        raise err(ERR_INVALID_REQUEST,
                  "direction, counterparty_firm_name, security_id, quantity, transfer_date are required")

    if direction not in ("INBOUND", "OUTBOUND"):
        raise err(ERR_INVALID_REQUEST, "direction must be INBOUND or OUTBOUND")

    # Account standing for OUTBOUND
    if direction == "OUTBOUND" and acct["status"] != "OPEN":
        raise err(ERR_ACCOUNT_RESTRICTED,
                  "Account is not OPEN for OUTBOUND transfer")

    # FK resolution
    sec = store.securities.get(sec_id)
    if sec is None or sec["firm_id"] != firmId:
        raise err(ERR_FOREIGN_KEY_UNRESOLVABLE,
                  "security_id does not resolve in this firm")

    # Supersede target check
    replaces_id = body.get("replaces_statement_id")
    if replaces_id:
        target = store.transfer_statements.get(replaces_id)
        if target is None or target["firm_id"] != firmId or target["status"] != "DELIVERED":
            raise err(ERR_SUPERSEDE_TARGET_INVALID,
                      "replaces_statement_id must reference a DELIVERED statement")

    stmt = _new_entity({
        "firm_id": firmId,
        "account_id": accountId,
        "direction": direction,
        "counterparty_firm_name": counterparty,
        "security_id": sec_id,
        "quantity": quantity,
        "transfer_date": transfer_date,
        "lots_payload": body.get("lots_payload"),
        "status": "PENDING",
        "replaces_statement_id": replaces_id,
    })
    store.transfer_statements[stmt["id"]] = stmt
    return success_object(_serialize(stmt), 201)


@app.route("/firms/<firmId>/transfer_statements/<stmtId>", methods=["GET"])
def get_transfer_statement(firmId, stmtId):
    uid, role = require_roles(["FirmAdmin", "TaxOps", "CustomerService", "Auditor"])
    firm = get_firm_or_404(firmId)
    stmt = get_transfer_statement_or_404(firmId, stmtId)
    return success_object(_serialize(stmt))


@app.route("/firms/<firmId>/accounts/<accountId>/transfer_statements", methods=["GET"])
def list_transfer_statements(firmId, accountId):
    uid, role = require_roles(["FirmAdmin", "TaxOps", "CustomerService", "Auditor"])
    firm = get_firm_or_404(firmId)
    acct = get_account_or_404(firmId, accountId)
    items = [s for s in store.transfer_statements.values()
             if s["firm_id"] == firmId and s["account_id"] == accountId]
    items = _filter_eq(items, "direction", request.args.get("direction"))
    items = _filter_eq(items, "status", request.args.get("status"))
    page, limit, offset, total = _paginate(items, request.args)
    return success_list(page, limit, offset, total)


@app.route("/firms/<firmId>/transfer_statements/<stmtId>/deliver", methods=["POST"])
def deliver_transfer_statement(firmId, stmtId):
    uid, role = require_roles(["TaxOps"])
    firm = get_firm_or_404(firmId)
    stmt = get_transfer_statement_or_404(firmId, stmtId)
    if stmt["status"] != "PENDING":
        raise err(ERR_INVALID_STATE_TRANSITION,
                  "TransferStatement is not PENDING")

    acct = store.accounts[stmt["account_id"]]

    # OCC check
    body = get_json_body(required=False) or {}
    expected_version = body.get("expected_account_version")
    if expected_version is not None and expected_version != acct["version"]:
        raise err(ERR_STALE_ACCOUNT_VERSION,
                  "expected_account_version does not match Account.version")

    # Lot detail required
    if not stmt.get("lots_payload"):
        raise err(ERR_TRANSFER_MISSING_LOT_DETAIL,
                  "lots_payload is required before delivery")

    if stmt["direction"] == "OUTBOUND":
        # Check sufficient position
        total_remaining = sum(
            Decimal(str(l["quantity_remaining"]))
            for l in store.tax_lots.values()
            if l["account_id"] == stmt["account_id"]
            and l["security_id"] == stmt["security_id"]
            and l["lot_status"] in ("OPEN", "PARTIALLY_DISPOSED")
        )
        if total_remaining < Decimal(str(stmt["quantity"])):
            raise err(ERR_TRANSFER_INSUFFICIENT_POSITION,
                      "Source account does not hold enough shares")

        # Consume lots in account's default_disposal_method order
        candidates = [
            l for l in store.tax_lots.values()
            if l["account_id"] == stmt["account_id"]
            and l["security_id"] == stmt["security_id"]
            and l["lot_status"] in ("OPEN", "PARTIALLY_DISPOSED")
            and Decimal(str(l["quantity_remaining"])) > 0
        ]
        method = acct["default_disposal_method"]
        if method == "FIFO":
            candidates.sort(key=lambda l: (_dt(l["acquisition_date"]), _dt(l["created_at"])))
        elif method == "LIFO":
            candidates.sort(key=lambda l: (_dt(l["acquisition_date"]), _dt(l["created_at"])), reverse=True)
        elif method == "HIFO":
            from services import _per_share_basis_cents
            candidates.sort(key=lambda l: (-_per_share_basis_cents(l), _dt(l["created_at"])))

        needed = Decimal(str(stmt["quantity"]))
        for lot in candidates:
            if needed <= 0:
                break
            take = min(Decimal(str(lot["quantity_remaining"])), needed)
            lot["quantity_remaining"] = float(Decimal(str(lot["quantity_remaining"])) - take)
            if Decimal(str(lot["quantity_remaining"])) <= 0:
                lot["quantity_remaining"] = 0
                lot["lot_status"] = "FULLY_DISPOSED"
            else:
                lot["lot_status"] = "PARTIALLY_DISPOSED"
            _touch(lot)
            needed -= take

        _touch(acct)

    # Handle supersession
    if stmt.get("replaces_statement_id"):
        old = store.transfer_statements.get(stmt["replaces_statement_id"])
        if old and old["status"] == "DELIVERED":
            # Restore old outbound lots
            if old["direction"] == "OUTBOUND":
                for l in store.tax_lots.values():
                    if (l["account_id"] == old["account_id"]
                            and l["security_id"] == old["security_id"]
                            and l["lot_status"] in ("FULLY_DISPOSED", "PARTIALLY_DISPOSED")):
                        # Restore quantity from the old lots_payload
                        for entry in (old.get("lots_payload") or []):
                            # Best-effort restore by matching acquisition_date
                            if l["acquisition_date"] == entry.get("acquisition_date"):
                                l["quantity_remaining"] = float(
                                    Decimal(str(l["quantity_remaining"])) + Decimal(str(entry.get("quantity", 0)))
                                )
                                if Decimal(str(l["quantity_remaining"])) >= Decimal(str(l["quantity"])):
                                    l["lot_status"] = "OPEN"
                                else:
                                    l["lot_status"] = "PARTIALLY_DISPOSED"
                                _touch(l)
            old["status"] = "SUPERSEDED"
            _touch(old)

    stmt["status"] = "DELIVERED"
    _touch(stmt)
    return success_object(_serialize(stmt))


@app.route("/firms/<firmId>/transfer_statements/<stmtId>/accept", methods=["POST"])
def accept_transfer_statement(firmId, stmtId):
    uid, role = require_roles(["TaxOps"])
    firm = get_firm_or_404(firmId)
    stmt = get_transfer_statement_or_404(firmId, stmtId)
    if stmt["status"] != "DELIVERED":
        raise err(ERR_INVALID_STATE_TRANSITION,
                  "TransferStatement is not DELIVERED")

    if stmt["direction"] == "INBOUND":
        # Materialize lots
        sec = store.securities.get(stmt["security_id"])
        for entry in (stmt.get("lots_payload") or []):
            covered = compute_covered_status(
                "TRANSFER_IN", entry["acquisition_date"], sec
            )
            lot = _new_entity({
                "firm_id": firmId,
                "account_id": stmt["account_id"],
                "security_id": stmt["security_id"],
                "acquisition_date": entry["acquisition_date"],
                "quantity": entry["quantity"],
                "quantity_remaining": entry["quantity"],
                "original_cost_basis_cents": entry["original_cost_basis_cents"],
                "adjusted_cost_basis_cents": entry["original_cost_basis_cents"],
                "acquisition_kind": "TRANSFER_IN",
                "gift_donor_basis_cents": None,
                "gift_fmv_cents_at_gift": None,
                "inherited_fmv_cents_at_death": None,
                "holding_period_start": entry["acquisition_date"],
                "wash_sale_taint_basis_cents": 0,
                "covered_status": covered,
                "lot_status": "OPEN",
                "superseded_by_action_id": None,
            })
            store.tax_lots[lot["id"]] = lot

    stmt["status"] = "ACCEPTED"
    _touch(stmt)
    return success_object(_serialize(stmt))


@app.route("/firms/<firmId>/transfer_statements/<stmtId>/reject", methods=["POST"])
def reject_transfer_statement(firmId, stmtId):
    uid, role = require_roles(["TaxOps"])
    firm = get_firm_or_404(firmId)
    stmt = get_transfer_statement_or_404(firmId, stmtId)
    if stmt["status"] != "DELIVERED":
        raise err(ERR_INVALID_STATE_TRANSITION,
                  "TransferStatement is not DELIVERED")

    if stmt["direction"] == "OUTBOUND":
        # Restore consumed lots
        for entry in (stmt.get("lots_payload") or []):
            for l in store.tax_lots.values():
                if (l["account_id"] == stmt["account_id"]
                        and l["security_id"] == stmt["security_id"]
                        and l["acquisition_date"] == entry.get("acquisition_date")):
                    l["quantity_remaining"] = float(
                        Decimal(str(l["quantity_remaining"])) + Decimal(str(entry.get("quantity", 0)))
                    )
                    if Decimal(str(l["quantity_remaining"])) >= Decimal(str(l["quantity"])):
                        l["lot_status"] = "OPEN"
                    elif Decimal(str(l["quantity_remaining"])) > 0:
                        l["lot_status"] = "PARTIALLY_DISPOSED"
                    _touch(l)

    stmt["status"] = "REJECTED"
    _touch(stmt)
    return success_object(_serialize(stmt))


@app.route("/firms/<firmId>/transfer_statements/<stmtId>/redeliver", methods=["POST"])
def redeliver_transfer_statement(firmId, stmtId):
    uid, role = require_roles(["TaxOps"])
    firm = get_firm_or_404(firmId)
    stmt = get_transfer_statement_or_404(firmId, stmtId)
    if stmt["status"] != "REJECTED":
        raise err(ERR_INVALID_STATE_TRANSITION,
                  "TransferStatement is not REJECTED")

    # Check no DELIVERED replacement exists
    for s in store.transfer_statements.values():
        if (s.get("replaces_statement_id") == stmtId
                and s["status"] == "DELIVERED"):
            raise err(ERR_TRANSFER_ALREADY_SUPERSEDED,
                      "A replacement statement has already reached DELIVERED")

    stmt["status"] = "PENDING"
    _touch(stmt)
    return success_object(_serialize(stmt))


# ---------------------------------------------------------------------------
# Wash Sale Events
# ---------------------------------------------------------------------------

@app.route("/firms/<firmId>/wash_sale_events/<eventId>", methods=["GET"])
def get_wash_sale_event(firmId, eventId):
    uid, role = require_roles(["FirmAdmin", "TaxOps", "CustomerService", "Auditor"])
    firm = get_firm_or_404(firmId)
    ev = get_wash_sale_event_or_404(firmId, eventId)
    return success_object(_serialize(ev))


@app.route("/firms/<firmId>/dispositions/<dispositionId>/wash_sale_events", methods=["GET"])
def list_wash_sale_events_for_disposition(firmId, dispositionId):
    uid, role = require_roles(["FirmAdmin", "TaxOps", "CustomerService", "Auditor"])
    firm = get_firm_or_404(firmId)
    disp = get_disposition_or_404(firmId, dispositionId)
    items = [e for e in store.wash_sale_events.values()
             if e["firm_id"] == firmId and e["disposition_id"] == dispositionId]
    page, limit, offset, total = _paginate(items, request.args)
    return success_list(page, limit, offset, total)


# ---------------------------------------------------------------------------
# Tax Forms 1099-B
# ---------------------------------------------------------------------------

@app.route("/firms/<firmId>/customers/<customerId>/tax_forms_1099b", methods=["POST"])
def create_tax_form(firmId, customerId):
    uid, role = require_roles(["TaxOps", "FirmAdmin"])
    firm = get_firm_or_404(firmId)
    cust = get_customer_or_404(firmId, customerId)
    body = get_json_body()
    tax_year = body.get("tax_year")
    if tax_year is None:
        raise err(ERR_INVALID_REQUEST, "tax_year is required")
    form = _new_entity({
        "firm_id": firmId,
        "customer_id": customerId,
        "tax_year": int(tax_year),
        "status": "DRAFT",
        "short_term_proceeds_cents": 0,
        "short_term_basis_cents": 0,
        "short_term_gain_cents": 0,
        "long_term_proceeds_cents": 0,
        "long_term_basis_cents": 0,
        "long_term_gain_cents": 0,
        "disallowed_wash_sale_loss_cents": 0,
        "filed_at": None,
        "correction_count": 0,
        "generated_from_version": cust["version"],
    })
    store.tax_forms[form["id"]] = form
    return success_object(_serialize(form), 201)


@app.route("/firms/<firmId>/customers/<customerId>/tax_forms_1099b/<formId>", methods=["GET"])
def get_tax_form(firmId, customerId, formId):
    uid, role = require_roles(["FirmAdmin", "TaxOps", "CustomerService", "Auditor", "Customer"])
    firm = get_firm_or_404(firmId)
    cust = get_customer_or_404(firmId, customerId)
    if role == "Customer" and uid != cust["id"]:
        raise err(ERR_NOT_FOUND, "Customer not found")
    form = get_tax_form_or_404(firmId, customerId, formId)
    return success_object(_serialize(form))


@app.route("/firms/<firmId>/customers/<customerId>/tax_forms_1099b", methods=["GET"])
def list_tax_forms(firmId, customerId):
    uid, role = require_roles(["FirmAdmin", "TaxOps", "CustomerService", "Auditor", "Customer"])
    firm = get_firm_or_404(firmId)
    cust = get_customer_or_404(firmId, customerId)
    if role == "Customer" and uid != cust["id"]:
        raise err(ERR_NOT_FOUND, "Customer not found")
    items = [f for f in store.tax_forms.values()
             if f["firm_id"] == firmId and f["customer_id"] == customerId]
    items = _filter_eq(items, "status", request.args.get("status"))
    tax_year = request.args.get("tax_year")
    if tax_year is not None:
        items = [f for f in items if f["tax_year"] == int(tax_year)]
    page, limit, offset, total = _paginate(items, request.args)
    return success_list(page, limit, offset, total)


@app.route("/firms/<firmId>/customers/<customerId>/tax_forms_1099b/<formId>/generate", methods=["POST"])
def generate_tax_form(firmId, customerId, formId):
    uid, role = require_roles(["TaxOps"])
    firm = get_firm_or_404(firmId)
    cust = get_customer_or_404(firmId, customerId)
    form = get_tax_form_or_404(firmId, customerId, formId)
    if form["status"] != "DRAFT":
        raise err(ERR_INVALID_STATE_TRANSITION,
                  "TaxForm1099B is not DRAFT")
    if cust["status"] == "CLOSED":
        raise err(ERR_INVALID_STATE_TRANSITION,
                  "Customer is CLOSED")

    # OCC check
    body = get_json_body(required=False) or {}
    expected = body.get("expected_customer_version")
    if expected is not None and expected != cust["version"]:
        raise err(ERR_STALE_FORM_VERSION,
                  "expected_customer_version does not match Customer.version")

    totals = aggregate_1099b(firmId, customerId, form["tax_year"])
    form.update(totals)
    form["generated_from_version"] = cust["version"]
    form["status"] = "GENERATED"
    _touch(form)
    return success_object(_serialize(form))


@app.route("/firms/<firmId>/customers/<customerId>/tax_forms_1099b/<formId>/file", methods=["POST"])
def file_tax_form(firmId, customerId, formId):
    uid, role = require_roles(["FirmAdmin"])
    firm = get_firm_or_404(firmId)
    cust = get_customer_or_404(firmId, customerId)
    form = get_tax_form_or_404(firmId, customerId, formId)
    if form["status"] != "GENERATED":
        raise err(ERR_INVALID_STATE_TRANSITION,
                  "TaxForm1099B is not GENERATED")
    if cust["version"] != form["generated_from_version"]:
        raise err(ERR_STALE_FORM_VERSION,
                  "Customer has been mutated since generation")
    form["filed_at"] = store.now_iso()
    form["status"] = "FILED"
    _touch(form)
    return success_object(_serialize(form))


@app.route("/firms/<firmId>/customers/<customerId>/tax_forms_1099b/<formId>/refile", methods=["POST"])
def refile_tax_form(firmId, customerId, formId):
    uid, role = require_roles(["FirmAdmin"])
    firm = get_firm_or_404(firmId)
    cust = get_customer_or_404(firmId, customerId)
    form = get_tax_form_or_404(firmId, customerId, formId)
    if form["status"] != "CORRECTION_PENDING":
        raise err(ERR_INVALID_STATE_TRANSITION,
                  "TaxForm1099B is not CORRECTION_PENDING")

    # Check correction window
    if form.get("filed_at"):
        deadline = _dt(form["filed_at"]) + timedelta(days=firm["correction_deadline_days"])
        if store.clock > deadline:
            raise err(ERR_CORRECTION_WINDOW_CLOSED,
                      "Correction window has closed")

    totals = aggregate_1099b(firmId, customerId, form["tax_year"])
    form.update(totals)
    form["correction_count"] = form.get("correction_count", 0) + 1
    form["generated_from_version"] = cust["version"]
    form["status"] = "REFILED"
    _touch(form)
    return success_object(_serialize(form))


# ---------------------------------------------------------------------------
# Basis Change Requests
# ---------------------------------------------------------------------------

@app.route("/firms/<firmId>/customers/<customerId>/basis_change_requests", methods=["POST"])
def create_basis_change_request(firmId, customerId):
    uid, role = require_roles(["Customer", "CustomerService"])
    firm = get_firm_or_404(firmId)
    cust = get_customer_or_404(firmId, customerId)

    # Customer role can only submit for themselves
    if role == "Customer" and uid != cust["id"]:
        raise err(ERR_NOT_FOUND, "Customer not found")

    # Customer standing check
    if cust["status"] in ("SUSPENDED", "CLOSED"):
        raise err(ERR_CUSTOMER_SUSPENDED,
                  "Customer is SUSPENDED or CLOSED")

    body = get_json_body()
    lot_id = body.get("tax_lot_id")
    kind = body.get("request_kind")
    if not lot_id or not kind:
        raise err(ERR_INVALID_REQUEST, "tax_lot_id and request_kind are required")
    if kind not in ("COVERAGE_RECLASS", "BASIS_AMOUNT_CORRECTION",
                    "ACQUISITION_DATE_CORRECTION", "GIFT_BASIS_SUPPLY"):
        raise err(ERR_INVALID_REQUEST, "Invalid request_kind")

    # FK resolution
    lot = store.tax_lots.get(lot_id)
    if lot is None or lot["firm_id"] != firmId:
        raise err(ERR_FOREIGN_KEY_UNRESOLVABLE,
                  "tax_lot_id does not resolve in this firm")

    req = _new_entity({
        "firm_id": firmId,
        "customer_id": customerId,
        "tax_lot_id": lot_id,
        "request_kind": kind,
        "proposed_basis_cents": body.get("proposed_basis_cents"),
        "proposed_acquisition_date": body.get("proposed_acquisition_date"),
        "proposed_coverage": body.get("proposed_coverage"),
        "gift_donor_basis_cents": body.get("gift_donor_basis_cents"),
        "gift_fmv_cents_at_gift": body.get("gift_fmv_cents_at_gift"),
        "supporting_doc_ref": body.get("supporting_doc_ref"),
        "status": "PENDING",
        "approved_by_user_id": None,
        "applied_by_user_id": None,
        "version_applied_to": None,
    })
    store.basis_change_requests[req["id"]] = req
    return success_object(_serialize(req), 201)


@app.route("/firms/<firmId>/basis_change_requests/<reqId>", methods=["GET"])
def get_basis_change_request(firmId, reqId):
    uid, role = require_roles(["FirmAdmin", "TaxOps", "CustomerService", "Auditor", "Customer"])
    firm = get_firm_or_404(firmId)
    req = get_basis_change_request_or_404(firmId, reqId)
    if role == "Customer" and uid != req["customer_id"]:
        raise err(ERR_NOT_FOUND, "BasisChangeRequest not found")
    return success_object(_serialize(req))


@app.route("/firms/<firmId>/customers/<customerId>/basis_change_requests", methods=["GET"])
def list_basis_change_requests(firmId, customerId):
    uid, role = require_roles(["FirmAdmin", "TaxOps", "CustomerService", "Auditor", "Customer"])
    firm = get_firm_or_404(firmId)
    cust = get_customer_or_404(firmId, customerId)
    if role == "Customer" and uid != cust["id"]:
        raise err(ERR_NOT_FOUND, "Customer not found")
    items = [r for r in store.basis_change_requests.values()
             if r["firm_id"] == firmId and r["customer_id"] == customerId]
    items = _filter_eq(items, "status", request.args.get("status"))
    items = _filter_eq(items, "request_kind", request.args.get("request_kind"))
    page, limit, offset, total = _paginate(items, request.args)
    return success_list(page, limit, offset, total)


@app.route("/firms/<firmId>/basis_change_requests/<reqId>/start_review", methods=["POST"])
def start_review_basis_change(firmId, reqId):
    uid, role = require_roles(["TaxOps"])
    firm = get_firm_or_404(firmId)
    req = get_basis_change_request_or_404(firmId, reqId)
    if req["status"] not in ("PENDING", "RESUBMITTED"):
        raise err(ERR_INVALID_STATE_TRANSITION,
                  "BasisChangeRequest is not PENDING or RESUBMITTED")
    req["status"] = "UNDER_REVIEW"
    _touch(req)
    return success_object(_serialize(req))


@app.route("/firms/<firmId>/basis_change_requests/<reqId>/approve", methods=["POST"])
def approve_basis_change(firmId, reqId):
    uid, role = require_roles(["TaxOps"])
    firm = get_firm_or_404(firmId)
    req = get_basis_change_request_or_404(firmId, reqId)
    if req["status"] != "UNDER_REVIEW":
        raise err(ERR_INVALID_STATE_TRANSITION,
                  "BasisChangeRequest is not UNDER_REVIEW")
    if not req.get("supporting_doc_ref"):
        raise err(ERR_MISSING_SUPPORTING_DOC,
                  "supporting_doc_ref is required for approval")
    lot = store.tax_lots.get(req["tax_lot_id"])
    if lot is None:
        raise err(ERR_NOT_FOUND, "TaxLot not found")
    req["approved_by_user_id"] = uid
    req["version_applied_to"] = lot["version"]
    req["status"] = "APPROVED"
    _touch(req)
    return success_object(_serialize(req))


@app.route("/firms/<firmId>/basis_change_requests/<reqId>/apply", methods=["POST"])
def apply_basis_change(firmId, reqId):
    uid, role = require_roles(["TaxOps"])
    firm = get_firm_or_404(firmId)
    req = get_basis_change_request_or_404(firmId, reqId)
    if req["status"] != "APPROVED":
        raise err(ERR_INVALID_STATE_TRANSITION,
                  "BasisChangeRequest is not APPROVED")

    # SOD check
    if uid == req["approved_by_user_id"]:
        raise err(ERR_SOD_VIOLATION,
                  "Same user cannot APPROVE and APPLY")

    lot = store.tax_lots.get(req["tax_lot_id"])
    if lot is None:
        raise err(ERR_NOT_FOUND, "TaxLot not found")

    # OCC check
    body = get_json_body(required=False) or {}
    expected = body.get("expected_tax_lot_version")
    if expected is not None and expected != lot["version"]:
        raise err(ERR_STALE_LOT_VERSION,
                  "expected_tax_lot_version does not match TaxLot.version")

    # Version snapshot check
    if req.get("version_applied_to") is not None and lot["version"] != req["version_applied_to"]:
        raise err(ERR_STALE_LOT_VERSION,
                  "TaxLot.version has advanced since approval")

    # Lot must be OPEN or PARTIALLY_DISPOSED
    if lot["lot_status"] not in ("OPEN", "PARTIALLY_DISPOSED"):
        raise err(ERR_INVALID_STATE_TRANSITION,
                  "TaxLot is not OPEN or PARTIALLY_DISPOSED")

    # Apply the change
    kind = req["request_kind"]
    if kind == "COVERAGE_RECLASS":
        lot["covered_status"] = req["proposed_coverage"]
    elif kind == "BASIS_AMOUNT_CORRECTION":
        lot["adjusted_cost_basis_cents"] = req["proposed_basis_cents"]
    elif kind == "ACQUISITION_DATE_CORRECTION":
        lot["acquisition_date"] = req["proposed_acquisition_date"]
        sec = store.securities.get(lot["security_id"])
        lot["covered_status"] = compute_covered_status(
            lot["acquisition_kind"], lot["acquisition_date"], sec
        )
        lot["holding_period_start"] = req["proposed_acquisition_date"]
    elif kind == "GIFT_BASIS_SUPPLY":
        lot["gift_donor_basis_cents"] = req["gift_donor_basis_cents"]
        lot["gift_fmv_cents_at_gift"] = req["gift_fmv_cents_at_gift"]
        lot["acquisition_kind"] = "GIFT"
        lot["covered_status"] = "NONCOVERED"

    _touch(lot)
    req["applied_by_user_id"] = uid
    req["status"] = "APPLIED"
    _touch(req)

    # Cascade: in-scope forms -> CORRECTION_PENDING
    tax_year = _dt(lot["acquisition_date"]).year
    customer_id = req["customer_id"]
    for form in store.tax_forms.values():
        if (form["firm_id"] == firmId
                and form["customer_id"] == customer_id
                and form["tax_year"] == tax_year
                and form["status"] in ("GENERATED", "FILED", "REFILED")):
            form["status"] = "CORRECTION_PENDING"
            _touch(form)
            cust = store.customers[customer_id]
            _touch(cust)

    return success_object(_serialize(req))


@app.route("/firms/<firmId>/basis_change_requests/<reqId>/reject", methods=["POST"])
def reject_basis_change(firmId, reqId):
    uid, role = require_roles(["TaxOps"])
    firm = get_firm_or_404(firmId)
    req = get_basis_change_request_or_404(firmId, reqId)
    if req["status"] != "UNDER_REVIEW":
        raise err(ERR_INVALID_STATE_TRANSITION,
                  "BasisChangeRequest is not UNDER_REVIEW")
    req["status"] = "REJECTED"
    _touch(req)
    return success_object(_serialize(req))


@app.route("/firms/<firmId>/basis_change_requests/<reqId>/resubmit", methods=["POST"])
def resubmit_basis_change(firmId, reqId):
    uid, role = require_roles(["Customer"])
    firm = get_firm_or_404(firmId)
    req = get_basis_change_request_or_404(firmId, reqId)
    if req["status"] != "REJECTED":
        raise err(ERR_INVALID_STATE_TRANSITION,
                  "BasisChangeRequest is not REJECTED")
    # Ownership check
    if uid != req["customer_id"]:
        raise err(ERR_NOT_FOUND, "BasisChangeRequest not found")
    req["status"] = "RESUBMITTED"
    _touch(req)
    return success_object(_serialize(req))


# ---------------------------------------------------------------------------
# Flat read surface
# ---------------------------------------------------------------------------

@app.route("/firms/customers/<customerId>", methods=["GET"])
def flat_get_customer(customerId):
    uid, role = require_roles(["FirmAdmin", "TaxOps", "CustomerService", "Auditor", "Customer"])
    cust = store.customers.get(customerId)
    if cust is None:
        raise err(ERR_NOT_FOUND, "Customer not found")
    if role == "Customer" and uid != cust["id"]:
        raise err(ERR_NOT_FOUND, "Customer not found")
    return success_object(_serialize(cust))


@app.route("/firms/customers", methods=["GET"])
def flat_list_customers():
    uid, role = require_roles(["FirmAdmin", "TaxOps", "CustomerService", "Auditor"])
    items = list(store.customers.values())
    items = _filter_eq(items, "firm_id", request.args.get("firm_id"))
    items = _filter_eq(items, "status", request.args.get("status"))
    page, limit, offset, total = _paginate(items, request.args)
    return success_list(page, limit, offset, total)


@app.route("/firms/accounts/<accountId>", methods=["GET"])
def flat_get_account(accountId):
    uid, role = require_roles(["FirmAdmin", "TaxOps", "CustomerService", "Auditor", "Customer"])
    acct = store.accounts.get(accountId)
    if acct is None:
        raise err(ERR_NOT_FOUND, "Account not found")
    if role == "Customer" and uid != acct["customer_id"]:
        raise err(ERR_NOT_FOUND, "Account not found")
    return success_object(_serialize(acct))


@app.route("/firms/accounts", methods=["GET"])
def flat_list_accounts():
    uid, role = require_roles(["FirmAdmin", "TaxOps", "CustomerService", "Auditor"])
    items = list(store.accounts.values())
    items = _filter_eq(items, "firm_id", request.args.get("firm_id"))
    items = _filter_eq(items, "customer_id", request.args.get("customer_id"))
    items = _filter_eq(items, "status", request.args.get("status"))
    page, limit, offset, total = _paginate(items, request.args)
    return success_list(page, limit, offset, total)


@app.route("/firms/securities/<securityId>", methods=["GET"])
def flat_get_security(securityId):
    uid, role = require_roles(["FirmAdmin", "TaxOps", "CustomerService", "Auditor", "Customer"])
    sec = store.securities.get(securityId)
    if sec is None:
        raise err(ERR_NOT_FOUND, "Security not found")
    return success_object(_serialize(sec))


@app.route("/firms/securities", methods=["GET"])
def flat_list_securities():
    uid, role = require_roles(["FirmAdmin", "TaxOps", "CustomerService", "Auditor", "Customer"])
    items = list(store.securities.values())
    items = _filter_eq(items, "firm_id", request.args.get("firm_id"))
    items = _filter_eq(items, "cusip", request.args.get("cusip"))
    items = _filter_eq(items, "security_type", request.args.get("security_type"))
    page, limit, offset, total = _paginate(items, request.args)
    return success_list(page, limit, offset, total)


@app.route("/firms/tax_lots/<lotId>", methods=["GET"])
def flat_get_tax_lot(lotId):
    uid, role = require_roles(["FirmAdmin", "TaxOps", "CustomerService", "Auditor", "Customer"])
    lot = store.tax_lots.get(lotId)
    if lot is None:
        raise err(ERR_NOT_FOUND, "TaxLot not found")
    if role == "Customer":
        acct = store.accounts.get(lot["account_id"])
        if acct is None or uid != acct["customer_id"]:
            raise err(ERR_NOT_FOUND, "TaxLot not found")
    return success_object(_serialize(lot))


@app.route("/firms/tax_lots", methods=["GET"])
def flat_list_tax_lots():
    uid, role = require_roles(["FirmAdmin", "TaxOps", "CustomerService", "Auditor"])
    items = list(store.tax_lots.values())
    items = _filter_eq(items, "firm_id", request.args.get("firm_id"))
    items = _filter_eq(items, "account_id", request.args.get("account_id"))
    items = _filter_eq(items, "security_id", request.args.get("security_id"))
    items = _filter_eq(items, "superseded_by_action_id", request.args.get("superseded_by_action_id"))
    items = _filter_eq(items, "lot_status", request.args.get("lot_status"))
    items = _filter_eq(items, "covered_status", request.args.get("covered_status"))
    items = _filter_eq(items, "acquisition_kind", request.args.get("acquisition_kind"))
    page, limit, offset, total = _paginate(items, request.args)
    return success_list(page, limit, offset, total)


@app.route("/firms/dispositions/<dispositionId>", methods=["GET"])
def flat_get_disposition(dispositionId):
    uid, role = require_roles(["FirmAdmin", "TaxOps", "CustomerService", "Auditor", "Customer"])
    disp = store.dispositions.get(dispositionId)
    if disp is None:
        raise err(ERR_NOT_FOUND, "Disposition not found")
    if role == "Customer":
        acct = store.accounts.get(disp["account_id"])
        if acct is None or uid != acct["customer_id"]:
            raise err(ERR_NOT_FOUND, "Disposition not found")
    return success_object(_serialize(disp))


@app.route("/firms/dispositions", methods=["GET"])
def flat_list_dispositions():
    uid, role = require_roles(["FirmAdmin", "TaxOps", "CustomerService", "Auditor"])
    items = list(store.dispositions.values())
    items = _filter_eq(items, "firm_id", request.args.get("firm_id"))
    items = _filter_eq(items, "account_id", request.args.get("account_id"))
    items = _filter_eq(items, "security_id", request.args.get("security_id"))
    items = _filter_eq(items, "status", request.args.get("status"))
    tax_year = request.args.get("tax_year")
    if tax_year is not None:
        items = [d for d in items if _dt(d["trade_date"]).year == int(tax_year)]
    page, limit, offset, total = _paginate(items, request.args)
    return success_list(page, limit, offset, total)


@app.route("/firms/corporate_actions/<actionId>", methods=["GET"])
def flat_get_corporate_action(actionId):
    uid, role = require_roles(["FirmAdmin", "TaxOps", "CustomerService", "Auditor", "Customer"])
    action = store.corporate_actions.get(actionId)
    if action is None:
        raise err(ERR_NOT_FOUND, "CorporateAction not found")
    return success_object(_serialize(action))


@app.route("/firms/corporate_actions", methods=["GET"])
def flat_list_corporate_actions():
    uid, role = require_roles(["FirmAdmin", "TaxOps", "CustomerService", "Auditor"])
    items = list(store.corporate_actions.values())
    items = _filter_eq(items, "firm_id", request.args.get("firm_id"))
    items = _filter_eq(items, "security_id", request.args.get("security_id"))
    items = _filter_eq(items, "merger_acquirer_security_id", request.args.get("merger_acquirer_security_id"))
    items = _filter_eq(items, "status", request.args.get("status"))
    page, limit, offset, total = _paginate(items, request.args)
    return success_list(page, limit, offset, total)


@app.route("/firms/transfer_statements/<stmtId>", methods=["GET"])
def flat_get_transfer_statement(stmtId):
    uid, role = require_roles(["FirmAdmin", "TaxOps", "CustomerService", "Auditor"])
    stmt = store.transfer_statements.get(stmtId)
    if stmt is None:
        raise err(ERR_NOT_FOUND, "TransferStatement not found")
    return success_object(_serialize(stmt))


@app.route("/firms/transfer_statements", methods=["GET"])
def flat_list_transfer_statements():
    uid, role = require_roles(["FirmAdmin", "TaxOps", "CustomerService", "Auditor"])
    items = list(store.transfer_statements.values())
    items = _filter_eq(items, "firm_id", request.args.get("firm_id"))
    items = _filter_eq(items, "account_id", request.args.get("account_id"))
    items = _filter_eq(items, "security_id", request.args.get("security_id"))
    items = _filter_eq(items, "replaces_statement_id", request.args.get("replaces_statement_id"))
    items = _filter_eq(items, "direction", request.args.get("direction"))
    items = _filter_eq(items, "status", request.args.get("status"))
    page, limit, offset, total = _paginate(items, request.args)
    return success_list(page, limit, offset, total)


@app.route("/firms/wash_sale_events/<eventId>", methods=["GET"])
def flat_get_wash_sale_event(eventId):
    uid, role = require_roles(["FirmAdmin", "TaxOps", "CustomerService", "Auditor"])
    ev = store.wash_sale_events.get(eventId)
    if ev is None:
        raise err(ERR_NOT_FOUND, "WashSaleEvent not found")
    return success_object(_serialize(ev))


@app.route("/firms/wash_sale_events", methods=["GET"])
def flat_list_wash_sale_events():
    uid, role = require_roles(["FirmAdmin", "TaxOps", "CustomerService", "Auditor"])
    items = list(store.wash_sale_events.values())
    items = _filter_eq(items, "firm_id", request.args.get("firm_id"))
    items = _filter_eq(items, "disposition_id", request.args.get("disposition_id"))
    items = _filter_eq(items, "triggering_lot_id", request.args.get("triggering_lot_id"))
    items = _filter_eq(items, "sold_lot_id", request.args.get("sold_lot_id"))
    page, limit, offset, total = _paginate(items, request.args)
    return success_list(page, limit, offset, total)


@app.route("/firms/tax_forms_1099b/<formId>", methods=["GET"])
def flat_get_tax_form(formId):
    uid, role = require_roles(["FirmAdmin", "TaxOps", "CustomerService", "Auditor", "Customer"])
    form = store.tax_forms.get(formId)
    if form is None:
        raise err(ERR_NOT_FOUND, "TaxForm1099B not found")
    if role == "Customer" and uid != form["customer_id"]:
        raise err(ERR_NOT_FOUND, "TaxForm1099B not found")
    return success_object(_serialize(form))


@app.route("/firms/tax_forms_1099b", methods=["GET"])
def flat_list_tax_forms():
    uid, role = require_roles(["FirmAdmin", "TaxOps", "CustomerService", "Auditor"])
    items = list(store.tax_forms.values())
    items = _filter_eq(items, "firm_id", request.args.get("firm_id"))
    items = _filter_eq(items, "customer_id", request.args.get("customer_id"))
    items = _filter_eq(items, "status", request.args.get("status"))
    tax_year = request.args.get("tax_year")
    if tax_year is not None:
        items = [f for f in items if f["tax_year"] == int(tax_year)]
    page, limit, offset, total = _paginate(items, request.args)
    return success_list(page, limit, offset, total)


@app.route("/firms/basis_change_requests/<reqId>", methods=["GET"])
def flat_get_basis_change_request(reqId):
    uid, role = require_roles(["FirmAdmin", "TaxOps", "CustomerService", "Auditor", "Customer"])
    req = store.basis_change_requests.get(reqId)
    if req is None:
        raise err(ERR_NOT_FOUND, "BasisChangeRequest not found")
    if role == "Customer" and uid != req["customer_id"]:
        raise err(ERR_NOT_FOUND, "BasisChangeRequest not found")
    return success_object(_serialize(req))


@app.route("/firms/basis_change_requests", methods=["GET"])
def flat_list_basis_change_requests():
    uid, role = require_roles(["FirmAdmin", "TaxOps", "CustomerService", "Auditor"])
    items = list(store.basis_change_requests.values())
    items = _filter_eq(items, "firm_id", request.args.get("firm_id"))
    items = _filter_eq(items, "customer_id", request.args.get("customer_id"))
    items = _filter_eq(items, "tax_lot_id", request.args.get("tax_lot_id"))
    items = _filter_eq(items, "status", request.args.get("status"))
    items = _filter_eq(items, "request_kind", request.args.get("request_kind"))
    page, limit, offset, total = _paginate(items, request.args)
    return success_list(page, limit, offset, total)
