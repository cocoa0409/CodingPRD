"""Threshold bands, stale-view rejection on the two guarded writes, and the
absence of read-after-write staleness anywhere in the service.

Every test builds its own world through the declared endpoints: the database is
empty when the test starts.
"""

import pytest

from test_helpers import (
    ACCOUNTANT_BOB,
    api_errors as E,
    assert_market_exposure,
    assert_tier_inventory_conserved,
    assert_timestamp_equals,
    assert_unchanged,
    assert_version_bumped_by,
    comp_allowance_for,
    expected_posture,
    factories,
    get_success_data,
    pct_of,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import DEFAULT_CLOCK

# ---------------------------------------------------------------------------
# The band market: a deliberately small ceiling so that whole-cent guarantees
# land on exact utilisation percentages.
# ---------------------------------------------------------------------------

BAND_LIMIT_CENTS = 1_000_000
BAND_GUARANTEES_CENTS = [700_000, 200_000, 99_000, 1_000, 1_000]
BAND_WINDOWS = [
    ("2026-12-02T02:00:00.000Z", "2026-12-01T14:00:00.000Z", "2026-12-02T08:00:00.000Z"),
    ("2026-12-09T02:00:00.000Z", "2026-12-08T14:00:00.000Z", "2026-12-09T08:00:00.000Z"),
    ("2026-12-16T02:00:00.000Z", "2026-12-15T14:00:00.000Z", "2026-12-16T08:00:00.000Z"),
    ("2026-12-23T02:00:00.000Z", "2026-12-22T14:00:00.000Z", "2026-12-23T08:00:00.000Z"),
    ("2026-12-30T02:00:00.000Z", "2026-12-29T14:00:00.000Z", "2026-12-30T08:00:00.000Z"),
]

# The four cumulative utilisation bands, in the order the walk reaches them.
BAND_WALK_UP = [
    (700_000, 70.00, "OPEN"),
    (900_000, 90.00, "WATCH"),
    (999_000, 99.90, "RESTRICTED"),
    (1_000_000, 100.00, "FROZEN"),
]

# An announce instant already behind the opening clock, so that going on sale
# never needs the clock moved.
ANNOUNCE_BEHIND_CLOCK = "2026-07-01T00:00:00.000Z"


def _band_market_world(build):
    """Five acts, five shows on disjoint load windows, five SUBMITTED offers.

    Each show carries its own act so that no artist-routing buffer applies, and
    the load windows are a week apart so that no venue occupancy overlaps.
    """
    market = build.market(
        name="Band Market",
        region_code="BD",
        guarantee_exposure_limit_cents=BAND_LIMIT_CENTS,
    )
    venue = build.venue(
        market["id"],
        name="Band Hall",
        gross_capacity=500,
        facility_fee_cents_per_ticket=0,
        ticket_tax_pct=0,
    )
    artists, shows, offers = [], [], []
    for index, (event_at, load_in_at, load_out_at) in enumerate(BAND_WINDOWS):
        artist = build.artist(
            name=f"Band Act {index + 1}",
            agency="Bnd Talent",
            tier="THEATER",
            historical_sellthrough_pct=60.00 + index,
            withholding_pct=0,
        )
        show = build.show(
            artist["id"],
            venue["id"],
            event_at=event_at,
            load_in_at=load_in_at,
            load_out_at=load_out_at,
            announce_at=ANNOUNCE_BEHIND_CLOCK,
            venue_arrangement="RENTAL",
            rental_fee_cents=500_000,
        )
        offer = build.submitted_offer(
            show["id"],
            expected_show_version=show["version"],
            deal_structure="FLAT_GUARANTEE",
            guarantee_cents=BAND_GUARANTEES_CENTS[index],
            deposit_cents=0,
            expense_cap_cents=BAND_GUARANTEES_CENTS[index],
        )
        artists.append(artist)
        shows.append(show)
        offers.append(offer)
    return {
        "market": market,
        "venue": venue,
        "artists": artists,
        "shows": shows,
        "offers": offers,
    }


def _accept(api, build, world, index):
    """Accept the offer on show ``index`` as that show's own artist rep."""
    return api.accept_offer(
        world["offers"][index]["id"], build.artist_rep(world["artists"][index]["id"])
    )


def _walk_market_to_frozen(api, build, world):
    """Accept the first four offers, landing the market at exactly 100.00."""
    for index in range(4):
        validate_success(_accept(api, build, world, index))
    return build.read_market(world["market"]["id"])


def _comp_ceiling_show(build):
    """A 100-seat ON_SALE house, so the comp allowance is exactly three seats."""
    return build.on_sale_show(
        tiers=[{"tier_name": "GA", "price_cents": 5_000, "allocation_qty": 100}],
        guarantee_cents=200_000,
        deposit_cents=0,
        expense_cap_cents=200_000,
        guarantee_exposure_limit_cents=1_000_000,
        gross_capacity=500,
        facility_fee_cents_per_ticket=0,
        ticket_tax_pct=0,
        market_name="Band Market",
        venue_name="Band Hall",
        artist_name="Band Act One",
        show={"rental_fee_cents": 500_000},
    )


def _comps_at_the_ceiling(api, build):
    """Drive the house to exactly three comp seats and return the context."""
    ctx = _comp_ceiling_show(build)
    tier = ctx["tiers"][0]
    ctx["label_comps"] = validate_success(
        api.create_ticket_hold(
            factories.ticket_hold_payload(
                tier["id"], kind="COMP", qty=2, holder="Label comps"
            ),
            build.buyer,
        ),
        201,
    )
    ctx["press_comp"] = validate_success(
        api.create_ticket_hold(
            factories.ticket_hold_payload(
                tier["id"], kind="COMP", qty=1, holder="Press comp"
            ),
            build.buyer,
        ),
        201,
    )
    return ctx


def _occ_planned_show(build):
    """A PLANNED show whose version is the only counter moving in the test."""
    market = build.market(
        name="OCC Market", region_code="OC", guarantee_exposure_limit_cents=5_000_000
    )
    venue = build.venue(
        market["id"],
        name="OCC Hall",
        gross_capacity=500,
        facility_fee_cents_per_ticket=0,
        ticket_tax_pct=0,
    )
    artist = build.artist(
        name="OCC Act",
        agency="Occ Talent",
        tier="THEATER",
        historical_sellthrough_pct=66.00,
        withholding_pct=0,
    )
    show = build.show(
        artist["id"],
        venue["id"],
        event_at="2026-12-02T02:00:00.000Z",
        load_in_at="2026-12-01T14:00:00.000Z",
        load_out_at="2026-12-02T08:00:00.000Z",
        announce_at=ANNOUNCE_BEHIND_CLOCK,
        venue_arrangement="RENTAL",
        rental_fee_cents=500_000,
    )
    return {"market": market, "venue": venue, "artist": artist, "show": show}


def _flat_offer_payload(show_id, expected_show_version, **overrides):
    return factories.offer_payload(
        show_id,
        expected_show_version,
        deal_structure="FLAT_GUARANTEE",
        guarantee_cents=100_000,
        deposit_cents=0,
        expense_cap_cents=100_000,
        **overrides,
    )


def _occ_on_sale_show(build):
    """A CONFIRMED show put on sale with one 200-seat GA tier at 5000."""
    return build.on_sale_show(
        tiers=[{"tier_name": "GA", "price_cents": 5_000, "allocation_qty": 200}],
        guarantee_cents=100_000,
        deposit_cents=0,
        expense_cap_cents=100_000,
        guarantee_exposure_limit_cents=5_000_000,
        gross_capacity=500,
        facility_fee_cents_per_ticket=0,
        ticket_tax_pct=0,
        market_name="OCC Market",
        venue_name="OCC Hall",
        artist_name="OCC Act",
        show={"rental_fee_cents": 500_000},
    )


def _now_world(build):
    """A PLANNED show carrying one SUBMITTED flat-guarantee offer of 200000.

    The clock is never moved after this point, so anything that only appears
    once time passes is a defect rather than a delay.
    """
    market = build.market(
        name="Now Market", region_code="NW", guarantee_exposure_limit_cents=5_000_000
    )
    venue = build.venue(
        market["id"],
        name="Now Hall",
        gross_capacity=500,
        facility_fee_cents_per_ticket=0,
        ticket_tax_pct=0,
    )
    artist = build.artist(
        name="Now Act",
        agency="Now Talent",
        tier="THEATER",
        historical_sellthrough_pct=64.00,
        withholding_pct=0,
    )
    show = build.show(
        artist["id"],
        venue["id"],
        event_at="2026-12-02T02:00:00.000Z",
        load_in_at="2026-12-01T14:00:00.000Z",
        load_out_at="2026-12-02T08:00:00.000Z",
        announce_at=ANNOUNCE_BEHIND_CLOCK,
        venue_arrangement="RENTAL",
        rental_fee_cents=500_000,
    )
    offer = build.submitted_offer(
        show["id"],
        expected_show_version=show["version"],
        deal_structure="FLAT_GUARANTEE",
        guarantee_cents=200_000,
        deposit_cents=0,
        expense_cap_cents=200_000,
    )
    return {
        "market": market,
        "venue": venue,
        "artist": artist,
        "show": show,
        "offer": offer,
    }


def _now_confirmed(api, build):
    """``_now_world`` with the offer accepted, so the show is CONFIRMED."""
    ctx = _now_world(build)
    ctx["accepted_offer"] = get_success_data(
        api.accept_offer(ctx["offer"]["id"], build.artist_rep(ctx["artist"]["id"]))
    )
    return ctx


def _now_on_sale_with_one_sale(api, build):
    """``_now_confirmed`` plus a 100-seat GA tier, on sale, with 10 seats sold."""
    ctx = _now_confirmed(api, build)
    tier = build.tier(
        ctx["show"]["id"], tier_name="GA", price_cents=5_000, allocation_qty=100
    )
    get_success_data(api.put_show_on_sale(ctx["show"]["id"], build.buyer))
    ctx["tier"] = build.read_tier(tier["id"])
    ctx["sale"] = get_success_data(api.record_sales(tier["id"], build.buyer, qty=10))
    return ctx


# ---------------------------------------------------------------------------
# Cumulative exposure bands
# ---------------------------------------------------------------------------


def test_exposure_utilization_bands_fire_at_their_inclusive_boundaries(api, build):
    """PRD.md 3.3: "`risk_posture` is then banded from that **rounded** percentage:
    `OPEN` when it is at most 70, `WATCH` when it is greater than 70 and at most
    90, `RESTRICTED` when it is greater than 90 and strictly below 100, and
    `FROZEN` at 100 or above. The boundaries are inclusive on the low side of
    each band, so a market sitting at exactly 70.00 is still `OPEN` and one at
    exactly 90.00 is still `WATCH`."

    Design: Corner/cross-cutting complexity layers/cumulative_exposure_bands_and_instantaneous_variance_bands_fire_at_their_boundaries
    """
    world = _band_market_world(build)
    assert_market_exposure(world["market"], 0, 0.00, "OPEN")

    for index, (committed_cents, utilization_pct, posture) in enumerate(BAND_WALK_UP):
        accepted = validate_success(_accept(api, build, world, index))
        assert accepted["status"] == "ACCEPTED"

        market = build.read_market(world["market"]["id"])
        assert_market_exposure(market, committed_cents, utilization_pct, posture)
        assert market["exposure_utilization_pct"] == pytest.approx(
            pct_of(committed_cents, BAND_LIMIT_CENTS), abs=0.01
        )
        assert market["risk_posture"] == expected_posture(
            market["exposure_utilization_pct"]
        )


def test_frozen_posture_blocks_the_next_acceptance(api, build):
    """PRD.md 3.3: "The third is **market posture**: if the market's `risk_posture`
    is `FROZEN`, the acceptance is rejected with `ERR_MARKET_POSTURE_FROZEN`
    (HTTP 409). The posture read here is the market's posture **before** this
    acceptance is applied."

    Design: Corner/cross-cutting complexity layers/cumulative_exposure_bands_and_instantaneous_variance_bands_fire_at_their_boundaries
    """
    world = _band_market_world(build)
    frozen_market = _walk_market_to_frozen(api, build, world)
    assert_market_exposure(frozen_market, 1_000_000, 100.00, "FROZEN")

    refused = _accept(api, build, world, 4)
    validate_error(refused, E.ERR_MARKET_POSTURE_FROZEN)

    assert build.read_offer(world["offers"][4]["id"])["status"] == "SUBMITTED"
    assert build.read_show(world["shows"][4]["id"])["show_status"] == "PLANNED"
    after = build.read_market(world["market"]["id"])
    assert_market_exposure(after, 1_000_000, 100.00, "FROZEN")
    assert after["version"] == frozen_market["version"]


def test_committed_exposure_walks_back_down_and_the_thawed_market_accepts_again(
    api, build
):
    """PRD.md 3.3: "Committed exposure is a strictly conserved quantity. Accepting
    an offer adds exactly the offer's `guarantee_cents` to the market's
    committed total, and each compensating operation — opening a cancellation
    event of either kind, or paying the settlement — subtracts exactly the same
    amount."

    Design: Corner/cross-cutting complexity layers/cumulative_exposure_bands_and_instantaneous_variance_bands_fire_at_their_boundaries
    """
    world = _band_market_world(build)
    _walk_market_to_frozen(api, build, world)
    validate_error(_accept(api, build, world, 4), E.ERR_MARKET_POSTURE_FROZEN)

    build.cancellation_event(world["shows"][3]["id"], kind="CANCELLED")
    assert_market_exposure(
        build.read_market(world["market"]["id"]), 999_000, 99.90, "RESTRICTED"
    )

    build.cancellation_event(world["shows"][2]["id"], kind="CANCELLED")
    assert_market_exposure(
        build.read_market(world["market"]["id"]), 900_000, 90.00, "WATCH"
    )

    accepted = validate_success(_accept(api, build, world, 4))
    assert accepted["status"] == "ACCEPTED"
    assert build.read_show(world["shows"][4]["id"])["show_status"] == "CONFIRMED"
    assert_market_exposure(
        build.read_market(world["market"]["id"]), 901_000, 90.10, "RESTRICTED"
    )


# ---------------------------------------------------------------------------
# The comp allowance ceiling
# ---------------------------------------------------------------------------


def test_comp_allowance_admits_the_ceiling_seat_and_refuses_the_next(api, build):
    """PRD.md 3.5: "The show's comp allowance in whole tickets is 3 percent of that
    total allocation, rounded half up. The show's current `comp_tickets_issued`
    plus the requested quantity must not exceed that allowance, or the request
    is rejected with `ERR_COMP_ALLOWANCE_EXCEEDED` (HTTP 422)."

    Design: Corner/cross-cutting complexity layers/cumulative_exposure_bands_and_instantaneous_variance_bands_fire_at_their_boundaries
    """
    ctx = _comp_ceiling_show(build)
    tier = ctx["tiers"][0]
    allowance = comp_allowance_for(tier["allocation_qty"])
    assert allowance == 3

    first = validate_success(
        api.create_ticket_hold(
            factories.ticket_hold_payload(
                tier["id"], kind="COMP", qty=2, holder="Label comps"
            ),
            build.buyer,
        ),
        201,
    )
    assert first["status"] == "HELD"
    after_first = build.read_tier(tier["id"])
    assert after_first["comp_qty"] == 2
    assert after_first["available_qty"] == 98

    second = validate_success(
        api.create_ticket_hold(
            factories.ticket_hold_payload(
                tier["id"], kind="COMP", qty=1, holder="Press comp"
            ),
            build.buyer,
        ),
        201,
    )
    assert second["status"] == "HELD"
    at_ceiling = build.read_tier(tier["id"])
    assert at_ceiling["comp_qty"] == allowance
    assert at_ceiling["available_qty"] == 97
    assert build.read_show(ctx["show"]["id"])["comp_tickets_issued"] == allowance

    refused = api.create_ticket_hold(
        factories.ticket_hold_payload(
            tier["id"], kind="COMP", qty=1, holder="Radio comp"
        ),
        build.buyer,
    )
    validate_error(refused, E.ERR_COMP_ALLOWANCE_EXCEEDED)

    unchanged = build.read_tier(tier["id"])
    assert unchanged["comp_qty"] == allowance
    assert unchanged["available_qty"] == 97
    assert unchanged["version"] == at_ceiling["version"]
    assert_tier_inventory_conserved(unchanged)


def test_comp_allowance_leaves_non_comp_holds_alone(api, build):
    """PRD.md 3.5: "On success, a `COMP` hold increases the tier's `comp_qty` by the
    held quantity while every other kind increases the tier's `held_qty`, and
    either way the tier's `available_qty` decreases by the same quantity."

    Design: Corner/cross-cutting complexity layers/cumulative_exposure_bands_and_instantaneous_variance_bands_fire_at_their_boundaries
    """
    ctx = _comps_at_the_ceiling(api, build)
    tier_id = ctx["tiers"][0]["id"]

    artist_hold = validate_success(
        api.create_ticket_hold(
            factories.ticket_hold_payload(
                tier_id, kind="ARTIST_HOLD", qty=5, holder="Artist guest list"
            ),
            build.buyer,
        ),
        201,
    )
    assert artist_hold["status"] == "HELD"
    assert artist_hold["kind"] == "ARTIST_HOLD"

    tier = build.read_tier(tier_id)
    assert tier["comp_qty"] == 3
    assert tier["held_qty"] == 5
    assert tier["available_qty"] == 92
    assert_tier_inventory_conserved(tier)

    show = build.read_show(ctx["show"]["id"])
    assert show["comp_tickets_issued"] == 3
    assert show["held_tickets"] == 5


def test_comp_allowance_is_rechecked_when_a_hold_is_converted_to_comp(api, build):
    """PRD.md 3.5: "The comp allowance is re-checked against the show's total
    allocation exactly as above, and a conversion that would push the show past
    its allowance is rejected with `ERR_COMP_ALLOWANCE_EXCEEDED`."

    Design: Corner/cross-cutting complexity layers/cumulative_exposure_bands_and_instantaneous_variance_bands_fire_at_their_boundaries
    """
    ctx = _comps_at_the_ceiling(api, build)
    tier_id = ctx["tiers"][0]["id"]
    artist_hold = validate_success(
        api.create_ticket_hold(
            factories.ticket_hold_payload(
                tier_id, kind="ARTIST_HOLD", qty=5, holder="Artist guest list"
            ),
            build.buyer,
        ),
        201,
    )
    before = build.read_tier(tier_id)

    refused = api.convert_hold_to_comp(artist_hold["id"], build.buyer)
    validate_error(refused, E.ERR_COMP_ALLOWANCE_EXCEEDED)

    hold = build.read_hold(artist_hold["id"])
    assert hold["status"] == "HELD"
    assert hold["kind"] == "ARTIST_HOLD"
    assert hold["version"] == artist_hold["version"]

    after = build.read_tier(tier_id)
    assert after["comp_qty"] == 3
    assert after["held_qty"] == 5
    assert after["available_qty"] == 92
    assert after["version"] == before["version"]


def test_releasing_a_comp_hold_restores_the_comp_headroom(api, build):
    """PRD.md 3.5: "the inventory movement is exactly reversed: the tier's
    `held_qty` — or its `comp_qty`, when the hold's kind is `COMP` — decreases
    by the hold's `qty` and its `available_qty` increases by the same amount."

    Design: Corner/cross-cutting complexity layers/cumulative_exposure_bands_and_instantaneous_variance_bands_fire_at_their_boundaries
    """
    ctx = _comps_at_the_ceiling(api, build)
    tier_id = ctx["tiers"][0]["id"]
    validate_success(
        api.create_ticket_hold(
            factories.ticket_hold_payload(
                tier_id, kind="ARTIST_HOLD", qty=5, holder="Artist guest list"
            ),
            build.buyer,
        ),
        201,
    )

    released = validate_success(
        api.release_ticket_hold(ctx["press_comp"]["id"], build.buyer)
    )
    assert released["status"] == "RELEASED"
    thawed = build.read_tier(tier_id)
    assert thawed["comp_qty"] == 2
    assert thawed["available_qty"] == 93
    assert_tier_inventory_conserved(thawed)

    reissued = validate_success(
        api.create_ticket_hold(
            factories.ticket_hold_payload(
                tier_id, kind="COMP", qty=1, holder="Radio comp"
            ),
            build.buyer,
        ),
        201,
    )
    assert reissued["status"] == "HELD"

    final_tier = build.read_tier(tier_id)
    assert final_tier["comp_qty"] == 3
    assert final_tier["held_qty"] == 5
    assert final_tier["available_qty"] == 92
    assert final_tier["sold_qty"] == 0
    assert_tier_inventory_conserved(final_tier)


# ---------------------------------------------------------------------------
# Instantaneous variance bands
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "actual_cents,expected_pct,expected_status,expected_role,expected_expense_cents",
    [
        (11_000, 10.00, "WITHIN_TOLERANCE", "NONE", 11_000),
        (11_001, 10.01, "PENDING_APPROVAL", "TOUR_ACCOUNTANT", 10_000),
        (12_500, 25.00, "PENDING_APPROVAL", "TOUR_ACCOUNTANT", 10_000),
        (12_501, 25.01, "PENDING_APPROVAL", "RISK_OFFICER", 10_000),
    ],
)
def test_variance_bands_fire_at_their_inclusive_boundaries(
    api,
    build,
    actual_cents,
    expected_pct,
    expected_status,
    expected_role,
    expected_expense_cents,
):
    """PRD.md 3.6: "A variance of at most 10.00 percent leaves the line
    `WITHIN_TOLERANCE` with `required_approver_role` `NONE` and
    `settlement_expense_cents` equal to `actual_cents`. Anything above 10.00
    percent puts the line in `PENDING_APPROVAL`, sets `settlement_expense_cents`
    to `budgeted_cents` while the variance is unresolved, and sets
    `required_approver_role` to `TOUR_ACCOUNTANT` when the variance is at most
    25.00 percent and `RISK_OFFICER` when it is above 25.00 percent."

    Design: Corner/cross-cutting complexity layers/cumulative_exposure_bands_and_instantaneous_variance_bands_fire_at_their_boundaries
    """
    ctx = build.confirmed_show(
        guarantee_cents=200_000,
        deposit_cents=0,
        expense_cap_cents=200_000,
        guarantee_exposure_limit_cents=1_000_000,
        gross_capacity=500,
        facility_fee_cents_per_ticket=0,
        ticket_tax_pct=0,
        market_name="Band Market",
        venue_name="Band Hall",
        artist_name="Band Act Two",
        show={"rental_fee_cents": 500_000},
    )
    line = build.line_with_actual(
        ctx["show"]["id"],
        10_000,
        actual_cents,
        category="PRODUCTION",
        is_artist_deductible=True,
    )

    assert line["budgeted_cents"] == 10_000
    assert line["actual_cents"] == actual_cents
    assert line["variance_cents"] == actual_cents - 10_000
    assert line["variance_pct"] == pytest.approx(expected_pct, abs=0.01)
    assert line["variance_status"] == expected_status
    assert line["required_approver_role"] == expected_role
    assert line["settlement_expense_cents"] == expected_expense_cents


# ---------------------------------------------------------------------------
# Optimistic concurrency on POST /offers
# ---------------------------------------------------------------------------


def test_offer_create_with_a_stale_show_version_is_rejected_and_writes_nothing(
    api, build
):
    """PRD.md 2.7: "If the supplied value does not equal the show's current
    `version`, the create is rejected with `ERR_STALE_SHOW_VERSION` (HTTP 412)."

    Design: Corner/cross-cutting complexity layers/optimistic_concurrency_rejects_both_declared_stale_show_version_writes
    """
    ctx = _occ_planned_show(build)
    show_id = ctx["show"]["id"]
    version_at_creation = ctx["show"]["version"]

    overridden = validate_success(
        api.grant_exposure_override(
            show_id,
            build.risk,
            exposure_override_limit_cents=9_000_000,
            exposure_override_justification="anchor date for the December routing",
        )
    )
    assert_version_bumped_by(overridden, ctx["show"], 1)
    current_version = overridden["version"]

    refused = api.create_offer(
        _flat_offer_payload(show_id, version_at_creation), build.buyer
    )
    validate_error(refused, E.ERR_STALE_SHOW_VERSION)

    rows, meta = validate_paginated(api.list_offers(build.buyer, show_id=show_id))
    assert rows == []
    assert meta["total_count"] == 0

    show = build.read_show(show_id)
    assert show["version"] == current_version
    assert show["show_status"] == "PLANNED"
    assert show["committed_guarantee_cents"] == 0


def test_offer_create_with_the_current_show_version_is_accepted(api, build):
    """PRD.md 2.7: "A `POST /offers` request must carry `expected_show_version`
    matching the target show's current `version`."

    Design: Corner/cross-cutting complexity layers/optimistic_concurrency_rejects_both_declared_stale_show_version_writes
    """
    ctx = _occ_planned_show(build)
    show_id = ctx["show"]["id"]
    overridden = validate_success(
        api.grant_exposure_override(
            show_id,
            build.risk,
            exposure_override_limit_cents=9_000_000,
            exposure_override_justification="anchor date for the December routing",
        )
    )
    current_version = overridden["version"]

    created = validate_success(
        api.create_offer(_flat_offer_payload(show_id, current_version), build.buyer), 201
    )
    assert created["status"] == "DRAFT"
    assert created["show_id"] == show_id
    assert created["guarantee_cents"] == 100_000

    validate_success(api.submit_offer(created["id"], build.buyer))
    accepted = validate_success(
        api.accept_offer(created["id"], build.artist_rep(ctx["artist"]["id"]))
    )
    assert accepted["status"] == "ACCEPTED"

    show = build.read_show(show_id)
    assert show["show_status"] == "CONFIRMED"
    assert show["committed_guarantee_cents"] == 100_000
    assert show["version"] > current_version


def test_a_stale_show_version_preempts_incoherent_deal_terms(api, build):
    """PRD.md 2.9: "Where several rules could reject the same call, they are
    evaluated in a fixed order and the **first** violated rule determines the
    response. No later rule is evaluated once one has fired, and no side effect
    of the operation runs."

    Design: Corner/cross-cutting complexity layers/optimistic_concurrency_rejects_both_declared_stale_show_version_writes
    """
    ctx = _occ_planned_show(build)
    show_id = ctx["show"]["id"]
    version_before_deal = build.read_show(show_id)["version"]
    accepted = build.accepted_offer(
        show_id,
        ctx["artist"]["id"],
        expected_show_version=version_before_deal,
        deal_structure="FLAT_GUARANTEE",
        guarantee_cents=100_000,
        deposit_cents=0,
        expense_cap_cents=100_000,
    )
    assert accepted["status"] == "ACCEPTED"

    doubly_invalid = api.create_offer(
        _flat_offer_payload(show_id, version_before_deal, versus_pct=85.00),
        build.buyer,
    )
    validate_error(doubly_invalid, E.ERR_STALE_SHOW_VERSION)

    rows, meta = validate_paginated(api.list_offers(build.buyer, show_id=show_id))
    assert meta["total_count"] == 1
    assert rows[0]["id"] == accepted["id"]
    assert build.read_offer(accepted["id"])["status"] == "ACCEPTED"


# ---------------------------------------------------------------------------
# Optimistic concurrency on POST /ticket-tiers/{ticket_tier_id}/price-adjustments
# ---------------------------------------------------------------------------


def test_price_adjustment_with_a_stale_show_version_leaves_the_face_price(api, build):
    """PRD.md 2.7: "A `POST /ticket-tiers/{ticket_tier_id}/price-adjustments`
    request must likewise carry `expected_show_version` matching the current
    `version` of the show that owns the tier."

    Design: Corner/cross-cutting complexity layers/optimistic_concurrency_rejects_both_declared_stale_show_version_writes
    """
    ctx = _occ_on_sale_show(build)
    show_id = ctx["show"]["id"]
    tier_id = ctx["tiers"][0]["id"]

    version_before_sale = build.read_show(show_id)["version"]
    sale = validate_success(api.record_sales(tier_id, build.buyer, qty=10))
    assert sale["sold_qty"] == 10
    version_after_sale = build.read_show(show_id)["version"]
    assert version_after_sale == version_before_sale + 1

    refused = api.adjust_tier_price(
        tier_id,
        build.buyer,
        new_price_cents=6_000,
        expected_show_version=version_before_sale,
        reason="sustained demand after the first sales week",
    )
    validate_error(refused, E.ERR_STALE_SHOW_VERSION)

    tier = build.read_tier(tier_id)
    assert tier["price_cents"] == 5_000
    assert tier["price_revision_count"] == 0
    assert tier["last_price_cents"] is None
    assert build.read_show(show_id)["version"] == version_after_sale


def test_price_adjustment_with_the_current_show_version_reprices_the_tier(api, build):
    """PRD.md 3.4: "On success the tier's `last_price_cents` records the price it
    held immediately before the revision, its `price_cents` becomes
    `new_price_cents`, and its `price_revision_count` increases by 1."

    Design: Corner/cross-cutting complexity layers/optimistic_concurrency_rejects_both_declared_stale_show_version_writes
    """
    ctx = _occ_on_sale_show(build)
    show_id = ctx["show"]["id"]
    tier_id = ctx["tiers"][0]["id"]
    validate_success(api.record_sales(tier_id, build.buyer, qty=10))
    current_version = build.read_show(show_id)["version"]

    repriced = validate_success(
        api.adjust_tier_price(
            tier_id,
            build.buyer,
            new_price_cents=6_000,
            expected_show_version=current_version,
            reason="sustained demand after the first sales week",
        )
    )
    assert repriced["price_cents"] == 6_000
    assert repriced["last_price_cents"] == 5_000
    assert repriced["price_revision_count"] == 1
    assert repriced["sold_qty"] == 10
    assert repriced["gross_sold_cents"] == 50_000
    assert build.read_show(show_id)["version"] == current_version + 1


def test_a_successful_guarded_write_invalidates_its_own_expected_show_version(
    api, build
):
    """PRD.md 2.4: "`version` starts at 1 when the resource is created and increases
    by exactly 1 on each mutation of that resource, and `updated_at` is
    refreshed to the current logical clock on each mutation."

    Design: Corner/cross-cutting complexity layers/optimistic_concurrency_rejects_both_declared_stale_show_version_writes
    """
    ctx = _occ_on_sale_show(build)
    show_id = ctx["show"]["id"]
    tier_id = ctx["tiers"][0]["id"]
    validate_success(api.record_sales(tier_id, build.buyer, qty=10))
    spent_version = build.read_show(show_id)["version"]

    validate_success(
        api.adjust_tier_price(
            tier_id,
            build.buyer,
            new_price_cents=6_000,
            expected_show_version=spent_version,
            reason="sustained demand after the first sales week",
        )
    )
    assert build.read_show(show_id)["version"] == spent_version + 1

    replayed = api.adjust_tier_price(
        tier_id,
        build.buyer,
        new_price_cents=7_000,
        expected_show_version=spent_version,
        reason="a replay of the token that has already been spent",
    )
    validate_error(replayed, E.ERR_STALE_SHOW_VERSION)

    tier = build.read_tier(tier_id)
    assert tier["price_cents"] == 6_000
    assert tier["price_revision_count"] == 1
    assert tier["last_price_cents"] == 5_000
    assert build.read_show(show_id)["version"] == spent_version + 1


def test_no_other_endpoint_rejects_a_request_for_omitting_a_version_field(api, build):
    """PRD.md 2.7: "No other endpoint in this system takes a version field.
    Endpoints not named above must not require one, and must not reject a
    request because a version field was omitted."

    Design: Corner/cross-cutting complexity layers/optimistic_concurrency_rejects_both_declared_stale_show_version_writes
    """
    ctx = build.confirmed_show(
        guarantee_cents=100_000,
        deposit_cents=0,
        expense_cap_cents=100_000,
        guarantee_exposure_limit_cents=5_000_000,
        gross_capacity=500,
        facility_fee_cents_per_ticket=0,
        ticket_tax_pct=0,
        market_name="OCC Market",
        venue_name="OCC Hall",
        artist_name="OCC Act",
        show={
            "rental_fee_cents": 500_000,
            "announce_at": ANNOUNCE_BEHIND_CLOCK,
        },
    )
    show_id = ctx["show"]["id"]

    tier = validate_success(
        api.create_ticket_tier(
            factories.ticket_tier_payload(
                show_id, tier_name="GA", price_cents=5_000, allocation_qty=200
            ),
            build.buyer,
        ),
        201,
    )
    validate_success(api.put_show_on_sale(show_id, build.buyer))
    validate_success(api.record_sales(tier["id"], build.buyer, qty=5))
    validate_success(
        api.create_ticket_hold(
            factories.ticket_hold_payload(
                tier["id"], kind="PROMOTER_HOLD", qty=2, holder="front of house"
            ),
            build.buyer,
        ),
        201,
    )
    line = validate_success(
        api.create_budget_line(
            factories.budget_line_payload(
                show_id,
                category="PRODUCTION",
                description="Crew and gear",
                budgeted_cents=100_000,
                is_artist_deductible=True,
            ),
            build.accountant,
        ),
        201,
    )
    validate_success(
        api.create_vendor_invoice(
            factories.vendor_invoice_payload(show_id, line["id"], amount_cents=50_000),
            build.accountant,
        ),
        201,
    )
    validate_success(api.pause_sales(show_id, "a weather hold on the building", build.buyer))
    validate_success(api.resume_sales(show_id, build.buyer))
    validate_success(
        api.grant_exposure_override(
            show_id,
            build.risk,
            exposure_override_limit_cents=9_000_000,
            exposure_override_justification="anchor date for the December routing",
        )
    )


# ---------------------------------------------------------------------------
# Immediate visibility: no read-after-write staleness anywhere
# ---------------------------------------------------------------------------


def test_offer_acceptance_is_final_in_its_own_response_and_across_the_cascade(
    api, build
):
    """PRD.md 2.10: "This system has no eventual consistency. When a write changes a
    figure that another figure is derived from, every dependent figure is
    recomputed **within the same request**, and the response reflects the fully
    settled state."

    Design: Corner/consistency model/every_mutation_is_fully_visible_the_moment_its_response_returns
    """
    ctx = _now_world(build)
    submitted = ctx["offer"]
    assert ctx["market"]["committed_guarantee_cents"] == 0
    assert ctx["market"]["at_risk_guarantee_cents"] == 0

    accepted = validate_success(
        api.accept_offer(submitted["id"], build.artist_rep(ctx["artist"]["id"]))
    )
    assert accepted["status"] == "ACCEPTED"
    assert accepted["accepted_by_user_id"] == ctx["artist"]["id"]
    assert_version_bumped_by(accepted, submitted, 1)
    assert_timestamp_equals(accepted["updated_at"], DEFAULT_CLOCK)

    reread_offer = build.read_offer(accepted["id"])
    assert reread_offer["status"] == "ACCEPTED"
    assert reread_offer["version"] == accepted["version"]

    show = build.read_show(ctx["show"]["id"])
    assert show["show_status"] == "CONFIRMED"
    assert show["committed_guarantee_cents"] == 200_000
    assert show["breakeven_cents"] == 200_000
    assert_timestamp_equals(show["updated_at"], DEFAULT_CLOCK)

    market = build.read_market(ctx["market"]["id"])
    assert_market_exposure(market, 200_000, 4.00, "OPEN")
    assert market["at_risk_guarantee_cents"] == 200_000
    assert_timestamp_equals(market["updated_at"], DEFAULT_CLOCK)


def test_a_ticket_sale_is_visible_on_the_tier_the_show_and_the_market_at_once(
    api, build
):
    """PRD.md 3.4: "Each sale then rolls upward. The show's `gross_sold_cents` is the
    sum of `gross_sold_cents` across **its own** tiers, and its
    `paid_tickets_sold` is the sum of `sold_qty` across its own tiers"

    Design: Corner/consistency model/every_mutation_is_fully_visible_the_moment_its_response_returns
    """
    ctx = _now_confirmed(api, build)
    show_id = ctx["show"]["id"]
    tier = build.tier(show_id, tier_name="GA", price_cents=5_000, allocation_qty=100)
    validate_success(api.put_show_on_sale(show_id, build.buyer))
    tier_on_sale = build.read_tier(tier["id"])

    sale = validate_success(api.record_sales(tier["id"], build.buyer, qty=10))
    assert sale["sold_qty"] == 10
    assert sale["gross_sold_cents"] == 50_000
    assert sale["available_qty"] == 90
    assert_tier_inventory_conserved(sale)
    assert_version_bumped_by(sale, tier_on_sale, 1)
    assert_timestamp_equals(sale["updated_at"], DEFAULT_CLOCK)

    show = build.read_show(show_id)
    assert show["gross_sold_cents"] == 50_000
    assert show["paid_tickets_sold"] == 10
    assert show["adjusted_gross_cents"] == 48_750
    assert show["projected_adjusted_gross_cents"] == 487_500

    market = build.read_market(ctx["market"]["id"])
    assert market["committed_guarantee_cents"] == 200_000
    assert market["at_risk_guarantee_cents"] == 151_250


def test_invoice_approval_is_final_at_every_level_on_the_very_next_read(api, build):
    """PRD.md 3.6: "**Hop three:** the line's new recognised expense recomputes the
    show's `total_actual_expense_cents`, `budget_posture` and `breakeven_cents`.
    **Hop four:** the show's `breakeven_cents` and `projected_promoter_net_cents`
    recompute the market's `at_risk_guarantee_cents`, which re-bands its
    `risk_posture`."

    Design: Corner/consistency model/every_mutation_is_fully_visible_the_moment_its_response_returns
    """
    ctx = _now_on_sale_with_one_sale(api, build)
    show_id = ctx["show"]["id"]
    line = build.budget_line(
        show_id,
        category="PRODUCTION",
        description="Crew and gear",
        budgeted_cents=100_000,
        is_artist_deductible=True,
    )
    verified = build.verified_invoice(
        show_id, line["id"], 130_000, vendor_name="Now Staging"
    )

    approved = validate_success(
        api.approve_vendor_invoice(verified["id"], build.accountant_two)
    )
    assert approved["status"] == "APPROVED"
    assert approved["approved_by_user_id"] == ACCOUNTANT_BOB
    assert_version_bumped_by(approved, verified, 1)
    assert_timestamp_equals(approved["updated_at"], DEFAULT_CLOCK)

    recognised = build.read_budget_line(line["id"])
    assert recognised["actual_cents"] == 130_000
    assert recognised["variance_cents"] == 30_000
    assert recognised["variance_pct"] == pytest.approx(30.00, abs=0.01)
    assert recognised["variance_status"] == "PENDING_APPROVAL"
    assert recognised["required_approver_role"] == "RISK_OFFICER"
    assert recognised["settlement_expense_cents"] == 100_000

    show = build.read_show(show_id)
    assert show["total_actual_expense_cents"] == 130_000
    assert show["total_budgeted_expense_cents"] == 100_000
    assert show["budget_posture"] == "VARIANCE_PENDING"
    assert show["breakeven_cents"] == 300_000

    market = build.read_market(ctx["market"]["id"])
    assert market["committed_guarantee_cents"] == 200_000
    assert market["at_risk_guarantee_cents"] == 251_250


def test_the_settlement_projection_read_persists_nothing(api, build):
    """PRD.md 3.7: "It may be run at any `show_status` — before the show, during the
    on-sale, after the performance — and it neither creates, reads nor mutates
    any settlement row. Its result is a settlement-shaped transient object in
    which `id`, `created_at`, `updated_at` and `version` are all null, `status`
    is reported as `DRAFT`, and `show_id` echoes the show whose projection was
    requested."

    Design: Corner/consistency model/every_mutation_is_fully_visible_the_moment_its_response_returns
    """
    ctx = _now_on_sale_with_one_sale(api, build)
    show_id = ctx["show"]["id"]
    line = build.budget_line(
        show_id,
        category="PRODUCTION",
        description="Crew and gear",
        budgeted_cents=100_000,
        is_artist_deductible=True,
    )
    build.approved_invoice(show_id, line["id"], 130_000, vendor_name="Now Staging")

    show_before = build.read_show(show_id)
    market_before = build.read_market(ctx["market"]["id"])

    projection = validate_success(api.get_settlement_projection(show_id, build.buyer))
    assert projection["show_id"] == show_id
    assert projection["status"] == "DRAFT"
    assert projection["id"] is None
    assert projection["created_at"] is None
    assert projection["updated_at"] is None
    assert projection["version"] is None

    rows, meta = validate_paginated(
        api.list_settlements(build.accountant, show_id=show_id)
    )
    assert rows == []
    assert meta["total_count"] == 0

    assert_unchanged(
        build.read_show(show_id),
        show_before,
        [
            "version",
            "updated_at",
            "committed_guarantee_cents",
            "breakeven_cents",
            "adjusted_gross_cents",
            "projected_adjusted_gross_cents",
            "total_actual_expense_cents",
            "budget_posture",
        ],
    )
    assert_unchanged(
        build.read_market(ctx["market"]["id"]),
        market_before,
        [
            "version",
            "committed_guarantee_cents",
            "at_risk_guarantee_cents",
            "exposure_utilization_pct",
            "risk_posture",
        ],
    )
