"""Two calculations that each run twice over the same row and must diverge.

The credit's exposure figure is computed once at draft time with the tolerance and the
tenor forced to zero, and again at issuance with both honoured; the settlement waterfall
is computed once for a sight honour and again for a negotiation. Each pair shares its
inputs, so any implementation that runs a single code path lands on one answer twice.
"""

from prd_bench_local_runner.testing import validate_success
from test_helpers import (
    api_client,
    assert_charge_sum,
    assert_chargeable_sum,
    assert_facility_ledger,
    assert_issuance_charges,
    assert_net_proceeds_identity,
    assert_settlement_waterfall,
    complying_presentation,
    factories,
    issued_credit,
    lodge_claim,
    set_clock,
    settle_claim,
    setup_parties,
    trade_finance_officer_headers,
)
from test_helpers.fixtures import approved_credit, draft_credit, issue_credit


def _usance_parties():
    """A 200,000,000 facility carrying a 20 percent collateral policy, no collateral posted."""
    return setup_parties(
        facility={"limit_cents": 200000000, "collateral_required_pct": 20},
        bank={
            "country_code": "SG",
            "country_risk_score": 25,
            "credit_rating": "A",
            "confirmation_appetite_cents": 200000000,
        },
        beneficiary={"country_code": "SG"},
    )


USANCE_CREDIT_TERMS = {
    "amount_cents": 100000000,
    "available_by": "ACCEPTANCE",
    "tenor_days": 90,
    "tolerance_pct": 5,
    "incoterm": "FOB",
    "latest_shipment_date": "2026-10-31",
    "expiry_date": "2026-11-30",
    "presentation_period_days": 21,
}

USANCE_REQUIREMENTS = [
    factories.invoice_requirement_payload(),
    factories.transport_requirement_payload(originals_required=3),
]


class TestFacilityExposureProvisionalVersusCommitted:
    """One credit, two runs of the five-step exposure rule."""

    def test_draft_time_estimate_forces_tolerance_and_tenor_to_zero(self, clock):
        """A draft's provisional estimate ignores the tolerance and the tenor it declares.

        PRD 3.2: "The provisional estimate is computed by the same five-step exposure rule
        the bank uses at issuance, but run with the tolerance and the tenor deliberately
        forced to zero, because a draft is not yet an undertaking."

        Design: Difficulty/dual_variant_calc/facility_allocation_provisional_vs_committed
        """
        ctx = draft_credit(_usance_parties(), USANCE_REQUIREMENTS, **USANCE_CREDIT_TERMS)

        assert ctx.credit["provisional_allocation_cents"] == 100000000
        assert ctx.credit["max_drawable_cents"] == 105000000
        facility = ctx.refresh_facility()
        assert_facility_ledger(facility, allocated_cents=0, available_cents=200000000)

    def test_issuance_run_honours_tolerance_and_tenor_and_prices_the_commission(self, clock):
        """Issuance recomputes the same rule in earnest and the two answers diverge.

        PRD 3.3: "For identical inputs this always returns a figure at least as large as
        the provisional estimate, and a strictly larger one whenever `tolerance_pct` or
        `tenor_days` is above zero."

        Design: Difficulty/dual_variant_calc/facility_allocation_provisional_vs_committed
        """
        ctx = approved_credit(_usance_parties(), USANCE_REQUIREMENTS, **USANCE_CREDIT_TERMS)
        provisional = ctx.credit["provisional_allocation_cents"]

        issued = validate_success(
            api_client.issue_credit(
                ctx.credit_id, factories.issue_payload(), trade_finance_officer_headers()
            )
        )

        assert_issuance_charges(
            issued,
            max_drawable_cents=105000000,
            gross_exposure_cents=105787500,
            committed_allocation_cents=105787500,
            commission_bps_applied=7,
            base_commission_cents=148103,
            confirmation_charge_cents=0,
            total_charge_cents=148103,
            chargeable_utilisation_cents=105935603,
        )
        assert issued["committed_allocation_cents"] - provisional == 5787500
        assert issued["presentation_deadline_date"] == "2026-11-21"
        assert issued["status"] == "ISSUED"
        assert_charge_sum(issued)
        assert_chargeable_sum(issued)

    def test_only_the_committed_run_debits_the_facility(self, clock):
        """The facility ledger moves by the chargeable figure, not by the draft estimate.

        PRD 3.3: "**Hop two** is caused by hop one: the new open row re-drives the
        facility's exposure ledger, so the facility's `allocated_cents` rises by exactly
        the credit's `chargeable_utilisation_cents`, its `available_cents` falls by the
        same amount, and its `version` increments by one."

        Design: Difficulty/dual_variant_calc/facility_allocation_provisional_vs_committed
        """
        ctx = approved_credit(_usance_parties(), USANCE_REQUIREMENTS, **USANCE_CREDIT_TERMS)
        assert ctx.refresh_facility()["allocated_cents"] == 0

        issue_credit(ctx.credit_id)

        facility = ctx.refresh_facility()
        assert_facility_ledger(
            facility,
            allocated_cents=105935603,
            available_cents=94064397,
            utilisation_posture="OPEN",
            status="ACTIVE",
        )


def _settlement_parties():
    return setup_parties(
        facility={"limit_cents": 50000000},
        bank={
            "country_code": "SG",
            "country_risk_score": 20,
            "credit_rating": "AA",
            "confirmation_appetite_cents": 100000000,
        },
        beneficiary={"country_code": "SG"},
    )


SETTLEMENT_INVOICES = (3001000, 5001000)
SETTLEMENT_DRAWN = 8002000


def _issue_leg(parties, available_by, tenor_days):
    """Issue one leg of the pair; the two legs differ only in availability and tenor."""
    return issued_credit(
        parties,
        amount_cents=10000000,
        available_by=available_by,
        tenor_days=tenor_days,
        latest_shipment_date="2026-10-31",
        expiry_date="2026-11-30",
        presentation_period_days=21,
    )


def _presented_credit(parties, available_by, tenor_days):
    ctx = _issue_leg(parties, available_by, tenor_days)
    set_clock("2026-09-14T09:00:00Z")
    return complying_presentation(ctx, SETTLEMENT_INVOICES)


class TestSettlementProceedsSightVersusNegotiation:
    """Byte-identical presentations under a sight and a negotiation credit."""

    def test_sight_honour_charges_twelve_basis_points_and_no_discount(self, clock):
        """A `PAYMENT` claim on a sight credit is priced as `SIGHT_HONOUR`.

        PRD 3.9: "`SIGHT_HONOUR` applies to a `PAYMENT` claim on a `SIGHT_PAYMENT` credit
        and to every `REIMBURSEMENT` claim: commission at 12 basis points and no discount,
        which for an identical presentation always yields a strictly larger net than the
        negotiation variant."

        Design: Difficulty/dual_variant_calc/settlement_proceeds_sight_vs_negotiation
        """
        pctx = _presented_credit(_settlement_parties(), "SIGHT_PAYMENT", 0)
        assert pctx.presentation["drawn_amount_cents"] == SETTLEMENT_DRAWN

        claim = lodge_claim(pctx, "PAYMENT", SETTLEMENT_DRAWN)
        settled = settle_claim(claim["id"])

        assert_settlement_waterfall(
            settled,
            variant_applied="SIGHT_HONOUR",
            commission_bps_applied=12,
            commission_cents=9602,
            discount_cents=0,
            days_to_maturity=0,
            doc_examination_fee_cents=7502,
            net_proceeds_cents=7984896,
        )
        assert_net_proceeds_identity(settled, SETTLEMENT_DRAWN)
        assert pctx.refresh()["settlement_status"] == "PAID"

    def test_negotiation_charges_twenty_basis_points_plus_a_discount_to_maturity(self, clock):
        """A `NEGOTIATION` claim on the same drawn amount is priced under discount.

        PRD 3.9: "`NEGOTIATION_UNDER_DISCOUNT` applies to a `NEGOTIATION` claim:
        commission at 20 basis points and a discount charged for the whole run from the
        settlement date to `maturity_date` on the 360-day basis, so the same drawn amount
        and the same documents yield materially smaller proceeds."

        Design: Difficulty/dual_variant_calc/settlement_proceeds_sight_vs_negotiation
        """
        pctx = _presented_credit(_settlement_parties(), "NEGOTIATION", 90)
        assert pctx.presentation["drawn_amount_cents"] == SETTLEMENT_DRAWN
        assert pctx.presentation["maturity_date"] == "2026-12-13"

        claim = lodge_claim(pctx, "NEGOTIATION", SETTLEMENT_DRAWN)
        settled = settle_claim(claim["id"])

        assert_settlement_waterfall(
            settled,
            variant_applied="NEGOTIATION_UNDER_DISCOUNT",
            commission_bps_applied=20,
            commission_cents=16004,
            discount_cents=90023,
            days_to_maturity=90,
            doc_examination_fee_cents=7502,
            net_proceeds_cents=7888471,
        )
        assert_net_proceeds_identity(settled, SETTLEMENT_DRAWN)
        assert pctx.refresh()["settlement_status"] == "NEGOTIATED"

    def test_the_two_variants_diverge_on_one_facility_and_one_presentation_shape(self, clock):
        """Both legs run under one facility; only `available_by` differs between them.

        PRD 3.9: "Three variants use that arithmetic differently, and which one applied is
        recorded on the claim as `variant_applied`, whose value is `SIGHT_HONOUR`,
        `NEGOTIATION_UNDER_DISCOUNT` or `ACCEPTANCE_AT_MATURITY`."

        Design: Difficulty/dual_variant_calc/settlement_proceeds_sight_vs_negotiation
        """
        parties = _settlement_parties()
        sight_ctx = _issue_leg(parties, "SIGHT_PAYMENT", 0)
        negotiation_ctx = _issue_leg(parties, "NEGOTIATION", 90)
        set_clock("2026-09-14T09:00:00Z")
        sight = complying_presentation(sight_ctx, SETTLEMENT_INVOICES)
        negotiation = complying_presentation(negotiation_ctx, SETTLEMENT_INVOICES)

        net_sight = settle_claim(lodge_claim(sight, "PAYMENT", SETTLEMENT_DRAWN)["id"])[
            "net_proceeds_cents"
        ]
        net_negotiation = settle_claim(
            lodge_claim(negotiation, "NEGOTIATION", SETTLEMENT_DRAWN)["id"]
        )["net_proceeds_cents"]

        assert net_sight == 7984896
        assert net_negotiation == 7888471
        assert net_sight - net_negotiation == 96425
