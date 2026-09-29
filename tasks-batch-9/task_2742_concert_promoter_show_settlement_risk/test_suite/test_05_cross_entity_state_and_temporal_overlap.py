"""Cross-entity state dependencies and the two temporal-overlap resources.

Every test builds its own world from scratch: the database is empty when the
test starts, so the helpers below compose the whole precondition chain through
the declared endpoints.
"""

from typing import Any, Dict, List

import pytest

from test_helpers import (
    api_errors as E,
    factories as f,
    validate_error,
    validate_paginated,
    validate_success,
)

# ---------------------------------------------------------------------------
# World builders
# ---------------------------------------------------------------------------


def _performed_show_with_one_verified_invoice(api, build) -> Dict[str, Any]:
    """A PERFORMED rental show whose MARKETING invoice stopped at VERIFIED.

    Cedar Room takes no ticket tax and no facility fee, so the only receipts
    deduction is the card fee. Two non-deductible lines are budgeted at 500000
    and 300000; the PRODUCTION invoice is verified and approved, the MARKETING
    invoice is verified only.
    """
    build.set_clock("2026-08-01T00:00:00.000Z")
    market = build.market(
        name="Cascade Basin",
        region_code="CSB",
        guarantee_exposure_limit_cents=10_000_000,
    )
    artist = build.artist(
        name="Verdant Coil",
        agency="Fernway Talent",
        tier="CLUB",
        historical_sellthrough_pct=44.00,
        withholding_pct=0,
    )
    venue = build.venue(
        market["id"],
        name="Cedar Room",
        gross_capacity=500,
        facility_fee_cents_per_ticket=0,
        ticket_tax_pct=0,
    )
    show = build.show(
        artist["id"],
        venue["id"],
        event_at="2026-09-05T02:00:00.000Z",
        load_in_at="2026-09-04T14:00:00.000Z",
        load_out_at="2026-09-05T08:00:00.000Z",
        announce_at="2026-08-05T15:00:00.000Z",
        venue_arrangement="RENTAL",
        rental_fee_cents=100_000,
    )
    offer = build.accepted_offer(
        show["id"],
        artist["id"],
        expected_show_version=show["version"],
        deal_structure="FLAT_GUARANTEE",
        guarantee_cents=1_000_000,
        deposit_cents=0,
        expense_cap_cents=1_000_000,
    )
    tier = build.tier(
        show["id"], tier_name="GA", price_cents=2_000, allocation_qty=500
    )
    production_line = build.budget_line(
        show["id"],
        category="PRODUCTION",
        description="backline and audio",
        budgeted_cents=500_000,
        is_artist_deductible=False,
    )
    marketing_line = build.budget_line(
        show["id"],
        category="MARKETING",
        description="local radio buy",
        budgeted_cents=300_000,
        is_artist_deductible=False,
    )
    build.set_clock("2026-08-05T15:00:00.000Z")
    validate_success(api.put_show_on_sale(show["id"], build.buyer))
    build.sell(tier["id"], 200)
    build.set_clock("2026-09-05T06:00:00.000Z")
    validate_success(api.perform_show(show["id"], build.accountant))
    build.approved_invoice(
        show["id"],
        production_line["id"],
        500_000,
        vendor_name="Cedar Audio",
        invoice_date="2026-09-04",
        documentation_ref="INV-U-PROD",
    )
    verified = build.verified_invoice(
        show["id"],
        marketing_line["id"],
        300_000,
        vendor_name="KCDR Radio",
        invoice_date="2026-09-04",
        documentation_ref="INV-U-MKT",
    )
    book = build.settlement(show["id"])
    return {
        "market": market,
        "artist": artist,
        "venue": venue,
        "show": build.read_show(show["id"]),
        "offer": offer,
        "tier": build.read_tier(tier["id"]),
        "production_line": build.read_budget_line(production_line["id"]),
        "marketing_line": build.read_budget_line(marketing_line["id"]),
        "verified_invoice": verified,
        "settlement": book,
    }


class TestSettlementCalculateBlockedByVerifiedInvoice:
    """The refusal comes from a vendor invoice's state, not the settlement's."""

    def test_calculate_refused_while_one_invoice_is_still_verified(self, api, build):
        """PRD 3.7: "no vendor invoice on the show may still be `SUBMITTED`,
        `VERIFIED` or `DISPUTED` — every invoice must have reached `APPROVED` or
        `REJECTED` before the books close — or the call is rejected with
        `ERR_UNRESOLVED_INVOICES` (HTTP 409)".
        PRD 2.9: "No later rule is evaluated once one has fired, and no side
        effect of the operation runs."

        Design: Difficulty/cross_entity_state_dependency/settlement_calculate_blocked_by_a_still_verified_vendor_invoice
        """
        ctx = _performed_show_with_one_verified_invoice(api, build)
        book = ctx["settlement"]
        assert book["status"] == "DRAFT", (
            f"a freshly opened settlement book is DRAFT, got {book['status']}"
        )
        assert ctx["verified_invoice"]["status"] == "VERIFIED", (
            "the blocking invoice must sit in VERIFIED, not SUBMITTED, "
            f"got {ctx['verified_invoice']['status']}"
        )

        validate_error(
            api.calculate_settlement(book["id"], build.accountant),
            E.ERR_UNRESOLVED_INVOICES,
        )

        after = build.read_settlement(book["id"])
        assert after["status"] == "DRAFT", (
            f"the refused calculate must leave the book in DRAFT, got {after['status']}"
        )
        assert after["deal_structure_applied"] is None, (
            "no deal structure may be copied onto a refused calculation"
        )
        for field in (
            "gross_receipts_cents",
            "adjusted_gross_cents",
            "artist_earnings_cents",
            "promoter_net_cents",
        ):
            assert after[field] == 0, (
                f"{field} must still be 0 after a refused calculate, got {after[field]}"
            )

    def test_calculate_refusal_is_not_a_variance_problem(self, api, build):
        """PRD 3.6: "A variance of at most 10.00 percent leaves the line
        `WITHIN_TOLERANCE` with `required_approver_role` `NONE` and
        `settlement_expense_cents` equal to `actual_cents`."
        PRD 3.7: "no budget line on the show may be `PENDING_APPROVAL`, or the
        call is rejected with `ERR_UNRESOLVED_VARIANCE` (HTTP 409)".

        Design: Difficulty/cross_entity_state_dependency/settlement_calculate_blocked_by_a_still_verified_vendor_invoice
        """
        ctx = _performed_show_with_one_verified_invoice(api, build)
        production = build.read_budget_line(ctx["production_line"]["id"])
        marketing = build.read_budget_line(ctx["marketing_line"]["id"])
        assert production["variance_status"] == "WITHIN_TOLERANCE", (
            f"the approved-invoice line lands on 0.00 percent variance, "
            f"got {production['variance_status']}"
        )
        assert marketing["variance_status"] == "WITHIN_TOLERANCE", (
            "the line behind the still-verified invoice has recognised nothing yet, "
            f"got {marketing['variance_status']}"
        )
        assert marketing["actual_cents"] == 0, (
            f"a VERIFIED invoice is invisible to the ledger, got {marketing['actual_cents']}"
        )

        validate_error(
            api.calculate_settlement(ctx["settlement"]["id"], build.accountant),
            E.ERR_UNRESOLVED_INVOICES,
        )

    def test_approving_the_blocking_invoice_unblocks_the_identical_call(self, api, build):
        """PRD 3.7: "It is reachable from `DRAFT`, from `DISPUTED` and from
        `REOPENED`, all three landing on `CALCULATED`, and it may be run as many
        times as those cycles allow — each run re-reads the ledger and may
        produce different money."
        PRD 3.6: "the line's `actual_cents` is refreshed to the total
        `amount_cents` of the line's invoices whose status is `APPROVED`".

        Design: Difficulty/cross_entity_state_dependency/settlement_calculate_blocked_by_a_still_verified_vendor_invoice
        """
        ctx = _performed_show_with_one_verified_invoice(api, build)
        book = ctx["settlement"]
        validate_error(
            api.calculate_settlement(book["id"], build.accountant),
            E.ERR_UNRESOLVED_INVOICES,
        )

        approved = validate_success(
            api.approve_vendor_invoice(
                ctx["verified_invoice"]["id"], build.accountant_two
            )
        )
        assert approved["status"] == "APPROVED", (
            f"approval moves the invoice to APPROVED, got {approved['status']}"
        )
        marketing = build.read_budget_line(ctx["marketing_line"]["id"])
        assert marketing["actual_cents"] == 300_000, (
            f"the newly approved 300000 must reach actual_cents, got {marketing['actual_cents']}"
        )
        assert marketing["variance_cents"] == 0, (
            f"actual equals budget, so variance_cents is 0, got {marketing['variance_cents']}"
        )
        assert marketing["settlement_expense_cents"] == 300_000, (
            "a WITHIN_TOLERANCE line recognises actual_cents, got "
            f"{marketing['settlement_expense_cents']}"
        )

        settled = validate_success(
            api.calculate_settlement(book["id"], build.accountant)
        )
        assert settled["status"] == "CALCULATED", (
            "the byte-identical second calculate must succeed, got "
            f"{settled['status']}"
        )
        assert settled["deal_structure_applied"] == "FLAT_GUARANTEE", (
            f"the accepted offer's structure is copied, got {settled['deal_structure_applied']}"
        )

    def test_money_after_the_blocking_invoice_is_finally_recognised(self, api, build):
        """PRD 3.7: "`total_settlement_expense_cents` is the sum of
        `settlement_expense_cents` across the show's participating lines — the
        recognised figure, which differs from the show's
        `total_actual_expense_cents` wherever a variance was approved with a cap
        or rejected."
        PRD 3.7: "One closing invariant must hold on every `CALCULATED`
        settlement, under either arrangement: `adjusted_gross_cents` equals
        `artist_earnings_cents` plus `promoter_borne_expense_cents` plus
        `venue_share_cents` plus `promoter_net_cents`."

        Design: Difficulty/cross_entity_state_dependency/settlement_calculate_blocked_by_a_still_verified_vendor_invoice
        """
        ctx = _performed_show_with_one_verified_invoice(api, build)
        book = ctx["settlement"]
        validate_error(
            api.calculate_settlement(book["id"], build.accountant),
            E.ERR_UNRESOLVED_INVOICES,
        )
        validate_success(
            api.approve_vendor_invoice(
                ctx["verified_invoice"]["id"], build.accountant_two
            )
        )
        s = validate_success(api.calculate_settlement(book["id"], build.accountant))

        # Receipts: 200 tickets at 2000, no tax, no facility fee, 2.5% card fee.
        assert s["gross_receipts_cents"] == 400_000
        assert s["ticket_tax_cents"] == 0
        assert s["facility_fee_cents"] == 0
        assert s["credit_card_fee_cents"] == 10_000
        assert s["adjusted_gross_cents"] == 390_000

        # Expense recognition: both lines count, neither is artist-deductible.
        assert s["total_settlement_expense_cents"] == 800_000, (
            "the MARKETING 300000 is inside the total only because the blocking "
            f"invoice was finally approved, got {s['total_settlement_expense_cents']}"
        )
        assert s["allowed_expense_cents"] == 0
        assert s["breakeven_cents"] == 1_000_000

        # Earnings: flat guarantee, cap leg of the co-op binds at 5% of 1000000.
        assert s["artist_base_earnings_cents"] == 1_000_000
        assert s["artist_coop_contribution_cents"] == 50_000
        assert s["artist_earnings_cents"] == 950_000
        assert s["withholding_cents"] == 0
        assert s["deposit_credit_cents"] == 0
        assert s["payment_due_cents"] == 950_000

        # Rental split: the flat fee is paid regardless of outcome.
        assert s["venue_expense_reimbursement_cents"] == 0
        assert s["promoter_borne_expense_cents"] == 800_000
        assert s["venue_share_cents"] == 100_000
        assert s["promoter_net_cents"] == -1_460_000, (
            f"promoter_net_cents is signed and this show lost money, got {s['promoter_net_cents']}"
        )
        assert (
            s["artist_earnings_cents"]
            + s["promoter_borne_expense_cents"]
            + s["venue_share_cents"]
            + s["promoter_net_cents"]
            == s["adjusted_gross_cents"]
        ), "the closing settlement identity must hold exactly"


def _two_shows_each_with_a_pending_variance(api, build) -> Dict[str, Any]:
    """Two CONFIRMED shows in one market, each carrying a 30 percent variance.

    Both acts are distinct, so the artist calendar never enters the picture, and
    both venues are distinct, so the load windows never collide. Each show has a
    single artist-deductible PRODUCTION line budgeted at 200000 whose approved
    invoice for 260000 drives the line into PENDING_APPROVAL needing a
    RISK_OFFICER.
    """
    build.set_clock("2026-08-01T00:00:00.000Z")
    market = build.market(
        name="Sierra Corridor",
        region_code="SRC",
        guarantee_exposure_limit_cents=5_000_000,
    )
    artist_p = build.artist(name="Paper Lanterns", tier="THEATER")
    artist_q = build.artist(name="Quarry Bells", tier="THEATER")
    venue_one = build.venue(market["id"], name="Foothill Theatre", gross_capacity=1_200)
    venue_two = build.venue(market["id"], name="Granite Hall", gross_capacity=1_200)
    show_p = build.show(
        artist_p["id"],
        venue_one["id"],
        event_at="2026-10-10T02:00:00.000Z",
        load_in_at="2026-10-09T14:00:00.000Z",
        load_out_at="2026-10-10T08:00:00.000Z",
        announce_at="2026-08-15T15:00:00.000Z",
        venue_arrangement="RENTAL",
        rental_fee_cents=300_000,
    )
    show_q = build.show(
        artist_q["id"],
        venue_two["id"],
        event_at="2026-10-18T02:00:00.000Z",
        load_in_at="2026-10-17T14:00:00.000Z",
        load_out_at="2026-10-18T08:00:00.000Z",
        announce_at="2026-08-15T15:00:00.000Z",
        venue_arrangement="RENTAL",
        rental_fee_cents=300_000,
    )
    build.accepted_offer(
        show_p["id"],
        artist_p["id"],
        deal_structure="FLAT_GUARANTEE",
        guarantee_cents=1_000_000,
        deposit_cents=0,
        expense_cap_cents=1_000_000,
    )
    build.accepted_offer(
        show_q["id"],
        artist_q["id"],
        deal_structure="FLAT_GUARANTEE",
        guarantee_cents=1_000_000,
        deposit_cents=0,
        expense_cap_cents=1_000_000,
    )
    line_p = build.line_with_actual(
        show_p["id"],
        200_000,
        260_000,
        category="PRODUCTION",
        is_artist_deductible=True,
        vendor_name="Foothill Rigging",
    )
    line_q = build.line_with_actual(
        show_q["id"],
        200_000,
        260_000,
        category="PRODUCTION",
        is_artist_deductible=True,
        vendor_name="Granite Rigging",
    )
    return {
        "market": market,
        "artist_p": artist_p,
        "artist_q": artist_q,
        "show_p": build.read_show(show_p["id"]),
        "show_q": build.read_show(show_q["id"]),
        "line_p": line_p,
        "line_q": line_q,
    }


class TestVarianceDecisionBlockedByPostponedShow:
    """The budget line is decidable; the show it hangs off is not."""

    def test_thirty_percent_overrun_parks_the_line_on_a_risk_officer(self, api, build):
        """PRD 3.6: "a line budgeted at 200,000 with actual 260,000 lands on 30.00
        and goes to `PENDING_APPROVAL` needing a `RISK_OFFICER`".

        Design: Difficulty/cross_entity_state_dependency/budget_line_variance_decision_blocked_by_postponed_show
        """
        ctx = _two_shows_each_with_a_pending_variance(api, build)
        for label, line in (("P", ctx["line_p"]), ("Q", ctx["line_q"])):
            assert line["actual_cents"] == 260_000, (
                f"line {label} should have recognised the approved invoice, "
                f"got {line['actual_cents']}"
            )
            assert line["variance_cents"] == 60_000, (
                f"line {label} variance_cents: expected 60000, got {line['variance_cents']}"
            )
            assert line["variance_pct"] == pytest.approx(30.00, abs=0.01), (
                f"line {label} variance_pct: expected 30.00, got {line['variance_pct']}"
            )
            assert line["variance_status"] == "PENDING_APPROVAL", (
                f"line {label} variance_status: expected PENDING_APPROVAL, "
                f"got {line['variance_status']}"
            )
            assert line["required_approver_role"] == "RISK_OFFICER", (
                f"line {label} required_approver_role: expected RISK_OFFICER, "
                f"got {line['required_approver_role']}"
            )
            assert line["settlement_expense_cents"] == 200_000, (
                "a PENDING_APPROVAL line recognises only the budget, got "
                f"{line['settlement_expense_cents']}"
            )

    def test_variance_decision_refused_once_the_show_is_postponed(self, api, build):
        """PRD 3.6: "The line must be in `PENDING_APPROVAL` and the show's
        `show_status` must be `CONFIRMED`, `ON_SALE` or `PERFORMED`."
        PRD 2.9: "State legality — `ERR_INVALID_STATE` when the target sits in a
        non-terminal state from which the requested trigger has no declared
        transition, including sub-resource guards such as a show's ticketing
        state or a budget line's own lifecycle state."

        Design: Difficulty/cross_entity_state_dependency/budget_line_variance_decision_blocked_by_postponed_show
        """
        ctx = _two_shows_each_with_a_pending_variance(api, build)
        event = build.cancellation_event(ctx["show_q"]["id"], kind="POSTPONED")
        assert event["kind"] == "POSTPONED", (
            f"the compensating event must be a POSTPONED one, got {event['kind']}"
        )
        postponed = build.read_show(ctx["show_q"]["id"])
        assert postponed["show_status"] == "POSTPONED", (
            f"show Q must sit in POSTPONED, got {postponed['show_status']}"
        )

        validate_error(
            api.decide_variance(
                ctx["line_q"]["id"],
                build.risk,
                decision="APPROVE",
                approved_cap_cents=250_000,
                variance_justification="carried across to the replacement date",
            ),
            E.ERR_INVALID_STATE,
        )

        after = build.read_budget_line(ctx["line_q"]["id"])
        assert after["variance_status"] == "PENDING_APPROVAL", (
            f"the refused decision must not move the line, got {after['variance_status']}"
        )
        assert after["approved_cap_cents"] is None, (
            f"no cap may be recorded by a refused decision, got {after['approved_cap_cents']}"
        )
        assert after["variance_decided_by_user_id"] is None, (
            "no decider may be recorded by a refused decision, got "
            f"{after['variance_decided_by_user_id']}"
        )
        assert after["variance_justification"] is None, (
            f"no justification may be stored, got {after['variance_justification']}"
        )
        assert after["settlement_expense_cents"] == 200_000, (
            "recognition must still be the budgeted figure, got "
            f"{after['settlement_expense_cents']}"
        )

    def test_postponement_leaves_the_line_active_and_the_variance_pending(self, api, build):
        """PRD 3.9: "Under `POSTPONED` the show's `show_status` moves to
        `POSTPONED` and budget lines are explicitly **not** voided, because they
        carry across to the replacement date."
        PRD 3.6: "it is `VARIANCE_PENDING` whenever **any** line is
        `PENDING_APPROVAL`, which takes precedence".

        Design: Difficulty/cross_entity_state_dependency/budget_line_variance_decision_blocked_by_postponed_show
        """
        ctx = _two_shows_each_with_a_pending_variance(api, build)
        build.cancellation_event(ctx["show_q"]["id"], kind="POSTPONED")

        line = build.read_budget_line(ctx["line_q"]["id"])
        assert line["status"] == "ACTIVE", (
            f"a postponed show keeps its budget lines ACTIVE, got {line['status']}"
        )
        show = build.read_show(ctx["show_q"]["id"])
        assert show["budget_posture"] == "VARIANCE_PENDING", (
            f"the undecided line keeps the show on VARIANCE_PENDING, got {show['budget_posture']}"
        )
        assert show["total_actual_expense_cents"] == 260_000, (
            f"the recognised actuals survive the postponement, got {show['total_actual_expense_cents']}"
        )

        validate_error(
            api.decide_variance(
                ctx["line_q"]["id"],
                build.risk,
                decision="REJECT",
                variance_justification="the overrun is not carried",
            ),
            E.ERR_INVALID_STATE,
        )

    def test_the_same_decision_lands_on_the_still_confirmed_sibling_show(self, api, build):
        """PRD 3.6: "On `APPROVE` the line moves `PENDING_APPROVAL → APPROVED`,
        records `approved_cap_cents`, `variance_justification` and
        `variance_decided_by_user_id`, and its `settlement_expense_cents` becomes
        the **lesser** of `actual_cents` and `approved_cap_cents`".

        Design: Difficulty/cross_entity_state_dependency/budget_line_variance_decision_blocked_by_postponed_show
        """
        ctx = _two_shows_each_with_a_pending_variance(api, build)
        build.cancellation_event(ctx["show_q"]["id"], kind="POSTPONED")
        validate_error(
            api.decide_variance(
                ctx["line_q"]["id"],
                build.risk,
                decision="APPROVE",
                approved_cap_cents=250_000,
                variance_justification="carried across to the replacement date",
            ),
            E.ERR_INVALID_STATE,
        )

        decided = validate_success(
            api.decide_variance(
                ctx["line_p"]["id"],
                build.risk,
                decision="APPROVE",
                approved_cap_cents=250_000,
                variance_justification="freight surcharge accepted at a cap",
            )
        )
        assert decided["variance_status"] == "APPROVED", (
            f"the CONFIRMED show's line is decidable, got {decided['variance_status']}"
        )
        assert decided["approved_cap_cents"] == 250_000
        assert decided["settlement_expense_cents"] == 250_000, (
            "recognition is the lesser of 260000 actual and the 250000 cap, got "
            f"{decided['settlement_expense_cents']}"
        )
        assert decided["variance_decided_by_user_id"] is not None, (
            "the deciding officer must be stamped on the line"
        )

        show_p = build.read_show(ctx["show_p"]["id"])
        assert show_p["budget_posture"] == "OVER_BUDGET", (
            "with the only line approved above budget the show is OVER_BUDGET, got "
            f"{show_p['budget_posture']}"
        )
        assert show_p["breakeven_cents"] == 1_250_000, (
            f"breakeven is the guarantee plus the allowed expense, got {show_p['breakeven_cents']}"
        )

        market = build.read_market(ctx["market"]["id"])
        assert market["committed_guarantee_cents"] == 1_000_000, (
            "the postponed show has left the exposure book, got "
            f"{market['committed_guarantee_cents']}"
        )


# ---------------------------------------------------------------------------
# Venue occupancy: the half-open interval [load_in_at, load_out_at)
# ---------------------------------------------------------------------------

ANCHOR_LOAD_IN = "2026-10-09T14:00:00.000Z"
ANCHOR_LOAD_OUT = "2026-10-10T08:00:00.000Z"
ANCHOR_EVENT = "2026-10-10T02:00:00.000Z"


def _anchored_venue(api, build) -> Dict[str, Any]:
    """One building holding a single PLANNED show over [10-09 14:00, 10-10 08:00)."""
    build.set_clock("2026-08-01T00:00:00.000Z")
    market = build.market(
        name="Cascade Basin", region_code="CSB", guarantee_exposure_limit_cents=20_000_000
    )
    artist = build.artist(name="Verdant Coil", tier="THEATER")
    venue = build.venue(market["id"], name="Cedar Room", gross_capacity=1_200)
    anchor = build.show(
        artist["id"],
        venue["id"],
        event_at=ANCHOR_EVENT,
        load_in_at=ANCHOR_LOAD_IN,
        load_out_at=ANCHOR_LOAD_OUT,
        announce_at="2026-08-15T15:00:00.000Z",
        venue_arrangement="RENTAL",
        rental_fee_cents=250_000,
    )
    assert anchor["show_status"] == "PLANNED", (
        f"a newly booked show starts PLANNED, got {anchor['show_status']}"
    )
    return {"market": market, "artist": artist, "venue": venue, "anchor": anchor}


def _probe_payload(
    ctx: Dict[str, Any], event_at: str, load_in_at: str, load_out_at: str
) -> Dict[str, Any]:
    return f.show_payload(
        ctx["artist"]["id"],
        ctx["venue"]["id"],
        event_at=event_at,
        load_in_at=load_in_at,
        load_out_at=load_out_at,
        announce_at="2026-08-15T15:00:00.000Z",
        venue_arrangement="RENTAL",
        rental_fee_cents=250_000,
    )


def _show_ids_at_venue(api, build, venue_id: str) -> List[str]:
    rows, _meta = validate_paginated(api.list_shows(build.buyer, venue_id=venue_id))
    return [row["id"] for row in rows]


class TestVenueLoadWindowHalfOpenOverlap:
    """One millisecond decides the answer; exact adjacency is a pass."""

    @pytest.mark.parametrize(
        "label,event_at,load_in_at,load_out_at",
        [
            (
                "one millisecond before the anchor loads out",
                "2026-10-10T20:00:00.000Z",
                "2026-10-10T07:59:59.999Z",
                "2026-10-11T02:00:00.000Z",
            ),
            (
                "one millisecond after the anchor loads in",
                "2026-10-09T08:00:00.000Z",
                "2026-10-09T02:00:00.000Z",
                "2026-10-09T14:00:00.001Z",
            ),
        ],
    )
    def test_a_single_millisecond_of_overlap_is_a_window_conflict(
        self, api, build, label, event_at, load_in_at, load_out_at
    ):
        """PRD 3.1: "the new show's half-open interval from `load_in_at` up to but
        not including `load_out_at` must not overlap the interval of any other
        show at the same venue whose `show_status` is anything other than
        `CANCELLED` or `RESCHEDULED`; an overlap yields
        `ERR_VENUE_WINDOW_CONFLICT`".

        Design: Difficulty/resource_temporal_overlap/venue_load_window_half_open_overlap_rejects_at_one_millisecond
        """
        ctx = _anchored_venue(api, build)
        validate_error(
            api.create_show(
                _probe_payload(ctx, event_at, load_in_at, load_out_at), build.buyer
            ),
            E.ERR_VENUE_WINDOW_CONFLICT,
        )
        assert _show_ids_at_venue(api, build, ctx["venue"]["id"]) == [
            ctx["anchor"]["id"]
        ], f"the refused booking ({label}) must have persisted nothing"

    @pytest.mark.parametrize(
        "label,event_at,load_in_at,load_out_at",
        [
            (
                "loading in exactly when the anchor loads out",
                "2026-10-10T20:00:00.000Z",
                "2026-10-10T08:00:00.000Z",
                "2026-10-11T02:00:00.000Z",
            ),
            (
                "loading out exactly when the anchor loads in",
                "2026-10-09T08:00:00.000Z",
                "2026-10-09T02:00:00.000Z",
                "2026-10-09T14:00:00.000Z",
            ),
        ],
    )
    def test_exact_adjacency_at_either_end_is_accepted(
        self, api, build, label, event_at, load_in_at, load_out_at
    ):
        """PRD 3.1: "Exact adjacency is deliberately permitted — one show's
        `load_out_at` may equal the next show's `load_in_at`, because the trucks
        pass in the alley."

        Design: Difficulty/resource_temporal_overlap/venue_load_window_half_open_overlap_rejects_at_one_millisecond
        """
        ctx = _anchored_venue(api, build)
        created = validate_success(
            api.create_show(
                _probe_payload(ctx, event_at, load_in_at, load_out_at), build.buyer
            ),
            201,
        )
        assert created["show_status"] == "PLANNED", (
            f"the adjacent booking ({label}) must be created PLANNED, "
            f"got {created['show_status']}"
        )
        assert created["venue_id"] == ctx["venue"]["id"]
        assert set(_show_ids_at_venue(api, build, ctx["venue"]["id"])) == {
            ctx["anchor"]["id"],
            created["id"],
        }, "both the anchor and the adjacent booking must survive"

    def test_the_millisecond_probe_fits_once_it_stops_touching_the_anchor(self, api, build):
        """PRD 3.1: "Exact adjacency is deliberately permitted — one show's
        `load_out_at` may equal the next show's `load_in_at`, because the trucks
        pass in the alley."

        Design: Difficulty/resource_temporal_overlap/venue_load_window_half_open_overlap_rejects_at_one_millisecond
        """
        ctx = _anchored_venue(api, build)
        overlapping = _probe_payload(
            ctx,
            "2026-10-10T20:00:00.000Z",
            "2026-10-10T07:59:59.999Z",
            "2026-10-11T02:00:00.000Z",
        )
        validate_error(api.create_show(overlapping, build.buyer), E.ERR_VENUE_WINDOW_CONFLICT)

        overlapping["load_in_at"] = "2026-10-10T08:00:00.000Z"
        created = validate_success(api.create_show(overlapping, build.buyer), 201)
        assert created["load_in_at"].startswith("2026-10-10T08:00:00"), (
            f"the accepted booking loads in at the anchor's load out, got {created['load_in_at']}"
        )

    def test_a_cancelled_show_releases_its_venue_window(self, api, build):
        """PRD 3.1: "the new show's half-open interval from `load_in_at` up to but
        not including `load_out_at` must not overlap the interval of any other
        show at the same venue whose `show_status` is anything other than
        `CANCELLED` or `RESCHEDULED`; an overlap yields
        `ERR_VENUE_WINDOW_CONFLICT`".

        Design: Difficulty/resource_temporal_overlap/venue_load_window_half_open_overlap_rejects_at_one_millisecond
        """
        ctx = _anchored_venue(api, build)
        inside = _probe_payload(
            ctx,
            "2026-10-09T20:00:00.000Z",
            "2026-10-09T15:00:00.000Z",
            "2026-10-10T03:00:00.000Z",
        )
        validate_error(api.create_show(inside, build.buyer), E.ERR_VENUE_WINDOW_CONFLICT)

        build.cancellation_event(ctx["anchor"]["id"], kind="CANCELLED")
        cancelled = build.read_show(ctx["anchor"]["id"])
        assert cancelled["show_status"] == "CANCELLED", (
            f"the anchor must be pulled before the window frees up, got {cancelled['show_status']}"
        )

        created = validate_success(api.create_show(inside, build.buyer), 201)
        assert created["show_status"] == "PLANNED", (
            "a cancelled show no longer occupies the building, got "
            f"{created['show_status']}"
        )


# ---------------------------------------------------------------------------
# Artist routing: a symmetric 36 hour point distance between event instants
# ---------------------------------------------------------------------------

ROUTING_DATES = {
    # the reference night
    "anchor": (
        "2026-10-10T02:00:00.000Z",
        "2026-10-09T14:00:00.000Z",
        "2026-10-10T08:00:00.000Z",
    ),
    # exactly 36 hours after the anchor
    "plus_36h": (
        "2026-10-11T14:00:00.000Z",
        "2026-10-11T02:00:00.000Z",
        "2026-10-11T20:00:00.000Z",
    ),
    # exactly 36 hours before the anchor
    "minus_36h": (
        "2026-10-08T14:00:00.000Z",
        "2026-10-08T02:00:00.000Z",
        "2026-10-08T20:00:00.000Z",
    ),
    # 25 hours before the anchor
    "minus_25h": (
        "2026-10-09T01:00:00.000Z",
        "2026-10-08T13:00:00.000Z",
        "2026-10-09T07:00:00.000Z",
    ),
    # 12 hours after the plus_36h night, 48 hours after the anchor
    "twelve_hours_after_plus_36h": (
        "2026-10-12T02:00:00.000Z",
        "2026-10-11T14:00:00.000Z",
        "2026-10-12T08:00:00.000Z",
    ),
}


def _routed_artist(api, build, keys: List[str]) -> Dict[str, Any]:
    """One act with a submitted 1,000,000 offer on each requested night.

    Every night gets its own building, so venue occupancy can never be the
    reason a booking is refused, and the market ceiling is 20,000,000, so the
    exposure check can never be the reason either.
    """
    build.set_clock("2026-08-01T00:00:00.000Z")
    market = build.market(
        name="Great Lakes", region_code="GRL", guarantee_exposure_limit_cents=20_000_000
    )
    artist = build.artist(name="Marble Arch", tier="ARENA")
    shows: Dict[str, Any] = {}
    offers: Dict[str, Any] = {}
    for index, key in enumerate(keys, start=1):
        event_at, load_in_at, load_out_at = ROUTING_DATES[key]
        venue = build.venue(
            market["id"], name=f"Routing Hall {index}", gross_capacity=1_500
        )
        show = build.show(
            artist["id"],
            venue["id"],
            event_at=event_at,
            load_in_at=load_in_at,
            load_out_at=load_out_at,
            announce_at="2026-08-15T15:00:00.000Z",
            venue_arrangement="RENTAL",
            rental_fee_cents=250_000,
        )
        shows[key] = show
        offers[key] = build.submitted_offer(
            show["id"],
            deal_structure="FLAT_GUARANTEE",
            guarantee_cents=1_000_000,
            deposit_cents=0,
            expense_cap_cents=1_000_000,
        )
    return {"market": market, "artist": artist, "shows": shows, "offers": offers}


class TestArtistRestBufferIsASymmetricPointDistance:
    """36 hours is measured between event instants, in either direction."""

    def test_exactly_thirty_six_hours_is_permitted_on_both_sides(self, api, build):
        """PRD 3.3: "For every other show of the same act whose `show_status` is
        `CONFIRMED`, `ON_SALE`, `PERFORMED` or `POSTPONED`, the absolute
        difference between that show's `event_at` and this show's `event_at` must
        be at least 36 hours — a day and a half of rest and travel. A gap of
        exactly 36 hours is permitted; anything shorter yields
        `ERR_ARTIST_ROUTING_CONFLICT` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/artist_rest_buffer_is_a_symmetric_point_distance_not_an_interval
        """
        ctx = _routed_artist(api, build, ["anchor", "plus_36h", "minus_36h"])
        for key in ("anchor", "plus_36h", "minus_36h"):
            accepted = validate_success(
                api.accept_offer(
                    ctx["offers"][key]["id"], build.artist_rep(ctx["artist"]["id"])
                )
            )
            assert accepted["status"] == "ACCEPTED", (
                f"the {key} night sits at least 36 hours from every other date, "
                f"got offer status {accepted['status']}"
            )
            show = build.read_show(ctx["shows"][key]["id"])
            assert show["show_status"] == "CONFIRMED", (
                f"the {key} night must move PLANNED to CONFIRMED, got {show['show_status']}"
            )
            assert show["committed_guarantee_cents"] == 1_000_000, (
                f"the {key} night commits its guarantee, got {show['committed_guarantee_cents']}"
            )

        artist = build.read_artist(ctx["artist"]["id"])
        assert artist["confirmed_show_count"] == 3, (
            f"all three nights are confirmed, got {artist['confirmed_show_count']}"
        )
        market = build.read_market(ctx["market"]["id"])
        assert market["committed_guarantee_cents"] == 3_000_000
        assert market["exposure_utilization_pct"] == pytest.approx(15.00, abs=0.01)
        assert market["risk_posture"] == "OPEN"

    def test_a_gap_shorter_than_thirty_six_hours_is_refused(self, api, build):
        """PRD 3.3: "A gap of exactly 36 hours is permitted; anything shorter
        yields `ERR_ARTIST_ROUTING_CONFLICT` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/artist_rest_buffer_is_a_symmetric_point_distance_not_an_interval
        """
        ctx = _routed_artist(api, build, ["anchor", "minus_25h"])
        validate_success(
            api.accept_offer(
                ctx["offers"]["anchor"]["id"], build.artist_rep(ctx["artist"]["id"])
            )
        )

        validate_error(
            api.accept_offer(
                ctx["offers"]["minus_25h"]["id"], build.artist_rep(ctx["artist"]["id"])
            ),
            E.ERR_ARTIST_ROUTING_CONFLICT,
        )

        refused_offer = build.read_offer(ctx["offers"]["minus_25h"]["id"])
        assert refused_offer["status"] == "SUBMITTED", (
            f"the refused offer must stay SUBMITTED, got {refused_offer['status']}"
        )
        assert refused_offer["accepted_by_user_id"] is None, (
            "no accepting rep may be stamped on a refused acceptance"
        )
        refused_show = build.read_show(ctx["shows"]["minus_25h"]["id"])
        assert refused_show["show_status"] == "PLANNED", (
            f"the refused night must stay PLANNED, got {refused_show['show_status']}"
        )
        assert refused_show["committed_guarantee_cents"] == 0, (
            f"no guarantee may be committed, got {refused_show['committed_guarantee_cents']}"
        )
        market = build.read_market(ctx["market"]["id"])
        assert market["committed_guarantee_cents"] == 1_000_000, (
            f"only the anchor is on the book, got {market['committed_guarantee_cents']}"
        )
        artist = build.read_artist(ctx["artist"]["id"])
        assert artist["confirmed_show_count"] == 1, (
            f"only the anchor is confirmed, got {artist['confirmed_show_count']}"
        )

    def test_the_buffer_is_measured_from_the_nearest_night_not_from_the_first(self, api, build):
        """PRD 3.3: "For every other show of the same act whose `show_status` is
        `CONFIRMED`, `ON_SALE`, `PERFORMED` or `POSTPONED`, the absolute
        difference between that show's `event_at` and this show's `event_at` must
        be at least 36 hours".

        Design: Difficulty/resource_temporal_overlap/artist_rest_buffer_is_a_symmetric_point_distance_not_an_interval
        """
        ctx = _routed_artist(
            api, build, ["anchor", "plus_36h", "twelve_hours_after_plus_36h"]
        )
        rep = build.artist_rep(ctx["artist"]["id"])
        validate_success(api.accept_offer(ctx["offers"]["anchor"]["id"], rep))
        validate_success(api.accept_offer(ctx["offers"]["plus_36h"]["id"], rep))

        # 48 hours clear of the anchor, but only 12 hours from the second night.
        validate_error(
            api.accept_offer(
                ctx["offers"]["twelve_hours_after_plus_36h"]["id"], rep
            ),
            E.ERR_ARTIST_ROUTING_CONFLICT,
        )
        market = build.read_market(ctx["market"]["id"])
        assert market["committed_guarantee_cents"] == 2_000_000, (
            f"only the two accepted nights are committed, got {market['committed_guarantee_cents']}"
        )

    def test_a_postponed_night_keeps_blocking_the_calendar_it_has_left_the_book(
        self, api, build
    ):
        """PRD 3.3: "Note carefully that this routing set **includes**
        `POSTPONED`: the act still holds that night while a replacement date is
        being found, so a postponed show keeps blocking the calendar even though,
        as described below, it has already left the market's exposure book."

        Design: Difficulty/resource_temporal_overlap/artist_rest_buffer_is_a_symmetric_point_distance_not_an_interval
        """
        ctx = _routed_artist(
            api, build, ["anchor", "plus_36h", "twelve_hours_after_plus_36h"]
        )
        rep = build.artist_rep(ctx["artist"]["id"])
        validate_success(api.accept_offer(ctx["offers"]["anchor"]["id"], rep))
        validate_success(api.accept_offer(ctx["offers"]["plus_36h"]["id"], rep))
        validate_error(
            api.accept_offer(ctx["offers"]["twelve_hours_after_plus_36h"]["id"], rep),
            E.ERR_ARTIST_ROUTING_CONFLICT,
        )

        build.cancellation_event(ctx["shows"]["plus_36h"]["id"], kind="POSTPONED")
        postponed = build.read_show(ctx["shows"]["plus_36h"]["id"])
        assert postponed["show_status"] == "POSTPONED", (
            f"the blocking night must be POSTPONED, got {postponed['show_status']}"
        )
        market = build.read_market(ctx["market"]["id"])
        assert market["committed_guarantee_cents"] == 1_000_000, (
            "the postponed night has left the exposure book, got "
            f"{market['committed_guarantee_cents']}"
        )

        validate_error(
            api.accept_offer(ctx["offers"]["twelve_hours_after_plus_36h"]["id"], rep),
            E.ERR_ARTIST_ROUTING_CONFLICT,
        )
        still_planned = build.read_show(
            ctx["shows"]["twelve_hours_after_plus_36h"]["id"]
        )
        assert still_planned["show_status"] == "PLANNED", (
            f"the crowded night is still unbookable, got {still_planned['show_status']}"
        )

    def test_a_cancelled_night_releases_the_calendar(self, api, build):
        """PRD 3.3: "For every other show of the same act whose `show_status` is
        `CONFIRMED`, `ON_SALE`, `PERFORMED` or `POSTPONED`, the absolute
        difference between that show's `event_at` and this show's `event_at` must
        be at least 36 hours".

        Design: Difficulty/resource_temporal_overlap/artist_rest_buffer_is_a_symmetric_point_distance_not_an_interval
        """
        ctx = _routed_artist(api, build, ["anchor", "minus_25h"])
        rep = build.artist_rep(ctx["artist"]["id"])
        validate_success(api.accept_offer(ctx["offers"]["anchor"]["id"], rep))
        validate_error(
            api.accept_offer(ctx["offers"]["minus_25h"]["id"], rep),
            E.ERR_ARTIST_ROUTING_CONFLICT,
        )

        build.cancellation_event(ctx["shows"]["anchor"]["id"], kind="CANCELLED")
        assert build.read_show(ctx["shows"]["anchor"]["id"])["show_status"] == "CANCELLED"

        accepted = validate_success(
            api.accept_offer(ctx["offers"]["minus_25h"]["id"], rep)
        )
        assert accepted["status"] == "ACCEPTED", (
            f"a cancelled night is outside the routing set, got {accepted['status']}"
        )
        market = build.read_market(ctx["market"]["id"])
        assert market["committed_guarantee_cents"] == 1_000_000, (
            f"the cancelled night came off as the new one went on, got {market['committed_guarantee_cents']}"
        )
        assert market["exposure_utilization_pct"] == pytest.approx(5.00, abs=0.01)
        assert market["risk_posture"] == "OPEN"
        artist = build.read_artist(ctx["artist"]["id"])
        assert artist["confirmed_show_count"] == 1, (
            f"exactly one night is confirmed, got {artist['confirmed_show_count']}"
        )
