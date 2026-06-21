"""Application endpoints (PRD §3.2, §3.3)."""
from flask import Blueprint, request

import db
from errors import err
from middleware import authenticate, require_role, require_borrower_owns
from response import success
from services import engine
from services import calculations as calc
from services.engine import stamp_new, touch, serialize_application
from routes.common import (
    get_json_body, require_str, require_int, parse_pagination, paginate,
    sort_by_created, require_application, require_borrower, require_merchant,
)

bp = Blueprint("applications", __name__)

VALID_PLANS = {"PAY_IN_4", "MONTHLY"}
VALID_DECISIONS = {"APPROVE", "COUNTER", "DECLINE"}


def _price_provisional(app):
    """Provisional pricing off requested_down_payment (PRD §3.2)."""
    down = app["requested_down_payment_cents"]
    apr, fp, fc, top = calc.finance_figures(
        app["cart_amount_cents"], down, app["plan_type"], app.get("term_months"))
    app["apr_bps"] = apr
    app["financed_principal_cents"] = fp
    app["finance_charge_cents"] = fc
    app["total_of_payments_cents"] = top


def _price_approved(app, approved_down):
    """Recompute figures off the fixed approved down payment (PRD §3.3)."""
    app["approved_down_payment_cents"] = approved_down
    apr, fp, fc, top = calc.finance_figures(
        app["cart_amount_cents"], approved_down, app["plan_type"],
        app.get("term_months"))
    app["apr_bps"] = apr
    app["financed_principal_cents"] = fp
    app["finance_charge_cents"] = fc
    app["total_of_payments_cents"] = top


@bp.route("/applications", methods=["POST"])
def create_application():
    uid, role = authenticate()
    require_role(role, {"Borrower"})
    body = get_json_body()

    # Existence (priority 3): body FK ids resolve left-to-right.
    borrower_id = require_str(body, "borrower_id")
    merchant_id = require_str(body, "merchant_id")
    borrower = require_borrower(borrower_id)
    merchant = require_merchant(merchant_id)

    # Ownership: a Borrower may only submit on its own borrower_id.
    require_borrower_owns(role, uid, borrower_id)

    # Schema validity (priority 4).
    cart_amount_cents = require_int(body, "cart_amount_cents", gt=0)
    plan_type = require_str(body, "plan_type")
    if plan_type not in VALID_PLANS:
        raise err("ERR_INVALID_REQUEST", "plan_type must be PAY_IN_4 or MONTHLY.")

    term_months = None
    if plan_type == "MONTHLY":
        # term_months REQUIRED and 3..24
        term_months = require_int(body, "term_months", required=True,
                                  minimum=3, maximum=24)
    else:
        # PAY_IN_4: term_months MUST be omitted entirely
        if "term_months" in body and body.get("term_months") is not None:
            raise err("ERR_INVALID_REQUEST",
                      "term_months must be omitted for PAY_IN_4.")

    requested_down = require_int(body, "requested_down_payment_cents",
                                 required=False, default=0, minimum=0)
    if requested_down >= cart_amount_cents:
        raise err("ERR_INVALID_REQUEST",
                  "requested_down_payment_cents must be < cart_amount_cents.")

    app = {
        "borrower_id": borrower_id,
        "merchant_id": merchant_id,
        "cart_amount_cents": cart_amount_cents,
        "plan_type": plan_type,
        "term_months": term_months,
        "requested_down_payment_cents": requested_down,
        "approved_down_payment_cents": None,
        "status": "SUBMITTED",
        "decline_reason": None,
    }
    _price_provisional(app)
    stamp_new(app)
    db.applications[app["id"]] = app
    return success(serialize_application(app), status=201)


@bp.route("/applications/<application_id>", methods=["GET"])
def get_application(application_id):
    uid, role = authenticate()
    require_role(role, {"Servicer", "Borrower", "Merchant"})
    app = require_application(application_id)
    require_borrower_owns(role, uid, app["borrower_id"])
    require_merchant_owns_app(role, uid, app["merchant_id"])
    return success(serialize_application(app), status=200)


def require_merchant_owns_app(role, uid, merchant_id):
    if role == "Merchant" and uid != merchant_id:
        raise err("ERR_FORBIDDEN", "Merchant does not own the targeted resource.")


@bp.route("/applications", methods=["GET"])
def list_applications():
    uid, role = authenticate()
    require_role(role, {"Servicer", "Borrower", "Merchant"})
    limit, offset = parse_pagination()
    borrower_filter = request.args.get("borrower_id")
    merchant_filter = request.args.get("merchant_id")

    rows = list(db.applications.values())
    if borrower_filter is not None:
        rows = [a for a in rows if a["borrower_id"] == borrower_filter]
    if merchant_filter is not None:
        rows = [a for a in rows if a["merchant_id"] == merchant_filter]
    # Ownership scoping for entity-backed roles.
    if role == "Borrower":
        rows = [a for a in rows if a["borrower_id"] == uid]
    elif role == "Merchant":
        rows = [a for a in rows if a["merchant_id"] == uid]

    rows = sort_by_created(rows)
    page, meta = paginate(rows, limit, offset)
    return success([serialize_application(a) for a in page],
                   status=200, pagination=meta)


@bp.route("/applications/<application_id>/decision", methods=["POST"])
def decide_application(application_id):
    _uid, role = authenticate()
    require_role(role, {"Servicer"})
    app = require_application(application_id)
    body = get_json_body()

    decision = require_str(body, "decision")
    if decision not in VALID_DECISIONS:
        raise err("ERR_INVALID_REQUEST",
                  "decision must be APPROVE, COUNTER, or DECLINE.")

    # State legality (priority 5): must be SUBMITTED.
    if app["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE",
                  "Application must be SUBMITTED to be decided.")

    borrower = db.borrowers[app["borrower_id"]]
    merchant = db.merchants[app["merchant_id"]]

    outstanding = engine.compute_borrower_outstanding(borrower["id"])
    avail = max(0, borrower["eligible_credit_limit_cents"] - outstanding)
    need = app["cart_amount_cents"] - app["requested_down_payment_cents"]

    # Determine the natural outcome (PRD §3.3). The supplied `decision` selects
    # the branch the servicer takes; the eligibility math determines its details.
    if merchant["status"] == "SUSPENDED":
        _apply_decline(app, "MERCHANT_SUSPENDED")
    elif avail == 0:
        _apply_decline(app, "INSUFFICIENT_CREDIT")
    elif need <= avail:
        _apply_approve(app)
    elif (app["cart_amount_cents"] - 1) <= avail:
        _apply_counter(app, avail)
    else:
        _apply_decline(app, "DOWN_PAYMENT_TOO_LOW")

    touch(app)
    return success(serialize_application(app), status=200)


def _apply_approve(app):
    app["status"] = "APPROVED"
    _price_approved(app, app["requested_down_payment_cents"])


def _apply_counter(app, avail):
    app["status"] = "COUNTERED"
    # minimum down payment that fits the limit = cart - available credit
    countered_down = app["cart_amount_cents"] - avail
    _price_approved(app, countered_down)


def _apply_decline(app, reason):
    app["status"] = "DECLINED"
    app["decline_reason"] = reason


@bp.route("/applications/<application_id>/revise", methods=["POST"])
def revise_application(application_id):
    uid, role = authenticate()
    require_role(role, {"Borrower"})
    app = require_application(application_id)
    require_borrower_owns(role, uid, app["borrower_id"])
    body = get_json_body()

    new_down = require_int(body, "requested_down_payment_cents", minimum=0)

    # State legality.
    if app["status"] != "COUNTERED":
        raise err("ERR_INVALID_STATE",
                  "Application must be COUNTERED to be revised.")
    # New value must be >= the countered approved_down_payment.
    if new_down < app["approved_down_payment_cents"]:
        raise err("ERR_INVALID_REQUEST",
                  "requested_down_payment_cents must be >= the countered down payment.")
    if new_down >= app["cart_amount_cents"]:
        raise err("ERR_INVALID_REQUEST",
                  "requested_down_payment_cents must be < cart_amount_cents.")

    app["requested_down_payment_cents"] = new_down
    app["status"] = "SUBMITTED"
    app["decline_reason"] = None
    _price_provisional(app)
    touch(app)
    return success(serialize_application(app), status=200)


@bp.route("/applications/<application_id>/withdraw", methods=["POST"])
def withdraw_application(application_id):
    uid, role = authenticate()
    require_role(role, {"Borrower"})
    app = require_application(application_id)
    require_borrower_owns(role, uid, app["borrower_id"])

    if app["status"] not in ("SUBMITTED", "COUNTERED"):
        raise err("ERR_INVALID_STATE",
                  "Application must be SUBMITTED or COUNTERED to withdraw.")
    app["status"] = "WITHDRAWN"
    touch(app)
    return success(serialize_application(app), status=200)
