"""Aggregate ceilings, configuration-scoped rules and the fixed order of checks.

Three questions are asked here.  Does a limit that no single request breaks
still bind once the requests are added together?  Does a rule that names one
configuration stay silent on every other configuration?  And when two rules
could both reject the same call, does the earlier band of the global validation
order answer first?
"""

import pytest

from test_helpers import (
    DEFAULT_CLOCK,
    api_errors as E,
    assert_market_exposure,
    expected_posture,
    factories as f,
    get_success_data,
    pct_of,
    validate_error,
    validate_paginated,
)

# PRD 3.1 requires a positive rental_fee_cents under the RENTAL arrangement, so
# the flat building fee is always a known term of the promoter/venue split.
RENTAL_FEE_CENTS = 100_000

# Identifiers that resolve to no row in any collection.
MISSING_TIER_ID = "00000000-0000-4000-8000-000000000011"
MISSING_SHOW_ID = "00000000-0000-4000-8000-000000000007"
MISSING_SETTLEMENT_ID = "00000000-0000-4000-8000-000000000013"
MISSING_BUDGET_LINE_ID = "00000000-0000-4000-8000-000000000009"
MISSING_SHOW_ID_FOR_OFFER = "00000000-0000-4000-8000-000000000016"
MISSING_ARTIST_ID = "00000000-0000-4000-8000-000000000005"

WEEKLY_WINDOWS = [
    {
        "event_at": "2026-12-02T02:00:00.000Z",
        "load_in_at": "2026-12-01T14:00:00.000Z",
        "load_out_at": "2026-12-02T08:00:00.000Z",
        "announce_at": DEFAULT_CLOCK,
    },
    {
        "event_at": "2026-12-09T02:00:00.000Z",
        "load_in_at": "2026-12-08T14:00:00.000Z",
        "load_out_at": "2026-12-09T08:00:00.000Z",
        "announce_at": DEFAULT_CLOCK,
    },
    {
        "event_at": "2026-12-16T02:00:00.000Z",
        "load_in_at": "2026-12-15T14:00:00.000Z",
        "load_out_at": "2026-12-16T08:00:00.000Z",
        "announce_at": DEFAULT_CLOCK,
    },
    {
        "event_at": "2026-12-23T02:00:00.000Z",
        "load_in_at": "2026-12-22T14:00:00.000Z",
        "load_out_at": "2026-12-23T08:00:00.000Z",
        "announce_at": DEFAULT_CLOCK,
    },
]


def _act(build, label, ordinal):
    return build.artist(
        name=f"{label} Act {ordinal}",
        agency="Meridian Talent",
        tier="THEATER",
        historical_sellthrough_pct=60.00,
        withholding_pct=0,
    )


def _zero_fee_hall(build, label, limit_cents, gross_capacity=1_000):
    market = build.market(
        name=f"{label} Market",
        region_code="AGG",
        guarantee_exposure_limit_cents=limit_cents,
    )
    venue = build.venue(
        market["id"],
        name=f"{label} Hall",
        gross_capacity=gross_capacity,
        facility_fee_cents_per_ticket=0,
        ticket_tax_pct=0,
    )
    return market, venue


def _rental_show(build, artist_id, venue_id, window):
    return build.show(
        artist_id,
        venue_id,
        venue_arrangement="RENTAL",
        rental_fee_cents=RENTAL_FEE_CENTS,
        **window,
    )


# ---------------------------------------------------------------------------
# Ceilings that only bind in aggregate
# ---------------------------------------------------------------------------


def _four_submitted_offers(build, guarantee_cents=400_000, limit_cents=1_000_000):
    """Four dates a week apart, each carrying one SUBMITTED flat-guarantee offer."""
    market, venue = _zero_fee_hall(build, "Agg", limit_cents)
    dates = []
    for ordinal, window in enumerate(WEEKLY_WINDOWS, start=1):
        artist = _act(build, "Agg", ordinal)
        show = _rental_show(build, artist["id"], venue["id"], window)
        offer = build.submitted_offer(
            show["id"],
            deal_structure="FLAT_GUARANTEE",
            guarantee_cents=guarantee_cents,
            deposit_cents=0,
            expense_cap_cents=400_000,
        )
        dates.append({"artist": artist, "show": show, "offer": offer})
    assert build.read_market(market["id"])["committed_guarantee_cents"] == 0
    return market, venue, dates


def _accept(build, date):
    return get_success_data(
        build.api.accept_offer(date["offer"]["id"], build.artist_rep(date["artist"]["id"]))
    )


def test_a_third_affordable_guarantee_breaks_the_limit_only_in_aggregate(build, api):
    """PRD 3.3: "The fourth is **market exposure**: the market's current
    `committed_guarantee_cents` plus this offer's `guarantee_cents` must not exceed the applicable
    ceiling, and equality with the ceiling passes." ... "Exceeding it yields
    `ERR_MARKET_EXPOSURE_EXCEEDED` (HTTP 402)."

    Design: Corner/validations/individually_affordable_guarantees_collectively_break_the_market_limit
    """
    market, _venue, dates = _four_submitted_offers(build)

    _accept(build, dates[0])
    assert_market_exposure(build.read_market(market["id"]), 400_000, 40.00, "OPEN")
    assert expected_posture(40.00) == "OPEN"

    _accept(build, dates[1])
    assert_market_exposure(build.read_market(market["id"]), 800_000, 80.00, "WATCH")
    assert pct_of(800_000, 1_000_000) == pytest.approx(80.00, abs=0.01)

    validate_error(
        api.accept_offer(dates[2]["offer"]["id"], build.artist_rep(dates[2]["artist"]["id"])),
        E.ERR_MARKET_EXPOSURE_EXCEEDED,
        expected_status=402,
    )

    assert_market_exposure(build.read_market(market["id"]), 800_000, 80.00, "WATCH")
    assert build.read_offer(dates[2]["offer"]["id"])["status"] == "SUBMITTED"
    assert build.read_show(dates[2]["show"]["id"])["show_status"] == "PLANNED"
    assert build.read_show(dates[2]["show"]["id"])["committed_guarantee_cents"] == 0


def test_a_show_scoped_override_re_bases_the_ceiling_for_that_one_acceptance(build, api):
    """PRD 3.3: "The applicable ceiling is the show's own `exposure_override_limit_cents` when
    that field is non-null, and the market's `guarantee_exposure_limit_cents` otherwise."

    Design: Corner/validations/individually_affordable_guarantees_collectively_break_the_market_limit
    """
    market, _venue, dates = _four_submitted_offers(build)
    _accept(build, dates[0])
    _accept(build, dates[1])

    get_success_data(
        api.grant_exposure_override(
            dates[2]["show"]["id"],
            build.risk,
            exposure_override_limit_cents=1_200_000,
            exposure_override_justification="the routing is worth carrying past the market limit",
        )
    )
    accepted = _accept(build, dates[2])
    assert accepted["status"] == "ACCEPTED"

    assert_market_exposure(build.read_market(market["id"]), 1_200_000, 120.00, "FROZEN")
    assert build.read_show(dates[2]["show"]["id"])["show_status"] == "CONFIRMED"


def test_an_acceptance_into_a_frozen_market_fails_on_posture_not_on_exposure(build, api):
    """PRD 3.3: "The third is **market posture**: if the market's `risk_posture` is `FROZEN`, the
    acceptance is rejected with `ERR_MARKET_POSTURE_FROZEN` (HTTP 409)." ... "it is the *next*
    acceptance that fails, and it fails on posture rather than on exposure."

    Design: Corner/validations/individually_affordable_guarantees_collectively_break_the_market_limit
    """
    market, _venue, dates = _four_submitted_offers(build)
    _accept(build, dates[0])
    _accept(build, dates[1])
    get_success_data(
        api.grant_exposure_override(
            dates[2]["show"]["id"],
            build.risk,
            exposure_override_limit_cents=1_200_000,
            exposure_override_justification="the routing is worth carrying past the market limit",
        )
    )
    _accept(build, dates[2])
    assert build.read_market(market["id"])["risk_posture"] == "FROZEN"

    validate_error(
        api.accept_offer(dates[3]["offer"]["id"], build.artist_rep(dates[3]["artist"]["id"])),
        E.ERR_MARKET_POSTURE_FROZEN,
        expected_status=409,
    )

    assert_market_exposure(build.read_market(market["id"]), 1_200_000, 120.00, "FROZEN")
    assert build.read_offer(dates[3]["offer"]["id"])["status"] == "SUBMITTED"
    assert build.read_show(dates[3]["show"]["id"])["show_status"] == "PLANNED"


def test_tier_allocations_aggregate_against_the_venues_gross_capacity(build, api):
    """PRD 3.4: "the sum of `allocation_qty` across the show's tiers, counting the tier being
    created, may not exceed the venue's `gross_capacity`, or the create is rejected with
    `ERR_VENUE_CAPACITY_EXCEEDED` (HTTP 422)"

    Design: Corner/validations/individually_affordable_guarantees_collectively_break_the_market_limit
    """
    _market, venue = _zero_fee_hall(build, "Agg", 1_000_000, gross_capacity=1_000)
    show = _rental_show(build, _act(build, "Agg", 1)["id"], venue["id"], WEEKLY_WINDOWS[0])

    build.tier(show["id"], tier_name="FLOOR", price_cents=6_000, allocation_qty=400)
    build.tier(show["id"], tier_name="LOWER", price_cents=5_000, allocation_qty=400)

    validate_error(
        api.create_ticket_tier(
            f.ticket_tier_payload(
                show["id"], tier_name="UPPER", price_cents=3_000, allocation_qty=400
            ),
            build.buyer,
        ),
        E.ERR_VENUE_CAPACITY_EXCEEDED,
        expected_status=422,
    )

    fits = get_success_data(
        api.create_ticket_tier(
            f.ticket_tier_payload(
                show["id"], tier_name="UPPER", price_cents=3_000, allocation_qty=200
            ),
            build.buyer,
        ),
        expected_status=201,
    )
    assert fits["allocation_qty"] == 200

    rows, meta = validate_paginated(api.list_ticket_tiers(build.buyer, show_id=show["id"]))
    assert meta["total_count"] == 3
    assert sum(row["allocation_qty"] for row in rows) == venue["gross_capacity"]


# ---------------------------------------------------------------------------
# Rules that only bite the configuration naming them
# ---------------------------------------------------------------------------


def _signed_settlement_due(build, guarantee_cents):
    """A signed rental settlement whose ``payment_due_cents`` is ``guarantee_cents``.

    Two hundred 5,000-cent seats gross 1,000,000; the only deduction is the
    2.5 percent card charge, so the adjusted gross is 975,000.  The single budget
    line is never invoiced and is not artist-deductible, so no expense is
    recognised and the flat guarantee falls straight through to the artist.
    """
    market, venue = _zero_fee_hall(build, "Cond", 5_000_000)
    artist = _act(build, "Cond", 1)
    show = _rental_show(build, artist["id"], venue["id"], WEEKLY_WINDOWS[0])
    build.accepted_offer(
        show["id"],
        artist["id"],
        deal_structure="FLAT_GUARANTEE",
        guarantee_cents=guarantee_cents,
        deposit_cents=0,
        expense_cap_cents=500_000,
    )
    tier = build.tier(show["id"], tier_name="GA", price_cents=5_000, allocation_qty=200)
    get_success_data(build.api.put_show_on_sale(show["id"], build.buyer))
    build.sell(tier["id"], 200)
    build.budget_line(
        show["id"],
        category="PRODUCTION",
        description="backline the promoter never invoiced",
        budgeted_cents=100_000,
        is_artist_deductible=False,
    )
    build.set_clock(WEEKLY_WINDOWS[0]["event_at"])
    get_success_data(build.api.perform_show(show["id"], build.accountant))

    settlement = build.signed_settlement(show["id"], artist["id"])
    assert settlement["status"] == "ARTIST_SIGNED"
    assert settlement["adjusted_gross_cents"] == 975_000
    assert settlement["total_settlement_expense_cents"] == 0
    assert settlement["payment_due_cents"] == guarantee_cents
    assert settlement["venue_share_cents"] == RENTAL_FEE_CENTS
    assert settlement["promoter_net_cents"] == 975_000 - guarantee_cents - RENTAL_FEE_CENTS
    return {"market": market, "artist": artist, "show": show, "settlement": settlement}


def test_a_cash_payment_one_cent_above_the_limit_is_refused(build, api):
    """PRD 3.8: "Cash is capped: when `payment_method` is `CASH`, the settlement's
    `payment_due_cents` may not exceed 1,000,000 cents — ten thousand dollars — or the payment is
    rejected with `ERR_CASH_PAYMENT_LIMIT` (HTTP 422)."

    Design: Corner/validations/cash_limit_and_deal_coherence_apply_only_to_the_configuration_that_names_them
    """
    world = _signed_settlement_due(build, 1_000_001)
    settlement = world["settlement"]
    assert settlement["promoter_net_cents"] == -125_001

    validate_error(
        api.pay_settlement(
            settlement["id"],
            build.accountant_two,
            payment_method="CASH",
            payment_reference="CASH-OVER-BY-ONE",
        ),
        E.ERR_CASH_PAYMENT_LIMIT,
        expected_status=422,
    )

    unchanged = build.read_settlement(settlement["id"])
    assert unchanged["status"] == "ARTIST_SIGNED"
    assert unchanged["paid_at"] is None
    assert unchanged["payment_method"] is None
    assert build.read_show(world["show"]["id"])["show_status"] == "PERFORMED"


def test_the_same_settlement_the_cash_cap_refused_pays_by_wire(build, api):
    """PRD 3.8: "Wire and cheque payments carry no such cap."

    Design: Corner/validations/cash_limit_and_deal_coherence_apply_only_to_the_configuration_that_names_them
    """
    world = _signed_settlement_due(build, 1_000_001)
    settlement = world["settlement"]
    validate_error(
        api.pay_settlement(
            settlement["id"],
            build.accountant_two,
            payment_method="CASH",
            payment_reference="CASH-OVER-BY-ONE",
        ),
        E.ERR_CASH_PAYMENT_LIMIT,
        expected_status=422,
    )

    paid = get_success_data(
        api.pay_settlement(
            settlement["id"],
            build.accountant_two,
            payment_method="WIRE",
            payment_reference="WIRE-CD-0001",
        )
    )
    assert paid["status"] == "PAID"
    assert paid["payment_method"] == "WIRE"
    assert paid["payment_due_cents"] == 1_000_001
    assert build.read_show(world["show"]["id"])["show_status"] == "SETTLED"


def test_a_cash_payment_at_exactly_the_limit_is_paid(build, api):
    """PRD 3.8: "Cash is capped: when `payment_method` is `CASH`, the settlement's
    `payment_due_cents` may not exceed 1,000,000 cents — ten thousand dollars — or the payment is
    rejected with `ERR_CASH_PAYMENT_LIMIT` (HTTP 422)."

    Design: Corner/validations/cash_limit_and_deal_coherence_apply_only_to_the_configuration_that_names_them
    """
    world = _signed_settlement_due(build, 1_000_000)
    assert world["settlement"]["promoter_net_cents"] == -125_000

    paid = get_success_data(
        api.pay_settlement(
            world["settlement"]["id"],
            build.accountant_two,
            payment_method="CASH",
            payment_reference="CASH-CD-0002",
        )
    )
    assert paid["status"] == "PAID"
    assert paid["payment_method"] == "CASH"
    assert paid["payment_due_cents"] == 1_000_000
    assert build.read_show(world["show"]["id"])["show_status"] == "SETTLED"


def _planned_show_for_offers(build):
    _market, venue = _zero_fee_hall(build, "Cond", 5_000_000)
    artist = _act(build, "Cond", 3)
    return _rental_show(build, artist["id"], venue["id"], WEEKLY_WINDOWS[2])


def test_a_flat_guarantee_offer_may_not_carry_a_versus_percentage(build, api):
    """PRD 3.2: "Deal terms must be coherent with the structure chosen, and this check applies
    both when the offer is written and when the artist side counters it. `FLAT_GUARANTEE` forbids
    both `versus_pct` and `backend_split_artist_pct`."

    Design: Corner/validations/cash_limit_and_deal_coherence_apply_only_to_the_configuration_that_names_them
    """
    show = _planned_show_for_offers(build)

    validate_error(
        api.create_offer(
            f.offer_payload(
                show["id"],
                show["version"],
                deal_structure="FLAT_GUARANTEE",
                guarantee_cents=400_000,
                deposit_cents=0,
                expense_cap_cents=500_000,
                versus_pct=85.00,
            ),
            build.buyer,
        ),
        E.ERR_DEAL_TERMS_INCOHERENT,
        expected_status=422,
    )

    _rows, meta = validate_paginated(api.list_offers(build.buyer, show_id=show["id"]))
    assert meta["total_count"] == 0


def test_a_versus_offer_must_carry_a_versus_percentage(build, api):
    """PRD 3.2: "`VERSUS` requires `versus_pct` to be present and greater than 0 and forbids
    `backend_split_artist_pct`."

    Design: Corner/validations/cash_limit_and_deal_coherence_apply_only_to_the_configuration_that_names_them
    """
    show = _planned_show_for_offers(build)

    validate_error(
        api.create_offer(
            f.offer_payload(
                show["id"],
                show["version"],
                deal_structure="VERSUS",
                guarantee_cents=400_000,
                deposit_cents=0,
                expense_cap_cents=500_000,
            ),
            build.buyer,
        ),
        E.ERR_DEAL_TERMS_INCOHERENT,
        expected_status=422,
    )

    _rows, meta = validate_paginated(api.list_offers(build.buyer, show_id=show["id"]))
    assert meta["total_count"] == 0


def test_a_deposit_larger_than_the_guarantee_is_incoherent_in_every_structure(build, api):
    """PRD 3.2: "In every structure `deposit_cents` may not exceed `guarantee_cents`, and
    `expense_cap_cents`, when supplied, must be greater than 0."

    Design: Corner/validations/cash_limit_and_deal_coherence_apply_only_to_the_configuration_that_names_them
    """
    show = _planned_show_for_offers(build)

    validate_error(
        api.create_offer(
            f.offer_payload(
                show["id"],
                show["version"],
                deal_structure="FLAT_GUARANTEE",
                guarantee_cents=400_000,
                deposit_cents=500_000,
                expense_cap_cents=500_000,
            ),
            build.buyer,
        ),
        E.ERR_DEAL_TERMS_INCOHERENT,
        expected_status=422,
    )

    _rows, meta = validate_paginated(api.list_offers(build.buyer, show_id=show["id"]))
    assert meta["total_count"] == 0


def test_a_coherent_versus_offer_keeps_its_percentage_and_leaves_the_backend_null(build, api):
    """PRD 3.2: "On success the new offer is created in status `DRAFT` with `round_index` 1, and
    every **other** offer on the same show whose status is `SUBMITTED` or `COUNTERED` is moved to
    `SUPERSEDED`."

    Design: Corner/validations/cash_limit_and_deal_coherence_apply_only_to_the_configuration_that_names_them
    """
    show = _planned_show_for_offers(build)

    created = get_success_data(
        api.create_offer(
            f.offer_payload(
                show["id"],
                show["version"],
                deal_structure="VERSUS",
                guarantee_cents=400_000,
                deposit_cents=0,
                expense_cap_cents=500_000,
                versus_pct=85.00,
            ),
            build.buyer,
        ),
        expected_status=201,
    )
    assert created["status"] == "DRAFT"
    assert created["round_index"] == 1
    assert created["deal_structure"] == "VERSUS"
    assert created["versus_pct"] == pytest.approx(85.00, abs=0.01)
    # PRD 3.2: each of the two conditional terms "defaults to 0".
    assert created["backend_split_artist_pct"] == 0

    rows, meta = validate_paginated(api.list_offers(build.buyer, show_id=show["id"]))
    assert meta["total_count"] == 1
    assert rows[0]["id"] == created["id"]


# ---------------------------------------------------------------------------
# The fixed order: identity, authorisation, body, existence, then everything else
# ---------------------------------------------------------------------------


def _ordering_world(build):
    """One market, one act, one hall, one PLANNED show and one budget line.

    An exposure override is granted at the end purely to move the show's
    ``version`` on, so the version captured beforehand is genuinely stale.
    """
    market, venue = _zero_fee_hall(build, "Order", 5_000_000)
    artist = _act(build, "Order", 1)
    show = _rental_show(build, artist["id"], venue["id"], WEEKLY_WINDOWS[0])
    line = build.budget_line(
        show["id"],
        category="PRODUCTION",
        description="staging for the December date",
        budgeted_cents=250_000,
        is_artist_deductible=True,
    )
    stale_version = build.read_show(show["id"])["version"]
    get_success_data(
        build.api.grant_exposure_override(
            show["id"],
            build.risk,
            exposure_override_limit_cents=6_000_000,
            exposure_override_justification="lift the ceiling so the show's version moves on",
        )
    )
    assert build.read_show(show["id"])["version"] == stale_version + 1
    return {
        "market": market,
        "venue": venue,
        "artist": artist,
        "show": show,
        "line": line,
        "stale_version": stale_version,
    }


def test_a_missing_tier_answers_before_the_inventory_check(build, api):
    """PRD 2.9: "Where several rules could reject the same call, they are evaluated in a fixed
    order and the **first** violated rule determines the response." The order puts "Existence of
    every referenced resource" at 4 and "tier inventory sufficiency (`ERR_INSUFFICIENT_TIER_INVENTORY`)"
    among the domain checks at 10.

    Design: Corner/validations/existence_and_authorization_checks_run_before_state_and_amount_checks
    """
    _ordering_world(build)

    validate_error(
        api.create_ticket_hold(
            f.ticket_hold_payload(
                MISSING_TIER_ID, kind="PROMOTER_HOLD", qty=999_999, holder="nowhere at all"
            ),
            build.buyer,
        ),
        E.ERR_TICKET_TIER_NOT_FOUND,
        expected_status=404,
    )


def test_a_missing_show_answers_before_the_invoice_cross_reference_check(build, api):
    """PRD 2.11: "The same codes apply to identifiers supplied in a request body or as a list
    filter rather than in the path." A missing show yields `ERR_SHOW_NOT_FOUND`, and existence sits
    at 4 in the order while "invoice-to-budget-line coherence (`ERR_BUDGET_LINE_SHOW_MISMATCH`)"
    is the first of the domain checks at 10.

    Design: Corner/validations/existence_and_authorization_checks_run_before_state_and_amount_checks
    """
    world = _ordering_world(build)

    validate_error(
        api.create_vendor_invoice(
            f.vendor_invoice_payload(
                MISSING_SHOW_ID,
                world["line"]["id"],
                amount_cents=100_000,
                vendor_name="Nowhere Staging",
                documentation_ref="PKT-ORD-01",
            ),
            build.accountant,
        ),
        E.ERR_SHOW_NOT_FOUND,
        expected_status=404,
    )

    _rows, meta = validate_paginated(
        api.list_vendor_invoices(build.accountant, show_id=world["show"]["id"])
    )
    assert meta["total_count"] == 0


def test_a_missing_settlement_answers_before_the_state_check(build, api):
    """PRD 2.9: "4. Existence of every referenced resource, in the order market, artist, venue,
    show, offer, budget line, vendor invoice, ticket tier, ticket hold, settlement, cancellation
    event — each with its own error code, listed in §2.11." State legality is rule 7.

    Design: Corner/validations/existence_and_authorization_checks_run_before_state_and_amount_checks
    """
    _ordering_world(build)

    validate_error(
        api.calculate_settlement(MISSING_SETTLEMENT_ID, build.accountant),
        E.ERR_SETTLEMENT_NOT_FOUND,
        expected_status=404,
    )


def test_a_missing_budget_line_answers_before_the_variance_cap_check(build, api):
    """PRD 2.11: "A missing `budget_line_id` on an invoice body or filter yields
    `ERR_BUDGET_LINE_NOT_FOUND`, and a missing `ticket_tier_id` on a hold body or filter yields
    `ERR_TICKET_TIER_NOT_FOUND`."

    Design: Corner/validations/existence_and_authorization_checks_run_before_state_and_amount_checks
    """
    world = _ordering_world(build)

    validate_error(
        api.decide_variance(
            MISSING_BUDGET_LINE_ID,
            build.risk,
            decision="REJECT",
            approved_cap_cents=1,
            variance_justification="a cap that would be invalid on a real line",
        ),
        E.ERR_BUDGET_LINE_NOT_FOUND,
        expected_status=404,
    )

    untouched = build.read_budget_line(world["line"]["id"])
    assert untouched["variance_status"] == "WITHIN_TOLERANCE"
    assert untouched["approved_cap_cents"] is None
    assert untouched["variance_decided_by_user_id"] is None


def test_a_missing_show_answers_before_the_stale_view_check(build, api):
    """PRD 2.9: "6. Stale-view rejection — `ERR_STALE_SHOW_VERSION`." Existence of every
    referenced resource is rule 4, and "No later rule is evaluated once one has fired, and no side
    effect of the operation runs."

    Design: Corner/validations/existence_and_authorization_checks_run_before_state_and_amount_checks
    """
    world = _ordering_world(build)
    stale = world["stale_version"]

    validate_error(
        api.create_offer(
            f.offer_payload(
                MISSING_SHOW_ID_FOR_OFFER,
                stale,
                deal_structure="FLAT_GUARANTEE",
                guarantee_cents=400_000,
                deposit_cents=0,
                expense_cap_cents=500_000,
            ),
            build.buyer,
        ),
        E.ERR_SHOW_NOT_FOUND,
        expected_status=404,
    )

    # The very same stale version, aimed at a show that does exist, is what
    # ERR_STALE_SHOW_VERSION is for — which is how we know the version was stale.
    validate_error(
        api.create_offer(
            f.offer_payload(
                world["show"]["id"],
                stale,
                deal_structure="FLAT_GUARANTEE",
                guarantee_cents=400_000,
                deposit_cents=0,
                expense_cap_cents=500_000,
            ),
            build.buyer,
        ),
        E.ERR_STALE_SHOW_VERSION,
        expected_status=412,
    )

    _rows, meta = validate_paginated(api.list_offers(build.buyer, show_id=world["show"]["id"]))
    assert meta["total_count"] == 0


def test_role_authorisation_answers_before_body_well_formedness(build, api):
    """PRD 2.9: "2. Role recognition and endpoint authorisation — `ERR_ROLE_FORBIDDEN`.
    3. Request-body well-formedness — `ERR_INVALID_REQUEST`. Every required field must be present,
    every enum-valued field must hold a declared member, every `_cents` field must be an integer
    that is not negative"

    Design: Corner/validations/existence_and_authorization_checks_run_before_state_and_amount_checks
    """
    _ordering_world(build)

    validate_error(
        api.create_market(
            f.market_payload(
                name="Never Opened", region_code="NOPE", guarantee_exposure_limit_cents=-500
            ),
            build.buyer,
        ),
        E.ERR_ROLE_FORBIDDEN,
        expected_status=403,
    )

    _rows, meta = validate_paginated(api.list_markets(build.risk))
    assert meta["total_count"] == 1


def test_body_well_formedness_answers_before_referenced_existence(build, api):
    """PRD 2.9: "3. Request-body well-formedness — `ERR_INVALID_REQUEST`. Every required field
    must be present, every enum-valued field must hold a declared member, every `_cents` field
    must be an integer that is not negative, every `_pct` field must be a number between 0 and 100
    inclusive, every `_at` field must be a valid ISO 8601 UTC timestamp, and every quantity field
    must be an integer of at least 1."

    Design: Corner/validations/existence_and_authorization_checks_run_before_state_and_amount_checks
    """
    world = _ordering_world(build)

    validate_error(
        api.create_show(
            f.show_payload(
                MISSING_ARTIST_ID,
                world["venue"]["id"],
                event_at="not-a-timestamp",
                load_in_at=WEEKLY_WINDOWS[1]["load_in_at"],
                load_out_at=WEEKLY_WINDOWS[1]["load_out_at"],
                announce_at=DEFAULT_CLOCK,
                venue_arrangement="RENTAL",
                rental_fee_cents=RENTAL_FEE_CENTS,
            ),
            build.buyer,
        ),
        E.ERR_INVALID_REQUEST,
        expected_status=400,
    )

    _rows, meta = validate_paginated(api.list_shows(build.buyer, venue_id=world["venue"]["id"]))
    assert meta["total_count"] == 1
