"""Utility service orders (two parallel state dimensions), credit-check
handoffs and deposit payments."""

from flask import Blueprint

import db
import response
import validators as v
from errors import ApiError
from middleware import (
    COMPLIANCE_OFFICER,
    EXTERNAL_SERVICE_GATEWAY,
    MOVE_OPS_AGENT,
    PROVIDER_AGENT,
    RESIDENT,
    authenticate,
)
from services import cascades, derive, deposits, enums, gates, scheduling
from services.lookup import (
    handoff_or_404,
    handoffs_of_order,
    move_or_404,
    order_or_404,
)

bp = Blueprint("orders", __name__)


def _provider(order):
    return db.db.utility_providers[order["provider_id"]]


@bp.get("/utility-orders/<order_id>")
def read_order(order_id):
    caller = authenticate(MOVE_OPS_AGENT, COMPLIANCE_OFFICER, PROVIDER_AGENT)
    order = order_or_404(order_id)
    caller.own_if(PROVIDER_AGENT, order["provider_id"])
    return response.ok(db.public(order))


@bp.get("/utility-orders")
def list_orders():
    authenticate(MOVE_OPS_AGENT, COMPLIANCE_OFFICER, PROVIDER_AGENT)
    rows = response.match_filters(
        db.db.orders.values(),
        {
            "move_id": "move_id",
            "provider_id": "provider_id",
            "service_address_id": "service_address_id",
            "territory_id": "territory_id",
            "provision_status": "provision_status",
            "credit_status": "credit_status",
            "order_kind": "order_kind",
            "utility_type": "utility_type",
        },
    )
    return response.paginated(rows)


# ------------------------------------------------------------------- schedule
@bp.post("/utility-orders/<order_id>/schedule")
def schedule_order(order_id):
    authenticate(MOVE_OPS_AGENT)
    order = order_or_404(order_id)
    body = v.body()
    date_text, requested_date = v.date_field(body, "requested_service_date")
    start_text, window_start = v.ts_field(body, "scheduled_window_start")
    end_text, window_end = v.ts_field(body, "scheduled_window_end")
    account_data = v.obj_field(body, "account_data")

    move = move_or_404(order["move_id"])
    gates.require_move_state(move, ("SCHEDULING",))
    gates.require_order_state(order, ("DRAFT",))
    gates.require_identity_verified(move)
    gates.require_identity_current(move)
    gates.require_consent(move, "UTILITY_SETUP")
    gates.require_gate_open(move)

    provider = _provider(order)
    scheduling.check_account_data(provider, account_data)
    gates.require_provider_active(provider)
    scheduling.check_service_window(requested_date, window_start, window_end)
    scheduling.check_lead_time(provider, order, requested_date)
    scheduling.check_window_conflict(order, window_start, window_end)

    order["requested_service_date"] = date_text
    order["scheduled_window_start"] = start_text
    order["scheduled_window_end"] = end_text
    order["account_data"] = account_data
    order["provision_status"] = "SCHEDULED"
    db.touch(order)

    derive.refresh(move)
    return response.ok(db.public(order))


# -------------------------------------------------------- credit-check handoff
@bp.post("/utility-orders/<order_id>/credit-checks")
def open_credit_check(order_id):
    caller = authenticate(MOVE_OPS_AGENT)
    order = order_or_404(order_id)
    body = v.body()
    bureau = v.enum_field(body, "bureau", enums.BUREAUS)

    move = move_or_404(order["move_id"])
    gates.require_move_state(move, ("SCHEDULING", "ATTENTION_REQUIRED"))
    gates.require_order_state(order, ("DRAFT",))
    gates.require_credit_state(
        order,
        ("PENDING_CHECK",),
        "A credit check may only be dispatched while credit_status is PENDING_CHECK.",
    )
    gates.require_gate_open(move)

    # rung 40: at most one live handoff per order.
    for existing in handoffs_of_order(order["id"]):
        if existing["handoff_status"] == "SUBMITTED":
            raise ApiError(
                "ERR_HANDOFF_ALREADY_OPEN",
                "This order already has a SUBMITTED credit-check handoff.",
            )

    rec = db.base_record()
    rec.update(
        {
            "utility_order_id": order["id"],
            "bureau": bureau,
            "handoff_status": "SUBMITTED",
            "score": None,
            "result": None,
            "submitted_by_user_id": caller.user_id,
            "responded_at": None,
        }
    )
    db.db.handoffs[rec["id"]] = rec

    # Evaluation-order pin: the deposit formula may only read this snapshot.
    order["readiness_snapshot"] = move["readiness_score"]
    db.touch(order)
    return response.created(db.public(rec))


@bp.get("/credit-check-handoffs/<handoff_id>")
def read_handoff(handoff_id):
    authenticate(MOVE_OPS_AGENT, COMPLIANCE_OFFICER)
    return response.ok(db.public(handoff_or_404(handoff_id)))


@bp.get("/credit-check-handoffs")
def list_handoffs():
    authenticate(MOVE_OPS_AGENT, COMPLIANCE_OFFICER)
    rows = response.match_filters(
        db.db.handoffs.values(),
        {
            "utility_order_id": "utility_order_id",
            "handoff_status": "handoff_status",
            "result": "result",
        },
    )
    return response.paginated(rows)


@bp.post("/credit-check-handoffs/<handoff_id>/bureau-response")
def bureau_response(handoff_id):
    authenticate(EXTERNAL_SERVICE_GATEWAY)
    handoff = handoff_or_404(handoff_id)
    body = v.body()
    score = v.int_field(
        body, "score", minimum=enums.CREDIT_SCORE_MIN, maximum=enums.CREDIT_SCORE_MAX
    )

    # rung 13: only a SUBMITTED handoff accepts a bureau response.
    if handoff["handoff_status"] != "SUBMITTED":
        raise ApiError(
            "ERR_HANDOFF_NOT_OPEN",
            "This credit-check handoff is no longer open.",
        )

    order = order_or_404(handoff["utility_order_id"])
    move = move_or_404(order["move_id"])
    result = deposits.band_for_score(score)

    handoff["score"] = score
    handoff["result"] = result
    handoff["handoff_status"] = "RESPONDED"
    handoff["responded_at"] = db.now_iso()
    db.touch(handoff)

    snap = derive.snapshot(move)
    if result == "CLEAR":
        order["credit_status"] = "CLEARED"
        db.touch(order)
    elif result == "DEPOSIT_REQUIRED":
        order["credit_status"] = "DEPOSIT_DUE"
        order["deposit_amount_cents"] = deposits.deposit_amount(
            _provider(order), score, order["readiness_snapshot"]
        )
        db.touch(order)
    else:
        order["credit_status"] = "DECLINED"
        # hop 2: the provision dimension follows the credit decline.
        if order["provision_status"] in ("DRAFT", "SCHEDULED"):
            cascades.fail_order(order, "CREDIT_DECLINED", void_credit=False)
        else:
            db.touch(order)
        # hop 3: the parent move parks for human attention.
        derive.park_attention(move, "CREDIT_DECLINED")

    derive.recompute(move)
    derive.commit(move, snap)
    return response.ok(db.public(handoff))


# ------------------------------------------------------------ deposit payment
@bp.post("/utility-orders/<order_id>/deposit-payments")
def pay_deposit(order_id):
    caller = authenticate(MOVE_OPS_AGENT, RESIDENT)
    order = order_or_404(order_id)
    move = move_or_404(order["move_id"])
    caller.own_if(RESIDENT, move["resident_id"])
    body = v.body()
    amount = v.int_field(body, "amount_cents", minimum=0)

    gates.require_move_live(move)
    gates.require_order_state(
        order,
        ("DRAFT", "SCHEDULED"),
        "A deposit may only be paid while the order is DRAFT or SCHEDULED.",
    )
    gates.require_credit_state(
        order,
        ("DEPOSIT_DUE",),
        "No deposit is currently due on this order.",
    )

    # rung 47: exact settlement only, no partial and no over-payment.
    if amount != order["deposit_amount_cents"]:
        raise ApiError(
            "ERR_DEPOSIT_AMOUNT_MISMATCH",
            "amount_cents must equal deposit_amount_cents exactly.",
        )

    order["deposit_paid_cents"] = amount
    order["credit_status"] = "DEPOSIT_PAID"
    db.touch(order)
    derive.refresh(move)
    return response.ok(db.public(order))


# ----------------------------------------------------------------- activation
@bp.post("/utility-orders/<order_id>/activation")
def activate_order(order_id):
    caller = authenticate(PROVIDER_AGENT)
    order = order_or_404(order_id)
    caller.own_if(PROVIDER_AGENT, order["provider_id"])
    body = v.body()
    confirmation_code = v.str_field(body, "confirmation_code", min_len=1, max_len=64)

    move = move_or_404(order["move_id"])
    gates.require_move_live(move)
    gates.require_order_state(order, ("SCHEDULED",))
    gates.require_credit_state(
        order,
        enums.ACTIVATION_CREDIT_OK,
        "The credit dimension does not yet permit activation.",
        # The one gate outside the numbered ladder: it carries its own error id.
        error_id="ERR_CREDIT_NOT_CLEARED",
    )
    gates.require_gate_open(move)
    gates.require_provider_active(_provider(order))

    # rung 37: the window must have opened.
    window_start = db.parse_ts(order["scheduled_window_start"])
    if window_start is not None and db.now() < window_start:
        raise ApiError(
            "ERR_ACTIVATION_TOO_EARLY",
            "The scheduled service window has not opened yet.",
        )

    order["confirmation_code"] = confirmation_code
    order["provision_status"] = "ACTIVE_SERVICE"
    db.touch(order)

    snap = derive.snapshot(move)
    derive.recompute(move)
    derive.try_bubble_up(move)
    derive.recompute(move)
    derive.commit(move, snap)
    return response.ok(db.public(order))


# ------------------------------------------------------------ provision failure
@bp.post("/utility-orders/<order_id>/provision-failure")
def fail_provision(order_id):
    caller = authenticate(PROVIDER_AGENT)
    order = order_or_404(order_id)
    caller.own_if(PROVIDER_AGENT, order["provider_id"])
    body = v.body()
    failure_reason = v.str_field(body, "failure_reason", min_len=1, max_len=500)

    move = move_or_404(order["move_id"])
    gates.require_move_live(move)
    gates.require_order_state(order, ("DRAFT", "SCHEDULED"))

    # hop 1 and hop 2: the order fails and its open credit line is voided.
    cascades.fail_order(order, failure_reason)

    # hop 3: the parent move parks for human attention.
    snap = derive.snapshot(move)
    derive.park_attention(move, "PROVISION_FAILED")
    derive.recompute(move)
    derive.commit(move, snap)
    return response.ok(db.public(order))


# -------------------------------------------------------------------- closure
@bp.post("/utility-orders/<order_id>/closure")
def close_order(order_id):
    caller = authenticate(PROVIDER_AGENT, MOVE_OPS_AGENT)
    order = order_or_404(order_id)
    caller.own_if(PROVIDER_AGENT, order["provider_id"])
    body = v.body()
    v.str_field(
        body, "final_read_note", required=False, min_len=1, max_len=500, default=None
    )

    move = move_or_404(order["move_id"])
    gates.require_not_locked(move)
    gates.require_order_state(order, ("ACTIVE_SERVICE",))

    window_end = db.parse_ts(order["scheduled_window_end"])
    if window_end is not None and db.now() < window_end:
        raise ApiError(
            "ERR_ORDER_NOT_SCHEDULABLE",
            "The service window has not ended yet.",
        )

    order["provision_status"] = "CLOSED"
    db.touch(order)
    derive.refresh(move)
    return response.ok(db.public(order))


# --------------------------------------------------------------------- waiver
@bp.post("/utility-orders/<order_id>/waiver")
def waive(order_id):
    authenticate(MOVE_OPS_AGENT)
    order = order_or_404(order_id)
    body = v.body()
    waiver_reason = v.str_field(body, "waiver_reason", min_len=1, max_len=500)

    move = move_or_404(order["move_id"])
    gates.require_move_state(move, ("SCHEDULING", "ATTENTION_REQUIRED"))
    gates.require_order_state(order, ("DRAFT",))

    cascades.waive_order(order, waiver_reason)
    derive.refresh(move)
    return response.ok(db.public(order))
