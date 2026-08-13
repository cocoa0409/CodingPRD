"""ConsentOrder + PenaltyPayment endpoints."""

import uuid
from flask import Blueprint, request

import db
from errors import (
    err,
    ERR_INVALID_REQUEST,
    ERR_EXCEEDANCE_NOT_FOUND,
    ERR_CONSENT_ORDER_NOT_FOUND,
    ERR_CONSENT_ORDER_INVALID_STATE,
    ERR_CONSENT_ORDER_NOT_PAYABLE,
    ERR_PAYMENT_AMOUNT_INVALID,
    ERR_REFUND_EXCEEDS_PAID,
)
from middleware import require_roles
from response import success, list_success
from util import get_body, require_fields, dec
from services.core import (
    base_entity,
    ledger_entity,
    touch,
    append_audit,
    serialize_consent_order,
    serialize_penalty_payment,
    paginate,
    recompute_permit_rollup,
    permit_for_exceedance,
    ASSESSMENT_VARIANTS,
    PAYMENT_DIRECTIONS,
)
from services.penalty import compute_final_amount

bp = Blueprint("consent_orders", __name__)


def _refresh_order_totals(co):
    """Recompute paid_cents / refunded_cents / outstanding_cents from the ledger."""
    paid = 0
    refunded = 0
    for p in db.penalty_payments.values():
        if p["consent_order_id"] != co["id"] or p["status"] != "POSTED":
            continue
        if p["direction"] == "PAYMENT":
            paid += p["amount_cents"]
        else:
            refunded += p["amount_cents"]
    co["paid_cents"] = paid
    co["refunded_cents"] = refunded
    if co["status"] in ("FINAL", "SATISFIED") and co["final_amount_cents"] is not None:
        co["outstanding_cents"] = co["final_amount_cents"] - (paid - refunded)
    else:
        co["outstanding_cents"] = 0


@bp.route("/npdes/consent-orders", methods=["POST"])
def create_consent_order():
    user_id, role = require_roles(["Regulator"])
    body = get_body()
    require_fields(body, ["exceedance_id", "assessment_variant", "base_penalty_cents", "statutory_cap_cents"])
    exc = db.exceedances.get(body["exceedance_id"])
    if exc is None:
        raise err(ERR_EXCEEDANCE_NOT_FOUND, 404, "Exceedance not found")

    variant = body["assessment_variant"]
    if variant not in ASSESSMENT_VARIANTS:
        raise err(ERR_INVALID_REQUEST, 400, "assessment_variant must be PER_DAY or ECONOMIC_BENEFIT")

    base = body["base_penalty_cents"]
    if isinstance(base, bool) or not isinstance(base, int) or base <= 0:
        raise err(ERR_INVALID_REQUEST, 400, "base_penalty_cents must be a strictly positive integer")
    cap = body["statutory_cap_cents"]
    if isinstance(cap, bool) or not isinstance(cap, int) or cap <= 0:
        raise err(ERR_INVALID_REQUEST, 400, "statutory_cap_cents must be a strictly positive integer")
    if base > cap:
        raise err(ERR_INVALID_REQUEST, 400, "base_penalty_cents must not exceed statutory_cap_cents")

    daily = body.get("daily_accrual_cents")
    if daily is not None:
        if isinstance(daily, bool) or not isinstance(daily, int) or daily < 0:
            raise err(ERR_INVALID_REQUEST, 400, "daily_accrual_cents must be an integer >= 0")
    avoided = body.get("avoided_cost_cents")
    if avoided is not None:
        if isinstance(avoided, bool) or not isinstance(avoided, int) or avoided < 0:
            raise err(ERR_INVALID_REQUEST, 400, "avoided_cost_cents must be an integer >= 0")
    gravity = body.get("gravity_factor")
    if gravity is not None:
        g = dec(gravity)
        if g <= 0:
            raise err(ERR_INVALID_REQUEST, 400, "gravity_factor must be strictly greater than zero")
    else:
        g = None

    co = base_entity("ConsentOrder")
    co["id"] = str(uuid.uuid4())
    co.update(
        {
            "exceedance_id": exc["id"],
            "assessment_variant": variant,
            "base_penalty_cents": base,
            "daily_accrual_cents": daily,
            "avoided_cost_cents": avoided,
            "gravity_factor": g,
            "statutory_cap_cents": cap,
            "status": "PROPOSED",
            "issued_at": None,
            "finalized_at": None,
            "cure_date": None,
            "final_amount_cents": None,
            "paid_cents": 0,
            "refunded_cents": 0,
            "outstanding_cents": 0,
        }
    )
    db.consent_orders[co["id"]] = co

    # Proposing already moves the exceedance's enforcement dimension NONE -> ORDER_ISSUED
    if exc["enforcement_status"] == "NONE":
        exc["enforcement_status"] = "ORDER_ISSUED"
        touch(exc)
    permit = permit_for_exceedance(exc)
    if permit is not None:
        recompute_permit_rollup(permit["id"])

    append_audit("ConsentOrder", co["id"], "ORDER_PROPOSED", user_id, role)
    return success(serialize_consent_order(co), 201)


@bp.route("/npdes/consent-orders", methods=["GET"])
def list_consent_orders():
    require_roles(["Any"])
    items = list(db.consent_orders.values())
    exceedance_id = request.args.get("exceedance_id")
    if exceedance_id:
        items = [c for c in items if c["exceedance_id"] == exceedance_id]
    status = request.args.get("status")
    if status:
        items = [c for c in items if c["status"] == status]
    for co in items:
        _refresh_order_totals(co)
    page, total, limit, offset = paginate(items, request.args)
    return list_success([serialize_consent_order(c) for c in page], total, limit, offset)


@bp.route("/npdes/consent-orders/<cid>", methods=["GET"])
def get_consent_order(cid):
    require_roles(["Any"])
    co = db.consent_orders.get(cid)
    if co is None:
        raise err(ERR_CONSENT_ORDER_NOT_FOUND, 404, "ConsentOrder not found")
    _refresh_order_totals(co)
    return success(serialize_consent_order(co), 200)


@bp.route("/npdes/consent-orders/<cid>/issue", methods=["POST"])
def issue_order(cid):
    user_id, role = require_roles(["Regulator"])
    co = db.consent_orders.get(cid)
    if co is None:
        raise err(ERR_CONSENT_ORDER_NOT_FOUND, 404, "ConsentOrder not found")
    if co["status"] != "PROPOSED":
        raise err(ERR_CONSENT_ORDER_INVALID_STATE, 409, "Issue requires PROPOSED")
    co["issued_at"] = db.clock.now()
    co["status"] = "ISSUED"
    touch(co)
    exc = db.exceedances.get(co["exceedance_id"])
    if exc is not None:
        permit = permit_for_exceedance(exc)
        if permit is not None:
            recompute_permit_rollup(permit["id"])
    append_audit("ConsentOrder", co["id"], "ORDER_ISSUED", user_id, role)
    return success(serialize_consent_order(co), 200)


@bp.route("/npdes/consent-orders/<cid>/appeal", methods=["POST"])
def appeal_order(cid):
    user_id, role = require_roles(["EnvironmentalManager"])
    co = db.consent_orders.get(cid)
    if co is None:
        raise err(ERR_CONSENT_ORDER_NOT_FOUND, 404, "ConsentOrder not found")
    if co["status"] != "ISSUED":
        raise err(ERR_CONSENT_ORDER_INVALID_STATE, 409, "Appeal requires ISSUED")
    body = get_body()
    require_fields(body, ["appeal_grounds"])
    co["status"] = "UNDER_APPEAL"
    touch(co)
    append_audit("ConsentOrder", co["id"], "ORDER_APPEALED", user_id, role)
    return success(serialize_consent_order(co), 200)


@bp.route("/npdes/consent-orders/<cid>/finalize", methods=["POST"])
def finalize_order(cid):
    user_id, role = require_roles(["Regulator"])
    co = db.consent_orders.get(cid)
    if co is None:
        raise err(ERR_CONSENT_ORDER_NOT_FOUND, 404, "ConsentOrder not found")
    if co["status"] not in ("ISSUED", "UNDER_APPEAL"):
        raise err(ERR_CONSENT_ORDER_INVALID_STATE, 409, "Finalize requires ISSUED or UNDER_APPEAL")

    final_amount, cure_date = compute_final_amount(co)
    co["finalized_at"] = db.clock.now()
    co["cure_date"] = cure_date
    co["final_amount_cents"] = final_amount
    _refresh_order_totals(co)
    co["outstanding_cents"] = final_amount - (co["paid_cents"] - co["refunded_cents"])
    co["status"] = "FINAL"
    touch(co)
    append_audit("ConsentOrder", co["id"], "ORDER_FINAL", user_id, role)
    return success(serialize_consent_order(co), 200)


@bp.route("/npdes/consent-orders/<cid>/payments", methods=["POST"])
def post_payment(cid):
    user_id, role = require_roles(["ComplianceOfficer"])
    co = db.consent_orders.get(cid)
    if co is None:
        raise err(ERR_CONSENT_ORDER_NOT_FOUND, 404, "ConsentOrder not found")
    body = get_body()
    require_fields(body, ["direction", "amount_cents"])
    direction = body["direction"]
    if direction not in PAYMENT_DIRECTIONS:
        raise err(ERR_INVALID_REQUEST, 400, "direction must be PAYMENT or REFUND")
    amount = body["amount_cents"]
    if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
        raise err(ERR_INVALID_REQUEST, 400, "amount_cents must be a strictly positive integer")

    if co["status"] != "FINAL":
        raise err(ERR_CONSENT_ORDER_NOT_PAYABLE, 409, "Payments require the order in FINAL")

    _refresh_order_totals(co)
    if direction == "PAYMENT":
        if amount > co["outstanding_cents"]:
            raise err(ERR_PAYMENT_AMOUNT_INVALID, 422, "PAYMENT exceeds outstanding_cents")
    else:
        if amount > (co["paid_cents"] - co["refunded_cents"]):
            raise err(ERR_REFUND_EXCEEDS_PAID, 422, "REFUND exceeds net paid amount")

    payment = ledger_entity()
    payment["id"] = str(uuid.uuid4())
    payment.update(
        {
            "consent_order_id": co["id"],
            "direction": direction,
            "amount_cents": amount,
            "posted_at": db.clock.now(),
            "status": "POSTED",
        }
    )
    db.penalty_payments[payment["id"]] = payment
    append_audit("PenaltyPayment", payment["id"], "PAYMENT_POSTED", user_id, role)

    _refresh_order_totals(co)
    touch(co)

    # Auto-satisfaction: outstanding exactly 0 -> SATISFIED, enforcement resolved
    if co["status"] == "FINAL" and co["outstanding_cents"] == 0:
        co["status"] = "SATISFIED"
        append_audit("ConsentOrder", co["id"], "ORDER_SATISFIED", "system", "system")
        exc = db.exceedances.get(co["exceedance_id"])
        if exc is not None and exc["enforcement_status"] == "ORDER_ISSUED":
            exc["enforcement_status"] = "RESOLVED"
            touch(exc)
            permit = permit_for_exceedance(exc)
            if permit is not None:
                recompute_permit_rollup(permit["id"])

    return success(serialize_penalty_payment(payment), 201)


@bp.route("/npdes/consent-orders/<cid>/payments", methods=["GET"])
def list_payments(cid):
    require_roles(["Any"])
    co = db.consent_orders.get(cid)
    if co is None:
        raise err(ERR_CONSENT_ORDER_NOT_FOUND, 404, "ConsentOrder not found")
    items = [p for p in db.penalty_payments.values() if p["consent_order_id"] == cid]
    page, total, limit, offset = paginate(items, request.args)
    return list_success([serialize_penalty_payment(p) for p in page], total, limit, offset)
