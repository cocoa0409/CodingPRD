"""Which rule speaks first, and what happens exactly on a threshold.

The first half drives calls that break two rules at once and pins the response
to the higher-ranked one, then repairs only that defect on the identical
payload so the lower-ranked rule can be seen to have been live all along. The
second half walks a metric onto its threshold, one cent either side of it, and
onto a value whose raw ratio and rounded ratio fall on opposite sides.
"""

from typing import Any, Dict

import pytest

from test_helpers import (
    RISK_RITA,
    api_errors as E,
    assert_market_exposure,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# Instance setups
# ---------------------------------------------------------------------------


def _market_at_eighty_percent_with_a_draft_offer(build) -> Dict[str, Any]:
    """A market 80 percent committed plus a second show carrying a DRAFT offer.

    The limit is 5,000,000 and one accepted 4,000,000 guarantee already sits
    against it, so the market reads WATCH — which does not block acceptance.
    The second show's offer is 2,000,000 and was never submitted, so accepting
    it breaks both the offer's state machine and the market's ceiling at once.
    """
    market = build.market(
        name="Great Basin", region_code="GBS", guarantee_exposure_limit_cents=5_000_000
    )
    headliner = build.artist(
        name="Neon Arroyo", tier="ARENA", withholding_pct=0, agency="Sagebrush Talent"
    )
    choir = build.artist(
        name="Salt Flats Choir",
        tier="THEATER",
        withholding_pct=0,
        agency="Sagebrush Talent",
    )
    venue = build.venue(
        market["id"],
        name="Basin Center",
        gross_capacity=3_000,
        facility_fee_cents_per_ticket=200,
        ticket_tax_pct=7.00,
    )
    booked_show = build.show(
        headliner["id"],
        venue["id"],
        event_at="2026-10-03T02:00:00.000Z",
        load_in_at="2026-10-02T14:00:00.000Z",
        load_out_at="2026-10-03T08:00:00.000Z",
        announce_at="2026-08-20T15:00:00.000Z",
        venue_arrangement="RENTAL",
        rental_fee_cents=200_000,
    )
    build.accepted_offer(
        booked_show["id"],
        headliner["id"],
        deal_structure="FLAT_GUARANTEE",
        guarantee_cents=4_000_000,
        deposit_cents=0,
        expense_cap_cents=1_000_000,
    )
    second_show = build.show(
        choir["id"],
        venue["id"],
        event_at="2026-10-20T02:00:00.000Z",
        load_in_at="2026-10-19T14:00:00.000Z",
        load_out_at="2026-10-20T08:00:00.000Z",
        announce_at="2026-08-20T15:00:00.000Z",
        venue_arrangement="RENTAL",
        rental_fee_cents=200_000,
    )
    draft_offer = build.offer(
        second_show["id"],
        deal_structure="FLAT_GUARANTEE",
        guarantee_cents=2_000_000,
        deposit_cents=0,
        expense_cap_cents=1_000_000,
    )
    return {
        "market": build.read_market(market["id"]),
        "artist": choir,
        "show": build.read_show(second_show["id"]),
        "offer": draft_offer,
    }


def _risk_officer_line_pending_at_thirty_percent(build) -> Dict[str, Any]:
    """A CONFIRMED show with one line escalated all the way to RISK_OFFICER.

    A hospitality line budgeted at 200,000 carries an approved invoice for
    260,000, which is 30.00 percent over and therefore above the 25.00 percent
    escalation threshold, so only a RiskOfficer may decide it.
    """
    ctx = build.confirmed_show(
        guarantee_cents=1_000_000,
        deposit_cents=0,
        expense_cap_cents=1_000_000,
        deal_structure="FLAT_GUARANTEE",
        guarantee_exposure_limit_cents=10_000_000,
        gross_capacity=700,
        facility_fee_cents_per_ticket=0,
        ticket_tax_pct=0,
        tier="CLUB",
        market_name="Four Corners",
        venue_name="Mesa Social Club",
        artist_name="Mesa Drift",
        show={
            "event_at": "2026-10-08T02:00:00.000Z",
            "load_in_at": "2026-10-07T14:00:00.000Z",
            "load_out_at": "2026-10-08T08:00:00.000Z",
            "announce_at": "2026-08-25T15:00:00.000Z",
            "venue_arrangement": "RENTAL",
            "rental_fee_cents": 50_000,
        },
    )
    line = build.budget_line(
        ctx["show"]["id"],
        category="HOSPITALITY",
        description="green room catering",
        budgeted_cents=200_000,
        is_artist_deductible=True,
    )
    build.approved_invoice(
        ctx["show"]["id"],
        line["id"],
        260_000,
        vendor_name="High Mesa Catering",
        invoice_date="2026-10-07",
        documentation_ref="INV-V-0001",
    )
    ctx["line"] = build.read_budget_line(line["id"])
    ctx["show"] = build.read_show(ctx["show"]["id"])
    return ctx


def _three_lines_budgeted_at_one_and_a_half_million(build) -> Dict[str, Any]:
    """Three identical 1,500,000 production lines, each with one verified invoice.

    The invoices are 1,650,000 (exactly on the tolerance), 1,650,074 (a raw
    ratio just above it that rounds back onto it) and 1,651,000 (clear of it).
    None of the three lines is artist-deductible, so the show's breakeven never
    moves however they are recognised.
    """
    ctx = build.confirmed_show(
        guarantee_cents=1_000_000,
        deposit_cents=0,
        expense_cap_cents=1_000_000,
        deal_structure="FLAT_GUARANTEE",
        guarantee_exposure_limit_cents=10_000_000,
        gross_capacity=1_500,
        facility_fee_cents_per_ticket=0,
        ticket_tax_pct=0,
        tier="THEATER",
        market_name="Upper Midwest",
        venue_name="Birchwood Auditorium",
        artist_name="Boreal Echo",
        show={
            "event_at": "2026-10-24T02:00:00.000Z",
            "load_in_at": "2026-10-23T14:00:00.000Z",
            "load_out_at": "2026-10-24T08:00:00.000Z",
            "announce_at": "2026-08-28T15:00:00.000Z",
            "venue_arrangement": "RENTAL",
            "rental_fee_cents": 150_000,
        },
    )
    show_id = ctx["show"]["id"]
    specs = [
        ("at_boundary", "exactly-at-tolerance line", 1_650_000, "Birch Staging A", "INV-B-EQ"),
        ("rounds_down", "rounds-down-to-tolerance line", 1_650_074, "Birch Staging B", "INV-B-ROUND"),
        ("over_boundary", "just-over-tolerance line", 1_651_000, "Birch Staging C", "INV-B-OVER"),
    ]
    for key, description, amount_cents, vendor_name, documentation_ref in specs:
        line = build.budget_line(
            show_id,
            category="PRODUCTION",
            description=description,
            budgeted_cents=1_500_000,
            is_artist_deductible=False,
        )
        invoice = build.verified_invoice(
            show_id,
            line["id"],
            amount_cents,
            vendor_name=vendor_name,
            invoice_date="2026-10-23",
            documentation_ref=documentation_ref,
        )
        ctx[key] = {"line": line, "invoice": invoice}
    return ctx


def _three_boundary_markets_with_submitted_offers(build) -> Dict[str, Any]:
    """Three markets on an identical 5,000,000 ceiling, each with paper waiting.

    One act plays all four dates, at least 19 days apart so the rest buffer
    never binds. The submitted guarantees are 5,000,000 (exactly the ceiling),
    5,000,001 (one cent past it), 4,999,900 (100 cents short of it) and 100
    (which would land the third market exactly on its ceiling).
    """
    artist = build.artist(
        name="Iron Meridian", tier="ARENA", withholding_pct=0, agency="Anvil Route"
    )
    ctx: Dict[str, Any] = {"artist": artist}
    specs = [
        ("one", "Boundary Market One", "BM1", "Anvil Hall One", [("at_limit", 5_000_000, "2026-10-01", "2026-09-30")]),
        ("two", "Boundary Market Two", "BM2", "Anvil Hall Two", [("over_limit", 5_000_001, "2026-11-01", "2026-10-31")]),
        (
            "three",
            "Boundary Market Three",
            "BM3",
            "Anvil Hall Three",
            [
                ("under_limit", 4_999_900, "2026-12-01", "2026-11-30"),
                ("remainder", 100, "2026-12-20", "2026-12-19"),
            ],
        ),
    ]
    for key, market_name, region_code, venue_name, offers in specs:
        market = build.market(
            name=market_name,
            region_code=region_code,
            guarantee_exposure_limit_cents=5_000_000,
        )
        venue = build.venue(
            market["id"],
            name=venue_name,
            gross_capacity=2_000,
            facility_fee_cents_per_ticket=0,
            ticket_tax_pct=0,
        )
        ctx[f"market_{key}"] = market
        for offer_key, guarantee_cents, event_day, load_in_day in offers:
            show = build.show(
                artist["id"],
                venue["id"],
                event_at=f"{event_day}T02:00:00.000Z",
                load_in_at=f"{load_in_day}T14:00:00.000Z",
                load_out_at=f"{event_day}T08:00:00.000Z",
                announce_at="2026-08-20T15:00:00.000Z",
                venue_arrangement="RENTAL",
                rental_fee_cents=100_000,
            )
            offer = build.submitted_offer(
                show["id"],
                deal_structure="FLAT_GUARANTEE",
                guarantee_cents=guarantee_cents,
                deposit_cents=0,
                expense_cap_cents=1_000_000,
            )
            ctx[f"show_{offer_key}"] = show
            ctx[f"offer_{offer_key}"] = offer
    return ctx


# ---------------------------------------------------------------------------
# One accept call that breaks the offer's state machine and the market's
# ceiling at the same time
# ---------------------------------------------------------------------------


class TestAcceptOfferStateBeforeExposure:
    """The state rule and the exposure rule, both violated by one call."""

    def test_a_draft_offer_is_refused_on_state_not_on_the_ceiling(self, api, build):
        """PRD §2.9: "they are evaluated in a fixed order and the **first** violated rule determines the response"
        PRD §2.9: "State legality — `ERR_INVALID_STATE` when the target sits in a non-terminal state from which the requested trigger has no declared transition"
        PRD §2.9: "Everything else — the domain-specific checks, whose relative order among themselves is stated in the §3 subsection that describes each workflow."
        PRD §3.3: "An `ArtistRep` whose `X-User-ID` equals the show's `artist_id` accepts a `SUBMITTED` offer on a show that is still `PLANNED`"

        Design: Difficulty/priority_pair_validation_conflict/accept_offer_state_check_preempts_market_exposure_check
        """
        ctx = _market_at_eighty_percent_with_a_draft_offer(build)
        assert ctx["offer"]["status"] == "DRAFT", (
            "the second offer must still be unsubmitted for both rules to bite"
        )
        assert_market_exposure(ctx["market"], 4_000_000, 80.00, "WATCH")

        response = api.accept_offer(
            ctx["offer"]["id"], build.artist_rep(ctx["artist"]["id"])
        )

        body = validate_error(response, E.ERR_INVALID_STATE)
        assert body["error_id"] != E.ERR_MARKET_EXPOSURE_EXCEEDED, (
            "the ceiling is breached too, but the state rule is ranked above it"
        )

    def test_repairing_only_the_state_defect_uncovers_the_ceiling(self, api, build):
        """PRD §3.3: "The fourth is **market exposure**: the market's current `committed_guarantee_cents` plus this offer's `guarantee_cents` must not exceed the applicable ceiling, and equality with the ceiling passes."
        PRD §3.3: "The applicable ceiling is the show's own `exposure_override_limit_cents` when that field is non-null, and the market's `guarantee_exposure_limit_cents` otherwise. Exceeding it yields `ERR_MARKET_EXPOSURE_EXCEEDED` (HTTP 402)."
        PRD §2.9: "No later rule is evaluated once one has fired, and no side effect of the operation runs."

        Design: Difficulty/priority_pair_validation_conflict/accept_offer_state_check_preempts_market_exposure_check
        """
        ctx = _market_at_eighty_percent_with_a_draft_offer(build)
        rep = build.artist_rep(ctx["artist"]["id"])

        validate_error(api.accept_offer(ctx["offer"]["id"], rep), E.ERR_INVALID_STATE)
        validate_success(api.submit_offer(ctx["offer"]["id"], build.buyer))

        response = api.accept_offer(ctx["offer"]["id"], rep)

        validate_error(response, E.ERR_MARKET_EXPOSURE_EXCEEDED)
        offer = build.read_offer(ctx["offer"]["id"])
        assert offer["status"] == "SUBMITTED", (
            "the fiscal refusal must leave the offer where the submit put it"
        )

    def test_neither_refusal_moves_the_exposure_book_or_the_show(self, api, build):
        """PRD §2.9: "No later rule is evaluated once one has fired, and no side effect of the operation runs."
        PRD §3.3: "`PLANNED` shows contribute nothing, because no guarantee is committed until an offer is accepted"
        PRD §3.3: "The act's `confirmed_show_count` increases by 1. The `version` of the offer, the show, the artist and the market each increment by 1."

        Design: Difficulty/priority_pair_validation_conflict/accept_offer_state_check_preempts_market_exposure_check
        """
        ctx = _market_at_eighty_percent_with_a_draft_offer(build)
        rep = build.artist_rep(ctx["artist"]["id"])

        validate_error(api.accept_offer(ctx["offer"]["id"], rep), E.ERR_INVALID_STATE)
        validate_success(api.submit_offer(ctx["offer"]["id"], build.buyer))
        validate_error(
            api.accept_offer(ctx["offer"]["id"], rep), E.ERR_MARKET_EXPOSURE_EXCEEDED
        )

        market = build.read_market(ctx["market"]["id"])
        assert_market_exposure(market, 4_000_000, 80.00, "WATCH")

        show = build.read_show(ctx["show"]["id"])
        assert show["show_status"] == "PLANNED"
        assert show["committed_guarantee_cents"] == 0

        artist = build.read_artist(ctx["artist"]["id"])
        assert artist["confirmed_show_count"] == 0, "no acceptance cascade ran"


# ---------------------------------------------------------------------------
# One variance decision that lacks the authority and carries an invalid cap
# ---------------------------------------------------------------------------


class TestVarianceAuthorityBeforeCapValidity:
    """The authority rule and the cap rule, both violated by one payload."""

    def test_an_accountant_on_a_risk_officer_line_is_refused_on_authority(
        self, api, build
    ):
        """PRD §3.6: "Two checks then apply, in this order. First, the acting role must satisfy the line's `required_approver_role`"
        PRD §3.6: "a `TourAccountant` may decide only lines whose `required_approver_role` is `NONE` or `TOUR_ACCOUNTANT` and is refused on a `RISK_OFFICER` line with `ERR_VARIANCE_APPROVAL_AUTHORITY` (HTTP 403)"
        PRD §3.6: "a line budgeted at 200,000 with actual 260,000 lands on 30.00 and goes to `PENDING_APPROVAL` needing a `RISK_OFFICER`."

        Design: Difficulty/priority_pair_validation_conflict/variance_decision_authority_check_preempts_cap_validity_check
        """
        ctx = _risk_officer_line_pending_at_thirty_percent(build)
        line = ctx["line"]
        assert float(line["variance_pct"]) == pytest.approx(30.00, abs=0.01)
        assert line["variance_status"] == "PENDING_APPROVAL"
        assert line["required_approver_role"] == "RISK_OFFICER"

        response = api.decide_variance(
            line["id"],
            build.accountant_two,
            decision="APPROVE",
            approved_cap_cents=150_000,
            variance_justification=(
                "accountant tries to approve a risk-officer line with a cap below budget"
            ),
        )

        body = validate_error(response, E.ERR_VARIANCE_APPROVAL_AUTHORITY)
        assert body["error_id"] != E.ERR_VARIANCE_CAP_INVALID, (
            "the 150000 cap is below the 200000 budget too, but authority is checked first"
        )
        assert body["error_id"] != E.ERR_ROLE_FORBIDDEN, (
            "a TourAccountant may reach this endpoint; the denial is data-dependent"
        )

    def test_repairing_only_the_authority_defect_uncovers_the_cap_rule(
        self, api, build
    ):
        """PRD §3.6: "Second, on `APPROVE`, `approved_cap_cents` must be present and at least the line's `budgeted_cents`; on `REJECT`, `approved_cap_cents` must be absent; either violation yields `ERR_VARIANCE_CAP_INVALID` (HTTP 422)."
        PRD §3.6: "the acting role must satisfy the line's `required_approver_role`: a `RiskOfficer` may decide any line"

        Design: Difficulty/priority_pair_validation_conflict/variance_decision_authority_check_preempts_cap_validity_check
        """
        ctx = _risk_officer_line_pending_at_thirty_percent(build)
        line_id = ctx["line"]["id"]

        validate_error(
            api.decide_variance(
                line_id,
                build.accountant_two,
                decision="APPROVE",
                approved_cap_cents=150_000,
                variance_justification=(
                    "accountant tries to approve a risk-officer line with a cap below budget"
                ),
            ),
            E.ERR_VARIANCE_APPROVAL_AUTHORITY,
        )

        response = api.decide_variance(
            line_id,
            build.risk,
            decision="APPROVE",
            approved_cap_cents=150_000,
            variance_justification="risk officer retries with the same below-budget cap",
        )

        validate_error(response, E.ERR_VARIANCE_CAP_INVALID)

    def test_neither_refusal_writes_any_part_of_the_decision(self, api, build):
        """PRD §2.9: "No later rule is evaluated once one has fired, and no side effect of the operation runs."
        PRD §3.6: "Anything above 10.00 percent puts the line in `PENDING_APPROVAL`, sets `settlement_expense_cents` to `budgeted_cents` while the variance is unresolved"
        PRD §3.6: "On `APPROVE` the line moves `PENDING_APPROVAL → APPROVED`, records `approved_cap_cents`, `variance_justification` and `variance_decided_by_user_id`"

        Design: Difficulty/priority_pair_validation_conflict/variance_decision_authority_check_preempts_cap_validity_check
        """
        ctx = _risk_officer_line_pending_at_thirty_percent(build)
        line_id = ctx["line"]["id"]

        validate_error(
            api.decide_variance(
                line_id,
                build.accountant_two,
                decision="APPROVE",
                approved_cap_cents=150_000,
                variance_justification="the accountant has no authority here",
            ),
            E.ERR_VARIANCE_APPROVAL_AUTHORITY,
        )
        validate_error(
            api.decide_variance(
                line_id,
                build.risk,
                decision="APPROVE",
                approved_cap_cents=150_000,
                variance_justification="the cap is still below the budgeted figure",
            ),
            E.ERR_VARIANCE_CAP_INVALID,
        )

        line = build.read_budget_line(line_id)
        assert line["variance_status"] == "PENDING_APPROVAL"
        assert line["approved_cap_cents"] is None
        assert line["variance_decided_by_user_id"] is None
        assert line["settlement_expense_cents"] == 200_000, (
            "the unresolved variance still recognises the budgeted figure"
        )

    def test_a_risk_officer_with_a_lawful_cap_binds_the_recognised_expense(
        self, api, build
    ):
        """PRD §3.6: "its `settlement_expense_cents` becomes the **lesser** of `actual_cents` and `approved_cap_cents` — the approver's ceiling binds."
        PRD §3.6: "It is `ON_BUDGET` when every one of the show's lines is `WITHIN_TOLERANCE`; it is `VARIANCE_PENDING` whenever **any** line is `PENDING_APPROVAL`, which takes precedence; and it is `OVER_BUDGET` otherwise"
        PRD §3.6: "it is the show's `committed_guarantee_cents` plus the **lesser** of two amounts — the sum of `settlement_expense_cents` across the show's artist-deductible lines, and the accepted offer's `expense_cap_cents`."

        Design: Difficulty/priority_pair_validation_conflict/variance_decision_authority_check_preempts_cap_validity_check
        """
        ctx = _risk_officer_line_pending_at_thirty_percent(build)
        line_id = ctx["line"]["id"]

        line = validate_success(
            api.decide_variance(
                line_id,
                build.risk,
                decision="APPROVE",
                approved_cap_cents=250_000,
                variance_justification=(
                    "risk officer allows 250000 of the 260000 spend; 10000 disallowed"
                ),
            )
        )

        assert line["variance_status"] == "APPROVED"
        assert line["settlement_expense_cents"] == 250_000, (
            "the lesser of the 260000 actual and the 250000 approved cap"
        )
        assert line["variance_decided_by_user_id"] == RISK_RITA

        show = build.read_show(ctx["show"]["id"])
        assert show["budget_posture"] == "OVER_BUDGET", (
            "one decided line and none pending"
        )
        assert show["breakeven_cents"] == 1_250_000, (
            "1000000 guarantee plus the lesser of 250000 recognised and the "
            "1000000 expense cap"
        )


# ---------------------------------------------------------------------------
# The 10.00 percent variance tolerance, probed one cent at a time
# ---------------------------------------------------------------------------


class TestVarianceToleranceBoundary:
    """Approving an invoice that lands a line on, near or past 10.00 percent."""

    @pytest.mark.parametrize(
        "case, variance_cents, variance_pct, variance_status, approver_role, recognised_cents",
        [
            ("at_boundary", 150_000, 10.00, "WITHIN_TOLERANCE", "NONE", 1_650_000),
            ("rounds_down", 150_074, 10.00, "WITHIN_TOLERANCE", "NONE", 1_650_074),
            (
                "over_boundary",
                151_000,
                10.07,
                "PENDING_APPROVAL",
                "TOUR_ACCOUNTANT",
                1_500_000,
            ),
        ],
    )
    def test_the_tolerance_band_reads_the_rounded_variance(
        self,
        api,
        build,
        case,
        variance_cents,
        variance_pct,
        variance_status,
        approver_role,
        recognised_cents,
    ):
        """PRD §3.6: "A variance of at most 10.00 percent leaves the line `WITHIN_TOLERANCE` with `required_approver_role` `NONE` and `settlement_expense_cents` equal to `actual_cents`."
        PRD §3.6: "The boundaries are inclusive, and they read the rounded value: a line budgeted at 1,500,000 with actual 1,650,000 lands on exactly 10.00 and stays `WITHIN_TOLERANCE`; the same line with actual 1,650,074 has a raw ratio just above ten percent that **rounds** to 10.00 and therefore also stays `WITHIN_TOLERANCE`; with actual 1,651,000 it lands on 10.07 and goes to `PENDING_APPROVAL` needing a `TOUR_ACCOUNTANT`"
        PRD §2.6: "are themselves rounded half up to two decimal places, and every threshold comparison in this document reads the **rounded** value, never the raw ratio."

        Design: Difficulty/boundary_precision_check/variance_pct_at_exactly_ten_percent_stays_within_tolerance
        """
        ctx = _three_lines_budgeted_at_one_and_a_half_million(build)
        subject = ctx[case]

        validate_success(
            api.approve_vendor_invoice(
                subject["invoice"]["id"], build.accountant_two
            )
        )

        line = build.read_budget_line(subject["line"]["id"])
        assert line["variance_cents"] == variance_cents
        assert float(line["variance_pct"]) == pytest.approx(variance_pct, abs=0.01)
        assert line["variance_status"] == variance_status, (
            f"a variance of {variance_pct} percent must land in {variance_status}"
        )
        assert line["required_approver_role"] == approver_role
        assert line["settlement_expense_cents"] == recognised_cents

    def test_a_raw_ratio_over_ten_percent_that_rounds_back_does_not_escalate(
        self, api, build
    ):
        """PRD §3.6: "the same line with actual 1,650,074 has a raw ratio just above ten percent that **rounds** to 10.00 and therefore also stays `WITHIN_TOLERANCE`"
        PRD §3.6: "It is `ON_BUDGET` when every one of the show's lines is `WITHIN_TOLERANCE`; it is `VARIANCE_PENDING` whenever **any** line is `PENDING_APPROVAL`, which takes precedence"
        PRD §3.6: "A new line is created with `actual_cents` 0, `variance_cents` 0, `variance_pct` 0, `variance_status` `WITHIN_TOLERANCE`, `required_approver_role` `NONE`"

        Design: Difficulty/boundary_precision_check/variance_pct_at_exactly_ten_percent_stays_within_tolerance
        """
        ctx = _three_lines_budgeted_at_one_and_a_half_million(build)

        validate_success(
            api.approve_vendor_invoice(
                ctx["at_boundary"]["invoice"]["id"], build.accountant_two
            )
        )
        validate_success(
            api.approve_vendor_invoice(
                ctx["rounds_down"]["invoice"]["id"], build.accountant_two
            )
        )

        show = build.read_show(ctx["show"]["id"])
        assert show["budget_posture"] == "ON_BUDGET", (
            "both recognised lines round onto 10.00, so nothing is pending; an "
            "implementation banding on the raw 10.004933 ratio would report "
            "VARIANCE_PENDING here"
        )
        assert show["total_actual_expense_cents"] == 3_300_074

    def test_only_the_line_past_the_boundary_makes_the_show_pending(self, api, build):
        """PRD §3.6: "its `total_actual_expense_cents` is the sum of `actual_cents` over the same set — the invoiced reality."
        PRD §3.6: "it is `VARIANCE_PENDING` whenever **any** line is `PENDING_APPROVAL`, which takes precedence"
        PRD §3.6: "it is the show's `committed_guarantee_cents` plus the **lesser** of two amounts — the sum of `settlement_expense_cents` across the show's artist-deductible lines, and the accepted offer's `expense_cap_cents`."

        Design: Difficulty/boundary_precision_check/variance_pct_at_exactly_ten_percent_stays_within_tolerance
        """
        ctx = _three_lines_budgeted_at_one_and_a_half_million(build)

        for case in ("at_boundary", "rounds_down", "over_boundary"):
            validate_success(
                api.approve_vendor_invoice(
                    ctx[case]["invoice"]["id"], build.accountant_two
                )
            )

        show = build.read_show(ctx["show"]["id"])
        assert show["total_actual_expense_cents"] == 4_951_074, (
            "1650000 plus 1650074 plus 1651000"
        )
        assert show["budget_posture"] == "VARIANCE_PENDING", (
            "exactly one of the three lines escalated, and pending dominates"
        )
        assert show["breakeven_cents"] == 1_000_000, (
            "none of the three lines is artist-deductible, so no expense is allowed"
        )


# ---------------------------------------------------------------------------
# The guarantee exposure ceiling, probed one cent either side
# ---------------------------------------------------------------------------


class TestMarketExposureLimitBoundary:
    """Accepting offers that land a market on, past or just short of its limit."""

    def test_committing_exactly_to_the_limit_is_accepted_and_freezes_the_market(
        self, api, build
    ):
        """PRD §3.3: "the market's current `committed_guarantee_cents` plus this offer's `guarantee_cents` must not exceed the applicable ceiling, and equality with the ceiling passes"
        PRD §3.3: "`OPEN` when it is at most 70, `WATCH` when it is greater than 70 and at most 90, `RESTRICTED` when it is greater than 90 and strictly below 100, and `FROZEN` at 100 or above"
        PRD §3.3: "Committing exactly to the limit lands at 100.00 and freezes the market — and because the exposure check permits equality, that acceptance itself still succeeds"

        Design: Difficulty/boundary_precision_check/market_exposure_at_exactly_the_limit_is_accepted_and_freezes_the_market
        """
        ctx = _three_boundary_markets_with_submitted_offers(build)

        offer = validate_success(
            api.accept_offer(
                ctx["offer_at_limit"]["id"], build.artist_rep(ctx["artist"]["id"])
            )
        )

        assert offer["status"] == "ACCEPTED", (
            "0 plus 5000000 against a 5000000 ceiling passes on equality"
        )
        market = build.read_market(ctx["market_one"]["id"])
        assert_market_exposure(market, 5_000_000, 100.00, "FROZEN")

    def test_one_cent_past_the_limit_is_refused_and_writes_nothing(self, api, build):
        """PRD §3.3: "The applicable ceiling is the show's own `exposure_override_limit_cents` when that field is non-null, and the market's `guarantee_exposure_limit_cents` otherwise. Exceeding it yields `ERR_MARKET_EXPOSURE_EXCEEDED` (HTTP 402)."
        PRD §2.9: "No later rule is evaluated once one has fired, and no side effect of the operation runs."
        PRD §3.1: "A newly opened market starts empty in every derived respect: `committed_guarantee_cents` 0, `at_risk_guarantee_cents` 0, `exposure_utilization_pct` 0, `risk_posture` `OPEN`"

        Design: Difficulty/boundary_precision_check/market_exposure_at_exactly_the_limit_is_accepted_and_freezes_the_market
        """
        ctx = _three_boundary_markets_with_submitted_offers(build)

        response = api.accept_offer(
            ctx["offer_over_limit"]["id"], build.artist_rep(ctx["artist"]["id"])
        )

        validate_error(response, E.ERR_MARKET_EXPOSURE_EXCEEDED)
        market = build.read_market(ctx["market_two"]["id"])
        assert_market_exposure(market, 0, 0.00, "OPEN")
        assert build.read_offer(ctx["offer_over_limit"]["id"])["status"] == "SUBMITTED"
        assert build.read_show(ctx["show_over_limit"]["id"])["show_status"] == "PLANNED"

    def test_a_hundred_cents_of_headroom_still_rounds_to_a_frozen_posture(
        self, api, build
    ):
        """PRD §3.3: "`exposure_utilization_pct` is the market's `committed_guarantee_cents` multiplied by 100, divided by its `guarantee_exposure_limit_cents`, rounded half up to two decimal places."
        PRD §3.3: "`risk_posture` is then banded from that **rounded** percentage"
        PRD §2.6: "every threshold comparison in this document reads the **rounded** value, never the raw ratio"

        Design: Difficulty/boundary_precision_check/market_exposure_at_exactly_the_limit_is_accepted_and_freezes_the_market
        """
        ctx = _three_boundary_markets_with_submitted_offers(build)

        offer = validate_success(
            api.accept_offer(
                ctx["offer_under_limit"]["id"], build.artist_rep(ctx["artist"]["id"])
            )
        )

        assert offer["status"] == "ACCEPTED"
        market = build.read_market(ctx["market_three"]["id"])
        assert_market_exposure(market, 4_999_900, 100.00, "FROZEN")

    def test_the_last_hundred_cents_are_refused_on_posture_not_on_exposure(
        self, api, build
    ):
        """PRD §3.3: "The third is **market posture**: if the market's `risk_posture` is `FROZEN`, the acceptance is rejected with `ERR_MARKET_POSTURE_FROZEN` (HTTP 409). The posture read here is the market's posture **before** this acceptance is applied."
        PRD §3.3: "it is the *next* acceptance that fails, and it fails on posture rather than on exposure"

        Design: Difficulty/boundary_precision_check/market_exposure_at_exactly_the_limit_is_accepted_and_freezes_the_market
        """
        ctx = _three_boundary_markets_with_submitted_offers(build)
        rep = build.artist_rep(ctx["artist"]["id"])
        validate_success(api.accept_offer(ctx["offer_under_limit"]["id"], rep))

        response = api.accept_offer(ctx["offer_remainder"]["id"], rep)

        body = validate_error(response, E.ERR_MARKET_POSTURE_FROZEN)
        assert body["error_id"] != E.ERR_MARKET_EXPOSURE_EXCEEDED, (
            "4999900 plus 100 equals the 5000000 ceiling and would have passed the "
            "exposure check, so only the rounded posture band explains the refusal"
        )
        assert build.read_show(ctx["show_remainder"]["id"])["show_status"] == "PLANNED"
        market = build.read_market(ctx["market_three"]["id"])
        assert market["committed_guarantee_cents"] == 4_999_900
