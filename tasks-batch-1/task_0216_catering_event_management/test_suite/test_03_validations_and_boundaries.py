"""Validation-gauntlet tests: structural-over-business precedence, numeric/aggregate boundary
precision, cross-entity state dependencies, and resource temporal-overlap (venue half-open vs
leg inclusive). Plus the corner validation single-failure scenarios.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    make_client_headers,
    create_order_payload,
)
from test_helpers import fixtures as fx
from test_helpers import api_client

ADMIN = TEST_USERS["admin_headers"]
COORD = TEST_USERS["coordinator_headers"]
CAPTAIN = TEST_USERS["captain_headers"]


# =====================================================================
# Queue A — Rule 5: priority-pair validation conflict
# (Instance package_retired_outranks_lead_time_on_confirm is SKIPPED: see worklog —
#  PRD §3.12 pins auth-through-state over business rules but does NOT pin the order
#  AMONG business rules, so package-retired vs lead-time precedence is not uniquely derivable.)
# =====================================================================
def test_settle_on_deposit_held_state_outranks_balance_check(api):
    """PRD §3.7: "settlement is permitted only when `settlement_status` is `INVOICED` and the
    running deposit-ledger balance for the order exactly equals `final_total_cents`."
    PRD §3.12: "Where a single operation could trip more than one business rule, the
    authentication-through-state ordering always takes precedence over any business rule."

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_outranks_balance_unpaid_on_settle
    """
    ctx = fx.setup_guaranteed_order(guaranteed_headcount=80, clock="2026-06-01T00:00:00Z")
    order = ctx["order"]  # settlement_status == DEPOSIT_HELD (never invoiced)
    validate_error(
        api.settle_order(order["id"], {"expected_order_version": order["version"]}, COORD),
        ApiErrorId.ERR_INVALID_STATE.value,
    )
    after = validate_success(api.get_order(order["id"], COORD))
    assert after["settlement_status"] == "DEPOSIT_HELD"


def test_fulfill_from_guaranteed_unsettled_state_outranks_other_checks(api):
    """PRD §3.8: "It is permitted only when the order is `GUARANTEED`, its `settlement_status` is
    `SETTLED` (the invoice must be paid before the event closes), and every delivery leg attached
    to the order is in `stop_status` `DELIVERED`; a fulfill from any other configuration is
    rejected with `ERR_INVALID_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_outranks_balance_unpaid_on_settle
    """
    # Guaranteed but settlement DEPOSIT_HELD (never invoiced/settled) → state precondition fails.
    ctx = fx.setup_guaranteed_order(guaranteed_headcount=80, clock="2026-06-01T00:00:00Z")
    order = ctx["order"]
    validate_error(
        api.fulfill_order(order["id"], {"expected_order_version": order["version"]}, CAPTAIN),
        ApiErrorId.ERR_INVALID_STATE.value,
    )
    after = validate_success(api.get_order(order["id"], COORD))
    assert after["lifecycle_status"] == "GUARANTEED"


# =====================================================================
# Queue A — Rule 6: boundary precision
# =====================================================================
def test_lead_time_boundary_exactly_at_cutoff_confirms(api):
    """PRD §3.5: "the hours from the current server time to `event_start` must be at least the
    package's `lead_time_hours`; a confirmation that falls inside the lead-time window is rejected
    with `ERR_LEAD_TIME_VIOLATED`".

    Design: Difficulty/boundary_precision_check/lead_time_boundary_exactly_at_cutoff_passes
    """
    fx.set_clock("2026-09-01T17:00:00Z")
    ctx = fx.create_draft_order(
        booked_headcount=80,
        package_overrides={"lead_time_hours": 24},
        event_start="2026-09-02T17:00:00Z", event_end="2026-09-02T22:00:00Z",
    )
    order = ctx["order"]
    confirmed = validate_success(
        api.confirm_order(order["id"], {"expected_order_version": order["version"]}, COORD)
    )
    assert confirmed["lifecycle_status"] == "CONFIRMED"


def test_dietary_counts_sum_equal_to_headcount_allowed(api):
    """PRD §3.2: "The sum of the dietary counts across all tags must not exceed the order's
    effective headcount in scope ... a request whose dietary counts exceed the in-scope headcount
    is rejected with `ERR_DIETARY_EXCEEDS_HEADCOUNT`".

    Design: Difficulty/boundary_precision_check/dietary_counts_sum_equals_headcount_is_allowed
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    cat = fx.setup_catalog()
    headers = make_client_headers(cat["client"]["id"])
    order = validate_success(
        api.create_order(
            create_order_payload(cat["client"]["id"], cat["package"]["id"], cat["venue"]["id"],
                                 booked_headcount=10,
                                 dietary_counts={"VEGAN": 6, "NUT_FREE": 4}),
            headers,
        ),
        expected_status=201,
    )
    assert order["lifecycle_status"] == "DRAFT"
    assert order["dietary_counts"]["VEGAN"] == 6


def test_lead_time_just_below_cutoff_rejected(api):
    """PRD §3.5: "the hours from the current server time to `event_start` must be at least the
    package's `lead_time_hours`; a confirmation that falls inside the lead-time window is rejected
    with `ERR_LEAD_TIME_VIOLATED`".

    Design: Difficulty/boundary_precision_check/lead_time_boundary_exactly_at_cutoff_passes
    """
    # lead_time 24h; event_start 23h after clock → below cutoff → rejected.
    fx.set_clock("2026-09-01T18:00:00Z")
    ctx = fx.create_draft_order(
        booked_headcount=80, package_overrides={"lead_time_hours": 24},
        event_start="2026-09-02T17:00:00Z", event_end="2026-09-02T22:00:00Z",
    )
    order = ctx["order"]
    validate_error(
        api.confirm_order(order["id"], {"expected_order_version": order["version"]}, COORD),
        ApiErrorId.ERR_LEAD_TIME_VIOLATED.value,
    )


def test_dietary_counts_one_above_headcount_rejected(api):
    """PRD §3.2: "The sum of the dietary counts across all tags must not exceed the order's
    effective headcount in scope ... a request whose dietary counts exceed the in-scope headcount
    is rejected with `ERR_DIETARY_EXCEEDS_HEADCOUNT`".

    Design: Difficulty/boundary_precision_check/dietary_counts_sum_equals_headcount_is_allowed
    """
    # booked 10, dietary sum 11 (one above) → rejected.
    cat = fx.setup_catalog()
    headers = make_client_headers(cat["client"]["id"])
    validate_error(
        api.create_order(
            create_order_payload(cat["client"]["id"], cat["package"]["id"], cat["venue"]["id"],
                                 booked_headcount=10,
                                 dietary_counts={"VEGAN": 6, "NUT_FREE": 5}),
            headers,
        ),
        ApiErrorId.ERR_DIETARY_EXCEEDS_HEADCOUNT.value,
    )


# =====================================================================
# Queue A — Rule 7: cross-entity state dependency
# =====================================================================
def test_dispatch_requires_parent_order_guaranteed(api):
    """PRD §3.11: "Dispatching a leg ... moves it from `PLANNED` to `DISPATCHED`, but only when
    several conditions hold: the leg is `PLANNED`; the parent order is `GUARANTEED` (only
    guaranteed orders ship)".
    PRD §3.11: "a dispatch from a non-`PLANNED` leg is rejected with `ERR_INVALID_STATE`."

    Design: Difficulty/cross_entity_state_dependency/leg_dispatch_requires_parent_order_guaranteed
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    route = fx.create_route(vehicle_capacity_legs=3)
    ctx = fx.create_draft_order(booked_headcount=80)
    order = fx.confirm_order(ctx["order"])  # CONFIRMED, not guaranteed
    leg = fx.create_leg(order["id"], route["id"],
                        "2026-09-01T15:00:00Z", "2026-09-01T16:00:00Z")
    validate_error(
        api.dispatch_delivery_leg(leg["id"], {"expected_route_version": fx.route_version(route["id"])},
                                  CAPTAIN),
        ApiErrorId.ERR_INVALID_STATE.value,
    )
    leg_after = validate_success(api.get_delivery_leg(leg["id"], CAPTAIN))
    assert leg_after["stop_status"] == "PLANNED"


def test_guarantee_blocked_by_open_change_request(api):
    """PRD §3.6: "there is no open negotiation — that is, no change request on this order is in
    `PROPOSED` or `COUNTERED` status; an attempt to guarantee while an open change request exists
    is rejected with `ERR_OPEN_CHANGE_REQUEST`".

    Design: Difficulty/cross_entity_state_dependency/guarantee_blocked_by_open_change_request_on_order
    """
    ctx = fx.setup_order_with_open_change(requested_headcount=90, clock="2026-06-01T00:00:00Z",
                                          booked_headcount=80)
    order = ctx["order"]
    validate_error(
        api.guarantee_order(order["id"],
                            {"expected_order_version": order["version"], "guaranteed_headcount": 80},
                            COORD),
        ApiErrorId.ERR_OPEN_CHANGE_REQUEST.value,
    )
    after = validate_success(api.get_order(order["id"], COORD))
    assert after["lifecycle_status"] == "CONFIRMED"


def test_dispatch_from_guaranteed_order_succeeds(api):
    """PRD §3.11: "Dispatching a leg ... moves it from `PLANNED` to `DISPATCHED`, but only when
    several conditions hold: the leg is `PLANNED`; the parent order is `GUARANTEED` (only
    guaranteed orders ship)".

    Design: Difficulty/cross_entity_state_dependency/leg_dispatch_requires_parent_order_guaranteed
    """
    # Positive case: parent order GUARANTEED → dispatch permitted.
    ctx = fx.setup_guaranteed_order_with_route_and_leg(guaranteed_headcount=80)
    leg, route = ctx["leg"], ctx["route"]
    dispatched = validate_success(
        api.dispatch_delivery_leg(leg["id"], {"expected_route_version": fx.route_version(route["id"])},
                                  CAPTAIN)
    )
    assert dispatched["stop_status"] == "DISPATCHED"


def test_guarantee_succeeds_after_change_request_rejected(api):
    """PRD §3.6: "there is no open negotiation — that is, no change request on this order is in
    `PROPOSED` or `COUNTERED` status".
    PRD §3.10: "Either way the request moves to `REJECTED` ... the order is left entirely
    unchanged".

    Design: Difficulty/cross_entity_state_dependency/guarantee_blocked_by_open_change_request_on_order
    """
    ctx = fx.setup_order_with_open_change(requested_headcount=90, clock="2026-06-01T00:00:00Z",
                                          booked_headcount=80)
    order, cr = ctx["order"], ctx["change_request"]
    # Reject closes the negotiation, so no open change request remains → guarantee permitted.
    validate_success(api.reject_change_request(cr["id"], {}, COORD))
    order_now = validate_success(api.get_order(order["id"], COORD))
    guaranteed = validate_success(
        api.guarantee_order(order["id"],
                            {"expected_order_version": order_now["version"], "guaranteed_headcount": 80},
                            COORD)
    )
    assert guaranteed["lifecycle_status"] == "GUARANTEED"


# =====================================================================
# Queue A — Rule 8: resource temporal overlap
# =====================================================================
def test_venue_overlap_half_open_adjacency_allowed(api):
    """PRD §3.5: "counting the non-cancelled orders at the same venue whose half-open
    `event_start`-to-`event_end` interval overlaps this order's window ... Adjacency is allowed,
    because the overlap interval is half-open: an event that starts exactly when another ends does
    not overlap it."

    Design: Difficulty/resource_temporal_overlap/venue_overbook_half_open_interval_adjacency_allowed
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    cat = fx.setup_catalog(venue_overrides={"max_overlapping_events": 1})
    headers = make_client_headers(cat["client"]["id"])
    order_a = validate_success(
        api.create_order(
            create_order_payload(cat["client"]["id"], cat["package"]["id"], cat["venue"]["id"],
                                 booked_headcount=80,
                                 event_start="2026-09-01T17:00:00Z", event_end="2026-09-01T22:00:00Z"),
            headers,
        ),
        expected_status=201,
    )
    fx.confirm_order(order_a)
    # Order B starts exactly when A ends → adjacency, not an overlap.
    order_b = validate_success(
        api.create_order(
            create_order_payload(cat["client"]["id"], cat["package"]["id"], cat["venue"]["id"],
                                 booked_headcount=80,
                                 event_start="2026-09-01T22:00:00Z", event_end="2026-09-01T23:00:00Z"),
            headers,
        ),
        expected_status=201,
    )
    confirmed_b = validate_success(
        api.confirm_order(order_b["id"], {"expected_order_version": order_b["version"]}, COORD)
    )
    assert confirmed_b["lifecycle_status"] == "CONFIRMED"


def test_leg_dispatch_inclusive_window_overlap_rejected(api):
    """PRD §3.11: "the single vehicle is not double-booked, meaning no other already-`DISPATCHED`
    leg on the same route has a window that overlaps this leg's `window_start`-to-`window_end`
    interval inclusively at the endpoints ... a dispatch whose window inclusively overlaps another
    dispatched leg's window on the route is rejected with `ERR_LEG_WINDOW_CONFLICT`".

    Design: Difficulty/resource_temporal_overlap/leg_dispatch_inclusive_window_overlap_rejected
    """
    ctx = fx.setup_guaranteed_order_with_route_and_leg(
        guaranteed_headcount=80,
        window_start="2026-09-01T15:00:00Z", window_end="2026-09-01T16:00:00Z",
    )
    order, route, leg1 = ctx["order"], ctx["route"], ctx["leg"]
    # leg2 window touches leg1's endpoint (16:00) → inclusive overlap.
    leg2 = fx.create_leg(order["id"], route["id"],
                         "2026-09-01T16:00:00Z", "2026-09-01T17:00:00Z", preceding_leg_id=leg1["id"])
    fx.dispatch_leg(leg1["id"], route["id"])
    validate_error(
        api.dispatch_delivery_leg(leg2["id"], {"expected_route_version": fx.route_version(route["id"])},
                                  CAPTAIN),
        ApiErrorId.ERR_LEG_WINDOW_CONFLICT.value,
    )
    leg2_after = validate_success(api.get_delivery_leg(leg2["id"], CAPTAIN))
    assert leg2_after["stop_status"] == "PLANNED"


def test_venue_overbook_true_overlap_rejected(api):
    """PRD §3.5: "counting the non-cancelled orders at the same venue whose half-open
    `event_start`-to-`event_end` interval overlaps this order's window — excluding this order
    itself — that count must be strictly less than the venue's `max_overlapping_events`; a
    confirmation that would meet or exceed the cap is rejected with `ERR_VENUE_OVERBOOKED`".

    Design: Difficulty/resource_temporal_overlap/venue_overbook_half_open_interval_adjacency_allowed
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    cat = fx.setup_catalog(venue_overrides={"max_overlapping_events": 1})
    headers = make_client_headers(cat["client"]["id"])
    order_a = validate_success(
        api.create_order(
            create_order_payload(cat["client"]["id"], cat["package"]["id"], cat["venue"]["id"],
                                 booked_headcount=80,
                                 event_start="2026-09-01T17:00:00Z", event_end="2026-09-01T22:00:00Z"),
            headers,
        ),
        expected_status=201,
    )
    fx.confirm_order(order_a)
    # Order B truly overlaps A (18:00-20:00 inside 17:00-22:00) → cap reached → rejected.
    order_b = validate_success(
        api.create_order(
            create_order_payload(cat["client"]["id"], cat["package"]["id"], cat["venue"]["id"],
                                 booked_headcount=80,
                                 event_start="2026-09-01T18:00:00Z", event_end="2026-09-01T20:00:00Z"),
            headers,
        ),
        expected_status=201,
    )
    validate_error(
        api.confirm_order(order_b["id"], {"expected_order_version": order_b["version"]}, COORD),
        ApiErrorId.ERR_VENUE_OVERBOOKED.value,
    )


def test_leg_dispatch_non_overlapping_windows_both_succeed(api):
    """PRD §3.11: "no other already-`DISPATCHED` leg on the same route has a window that overlaps
    this leg's `window_start`-to-`window_end` interval inclusively at the endpoints".

    Design: Difficulty/resource_temporal_overlap/leg_dispatch_inclusive_window_overlap_rejected
    """
    # leg1 15:00-16:00 dispatched; leg2 16:00:01-17:00 does NOT touch the endpoint → no conflict.
    ctx = fx.setup_guaranteed_order_with_route_and_leg(
        guaranteed_headcount=80,
        window_start="2026-09-01T15:00:00Z", window_end="2026-09-01T16:00:00Z",
    )
    order, route, leg1 = ctx["order"], ctx["route"], ctx["leg"]
    leg2 = fx.create_leg(order["id"], route["id"],
                         "2026-09-01T16:00:01Z", "2026-09-01T17:00:00Z", preceding_leg_id=leg1["id"])
    fx.dispatch_leg(leg1["id"], route["id"])
    dispatched2 = validate_success(
        api.dispatch_delivery_leg(leg2["id"], {"expected_route_version": fx.route_version(route["id"])},
                                  CAPTAIN)
    )
    assert dispatched2["stop_status"] == "DISPATCHED"


# =====================================================================
# Queue B — validations (single-failure scenarios)
# =====================================================================
def test_confirm_below_lead_time_rejected(api):
    """PRD §3.5: "a confirmation that falls inside the lead-time window is rejected with
    `ERR_LEAD_TIME_VIOLATED`".

    Design: Corner/validations/confirm_below_lead_time_returns_lead_time_violated
    """
    fx.set_clock("2026-09-01T07:00:00Z")
    ctx = fx.create_draft_order(
        booked_headcount=80, package_overrides={"lead_time_hours": 24},
        event_start="2026-09-01T17:00:00Z", event_end="2026-09-01T22:00:00Z",
    )
    order = ctx["order"]
    validate_error(
        api.confirm_order(order["id"], {"expected_order_version": order["version"]}, COORD),
        ApiErrorId.ERR_LEAD_TIME_VIOLATED.value,
    )


def test_order_below_min_headcount_rejected(api):
    """PRD §3.2: "A booked headcount below `min_headcount` at create is rejected with
    `ERR_BELOW_MIN_HEADCOUNT`".

    Design: Corner/validations/order_below_min_headcount_returns_below_min
    """
    cat = fx.setup_catalog(package_overrides={"name": "Big", "min_headcount": 20})
    headers = make_client_headers(cat["client"]["id"])
    validate_error(
        api.create_order(
            create_order_payload(cat["client"]["id"], cat["package"]["id"], cat["venue"]["id"],
                                 booked_headcount=5),
            headers,
        ),
        ApiErrorId.ERR_BELOW_MIN_HEADCOUNT.value,
    )


def test_dietary_counts_exceed_headcount_rejected(api):
    """PRD §3.2: "a request whose dietary counts exceed the in-scope headcount is rejected with
    `ERR_DIETARY_EXCEEDS_HEADCOUNT`".

    Design: Corner/validations/dietary_counts_exceed_headcount_returns_error
    """
    cat = fx.setup_catalog()
    headers = make_client_headers(cat["client"]["id"])
    validate_error(
        api.create_order(
            create_order_payload(cat["client"]["id"], cat["package"]["id"], cat["venue"]["id"],
                                 booked_headcount=10,
                                 dietary_counts={"VEGAN": 7, "NUT_FREE": 5}),
            headers,
        ),
        ApiErrorId.ERR_DIETARY_EXCEEDS_HEADCOUNT.value,
    )


def test_settle_with_unpaid_balance_rejected(api):
    """PRD §3.7: "If the balance does not yet equal the invoice, settlement is rejected with
    `ERR_BALANCE_UNPAID`".

    Design: Corner/validations/settle_with_unpaid_balance_returns_balance_unpaid
    """
    ctx = fx.setup_invoiced_order(guaranteed_headcount=80, clock="2026-06-01T00:00:00Z")
    order = ctx["order"]  # invoiced, no payment recorded
    validate_error(
        api.settle_order(order["id"], {"expected_order_version": order["version"]}, COORD),
        ApiErrorId.ERR_BALANCE_UNPAID.value,
    )
    after = validate_success(api.get_order(order["id"], COORD))
    assert after["settlement_status"] == "INVOICED"


def test_confirm_exceeds_staff_pool_rejected(api):
    """PRD §2.9: "if the reservation would exceed the remaining capacity, confirmation is rejected
    with `ERR_STAFF_POOL_EXHAUSTED`".

    Design: Corner/validations/confirm_exceeds_staff_pool_returns_exhausted
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    fx.set_staff_pool(5)
    ctx = fx.create_draft_order(booked_headcount=80)
    order = ctx["order"]
    fx.add_staffing(order["id"], ctx["client_headers"], quantity=8)
    validate_error(
        api.confirm_order(order["id"], {"expected_order_version": order["version"]}, COORD),
        ApiErrorId.ERR_STAFF_POOL_EXHAUSTED.value,
    )
    after = validate_success(api.get_order(order["id"], COORD))
    assert after["lifecycle_status"] == "DRAFT"


def test_duplicate_billing_email_rejected(api):
    """PRD §3.2: "registering a second active client with an email already in use is rejected with
    `ERR_DUPLICATE_EMAIL`".

    Design: Corner/validations/duplicate_billing_email_returns_duplicate_email
    """
    fx.create_client(company_name="First", billing_email="dup@x.com")
    validate_error(
        api.create_client({"company_name": "Second", "billing_email": "dup@x.com"}, ADMIN),
        ApiErrorId.ERR_DUPLICATE_EMAIL.value,
    )


def test_payment_over_final_total_rejected(api):
    """PRD §3.7: "A payment whose `amount_cents` is at or below zero, or that would push the
    running ledger balance above `final_total_cents`, is rejected with `ERR_INVALID_PAYMENT`".

    Design: Corner/validations/payment_over_final_total_returns_invalid_payment
    """
    ctx = fx.setup_invoiced_order(guaranteed_headcount=80, clock="2026-06-01T00:00:00Z")
    order = ctx["order"]  # final_total_cents == 587000
    assert order["final_total_cents"] == 587000
    validate_error(
        api.pay_order(order["id"],
                      {"expected_order_version": order["version"], "amount_cents": 600000},
                      ctx["client_headers"]),
        ApiErrorId.ERR_INVALID_PAYMENT.value,
    )
