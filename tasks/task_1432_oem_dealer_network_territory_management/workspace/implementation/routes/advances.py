"""FloorPlanAdvance endpoints: create (credit pool), payment (curtailment /
payoff), aging audit (interest accrual + PAST_DUE / DEFAULTED)."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_DEALER_NOT_FOUND,
    ERR_ADVANCE_NOT_FOUND,
    ERR_DEALER_NOT_ACTIVE,
    ERR_DUPLICATE_ADVANCE_SERIAL,
    ERR_CREDIT_LIMIT_EXCEEDED,
    ERR_ADVANCE_NOT_OPEN,
    ERR_PAYMENT_EXCEEDS_BALANCE,
)
from middleware import require_roles
from response import success_object, success_list
from services.calculations import (
    accrued_interest_cents,
    advance_age_days,
    DEFAULT_DAYS,
    PAST_DUE_DAYS,
)
from services.serializers import serialize, serialize_list
from util import (
    apply_filters,
    get_json_body,
    paginate,
    parse_pagination,
    require_int,
    require_string,
    sort_by_created_at,
)

bp = Blueprint("advances", __name__)

LIVE_ADVANCE_STATUSES = ("OPEN", "CURTAILED", "PAST_DUE")


def get_advance_or_404(advance_id: str) -> dict:
    advance = db.advances.get(advance_id)
    if advance is None:
        raise_err(ERR_ADVANCE_NOT_FOUND, "Floor-plan advance id does not exist")
    return advance


@bp.route("/floorplan-advances", methods=["POST"])
@require_roles("OemNetworkAdmin")
def create_advance(_user_id: str, _role: str):
    body = get_json_body()
    dealer_id = require_string(body, "dealer_id")
    unit_serial = require_string(body, "unit_serial")
    advance_cents = require_int(body, "advance_cents")
    if advance_cents <= 0:
        raise_err(ERR_INVALID_REQUEST, "advance_cents must be > 0")

    # Priority 4 existence.
    dealer = db.dealers.get(dealer_id)
    if dealer is None:
        raise_err(ERR_DEALER_NOT_FOUND, "Dealer id does not exist")

    # Priority 6 state: floor-plan writes require an ACTIVE dealer.
    if dealer["status"] != "ACTIVE":
        raise_err(ERR_DEALER_NOT_ACTIVE, "Advance creation requires Dealer.status == ACTIVE")

    # Priority 8: one live advance per (dealer, unit_serial).
    for a in db.advances.values():
        if (
            a["dealer_id"] == dealer_id
            and a["unit_serial"] == unit_serial
            and a["status"] not in ("PAID_OFF", "DEFAULTED")
        ):
            raise_err(ERR_DUPLICATE_ADVANCE_SERIAL, "Non-terminal advance with same (dealer_id, unit_serial) exists")

    # Priority 11 fiscal: must fit within available credit.
    available = dealer["credit_limit_cents"] - dealer["floorplan_utilization_cents"]
    if advance_cents > available:
        raise_err(ERR_CREDIT_LIMIT_EXCEEDED, "advance_cents > floorplan_available_cents")

    advance = {
        "dealer_id": dealer_id,
        "unit_serial": unit_serial,
        "advance_cents": advance_cents,
        "advance_date": db.clock_date().isoformat(),
        "paid_curtailments_cents": 0,
        "accrued_interest_cents": 0,
        "status": "OPEN",
        "_paid_off_by_sale_id": None,
    }
    db.stamp_new(advance)
    db.advances[advance["id"]] = advance
    dealer["floorplan_utilization_cents"] += advance_cents
    db.touch(dealer)
    return success_object(serialize(advance), 201)


@bp.route("/floorplan-advances", methods=["GET"])
@require_roles("Any")
def list_advances(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = sort_by_created_at(list(db.advances.values()))
    items = apply_filters(items, ["dealer_id", "status"])
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page), limit, offset, total)


@bp.route("/floorplan-advances/<advance_id>", methods=["GET"])
@require_roles("Any")
def get_advance(advance_id: str, _user_id: str, _role: str):
    advance = get_advance_or_404(advance_id)
    return success_object(serialize(advance))


@bp.route("/floorplan-advances/<advance_id>/payment", methods=["POST"])
@require_roles("OemNetworkAdmin")
def record_payment(advance_id: str, _user_id: str, _role: str):
    body = get_json_body()
    amount_cents = require_int(body, "amount_cents")
    if amount_cents <= 0:
        raise_err(ERR_INVALID_REQUEST, "amount_cents must be > 0")
    advance = get_advance_or_404(advance_id)

    # Priority 6 state.
    if advance["status"] not in LIVE_ADVANCE_STATUSES:
        raise_err(ERR_ADVANCE_NOT_OPEN, "Payment requires advance in OPEN, CURTAILED, or PAST_DUE")

    # Priority 11 fiscal: amount must not exceed remaining principal.
    remaining = advance["advance_cents"] - advance["paid_curtailments_cents"]
    if amount_cents > remaining:
        raise_err(ERR_PAYMENT_EXCEEDS_BALANCE, "amount_cents > remaining principal")

    advance["paid_curtailments_cents"] += amount_cents
    if amount_cents == remaining:
        advance["status"] = "PAID_OFF"
        advance["paid_curtailments_cents"] = advance["advance_cents"]
    else:
        advance["status"] = "CURTAILED"
    db.touch(advance)

    dealer = db.dealers.get(advance["dealer_id"])
    if dealer is not None:
        dealer["floorplan_utilization_cents"] -= amount_cents
        db.touch(dealer)
    return success_object(serialize(advance))


@bp.route("/floorplan-advances/<advance_id>/aging-audit", methods=["POST"])
@require_roles("OemAuditor")
def aging_audit(advance_id: str, _user_id: str, _role: str):
    advance = get_advance_or_404(advance_id)

    # Priority 6 state.
    if advance["status"] not in LIVE_ADVANCE_STATUSES:
        raise_err(ERR_ADVANCE_NOT_OPEN, "Aging audit requires advance in OPEN, CURTAILED, or PAST_DUE")

    today = db.clock_date()
    # Interest recomputation applies on every invocation.
    advance["accrued_interest_cents"] = accrued_interest_cents(advance, today)
    age = advance_age_days(advance, today)

    dealer = db.dealers.get(advance["dealer_id"])
    if age > DEFAULT_DAYS:
        # Write off the remaining principal.
        remaining = advance["advance_cents"] - advance["paid_curtailments_cents"]
        advance["status"] = "DEFAULTED"
        if dealer is not None:
            dealer["floorplan_utilization_cents"] -= remaining
            dealer["default_loss_cents"] += remaining
            db.touch(dealer)
    elif age > PAST_DUE_DAYS:
        advance["status"] = "PAST_DUE"
    db.touch(advance)
    return success_object(serialize(advance))
