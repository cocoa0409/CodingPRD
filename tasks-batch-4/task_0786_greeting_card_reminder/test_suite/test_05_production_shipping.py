"""Scheduler-driven recurring sends, cancellation cascades onto the artist
reservation, shipment-to-order delivery cascade, and the production timing and
retired-card guards.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    build_pipeline, set_clock, holder, TEST_USERS,
    new_account, new_subscription, new_contact, new_card, retire_card,
    account_balance, create_order_payload,
)

STUDIO = TEST_USERS["studio_operator_headers"]


def _recurring_setup(api):
    account = new_account()
    new_subscription(account["id"], "PRO")  # 12 credits
    contact = new_contact(account["id"], verified=True)
    card = new_card()
    set_clock("2026-03-25T00:00:00Z")
    ah = holder(account["id"])
    imp = validate_success(api.create_important_date(contact["id"], {
        "occasion_type": "BIRTHDAY",
        "event_date": "2026-04-01T00:00:00Z",
        "lead_days": 7,               # next_trigger_at = 2026-03-25 (due now)
        "recurrence": "ANNUAL",
        "auto_send": True,
        "default_card_id": card["id"],
    }, ah), 201)
    return account, imp


def test_scheduler_fires_recurring_creates_order_and_holds_credit(api):
    """PRD §3.9: "the scheduler auto-creates an order for the reminder's
    `default_card_id` with the send instant taken from the occasion's event date,
    and immediately auto-submits it so that one credit is held."

    Design: Difficulty/transitive_cascade/scheduler_fires_recurring_creates_order_holds_credit
    """
    account, _ = _recurring_setup(api)
    result = validate_success(api.run_scheduler(TEST_USERS["platform_admin_headers"]), 200)
    assert len(result["created_order_ids"]) == 1, "one due reminder auto-creates one order"
    assert account_balance(account["id"]) == 11, "the auto-submit holds one credit: 12 -> 11"


def test_scheduler_advances_next_trigger_by_one_year(api):
    """PRD §3.9: "The reminder's `next_trigger_at` is then advanced by one year —
    that is, to the year-advanced event date minus the same lead-days offset".
    PRD §3.2: "A reminder's `next_trigger_at` is computed as the event date minus
    that lead-days offset, expressed in ISO 8601 UTC with three fractional
    digits."

    Design: Difficulty/transitive_cascade/scheduler_fires_recurring_creates_order_holds_credit
    """
    _, imp = _recurring_setup(api)
    validate_success(api.run_scheduler(TEST_USERS["platform_admin_headers"]), 200)
    refreshed = validate_success(
        api.get_important_date(imp["id"], TEST_USERS["platform_admin_headers"]), 200)
    # (2027-04-01) - 7 days = 2027-03-25.
    assert refreshed["next_trigger_at"] == "2027-03-25T00:00:00.000Z"


def test_cancel_scheduled_order_releases_artist_assignment(api):
    """PRD §3.8: "If the order still holds a `RESERVED` artist assignment, that
    assignment is released — moved from `RESERVED` to `RELEASED` — and the
    artist's `reserved_assignment_count` is recomputed."

    Design: Difficulty/transitive_cascade/cancel_scheduled_order_releases_assignment_updates_artist_count
    """
    ctx = build_pipeline("assigned", tier="PRO")  # SCHEDULED order, artist reserved (count 1)
    artist_before = validate_success(api.get_artist(ctx["artist_id"], STUDIO), 200)
    assert artist_before["reserved_assignment_count"] == 1
    validate_success(api.cancel_order(ctx["order_id"], holder(ctx["account_id"])), 200)
    assignment = validate_success(api.get_artist_assignment(ctx["assignment_id"], STUDIO), 200)
    assert assignment["status"] == "RELEASED"
    artist_after = validate_success(api.get_artist(ctx["artist_id"], STUDIO), 200)
    assert artist_after["reserved_assignment_count"] == 0, "release recomputes the artist count 1 -> 0"


def test_cancel_scheduled_order_refunds_credit(api):
    """PRD §3.8: "Cancelling from `PENDING_PROOF`, `PROOF_APPROVED`, or
    `SCHEDULED` — states in which `credit_status` is `HELD` — refunds the held
    credit by moving `credit_status` from `HELD` to `REFUNDED`".

    Design: Difficulty/transitive_cascade/cancel_scheduled_order_releases_assignment_updates_artist_count
    """
    ctx = build_pipeline("assigned", tier="PRO")
    ah = holder(ctx["account_id"])
    validate_success(api.cancel_order(ctx["order_id"], ah), 200)
    order = validate_success(api.get_order(ctx["order_id"], ah), 200)
    assert order["status"] == "CANCELLED"
    assert order["credit_status"] == "REFUNDED"


def test_shipment_delivered_cascades_order_to_delivered(api):
    """PRD §3.7: "When a shipment reaches `DELIVERED`, the change cascades to the
    order, advancing it from `MAILED` to the terminal `DELIVERED` and stamping
    the order's `delivered_at` and the shipment's `delivered_at` with the current
    logical clock."

    Design: Corner/state_machines/shipment_delivered_cascades_order_to_delivered
    """
    ctx = build_pipeline("mailed", tier="PRO")  # clock is at 2026-04-01 after produce
    ship_id, order_id = ctx["shipment_id"], ctx["order_id"]
    validate_success(api.advance_shipment(ship_id, {"to_status": "IN_TRANSIT"}, STUDIO), 200)
    shipment = validate_success(api.advance_shipment(ship_id, {"to_status": "DELIVERED"}, STUDIO), 200)
    assert shipment["status"] == "DELIVERED"
    order = validate_success(api.get_order(order_id, holder(ctx["account_id"])), 200)
    assert order["status"] == "DELIVERED"
    assert order["delivered_at"] == "2026-04-01T00:00:00.000Z"


def test_produce_before_send_date_returns_too_early(api):
    """PRD §3.6: "producing before that instant is rejected with
    `ERR_TOO_EARLY_TO_PRODUCE`."

    Design: Corner/validations/produce_before_send_date_returns_too_early
    """
    # "assigned" stage leaves the clock at the 2026-03-01 default, before the
    # 2026-04-01 scheduled_send_at.
    ctx = build_pipeline("assigned", tier="PRO")
    validate_error(api.produce_order(ctx["order_id"], STUDIO), ApiErrorId.ERR_TOO_EARLY_TO_PRODUCE.value)


def test_order_with_retired_card_returns_card_retired(api):
    """PRD §3.4: "At create time the card must be `ACTIVE`, or the request is
    rejected with `ERR_CARD_RETIRED`".

    Design: Corner/validations/order_with_retired_card_returns_card_retired
    """
    account = new_account()
    contact = new_contact(account["id"])
    card = new_card()
    retire_card(card["id"])
    payload = create_order_payload(account["id"], contact["id"], card["id"])
    validate_error(api.create_order(payload, holder(account["id"])), ApiErrorId.ERR_CARD_RETIRED.value)
