"""Routes: contractor accounts, bulk purchase agreements, sales, sale lines."""
from flask import Blueprint, request

import db
from errors import ApiError, err_not_owner, err_invalid_request
from response import success_obj, success_list
from services import (
    account_tier_for,
    agreement_pct_for,
    agreement_qualifying_qty,
    compute_sale_totals,
    recompute_account_trailing,
    refresh_agreement,
    refresh_all_agreements,
    sale_lines_of,
    serialize_account,
    serialize_agreement,
    serialize_item,
)
from util import (
    authenticate,
    require_role,
    get_body,
    req_str,
    opt_str,
    req_enum,
    opt_fk,
    opt_int,
    req_int,
    req_num,
    req_dt,
    lookup,
    paginate,
    serialize,
    round_cents,
    D,
)

bp = Blueprint("trade", __name__)

QUANTITY_UNITS = {"UNIT", "SQFT", "LINEAR_FT"}
SALE_CHANNELS = {"WALK_IN", "CONTRACTOR_ACCOUNT"}
SALE_ROLES = ["Cashier", "StoreManager", "Contractor"]
SALE_READ_ROLES = ["Cashier", "StoreManager", "WarehouseAdmin", "Contractor"]


def _get_account(account_id):
    return lookup(db.accounts, "account", account_id)


def _cancel_active_agreements(account_id):
    for ag in db.agreements.values():
        if ag["contractor_id"] == account_id and ag["status"] == "ACTIVE":
            ag["status"] = "CANCELLED"
            db.touch(ag)


# ---------------------------------------------------------------------------
# Contractor accounts
# ---------------------------------------------------------------------------


@bp.post("/reuse/contractor-accounts")
def create_account():
    data = get_body()
    company_name = req_str(data, "company_name")
    contact_email = req_str(data, "contact_email")
    credit_limit_cents = req_int(data, "credit_limit_cents", min_value=0)
    payment_terms_days = opt_int(data, "payment_terms_days", 30, min_value=1)
    ctx = authenticate()
    require_role(ctx, ["WarehouseAdmin"])
    account = {
        **db.base_fields(),
        "company_name": company_name,
        "contact_email": contact_email,
        "status": "PENDING_APPROVAL",
        "credit_limit_cents": credit_limit_cents,
        "outstanding_balance_cents": 0,
        "trailing_volume_cents": 0,
        "discount_tier": "STANDARD",
        "payment_terms_days": payment_terms_days,
        "suspension_reason": "",
        "approved_by_user_id": "",
    }
    db.accounts[account["id"]] = account
    return success_obj(serialize_account(account), 201)


@bp.get("/reuse/contractor-accounts")
def list_accounts():
    ctx = authenticate()
    require_role(ctx, ["WarehouseAdmin", "StoreManager", "Cashier"])
    records = list(db.accounts.values())
    for param in ("status", "discount_tier"):
        v = request.args.get(param)
        if v is not None:
            if param == "discount_tier":
                # tier derives from trailing volume; recompute before filtering
                for a in db.accounts.values():
                    recompute_account_trailing(a)
            records = [a for a in records if a.get(param) == v]
    page, meta = paginate(records)
    return success_list([serialize_account(a) for a in page], meta)


@bp.get("/reuse/contractor-accounts/<accountId>")
def get_account(accountId):
    ctx = authenticate()
    require_role(ctx, ["WarehouseAdmin", "StoreManager", "Cashier", "Contractor"])
    if ctx.role == "Contractor" and accountId != ctx.user_id:
        raise err_not_owner("Contractor may only read own account")
    return success_obj(serialize_account(_get_account(accountId)))


@bp.post("/reuse/contractor-accounts/<accountId>/approve")
def approve_account(accountId):
    get_body()
    ctx = authenticate()
    require_role(ctx, ["WarehouseAdmin"])
    account = _get_account(accountId)
    if account["status"] != "PENDING_APPROVAL":
        raise ApiError(
            "ERR_INVALID_ACCOUNT_STATE", 409, "approve requires PENDING_APPROVAL"
        )
    account["status"] = "ACTIVE"
    account["approved_by_user_id"] = ctx.user_id
    db.touch(account)
    return success_obj(serialize_account(account))


@bp.post("/reuse/contractor-accounts/<accountId>/suspend")
def suspend_account(accountId):
    data = get_body()
    reason = req_str(data, "suspension_reason")
    ctx = authenticate()
    require_role(ctx, ["WarehouseAdmin"])
    account = _get_account(accountId)
    if account["status"] != "ACTIVE":
        raise ApiError("ERR_ACCOUNT_NOT_ACTIVE", 409, "suspend requires ACTIVE")
    account["status"] = "SUSPENDED"
    account["suspension_reason"] = reason
    _cancel_active_agreements(account["id"])
    db.touch(account)
    return success_obj(serialize_account(account))


@bp.post("/reuse/contractor-accounts/<accountId>/reinstate")
def reinstate_account(accountId):
    get_body()
    ctx = authenticate()
    require_role(ctx, ["WarehouseAdmin"])
    account = _get_account(accountId)
    if account["status"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_ACCOUNT_STATE", 409, "reinstate requires SUSPENDED")
    if account["outstanding_balance_cents"] > account["credit_limit_cents"]:
        raise ApiError(
            "ERR_CREDIT_LIMIT_EXCEEDED",
            402,
            "Outstanding balance exceeds the credit limit",
        )
    account["status"] = "ACTIVE"
    account["suspension_reason"] = ""
    db.touch(account)
    return success_obj(serialize_account(account))


@bp.post("/reuse/contractor-accounts/<accountId>/close")
def close_account(accountId):
    get_body()
    ctx = authenticate()
    require_role(ctx, ["WarehouseAdmin"])
    account = _get_account(accountId)
    if account["status"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError(
            "ERR_INVALID_ACCOUNT_STATE", 409, "close requires ACTIVE or SUSPENDED"
        )
    if account["outstanding_balance_cents"] != 0:
        raise ApiError(
            "ERR_OUTSTANDING_BALANCE_NONZERO",
            402,
            "Account close requires a zero outstanding balance",
        )
    if account["status"] == "ACTIVE":
        _cancel_active_agreements(account["id"])
    account["status"] = "CLOSED"
    db.touch(account)
    return success_obj(serialize_account(account))


@bp.post("/reuse/contractor-accounts/<accountId>/payments")
def record_payment(accountId):
    data = get_body()
    amount_cents = req_int(data, "amount_cents")
    if amount_cents <= 0:
        raise err_invalid_request("amount_cents must be > 0")
    ctx = authenticate()
    require_role(ctx, ["WarehouseAdmin"])
    account = _get_account(accountId)
    if amount_cents > account["outstanding_balance_cents"]:
        raise ApiError(
            "ERR_OVERPAYMENT", 402, "Payment exceeds the outstanding balance"
        )
    account["outstanding_balance_cents"] -= amount_cents
    db.touch(account)
    return success_obj(serialize_account(account), 201)


# ---------------------------------------------------------------------------
# Bulk purchase agreements
# ---------------------------------------------------------------------------


@bp.post("/reuse/bulk-agreements")
def create_agreement():
    data = get_body()
    contractor_id = req_str(data, "contractor_id")
    category_id = req_str(data, "category_id")
    discount_pct = req_num(data, "discount_pct", ge=0)
    min_quantity = req_num(data, "min_quantity", gt=0)
    quantity_unit = req_enum(data, "quantity_unit", QUANTITY_UNITS)
    valid_from = req_dt(data, "valid_from")
    valid_until = req_dt(data, "valid_until")
    supersedes_agreement_id = opt_fk(data, "supersedes_agreement_id")
    expected_account_version = req_int(data, "expected_account_version")
    ctx = authenticate()
    require_role(ctx, ["WarehouseAdmin"])
    # Body FK existence (priority 5)
    account = lookup(db.accounts, "account", contractor_id)
    lookup(db.categories, "category", category_id)
    prior = None
    if supersedes_agreement_id is not None:
        prior = lookup(db.agreements, "agreement", supersedes_agreement_id)
    # OCC (priority 6)
    if expected_account_version != account["version"]:
        raise ApiError(
            "ERR_STALE_ACCOUNT_VERSION",
            412,
            "expected_account_version does not match the account's current version",
        )
    # Temporal arithmetic (priority 10)
    if not valid_until > valid_from:
        from errors import err_invalid_time_window

        raise err_invalid_time_window("valid_until must be after valid_from")
    # Referential linkage (priority 12): supersedes must be ACTIVE, same
    # contractor + category
    if prior is not None:
        refresh_agreement(prior)
        if (
            prior["status"] != "ACTIVE"
            or prior["contractor_id"] != contractor_id
            or prior["category_id"] != category_id
        ):
            raise ApiError(
                "ERR_AGREEMENT_NOT_ACTIVE",
                409,
                "supersedes_agreement_id must reference an ACTIVE agreement of the "
                "same contractor and category",
            )
    agreement = {
        **db.base_fields(),
        "contractor_id": contractor_id,
        "category_id": category_id,
        "discount_pct": discount_pct,
        "min_quantity": min_quantity,
        "quantity_unit": quantity_unit,
        "valid_from": valid_from,
        "valid_until": valid_until,
        "status": "ACTIVE",
        "supersedes_agreement_id": supersedes_agreement_id,
        "fulfilled_quantity": 0,
    }
    db.agreements[agreement["id"]] = agreement
    if prior is not None:
        prior["status"] = "SUPERSEDED"
        db.touch(prior)
    # The create bumps the parent account's version by one
    db.touch(account)
    return success_obj(serialize_agreement(agreement), 201)


@bp.get("/reuse/bulk-agreements")
def list_agreements():
    ctx = authenticate()
    require_role(ctx, ["WarehouseAdmin", "StoreManager", "Contractor"])
    refresh_all_agreements()  # lazy expiry is evaluated on read
    records = list(db.agreements.values())
    if ctx.role == "Contractor":
        records = [a for a in records if a["contractor_id"] == ctx.user_id]
    for param in ("contractor_id", "category_id", "status", "supersedes_agreement_id"):
        v = request.args.get(param)
        if v is not None:
            if ctx.role == "Contractor" and param == "contractor_id" and v != ctx.user_id:
                raise err_not_owner("Contractor may only list own agreements")
            records = [a for a in records if a.get(param) == v]
    page, meta = paginate(records)
    return success_list([serialize(a) for a in page], meta)


@bp.get("/reuse/bulk-agreements/<agreementId>")
def get_agreement(agreementId):
    ctx = authenticate()
    require_role(ctx, ["WarehouseAdmin", "StoreManager", "Contractor"])
    agreement = lookup(db.agreements, "agreement", agreementId)
    if ctx.role == "Contractor" and agreement["contractor_id"] != ctx.user_id:
        raise err_not_owner("Contractor may only read own agreements")
    return success_obj(serialize_agreement(agreement))


@bp.post("/reuse/bulk-agreements/<agreementId>/cancel")
def cancel_agreement(agreementId):
    get_body()
    ctx = authenticate()
    require_role(ctx, ["WarehouseAdmin"])
    agreement = lookup(db.agreements, "agreement", agreementId)
    refresh_agreement(agreement)
    if agreement["status"] != "ACTIVE":
        raise ApiError("ERR_AGREEMENT_NOT_ACTIVE", 409, "cancel requires ACTIVE")
    agreement["status"] = "CANCELLED"
    db.touch(agreement)
    return success_obj(serialize(agreement))


# ---------------------------------------------------------------------------
# Sales
# ---------------------------------------------------------------------------


def _check_sale_owner(ctx, sale):
    if ctx.role == "Contractor" and sale["contractor_id"] != ctx.user_id:
        raise err_not_owner("Contractor may only act on own sales")


@bp.post("/reuse/sales")
def create_sale():
    data = get_body()
    sale_channel = req_enum(data, "sale_channel", SALE_CHANNELS)
    contractor_id = opt_fk(data, "contractor_id")
    agreement_id = opt_fk(data, "agreement_id")
    if sale_channel == "CONTRACTOR_ACCOUNT" and contractor_id is None:
        raise err_invalid_request(
            "contractor_id is required for CONTRACTOR_ACCOUNT sales"
        )
    ctx = authenticate()
    require_role(ctx, SALE_ROLES)
    if ctx.role == "Contractor":
        if sale_channel != "CONTRACTOR_ACCOUNT" or contractor_id != ctx.user_id:
            raise err_not_owner(
                "Contractor may only open CONTRACTOR_ACCOUNT sales for themselves"
            )
    account = None
    if sale_channel == "WALK_IN":
        contractor_id = None
        agreement_id = None
    else:
        account = lookup(db.accounts, "account", contractor_id)
    agreement = None
    if agreement_id is not None:
        agreement = lookup(db.agreements, "agreement", agreement_id)
    # State (priority 7)
    if account is not None and account["status"] != "ACTIVE":
        raise ApiError("ERR_ACCOUNT_NOT_ACTIVE", 409, "Account is not ACTIVE")
    if agreement is not None:
        refresh_agreement(agreement)
        if agreement["status"] != "ACTIVE":
            raise ApiError(
                "ERR_AGREEMENT_NOT_ACTIVE", 409, "Agreement is not ACTIVE"
            )
        # Temporal (priority 10)
        if not (agreement["valid_from"] <= db.now() < agreement["valid_until"]):
            raise ApiError(
                "ERR_AGREEMENT_NOT_IN_WINDOW",
                422,
                "Clock is outside the agreement validity window",
            )
    tier_snapshot = None
    if account is not None:
        # Snapshot the tier from trailing volume EXCLUDING this sale
        recompute_account_trailing(account)
        tier_snapshot = account["discount_tier"]
    sale = {
        **db.base_fields(),
        "sale_channel": sale_channel,
        "contractor_id": contractor_id,
        "agreement_id": agreement_id,
        "status": "OPEN",
        "tier_snapshot": tier_snapshot,
        "discount_pct_applied": 0,
        "subtotal_cents": 0,
        "bulk_discount_cents": 0,
        "tax_cents": 0,
        "total_cents": 0,
        "payment_amount_cents": 0,
        "finalized_at": None,
        "void_reason": "",
    }
    db.sales[sale["id"]] = sale
    return success_obj(serialize(sale), 201)


@bp.get("/reuse/sales")
def list_sales():
    ctx = authenticate()
    require_role(ctx, SALE_READ_ROLES)
    records = list(db.sales.values())
    if ctx.role == "Contractor":
        records = [s for s in records if s["contractor_id"] == ctx.user_id]
    for param in ("contractor_id", "agreement_id", "status"):
        v = request.args.get(param)
        if v is not None:
            if ctx.role == "Contractor" and param == "contractor_id" and v != ctx.user_id:
                raise err_not_owner("Contractor may only list own sales")
            records = [s for s in records if s.get(param) == v]
    page, meta = paginate(records)
    return success_list([serialize(s) for s in page], meta)


@bp.get("/reuse/sales/<saleId>")
def get_sale(saleId):
    ctx = authenticate()
    require_role(ctx, SALE_READ_ROLES)
    sale = lookup(db.sales, "sale", saleId)
    _check_sale_owner(ctx, sale)
    return success_obj(serialize(sale))


@bp.post("/reuse/sales/<saleId>/lines")
def add_sale_line(saleId):
    data = get_body()
    item_id = req_str(data, "item_id")
    quantity = data.get("quantity")
    if quantity is not None:
        if not isinstance(quantity, (int, float)) or isinstance(quantity, bool):
            raise err_invalid_request("quantity must be a number")
        if D(quantity) <= 0:
            raise err_invalid_request("quantity must be > 0")
    ctx = authenticate()
    require_role(ctx, SALE_ROLES)
    sale = lookup(db.sales, "sale", saleId)
    _check_sale_owner(ctx, sale)
    item = lookup(db.items, "item", item_id)
    if sale["status"] != "OPEN":
        raise ApiError("ERR_SALE_NOT_OPEN", 409, "line add requires an OPEN sale")
    if item["sales_status"] != "ON_FLOOR":
        raise ApiError(
            "ERR_ITEM_NOT_AVAILABLE", 409, "Line add requires item ON_FLOOR"
        )
    if quantity is None:
        quantity = item["measure_qty"]
    else:
        # Partial quantity is allowed only for non-UNIT measured items
        if item["measure_unit"] == "UNIT" and D(quantity) != D(item["measure_qty"]):
            raise err_invalid_request(
                "UNIT-measured items are taken whole; partial quantity not allowed"
            )
        if D(quantity) > D(item["measure_qty"]):
            raise err_invalid_request("quantity may not exceed the item's measure_qty")
    line = {
        **db.lean_fields(),
        "sale_id": sale["id"],
        "item_id": item_id,
        "quantity": quantity,
        "unit_price_cents": item["current_price_cents"],
        "line_total_cents": 0,
    }
    line["line_total_cents"] = round_cents(D(line["unit_price_cents"]) * D(quantity))
    db.sale_lines[line["id"]] = line
    # Reserve the item (keeps occupying its zone slot)
    item["sales_status"] = "RESERVED"
    item["_reserved_zone_id"] = item["zone_id"]
    db.touch(item)
    return success_obj(serialize(line), 201)


@bp.get("/reuse/sale-lines")
def list_sale_lines():
    ctx = authenticate()
    require_role(ctx, SALE_READ_ROLES)
    records = list(db.sale_lines.values())
    if ctx.role == "Contractor":
        own_sales = {
            s["id"] for s in db.sales.values() if s["contractor_id"] == ctx.user_id
        }
        records = [l for l in records if l["sale_id"] in own_sales]
    for param in ("sale_id", "item_id"):
        v = request.args.get(param)
        if v is not None:
            records = [l for l in records if l.get(param) == v]
    page, meta = paginate(records)
    return success_list([serialize(l) for l in page], meta)


@bp.get("/reuse/sale-lines/<lineId>")
def get_sale_line(lineId):
    ctx = authenticate()
    require_role(ctx, SALE_READ_ROLES)
    line = lookup(db.sale_lines, "line", lineId)
    if ctx.role == "Contractor":
        sale = db.sales.get(line["sale_id"])
        if sale is None or sale["contractor_id"] != ctx.user_id:
            raise err_not_owner("Contractor may only read own sale lines")
    return success_obj(serialize(line))


@bp.delete("/reuse/sale-lines/<lineId>")
def delete_sale_line(lineId):
    get_body()
    ctx = authenticate()
    require_role(ctx, SALE_ROLES)
    line = lookup(db.sale_lines, "line", lineId)
    sale = db.sales[line["sale_id"]]
    _check_sale_owner(ctx, sale)
    if sale["status"] != "OPEN":
        raise ApiError("ERR_SALE_NOT_OPEN", 409, "line removal requires an OPEN sale")
    item = db.items.get(line["item_id"])
    del db.sale_lines[lineId]
    if item is not None and item["sales_status"] == "RESERVED":
        item["sales_status"] = "ON_FLOOR"  # zone_id retained
        item["_reserved_zone_id"] = None
        db.touch(item)
    return "", 204


@bp.post("/reuse/sales/<saleId>/finalize")
def finalize_sale(saleId):
    data = get_body()
    payment_amount_cents = opt_int(data, "payment_amount_cents", 0, min_value=0)
    ctx = authenticate()
    require_role(ctx, SALE_ROLES)
    sale = lookup(db.sales, "sale", saleId)
    _check_sale_owner(ctx, sale)
    # State (priority 7)
    if sale["status"] != "OPEN":
        raise ApiError("ERR_SALE_NOT_OPEN", 409, "finalize requires an OPEN sale")
    lines = sale_lines_of(sale["id"])
    if not lines:
        raise ApiError("ERR_EMPTY_SALE", 409, "finalize requires at least one line")
    account = None
    if sale["sale_channel"] == "CONTRACTOR_ACCOUNT":
        account = db.accounts[sale["contractor_id"]]
        if account["status"] != "ACTIVE":
            raise ApiError("ERR_ACCOUNT_NOT_ACTIVE", 409, "Account is not ACTIVE")
    agreement = None
    if sale.get("agreement_id"):
        agreement = db.agreements.get(sale["agreement_id"])
        if agreement is not None:
            refresh_agreement(agreement)
            if agreement["status"] != "ACTIVE":
                raise ApiError(
                    "ERR_AGREEMENT_NOT_ACTIVE", 409, "Agreement is not ACTIVE"
                )
            # Temporal (priority 10): before fiscal checks (priority 11)
            if not (agreement["valid_from"] <= db.now() < agreement["valid_until"]):
                raise ApiError(
                    "ERR_AGREEMENT_NOT_IN_WINDOW",
                    422,
                    "Clock is outside the agreement validity window",
                )
    totals = compute_sale_totals(sale)
    # Fiscal checks (priority 11)
    if sale["sale_channel"] == "CONTRACTOR_ACCOUNT":
        if (
            account["credit_limit_cents"] == 0
            and account["outstanding_balance_cents"] + totals["total_cents"] > 0
        ):
            raise ApiError(
                "ERR_CREDIT_LIMIT_EXCEEDED",
                402,
                "Account extends no credit (credit_limit_cents == 0)",
            )
    else:
        if payment_amount_cents < totals["total_cents"]:
            raise ApiError(
                "ERR_PAYMENT_INSUFFICIENT",
                402,
                "payment_amount_cents does not cover total_cents",
            )
    # Commit totals
    sale.update(totals)
    sale["status"] = "FINALIZED"
    sale["finalized_at"] = db.now()
    if sale["sale_channel"] == "WALK_IN":
        sale["payment_amount_cents"] = payment_amount_cents
    # Hop 1+2: items RESERVED -> SOLD; former zone occupancy decremented
    for line in lines:
        item = db.items.get(line["item_id"])
        if item is None or item["sales_status"] != "RESERVED":
            continue
        zone = db.zones.get(item["zone_id"] or "")
        item["sales_status"] = "SOLD"
        item["sold_via_sale_id"] = sale["id"]
        item["zone_id"] = None
        item["floor_since"] = None
        db.touch(item)
        if zone is not None:
            db.touch(zone)  # count/flag recompute on read
    # Contractor-channel account ledger (hop 2) and auto-suspension (hop 3+4)
    if account is not None:
        account["outstanding_balance_cents"] += totals["total_cents"]
        recompute_account_trailing(account)
        db.touch(account)
        if account["outstanding_balance_cents"] > account["credit_limit_cents"]:
            account["status"] = "SUSPENDED"
            account["suspension_reason"] = "CREDIT_LIMIT_BREACH"
            _cancel_active_agreements(account["id"])
            db.touch(account)
    # Agreement fulfilment accrual
    if agreement is not None:
        pct = agreement_pct_for(sale)
        if pct > 0:
            agreement["fulfilled_quantity"] = float(
                D(agreement["fulfilled_quantity"])
                + agreement_qualifying_qty(sale, agreement)
            )
            db.touch(agreement)
    db.touch(sale)
    return success_obj(serialize(sale))


@bp.post("/reuse/sales/<saleId>/void")
def void_sale(saleId):
    data = get_body()
    void_reason = opt_str(data, "void_reason", "")
    ctx = authenticate()
    require_role(ctx, ["StoreManager", "WarehouseAdmin"])
    sale = lookup(db.sales, "sale", saleId)
    if sale["status"] != "FINALIZED":
        raise ApiError("ERR_SALE_NOT_FINALIZED", 409, "void requires FINALIZED")
    sale["status"] = "VOIDED"
    sale["void_reason"] = void_reason
    # Compensating restock: finalize+void leaves zone occupancy unchanged
    for line in sale_lines_of(sale["id"]):
        item = db.items.get(line["item_id"])
        if (
            item is None
            or item["sales_status"] != "SOLD"
            or item["sold_via_sale_id"] != sale["id"]
        ):
            continue
        zone_id = item.get("_reserved_zone_id")
        item["sales_status"] = "ON_FLOOR"
        item["sold_via_sale_id"] = None
        item["zone_id"] = zone_id
        item["floor_since"] = db.now()
        item["_reserved_zone_id"] = None
        db.touch(item)
        if zone_id and zone_id in db.zones:
            db.touch(db.zones[zone_id])
    # Account balance reversal
    if sale["sale_channel"] == "CONTRACTOR_ACCOUNT":
        account = db.accounts[sale["contractor_id"]]
        account["outstanding_balance_cents"] -= sale["total_cents"]
        recompute_account_trailing(account)
        db.touch(account)
        # Agreement fulfilment reversal
        if sale.get("agreement_id"):
            agreement = db.agreements.get(sale["agreement_id"])
            if agreement is not None:
                agreement["fulfilled_quantity"] = float(
                    D(agreement["fulfilled_quantity"])
                    - agreement_qualifying_qty(sale, agreement)
                )
                db.touch(agreement)
    db.touch(sale)
    return success_obj(serialize(sale))


@bp.post("/reuse/sales/<saleId>/cancel")
def cancel_sale(saleId):
    get_body()
    ctx = authenticate()
    require_role(ctx, SALE_ROLES)
    sale = lookup(db.sales, "sale", saleId)
    _check_sale_owner(ctx, sale)
    if sale["status"] != "OPEN":
        raise ApiError("ERR_SALE_NOT_OPEN", 409, "cancel requires an OPEN sale")
    sale["status"] = "CANCELLED"
    for line in sale_lines_of(sale["id"]):
        item = db.items.get(line["item_id"])
        if item is not None and item["sales_status"] == "RESERVED":
            item["sales_status"] = "ON_FLOOR"  # zone_id retained
            item["_reserved_zone_id"] = None
            db.touch(item)
    db.touch(sale)
    return success_obj(serialize(sale))
