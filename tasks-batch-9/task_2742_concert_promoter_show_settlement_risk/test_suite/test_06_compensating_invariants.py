"""Compensating invariants: quantities that must return to their prior value.

Two conserved quantities are exercised here — a market's committed guarantee
exposure across a confirm-then-cancel round trip, and a ticket tier's four-way
inventory split across hold creation, release, conversion and expiry. Each test
builds its own world through the declared endpoints.
"""

from typing import Any, Dict

from test_helpers import (
    api_errors as E,
    assert_market_exposure,
    assert_tier_inventory_conserved,
    comp_allowance_for,
    factories as f,
    validate_error,
    validate_success,
)

EXPOSURE_FIELDS = (
    "committed_guarantee_cents",
    "at_risk_guarantee_cents",
    "exposure_utilization_pct",
    "risk_posture",
)


def _exposure_snapshot(market: Dict[str, Any]) -> Dict[str, Any]:
    return {field: market[field] for field in EXPOSURE_FIELDS}


# ---------------------------------------------------------------------------
# A market whose ceiling is exactly the two guarantees it is about to carry
# ---------------------------------------------------------------------------


def _gulf_coast_market(api, build) -> Dict[str, Any]:
    """A 5,000,000 ceiling, two acts, three booked nights, three submitted offers.

    Nothing is accepted yet, so the market still reads 0 across every exposure
    figure. Show A and show C carry 3,000,000 guarantees on the same act; show B
    carries 2,000,000 on a second act.
    """
    build.set_clock("2026-08-01T00:00:00.000Z")
    market = build.market(
        name="Gulf Coast", region_code="GLF", guarantee_exposure_limit_cents=5_000_000
    )
    artist_one = build.artist(name="Salt Marsh Choir", tier="ARENA")
    artist_two = build.artist(name="Delta Fanfare", tier="THEATER")
    venue_one = build.venue(market["id"], name="Bayou Arena", gross_capacity=8_000)
    venue_two = build.venue(market["id"], name="Delta Hall", gross_capacity=4_000)
    show_a = build.show(
        artist_one["id"],
        venue_one["id"],
        event_at="2026-10-10T02:00:00.000Z",
        load_in_at="2026-10-09T14:00:00.000Z",
        load_out_at="2026-10-10T08:00:00.000Z",
        announce_at="2026-08-15T15:00:00.000Z",
        venue_arrangement="RENTAL",
        rental_fee_cents=500_000,
    )
    show_b = build.show(
        artist_two["id"],
        venue_two["id"],
        event_at="2026-10-18T02:00:00.000Z",
        load_in_at="2026-10-17T14:00:00.000Z",
        load_out_at="2026-10-18T08:00:00.000Z",
        announce_at="2026-08-15T15:00:00.000Z",
        venue_arrangement="RENTAL",
        rental_fee_cents=400_000,
    )
    show_c = build.show(
        artist_one["id"],
        venue_one["id"],
        event_at="2026-11-14T02:00:00.000Z",
        load_in_at="2026-11-13T14:00:00.000Z",
        load_out_at="2026-11-14T08:00:00.000Z",
        announce_at="2026-08-15T15:00:00.000Z",
        venue_arrangement="RENTAL",
        rental_fee_cents=500_000,
    )
    offers = {
        "a": build.submitted_offer(
            show_a["id"],
            deal_structure="FLAT_GUARANTEE",
            guarantee_cents=3_000_000,
            deposit_cents=0,
            expense_cap_cents=3_000_000,
        ),
        "b": build.submitted_offer(
            show_b["id"],
            deal_structure="FLAT_GUARANTEE",
            guarantee_cents=2_000_000,
            deposit_cents=0,
            expense_cap_cents=2_000_000,
        ),
        "c": build.submitted_offer(
            show_c["id"],
            deal_structure="FLAT_GUARANTEE",
            guarantee_cents=3_000_000,
            deposit_cents=0,
            expense_cap_cents=3_000_000,
        ),
    }
    return {
        "market": market,
        "artist_one": artist_one,
        "artist_two": artist_two,
        "shows": {"a": show_a, "b": show_b, "c": show_c},
        "offers": offers,
    }


class TestMarketExposureReturnsToItsPriorValue:
    """Accept adds the guarantee; the compensating event subtracts the same."""

    def test_confirm_then_cancel_restores_every_exposure_figure(self, api, build):
        """PRD 3.3: "Committed exposure is a strictly conserved quantity.
        Accepting an offer adds exactly the offer's `guarantee_cents` to the
        market's committed total, and each compensating operation — opening a
        cancellation event of either kind, or paying the settlement — subtracts
        exactly the same amount. A confirm-then-cancel round trip therefore
        returns `committed_guarantee_cents`, `exposure_utilization_pct` and
        `risk_posture` to precisely their pre-acceptance values with no drift."

        Design: Difficulty/compensating_invariant/market_guarantee_exposure_returns_to_its_exact_prior_value_after_cancellation
        """
        ctx = _gulf_coast_market(api, build)
        validate_success(
            api.accept_offer(
                ctx["offers"]["b"]["id"], build.artist_rep(ctx["artist_two"]["id"])
            )
        )
        before_market = build.read_market(ctx["market"]["id"])
        assert_market_exposure(before_market, 2_000_000, 40.00, "OPEN")
        assert before_market["at_risk_guarantee_cents"] == 2_000_000, (
            "only show B's breakeven is exposed before the round trip, got "
            f"{before_market['at_risk_guarantee_cents']}"
        )
        before = _exposure_snapshot(before_market)

        validate_success(
            api.accept_offer(
                ctx["offers"]["a"]["id"], build.artist_rep(ctx["artist_one"]["id"])
            )
        )
        loaded = build.read_market(ctx["market"]["id"])
        assert_market_exposure(loaded, 5_000_000, 100.00, "FROZEN")
        assert loaded["at_risk_guarantee_cents"] == 5_000_000, (
            f"both breakevens are fully at risk, got {loaded['at_risk_guarantee_cents']}"
        )

        build.cancellation_event(ctx["shows"]["a"]["id"], kind="CANCELLED")

        after = _exposure_snapshot(build.read_market(ctx["market"]["id"]))
        assert after == before, (
            f"the round trip drifted: before {before}, after {after}"
        )

    def test_a_postponement_subtracts_exactly_the_same_amount(self, api, build):
        """PRD 3.3: "each compensating operation — opening a cancellation event of
        either kind, or paying the settlement — subtracts exactly the same
        amount".
        PRD 3.9: "The show leaves the market's in-scope exposure set either way,
        so the market's `committed_guarantee_cents` decreases by exactly the
        show's `committed_guarantee_cents`".

        Design: Difficulty/compensating_invariant/market_guarantee_exposure_returns_to_its_exact_prior_value_after_cancellation
        """
        ctx = _gulf_coast_market(api, build)
        validate_success(
            api.accept_offer(
                ctx["offers"]["b"]["id"], build.artist_rep(ctx["artist_two"]["id"])
            )
        )
        before = _exposure_snapshot(build.read_market(ctx["market"]["id"]))
        validate_success(
            api.accept_offer(
                ctx["offers"]["a"]["id"], build.artist_rep(ctx["artist_one"]["id"])
            )
        )
        assert_market_exposure(build.read_market(ctx["market"]["id"]), 5_000_000, 100.00, "FROZEN")

        build.cancellation_event(ctx["shows"]["a"]["id"], kind="POSTPONED")

        after = _exposure_snapshot(build.read_market(ctx["market"]["id"]))
        assert after == before, (
            f"postponement must subtract exactly the 3,000,000 it added: "
            f"before {before}, after {after}"
        )
        postponed = build.read_show(ctx["shows"]["a"]["id"])
        assert postponed["show_status"] == "POSTPONED"
        assert postponed["committed_guarantee_cents"] == 3_000_000, (
            "the show still names the guarantee of its ACCEPTED offer, got "
            f"{postponed['committed_guarantee_cents']}"
        )
        artist = build.read_artist(ctx["artist_one"]["id"])
        assert artist["confirmed_show_count"] == 0, (
            f"the act's confirmed window is empty again, got {artist['confirmed_show_count']}"
        )

    def test_voided_lines_leave_the_at_risk_book_with_the_cancelled_show(self, api, build):
        """PRD 3.3: "`at_risk_guarantee_cents` is the sum, over the same in-scope
        set, of the amount by which each show's `breakeven_cents` exceeds its
        `adjusted_gross_cents`".
        PRD 3.9: "every budget line whose lifecycle `status` is `ACTIVE` moves to
        `VOID`".

        Design: Difficulty/compensating_invariant/market_guarantee_exposure_returns_to_its_exact_prior_value_after_cancellation
        """
        ctx = _gulf_coast_market(api, build)
        validate_success(
            api.accept_offer(
                ctx["offers"]["b"]["id"], build.artist_rep(ctx["artist_two"]["id"])
            )
        )
        before = _exposure_snapshot(build.read_market(ctx["market"]["id"]))
        validate_success(
            api.accept_offer(
                ctx["offers"]["a"]["id"], build.artist_rep(ctx["artist_one"]["id"])
            )
        )

        line = build.line_with_actual(
            ctx["shows"]["a"]["id"],
            400_000,
            400_000,
            category="PRODUCTION",
            is_artist_deductible=True,
            vendor_name="Bayou Rigging",
        )
        assert line["settlement_expense_cents"] == 400_000, (
            f"the approved invoice is recognised in full, got {line['settlement_expense_cents']}"
        )
        show_a = build.read_show(ctx["shows"]["a"]["id"])
        assert show_a["breakeven_cents"] == 3_400_000, (
            f"breakeven is the guarantee plus the deductible expense, got {show_a['breakeven_cents']}"
        )
        loaded = build.read_market(ctx["market"]["id"])
        assert loaded["at_risk_guarantee_cents"] == 5_400_000, (
            f"the recognised expense re-priced the portfolio, got {loaded['at_risk_guarantee_cents']}"
        )
        assert loaded["committed_guarantee_cents"] == 5_000_000, (
            "expense recognition never moves the committed total, got "
            f"{loaded['committed_guarantee_cents']}"
        )

        build.cancellation_event(ctx["shows"]["a"]["id"], kind="CANCELLED")

        assert build.read_budget_line(line["id"])["status"] == "VOID", (
            "the cancellation must void the ACTIVE line"
        )
        after = _exposure_snapshot(build.read_market(ctx["market"]["id"]))
        assert after == before, (
            f"the at-risk book must return with the show: before {before}, after {after}"
        )

    def test_re_accepting_the_same_guarantee_reproduces_the_frozen_book(self, api, build):
        """PRD 3.3: "Accepting an offer adds exactly the offer's `guarantee_cents`
        to the market's committed total, and each compensating operation —
        opening a cancellation event of either kind, or paying the settlement —
        subtracts exactly the same amount."

        Design: Difficulty/compensating_invariant/market_guarantee_exposure_returns_to_its_exact_prior_value_after_cancellation
        """
        ctx = _gulf_coast_market(api, build)
        rep_one = build.artist_rep(ctx["artist_one"]["id"])
        validate_success(
            api.accept_offer(
                ctx["offers"]["b"]["id"], build.artist_rep(ctx["artist_two"]["id"])
            )
        )
        validate_success(api.accept_offer(ctx["offers"]["a"]["id"], rep_one))
        frozen = _exposure_snapshot(build.read_market(ctx["market"]["id"]))
        assert frozen["risk_posture"] == "FROZEN", (
            f"5,000,000 against a 5,000,000 ceiling is FROZEN, got {frozen['risk_posture']}"
        )

        build.cancellation_event(ctx["shows"]["a"]["id"], kind="CANCELLED")
        released = build.read_market(ctx["market"]["id"])
        assert released["risk_posture"] == "OPEN", (
            f"the market must thaw once the date is pulled, got {released['risk_posture']}"
        )

        # The replacement night carries the identical 3,000,000 guarantee.
        accepted = validate_success(api.accept_offer(ctx["offers"]["c"]["id"], rep_one))
        assert accepted["status"] == "ACCEPTED", (
            f"equality with the ceiling passes, got {accepted['status']}"
        )
        reloaded = _exposure_snapshot(build.read_market(ctx["market"]["id"]))
        assert reloaded == frozen, (
            f"an identical guarantee must reproduce the book exactly: "
            f"was {frozen}, now {reloaded}"
        )
        cancelled = build.read_show(ctx["shows"]["a"]["id"])
        assert cancelled["committed_guarantee_cents"] == 3_000_000, (
            "the cancelled show keeps naming its ACCEPTED offer's guarantee, got "
            f"{cancelled['committed_guarantee_cents']}"
        )
        artist = build.read_artist(ctx["artist_one"]["id"])
        assert artist["confirmed_show_count"] == 1, (
            f"one night in the confirmed window, got {artist['confirmed_show_count']}"
        )


# ---------------------------------------------------------------------------
# A 1,000 seat tier with 400 sold, the reference case for seat conservation
# ---------------------------------------------------------------------------


def _ridgeline_tier(api, build) -> Dict[str, Any]:
    """An ON_SALE show with one 1,000 seat tier, 400 of them already sold.

    Total allocation across the show is 1,000 seats, so the comp allowance is
    exactly 30 tickets.
    """
    build.set_clock("2026-08-01T00:00:00.000Z")
    market = build.market(
        name="Ridgeline", region_code="RDG", guarantee_exposure_limit_cents=10_000_000
    )
    artist = build.artist(name="Cedar Bells", tier="THEATER")
    venue = build.venue(
        market["id"],
        name="Ridgeline Ballroom",
        gross_capacity=1_200,
        facility_fee_cents_per_ticket=350,
        ticket_tax_pct=8.00,
    )
    show = build.show(
        artist["id"],
        venue["id"],
        event_at="2026-09-20T02:00:00.000Z",
        load_in_at="2026-09-19T14:00:00.000Z",
        load_out_at="2026-09-20T08:00:00.000Z",
        announce_at="2026-08-05T15:00:00.000Z",
        venue_arrangement="RENTAL",
        rental_fee_cents=400_000,
    )
    build.accepted_offer(
        show["id"],
        artist["id"],
        deal_structure="FLAT_GUARANTEE",
        guarantee_cents=1_000_000,
        deposit_cents=0,
        expense_cap_cents=1_000_000,
    )
    tier = build.tier(show["id"], tier_name="GA", price_cents=2_000, allocation_qty=1_000)
    build.set_clock("2026-08-05T15:00:00.000Z")
    validate_success(api.put_show_on_sale(show["id"], build.buyer))
    build.sell(tier["id"], 400)

    tier = build.read_tier(tier["id"])
    assert (tier["sold_qty"], tier["comp_qty"], tier["held_qty"], tier["available_qty"]) == (
        400,
        0,
        0,
        600,
    ), f"the reference tier should read 400/0/0/600, got {tier}"
    assert_tier_inventory_conserved(tier)
    assert comp_allowance_for(1_000) == 30, "a 1,000 seat show allows 30 comps"
    return {
        "market": market,
        "artist": artist,
        "venue": venue,
        "show": show,
        "tier": tier,
    }


def _split(tier: Dict[str, Any]):
    return (tier["sold_qty"], tier["comp_qty"], tier["held_qty"], tier["available_qty"])


class TestTierInventoryConservation:
    """Every seat movement is compensating and exact, at every intermediate step."""

    def test_hold_then_release_returns_the_tier_with_no_drift(self, api, build):
        """PRD 3.5: "a tier's `allocation_qty` always equals its `sold_qty` plus
        its `comp_qty` plus its `held_qty` plus its `available_qty`".
        PRD 3.5: "A hold-then-release round trip on a 1,000-seat tier with 400
        sold returns `held_qty` to its prior value and `available_qty` to 600 with
        no drift, and the invariant closes at every intermediate step".

        Design: Difficulty/compensating_invariant/tier_inventory_conserved_across_hold_release_convert_and_expiry
        """
        ctx = _ridgeline_tier(api, build)
        tier_id = ctx["tier"]["id"]
        operator = build.venue_operator(ctx["venue"]["id"])

        production = validate_success(
            api.create_ticket_hold(
                f.ticket_hold_payload(
                    tier_id,
                    kind="PRODUCTION_HOLD",
                    qty=120,
                    holder="production risers and mix world",
                ),
                operator,
            ),
            201,
        )
        held = build.read_tier(tier_id)
        assert _split(held) == (400, 0, 120, 480), (
            f"a non-comp hold moves seats from available to held, got {_split(held)}"
        )
        assert_tier_inventory_conserved(held)

        comp = build.hold(tier_id, kind="COMP", qty=25, holder="press and label guests")
        with_comp = build.read_tier(tier_id)
        assert _split(with_comp) == (400, 25, 120, 455), (
            f"a COMP hold lands in comp_qty, never in held_qty, got {_split(with_comp)}"
        )
        assert_tier_inventory_conserved(with_comp)
        assert build.read_show(ctx["show"]["id"])["comp_tickets_issued"] == 25

        released = validate_success(
            api.release_ticket_hold(production["id"], operator)
        )
        assert released["status"] == "RELEASED", (
            f"the production hold must move HELD to RELEASED, got {released['status']}"
        )
        assert released["released_by_user_id"] == ctx["venue"]["id"], (
            "the releasing identity is recorded, got "
            f"{released['released_by_user_id']}"
        )
        after = build.read_tier(tier_id)
        assert _split(after) == (400, 25, 0, 575), (
            f"the release must reverse exactly the 120 seats, got {_split(after)}"
        )
        assert_tier_inventory_conserved(after)
        assert build.read_hold(comp["id"])["status"] == "HELD", (
            "the comp hold is untouched by the production release"
        )

    def test_conversion_moves_held_to_comp_and_leaves_available_alone(self, api, build):
        """PRD 3.5: "On success the hold's `kind` becomes `COMP` and its status
        moves `HELD → CONVERTED`, `released_by_user_id` records the acting
        `X-User-ID`, the tier's `held_qty` decreases by the hold's `qty` while its
        `comp_qty` increases by the same amount, and the tier's `available_qty` is
        **unchanged**."

        Design: Difficulty/compensating_invariant/tier_inventory_conserved_across_hold_release_convert_and_expiry
        """
        ctx = _ridgeline_tier(api, build)
        tier_id = ctx["tier"]["id"]
        build.hold(tier_id, kind="COMP", qty=25, holder="press and label guests")
        artist_hold = validate_success(
            api.create_ticket_hold(
                f.ticket_hold_payload(
                    tier_id,
                    kind="ARTIST_HOLD",
                    qty=5,
                    holder="the act's guest list",
                    expires_at="2026-09-01T00:00:00.000Z",
                ),
                build.artist_rep(ctx["artist"]["id"]),
            ),
            201,
        )
        before = build.read_tier(tier_id)
        assert _split(before) == (400, 25, 5, 570), (
            f"expected 400/25/5/570 before the conversion, got {_split(before)}"
        )
        assert_tier_inventory_conserved(before)

        converted = validate_success(
            api.convert_hold_to_comp(artist_hold["id"], build.buyer)
        )
        assert converted["status"] == "CONVERTED", (
            f"conversion is terminal for the hold, got {converted['status']}"
        )
        assert converted["kind"] == "COMP", (
            f"the hold's kind becomes COMP, got {converted['kind']}"
        )

        after = build.read_tier(tier_id)
        assert _split(after) == (400, 30, 0, 570), (
            f"5 seats change class without changing sellability, got {_split(after)}"
        )
        assert after["available_qty"] == before["available_qty"], (
            "available_qty must be untouched by a conversion: "
            f"was {before['available_qty']}, now {after['available_qty']}"
        )
        assert_tier_inventory_conserved(after)
        show = build.read_show(ctx["show"]["id"])
        assert show["comp_tickets_issued"] == 30, (
            f"converted seats count as comps from the instant of conversion, got {show['comp_tickets_issued']}"
        )
        assert show["held_tickets"] == 0, (
            f"held_tickets decreases by the converted quantity, got {show['held_tickets']}"
        )

    def test_a_converted_hold_is_never_double_counted_against_the_allowance(self, api, build):
        """PRD 3.5: "`comp_qty` is the total `qty` of the tier's holds that either
        have `kind` `COMP` and status `HELD`, or have status `CONVERTED`
        regardless of kind; `held_qty` is the total `qty` of the tier's holds
        whose `kind` is anything other than `COMP` and whose status is `HELD`."
        PRD 3.5: "The show's current `comp_tickets_issued` plus the requested
        quantity must not exceed that allowance, or the request is rejected with
        `ERR_COMP_ALLOWANCE_EXCEEDED` (HTTP 422)."

        Design: Difficulty/compensating_invariant/tier_inventory_conserved_across_hold_release_convert_and_expiry
        """
        ctx = _ridgeline_tier(api, build)
        tier_id = ctx["tier"]["id"]
        build.hold(tier_id, kind="COMP", qty=25, holder="press and label guests")
        artist_hold = validate_success(
            api.create_ticket_hold(
                f.ticket_hold_payload(
                    tier_id,
                    kind="ARTIST_HOLD",
                    qty=5,
                    holder="the act's guest list",
                    expires_at="2026-09-01T00:00:00.000Z",
                ),
                build.artist_rep(ctx["artist"]["id"]),
            ),
            201,
        )
        validate_success(api.convert_hold_to_comp(artist_hold["id"], build.buyer))
        at_the_allowance = build.read_tier(tier_id)
        assert _split(at_the_allowance) == (400, 30, 0, 570)

        validate_error(
            api.create_ticket_hold(
                f.ticket_hold_payload(
                    tier_id, kind="COMP", qty=1, holder="one more guest"
                ),
                build.buyer,
            ),
            E.ERR_COMP_ALLOWANCE_EXCEEDED,
        )

        unchanged = build.read_tier(tier_id)
        assert _split(unchanged) == _split(at_the_allowance), (
            f"the refused comp must move nothing: was {_split(at_the_allowance)}, "
            f"now {_split(unchanged)}"
        )
        assert_tier_inventory_conserved(unchanged)
        assert build.read_show(ctx["show"]["id"])["comp_tickets_issued"] == 30

    def test_expiry_is_the_same_compensating_movement_as_release(self, api, build):
        """PRD 3.5: "Any hold in `HELD` whose `expires_at` is non-null and has been
        reached by the current logical clock moves `HELD → EXPIRED`; the tier's
        `held_qty` — or `comp_qty` for a comp hold — decreases by the hold's `qty`
        and its `available_qty` increases by the same amount".
        PRD 3.5: "`RELEASED` and `EXPIRED` holds contribute to neither. Every
        movement is compensating and exact: creating a hold moves seats from
        available to held, releasing or expiring one moves exactly the same seats
        back".

        Design: Difficulty/compensating_invariant/tier_inventory_conserved_across_hold_release_convert_and_expiry
        """
        ctx = _ridgeline_tier(api, build)
        tier_id = ctx["tier"]["id"]
        comp = build.hold(tier_id, kind="COMP", qty=25, holder="press and label guests")
        artist_hold = validate_success(
            api.create_ticket_hold(
                f.ticket_hold_payload(
                    tier_id,
                    kind="ARTIST_HOLD",
                    qty=5,
                    holder="the act's guest list",
                    expires_at="2026-09-01T00:00:00.000Z",
                ),
                build.artist_rep(ctx["artist"]["id"]),
            ),
            201,
        )
        validate_success(api.convert_hold_to_comp(artist_hold["id"], build.buyer))

        validate_success(api.release_ticket_hold(comp["id"], build.buyer))
        after_release = build.read_tier(tier_id)
        assert _split(after_release) == (400, 5, 0, 595), (
            "releasing a COMP hold takes the seats out of comp_qty and only the "
            f"converted 5 remain, got {_split(after_release)}"
        )
        assert_tier_inventory_conserved(after_release)

        expiring = validate_success(
            api.create_ticket_hold(
                f.ticket_hold_payload(
                    tier_id,
                    kind="ARTIST_HOLD",
                    qty=40,
                    holder="the act's touring party",
                    expires_at="2026-09-10T00:00:00.000Z",
                ),
                build.artist_rep(ctx["artist"]["id"]),
            ),
            201,
        )
        held = build.read_tier(tier_id)
        assert _split(held) == (400, 5, 40, 555), (
            f"the expiring hold takes 40 seats out of available, got {_split(held)}"
        )
        assert_tier_inventory_conserved(held)

        build.set_clock("2026-09-10T00:00:00.000Z")
        build.run_housekeeping()

        expired = build.read_hold(expiring["id"])
        assert expired["status"] == "EXPIRED", (
            f"the clock reached expires_at, so the hold must be EXPIRED, got {expired['status']}"
        )
        final = build.read_tier(tier_id)
        assert _split(final) == (400, 5, 0, 595), (
            f"expiry returns exactly the 40 seats it took, got {_split(final)}"
        )
        assert _split(final) == _split(after_release), (
            "expiry and release are the same compensating movement: "
            f"{_split(after_release)} vs {_split(final)}"
        )
        assert_tier_inventory_conserved(final)
        show = build.read_show(ctx["show"]["id"])
        assert show["held_tickets"] == 0, (
            f"the show's held_tickets follows the tier back to 0, got {show['held_tickets']}"
        )
        assert show["comp_tickets_issued"] == 5, (
            f"only the converted seats remain comps, got {show['comp_tickets_issued']}"
        )
