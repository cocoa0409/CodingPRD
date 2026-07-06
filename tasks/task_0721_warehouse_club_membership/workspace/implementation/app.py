"""Warehouse-Club Membership API — Flask entry point and all routes."""
import os

from flask import Flask, request

import errors
import serializers as S
from clock import clock
from db import db, iso
from errors import ApiError
from helpers import (
    get_body, parse_pagination, paginate, sort_by_created, parse_dt,
    require_fields, require_int, opt_int, opt_bool, require_str, is_int,
)
from middleware import get_user_context, require_roles
from response import ok, error_response
from services import (
    add_ledger_entry, add_fee_event, recompute_household_card_count,
    recompute_fees_paid, set_term, get_plan, reconcile, process_term_boundary,
    block_round, cancel_refund, _expire_unredeemed_reward, _revoke_all_cards,
    TERM_DAYS, NO_RECEIPT_WINDOW_DAYS,
)

app = Flask(__name__)

ALL_ROLES = {"ClubAdmin", "Member", "RegisterClerk", "ServiceDeskClerk"}


# --------------------------------------------------------------------------- #
# Error handling
# --------------------------------------------------------------------------- #
@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_NOT_FOUND", "Resource not found.", 404)


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_METHOD_NOT_ALLOWED", "Method not allowed.", 405)


@app.errorhandler(Exception)
def handle_generic(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    return error_response("ERR_INTERNAL", str(e), 500)


# --------------------------------------------------------------------------- #
# Auth helpers
# --------------------------------------------------------------------------- #
def auth(allowed_roles, anonymous_allowed=False):
    """Run auth (401) then RBAC (403). Returns (user_id, role)."""
    user_id, role = get_user_context(anonymous_allowed=anonymous_allowed)
    require_roles(role, allowed_roles)
    return user_id, role


def member_owns(role, user_id, membership_id):
    """For a Member, enforce ownership: X-User-ID == membership_id.
    ClubAdmin / clerks have override."""
    if role == "Member" and user_id != membership_id:
        raise ApiError(errors.ERR_INSUFFICIENT_PERMISSIONS, 403,
                       "Member may only act on their own membership.")


# --------------------------------------------------------------------------- #
# Existence helpers (404)
# --------------------------------------------------------------------------- #
def get_membership_or_404(mid):
    m = db.memberships.get(mid)
    if m is None:
        raise ApiError(errors.ERR_MEMBERSHIP_NOT_FOUND, 404, "Membership not found.")
    return m


def get_plan_or_404(pid):
    p = db.plans.get(pid)
    if p is None:
        raise ApiError(errors.ERR_PLAN_NOT_FOUND, 404, "Plan not found.")
    return p


def get_product_or_404(pid):
    p = db.products.get(pid)
    if p is None:
        raise ApiError(errors.ERR_PRODUCT_NOT_FOUND, 404, "Product not found.")
    return p


def get_transaction_or_404(tid):
    t = db.transactions.get(tid)
    if t is None:
        raise ApiError(errors.ERR_TRANSACTION_NOT_FOUND, 404, "Transaction not found.")
    return t


def get_return_or_404(rid):
    r = db.returns.get(rid)
    if r is None:
        raise ApiError(errors.ERR_RETURN_NOT_FOUND, 404, "Return not found.")
    return r


def get_card_or_404(cid):
    c = db.household_cards.get(cid)
    if c is None:
        raise ApiError(errors.ERR_CARD_NOT_FOUND, 404, "Card not found.")
    return c


def list_response(serializer, items):
    limit, offset = parse_pagination()
    items = sort_by_created(items)
    page, meta = paginate(items, limit, offset)
    return ok([serializer(x) for x in page], status=200, is_list=True, pagination=meta)


# =========================================================================== #
# Clock
# =========================================================================== #
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    auth({"ClubAdmin"})
    body = get_body()
    require_fields(body, ["to_iso8601"])
    dt = parse_dt(body["to_iso8601"])
    clock.set(dt)
    # Advancing the clock may surface term boundary transitions on subsequent reads.
    return ok({}, status=200)


# =========================================================================== #
# Plans
# =========================================================================== #
@app.route("/plans", methods=["POST"])
def create_plan():
    auth({"ClubAdmin"})
    body = get_body()
    require_fields(body, ["tier", "annual_fee_cents"])
    tier = body["tier"]
    if tier not in ("BASIC", "EXECUTIVE"):
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, "tier must be BASIC or EXECUTIVE.")
    annual_fee = require_int(body, "annual_fee_cents", minimum=0)
    reward_rate = opt_int(body, "reward_rate_bps", 0, minimum=0)
    reward_cap = opt_int(body, "reward_cap_cents", 0, minimum=0)
    max_household = opt_int(body, "max_household_cards", 1, minimum=0)
    addon_fee = opt_int(body, "addon_fee_cents", 0, minimum=0)

    if tier == "BASIC" and reward_rate != 0:
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, "BASIC plan must have reward_rate_bps == 0.")
    if tier == "BASIC" and reward_cap != 0:
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, "BASIC plan must have reward_cap_cents == 0.")

    p = {
        "tier": tier,
        "annual_fee_cents": annual_fee,
        "reward_rate_bps": reward_rate,
        "reward_cap_cents": reward_cap,
        "max_household_cards": max_household,
        "addon_fee_cents": addon_fee,
    }
    db.stamp_config(p)
    db.plans[p["id"]] = p
    return ok(S.plan_out(p), status=201)


@app.route("/plans", methods=["GET"])
def list_plans():
    auth(ALL_ROLES)
    parse_pagination()  # validate
    items = list(db.plans.values())
    tier = request.args.get("tier")
    if tier is not None:
        items = [x for x in items if x["tier"] == tier]
    return list_response(S.plan_out, items)


@app.route("/plans/<plan_id>", methods=["GET"])
def get_plan_route(plan_id):
    auth(ALL_ROLES)
    p = get_plan_or_404(plan_id)
    return ok(S.plan_out(p), status=200)


# =========================================================================== #
# Memberships
# =========================================================================== #
@app.route("/memberships", methods=["POST"])
def create_membership():
    auth({"Anonymous", "ClubAdmin"}, anonymous_allowed=True)
    body = get_body()
    require_fields(body, ["plan_id", "primary_member_name"])
    plan = get_plan_or_404(body["plan_id"])  # existence before well-formedness
    name = require_str(body, "primary_member_name")
    auto_renew = opt_bool(body, "auto_renew", True)

    m = {
        "plan_id": plan["id"],
        "primary_member_name": name,
        "status": "PENDING_PAYMENT",
        "auto_renew": auto_renew,
        "term_start_utc": None,
        "term_end_utc": None,
        "reward_accrued_cents": 0,
        "reward_redeemed_cents": 0,
        "fees_paid_cents": 0,
        "household_card_count": 0,
    }
    db.stamp_common(m)
    db.memberships[m["id"]] = m
    return ok(S.membership_out(m), status=201)


@app.route("/memberships/<membership_id>", methods=["GET"])
def get_membership_route(membership_id):
    user_id, role = auth(ALL_ROLES)
    m = get_membership_or_404(membership_id)
    member_owns(role, user_id, membership_id)
    reconcile(m)
    return ok(S.membership_out(m), status=200)


@app.route("/memberships", methods=["GET"])
def list_memberships():
    auth({"ClubAdmin"})
    parse_pagination()
    # Reconcile clock-driven transitions before listing.
    for m in list(db.memberships.values()):
        process_term_boundary(m)
        recompute_household_card_count(m)
        recompute_fees_paid(m)
    items = list(db.memberships.values())
    status = request.args.get("status")
    if status is not None:
        items = [x for x in items if x["status"] == status]
    return list_response(S.membership_out, items)


@app.route("/memberships/<membership_id>/renew", methods=["POST"])
def renew_membership(membership_id):
    user_id, role = auth({"Member", "ClubAdmin"})
    m = get_membership_or_404(membership_id)
    member_owns(role, user_id, membership_id)
    body = get_body()
    # well-formedness: expected_membership_version required integer
    if "expected_membership_version" not in body or body["expected_membership_version"] is None:
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, "expected_membership_version is required.")
    if not is_int(body["expected_membership_version"]):
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, "expected_membership_version must be an integer.")
    redeem = opt_int(body, "redeem_reward_cents", 0, minimum=0)

    # Apply any pending clock-driven boundary first so version reflects reality.
    process_term_boundary(m)

    # OCC check (priority 5) before state check (priority 6).
    if body["expected_membership_version"] != m["version"]:
        raise ApiError(errors.ERR_STALE_MEMBERSHIP_VERSION, 412, "Stale membership version.")

    if m["status"] != "ACTIVE":
        raise ApiError(errors.ERR_MEMBERSHIP_NOT_ACTIVE, 409, "Membership is not ACTIVE.")

    plan = get_plan(m)
    annual_fee = plan["annual_fee_cents"]

    # Reward redemption against the renewal fee (business fiscal, priority 13).
    available = m["reward_accrued_cents"] - m["reward_redeemed_cents"]
    if redeem > available:
        raise ApiError(errors.ERR_REWARD_REDEMPTION_EXCEEDS_AVAILABLE, 422,
                       "Redemption exceeds available reward.")
    applied = max(0, min(redeem, available, annual_fee))
    if applied > 0:
        m["reward_redeemed_cents"] += applied
        add_ledger_entry(m["id"], "REDEMPTION", -applied, m["term_start_utc"], None)

    prior_term_start = m["term_start_utc"]
    # EXPIRY of any unredeemed reward carried from the prior term.
    _expire_unredeemed_reward(m, prior_term_start)

    # Roll term: new start = old end.
    old_end = m["term_end_utc"]
    new_start = parse_dt(old_end)
    set_term(m, new_start)

    # FeeEvent RENEWAL net of redemption against the NEW term.
    add_fee_event(m["id"], "RENEWAL", annual_fee - applied, m["term_start_utc"])

    # Reset reward counters for new term.
    m["reward_accrued_cents"] = 0
    m["reward_redeemed_cents"] = 0

    recompute_fees_paid(m)
    recompute_household_card_count(m)
    db.touch(m)  # increments version by 1
    return ok(S.membership_out(m), status=200)


@app.route("/memberships/<membership_id>/cancel", methods=["POST"])
def cancel_membership(membership_id):
    user_id, role = auth({"Member", "ClubAdmin"})
    m = get_membership_or_404(membership_id)
    member_owns(role, user_id, membership_id)
    body = get_body()
    if "expected_membership_version" not in body or body["expected_membership_version"] is None:
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, "expected_membership_version is required.")
    if not is_int(body["expected_membership_version"]):
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, "expected_membership_version must be an integer.")

    process_term_boundary(m)

    if body["expected_membership_version"] != m["version"]:
        raise ApiError(errors.ERR_STALE_MEMBERSHIP_VERSION, 412, "Stale membership version.")

    if m["status"] != "ACTIVE":
        raise ApiError(errors.ERR_MEMBERSHIP_NOT_ACTIVE, 409, "Membership is not ACTIVE.")

    plan = get_plan(m)
    refund = cancel_refund(m, plan)
    term_start = m["term_start_utc"]

    add_fee_event(m["id"], "CANCEL_REFUND", -refund, term_start)
    _expire_unredeemed_reward(m, term_start)

    _revoke_all_cards(m)

    m["status"] = "CANCELLED"
    m["reward_accrued_cents"] = 0
    recompute_fees_paid(m)
    recompute_household_card_count(m)
    db.touch(m)  # increments version by 1
    return ok(S.membership_out(m), status=200)


# =========================================================================== #
# Payments
# =========================================================================== #
@app.route("/payments", methods=["POST"])
def create_payment():
    user_id, role = auth({"Member", "ClubAdmin"})
    body = get_body()
    require_fields(body, ["membership_id", "purpose", "outcome"])
    m = get_membership_or_404(body["membership_id"])
    member_owns(role, user_id, m["id"])

    purpose = body["purpose"]
    outcome = body["outcome"]
    if purpose not in ("SIGNUP", "RENEWAL"):
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, "purpose must be SIGNUP or RENEWAL.")
    if outcome not in ("PENDING", "SUCCEEDED", "FAILED"):
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, "outcome must be PENDING/SUCCEEDED/FAILED.")
    redeem = opt_int(body, "redeem_reward_cents", 0, minimum=0)

    plan = get_plan(m)
    annual_fee = plan["annual_fee_cents"]

    # Purpose/state guard (409).
    if purpose == "SIGNUP" and m["status"] != "PENDING_PAYMENT":
        raise ApiError(errors.ERR_PAYMENT_PURPOSE_MISMATCH, 409,
                       "SIGNUP payment requires PENDING_PAYMENT membership.")
    if purpose == "RENEWAL" and m["status"] not in ("EXPIRED", "ACTIVE"):
        raise ApiError(errors.ERR_PAYMENT_PURPOSE_MISMATCH, 409,
                       "RENEWAL payment requires EXPIRED or ACTIVE membership.")

    applied = 0
    if purpose == "RENEWAL":
        available = m["reward_accrued_cents"] - m["reward_redeemed_cents"]
        if redeem > available:
            raise ApiError(errors.ERR_REWARD_REDEMPTION_EXCEEDS_AVAILABLE, 422,
                           "Redemption exceeds available reward.")
        applied = max(0, min(redeem, available, annual_fee))

    amount_cents = annual_fee - applied

    payment = {
        "membership_id": m["id"],
        "purpose": purpose,
        "outcome": outcome,
        "amount_cents": amount_cents,
    }
    db.stamp_common(payment)
    db.payments[payment["id"]] = payment

    if outcome == "SUCCEEDED":
        if purpose == "SIGNUP":
            # Activation cascade.
            set_term(m, clock.get())
            m["status"] = "ACTIVE"
            add_fee_event(m["id"], "SIGNUP", annual_fee, m["term_start_utc"])
            recompute_fees_paid(m)
            db.touch(m)
        elif purpose == "RENEWAL" and m["status"] == "EXPIRED":
            # Reinstatement: roll term to clock_now, reset reward counters.
            if applied > 0:
                # Apply redemption ledger (reward existed before reset).
                m["reward_redeemed_cents"] += applied
                add_ledger_entry(m["id"], "REDEMPTION", -applied, m["term_start_utc"], None)
            set_term(m, clock.get())
            m["status"] = "ACTIVE"
            add_fee_event(m["id"], "RENEWAL", amount_cents, m["term_start_utc"])
            m["reward_accrued_cents"] = 0
            m["reward_redeemed_cents"] = 0
            recompute_fees_paid(m)
            db.touch(m)
        elif purpose == "RENEWAL" and m["status"] == "ACTIVE":
            # A SUCCEEDED RENEWAL payment on an ACTIVE membership records the
            # payment (used by clock-driven auto-renew); apply redemption if any.
            if applied > 0:
                m["reward_redeemed_cents"] += applied
                add_ledger_entry(m["id"], "REDEMPTION", -applied, m["term_start_utc"], None)
                db.touch(m)

    return ok(S.payment_out(payment), status=201)


@app.route("/payments", methods=["GET"])
def list_payments():
    user_id, role = auth({"ClubAdmin", "Member"})
    parse_pagination()
    items = list(db.payments.values())
    mid = request.args.get("membership_id")
    if role == "Member":
        items = [x for x in items if x["membership_id"] == user_id]
    if mid is not None:
        items = [x for x in items if x["membership_id"] == mid]
    return list_response(S.payment_out, items)


# =========================================================================== #
# Household Cards
# =========================================================================== #
@app.route("/household-cards", methods=["POST"])
def create_card():
    user_id, role = auth({"Member", "ClubAdmin"})
    body = get_body()
    require_fields(body, ["membership_id", "cardholder_name", "card_kind"])
    m = get_membership_or_404(body["membership_id"])
    member_owns(role, user_id, m["id"])

    name = require_str(body, "cardholder_name")
    card_kind = body["card_kind"]
    if card_kind not in ("INCLUDED", "PAID_ADDON"):
        raise ApiError(errors.ERR_CARD_KIND_INVALID, 400, "card_kind invalid.")

    plan = get_plan(m)
    active_cards = sum(
        1 for c in db.household_cards.values()
        if c["membership_id"] == m["id"] and c["status"] == "ACTIVE"
    )

    if card_kind == "INCLUDED":
        if active_cards >= plan["max_household_cards"]:
            raise ApiError(errors.ERR_HOUSEHOLD_CARD_LIMIT, 409, "Household card limit reached.")
        fee_charged = 0
    else:  # PAID_ADDON
        fee_charged = plan["addon_fee_cents"]

    card = {
        "membership_id": m["id"],
        "cardholder_name": name,
        "card_kind": card_kind,
        "status": "ACTIVE",
        "fee_charged_cents": fee_charged,
    }
    db.stamp_common(card)
    db.household_cards[card["id"]] = card

    if card_kind == "PAID_ADDON":
        add_fee_event(m["id"], "ADDON", plan["addon_fee_cents"], m["term_start_utc"])

    recompute_household_card_count(m)
    recompute_fees_paid(m)
    db.touch(m)
    return ok(S.card_out(card), status=201)


@app.route("/household-cards", methods=["GET"])
def list_cards():
    user_id, role = auth({"ClubAdmin", "Member"})
    parse_pagination()
    items = list(db.household_cards.values())
    if role == "Member":
        items = [x for x in items if x["membership_id"] == user_id]
    mid = request.args.get("membership_id")
    if mid is not None:
        items = [x for x in items if x["membership_id"] == mid]
    status = request.args.get("status")
    if status is not None:
        items = [x for x in items if x["status"] == status]
    return list_response(S.card_out, items)


@app.route("/household-cards/<card_id>", methods=["GET"])
def get_card_route(card_id):
    user_id, role = auth({"ClubAdmin", "Member"})
    c = get_card_or_404(card_id)
    member_owns(role, user_id, c["membership_id"])
    return ok(S.card_out(c), status=200)


@app.route("/household-cards/<card_id>/revoke", methods=["POST"])
def revoke_card(card_id):
    user_id, role = auth({"Member", "ClubAdmin"})
    c = get_card_or_404(card_id)
    member_owns(role, user_id, c["membership_id"])
    if c["status"] != "ACTIVE":
        raise ApiError(errors.ERR_CARD_NOT_ACTIVE, 409, "Card is not ACTIVE.")
    c["status"] = "REVOKED"
    db.touch(c)
    m = db.memberships.get(c["membership_id"])
    if m is not None:
        recompute_household_card_count(m)
        db.touch(m)
    return ok(S.card_out(c), status=200)


# =========================================================================== #
# Products
# =========================================================================== #
@app.route("/products", methods=["POST"])
def create_product():
    auth({"ClubAdmin"})
    body = get_body()
    require_fields(body, ["sku", "list_price_cents", "member_price_cents"])
    sku = require_str(body, "sku")
    list_price = require_int(body, "list_price_cents", minimum=0)
    member_price = require_int(body, "member_price_cents", minimum=0)
    member_only = opt_bool(body, "member_only", False)
    per_member_limit = opt_int(body, "per_member_limit", 0, minimum=0)
    department = body.get("department", "GENERAL")
    if department is None:
        department = "GENERAL"
    if department not in ("GENERAL", "GAS", "PHARMACY", "OPTICAL"):
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, "department invalid.")
    reward_eligible = opt_bool(body, "reward_eligible", True)

    if member_price > list_price:
        raise ApiError(errors.ERR_INVALID_PRICE, 400, "member_price_cents > list_price_cents.")

    for p in db.products.values():
        if p["sku"] == sku:
            raise ApiError(errors.ERR_PRODUCT_SKU_DUPLICATE, 409, "Duplicate sku.")

    p = {
        "sku": sku,
        "list_price_cents": list_price,
        "member_price_cents": member_price,
        "member_only": member_only,
        "per_member_limit": per_member_limit,
        "department": department,
        "reward_eligible": reward_eligible,
    }
    db.stamp_config(p)
    db.products[p["id"]] = p
    return ok(S.product_out(p), status=201)


@app.route("/products", methods=["GET"])
def list_products():
    auth(ALL_ROLES)
    parse_pagination()
    items = list(db.products.values())
    department = request.args.get("department")
    if department is not None:
        items = [x for x in items if x["department"] == department]
    member_only = request.args.get("member_only")
    if member_only is not None:
        want = member_only.lower() == "true"
        items = [x for x in items if x["member_only"] == want]
    return list_response(S.product_out, items)


@app.route("/products/<product_id>", methods=["GET"])
def get_product_route(product_id):
    auth(ALL_ROLES)
    p = get_product_or_404(product_id)
    return ok(S.product_out(p), status=200)


# =========================================================================== #
# Instant Savings
# =========================================================================== #
@app.route("/instant-savings", methods=["POST"])
def create_instant_saving():
    auth({"ClubAdmin"})
    body = get_body()
    require_fields(body, ["product_id", "kind", "amount_cents", "window_start_utc", "window_end_utc"])
    product = get_product_or_404(body["product_id"])
    kind = body["kind"]
    if kind not in ("INSTANT_SAVINGS", "MANUFACTURER_REBATE"):
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, "kind invalid.")
    amount = require_int(body, "amount_cents", minimum=0)
    max_units = opt_int(body, "max_units", 0, minimum=0)
    win_start = parse_dt(body["window_start_utc"])
    win_end = parse_dt(body["window_end_utc"])

    if win_end <= win_start:
        raise ApiError(errors.ERR_INVALID_PROMO_WINDOW, 400, "window_end_utc <= window_start_utc.")

    s = {
        "product_id": product["id"],
        "kind": kind,
        "amount_cents": amount,
        "window_start_utc": iso(win_start),
        "window_end_utc": iso(win_end),
        "max_units": max_units,
    }
    db.stamp_config(s)
    db.instant_savings[s["id"]] = s
    return ok(S.instant_saving_out(s), status=201)


@app.route("/instant-savings", methods=["GET"])
def list_instant_savings():
    auth(ALL_ROLES)
    parse_pagination()
    items = list(db.instant_savings.values())
    pid = request.args.get("product_id")
    if pid is not None:
        items = [x for x in items if x["product_id"] == pid]
    kind = request.args.get("kind")
    if kind is not None:
        items = [x for x in items if x["kind"] == kind]
    return list_response(S.instant_saving_out, items)


# =========================================================================== #
# Transactions
# =========================================================================== #
def _active_promos(product_id, kind):
    """InstantSaving rows for product with kind whose [start, end) contains clock_now."""
    now = iso(clock.get())
    result = []
    for s in db.instant_savings.values():
        if s["product_id"] != product_id or s["kind"] != kind:
            continue
        if s["window_start_utc"] <= now < s["window_end_utc"]:
            result.append(s)
    return result


def _recompute_transaction_totals(t):
    lines = [l for l in db.transaction_lines.values() if l["transaction_id"] == t["id"]]
    gross = sum(l["unit_price_cents"] * l["qty"] for l in lines)
    instant = sum(l["line_instant_savings_cents"] for l in lines)
    rebate = sum(l["line_rebate_cents"] for l in lines)
    net = max(0, gross - instant - rebate)
    t["gross_cents"] = gross
    t["instant_savings_cents"] = instant
    t["rebate_cents"] = rebate
    t["net_cents"] = net


@app.route("/transactions", methods=["POST"])
def create_transaction():
    auth({"RegisterClerk", "ClubAdmin"})
    body = get_body()
    require_fields(body, ["membership_id"])
    m = get_membership_or_404(body["membership_id"])
    process_term_boundary(m)
    if m["status"] != "ACTIVE":
        raise ApiError(errors.ERR_MEMBERSHIP_NOT_ACTIVE, 409, "Membership is not ACTIVE.")

    t = {
        "membership_id": m["id"],
        "status": "OPEN",
        "gross_cents": 0,
        "instant_savings_cents": 0,
        "rebate_cents": 0,
        "net_cents": 0,
        "reward_accrued_cents": 0,
        "finalized_at_utc": None,
    }
    db.stamp_common(t)
    db.transactions[t["id"]] = t
    return ok(S.transaction_out(t), status=201)


@app.route("/transactions/<transaction_id>", methods=["GET"])
def get_transaction_route(transaction_id):
    auth(ALL_ROLES)
    t = get_transaction_or_404(transaction_id)
    return ok(S.transaction_out(t), status=200)


@app.route("/transactions", methods=["GET"])
def list_transactions():
    auth(ALL_ROLES)
    parse_pagination()
    items = list(db.transactions.values())
    mid = request.args.get("membership_id")
    if mid is not None:
        items = [x for x in items if x["membership_id"] == mid]
    status = request.args.get("status")
    if status is not None:
        items = [x for x in items if x["status"] == status]
    return list_response(S.transaction_out, items)


def _term_purchased_qty(m, product_id, exclude_line_id=None):
    """Units of product already purchased by membership in current term:
    OPEN lines of any of its transactions + FINALIZED lines."""
    total = 0
    for t in db.transactions.values():
        if t["membership_id"] != m["id"]:
            continue
        if t["status"] not in ("OPEN", "FINALIZED"):
            continue
        # FINALIZED lines count only if within current term.
        if t["status"] == "FINALIZED":
            if t.get("finalized_at_utc") is None:
                continue
            if t["finalized_at_utc"] < (m.get("term_start_utc") or ""):
                continue
        for l in db.transaction_lines.values():
            if l["transaction_id"] != t["id"]:
                continue
            if l["product_id"] != product_id:
                continue
            if exclude_line_id is not None and l["id"] == exclude_line_id:
                continue
            total += l["qty"]
    return total


@app.route("/transactions/<transaction_id>/lines", methods=["POST"])
def add_line(transaction_id):
    auth({"RegisterClerk", "ClubAdmin"})
    t = get_transaction_or_404(transaction_id)
    body = get_body()
    require_fields(body, ["product_id", "qty"])
    product = get_product_or_404(body["product_id"])
    qty = body["qty"]
    if not is_int(qty) or qty < 1:
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, "qty must be an integer >= 1.")

    # State check (priority 6): transaction OPEN.
    if t["status"] != "OPEN":
        raise ApiError(errors.ERR_TRANSACTION_NOT_OPEN, 409, "Transaction is not OPEN.")

    m = db.memberships.get(t["membership_id"])
    process_term_boundary(m)
    # Owning membership must be ACTIVE (priority 7).
    if m["status"] != "ACTIVE":
        raise ApiError(errors.ERR_MEMBERSHIP_NOT_ACTIVE, 409, "Owning membership is not ACTIVE.")

    # member_only safety (priority 8). Membership is ACTIVE here, so this never
    # triggers; included for fidelity with spec ordering.
    if product["member_only"] and m["status"] != "ACTIVE":
        raise ApiError(errors.ERR_MEMBER_ONLY_PRODUCT, 403, "Member-only product.")

    # Per-member purchase limit (priority 9).
    limit = product["per_member_limit"]
    if limit > 0:
        already = _term_purchased_qty(m, product["id"])
        if already + qty > limit:
            raise ApiError(errors.ERR_PURCHASE_LIMIT_EXCEEDED, 409, "Purchase limit exceeded.")

    # Price snapshot.
    unit_price = product["member_price_cents"] if m["status"] == "ACTIVE" else product["list_price_cents"]
    gross_line = unit_price * qty

    # Instant savings then rebate, pinned order.
    instant = 0
    for s in _active_promos(product["id"], "INSTANT_SAVINGS"):
        units = qty if s["max_units"] == 0 else min(qty, s["max_units"])
        instant += s["amount_cents"] * units
    instant = min(instant, gross_line)
    base_after_instant = gross_line - instant

    rebate = 0
    for s in _active_promos(product["id"], "MANUFACTURER_REBATE"):
        units = qty if s["max_units"] == 0 else min(qty, s["max_units"])
        rebate += s["amount_cents"] * units
    rebate = min(rebate, base_after_instant)

    line = {
        "transaction_id": t["id"],
        "product_id": product["id"],
        "qty": qty,
        "unit_price_cents": unit_price,
        "line_instant_savings_cents": instant,
        "line_rebate_cents": rebate,
        "returned_qty": 0,
    }
    db.stamp_common(line)
    db.transaction_lines[line["id"]] = line

    _recompute_transaction_totals(t)
    db.touch(t)
    return ok(S.line_out(line), status=201)


@app.route("/transactions/<transaction_id>/lines", methods=["GET"])
def list_lines(transaction_id):
    auth(ALL_ROLES)
    t = get_transaction_or_404(transaction_id)
    parse_pagination()
    items = [l for l in db.transaction_lines.values() if l["transaction_id"] == t["id"]]
    return list_response(S.line_out, items)


@app.route("/transactions/<transaction_id>/finalize", methods=["POST"])
def finalize_transaction(transaction_id):
    auth({"RegisterClerk", "ClubAdmin"})
    t = get_transaction_or_404(transaction_id)

    if t["status"] != "OPEN":
        raise ApiError(errors.ERR_TRANSACTION_NOT_OPEN, 409, "Transaction is not OPEN.")

    lines = [l for l in db.transaction_lines.values() if l["transaction_id"] == t["id"]]
    if len(lines) == 0:
        raise ApiError(errors.ERR_EMPTY_TRANSACTION, 409, "Transaction has no lines.")

    m = db.memberships.get(t["membership_id"])
    process_term_boundary(m)
    if m["status"] != "ACTIVE":
        raise ApiError(errors.ERR_MEMBERSHIP_NOT_ACTIVE, 409, "Owning membership is not ACTIVE.")

    plan = get_plan(m)
    t["finalized_at_utc"] = iso(clock.get())
    t["status"] = "FINALIZED"

    accrued = 0
    if plan["tier"] == "EXECUTIVE":
        reward_base = 0
        for l in lines:
            product = db.products.get(l["product_id"])
            if product and product["reward_eligible"]:
                line_net = l["unit_price_cents"] * l["qty"] - l["line_instant_savings_cents"] - l["line_rebate_cents"]
                reward_base += line_net
        raw_reward = (reward_base * plan["reward_rate_bps"]) // 10000
        cap_remaining = plan["reward_cap_cents"] - m["reward_accrued_cents"]
        accrued = max(0, min(raw_reward, cap_remaining))

    t["reward_accrued_cents"] = accrued
    db.touch(t)

    if accrued > 0:
        m["reward_accrued_cents"] += accrued
        add_ledger_entry(m["id"], "ACCRUAL", accrued, m["term_start_utc"], t["id"])
        db.touch(m)
    elif plan["tier"] == "EXECUTIVE":
        # ledger entry only written when accrued > 0 per spec
        pass

    return ok(S.transaction_out(t), status=200)


@app.route("/transactions/<transaction_id>/void", methods=["POST"])
def void_transaction(transaction_id):
    auth({"RegisterClerk", "ClubAdmin"})
    t = get_transaction_or_404(transaction_id)
    if t["status"] != "OPEN":
        raise ApiError(errors.ERR_TRANSACTION_NOT_OPEN, 409, "Transaction is not OPEN.")
    t["status"] = "VOIDED"
    db.touch(t)
    return ok(S.transaction_out(t), status=200)


# =========================================================================== #
# Returns
# =========================================================================== #
def _find_receipted_line(transaction_id, product_id):
    """Return the TransactionLine for (transaction_id, product_id), or None."""
    for l in db.transaction_lines.values():
        if l["transaction_id"] == transaction_id and l["product_id"] == product_id:
            return l
    return None


def _line_net_total(l):
    return l["unit_price_cents"] * l["qty"] - l["line_instant_savings_cents"] - l["line_rebate_cents"]


def _line_attributable_accrual(l, m):
    """The ACCRUAL attributable to this line (net basis * rate, capped share).

    We reconstruct the per-line accrual from the transaction's recorded accrual,
    prorated by this line's reward-eligible net over the transaction's total
    reward-eligible net basis (block rounding).
    """
    t = db.transactions.get(l["transaction_id"])
    if t is None or t["reward_accrued_cents"] == 0:
        return 0
    product = db.products.get(l["product_id"])
    if not product or not product["reward_eligible"]:
        return 0
    # total reward-eligible net basis for the transaction
    total_base = 0
    for ll in db.transaction_lines.values():
        if ll["transaction_id"] != t["id"]:
            continue
        pp = db.products.get(ll["product_id"])
        if pp and pp["reward_eligible"]:
            total_base += _line_net_total(ll)
    if total_base == 0:
        return 0
    line_base = _line_net_total(l)
    return (t["reward_accrued_cents"] * line_base) // total_base


@app.route("/returns", methods=["POST"])
def create_return():
    auth({"ServiceDeskClerk", "ClubAdmin"})
    body = get_body()
    require_fields(body, ["membership_id", "product_id", "qty"])
    m = get_membership_or_404(body["membership_id"])
    # transaction (if provided) resolved before product per left-to-right order.
    txn_id = body.get("transaction_id")
    txn = None
    if txn_id is not None:
        txn = get_transaction_or_404(txn_id)
    product = get_product_or_404(body["product_id"])
    qty = body["qty"]
    if not is_int(qty) or qty < 1:
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, "qty must be an integer >= 1.")

    if txn_id is not None:
        # Receipted.
        lookup_mode = "RECEIPTED"
        line = _find_receipted_line(txn["id"], product["id"])
        if line is None:
            # No matching line; treat as qty exceeding purchased (0 purchased).
            raise ApiError(errors.ERR_RETURN_QTY_EXCEEDS_PURCHASED, 409,
                           "No matching line for receipted return.")
        if line["returned_qty"] + qty > line["qty"]:
            raise ApiError(errors.ERR_RETURN_QTY_EXCEEDS_PURCHASED, 409,
                           "Return qty exceeds purchased.")
    else:
        # No-receipt lookup policy.
        lookup_mode = _resolve_no_receipt(m, product)
        if lookup_mode == "DENIED":
            raise ApiError(errors.ERR_NO_RECEIPT_LOOKUP_DENIED, 409,
                           "No-receipt lookup denied.")

    r = {
        "membership_id": m["id"],
        "transaction_id": txn_id,
        "product_id": product["id"],
        "qty": qty,
        "lookup_mode": lookup_mode,
        "status": "PENDING",
        "refund_cents": 0,
        "reward_reversal_cents": 0,
    }
    db.stamp_common(r)
    db.returns[r["id"]] = r
    return ok(S.return_out(r), status=201)


def _resolve_no_receipt(m, product):
    """Return NO_RECEIPT_LOOKUP if a qualifying FINALIZED txn exists, else DENIED."""
    from helpers import parse_dt
    now = clock.get()
    qualifying = []
    for t in db.transactions.values():
        if t["membership_id"] != m["id"] or t["status"] != "FINALIZED":
            continue
        if t.get("finalized_at_utc") is None:
            continue
        # contains the product?
        has_product = any(
            l["transaction_id"] == t["id"] and l["product_id"] == product["id"]
            for l in db.transaction_lines.values()
        )
        if not has_product:
            continue
        fin = parse_dt(t["finalized_at_utc"])
        age_days = int((now - fin).total_seconds() // 86400)
        if age_days <= NO_RECEIPT_WINDOW_DAYS:
            qualifying.append(t)
    if not qualifying:
        return "DENIED"
    return "NO_RECEIPT_LOOKUP"


@app.route("/returns/<return_id>", methods=["GET"])
def get_return_route(return_id):
    user_id, role = auth({"ClubAdmin", "ServiceDeskClerk", "Member"})
    r = get_return_or_404(return_id)
    member_owns(role, user_id, r["membership_id"])
    return ok(S.return_out(r), status=200)


@app.route("/returns", methods=["GET"])
def list_returns():
    user_id, role = auth({"ClubAdmin", "ServiceDeskClerk", "Member"})
    parse_pagination()
    items = list(db.returns.values())
    if role == "Member":
        items = [x for x in items if x["membership_id"] == user_id]
    mid = request.args.get("membership_id")
    if mid is not None:
        items = [x for x in items if x["membership_id"] == mid]
    txn_id = request.args.get("transaction_id")
    if txn_id is not None:
        items = [x for x in items if x["transaction_id"] == txn_id]
    status = request.args.get("status")
    if status is not None:
        items = [x for x in items if x["status"] == status]
    return list_response(S.return_out, items)


@app.route("/returns/<return_id>/approve", methods=["POST"])
def approve_return(return_id):
    auth({"ServiceDeskClerk", "ClubAdmin"})
    r = get_return_or_404(return_id)
    if r["status"] != "PENDING":
        raise ApiError(errors.ERR_RETURN_NOT_PENDING, 409, "Return is not PENDING.")
    if r["lookup_mode"] == "DENIED":
        # Should not be reachable (denied returns are never created), but guard.
        raise ApiError(errors.ERR_NO_RECEIPT_LOOKUP_DENIED, 409, "Return lookup denied.")

    m = db.memberships.get(r["membership_id"])
    plan = get_plan(m)
    product = db.products.get(r["product_id"])

    refund = 0
    reversal = 0

    if r["lookup_mode"] == "RECEIPTED":
        txn = db.transactions.get(r["transaction_id"])
        if txn is None or txn["status"] != "FINALIZED":
            raise ApiError(errors.ERR_TRANSACTION_NOT_OPEN, 409, "Original transaction not FINALIZED.")
        line = _find_receipted_line(txn["id"], product["id"])
        if line is None or line["returned_qty"] + r["qty"] > line["qty"]:
            raise ApiError(errors.ERR_RETURN_QTY_EXCEEDS_PURCHASED, 409, "Return qty exceeds purchased.")
        line_net_total = _line_net_total(line)
        refund = block_round(line_net_total, r["qty"], line["qty"])
        if plan["tier"] == "EXECUTIVE" and product["reward_eligible"]:
            line_reward = _line_attributable_accrual(line, m)
            reversal = block_round(line_reward, r["qty"], line["qty"])
        # apply reversal
        if reversal > 0:
            m["reward_accrued_cents"] -= reversal
            add_ledger_entry(m["id"], "REVERSAL", -reversal, m["term_start_utc"], txn["id"])
        line["returned_qty"] += r["qty"]
        db.touch(line)
        if reversal > 0:
            db.touch(m)
    elif r["lookup_mode"] == "NO_RECEIPT_LOOKUP":
        refund = product["member_price_cents"] * r["qty"]
        reversal = 0

    r["refund_cents"] = refund
    r["reward_reversal_cents"] = reversal
    r["status"] = "APPROVED"
    db.touch(r)
    return ok(S.return_out(r), status=200)


@app.route("/returns/<return_id>/reject", methods=["POST"])
def reject_return(return_id):
    auth({"ServiceDeskClerk", "ClubAdmin"})
    r = get_return_or_404(return_id)
    if r["status"] != "PENDING":
        raise ApiError(errors.ERR_RETURN_NOT_PENDING, 409, "Return is not PENDING.")
    r["refund_cents"] = 0
    r["reward_reversal_cents"] = 0
    r["status"] = "REJECTED"
    db.touch(r)
    return ok(S.return_out(r), status=200)


# =========================================================================== #
# Reward ledger & fee events (reverse-reachability reads)
# =========================================================================== #
@app.route("/reward-ledger", methods=["GET"])
def list_reward_ledger():
    user_id, role = auth({"ClubAdmin", "Member"})
    parse_pagination()
    items = list(db.reward_ledger.values())
    if role == "Member":
        items = [x for x in items if x["membership_id"] == user_id]
    mid = request.args.get("membership_id")
    if mid is not None:
        items = [x for x in items if x["membership_id"] == mid]
    stid = request.args.get("source_transaction_id")
    if stid is not None:
        items = [x for x in items if x["source_transaction_id"] == stid]
    etype = request.args.get("entry_type")
    if etype is not None:
        items = [x for x in items if x["entry_type"] == etype]
    return list_response(S.ledger_out, items)


@app.route("/fee-events", methods=["GET"])
def list_fee_events():
    user_id, role = auth({"ClubAdmin", "Member"})
    parse_pagination()
    items = list(db.fee_events.values())
    if role == "Member":
        items = [x for x in items if x["membership_id"] == user_id]
    mid = request.args.get("membership_id")
    if mid is not None:
        items = [x for x in items if x["membership_id"] == mid]
    kind = request.args.get("kind")
    if kind is not None:
        items = [x for x in items if x["kind"] == kind]
    return list_response(S.fee_event_out, items)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
