"""Ticket tiers: optimistic concurrency, half-open sales windows, capacity
boundary, the logical clock default, and the ticket pricing pipeline
(PRD §3.4, §2.4, §2.7)."""
from datetime import datetime

import pytest

from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    assert_ticket_tier,
    assert_registration,
    create_record,
    create_event,
    create_committee,
    create_tier,
    register,
    confirm,
    setup_open_event,
    current_event,
    invite_member,
    accept_membership,
    TEST_USERS,
    make_alumni_headers,
)

STAFF = TEST_USERS["staff_headers"]


# ---------------------------------------------------------------------------
# OCC on tier creation and the default logical clock
# ---------------------------------------------------------------------------

def test_occ_stale_version_on_tier_create(api):
    """PRD §2.7: "creating a ticket tier on a reunion event requires the
    request body to carry `expected_event_version`, holding the event's
    `version` as the client last observed it. A prior tier creation or any
    posture-affecting mutation advances the event's `version`; if it no longer
    matches the submitted value, the create is rejected with
    `ERR_STALE_VERSION` (HTTP 412)".
    PRD §3.4: "A successful tier create starts `sold_count` at 0, increments
    the parent event's `version` by one, and re-derives posture."

    Design: Corner/cross_cutting_layers/occ_stale_version_on_tier_create
    """
    event = create_event()
    observed_version = event["version"]

    first = api.create_ticket_tier(
        event["id"],
        {
            "name": "T1", "base_price_cents": 1000, "capacity": 0,
            "sales_start": "2026-05-01T00:00:00Z", "sales_end": "2026-06-01T00:00:00Z",
            "early_bird_discount_pct": 0, "expected_event_version": observed_version,
        },
        STAFF,
    )
    validate_success(first, 201)
    event_after = validate_success(api.get_event(event["id"], STAFF))
    assert event_after["version"] == observed_version + 1

    stale = api.create_ticket_tier(
        event["id"],
        {
            "name": "T2", "base_price_cents": 1500, "capacity": 0,
            "sales_start": "2026-06-01T00:00:00Z", "sales_end": "2026-08-01T00:00:00Z",
            "early_bird_discount_pct": 0, "expected_event_version": observed_version,
        },
        STAFF,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)


def test_logical_clock_default_fixed(api):
    """PRD §2.4: "At startup, before any clock operation has been performed,
    the logical clock reads exactly `2026-05-01T00:00:00Z`."
    PRD §3.4: "a purchase at `sales_start` is inside the window".

    Design: Corner/cross_cutting_layers/logical_clock_default_fixed
    """
    # No set_current_utc call anywhere in this test: the tier window opens
    # exactly at the startup default reading 2026-05-01T00:00:00Z.
    ctx = setup_open_event(
        tier_overrides={
            "name": "GA", "base_price_cents": 1000, "capacity": 0,
            "sales_start": "2026-05-01T00:00:00Z", "sales_end": "2026-09-01T00:00:00Z",
        },
        clock_iso=None,
    )
    guest = create_record(full_name="KG", primary_email="kg@x.com")
    resp = api.create_registration(
        ctx["event"]["id"],
        {"tier_id": ctx["tier"]["id"], "alumni_id": guest["id"]},
        make_alumni_headers(guest["id"]),
    )
    data = validate_success(resp, 201)
    assert_registration(data)
    assert data["payment_status"] == "PENDING_PAYMENT"


# ---------------------------------------------------------------------------
# Half-open sales-window overlap semantics
# ---------------------------------------------------------------------------

def test_tier_window_touching_at_endpoint_allowed(api):
    """PRD §3.4: "the windows of an event's tiers may not overlap, though
    windows that merely touch at an endpoint are allowed".

    Design: Difficulty/resource_temporal_overlap/tier_sales_window_half_open_touching_allowed
    """
    event = create_event()
    create_tier(
        event["id"],
        name="Early", base_price_cents=1000, capacity=10,
        sales_start="2026-05-01T00:00:00Z", sales_end="2026-06-01T00:00:00Z",
    )

    # Second tier starts exactly at the first tier's sales_end: touching is allowed.
    resp_tier = create_tier(
        event["id"],
        name="Regular", base_price_cents=1500, capacity=10,
        sales_start="2026-06-01T00:00:00Z", sales_end="2026-08-01T00:00:00Z",
    )
    assert_ticket_tier(resp_tier)
    # PRD pins the three-fractional-digit timestamp format only for
    # server-generated timestamps (created_at/updated_at/api_request_timestamp),
    # not for the echo of a user-supplied `sales_start`; compare instants so
    # both verbatim-echo and normalized-echo implementations pass.
    assert datetime.fromisoformat(
        resp_tier["sales_start"].replace("Z", "+00:00")
    ) == datetime.fromisoformat("2026-06-01T00:00:00+00:00")


def test_tier_window_overlapping_by_one_second_rejected(api):
    """PRD §3.4: "The sales window is a half-open interval — a purchase at
    `sales_start` is inside the window, a purchase at `sales_end` is outside
    it — and the windows of an event's tiers may not overlap, though windows
    that merely touch at an endpoint are allowed; an overlapping create is
    rejected with `ERR_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/tier_sales_window_half_open_touching_allowed
    """
    event = create_event()
    create_tier(
        event["id"],
        name="Early", base_price_cents=1000, capacity=10,
        sales_start="2026-05-01T00:00:00Z", sales_end="2026-06-01T00:00:00Z",
    )
    create_tier(
        event["id"],
        name="Regular", base_price_cents=1500, capacity=10,
        sales_start="2026-06-01T00:00:00Z", sales_end="2026-08-01T00:00:00Z",
    )

    # Starts one second inside [2026-06-01, 2026-08-01): overlaps.
    resp = api.create_ticket_tier(
        event["id"],
        {
            "name": "Overlapper", "base_price_cents": 2000, "capacity": 10,
            "sales_start": "2026-07-31T23:59:59Z", "sales_end": "2026-09-01T00:00:00Z",
            "early_bird_discount_pct": 0,
            "expected_event_version": current_event(event["id"])["version"],
        },
        STAFF,
    )
    validate_error(resp, ApiErrorId.ERR_WINDOW_OVERLAP)


# ---------------------------------------------------------------------------
# Pricing pipeline: dual variant (ESTIMATE vs FINAL) and stacked inputs
# ---------------------------------------------------------------------------

def _late_fee_scenario(api):
    """Event OPEN with unlimited 10000-cent tier; clock inside the final
    seven days before event_date, past the early-bird cutoff."""
    ctx = setup_open_event(
        event_overrides={"event_date": "2026-08-10T18:00:00Z",
                         "title": "Class of 2001 25th Reunion"},
        tier_overrides={
            "name": "Standard", "base_price_cents": 10000, "capacity": 0,
            "sales_start": "2026-05-01T00:00:00Z", "sales_end": "2026-08-10T00:00:00Z",
            "early_bird_discount_pct": 0,
        },
        clock_iso="2026-05-15T00:00:00Z",
    )
    # Advance into the late-fee window (event_date - 7 days = 2026-08-03T18:00).
    api_client_set_clock = api.set_clock("2026-08-05T00:00:00Z", STAFF)
    validate_success(api_client_set_clock)
    registrant = create_record(full_name="Reg One", primary_email="reg1@x.com")
    return ctx, registrant


def test_estimate_ignores_late_fee(api):
    """PRD §3.4: "At registration creation the ESTIMATE variant produces
    `quoted_price_cents`: it is forward-looking, applying the early-bird
    discount whenever the clock is currently before the cutoff, and ignoring
    the late fee entirely since a registration is never late at the moment it
    is created."

    Design: Difficulty/dual_variant_calc/ticket_price_estimate_vs_final_late_fee
    """
    ctx, registrant = _late_fee_scenario(api)
    registration = register(ctx["event"]["id"], ctx["tier"]["id"], registrant["id"])
    # No early-bird discount (pct 0), no committee membership, late fee ignored:
    # ESTIMATE is the bare list price.
    assert registration["quoted_price_cents"] == 10000


def test_final_applies_late_fee_within_seven_days(api):
    """PRD §3.4: "Step three adds a flat late fee of $15.00 (1500 cents) when
    the current logical clock has advanced into the final seven days before
    the event" and "At payment confirmation the FINAL variant produces
    `final_price_cents`: it is chronological, evaluating all four steps
    against the logical clock at confirm time, including the late fee."

    Design: Difficulty/dual_variant_calc/ticket_price_estimate_vs_final_late_fee
    """
    ctx, registrant = _late_fee_scenario(api)
    registration = register(ctx["event"]["id"], ctx["tier"]["id"], registrant["id"])
    confirmed = confirm(registration["id"], registrant["id"])
    assert confirmed["payment_status"] == "CONFIRMED"
    assert confirmed["final_price_cents"] == 11500, (
        f"FINAL = 10000 + 1500 late fee, got {confirmed['final_price_cents']}"
    )
    assert confirmed["final_price_cents"] != registration["quoted_price_cents"]


def _stacked_discount_setup(api):
    """Full stacked-input setup: committee MEMBER accepted before opening.

    Order: event -> committee -> CHAIR accept -> MEMBER invite+accept ->
    form-committee -> tier -> clock -> open-registration.
    """
    chair = create_record(full_name="Chair Three", primary_email="chair3@x.com")
    member = create_record(full_name="Member Three", primary_email="member3@x.com")
    event = create_event(
        title="Reunion 25", event_date="2026-09-20T18:00:00Z",
        committee_quorum_required=1,
    )
    committee = create_committee(event["id"])
    chair_mem = invite_member(committee["id"], chair["id"], role="CHAIR")
    accept_membership(chair_mem["id"], chair["id"])
    member_mem = invite_member(committee["id"], member["id"], role="MEMBER")
    accept_membership(member_mem["id"], member["id"])
    validate_success(api.form_committee(event["id"], STAFF))
    tier = create_tier(
        event["id"],
        name="Early", base_price_cents=20000, capacity=0,
        sales_start="2026-05-01T00:00:00Z", sales_end="2026-09-20T00:00:00Z",
        early_bird_discount_pct=10,
    )
    validate_success(api.set_clock("2026-07-01T00:00:00Z", STAFF))
    validate_success(api.open_registration(event["id"], STAFF))
    return {"event": current_event(event["id"]), "tier": tier, "member": member}


def test_stacked_discounts_estimate_at_creation(api):
    """PRD §3.4: "step one applies the early-bird discount when the current
    logical clock is before the early-bird cutoff — sixty days before the
    `event_date` — by scaling the price by the complement of
    `early_bird_discount_pct` (a 20 percent discount multiplies the price by
    0.80). Step two grants committee members a 25 percent discount, scaling
    the running price by 0.75, whenever the registrant holds a committee
    membership with `status` `ACTIVE` on this event's committee."
    PRD §3.4: "At registration creation the ESTIMATE variant produces
    `quoted_price_cents` ... ignoring the late fee entirely".

    Design: Difficulty/combinatorial_formula/ticket_price_three_input_stacked_discounts
    """
    ctx = _stacked_discount_setup(api)
    registration = register(ctx["event"]["id"], ctx["tier"]["id"], ctx["member"]["id"])
    # 20000 * 0.90 (early bird) * 0.75 (committee) = 13500; no late fee.
    assert registration["quoted_price_cents"] == 13500


def test_stacked_discounts_final_at_confirmation(api):
    """PRD §3.4: "The price a registrant pays is computed by a four-step
    pipeline whose evaluation order is pinned: early-bird discount first,
    committee discount second, late fee third, rounding last." With the clock
    at 2026-07-01 — before the early-bird cutoff of event_date minus sixty
    days and not "strictly later than `event_date` minus seven days" — the
    FINAL price is 20000 * 0.90 * 0.75 = 13500.

    Design: Difficulty/combinatorial_formula/ticket_price_three_input_stacked_discounts
    """
    ctx = _stacked_discount_setup(api)
    registration = register(ctx["event"]["id"], ctx["tier"]["id"], ctx["member"]["id"])
    confirmed = confirm(registration["id"], ctx["member"]["id"])
    assert confirmed["final_price_cents"] == 13500


# ---------------------------------------------------------------------------
# Capacity boundary: capacity == 0 is unlimited
# ---------------------------------------------------------------------------

def _capacity_zero_scenario(api):
    ctx = setup_open_event(
        event_overrides={"event_date": "2026-09-01T18:00:00Z"},
        tier_overrides={
            "name": "Unlimited", "base_price_cents": 1000, "capacity": 0,
            "sales_start": "2026-05-01T00:00:00Z", "sales_end": "2026-09-01T00:00:00Z",
        },
        clock_iso="2026-06-01T00:00:00Z",
    )
    guest = create_record(full_name="Guest D", primary_email="guestd@x.com")
    return ctx, guest


def test_capacity_zero_tier_never_sold_out(api):
    """PRD §3.4: "A `capacity` of exactly 0 means the tier is unlimited and
    can never sell out; any positive capacity sells out when `sold_count`
    reaches it."

    Design: Difficulty/boundary_precision_check/tier_capacity_zero_is_unlimited_not_sold_out
    """
    ctx, guest = _capacity_zero_scenario(api)
    r1 = register(ctx["event"]["id"], ctx["tier"]["id"], guest["id"])
    confirm(r1["id"], guest["id"])
    r2 = register(ctx["event"]["id"], ctx["tier"]["id"], guest["id"])
    confirmed2 = confirm(r2["id"], guest["id"])
    assert confirmed2["payment_status"] == "CONFIRMED", (
        "Second confirmation on a capacity-0 tier must not raise ERR_TIER_SOLD_OUT"
    )

    tier = validate_success(api.get_ticket_tier(ctx["tier"]["id"], STAFF))
    assert tier["sold_count"] == 2
    assert tier["capacity"] == 0


def test_capacity_zero_tier_keeps_posture_open(api):
    """PRD §3.4: "otherwise it is `SOLD_OUT` when no tier remains bookable —
    every tier having a positive `capacity` fully reached by its `sold_count`
    — and `OPEN` when at least one tier is bookable." A capacity-0 tier is
    never fully reached, so the posture stays OPEN.

    Design: Difficulty/boundary_precision_check/tier_capacity_zero_is_unlimited_not_sold_out
    """
    ctx, guest = _capacity_zero_scenario(api)
    r1 = register(ctx["event"]["id"], ctx["tier"]["id"], guest["id"])
    confirm(r1["id"], guest["id"])
    r2 = register(ctx["event"]["id"], ctx["tier"]["id"], guest["id"])
    confirm(r2["id"], guest["id"])

    event = validate_success(api.get_event(ctx["event"]["id"], STAFF))
    assert event["posture"] == "OPEN"
