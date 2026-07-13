"""Event order lifecycle: invalid transitions, terminal lockdown, order-line gating.

Translates queue-A instance (cross_entity_state_dependency/orderline_delete_requires_order_draft)
and queue-B corner instances (state_machines section).
"""
from test_helpers import validate_success, validate_error, ApiErrorId
from test_helpers import fixtures as fx
from test_helpers.factories import create_event_order_payload


# --------------------------------------------------------------------------
# Difficulty: cross_entity_state_dependency / orderline_delete_requires_order_draft
# --------------------------------------------------------------------------
def test_delete_order_line_on_quoted_order_rejected(api, sales_manager_headers):
    """PRD §3.2: "Both adding a line and removing a line are permitted only while the
    parent order's `status` is `DRAFT`; attempting either against a non-`DRAFT` order is
    rejected with `ERR_ORDER_NOT_DRAFT`."

    Design: Difficulty/cross_entity_state_dependency/orderline_delete_requires_order_draft
    """
    base = fx.quoted_order_with_line(api, guest_count=20)  # order is QUOTED
    validate_error(api.delete_order_line(base["line_id"], sales_manager_headers),
                   ApiErrorId.ERR_ORDER_NOT_DRAFT)


def test_delete_order_line_on_draft_order_allowed(api, sales_manager_headers):
    """PRD §3.2: "An order line is born `ACTIVE`; removing it is a soft delete that
    transitions it `ACTIVE → REMOVED`, and removed lines are excluded from every
    calculation and from default list results."

    Design: Difficulty/cross_entity_state_dependency/orderline_delete_requires_order_draft
    """
    base = fx.draft_order_with_line(api, guest_count=20)  # order stays DRAFT
    data = validate_success(api.delete_order_line(base["line_id"], sales_manager_headers))
    assert data["status"] == "REMOVED", f"delete on DRAFT must soft-remove the line, got {data['status']}"


# --------------------------------------------------------------------------
# Corner: state_machines
# --------------------------------------------------------------------------
def test_orderline_delete_on_draft_order_succeeds_and_bumps_version(api, sales_manager_headers):
    """PRD §3.2: "removing it is a soft delete that transitions it `ACTIVE → REMOVED`"
    PRD §3.2: "Each successful add or remove increments the parent `EventOrder.version` by
    one — the very mutations that the quote-generation concurrency guard keys on."

    Design: Corner/state_machines/orderline_delete_on_draft_order_succeeds
    """
    base = fx.draft_order_with_line(api, guest_count=20)
    before = fx.order_version(api, base["order_id"])
    data = validate_success(api.delete_order_line(base["line_id"], sales_manager_headers))
    assert data["status"] == "REMOVED"
    after = fx.order_version(api, base["order_id"])
    assert after == before + 1, f"parent version must increment by 1, {before} -> {after}"


def test_confirm_from_draft_returns_invalid_state(api, sales_manager_headers):
    """PRD §3.3: "From `QUOTED`, the sales manager can instead confirm the order, moving it
    `QUOTED → CONFIRMED`; confirmation requires the order to actually be in `QUOTED` state"

    Design: Corner/state_machines/confirm_from_draft_returns_invalid_state
    """
    order = validate_success(api.create_event_order(create_event_order_payload(guest_count=20), sales_manager_headers), 201)
    validate_error(api.confirm_order(order["id"], sales_manager_headers), ApiErrorId.ERR_INVALID_STATE)


def test_cancel_from_cancelled_terminal_returns_invalid_state(api, sales_manager_headers):
    """PRD §3.9: "At any point before the order becomes terminal, the `SalesManager` may
    cancel it, moving its `status` to `CANCELLED`. Cancellation is available from `DRAFT`,
    `QUOTED`, `CONFIRMED`, and `IN_PRODUCTION`"

    Design: Corner/state_machines/cancel_from_cancelled_terminal_returns_invalid_state
    """
    order = validate_success(api.create_event_order(create_event_order_payload(guest_count=20), sales_manager_headers), 201)
    validate_success(api.cancel_order(order["id"], sales_manager_headers))
    validate_error(api.cancel_order(order["id"], sales_manager_headers), ApiErrorId.ERR_INVALID_STATE)


def test_double_confirm_is_rejected(api, sales_manager_headers):
    """PRD §3.3: "From `QUOTED`, the sales manager can instead confirm the order, moving it
    `QUOTED → CONFIRMED`; confirmation requires the order to actually be in `QUOTED` state"

    Design: Corner/state_machines/double_confirm_is_rejected_idempotency
    """
    base = fx.confirmed_order_with_line(api, guest_count=20)  # already CONFIRMED
    validate_error(api.confirm_order(base["order_id"], sales_manager_headers), ApiErrorId.ERR_INVALID_STATE)
