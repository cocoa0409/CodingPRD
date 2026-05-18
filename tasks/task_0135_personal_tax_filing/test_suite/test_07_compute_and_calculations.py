"""Compute pipeline — AGI, deductions, regular tax, AMT.

Coverage targets (PRD §3.5):
- DRAFT -> READY_TO_FILE on successful compute.
- AGI is wages + nonemployee comp + interest + dividends + sched_c
  net floor 0 + sched_e net floor 0 + cap gains floored at -300_000
  - half_SE.
- Standard deduction lookup by filing_status (incl. is_blind +150_000).
- Itemized path applies medical floor, SALT cap (input cap), charity
  cap (60% AGI).
- Regular tax brackets pinned (per-slice floor then sum).
- AMT: exemption per filing_status, two-tier rate, floored at 0.
- locked taxpayer blocks compute.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    BRACKETS_SINGLE,
    add_1099_b,
    add_1099_int,
    add_1099_nec,
    add_schedule_a,
    add_schedule_c,
    add_schedule_e,
    add_w2,
    compute_tax_return,
    make_taxpayer_headers,
    re_get_tax_return,
    setup_active_taxpayer_with_draft_return,
    setup_for_dual_variant_deduction,
    setup_simple_w2_return,
    STANDARD_DEDUCTION,
    validate_error,
)


# ===========================================================================
# Basic DRAFT -> READY_TO_FILE — PRD §3.5
# ===========================================================================
class TestComputeBasic:

    def test_compute_transitions_draft_to_ready(self, api):
        """PRD §3.5: "A Taxpayer triggers it on a return that is in
        DRAFT; the return advances to READY_TO_FILE."

        Claim: POST /tax-returns/{id}/compute moves DRAFT to
        READY_TO_FILE.
        """
        taxpayer, _, _ = setup_simple_w2_return(
            wages_cents=4_000_000, federal_withholding_cents=300_000,
        )
        # setup_simple_w2_return leaves the return in DRAFT — but
        # let's verify and then compute.
        tax_return = re_get_tax_return(
            taxpayer,
            api.list_tax_returns(
                make_taxpayer_headers(taxpayer["id"]),
                params={"taxpayer_id": taxpayer["id"]},
            ).json()["data"][0]["id"],
        )
        assert tax_return["status"] == "DRAFT"
        computed = compute_tax_return(taxpayer, tax_return["id"])
        assert computed["status"] == "READY_TO_FILE"

    def test_compute_on_locked_taxpayer_rejected(self, api):
        """PRD §3.5: "Before any arithmetic runs the system verifies
        several preconditions: the owning Taxpayer must be in
        account_status ACTIVE (a locked taxpayer is rejected with
        ERR_TAXPAYER_LOCKED)".

        Claim: compute on a locked taxpayer's DRAFT return ->
        ERR_TAXPAYER_LOCKED.
        """
        taxpayer, tax_return, _ = setup_simple_w2_return(
            wages_cents=1_000_000,
        )
        from test_helpers import compliance_lock
        compliance_lock(taxpayer["id"])
        resp = api.compute_tax_return(
            tax_return["id"], {}, make_taxpayer_headers(taxpayer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_TAXPAYER_LOCKED.value)

    def test_compute_on_ready_state_rejected(self, api):
        """PRD §2.10 priority 7: "The target entity is in a state valid
        for the requested operation (for example, compute requires the
        return to be in DRAFT ...)" -> ERR_INVALID_STATE.

        Claim: second compute on a return already in READY_TO_FILE ->
        ERR_INVALID_STATE.
        """
        taxpayer, tax_return, _ = setup_simple_w2_return(
            wages_cents=1_000_000,
        )
        compute_tax_return(taxpayer, tax_return["id"])
        # Try compute a second time without re-opening to DRAFT first.
        resp = api.compute_tax_return(
            tax_return["id"], {},
            make_taxpayer_headers(taxpayer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# AGI calculation — PRD §3.5 Step 1
# ===========================================================================
class TestAgi:

    def test_w2_only_agi(self, api):
        """PRD §3.5 step 1: "the system first totals raw income across
        all imported documents on the return: total_income_cents is
        the sum of wages_cents across every W2, plus
        nonemployee_comp_cents across every 1099_NEC, plus
        interest_income_cents across every 1099_INT, plus
        ordinary_dividends_cents across every 1099_DIV."

        Claim: single W-2 wages_cents=5_000_000 -> total_income_cents
        = 5_000_000 and agi_cents = 5_000_000 (no SE adjustment).
        """
        taxpayer, _, _ = setup_simple_w2_return(
            wages_cents=5_000_000, federal_withholding_cents=0,
        )
        # Re-read.
        tr = api.list_tax_returns(
            make_taxpayer_headers(taxpayer["id"]),
            params={"taxpayer_id": taxpayer["id"]},
        ).json()["data"][0]
        computed = compute_tax_return(taxpayer, tr["id"])
        assert computed["total_income_cents"] == 5_000_000
        assert computed["agi_cents"] == 5_000_000

    def test_capital_loss_floored_at_minus_3000(self, api):
        """PRD §3.5 step 1: "the capital-gains contribution floored at
        negative 300,000 cents so a net capital loss is deductible
        against ordinary income up to a $3,000 ceiling and no further."

        Claim: a 1099-B losing 1,000,000 cents (long-term) contributes
        only -300,000 cents to total_income_cents.
        """
        taxpayer, tax_return, _ = setup_simple_w2_return(
            wages_cents=5_000_000, federal_withholding_cents=0,
        )
        # Attach a 1099-B with proceeds=100_000, cost=1_100_000 -> -1_000_000.
        add_1099_b(
            taxpayer, tax_return["id"],
            proceeds_cents=100_000, cost_basis_cents=1_100_000,
            holding_period="LONG_TERM",
        )
        # Compute and verify total_income_cents == 5_000_000 - 300_000 = 4_700_000
        computed = compute_tax_return(taxpayer, tax_return["id"])
        assert computed["total_income_cents"] == 4_700_000, (
            f"PRD §3.5: cap loss floored at -300_000; expected "
            f"total_income_cents=4_700_000, got "
            f"{computed['total_income_cents']}"
        )

    def test_schedule_c_negative_net_floored_at_zero_for_agi(self, api):
        """PRD §3.5 step 1: "the Schedule C net (gross receipts minus
        expenses on every Schedule C, summed and floored at zero)".

        Claim: Schedule C with expenses exceeding gross receipts adds
        0 to total income (the loss is not deductible against ordinary
        income via AGI in this simplified model).
        """
        taxpayer, tax_return, _ = setup_simple_w2_return(
            wages_cents=2_000_000, federal_withholding_cents=0,
        )
        add_schedule_c(
            taxpayer, tax_return["id"],
            schedule_c_gross_receipts_cents=100_000,
            schedule_c_expenses_cents=500_000,  # loss
        )
        computed = compute_tax_return(taxpayer, tax_return["id"])
        # Schedule C net is floored at 0 in total_income.
        # SE tax base is also floored, so half-SE adjustment is 0.
        assert computed["total_income_cents"] == 2_000_000


# ===========================================================================
# Standard deduction — PRD §3.5 Step 2
# ===========================================================================
class TestStandardDeduction:

    @pytest.mark.parametrize(
        "filing_status,std",
        [
            ("SINGLE", 1_500_000),
            ("MARRIED_JOINT", 3_000_000),
            ("MARRIED_SEPARATE", 1_500_000),
            ("HEAD_OF_HOUSEHOLD", 2_225_000),
            ("QUALIFYING_SURVIVING_SPOUSE", 3_000_000),
        ],
    )
    def test_standard_deduction_lookup(self, api, filing_status, std):
        """PRD §3.5 step 2: "the system looks up the standard deduction
        from a filing-status table — 1,500,000 cents for SINGLE or
        MARRIED_SEPARATE, 3,000,000 cents for MARRIED_JOINT or
        QUALIFYING_SURVIVING_SPOUSE, and 2,225,000 cents for
        HEAD_OF_HOUSEHOLD".

        Claim: taxable_income = AGI - STD[filing_status] when
        deduction_method=STANDARD.
        """
        taxpayer, tax_return, _ = setup_simple_w2_return(
            wages_cents=5_000_000, federal_withholding_cents=0,
            filing_status=filing_status,
        )
        computed = compute_tax_return(taxpayer, tax_return["id"])
        assert computed["agi_cents"] == 5_000_000
        assert computed["taxable_income_cents"] == 5_000_000 - std

    def test_blind_addon(self, api):
        """PRD §3.5 step 2: "adds a flat 150,000 cents (the blind
        add-on) when the taxpayer's is_blind flag is true."

        Claim: is_blind=True with SINGLE -> deduction is 1_500_000 +
        150_000 = 1_650_000.
        """
        taxpayer, tax_return, _ = setup_simple_w2_return(
            wages_cents=5_000_000, federal_withholding_cents=0,
            filing_status="SINGLE", is_blind=True,
        )
        computed = compute_tax_return(taxpayer, tax_return["id"])
        assert computed["taxable_income_cents"] == (
            5_000_000 - (1_500_000 + 150_000)
        )


# ===========================================================================
# Itemized deduction caps — PRD §3.5 Step 2
# ===========================================================================
class TestItemizedDeduction:

    def test_itemized_basic(self, api):
        """PRD §3.5 step 2: "When the method is ITEMIZED, the system
        reads the Schedule A row attached to the return and applies,
        in this pinned order, a medical floor (multiply agi_cents by
        750 basis points, divide by 10,000 using floor division,
        subtract the result from itemized_medical_cents, floor at
        zero), a SALT cap of 1,000,000 cents on itemized_salt_cents,
        no cap on itemized_mortgage_interest_cents, and a charity cap
        computed as 60 percent of agi_cents using integer floor
        division applied against itemized_charity_cents."

        Claim: AGI=8_000_000, salt=500_000, charity=200_000, no
        medical, no mortgage -> total_itemized=700_000.
        """
        taxpayer, tax_return, _ = setup_for_dual_variant_deduction(
            wages_cents=8_000_000,
            federal_withholding_cents=600_000,
            itemized_salt_cents=500_000,
            itemized_charity_cents=200_000,
            itemized_medical_cents=0,
            itemized_mortgage_interest_cents=0,
        )
        # Switch the return to ITEMIZED.
        from test_helpers import patch_tax_return
        tr_now = re_get_tax_return(taxpayer, tax_return["id"])
        patch_tax_return(
            taxpayer, tax_return["id"],
            deduction_method="ITEMIZED",
            version=tr_now["version"],
        )
        computed = compute_tax_return(taxpayer, tax_return["id"])
        assert computed["agi_cents"] == 8_000_000
        # Itemized: medical_allowed=0, salt=500_000, mortgage=0,
        # charity=200_000 (under 60% of 8M).
        assert computed["taxable_income_cents"] == 8_000_000 - 700_000


# ===========================================================================
# Regular tax brackets — PRD §3.5 Step 3
# ===========================================================================
class TestRegularTax:

    def test_regular_tax_single_low_bracket(self, api):
        """PRD §3.5 step 3: "10 percent (1000 basis points) on the slice
        from 0 up to 1,100,000 cents".

        Claim: SINGLE with taxable_income=1_000_000 -> regular_tax =
        floor(1_000_000 * 1000 / 10000) = 100_000.
        """
        # Use wages just enough to give taxable=1_000_000 after STD.
        # SINGLE STD = 1_500_000 so wages = 1_000_000 + 1_500_000 = 2_500_000.
        taxpayer, tax_return, _ = setup_simple_w2_return(
            wages_cents=2_500_000, federal_withholding_cents=0,
            filing_status="SINGLE",
        )
        computed = compute_tax_return(taxpayer, tax_return["id"])
        assert computed["taxable_income_cents"] == 1_000_000
        # All in bracket 1 at 10%.
        assert computed["regular_tax_cents"] == 100_000


# ===========================================================================
# AMT calculation — PRD §3.5 Step 4
# ===========================================================================
class TestAmt:

    def test_amt_zero_when_low_income(self, api):
        """PRD §3.5 step 4: "amt_cents is the tentative AMT minus
        regular_tax_cents, floored at zero - so when the regular tax
        already exceeds the tentative AMT the AMT add-on is exactly
        zero."

        Claim: low-income SINGLE filer below AMT exemption -> amt_cents == 0.
        """
        taxpayer, tax_return, _ = setup_simple_w2_return(
            wages_cents=3_000_000, federal_withholding_cents=0,
            filing_status="SINGLE",
        )
        computed = compute_tax_return(taxpayer, tax_return["id"])
        # AGI=3_000_000, AMT exemption SINGLE=8_550_000, amt_base=0.
        assert computed["amt_cents"] == 0
