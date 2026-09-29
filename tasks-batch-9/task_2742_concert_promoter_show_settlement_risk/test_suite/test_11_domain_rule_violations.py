"""Domain-rule violations, each answering with its own error id.

Every rule exercised here sits in the tenth and last band of the global
validation order, so nothing earlier in the order can mask it: the payloads are
well formed, every referenced row exists, the acting role is authorised and the
target sits in a legal state.  What is left is the domain rule itself, and each
one has to name itself in the response.
"""

import pytest

from test_helpers import (
    DEFAULT_CLOCK,
    api_errors as E,
    assert_timestamp_equals,
    factories as f,
    get_success_data,
    make_risk_officer_headers,
    validate_error,
    validate_paginated,
)

# PRD 3.1 requires a positive rental_fee_cents under the RENTAL arrangement, so
# every show built here carries one and the flat building fee is a known term of
# the promoter/venue split.
RENTAL_FEE_CENTS = 100_000

DECEMBER_WINDOW = {
    "event_at": "2026-12-02T02:00:00.000Z",
    "load_in_at": "2026-12-01T14:00:00.000Z",
    "load_out_at": "2026-12-02T08:00:00.000Z",
    "announce_at": DEFAULT_CLOCK,
}


def _market_act_and_hall(build, limit_cents=5_000_000, gross_capacity=1_000, label="Rule"):
    """A market, an act and a zero-fee, zero-tax hall that agree with each other."""
    market = build.market(
        name=f"{label} Market",
        region_code="RUL",
        guarantee_exposure_limit_cents=limit_cents,
    )
    artist = build.artist(
        name=f"{label} Act",
        agency="Meridian Talent",
        tier="THEATER",
        historical_sellthrough_pct=61.00,
        withholding_pct=0,
    )
    venue = build.venue(
        market["id"],
        name=f"{label} Hall",
        gross_capacity=gross_capacity,
        facility_fee_cents_per_ticket=0,
        ticket_tax_pct=0,
    )
    return market, artist, venue


def _planned_rental_show(build, artist_id, venue_id, **window):
    payload = dict(DECEMBER_WINDOW)
    payload.update(window)
    return build.show(
        artist_id,
        venue_id,
        venue_arrangement="RENTAL",
        rental_fee_cents=RENTAL_FEE_CENTS,
        **payload,
    )


def _show_payload(artist_id, venue_id, **window):
    payload = dict(DECEMBER_WINDOW)
    payload.update(window)
    return f.show_payload(
        artist_id,
        venue_id,
        venue_arrangement="RENTAL",
        rental_fee_cents=RENTAL_FEE_CENTS,
        **payload,
    )


def _on_sale_show_with_five_seats_left(build):
    """A 400-seat tier on sale with 395 sold, so exactly 5 seats remain."""
    market, artist, venue = _market_act_and_hall(build)
    show = _planned_rental_show(build, artist["id"], venue["id"])
    build.accepted_offer(
        show["id"],
        artist["id"],
        deal_structure="FLAT_GUARANTEE",
        guarantee_cents=500_000,
        deposit_cents=0,
        expense_cap_cents=500_000,
    )
    tier = build.tier(show["id"], tier_name="GA", price_cents=5_000, allocation_qty=400)
    get_success_data(build.api.put_show_on_sale(show["id"], build.buyer))
    build.sell(tier["id"], 395)
    tier = build.read_tier(tier["id"])
    assert tier["available_qty"] == 5, "the fixture must leave exactly five seats"
    return {"market": market, "artist": artist, "venue": venue, "show": show, "tier": tier}


# ---------------------------------------------------------------------------
# Show booking and ticket inventory
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "clause,window",
    [
        (
            "load_in_at after event_at",
            {
                "event_at": "2026-12-20T02:00:00.000Z",
                "load_in_at": "2026-12-21T00:00:00.000Z",
                "load_out_at": "2026-12-22T00:00:00.000Z",
                "announce_at": DEFAULT_CLOCK,
            },
        ),
        (
            "announce_at after event_at",
            {
                "event_at": "2026-12-20T02:00:00.000Z",
                "load_in_at": "2026-12-19T14:00:00.000Z",
                "load_out_at": "2026-12-20T08:00:00.000Z",
                "announce_at": "2026-12-25T15:00:00.000Z",
            },
        ),
    ],
)
def test_an_incoherent_show_window_is_refused_whichever_clause_breaks(build, api, clause, window):
    """PRD 3.1: "First, window coherence: `load_in_at` must be strictly earlier than `event_at`,
    `event_at` must be strictly earlier than `load_out_at`, and `announce_at` must be no later
    than `event_at`; otherwise `ERR_INVALID_SHOW_WINDOW`."

    Design: Corner/validations/show_and_inventory_rule_violations_each_return_their_own_error_id
    """
    _market, artist, venue = _market_act_and_hall(build)
    _planned_rental_show(build, artist["id"], venue["id"])

    response = api.create_show(_show_payload(artist["id"], venue["id"], **window), build.buyer)
    validate_error(response, E.ERR_INVALID_SHOW_WINDOW, expected_status=422)

    rows, meta = validate_paginated(api.list_shows(build.buyer, venue_id=venue["id"]))
    assert meta["total_count"] == 1, f"the refused create wrote a row ({clause})"
    assert len(rows) == 1


def test_a_coherent_window_entirely_in_the_past_is_a_past_event_date(build, api):
    """PRD 3.1: "Second, `event_at` must be strictly after the current logical clock — booking
    into the past yields `ERR_EVENT_DATE_IN_PAST`."

    Design: Corner/validations/show_and_inventory_rule_violations_each_return_their_own_error_id
    """
    _market, artist, venue = _market_act_and_hall(build)
    _planned_rental_show(build, artist["id"], venue["id"])

    response = api.create_show(
        _show_payload(
            artist["id"],
            venue["id"],
            event_at="2026-07-15T02:00:00.000Z",
            load_in_at="2026-07-14T14:00:00.000Z",
            load_out_at="2026-07-15T08:00:00.000Z",
            announce_at="2026-07-01T15:00:00.000Z",
        ),
        build.buyer,
    )
    validate_error(response, E.ERR_EVENT_DATE_IN_PAST, expected_status=422)

    _rows, meta = validate_paginated(api.list_shows(build.buyer, venue_id=venue["id"]))
    assert meta["total_count"] == 1, "a show booked into the past must not be persisted"


def test_a_second_tier_reusing_a_tier_name_on_the_same_show_is_a_conflict(build, api):
    """PRD 3.4: "and `tier_name` must be unique among that show's tiers, or the create is
    rejected with `ERR_DUPLICATE_TIER_NAME` (HTTP 409)."

    Design: Corner/validations/show_and_inventory_rule_violations_each_return_their_own_error_id
    """
    _market, artist, venue = _market_act_and_hall(build)
    show = _planned_rental_show(build, artist["id"], venue["id"])
    build.tier(show["id"], tier_name="GA", price_cents=5_000, allocation_qty=400)

    response = api.create_ticket_tier(
        f.ticket_tier_payload(show["id"], tier_name="GA", price_cents=6_000, allocation_qty=10),
        build.buyer,
    )
    validate_error(response, E.ERR_DUPLICATE_TIER_NAME, expected_status=409)

    rows, meta = validate_paginated(api.list_ticket_tiers(build.buyer, show_id=show["id"]))
    assert meta["total_count"] == 1, "the duplicate name must not have created a second tier"
    assert rows[0]["tier_name"] == "GA"
    assert rows[0]["allocation_qty"] == 400


def test_a_sale_of_one_seat_more_than_available_is_refused(build, api):
    """PRD 3.4: "and `qty` must not exceed the tier's `available_qty`, or the request is
    rejected with `ERR_INSUFFICIENT_TIER_INVENTORY` (HTTP 422)."

    Design: Corner/validations/show_and_inventory_rule_violations_each_return_their_own_error_id
    """
    world = _on_sale_show_with_five_seats_left(build)
    tier = world["tier"]

    response = api.record_sales(tier["id"], build.buyer, qty=6)
    validate_error(response, E.ERR_INSUFFICIENT_TIER_INVENTORY, expected_status=422)

    unchanged = build.read_tier(tier["id"])
    assert unchanged["sold_qty"] == 395
    assert unchanged["available_qty"] == 5
    assert unchanged["gross_sold_cents"] == 395 * 5_000


def test_a_hold_of_one_seat_more_than_available_is_refused(build, api):
    """PRD 3.5: "Second, the requested `qty` must not exceed the tier's `available_qty`, or the
    request is rejected with `ERR_INSUFFICIENT_TIER_INVENTORY` (HTTP 422) — inventory is never
    allowed to go negative."

    Design: Corner/validations/show_and_inventory_rule_violations_each_return_their_own_error_id
    """
    world = _on_sale_show_with_five_seats_left(build)
    tier = world["tier"]

    response = api.create_ticket_hold(
        f.ticket_hold_payload(tier["id"], kind="PROMOTER_HOLD", qty=6, holder="house left riser"),
        build.buyer,
    )
    validate_error(response, E.ERR_INSUFFICIENT_TIER_INVENTORY, expected_status=422)

    unchanged = build.read_tier(tier["id"])
    assert unchanged["held_qty"] == 0
    assert unchanged["available_qty"] == 5


def test_a_sale_of_exactly_the_available_quantity_succeeds(build, api):
    """PRD 3.4: "On success the tier's `sold_qty` increases by `qty`, its `available_qty`
    decreases by `qty`, and its `gross_sold_cents` **accumulates** the quantity multiplied by
    the tier's price **at that instant**."

    Design: Corner/validations/show_and_inventory_rule_violations_each_return_their_own_error_id
    """
    world = _on_sale_show_with_five_seats_left(build)
    tier = world["tier"]

    sold = get_success_data(api.record_sales(tier["id"], build.buyer, qty=5))
    assert sold["sold_qty"] == 400
    assert sold["available_qty"] == 0
    assert sold["gross_sold_cents"] == 400 * 5_000


def test_at_zero_available_even_a_single_held_seat_is_too_many(build, api):
    """PRD 3.5: "Second, the requested `qty` must not exceed the tier's `available_qty`, or the
    request is rejected with `ERR_INSUFFICIENT_TIER_INVENTORY` (HTTP 422) — inventory is never
    allowed to go negative."

    Design: Corner/validations/show_and_inventory_rule_violations_each_return_their_own_error_id
    """
    world = _on_sale_show_with_five_seats_left(build)
    tier = world["tier"]
    build.sell(tier["id"], 5)
    assert build.read_tier(tier["id"])["available_qty"] == 0

    response = api.create_ticket_hold(
        f.ticket_hold_payload(tier["id"], kind="PROMOTER_HOLD", qty=1, holder="one seat too late"),
        build.buyer,
    )
    validate_error(response, E.ERR_INSUFFICIENT_TIER_INVENTORY, expected_status=422)
    assert build.read_tier(tier["id"])["held_qty"] == 0


# ---------------------------------------------------------------------------
# Deal negotiation, the settlement book and the insurance claim window
# ---------------------------------------------------------------------------

JANUARY_WINDOW = {
    "event_at": "2027-01-20T02:00:00.000Z",
    "load_in_at": "2027-01-19T14:00:00.000Z",
    "load_out_at": "2027-01-20T08:00:00.000Z",
    "announce_at": DEFAULT_CLOCK,
}


def _second_act(build, label="Second"):
    return build.artist(
        name=f"{label} Act",
        agency="Meridian Talent",
        tier="THEATER",
        historical_sellthrough_pct=58.00,
        withholding_pct=0,
    )


def _on_sale_flat_show(build, guarantee_cents=500_000, deposit_cents=0, sold_qty=100,
                       allocation_qty=400, price_cents=5_000, window=None):
    """A CONFIRMED-then-ON_SALE rental show on one accepted flat-guarantee offer."""
    market, artist, venue = _market_act_and_hall(build)
    show = _planned_rental_show(build, artist["id"], venue["id"], **(window or {}))
    build.accepted_offer(
        show["id"],
        artist["id"],
        deal_structure="FLAT_GUARANTEE",
        guarantee_cents=guarantee_cents,
        deposit_cents=deposit_cents,
        expense_cap_cents=500_000,
    )
    tier = build.tier(
        show["id"], tier_name="GA", price_cents=price_cents, allocation_qty=allocation_qty
    )
    get_success_data(build.api.put_show_on_sale(show["id"], build.buyer))
    build.sell(tier["id"], sold_qty)
    return {"market": market, "artist": artist, "venue": venue, "show": show, "tier": tier}


def _perform(build, show_id, at=None):
    build.set_clock(at or DECEMBER_WINDOW["event_at"])
    return get_success_data(build.api.perform_show(show_id, build.accountant))


def test_an_acceptance_one_millisecond_after_expiry_is_refused(build, api):
    """PRD 3.2: "Separately, a counter or an acceptance attempted at or after the offer's
    `expires_at` is rejected with `ERR_OFFER_EXPIRED` (HTTP 409); the current logical clock must
    be strictly earlier than `expires_at`."

    Design: Corner/validations/settlement_offer_and_claim_rule_violations_each_return_their_own_error_id
    """
    market, artist, venue = _market_act_and_hall(build)
    show = _planned_rental_show(build, artist["id"], venue["id"])
    offer = build.submitted_offer(
        show["id"],
        deal_structure="FLAT_GUARANTEE",
        guarantee_cents=300_000,
        deposit_cents=0,
        expense_cap_cents=500_000,
    )
    assert_timestamp_equals(offer["expires_at"], "2026-08-04T00:00:00.000Z")

    build.set_clock("2026-08-04T00:00:00.001Z")
    response = api.accept_offer(offer["id"], build.artist_rep(artist["id"]))
    validate_error(response, E.ERR_OFFER_EXPIRED, expected_status=409)

    assert build.read_offer(offer["id"])["status"] == "SUBMITTED"
    assert build.read_show(show["id"])["show_status"] == "PLANNED"
    assert build.read_market(market["id"])["committed_guarantee_cents"] == 0
    assert venue["id"] == build.read_show(show["id"])["venue_id"]


def test_a_reschedule_onto_a_show_that_never_named_the_original_is_refused(build, api):
    """PRD 3.9: "The replacement must be a genuine replacement: the show it names must carry a
    `rescheduled_from_show_id` equal to the event's own `show_id`, must itself be in
    `show_status` `PLANNED`, and must not be the original show; any violation yields
    `ERR_REPLACEMENT_SHOW_INVALID` (HTTP 422)."

    Design: Corner/validations/settlement_offer_and_claim_rule_violations_each_return_their_own_error_id
    """
    _market, artist, venue = _market_act_and_hall(build)
    postponed = _planned_rental_show(build, artist["id"], venue["id"])
    build.accepted_offer(
        postponed["id"],
        artist["id"],
        deal_structure="FLAT_GUARANTEE",
        guarantee_cents=300_000,
        deposit_cents=0,
        expense_cap_cents=500_000,
    )
    unrelated = _planned_rental_show(
        build, _second_act(build)["id"], venue["id"], **JANUARY_WINDOW
    )
    assert unrelated["rescheduled_from_show_id"] is None

    event = build.cancellation_event(postponed["id"], kind="POSTPONED")
    response = api.reschedule_cancellation_event(
        event["id"], build.buyer, replacement_show_id=unrelated["id"]
    )
    validate_error(response, E.ERR_REPLACEMENT_SHOW_INVALID, expected_status=422)

    assert build.read_event(event["id"])["status"] == "OPENED"
    assert build.read_event(event["id"])["replacement_show_id"] is None
    assert build.read_show(postponed["id"])["show_status"] == "POSTPONED"
    assert build.read_show(unrelated["id"])["show_status"] == "PLANNED"


def test_an_override_one_cent_above_twice_the_market_limit_is_refused(build, api):
    """PRD 3.3: "The override may not exceed twice the market's own
    `guarantee_exposure_limit_cents`, and the justification may not be empty; either violation
    yields `ERR_EXPOSURE_OVERRIDE_INVALID` (HTTP 422)."

    Design: Corner/validations/settlement_offer_and_claim_rule_violations_each_return_their_own_error_id
    """
    _market, artist, venue = _market_act_and_hall(build, limit_cents=5_000_000)
    show = _planned_rental_show(build, artist["id"], venue["id"])

    response = api.grant_exposure_override(
        show["id"],
        build.risk,
        exposure_override_limit_cents=10_000_001,
        exposure_override_justification="one cent beyond what the officer may lift",
    )
    validate_error(response, E.ERR_EXPOSURE_OVERRIDE_INVALID, expected_status=422)

    after = build.read_show(show["id"])
    assert after["exposure_override_limit_cents"] is None
    assert after["exposure_override_by_user_id"] is None
    assert after["version"] == show["version"]


def test_an_invoice_whose_budget_line_belongs_to_another_show_is_refused(build, api):
    """PRD 3.6: "Cross-reference coherence is enforced: the `BudgetLine` named by
    `budget_line_id` must belong to the same show as the `show_id` on the invoice, or the create
    is rejected with `ERR_BUDGET_LINE_SHOW_MISMATCH` (HTTP 422)."

    Design: Corner/validations/settlement_offer_and_claim_rule_violations_each_return_their_own_error_id
    """
    _market, artist, venue = _market_act_and_hall(build)
    show_x = _planned_rental_show(build, artist["id"], venue["id"])
    show_y = _planned_rental_show(
        build, _second_act(build)["id"], venue["id"], **JANUARY_WINDOW
    )
    line_on_y = build.budget_line(
        show_y["id"],
        category="PRODUCTION",
        description="rigging call on the January date",
        budgeted_cents=50_000,
        is_artist_deductible=False,
    )

    response = api.create_vendor_invoice(
        f.vendor_invoice_payload(
            show_x["id"],
            line_on_y["id"],
            amount_cents=40_000,
            vendor_name="Crossed Wires Freight",
            documentation_ref="PKT-MM-01",
        ),
        build.accountant,
    )
    validate_error(response, E.ERR_BUDGET_LINE_SHOW_MISMATCH, expected_status=422)

    _rows, meta = validate_paginated(
        api.list_vendor_invoices(build.accountant, show_id=show_x["id"])
    )
    assert meta["total_count"] == 0
    assert build.read_budget_line(line_on_y["id"])["actual_cents"] == 0


def test_a_calculation_with_a_pending_variance_is_refused_until_the_variance_is_decided(build, api):
    """PRD 3.7: "and no budget line on the show may be `PENDING_APPROVAL`, or the call is
    rejected with `ERR_UNRESOLVED_VARIANCE` (HTTP 409)."

    Design: Corner/validations/settlement_offer_and_claim_rule_violations_each_return_their_own_error_id
    """
    world = _on_sale_flat_show(build, guarantee_cents=300_000, sold_qty=100)
    line = build.line_with_actual(
        world["show"]["id"],
        200_000,
        260_000,
        category="PRODUCTION",
        is_artist_deductible=False,
        vendor_name="Overrun Staging",
    )
    assert line["variance_pct"] == pytest.approx(30.00, abs=0.01)
    assert line["variance_status"] == "PENDING_APPROVAL"
    assert line["required_approver_role"] == "RISK_OFFICER"
    _perform(build, world["show"]["id"])

    book = build.settlement(world["show"]["id"])
    validate_error(
        api.calculate_settlement(book["id"], build.accountant),
        E.ERR_UNRESOLVED_VARIANCE,
        expected_status=409,
    )
    assert build.read_settlement(book["id"])["status"] == "DRAFT"

    decided = build.approve_variance(line["id"], 260_000, as_risk_officer=True)
    assert decided["variance_status"] == "APPROVED"
    assert decided["settlement_expense_cents"] == 260_000

    calculated = get_success_data(api.calculate_settlement(book["id"], build.accountant))
    assert calculated["status"] == "CALCULATED"
    assert calculated["adjusted_gross_cents"] == 487_500
    assert calculated["total_settlement_expense_cents"] == 260_000
    assert calculated["promoter_borne_expense_cents"] == 260_000
    assert calculated["venue_share_cents"] == RENTAL_FEE_CENTS
    assert calculated["artist_earnings_cents"] == 300_000
    assert calculated["promoter_net_cents"] == -172_500


def test_a_second_settlement_while_one_is_outstanding_is_refused(build, api):
    """PRD 3.7: "A show may have at most one settlement that is not yet `PAID`; attempting to
    open a second while one is outstanding yields `ERR_SETTLEMENT_ALREADY_OPEN` (HTTP 409)."

    Design: Corner/validations/settlement_offer_and_claim_rule_violations_each_return_their_own_error_id
    """
    world = _on_sale_flat_show(build, guarantee_cents=300_000, sold_qty=100)
    build.budget_line(
        world["show"]["id"],
        category="PRODUCTION",
        description="backline rental for the December date",
        budgeted_cents=200_000,
        is_artist_deductible=False,
    )
    _perform(build, world["show"]["id"])
    first = build.settlement(world["show"]["id"])
    assert first["status"] == "DRAFT"

    validate_error(
        api.create_settlement(f.settlement_payload(world["show"]["id"]), build.accountant),
        E.ERR_SETTLEMENT_ALREADY_OPEN,
        expected_status=409,
    )

    rows, meta = validate_paginated(
        api.list_settlements(build.accountant, show_id=world["show"]["id"])
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == first["id"]


def _refunds_processed_event(build, occurred_at="2026-12-02T02:00:00.000Z"):
    """A cancelled, refunded January date whose claim window opens at ``occurred_at``."""
    world = _on_sale_flat_show(
        build,
        guarantee_cents=500_000,
        deposit_cents=100_000,
        sold_qty=100,
        allocation_qty=400,
        price_cents=2_000,
        window=JANUARY_WINDOW,
    )
    build.set_clock(occurred_at)
    event = build.refunds_processed_event(world["show"]["id"])
    assert event["status"] == "REFUNDS_PROCESSED"
    assert_timestamp_equals(event["occurred_at"], occurred_at)
    world["event"] = event
    return world


def test_a_claim_filed_at_the_final_instant_of_the_window_is_accepted(build, api):
    """PRD 3.9: "The filing must land inside the claim window: the current logical clock must be
    within 30 days of the event's `occurred_at`, inclusive of the final instant, or the filing is
    rejected with `ERR_CLAIM_WINDOW_CLOSED` (HTTP 422)."

    Design: Corner/validations/settlement_offer_and_claim_rule_violations_each_return_their_own_error_id
    """
    world = _refunds_processed_event(build, occurred_at="2026-12-02T02:00:00.000Z")

    build.set_clock("2027-01-01T02:00:00.000Z")
    filed = get_success_data(
        api.file_claim(
            world["event"]["id"],
            build.risk,
            claim_amount_cents=400_000,
            claim_documentation_ref="CLM-EDGE-01",
        )
    )
    assert filed["status"] == "CLAIM_FILED"
    assert filed["claim_amount_cents"] == 400_000


def test_a_claim_filed_one_millisecond_past_the_window_is_refused(build, api):
    """PRD 3.9: "The filing must land inside the claim window: the current logical clock must be
    within 30 days of the event's `occurred_at`, inclusive of the final instant, or the filing is
    rejected with `ERR_CLAIM_WINDOW_CLOSED` (HTTP 422)."

    Design: Corner/validations/settlement_offer_and_claim_rule_violations_each_return_their_own_error_id
    """
    world = _refunds_processed_event(build, occurred_at="2026-12-02T02:00:00.000Z")

    build.set_clock("2027-01-01T02:00:00.001Z")
    validate_error(
        api.file_claim(
            world["event"]["id"],
            build.risk,
            claim_amount_cents=400_000,
            claim_documentation_ref="CLM-EDGE-02",
        ),
        E.ERR_CLAIM_WINDOW_CLOSED,
        expected_status=422,
    )

    unchanged = build.read_event(world["event"]["id"])
    assert unchanged["status"] == "REFUNDS_PROCESSED"
    assert unchanged["version"] == world["event"]["version"], (
        "a refused filing must run no side effect, so the event's version may not move"
    )


# ---------------------------------------------------------------------------
# The satisfied side of the same rules, sitting exactly on the boundary
# ---------------------------------------------------------------------------

EDGE_WINDOW = {
    "event_at": "2026-08-01T00:00:00.001Z",
    "load_in_at": "2026-07-31T20:00:00.000Z",
    "load_out_at": "2026-08-01T06:00:00.000Z",
    "announce_at": "2026-08-01T00:00:00.001Z",
}

SEPTEMBER_WINDOW = {
    "event_at": "2026-09-02T02:00:00.000Z",
    "load_in_at": "2026-09-01T14:00:00.000Z",
    "load_out_at": "2026-09-02T08:00:00.000Z",
    "announce_at": DEFAULT_CLOCK,
}


def _pass_market_and_room(build):
    market = build.market(
        name="Pass Market", region_code="PAS", guarantee_exposure_limit_cents=4_000_000
    )
    venue = build.venue(
        market["id"],
        name="Pass Room",
        gross_capacity=300,
        facility_fee_cents_per_ticket=0,
        ticket_tax_pct=0,
    )
    return market, venue


def _pass_act(build, ordinal):
    return build.artist(
        name=f"Pass Act {ordinal}",
        agency="Meridian Talent",
        tier="CLUB",
        historical_sellthrough_pct=55.00,
        withholding_pct=0,
    )


def test_an_announce_equal_to_an_event_one_millisecond_away_is_booked(build, api):
    """PRD 3.1: "First, window coherence: `load_in_at` must be strictly earlier than `event_at`,
    `event_at` must be strictly earlier than `load_out_at`, and `announce_at` must be no later
    than `event_at`; otherwise `ERR_INVALID_SHOW_WINDOW`."

    Design: Corner/validations/satisfied_conditions_pass_at_the_exact_edge_of_the_rule_they_almost_break
    """
    _market, venue = _pass_market_and_room(build)
    artist = _pass_act(build, 1)

    created = get_success_data(
        api.create_show(_show_payload(artist["id"], venue["id"], **EDGE_WINDOW), build.buyer),
        expected_status=201,
    )
    assert created["show_status"] == "PLANNED"
    assert_timestamp_equals(created["event_at"], EDGE_WINDOW["event_at"])
    assert_timestamp_equals(created["announce_at"], EDGE_WINDOW["event_at"])
    assert_timestamp_equals(created["load_in_at"], EDGE_WINDOW["load_in_at"])


def test_two_tiers_summing_to_exactly_gross_capacity_are_both_allowed(build, api):
    """PRD 3.4: "the sum of `allocation_qty` across the show's tiers, counting the tier being
    created, may not exceed the venue's `gross_capacity`, or the create is rejected with
    `ERR_VENUE_CAPACITY_EXCEEDED` (HTTP 422)"

    Design: Corner/validations/satisfied_conditions_pass_at_the_exact_edge_of_the_rule_they_almost_break
    """
    _market, venue = _pass_market_and_room(build)
    artist = _pass_act(build, 1)
    show = _planned_rental_show(build, artist["id"], venue["id"], **SEPTEMBER_WINDOW)

    front = get_success_data(
        api.create_ticket_tier(
            f.ticket_tier_payload(
                show["id"], tier_name="FRONT", price_cents=9_000, allocation_qty=100
            ),
            build.buyer,
        ),
        expected_status=201,
    )
    balcony = get_success_data(
        api.create_ticket_tier(
            f.ticket_tier_payload(
                show["id"], tier_name="BALCONY", price_cents=4_000, allocation_qty=200
            ),
            build.buyer,
        ),
        expected_status=201,
    )
    assert front["allocation_qty"] == 100
    assert balcony["allocation_qty"] == 200
    assert balcony["available_qty"] == 200
    assert venue["gross_capacity"] == front["allocation_qty"] + balcony["allocation_qty"]


def test_an_invoice_against_its_own_shows_budget_line_is_accepted(build, api):
    """PRD 3.6: "Cross-reference coherence is enforced: the `BudgetLine` named by
    `budget_line_id` must belong to the same show as the `show_id` on the invoice, or the create
    is rejected with `ERR_BUDGET_LINE_SHOW_MISMATCH` (HTTP 422)."

    Design: Corner/validations/satisfied_conditions_pass_at_the_exact_edge_of_the_rule_they_almost_break
    """
    _market, venue = _pass_market_and_room(build)
    artist = _pass_act(build, 1)
    show = _planned_rental_show(build, artist["id"], venue["id"], **SEPTEMBER_WINDOW)
    line = build.budget_line(
        show["id"],
        category="PRODUCTION",
        description="backline for the September date",
        budgeted_cents=60_000,
        is_artist_deductible=True,
    )

    invoice = get_success_data(
        api.create_vendor_invoice(
            f.vendor_invoice_payload(
                show["id"],
                line["id"],
                amount_cents=55_000,
                vendor_name="Matched Freight",
                documentation_ref="PKT-PS-01",
            ),
            build.accountant,
        ),
        expected_status=201,
    )
    assert invoice["status"] == "SUBMITTED"
    assert invoice["show_id"] == show["id"]
    assert invoice["budget_line_id"] == line["id"]
    assert build.read_budget_line(line["id"])["actual_cents"] == 0


def test_a_tier_name_is_free_again_on_a_different_show(build, api):
    """PRD 3.4: "and `tier_name` must be unique among that show's tiers, or the create is
    rejected with `ERR_DUPLICATE_TIER_NAME` (HTTP 409)."

    Design: Corner/validations/satisfied_conditions_pass_at_the_exact_edge_of_the_rule_they_almost_break
    """
    _market, venue = _pass_market_and_room(build)
    first = _planned_rental_show(
        build, _pass_act(build, 1)["id"], venue["id"], **EDGE_WINDOW
    )
    second = _planned_rental_show(
        build, _pass_act(build, 2)["id"], venue["id"], **SEPTEMBER_WINDOW
    )
    build.tier(first["id"], tier_name="GA", price_cents=5_000, allocation_qty=100)

    reused = get_success_data(
        api.create_ticket_tier(
            f.ticket_tier_payload(
                second["id"], tier_name="GA", price_cents=5_000, allocation_qty=100
            ),
            build.buyer,
        ),
        expected_status=201,
    )
    assert reused["tier_name"] == "GA"
    assert reused["show_id"] == second["id"]

    _rows, first_meta = validate_paginated(api.list_ticket_tiers(build.buyer, show_id=first["id"]))
    _rows, second_meta = validate_paginated(
        api.list_ticket_tiers(build.buyer, show_id=second["id"])
    )
    assert first_meta["total_count"] == 1
    assert second_meta["total_count"] == 1


def test_an_override_at_exactly_twice_the_market_limit_is_granted(build, api):
    """PRD 3.3: "On success the show records `exposure_override_limit_cents`,
    `exposure_override_justification` and `exposure_override_by_user_id` (the granting officer's
    opaque `X-User-ID`), and the show's `version` increments by 1."

    Design: Corner/validations/satisfied_conditions_pass_at_the_exact_edge_of_the_rule_they_almost_break
    """
    market, venue = _pass_market_and_room(build)
    show = _planned_rental_show(
        build, _pass_act(build, 1)["id"], venue["id"], **SEPTEMBER_WINDOW
    )
    officer = make_risk_officer_headers("risk-edge-officer")

    granted = get_success_data(
        api.grant_exposure_override(
            show["id"],
            officer,
            exposure_override_limit_cents=2 * market["guarantee_exposure_limit_cents"],
            exposure_override_justification="strategic routing worth exactly double the ceiling",
        )
    )
    assert granted["exposure_override_limit_cents"] == 8_000_000
    assert granted["exposure_override_by_user_id"] == "risk-edge-officer"
    assert granted["version"] == show["version"] + 1
