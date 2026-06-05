import os
import re
from flask import Flask, request

import errors
from errors import ApiError, err
from response import success, error_response, iso_ms
from clock import clock
from db import db, new_common, touch
from middleware import authenticate, require_role, require_owner
from pagination import parse_pagination, paginate
import util
from util import parse_iso, add_days
import serialize
import services

app = Flask(__name__)

QUARTER_RE = re.compile(r"^[0-9]{4}-Q[1-4]$")
UPPER_SNAKE_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


# ===========================================================================
# Error handling
# ===========================================================================

@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_RESOURCE_NOT_FOUND", "Resource not found.", 404)


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_RESOURCE_NOT_FOUND", "Method not allowed.", 404)


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    return error_response("ERR_INVALID_REQUEST", f"Unexpected error: {e}", 400)


def get_json():
    """Parse the request JSON body, defaulting to {} for empty bodies on
    action endpoints. Malformed JSON -> ERR_INVALID_REQUEST."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise err(errors.ERR_INVALID_REQUEST, "Malformed JSON body.")
    if body is None:
        return {}
    return body


# ===========================================================================
# Generic list / fetch helpers
# ===========================================================================

def do_list(collection, serializer, filters=None):
    limit, offset = parse_pagination()
    items = list(collection.values())
    if filters:
        for field, value in filters.items():
            if value is not None:
                items = [r for r in items if r.get(field) == value]
    page, meta = paginate(items, limit, offset)
    return success([serializer(r) for r in page], status=200, pagination=meta)


def fetch_or_404(collection, rid):
    rec = collection.get(rid)
    if rec is None:
        raise err(errors.ERR_RESOURCE_NOT_FOUND, "Resource not found.")
    return rec


# ===========================================================================
# Clock (test-driving)
# ===========================================================================

@app.route("/_clock/set_current_utc", methods=["POST"])
def clock_set():
    _, role = authenticate()
    require_role(role, {"ProgramAdmin", "RewardsOps"})
    body = util.require_body(get_json())
    dt = util.req_datetime(body, "to_iso8601")
    clock.set(dt)
    return success({}, status=200)


# ===========================================================================
# CardProduct
# ===========================================================================

@app.route("/products", methods=["POST"])
def create_product():
    _, role = authenticate()
    require_role(role, {"ProgramAdmin"})
    body = util.require_body(get_json())
    name = util.req_str(body, "name", 1, 100)
    base = util.req_int(body, "base_earn_rate_bps", 0, 1000)
    sbp = util.req_int(body, "signup_bonus_points", 0)
    sbt = util.req_int(body, "signup_bonus_spend_threshold_cents", 1)
    sbw = util.req_int(body, "signup_bonus_window_days", 1, 365)
    tiers = _validate_tier_thresholds(body.get("tier_thresholds"))
    pem = util.req_int(body, "points_expiry_months", 1, 120)

    rec = new_common()
    rec.update({
        "name": name,
        "base_earn_rate_bps": base,
        "signup_bonus_points": sbp,
        "signup_bonus_spend_threshold_cents": sbt,
        "signup_bonus_window_days": sbw,
        "tier_thresholds": tiers,
        "points_expiry_months": pem,
        "status": "ACTIVE",
    })
    db.products[rec["id"]] = rec
    return success(serialize.product_out(rec), status=201)


def _validate_tier_thresholds(value):
    if value is None or not isinstance(value, list):
        raise err(errors.ERR_INVALID_REQUEST, "tier_thresholds must be a list.")
    if len(value) > 4:
        raise err(errors.ERR_INVALID_REQUEST, "tier_thresholds may have at most 4 elements.")
    out = []
    prev = None
    for i, el in enumerate(value):
        if not isinstance(el, dict):
            raise err(errors.ERR_INVALID_REQUEST, "tier_thresholds elements must be objects.")
        m = el.get("min_annual_spend_cents")
        mult = el.get("tier_multiplier_bps")
        if not isinstance(m, int) or isinstance(m, bool):
            raise err(errors.ERR_INVALID_REQUEST, "min_annual_spend_cents must be an integer.")
        if not isinstance(mult, int) or isinstance(mult, bool):
            raise err(errors.ERR_INVALID_REQUEST, "tier_multiplier_bps must be an integer.")
        if i == 0 and m < 1:
            raise err(errors.ERR_INVALID_REQUEST, "first tier min_annual_spend_cents must be >= 1.")
        if prev is not None and m <= prev:
            raise err(errors.ERR_INVALID_REQUEST, "min_annual_spend_cents must be strictly ascending.")
        prev = m
        out.append({"min_annual_spend_cents": m, "tier_multiplier_bps": mult})
    return out


@app.route("/products/<rid>", methods=["GET"])
def get_product(rid):
    authenticate()
    rec = fetch_or_404(db.products, rid)
    return success(serialize.product_out(rec), status=200)


@app.route("/products", methods=["GET"])
def list_products():
    authenticate()
    status = request.args.get("status")
    return do_list(db.products, serialize.product_out, {"status": status})


@app.route("/products/<rid>/retire", methods=["POST"])
def retire_product(rid):
    _, role = authenticate()
    require_role(role, {"ProgramAdmin"})
    rec = fetch_or_404(db.products, rid)
    rec["status"] = "RETIRED"
    touch(rec)
    return success(serialize.product_out(rec), status=200)


# ===========================================================================
# CashbackCategory
# ===========================================================================

@app.route("/cashback-categories", methods=["POST"])
def create_cashback_category():
    _, role = authenticate()
    require_role(role, {"ProgramAdmin"})
    body = util.require_body(get_json())
    # existence (priority 4) before body field checks? FK existence is priority 4,
    # body presence/type is priority 5. But we must read the FK value first.
    product_id = body.get("card_product_id")
    if not isinstance(product_id, str) or not product_id:
        raise err(errors.ERR_INVALID_REQUEST, "card_product_id must be a string.")
    product = db.products.get(product_id)
    if product is None:
        raise err(errors.ERR_RESOURCE_NOT_FOUND, "Referenced product does not exist.")
    code = util.req_str(body, "code", 1, 100)
    if not UPPER_SNAKE_RE.match(code):
        raise err(errors.ERR_INVALID_REQUEST, "code must be UPPER_SNAKE.")
    mult = util.req_int(body, "earn_multiplier_bps", 100, 1000)

    # uniqueness (priority 9): code unique per product among cashback categories
    for cb in db.cashback_categories.values():
        if cb["card_product_id"] == product_id and cb["code"] == code:
            raise err(errors.ERR_DUPLICATE_ACTIVATION, "Duplicate cashback category code for product.")

    rec = new_common()
    rec.update({
        "card_product_id": product_id,
        "code": code,
        "earn_multiplier_bps": mult,
        "status": "ACTIVE",
    })
    db.cashback_categories[rec["id"]] = rec
    return success(serialize.cashback_category_out(rec), status=201)


@app.route("/cashback-categories/<rid>", methods=["GET"])
def get_cashback_category(rid):
    authenticate()
    rec = fetch_or_404(db.cashback_categories, rid)
    return success(serialize.cashback_category_out(rec), status=200)


@app.route("/cashback-categories", methods=["GET"])
def list_cashback_categories():
    authenticate()
    return do_list(db.cashback_categories, serialize.cashback_category_out, {
        "card_product_id": request.args.get("card_product_id"),
        "status": request.args.get("status"),
    })


# ===========================================================================
# QuarterlyCategory
# ===========================================================================

@app.route("/quarterly-categories", methods=["POST"])
def create_quarterly_category():
    _, role = authenticate()
    require_role(role, {"ProgramAdmin"})
    body = util.require_body(get_json())
    product_id = body.get("card_product_id")
    if not isinstance(product_id, str) or not product_id:
        raise err(errors.ERR_INVALID_REQUEST, "card_product_id must be a string.")
    product = db.products.get(product_id)
    if product is None:
        raise err(errors.ERR_RESOURCE_NOT_FOUND, "Referenced product does not exist.")
    code = util.req_str(body, "code", 1, 100)
    if not UPPER_SNAKE_RE.match(code):
        raise err(errors.ERR_INVALID_REQUEST, "code must be UPPER_SNAKE.")
    quarter_label = util.req_str(body, "quarter_label", 1, 100)
    if not QUARTER_RE.match(quarter_label):
        raise err(errors.ERR_INVALID_REQUEST, "quarter_label must match YYYY-Qn.")
    window_start = util.req_datetime(body, "window_start")
    window_end = util.req_datetime(body, "window_end")
    if not (window_start < window_end):
        raise err(errors.ERR_INVALID_REQUEST, "window_start must be before window_end.")
    mult = util.req_int(body, "earn_multiplier_bps", 100, 1000)
    cap = util.req_int(body, "bonus_cap_cents", 1)

    # uniqueness (priority 9): (card_product_id, quarter_label) unique
    for q in db.quarterly_categories.values():
        if q["card_product_id"] == product_id and q["quarter_label"] == quarter_label:
            raise err(errors.ERR_DUPLICATE_ACTIVATION, "Duplicate quarterly category for product/quarter.")

    rec = new_common()
    rec.update({
        "card_product_id": product_id,
        "code": code,
        "quarter_label": quarter_label,
        "window_start": iso_ms(window_start),
        "window_end": iso_ms(window_end),
        "earn_multiplier_bps": mult,
        "bonus_cap_cents": cap,
    })
    db.quarterly_categories[rec["id"]] = rec
    return success(serialize.quarterly_category_out(rec), status=201)


@app.route("/quarterly-categories/<rid>", methods=["GET"])
def get_quarterly_category(rid):
    authenticate()
    rec = fetch_or_404(db.quarterly_categories, rid)
    return success(serialize.quarterly_category_out(rec), status=200)


@app.route("/quarterly-categories", methods=["GET"])
def list_quarterly_categories():
    authenticate()
    return do_list(db.quarterly_categories, serialize.quarterly_category_out, {
        "card_product_id": request.args.get("card_product_id"),
        "quarter_label": request.args.get("quarter_label"),
    })


# ===========================================================================
# TransferPartner
# ===========================================================================

@app.route("/transfer-partners", methods=["POST"])
def create_transfer_partner():
    _, role = authenticate()
    require_role(role, {"ProgramAdmin"})
    body = util.require_body(get_json())
    name = util.req_str(body, "name", 1, 100)
    partner_type = util.req_enum(body, "partner_type", {"AIRLINE", "HOTEL"})
    num = util.req_int(body, "transfer_ratio_num", 1)
    den = util.req_int(body, "transfer_ratio_den", 1)
    minp = util.req_int(body, "min_transfer_points", 1)

    rec = new_common()
    rec.update({
        "name": name,
        "partner_type": partner_type,
        "transfer_ratio_num": num,
        "transfer_ratio_den": den,
        "min_transfer_points": minp,
        "status": "ACTIVE",
    })
    db.transfer_partners[rec["id"]] = rec
    return success(serialize.transfer_partner_out(rec), status=201)


@app.route("/transfer-partners/<rid>", methods=["GET"])
def get_transfer_partner(rid):
    authenticate()
    rec = fetch_or_404(db.transfer_partners, rid)
    return success(serialize.transfer_partner_out(rec), status=200)


@app.route("/transfer-partners", methods=["GET"])
def list_transfer_partners():
    authenticate()
    return do_list(db.transfer_partners, serialize.transfer_partner_out, {
        "partner_type": request.args.get("partner_type"),
        "status": request.args.get("status"),
    })


@app.route("/transfer-partners/<rid>/suspend", methods=["POST"])
def suspend_transfer_partner(rid):
    _, role = authenticate()
    require_role(role, {"ProgramAdmin"})
    rec = fetch_or_404(db.transfer_partners, rid)
    rec["status"] = "SUSPENDED"
    touch(rec)
    return success(serialize.transfer_partner_out(rec), status=200)


# ===========================================================================
# CardAccount
# ===========================================================================

@app.route("/accounts", methods=["POST"])
def create_account():
    _, role = authenticate()
    require_role(role, {"ProgramAdmin"})
    body = util.require_body(get_json())
    product_id = body.get("card_product_id")
    if not isinstance(product_id, str) or not product_id:
        raise err(errors.ERR_INVALID_REQUEST, "card_product_id must be a string.")
    product = db.products.get(product_id)
    if product is None:
        raise err(errors.ERR_RESOURCE_NOT_FOUND, "Referenced product does not exist.")
    cardholder_name = util.req_str(body, "cardholder_name", 1, 100)
    # cross-product integrity (priority 8): product must be ACTIVE at open
    if product["status"] != "ACTIVE":
        raise err(errors.ERR_CROSS_PRODUCT_MISMATCH, "Cannot open account under a non-ACTIVE product.")

    rec = new_common()
    rec.update({
        "card_product_id": product_id,
        "cardholder_name": cardholder_name,
        "opened_at": rec["created_at"],
        "points_balance": 0,
        "pending_points": 0,
        "qualifying_spend_cents": 0,
        "annual_spend_cents": 0,
        "current_tier_index": 0,
        "signup_bonus_status": "NOT_QUALIFIED",
        "status": "PENDING",
    })
    db.accounts[rec["id"]] = rec
    return success(serialize.account_out(rec), status=201)


@app.route("/accounts/<rid>", methods=["GET"])
def get_account(rid):
    user_id, role = authenticate()
    rec = fetch_or_404(db.accounts, rid)
    require_owner(role, user_id, rec["id"])
    return success(serialize.account_out(rec), status=200)


@app.route("/accounts", methods=["GET"])
def list_accounts():
    _, role = authenticate()
    require_role(role, {"ProgramAdmin", "RewardsOps"})
    return do_list(db.accounts, serialize.account_out, {
        "card_product_id": request.args.get("card_product_id"),
        "status": request.args.get("status"),
    })


@app.route("/accounts/<rid>/activate", methods=["POST"])
def activate_account(rid):
    _, role = authenticate()
    require_role(role, {"ProgramAdmin"})
    rec = fetch_or_404(db.accounts, rid)
    # state (priority 7)
    if rec["status"] != "PENDING":
        raise err(errors.ERR_INVALID_STATE, "Account is not PENDING.")
    product = db.products.get(rec["card_product_id"])
    # cross-product (priority 8): referenced product must be ACTIVE
    if product is None or product["status"] != "ACTIVE":
        raise err(errors.ERR_CROSS_PRODUCT_MISMATCH, "Product is not ACTIVE.")
    rec["status"] = "ACTIVE"
    touch(rec)
    return success(serialize.account_out(rec), status=200)


@app.route("/accounts/<rid>/close", methods=["POST"])
def close_account(rid):
    user_id, role = authenticate()
    require_role(role, {"ProgramAdmin", "Cardholder"})
    rec = fetch_or_404(db.accounts, rid)
    require_owner(role, user_id, rec["id"])
    # state (priority 7): must be ACTIVE and no PENDING redemption
    if rec["status"] != "ACTIVE":
        raise err(errors.ERR_INVALID_STATE, "Account is not ACTIVE.")
    for r in db.redemptions.values():
        if r["card_account_id"] == rec["id"] and r["status"] == "PENDING":
            raise err(errors.ERR_INVALID_STATE, "Account has a pending redemption.")
    # forfeit all ACTIVE lots
    for lot in db.points_lots.values():
        if lot["card_account_id"] == rec["id"] and lot["status"] == "ACTIVE":
            lot["status"] = "EXPIRED"
            lot["remaining_points"] = 0
    rec["points_balance"] = 0
    rec["status"] = "CLOSED"
    touch(rec)
    return success(serialize.account_out(rec), status=200)


# ===========================================================================
# Transaction
# ===========================================================================

@app.route("/transactions", methods=["POST"])
def create_transaction():
    _, role = authenticate()
    require_role(role, {"ProgramAdmin"})
    body = util.require_body(get_json())
    account_id = body.get("card_account_id")
    if not isinstance(account_id, str) or not account_id:
        raise err(errors.ERR_INVALID_REQUEST, "card_account_id must be a string.")
    account = db.accounts.get(account_id)
    if account is None:
        raise err(errors.ERR_RESOURCE_NOT_FOUND, "Referenced account does not exist.")
    amount = util.req_int(body, "amount_cents", 1)
    category_code = util.req_str(body, "category_code", 1, 100)
    if not UPPER_SNAKE_RE.match(category_code):
        raise err(errors.ERR_INVALID_REQUEST, "category_code must be UPPER_SNAKE.")
    transacted_at = util.req_datetime(body, "transacted_at")

    # state (priority 7): account must be ACTIVE
    if account["status"] != "ACTIVE":
        raise err(errors.ERR_INVALID_STATE, "Account is not ACTIVE.")

    # temporal (priority 10): opened_at <= transacted_at <= now
    opened = parse_iso(account["opened_at"])
    now = clock.now()
    if transacted_at < opened or transacted_at > now:
        raise err(errors.ERR_TEMPORAL_OUT_OF_RANGE, "transacted_at out of allowed range.")

    product = db.products.get(account["card_product_id"])

    rec = new_common()
    rec.update({
        "card_account_id": account_id,
        "amount_cents": amount,
        "category_code": category_code,
        "transacted_at": iso_ms(transacted_at),
        "earned_points": 0,
        "quarterly_bonus_applied_cents": 0,
        "status": "PENDING",
    })
    db.transactions[rec["id"]] = rec

    # provisional points -> pending_points (same formula, no lot, earned_points stays 0)
    provisional, _bonus = services.compute_earned_points(
        account, product, amount, category_code, transacted_at)
    rec["_provisional_points"] = provisional
    account["pending_points"] += provisional
    touch(account)

    return success(serialize.transaction_out(rec), status=201)


@app.route("/transactions/<rid>", methods=["GET"])
def get_transaction(rid):
    authenticate()
    rec = fetch_or_404(db.transactions, rid)
    return success(serialize.transaction_out(rec), status=200)


@app.route("/transactions", methods=["GET"])
def list_transactions():
    authenticate()
    return do_list(db.transactions, serialize.transaction_out, {
        "card_account_id": request.args.get("card_account_id"),
        "status": request.args.get("status"),
    })


@app.route("/transactions/<rid>/post", methods=["POST"])
def post_transaction(rid):
    _, role = authenticate()
    require_role(role, {"ProgramAdmin"})
    rec = fetch_or_404(db.transactions, rid)
    account = db.accounts.get(rec["card_account_id"])
    # state (priority 7): txn PENDING and account ACTIVE
    if rec["status"] != "PENDING":
        raise err(errors.ERR_INVALID_STATE, "Transaction is not PENDING.")
    if account is None or account["status"] != "ACTIVE":
        raise err(errors.ERR_INVALID_STATE, "Owning account is not ACTIVE.")
    product = db.products.get(account["card_product_id"])

    transacted_at = parse_iso(rec["transacted_at"])

    # compute earned_points/quarterly using current_tier_index BEFORE adding spend
    earned, bonus_cents = services.compute_earned_points(
        account, product, rec["amount_cents"], rec["category_code"], transacted_at)
    rec["earned_points"] = earned
    rec["quarterly_bonus_applied_cents"] = bonus_cents
    rec["status"] = "POSTED"

    # move provisional out of pending_points
    account["pending_points"] = max(0, account["pending_points"] - rec.get("_provisional_points", 0))

    # mint EARN lot when earned > 0; add into points_balance
    if earned > 0:
        services.mint_lot(account, product, earned, "EARN", rec["id"])

    # tier-year spend update + tier re-derive
    if services.in_tier_year(account, transacted_at):
        account["annual_spend_cents"] += rec["amount_cents"]
        account["current_tier_index"] = services.derive_tier_index(product, account["annual_spend_cents"])

    # signup-window spend update + maybe grant bonus
    if services.in_signup_window(account, product, transacted_at):
        account["qualifying_spend_cents"] += rec["amount_cents"]
        services.maybe_grant_signup_bonus(account, product)

    services.recompute_balance(account)
    touch(account)
    return success(serialize.transaction_out(rec), status=200)


@app.route("/transactions/<rid>/decline", methods=["POST"])
def decline_transaction(rid):
    _, role = authenticate()
    require_role(role, {"ProgramAdmin"})
    rec = fetch_or_404(db.transactions, rid)
    if rec["status"] != "PENDING":
        raise err(errors.ERR_INVALID_STATE, "Transaction is not PENDING.")
    account = db.accounts.get(rec["card_account_id"])
    rec["status"] = "DECLINED"
    if account is not None:
        account["pending_points"] = max(0, account["pending_points"] - rec.get("_provisional_points", 0))
        touch(account)
    return success(serialize.transaction_out(rec), status=200)


@app.route("/transactions/<rid>/refund", methods=["POST"])
def refund_transaction(rid):
    _, role = authenticate()
    require_role(role, {"ProgramAdmin"})
    rec = fetch_or_404(db.transactions, rid)
    if rec["status"] != "POSTED":
        raise err(errors.ERR_INVALID_STATE, "Transaction is not POSTED.")
    account = db.accounts.get(rec["card_account_id"])
    product = db.products.get(account["card_product_id"]) if account else None
    rec["status"] = "REFUNDED"

    # claw back the EARN lot minted by this txn
    for lot in db.points_lots.values():
        if (lot["source_transaction_id"] == rec["id"]
                and lot["lot_type"] == "EARN"
                and lot["status"] in ("ACTIVE", "CONSUMED")):
            lot["status"] = "CLAWED_BACK"
            lot["remaining_points"] = 0

    transacted_at = parse_iso(rec["transacted_at"])
    # subtract from annual spend (floor 0) within tier year, re-derive tier
    if services.in_tier_year(account, transacted_at):
        account["annual_spend_cents"] = max(0, account["annual_spend_cents"] - rec["amount_cents"])
        account["current_tier_index"] = services.derive_tier_index(product, account["annual_spend_cents"])
    # subtract from qualifying spend (floor 0) within signup window
    if services.in_signup_window(account, product, transacted_at):
        account["qualifying_spend_cents"] = max(0, account["qualifying_spend_cents"] - rec["amount_cents"])

    services.recompute_balance(account)
    touch(account)
    return success(serialize.transaction_out(rec), status=200)


# ===========================================================================
# PointsLot (read-only)
# ===========================================================================

@app.route("/points-lots/<rid>", methods=["GET"])
def get_points_lot(rid):
    authenticate()
    rec = fetch_or_404(db.points_lots, rid)
    return success(serialize.points_lot_out(rec), status=200)


@app.route("/points-lots", methods=["GET"])
def list_points_lots():
    authenticate()
    return do_list(db.points_lots, serialize.points_lot_out, {
        "card_account_id": request.args.get("card_account_id"),
        "source_transaction_id": request.args.get("source_transaction_id"),
        "status": request.args.get("status"),
    })


# ===========================================================================
# Redemption
# ===========================================================================

@app.route("/redemptions", methods=["POST"])
def create_redemption():
    user_id, role = authenticate()
    require_role(role, {"Cardholder"})
    body = util.require_body(get_json())

    # FK / ownership: read account_id, verify ownership (priority 3) before existence?
    # Priority order: auth(1,2) -> ownership(3) -> existence(4). Ownership compares
    # X-User-ID to card_account_id without dereferencing it.
    account_id = body.get("card_account_id")
    if not isinstance(account_id, str) or not account_id:
        # body shape problem; but ownership (3) precedes existence/body(4,5).
        # We need the value to do the ownership check; a missing/invalid id can't
        # match X-User-ID, so it's an ownership failure for a Cardholder.
        require_owner(role, user_id, account_id if isinstance(account_id, str) else None)
        raise err(errors.ERR_INVALID_REQUEST, "card_account_id must be a string.")
    require_owner(role, user_id, account_id)

    # existence (priority 4)
    account = db.accounts.get(account_id)
    if account is None:
        raise err(errors.ERR_RESOURCE_NOT_FOUND, "Referenced account does not exist.")

    # body presence/type/enum (priority 5)
    redemption_type = util.req_enum(body, "redemption_type", {"STATEMENT_CREDIT", "POINTS_TRANSFER"})
    points_requested = util.req_int(body, "points_requested", 1)
    expected_version = util.req_int(body, "expected_card_account_version", 1)
    transfer_partner_id = body.get("transfer_partner_id")
    if transfer_partner_id is not None and not isinstance(transfer_partner_id, str):
        raise err(errors.ERR_INVALID_REQUEST, "transfer_partner_id must be a string.")

    # existence of transfer_partner FK (priority 4 conceptually, but only meaningful
    # when present). Validate referenced partner exists before later business rules.
    partner = None
    if transfer_partner_id is not None:
        partner = db.transfer_partners.get(transfer_partner_id)
        if partner is None:
            raise err(errors.ERR_RESOURCE_NOT_FOUND, "Referenced transfer partner does not exist.")

    # conditional partner-field shape (priority 6)
    if redemption_type == "POINTS_TRANSFER" and transfer_partner_id is None:
        raise err(errors.ERR_PARTNER_FIELD_MISMATCH, "transfer_partner_id required for POINTS_TRANSFER.")
    if redemption_type == "STATEMENT_CREDIT" and transfer_partner_id is not None:
        raise err(errors.ERR_PARTNER_FIELD_MISMATCH, "transfer_partner_id forbidden for STATEMENT_CREDIT.")

    # state (priority 7): account ACTIVE
    if account["status"] != "ACTIVE":
        raise err(errors.ERR_INVALID_STATE, "Account is not ACTIVE.")

    # cross-product (priority 8): partner ACTIVE for transfer
    if redemption_type == "POINTS_TRANSFER" and partner["status"] != "ACTIVE":
        raise err(errors.ERR_CROSS_PRODUCT_MISMATCH, "Transfer partner is not ACTIVE.")

    # below-min-transfer (priority 11; temporal priority 10 N/A for redemptions here)
    if redemption_type == "POINTS_TRANSFER" and points_requested < partner["min_transfer_points"]:
        raise err(errors.ERR_BELOW_MIN_TRANSFER, "points_requested below partner minimum.")

    # OCC (priority 12)
    if expected_version != account["version"]:
        raise err(errors.ERR_STALE_ACCOUNT_VERSION, "Stale account version.")

    # sufficient balance (priority 13)
    if points_requested > account["points_balance"]:
        raise err(errors.ERR_INSUFFICIENT_POINTS, "Insufficient redeemable points.")

    rec = new_common()
    rec.update({
        "card_account_id": account_id,
        "redemption_type": redemption_type,
        "points_requested": points_requested,
        "transfer_partner_id": transfer_partner_id,
        "expected_card_account_version": expected_version,
        "redeemed_value": 0,
        "lots_consumed": [],
        "status": "PENDING",
    })
    db.redemptions[rec["id"]] = rec
    touch(account)
    return success(serialize.redemption_out(rec), status=201)


@app.route("/redemptions/<rid>", methods=["GET"])
def get_redemption(rid):
    authenticate()
    rec = fetch_or_404(db.redemptions, rid)
    return success(serialize.redemption_out(rec), status=200)


@app.route("/redemptions", methods=["GET"])
def list_redemptions():
    authenticate()
    return do_list(db.redemptions, serialize.redemption_out, {
        "card_account_id": request.args.get("card_account_id"),
        "transfer_partner_id": request.args.get("transfer_partner_id"),
        "status": request.args.get("status"),
    })


@app.route("/redemptions/<rid>/confirm", methods=["POST"])
def confirm_redemption(rid):
    _, role = authenticate()
    require_role(role, {"RewardsOps"})
    rec = fetch_or_404(db.redemptions, rid)
    account = db.accounts.get(rec["card_account_id"])
    # state (priority 7): redemption PENDING and account ACTIVE
    if rec["status"] != "PENDING":
        raise err(errors.ERR_INVALID_STATE, "Redemption is not PENDING.")
    if account is None or account["status"] != "ACTIVE":
        raise err(errors.ERR_INVALID_STATE, "Owning account is not ACTIVE.")

    # re-check sufficiency (priority 13)
    if rec["points_requested"] > account["points_balance"]:
        raise err(errors.ERR_INSUFFICIENT_POINTS, "Insufficient redeemable points at confirm.")

    # FIFO consumption
    remaining = rec["points_requested"]
    lots_consumed = []
    for lot in services.active_lots_fifo(account):
        if remaining <= 0:
            break
        take = min(lot["remaining_points"], remaining)
        if take <= 0:
            continue
        lot["remaining_points"] -= take
        if lot["remaining_points"] == 0:
            lot["status"] = "CONSUMED"
        lots_consumed.append({"points_lot_id": lot["id"], "points_taken": take})
        remaining -= take
    rec["lots_consumed"] = lots_consumed

    # redeemed_value
    partner = db.transfer_partners.get(rec["transfer_partner_id"]) if rec["transfer_partner_id"] else None
    rec["redeemed_value"] = services.compute_redeemed_value(rec, partner)
    rec["status"] = "CONFIRMED"

    services.recompute_balance(account)
    touch(rec)
    touch(account)
    return success(serialize.redemption_out(rec), status=200)


@app.route("/redemptions/<rid>/reject", methods=["POST"])
def reject_redemption(rid):
    _, role = authenticate()
    require_role(role, {"RewardsOps"})
    rec = fetch_or_404(db.redemptions, rid)
    if rec["status"] != "PENDING":
        raise err(errors.ERR_INVALID_STATE, "Redemption is not PENDING.")
    account = db.accounts.get(rec["card_account_id"])
    rec["status"] = "REJECTED"
    touch(rec)
    if account is not None:
        touch(account)
    return success(serialize.redemption_out(rec), status=200)


@app.route("/redemptions/<rid>/reverse", methods=["POST"])
def reverse_redemption(rid):
    _, role = authenticate()
    require_role(role, {"RewardsOps"})
    rec = fetch_or_404(db.redemptions, rid)
    if rec["status"] != "CONFIRMED":
        raise err(errors.ERR_INVALID_STATE, "Redemption is not CONFIRMED.")
    account = db.accounts.get(rec["card_account_id"])
    product = db.products.get(account["card_product_id"]) if account else None
    now = clock.now()

    # restore points to exactly the lots in lots_consumed
    for entry in rec["lots_consumed"]:
        lot = db.points_lots.get(entry["points_lot_id"])
        taken = entry["points_taken"]
        if lot is None:
            continue
        if lot["status"] in ("EXPIRED",) or parse_iso(lot["expires_at"]) <= now:
            # original lot has expired: spill into a fresh restoration lot with
            # the same expires_at as the original lot.
            new_lot = services.mint_lot(account, product, taken, lot["lot_type"], lot["source_transaction_id"])
            new_lot["expires_at"] = lot["expires_at"]
            # if the just-minted restoration lot is already past expiry, it stays
            # ACTIVE until a sweep; balance recompute counts ACTIVE lots.
        else:
            lot["remaining_points"] += taken
            if lot["status"] == "CONSUMED":
                lot["status"] = "ACTIVE"

    rec["status"] = "REVERSED"
    services.recompute_balance(account)
    touch(rec)
    touch(account)
    return success(serialize.redemption_out(rec), status=200)


# ===========================================================================
# CategoryActivation
# ===========================================================================

@app.route("/category-activations", methods=["POST"])
def create_category_activation():
    user_id, role = authenticate()
    require_role(role, {"Cardholder"})
    body = util.require_body(get_json())

    account_id = body.get("card_account_id")
    if not isinstance(account_id, str) or not account_id:
        require_owner(role, user_id, account_id if isinstance(account_id, str) else None)
        raise err(errors.ERR_INVALID_REQUEST, "card_account_id must be a string.")
    require_owner(role, user_id, account_id)

    # existence (priority 4): account, then quarterly_category
    account = db.accounts.get(account_id)
    if account is None:
        raise err(errors.ERR_RESOURCE_NOT_FOUND, "Referenced account does not exist.")
    quarterly_category_id = body.get("quarterly_category_id")
    if not isinstance(quarterly_category_id, str) or not quarterly_category_id:
        raise err(errors.ERR_INVALID_REQUEST, "quarterly_category_id must be a string.")
    quarterly = db.quarterly_categories.get(quarterly_category_id)
    if quarterly is None:
        raise err(errors.ERR_RESOURCE_NOT_FOUND, "Referenced quarterly category does not exist.")

    # state (priority 7): account ACTIVE
    if account["status"] != "ACTIVE":
        raise err(errors.ERR_INVALID_STATE, "Account is not ACTIVE.")

    # cross-product (priority 8): quarterly.card_product_id == account.card_product_id
    if quarterly["card_product_id"] != account["card_product_id"]:
        raise err(errors.ERR_CROSS_PRODUCT_MISMATCH, "Quarterly category belongs to a different product.")

    # uniqueness (priority 9): one ACTIVE per (account, quarterly_category)
    for a in db.category_activations.values():
        if (a["card_account_id"] == account_id
                and a["quarterly_category_id"] == quarterly_category_id
                and a["status"] == "ACTIVE"):
            raise err(errors.ERR_DUPLICATE_ACTIVATION, "Activation already exists.")

    rec = new_common()
    rec.update({
        "card_account_id": account_id,
        "quarterly_category_id": quarterly_category_id,
        "activated_at": rec["created_at"],
        "status": "ACTIVE",
    })
    db.category_activations[rec["id"]] = rec
    return success(serialize.category_activation_out(rec), status=201)


@app.route("/category-activations/<rid>", methods=["GET"])
def get_category_activation(rid):
    authenticate()
    rec = fetch_or_404(db.category_activations, rid)
    return success(serialize.category_activation_out(rec), status=200)


@app.route("/category-activations", methods=["GET"])
def list_category_activations():
    authenticate()
    return do_list(db.category_activations, serialize.category_activation_out, {
        "card_account_id": request.args.get("card_account_id"),
        "quarterly_category_id": request.args.get("quarterly_category_id"),
        "status": request.args.get("status"),
    })


# ===========================================================================
# Period close
# ===========================================================================

@app.route("/close-period", methods=["POST"])
def close_period():
    _, role = authenticate()
    require_role(role, {"RewardsOps"})
    summary = services.run_close_period()
    return success(summary, status=200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
