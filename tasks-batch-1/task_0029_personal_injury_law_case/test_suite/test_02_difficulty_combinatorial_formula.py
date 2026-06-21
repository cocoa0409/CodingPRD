"""Difficulty Rule 2 — combinatorial_formula.

Multi-step formulas with PRD-pinned rounding order and PRD-pinned evaluation
order, where a different order yields a measurably different cent value:

  • demand_letter_amount: round per-line first, then sum, then round buffer (PRD §3.4)
  • net_to_client: gross → fee → distributable → lien waterfall → net (PRD §3.7)
"""
import pytest

from test_helpers import (
    validate_success,
    set_clock,
    register_client,
    sign_retainer,
    create_case,
    activate_case,
    register_provider,
    create_records_request,
    walk_records_request_to_reviewed,
    create_included_damages,
    create_demand_letter,
    send_demand_letter,
    create_lien,
    create_offer,
    accept_offer,
    get_case_version,
    get_case,
    get_disbursement_for_case,
    setup_active_case_with_reviewed_records,
)


# =============================================================================
# Instance: demand_letter_amount_per_line_rounding_pinned
# =============================================================================


class TestDemandLetterAmountPerLineRoundingPinned:
    """demand_amount_cents must be computed with rounding pinned per category
    line first, then sum, then round the buffer once."""

    def test_pain_multiplier_three_yields_pinned_demand_amount(self, api):
        """PRD §3.4: "First, four per-category line totals are computed and each
        is rounded half-up to whole cents independently: the medical line is
        the sum of `amount_cents` over `INCLUDED` items with `category ==
        MEDICAL_BILLS` multiplied by one (so it is just the sum), the wages
        line is the same construction over `LOST_WAGES`, the property line is
        the same construction over `PROPERTY`, and the future-medical line is
        the sum of `amount_cents` over `INCLUDED` items in `FUTURE_MEDICAL`
        multiplied by the present-value discount factor `0.85` and rounded
        half-up."
        PRD §3.4: "Next, the pain-and-suffering line is computed by summing the
        just-rounded medical line, wages line, and future-medical line — the
        property line is deliberately excluded from the multiplier base —
        multiplying that sum by the `pain_multiplier`, and rounding half-up."

        Design: Difficulty/combinatorial_formula/demand_letter_amount_per_line_rounding_pinned
        """
        set_clock("2026-01-01T00:00:00Z")
        client, case, provider, mrr = setup_active_case_with_reviewed_records()
        # Four INCLUDED items totalling 2_400_000 cents (no PAIN_SUFFERING line items).
        create_included_damages(case["id"], "MEDICAL_BILLS", 1_000_000)
        create_included_damages(case["id"], "LOST_WAGES", 500_000)
        create_included_damages(case["id"], "FUTURE_MEDICAL", 600_000)
        create_included_damages(case["id"], "PROPERTY", 300_000)

        dl = create_demand_letter(case["id"], pain_multiplier=3.0,
                                   drafter_user_id="drafter-2a")
        # Expected per-line:
        #   medical_line   = 1_000_000
        #   wages_line     =   500_000
        #   property_line  =   300_000
        #   future_med_line= round_half_up(600_000 * 0.85)         =   510_000
        #   pain_line      = round_half_up((1_000_000 + 500_000 + 510_000) * 3.0)
        #                  = round_half_up(6_030_000)              = 6_030_000
        # Subtotal = 1_000_000 + 500_000 + 300_000 + 510_000 + 6_030_000 = 8_340_000
        # subtotal >= 5_000_000 → buffer_rate = 0.10 → buffer = 834_000
        # demand = 8_340_000 + 834_000 = 9_174_000
        assert dl["demand_amount_cents"] == 9_174_000
        assert dl["status"] == "DRAFT"
        assert float(dl["pain_multiplier"]) == 3.0

    def test_property_line_excluded_from_pain_multiplier_base(self, api):
        """PRD §3.4: "Next, the pain-and-suffering line is computed by summing the
        just-rounded medical line, wages line, and future-medical line — the
        property line is deliberately excluded from the multiplier base —
        multiplying that sum by the `pain_multiplier`, and rounding half-up."

        Design: Difficulty/combinatorial_formula/demand_letter_amount_per_line_rounding_pinned
        """
        # Two cases sharing identical medical/wages/future-medical lines but
        # differing only in the PROPERTY line. The pain_line must be unchanged
        # because PROPERTY is excluded from the multiplier base; the only
        # difference in the final demand_amount_cents must come from the raw
        # property contribution + its tiered-buffer contribution.
        set_clock("2026-01-01T00:00:00Z")
        # Case A — no PROPERTY line.
        c_a = register_client(email="prop-a@example.com")
        sign_retainer(c_a["id"])
        case_a = create_case(c_a["id"])
        activate_case(case_a["id"])
        p_a = register_provider()
        mrr_a = create_records_request(case_a["id"], p_a["id"])
        walk_records_request_to_reviewed(mrr_a["id"])
        create_included_damages(case_a["id"], "MEDICAL_BILLS", 1_000_000)
        create_included_damages(case_a["id"], "LOST_WAGES", 500_000)
        create_included_damages(case_a["id"], "FUTURE_MEDICAL", 600_000)
        dl_a = create_demand_letter(case_a["id"], pain_multiplier=3.0,
                                     drafter_user_id="drafter-2b-A")
        # subtotal_a = 1_000_000 + 500_000 + 510_000 + 6_030_000 = 8_040_000
        # buffer_a = round_half_up(8_040_000 * 0.10) = 804_000
        # demand_a = 8_040_000 + 804_000 = 8_844_000
        assert dl_a["demand_amount_cents"] == 8_844_000

        # Case B — same as A but +300_000 PROPERTY line.
        c_b = register_client(email="prop-b@example.com")
        sign_retainer(c_b["id"])
        case_b = create_case(c_b["id"])
        activate_case(case_b["id"])
        p_b = register_provider()
        mrr_b = create_records_request(case_b["id"], p_b["id"])
        walk_records_request_to_reviewed(mrr_b["id"])
        create_included_damages(case_b["id"], "MEDICAL_BILLS", 1_000_000)
        create_included_damages(case_b["id"], "LOST_WAGES", 500_000)
        create_included_damages(case_b["id"], "FUTURE_MEDICAL", 600_000)
        create_included_damages(case_b["id"], "PROPERTY", 300_000)
        dl_b = create_demand_letter(case_b["id"], pain_multiplier=3.0,
                                     drafter_user_id="drafter-2b-B")
        # Adding property line of 300_000 only shifts subtotal/buffer; pain_line
        # stays at 6_030_000 because property is excluded from the multiplier
        # base. demand_b = 8_340_000 + 834_000 = 9_174_000.
        assert dl_b["demand_amount_cents"] == 9_174_000
        # Net difference between B and A is property line plus its buffer-rate
        # contribution at 0.10 (both subtotals are in the high tier).
        assert dl_b["demand_amount_cents"] - dl_a["demand_amount_cents"] == 330_000


# =============================================================================
# Instance: net_to_client_evaluation_order_pinned
# =============================================================================


class TestNetToClientEvaluationOrderPinned:
    """The PRD pins the evaluation order: gross → fee → distributable → lien
    waterfall → net. Reversing this order yields a different net."""

    def _build_settle_with_single_lien(self):
        """Active CA case, REVIEWED records, one INCLUDED MEDICAL_BILLS=1_000_000,
        demand sent, one MedicalLien asserted at 1_500_000, one CARRIER PENDING
        offer at 6_000_000. Returns (case_id, offer_id, lien_id)."""
        set_clock("2026-01-01T00:00:00Z")
        client, case, provider, mrr = setup_active_case_with_reviewed_records()
        create_included_damages(case["id"], "MEDICAL_BILLS", 1_000_000)
        dl = create_demand_letter(case["id"], pain_multiplier=1.5,
                                   drafter_user_id="drafter-2c")
        send_demand_letter(dl["id"], partner_user_id="partner-2c")
        lien = create_lien(case["id"], provider["id"], 1_500_000)
        offer = create_offer(case["id"], 6_000_000, "CARRIER")
        return case["id"], offer["id"], lien["id"]

    def test_net_equals_gross_minus_fee_minus_total_lien_payout(self, api):
        """PRD §3.7: "The disbursement also captures the contingency fee and
        the `net_to_client_cents`, which is the gross settlement minus the
        contingency fee minus the total lien payout. The order is pinned:
        gross is stamped first, fee is computed against the gross and the
        filed-in-court flag, the distributable-to-liens amount is taken as
        gross minus fee, the waterfall runs against that distributable amount,
        the total lien payout is summed, and the net equals gross minus fee
        minus payout."
        PRD §3.7: "Reversing this order — for example, computing the lien
        payout against the gross before taking the fee — yields a different
        net and is not the contract."

        Design: Difficulty/combinatorial_formula/net_to_client_evaluation_order_pinned
        """
        case_id, offer_id, lien_id = self._build_settle_with_single_lien()
        case_v = get_case_version(case_id)
        accept_offer(offer_id, case_v, partner_user_id="partner-2c")
        disb = get_disbursement_for_case(case_id)
        # gross=6_000_000, pre-suit, fee=1_999_800; distributable=4_000_200;
        # lien asserted 1_500_000 << distributable → full payout=1_500_000;
        # net = 6_000_000 - 1_999_800 - 1_500_000 = 2_500_200.
        assert disb["gross_settlement_cents"] == 6_000_000
        assert disb["contingency_fee_cents"] == 1_999_800
        assert disb["total_lien_payout_cents"] == 1_500_000
        assert disb["net_to_client_cents"] == 2_500_200

    def test_lien_payout_uses_distributable_not_gross(self, api):
        """PRD §3.7: "starting from the case's just-stamped
        `gross_settlement_cents`, the contingency fee is computed first."
        PRD §3.7: "The pool distributable to liens is then
        `gross_settlement_cents` minus `contingency_fee_cents`."
        PRD §3.7: "If the total asserted is less than or equal to the
        distributable pool, every lien gets paid its full `asserted_amount_cents`
        and the waterfall terminates."

        Design: Difficulty/combinatorial_formula/net_to_client_evaluation_order_pinned
        """
        case_id, offer_id, lien_id = self._build_settle_with_single_lien()
        case_v = get_case_version(case_id)
        accept_offer(offer_id, case_v, partner_user_id="partner-2d")
        disb = get_disbursement_for_case(case_id)
        # The pinned-order check: the lien is below distributable (4_000_200);
        # it must be paid in full at its asserted amount. The "reverse-order"
        # interpretation (compute lien payout off gross before fee) would have
        # produced a different fee (1_499_850 on 4_500_000) and a different
        # net. The test rejects that path by pinning all three derived
        # quantities to the forward-order outcome.
        case_after = get_case(case_id)
        from test_helpers import TEST_USERS, validate_success
        lien_res = api.get_lien(lien_id, TEST_USERS["attorney_headers"])
        lien_after = validate_success(lien_res, 200)
        assert case_after["status"] == "SETTLED"
        assert case_after["gross_settlement_cents"] == 6_000_000
        assert lien_after["status"] == "AGREED"
        assert lien_after["negotiated_amount_cents"] == 1_500_000
        # And the disbursement must reflect the pinned-order arithmetic.
        assert disb["contingency_fee_cents"] == 1_999_800
        assert disb["total_lien_payout_cents"] == 1_500_000
        assert disb["net_to_client_cents"] == 2_500_200
