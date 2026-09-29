"""Cascades that run several levels deep from one call.

Each test here drives a single endpoint and then walks the chain of rows the
contract says that one call must rewrite, checking every hop is caused by the
one before it rather than frozen at its pre-call value.
"""

from typing import Any, Dict

import pytest

from test_helpers import (
    ACCOUNTANT_BOB,
    assert_market_exposure,
    assert_version_bumped_by,
    validate_success,
)


# ---------------------------------------------------------------------------
# Instance setups
# ---------------------------------------------------------------------------


def _hospitality_line_with_verified_invoice(build) -> Dict[str, Any]:
    """A rental show on sale with one hospitality line and one verified invoice.

    Zero facility fee and zero ticket tax at a 1200-seat pavilion, a
    FLAT_GUARANTEE of 5,000,000 against a 2,000,000 expense cap, 300 of 1000 GA
    seats sold at 2000 so ``adjusted_gross_cents`` is 585,000, one HOSPITALITY
    line budgeted at 200,000 and artist-deductible, and one 260,000 invoice on
    that line already verified and not yet approved.
    """
    ctx = build.on_sale_show(
        tiers=[{"tier_name": "GA", "price_cents": 2_000, "allocation_qty": 1_000}],
        announce_at="2026-08-08T15:00:00.000Z",
        deal_structure="FLAT_GUARANTEE",
        guarantee_cents=5_000_000,
        deposit_cents=0,
        expense_cap_cents=2_000_000,
        guarantee_exposure_limit_cents=10_000_000,
        gross_capacity=1_200,
        facility_fee_cents_per_ticket=0,
        ticket_tax_pct=0,
        tier="THEATER",
        market_name="Gulf Coast",
        venue_name="Gulf Pavilion",
        artist_name="Bayou Kings",
        show={
            "event_at": "2026-09-26T02:00:00.000Z",
            "load_in_at": "2026-09-25T14:00:00.000Z",
            "load_out_at": "2026-09-26T08:00:00.000Z",
            "venue_arrangement": "RENTAL",
            "rental_fee_cents": 100_000,
        },
    )
    build.sell(ctx["tiers"][0]["id"], 300)
    line = build.budget_line(
        ctx["show"]["id"],
        category="HOSPITALITY",
        description="catering, dressing rooms and runner",
        budgeted_cents=200_000,
        is_artist_deductible=True,
    )
    ctx["invoice"] = build.verified_invoice(
        ctx["show"]["id"],
        line["id"],
        260_000,
        vendor_name="Crescent Catering",
        invoice_date="2026-09-25",
        documentation_ref="INV-D-0001",
    )
    ctx["line"] = build.read_budget_line(line["id"])
    ctx["show"] = build.read_show(ctx["show"]["id"])
    ctx["market"] = build.read_market(ctx["market"]["id"])
    return ctx


def _versus_offer_awaiting_acceptance(build) -> Dict[str, Any]:
    """A PLANNED co-promote show carrying one SUBMITTED VERSUS offer.

    Market limit 10,000,000 with nothing committed, an act with
    ``confirmed_show_count`` 0, and an offer of 4,000,000 at 70.00 percent
    versus with an 800,000 deposit and a 3,000,000 expense cap. The show has no
    tiers and no budget lines.
    """
    ctx = build.planned_show(
        guarantee_exposure_limit_cents=10_000_000,
        gross_capacity=5_000,
        facility_fee_cents_per_ticket=250,
        ticket_tax_pct=5.00,
        tier="ARENA",
        market_name="Great Plains",
        venue_name="Stockyards Arena",
        artist_name="Prairie Static",
        show={
            "event_at": "2026-12-05T02:00:00.000Z",
            "load_in_at": "2026-12-04T14:00:00.000Z",
            "load_out_at": "2026-12-05T08:00:00.000Z",
            "announce_at": "2026-09-15T15:00:00.000Z",
            "venue_arrangement": "CO_PROMOTE",
            "copromote_venue_share_pct": 20.00,
            "venue_expense_pct_production": 30.00,
            "venue_expense_pct_marketing": 0,
            "venue_expense_pct_staffing": 100.00,
            "venue_expense_pct_hospitality": 0,
        },
    )
    ctx["offer"] = build.submitted_offer(
        ctx["show"]["id"],
        deal_structure="VERSUS",
        guarantee_cents=4_000_000,
        deposit_cents=800_000,
        expense_cap_cents=3_000_000,
        versus_pct=70.00,
    )
    ctx["show"] = build.read_show(ctx["show"]["id"])
    ctx["market"] = build.read_market(ctx["market"]["id"])
    ctx["artist"] = build.read_artist(ctx["artist"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Approving one vendor invoice rewrites the invoice, the line, the show and
# the market
# ---------------------------------------------------------------------------


class TestInvoiceApprovalCascade:
    """POST /vendor-invoices/{id}/approve, walked hop by hop."""

    def test_approval_admits_the_amount_and_escalates_the_line_variance(
        self, api, build
    ):
        """PRD §3.6: "Approving an invoice is the four-hop cascade at the centre of this system."
        PRD §3.6: "the line's `actual_cents` is refreshed to the total `amount_cents` of the line's invoices whose status is `APPROVED`"
        PRD §3.6: "a line budgeted at 200,000 with actual 260,000 lands on 30.00 and goes to `PENDING_APPROVAL` needing a `RISK_OFFICER`."
        PRD §3.6: "Anything above 10.00 percent puts the line in `PENDING_APPROVAL`, sets `settlement_expense_cents` to `budgeted_cents` while the variance is unresolved"

        Design: Difficulty/transitive_cascade/invoice_approval_cascades_four_levels_invoice_line_show_market
        """
        ctx = _hospitality_line_with_verified_invoice(build)
        line_before = ctx["line"]

        invoice = validate_success(
            api.approve_vendor_invoice(ctx["invoice"]["id"], build.accountant_two)
        )

        assert invoice["status"] == "APPROVED", (
            f"hop one: expected APPROVED, got {invoice['status']}"
        )
        assert invoice["approved_by_user_id"] == ACCOUNTANT_BOB, (
            "the approving accountant's opaque X-User-ID must be recorded"
        )

        line = build.read_budget_line(line_before["id"])
        assert line["actual_cents"] == 260_000, (
            "hop two is caused by hop one: only an APPROVED invoice reaches actual_cents"
        )
        assert line["variance_cents"] == 60_000
        assert float(line["variance_pct"]) == pytest.approx(30.00, abs=0.01)
        assert line["variance_status"] == "PENDING_APPROVAL"
        assert line["required_approver_role"] == "RISK_OFFICER"
        assert line["settlement_expense_cents"] == 200_000, (
            "an unresolved variance recognises the budgeted figure, not the actual"
        )
        assert_version_bumped_by(line, line_before, 1)

    def test_recognised_expense_moves_the_show_breakeven_and_market_at_risk(
        self, api, build
    ):
        """PRD §3.6: "the line's new recognised expense recomputes the show's `total_actual_expense_cents`, `budget_posture` and `breakeven_cents`."
        PRD §3.6: "it is the show's `committed_guarantee_cents` plus the **lesser** of two amounts — the sum of `settlement_expense_cents` across the show's artist-deductible lines, and the accepted offer's `expense_cap_cents`."
        PRD §3.6: "it is `VARIANCE_PENDING` whenever **any** line is `PENDING_APPROVAL`, which takes precedence"
        PRD §3.3: "`at_risk_guarantee_cents` is the sum, over the same in-scope set, of the amount by which each show's `breakeven_cents` exceeds its `adjusted_gross_cents`"

        Design: Difficulty/transitive_cascade/invoice_approval_cascades_four_levels_invoice_line_show_market
        """
        ctx = _hospitality_line_with_verified_invoice(build)
        show_before = ctx["show"]
        market_before = ctx["market"]

        assert show_before["breakeven_cents"] == 5_000_000, (
            "pre-trigger baseline: no recognised deductible expense yet"
        )
        assert market_before["at_risk_guarantee_cents"] == 4_415_000, (
            "pre-trigger baseline: 5000000 breakeven less 585000 adjusted gross"
        )

        validate_success(
            api.approve_vendor_invoice(ctx["invoice"]["id"], build.accountant_two)
        )

        show = build.read_show(show_before["id"])
        assert show["total_actual_expense_cents"] == 260_000
        assert show["budget_posture"] == "VARIANCE_PENDING"
        assert show["breakeven_cents"] == 5_200_000, (
            "hop three: 5000000 guarantee plus the lesser of 200000 recognised "
            "and the 2000000 expense cap"
        )
        assert_version_bumped_by(show, show_before, 1)

        market = build.read_market(market_before["id"])
        assert market["at_risk_guarantee_cents"] == 4_615_000, (
            "hop four: the new 5200000 breakeven less the show's 585000 adjusted gross"
        )
        assert (
            market["at_risk_guarantee_cents"]
            - market_before["at_risk_guarantee_cents"]
            == 200_000
        ), "the at-risk book moved by exactly the newly recognised expense"
        assert_version_bumped_by(market, market_before, 1)

    def test_expense_cascade_leaves_the_revenue_ladder_and_committed_book_alone(
        self, api, build
    ):
        """PRD §3.3: "Over that set, `committed_guarantee_cents` is the sum of each in-scope show's `committed_guarantee_cents`."
        PRD §3.6: "A show's `total_budgeted_expense_cents` is the sum of `budgeted_cents` over its lines whose `status` is not `VOID`, and its `total_actual_expense_cents` is the sum of `actual_cents` over the same set — the invoiced reality."
        PRD §2.10: "An approved vendor invoice changes a `BudgetLine`'s actual and recognised expense, which changes that line's variance state, which changes its `Show`'s expense totals, budget posture and breakeven, which changes its market's at-risk exposure and risk posture."

        Design: Difficulty/transitive_cascade/invoice_approval_cascades_four_levels_invoice_line_show_market
        """
        ctx = _hospitality_line_with_verified_invoice(build)

        validate_success(
            api.approve_vendor_invoice(ctx["invoice"]["id"], build.accountant_two)
        )

        show = build.read_show(ctx["show"]["id"])
        assert show["adjusted_gross_cents"] == 585_000, (
            "the expense cascade never touches the receipts waterfall"
        )
        assert show["total_budgeted_expense_cents"] == 200_000, (
            "approving an invoice moves actual and recognised expense, never the budget"
        )

        market = build.read_market(ctx["market"]["id"])
        assert_market_exposure(market, 5_000_000, 50.00, "OPEN")


# ---------------------------------------------------------------------------
# Accepting one offer confirms the show and then fans out to the act and the
# market at the same level
# ---------------------------------------------------------------------------


class TestOfferAcceptanceCascade:
    """POST /offers/{offer_id}/accept, walked hop by hop."""

    def test_acceptance_confirms_the_show_and_books_its_guarantee(self, api, build):
        """PRD §3.3: "the offer moves `SUBMITTED → ACCEPTED` and, in the same request, the show moves `PLANNED → CONFIRMED`."
        PRD §3.3: "The offer's `accepted_by_user_id` records the accepting rep's `X-User-ID`."
        PRD §3.3: "The show's `committed_guarantee_cents` is set to the accepted offer's `guarantee_cents` — this field is defined as the guarantee of the single offer on the show whose status is `ACCEPTED`, and 0 when no such offer exists."
        PRD §3.4: "Going on sale is a single call by a `TalentBuyer` that advances **both** of a show's status dimensions at once"

        Design: Difficulty/transitive_cascade/offer_acceptance_cascades_three_levels_offer_show_artist_and_market
        """
        ctx = _versus_offer_awaiting_acceptance(build)
        artist_id = ctx["artist"]["id"]

        offer = validate_success(
            api.accept_offer(ctx["offer"]["id"], build.artist_rep(artist_id))
        )

        assert offer["status"] == "ACCEPTED", (
            f"hop one: expected ACCEPTED, got {offer['status']}"
        )
        assert offer["accepted_by_user_id"] == artist_id

        show = build.read_show(ctx["show"]["id"])
        assert show["show_status"] == "CONFIRMED", (
            "hop two is caused by hop one: the show confirms in the same request"
        )
        assert show["committed_guarantee_cents"] == 4_000_000
        assert show["sales_status"] == "PRE_SALE", (
            "confirming a date does not open ticketing"
        )

    def test_confirmation_recomputes_the_show_breakeven_and_projected_net(
        self, api, build
    ):
        """PRD §3.3: "That change cascades: the show's `breakeven_cents` and `projected_promoter_net_cents` are recomputed"
        PRD §3.6: "The show's `breakeven_cents` is derived here too: it is the show's `committed_guarantee_cents` plus the **lesser** of two amounts — the sum of `settlement_expense_cents` across the show's artist-deductible lines, and the accepted offer's `expense_cap_cents`."
        PRD §3.7: "it is the show's `projected_adjusted_gross_cents` less its `committed_guarantee_cents` less its `total_budgeted_expense_cents`, and it may be negative."

        Design: Difficulty/transitive_cascade/offer_acceptance_cascades_three_levels_offer_show_artist_and_market
        """
        ctx = _versus_offer_awaiting_acceptance(build)

        validate_success(
            api.accept_offer(ctx["offer"]["id"], build.artist_rep(ctx["artist"]["id"]))
        )

        show = build.read_show(ctx["show"]["id"])
        assert show["breakeven_cents"] == 4_000_000, (
            "the guarantee plus zero recognised deductible expense"
        )
        assert show["projected_adjusted_gross_cents"] == 0, (
            "the show has no tiers, so nothing is sellable yet"
        )
        assert show["projected_promoter_net_cents"] == -4_000_000, (
            "0 projected gross less the 4000000 guarantee less 0 budgeted expense"
        )

    def test_acceptance_fans_out_to_the_act_and_the_market_in_one_call(
        self, api, build
    ):
        """PRD §3.3: "The act's `confirmed_show_count` increases by 1. The `version` of the offer, the show, the artist and the market each increment by 1."
        PRD §3.3: "`exposure_utilization_pct` is the market's `committed_guarantee_cents` multiplied by 100, divided by its `guarantee_exposure_limit_cents`, rounded half up to two decimal places."
        PRD §3.3: "`risk_posture` is then banded from that **rounded** percentage: `OPEN` when it is at most 70, `WATCH` when it is greater than 70 and at most 90, `RESTRICTED` when it is greater than 90 and strictly below 100, and `FROZEN` at 100 or above."

        Design: Difficulty/transitive_cascade/offer_acceptance_cascades_three_levels_offer_show_artist_and_market
        """
        ctx = _versus_offer_awaiting_acceptance(build)
        offer_before = ctx["offer"]
        show_before = ctx["show"]
        artist_before = ctx["artist"]
        market_before = ctx["market"]
        assert artist_before["confirmed_show_count"] == 0

        offer = validate_success(
            api.accept_offer(offer_before["id"], build.artist_rep(artist_before["id"]))
        )

        artist = build.read_artist(artist_before["id"])
        assert artist["confirmed_show_count"] == 1, (
            "one branch of the fan-out: the act now holds one confirmed date"
        )

        market = build.read_market(market_before["id"])
        assert_market_exposure(market, 4_000_000, 40.00, "OPEN")
        assert market["at_risk_guarantee_cents"] == 4_000_000, (
            "the whole breakeven is at risk while nothing has sold"
        )

        show = build.read_show(show_before["id"])
        assert_version_bumped_by(offer, offer_before, 1)
        assert_version_bumped_by(show, show_before, 1)
        assert_version_bumped_by(artist, artist_before, 1)
        assert_version_bumped_by(market, market_before, 1)

    def test_acceptance_leaves_the_trailing_settled_index_at_zero(self, api, build):
        """PRD §3.3: "Backward-looking by design: a market with no settled show reports 0."
        PRD §3.3: "A market also carries `settled_show_count`, the count of its shows whose settlement has reached `PAID`."
        PRD §3.3: "Shows that are `CANCELLED`, `RESCHEDULED`, `PLANNED` or `CONFIRMED` appear in neither valuation."

        Design: Difficulty/transitive_cascade/offer_acceptance_cascades_three_levels_offer_show_artist_and_market
        """
        ctx = _versus_offer_awaiting_acceptance(build)

        validate_success(
            api.accept_offer(ctx["offer"]["id"], build.artist_rep(ctx["artist"]["id"]))
        )

        market = build.read_market(ctx["market"]["id"])
        assert market["settled_show_count"] == 0, (
            "no settlement has reached PAID, so the count stays at zero"
        )
        assert market["performance_index"] == 0, (
            "a CONFIRMED show enters neither valuation, so the trailing index "
            "keeps its zero-denominator default"
        )
