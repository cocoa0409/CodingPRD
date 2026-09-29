"""Requests that break two rules at once, and which error must come back.

The rejection order is normative, so each of these pairs is checked twice: once in
the configuration where both rules are broken and the higher-ranked one must win,
and once in the configuration where only the lower-ranked one is broken.
"""
from test_helpers import (
    ANALYST_ONE_USER_ID,
    ANALYST_TWO_USER_ID,
    ApiErrorId,
    add_hour_window,
    create_adjustment_payload,
    create_channel,
    create_finalized_menu_version,
    create_order_payload,
    create_store,
    make_analyst_headers,
    make_channel_partner_headers,
    order_line,
    place_ready_order,
    publish_menu,
    read_order,
    read_statement,
    read_store,
    set_clock,
    setup_published_store,
    setup_settled_statement,
    validate_error,
    validate_paginated,
    validate_success,
)

SUNDAY_EVENING_CLOCK = "2026-08-03T04:00:00Z"
"""04:00 UTC is 23:00 the previous local day for a store at offset -300."""

BURGER_LINE = [order_line("BURGER", 1)]


def _unpublished_closed_store():
    """A store with Monday hours only, holding a frozen menu it has not adopted."""
    set_clock(SUNDAY_EVENING_CLOCK)
    channel = create_channel()
    menu_version, _items = create_finalized_menu_version()
    store = create_store()
    add_hour_window(store["id"], day_of_week=0, opens_at_minute=600, closes_at_minute=1320)
    return store, channel, menu_version


def test_unpublished_store_reports_the_menu_error_not_the_closed_error(api):
    """Both rules are broken at once and the menu rule outranks the hours rule.

    PRD: "The ranking is normative and is the reason, for example, that a request
    against a store with no published menu reports the menu error rather than the
    closed-store error even when both are true." The ladder places
    "`ERR_STORE_MENU_NOT_PUBLISHED` (409) — the store has no active menu version"
    above "`ERR_STORE_CLOSED` (422) — the logical clock falls outside every
    operating-hours window for the store's local day."

    Design: Difficulty/priority_pair_validation_conflict/conflict_menu_not_published_outranks_store_closed
    """
    store, channel, _menu_version = _unpublished_closed_store()
    assert store["active_menu_version_id"] is None
    payload = create_order_payload(
        store["id"], channel["id"], external_ref="MP-1001",
        fulfillment_mode="PICKUP", lines=BURGER_LINE, tip_cents=0,
    )

    response = api.create_order(payload, make_channel_partner_headers(channel["id"]))

    validate_error(response, ApiErrorId.ERR_STORE_MENU_NOT_PUBLISHED, 409)
    assert read_store(store["id"])["open_order_count"] == 0


def test_publishing_leaves_only_the_closed_store_objection_standing(api):
    """With a menu adopted the same request now reports the hours violation.

    PRD: "The first successful publish also lifts the store's posture from `PAUSED`
    to `NORMAL` — this is the only way a store leaves its initial paused posture."
    "`ERR_STORE_CLOSED` (422) — the logical clock falls outside every
    operating-hours window for the store's local day. Applies to `POST /orders` and
    `GET /stores/{id}/quote`."

    Design: Difficulty/priority_pair_validation_conflict/conflict_menu_not_published_outranks_store_closed
    """
    store, channel, menu_version = _unpublished_closed_store()

    published = publish_menu(store["id"], menu_version["id"], store["version"])
    assert published["active_menu_version_id"] == menu_version["id"]
    assert published["throttle_state"] == "NORMAL"

    payload = create_order_payload(
        store["id"], channel["id"], external_ref="MP-1002",
        fulfillment_mode="PICKUP", lines=BURGER_LINE, tip_cents=0,
    )
    response = api.create_order(payload, make_channel_partner_headers(channel["id"]))

    validate_error(response, ApiErrorId.ERR_STORE_CLOSED, 422)
    assert read_store(store["id"])["open_order_count"] == 0, "a refused order reserves nothing"


def test_settled_order_reports_closed_money_not_the_refund_ceiling(api):
    """An absurd refund against a settled order still reports the settled error.

    PRD: "The order's `settlement_status` must not be `SETTLED` — money on a
    settled order is closed, and an attempt is refused with
    `ERR_ORDER_ALREADY_SETTLED`. Only then is the refund ceiling evaluated".
    "Because the already-settled check ranks above the ceiling check, an over-large
    refund against a settled order reports the settled error."

    Design: Difficulty/priority_pair_validation_conflict/conflict_order_settled_outranks_refund_ceiling
    """
    env = setup_published_store()
    order = place_ready_order(
        env, external_ref="MP-1001", fulfillment_mode="PICKUP", lines=BURGER_LINE, tip_cents=0
    )
    statement = setup_settled_statement(
        env, [order], reconciler_user_id=ANALYST_ONE_USER_ID, settler_user_id=ANALYST_TWO_USER_ID
    )
    assert read_statement(statement["id"])["state"] == "SETTLED"
    settled = read_order(order["id"])
    assert settled["settlement_status"] == "SETTLED"

    payload = create_adjustment_payload(order["id"], settled["version"], amount_cents=999999)
    response = api.create_adjustment(payload, make_analyst_headers())

    validate_error(response, ApiErrorId.ERR_ORDER_ALREADY_SETTLED, 409)
    _rows, meta = validate_paginated(
        api.list_adjustments(make_analyst_headers(), params={"order_id": order["id"]})
    )
    assert meta["total_count"] == 0, "a refused proposal leaves no adjustment behind"
    assert read_order(order["id"])["refunded_total_cents"] == 0


def test_settleable_order_reports_the_refund_ceiling(api):
    """With settlement still open, the same amount trips the ceiling instead.

    PRD: "the sum of the order's current `refunded_total_cents` and the proposed
    `amount_cents` must be less than or equal to the order's
    `channel_collected_cents`, or the proposal is refused with
    `ERR_REFUND_EXCEEDS_COLLECTED`. A refund may never exceed what the channel
    actually collected, counting refunds already accepted, and a refund for exactly
    the remaining balance is allowed."

    Design: Difficulty/priority_pair_validation_conflict/conflict_order_settled_outranks_refund_ceiling
    """
    env = setup_published_store()
    order = place_ready_order(
        env, external_ref="MP-1003", fulfillment_mode="PICKUP", lines=BURGER_LINE, tip_cents=0
    )
    unassigned = read_order(order["id"])
    assert unassigned["settlement_status"] == "SETTLEABLE"
    assert unassigned["channel_collected_cents"] < 999999

    payload = create_adjustment_payload(order["id"], unassigned["version"], amount_cents=999999)
    response = api.create_adjustment(payload, make_analyst_headers())

    validate_error(response, ApiErrorId.ERR_REFUND_EXCEEDS_COLLECTED, 422)
    _rows, meta = validate_paginated(
        api.list_adjustments(make_analyst_headers(), params={"order_id": order["id"]})
    )
    assert meta["total_count"] == 0
    assert read_order(order["id"])["refunded_total_cents"] == 0

    within_ceiling = create_adjustment_payload(
        order["id"], unassigned["version"], amount_cents=unassigned["channel_collected_cents"]
    )
    accepted = validate_success(
        api.create_adjustment(within_ceiling, make_analyst_headers()), expected_status=201
    )
    assert accepted["amount_cents"] == unassigned["channel_collected_cents"], (
        "a refund for exactly the remaining balance is allowed"
    )
