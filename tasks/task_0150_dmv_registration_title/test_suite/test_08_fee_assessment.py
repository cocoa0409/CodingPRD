"""Fee assessment: registration fee, sales tax (resident vs non-resident),
processing fee tiers, total_due.

PRD §3.7.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_clock_to,
    approve_owner_to_real_id,
    assess_fees,
    create_owner,
    create_transfer_application,
    create_vehicle,
    current_clock,
    date_for_age,
    drive_vehicle_to_emissions_passed,
    get_transfer_application,
    list_fee_ledger,
    parse_iso,
    revoke_real_id,
    setup_application_at_emissions_passed,
    setup_owner_with_real_id_approved,
    setup_vehicle_for_weight_tier,
    validate_error,
    validate_success,
    verify_vin,
)


# ---------------------------------------------------------------------------
# Registration fee — PRD §3.7
# ---------------------------------------------------------------------------
class TestRegistrationFeeWeightTiers:

    @pytest.mark.parametrize("weight,expected_reg_fee", [
        # PRD §3.7: weight base = 65.00 for <3000; +22 resident surcharge;
        # age 0 → factor 1.00. (curb_weight 2500) → 65*1 + 22 = 87.00
        (2500, 87.00),
        # 4500 lbs → BASE_MID 110.00 → 110*1 + 22 = 132.00
        (4500, 132.00),
        # 6000 lbs is the inclusive HEAVY boundary → 185.00 → 185+22 = 207.00
        (6000, 207.00),
        # 5999 lbs still MID → 132.00 (proves >= 6000 not > 6000)
        (5999, 132.00),
    ])
    def test_weight_tier_boundaries(self, api, weight, expected_reg_fee):
        """PRD §3.7: "if curb_weight_lbs is strictly less than 3000
        pounds, the weight base is 65.00; if it is at least 3000 pounds
        and strictly less than 6000 pounds, the weight base is 110.00;
        if it is at least 6000 pounds, the weight base is 185.00 —
        note that the heavy tier uses the inclusive boundary 6000, not
        strictly greater than 6000."
        PRD §3.7: "The surcharge is 22.00 if Owner.is_resident is true."
        """
        base = setup_vehicle_for_weight_tier(
            curb_weight_lbs=weight,
            model_year=2026,
            residency_state="CA",
            declared_sale_price=20000.00,
            trade_in_value=0.00,
        )
        assess_fees(base["application"]["id"])
        app_after = get_transfer_application(base["application"]["id"])
        # Reg fee is not exposed directly on TransferApplication, only
        # fee_subtotal = reg_fee + sales_tax. For trade_in=0, resident,
        # sale=20000:  sales_tax = 20000 * 0.0725 = 1450.00 — but PRD
        # variant for resident takes max(0, sale - trade_in) so this is
        # 20000 * 0.0725 = 1450.00.
        expected_sales_tax = 20000.00 * 0.0725  # 1450.00
        expected_subtotal = round(expected_reg_fee + expected_sales_tax, 2)
        assert app_after["fee_subtotal"] == pytest.approx(expected_subtotal, abs=0.01), (
            f"fee_subtotal expected {expected_subtotal}, got "
            f"{app_after['fee_subtotal']}"
        )

    def test_non_resident_surcharge_55(self, api):
        """PRD §3.7: "The surcharge is 22.00 if Owner.is_resident is
        true, otherwise it is 55.00."

        For curb_weight 2500, model_year 2026, non-resident:
        reg_fee = 65 * 1.00 + 55 = 120.00.
        Sales tax (non-resident): 20000 * 0.085 = 1700.00.
        fee_subtotal = 1820.00.
        """
        base = setup_application_at_emissions_passed(
            application_type="TITLE_TRANSFER",
            residency_state="NV",
            declared_sale_price=20000.00,
            trade_in_value=5000.00,  # ignored in non-resident variant
            curb_weight_lbs=2500,
            model_year=2026,
        )
        assess_fees(base["application"]["id"])
        app_after = get_transfer_application(base["application"]["id"])
        assert app_after["fee_subtotal"] == pytest.approx(1820.00, abs=0.01)

    def test_age_factor_floor(self, api):
        """PRD §3.7: "the age factor is the larger of 0.50 and the
        value 1.00 minus 0.05 multiplied by the age in years, with the
        0.50 floor preventing arbitrarily old vehicles from
        depreciating below half the base."

        For curb_weight=2500, model_year=1980 (very old → factor
        floored at 0.50), resident:
        reg_fee = 65 * 0.50 + 22 = 54.50.
        sales_tax (resident, trade_in=0): 20000 * 0.0725 = 1450.00.
        fee_subtotal = 1504.50.
        """
        base = setup_application_at_emissions_passed(
            application_type="TITLE_TRANSFER",
            residency_state="CA",
            declared_sale_price=20000.00,
            trade_in_value=0.00,
            curb_weight_lbs=2500,
            model_year=1980,  # ancient
        )
        assess_fees(base["application"]["id"])
        app_after = get_transfer_application(base["application"]["id"])
        expected_subtotal = round(54.50 + 1450.00, 2)
        assert app_after["fee_subtotal"] == pytest.approx(
            expected_subtotal, abs=0.01,
        ), f"got {app_after['fee_subtotal']}, expected {expected_subtotal}"


# ---------------------------------------------------------------------------
# Sales tax dual variants — PRD §3.7
# ---------------------------------------------------------------------------
class TestSalesTaxDualVariants:

    def test_resident_with_trade_in(self, api):
        """PRD §3.7: "In the resident variant, the taxable base is the
        larger of zero and declared_sale_price minus trade_in_value, and
        the sales tax is the taxable base multiplied by the resident
        rate of 0.0725, rounded half-up to two decimal places."

        Setup A: resident, sale 20000, trade-in 5000.
        taxable_base = 15000. sales_tax = 15000 * 0.0725 = 1087.50.
        reg_fee (2500 lbs, 2026, resident) = 65 + 22 = 87.00.
        fee_subtotal = 1174.50. processing_fee tier 1000<1174.50<=5000
        → 38.00. total_due = 1212.50.
        """
        base = setup_application_at_emissions_passed(
            application_type="TITLE_TRANSFER",
            residency_state="CA",
            declared_sale_price=20000.00,
            trade_in_value=5000.00,
            curb_weight_lbs=2500,
            model_year=2026,
        )
        assess_fees(base["application"]["id"])
        app_after = get_transfer_application(base["application"]["id"])
        assert app_after["fee_subtotal"] == pytest.approx(1174.50, abs=0.01)
        assert app_after["processing_fee"] == pytest.approx(38.00, abs=0.01)
        assert app_after["total_due"] == pytest.approx(1212.50, abs=0.01)

    def test_non_resident_ignores_trade_in(self, api):
        """PRD §3.7: "In the non-resident variant, trade_in_value is
        ignored entirely: the taxable base is declared_sale_price
        outright, and the sales tax is the taxable base multiplied by
        the non-resident rate of 0.085, rounded half-up to two decimal
        places."

        Setup B: non-resident, sale 20000, trade-in 5000 (ignored).
        sales_tax = 20000 * 0.085 = 1700.00.
        reg_fee (2500 lbs, 2026, non-resident) = 65 + 55 = 120.00.
        fee_subtotal = 1820.00. processing_fee tier 1000<1820<=5000
        → 38.00. total_due = 1858.00.
        """
        base = setup_application_at_emissions_passed(
            application_type="TITLE_TRANSFER",
            residency_state="NV",
            declared_sale_price=20000.00,
            trade_in_value=5000.00,
            curb_weight_lbs=2500,
            model_year=2026,
        )
        assess_fees(base["application"]["id"])
        app_after = get_transfer_application(base["application"]["id"])
        assert app_after["fee_subtotal"] == pytest.approx(1820.00, abs=0.01)
        assert app_after["processing_fee"] == pytest.approx(38.00, abs=0.01)
        assert app_after["total_due"] == pytest.approx(1858.00, abs=0.01)

    def test_taxable_base_clamped_to_zero(self, api):
        """PRD §3.7: "the taxable base is the larger of zero and
        declared_sale_price minus trade_in_value."

        Setup: resident, sale 5000, trade-in 8000 → max(0, -3000) = 0
        → sales_tax 0. reg_fee = 65 + 22 = 87. fee_subtotal = 87.00.
        """
        base = setup_application_at_emissions_passed(
            application_type="TITLE_TRANSFER",
            residency_state="CA",
            declared_sale_price=5000.00,
            trade_in_value=8000.00,
            curb_weight_lbs=2500,
            model_year=2026,
        )
        assess_fees(base["application"]["id"])
        app_after = get_transfer_application(base["application"]["id"])
        # sales_tax = 0; reg_fee = 87.00 → fee_subtotal = 87.00
        # processing_fee tier 1: <=200 → 8.00. total_due = 95.00.
        assert app_after["fee_subtotal"] == pytest.approx(87.00, abs=0.01)
        assert app_after["processing_fee"] == pytest.approx(8.00, abs=0.01)
        assert app_after["total_due"] == pytest.approx(95.00, abs=0.01)


# ---------------------------------------------------------------------------
# Processing fee tiers — PRD §3.7
# ---------------------------------------------------------------------------
class TestProcessingFeeTiers:

    def test_tier1_subtotal_at_or_below_200(self, api):
        """PRD §3.7: "when fee_subtotal is at most 200.00, the
        processing fee is a flat 8.00."

        sale 1000, trade-in 0, resident, 2500 lbs, 2026 →
        sales_tax = 1000 * 0.0725 = 72.50. reg_fee = 87.00.
        fee_subtotal = 159.50. processing_fee tier 1 = 8.00.
        total_due = 167.50.
        """
        base = setup_application_at_emissions_passed(
            application_type="TITLE_TRANSFER",
            residency_state="CA",
            declared_sale_price=1000.00,
            trade_in_value=0.00,
            curb_weight_lbs=2500,
            model_year=2026,
        )
        assess_fees(base["application"]["id"])
        app_after = get_transfer_application(base["application"]["id"])
        assert app_after["fee_subtotal"] == pytest.approx(159.50, abs=0.01)
        assert app_after["processing_fee"] == pytest.approx(8.00, abs=0.01)
        assert app_after["total_due"] == pytest.approx(167.50, abs=0.01)

    def test_tier2_subtotal_above_200_up_to_1000(self, api):
        """PRD §3.7: "when fee_subtotal is strictly greater than 200.00
        and at most 1000.00, it is a flat 18.00."

        Construct fee_subtotal == 800.00 region:
        sale 9000, trade-in 0, resident, 2500 lbs, 2026 →
        sales_tax = 9000 * 0.0725 = 652.50. reg_fee = 87.00.
        fee_subtotal = 739.50. processing_fee tier 2 = 18.00.
        total_due = 757.50.
        """
        base = setup_application_at_emissions_passed(
            application_type="TITLE_TRANSFER",
            residency_state="CA",
            declared_sale_price=9000.00,
            trade_in_value=0.00,
            curb_weight_lbs=2500,
            model_year=2026,
        )
        assess_fees(base["application"]["id"])
        app_after = get_transfer_application(base["application"]["id"])
        assert app_after["fee_subtotal"] == pytest.approx(739.50, abs=0.01)
        assert app_after["processing_fee"] == pytest.approx(18.00, abs=0.01)
        assert app_after["total_due"] == pytest.approx(757.50, abs=0.01)

    def test_tier3_subtotal_above_1000_up_to_5000(self, api):
        """PRD §3.7: "when fee_subtotal is strictly greater than 1000.00
        and at most 5000.00, it is a flat 38.00."

        See the dual-variant test (1174.50 falls in tier 3 → 38.00).
        Here we use a different point in the tier:
        sale 40000, trade-in 0, resident, 2500 lbs, 2026 →
        sales_tax = 40000 * 0.0725 = 2900.00. reg_fee = 87.00.
        fee_subtotal = 2987.00. tier 3 → 38.00. total_due = 3025.00.
        """
        base = setup_application_at_emissions_passed(
            application_type="TITLE_TRANSFER",
            residency_state="CA",
            declared_sale_price=40000.00,
            trade_in_value=0.00,
            curb_weight_lbs=2500,
            model_year=2026,
        )
        assess_fees(base["application"]["id"])
        app_after = get_transfer_application(base["application"]["id"])
        assert app_after["fee_subtotal"] == pytest.approx(2987.00, abs=0.01)
        assert app_after["processing_fee"] == pytest.approx(38.00, abs=0.01)
        assert app_after["total_due"] == pytest.approx(3025.00, abs=0.01)

    def test_tier4_subtotal_above_5000_is_two_percent(self, api):
        """PRD §3.7: "when fee_subtotal is strictly greater than
        5000.00, the processing fee is two percent (0.02) of
        fee_subtotal, rounded half-up to two decimal places."

        sale 100000, trade-in 0, resident, 2500 lbs, 2026 →
        sales_tax = 100000 * 0.0725 = 7250.00. reg_fee = 87.00.
        fee_subtotal = 7337.00. tier 4 → 7337 * 0.02 = 146.74.
        total_due = 7483.74.
        """
        base = setup_application_at_emissions_passed(
            application_type="TITLE_TRANSFER",
            residency_state="CA",
            declared_sale_price=100000.00,
            trade_in_value=0.00,
            curb_weight_lbs=2500,
            model_year=2026,
        )
        assess_fees(base["application"]["id"])
        app_after = get_transfer_application(base["application"]["id"])
        assert app_after["fee_subtotal"] == pytest.approx(7337.00, abs=0.01)
        assert app_after["processing_fee"] == pytest.approx(146.74, abs=0.01)
        assert app_after["total_due"] == pytest.approx(7483.74, abs=0.01)


# ---------------------------------------------------------------------------
# Ledger and assess-fees side effects
# ---------------------------------------------------------------------------
class TestAssessFeesLedger:

    def test_assess_fees_writes_three_ledger_rows(self, api):
        """PRD §3.7: "appends exactly three FeeLedgerEntry rows whose
        kind values are SALES_TAX, REG_FEE, and PROCESSING_FEE, each
        with amount_cents equal to the positive cents amount of the
        corresponding figure."
        """
        base = setup_application_at_emissions_passed(
            application_type="TITLE_TRANSFER",
            residency_state="CA",
            declared_sale_price=20000.00,
            trade_in_value=5000.00,
            curb_weight_lbs=2500,
            model_year=2026,
        )
        assess_fees(base["application"]["id"])
        ledger = list_fee_ledger(base["application"]["id"])
        # Resident variant: sales_tax 1087.50, reg_fee 87.00,
        # processing_fee 38.00 → cents 108750, 8700, 3800.
        kinds = sorted(e["kind"] for e in ledger)
        assert kinds == ["PROCESSING_FEE", "REG_FEE", "SALES_TAX"]
        by_kind = {e["kind"]: e for e in ledger}
        assert by_kind["SALES_TAX"]["amount_cents"] == 108750
        assert by_kind["REG_FEE"]["amount_cents"] == 8700
        assert by_kind["PROCESSING_FEE"]["amount_cents"] == 3800

    def test_assess_fees_transitions_to_tax_assessed(self, api):
        """PRD §3.7: "The successful assessment transitions the
        application's status from EMISSIONS_PASSED to TAX_ASSESSED."
        """
        base = setup_application_at_emissions_passed()
        result = assess_fees(base["application"]["id"])
        assert result["status"] == "TAX_ASSESSED"


# ---------------------------------------------------------------------------
# Assess-fees gates
# ---------------------------------------------------------------------------
class TestAssessFeesGates:

    def test_emissions_expired_blocks_assess_fees(self, api):
        """PRD §3.7: "Vehicle.emissions_expires_at must be in the
        future: if it is null on a non-electric vehicle, or if the
        current server time is at or after the stored expiry instant
        (the boundary is inclusive — the expiry day itself fails), the
        call is rejected with ERR_EMISSIONS_EXPIRED."
        """
        base = setup_application_at_emissions_passed()
        # Advance clock past emissions_expires_at.
        vehicle = base["vehicle"]
        expires = parse_iso(vehicle["emissions_expires_at"])
        advance_clock_to(expires)  # exactly at expiry — inclusive boundary
        resp = api.assess_fees(
            base["application"]["id"],
            TEST_USERS["tax_assessor_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_EMISSIONS_EXPIRED.value)

    def test_revoked_real_id_blocks_assess_fees(self, api):
        """PRD §3.7: "Owner.real_id_status must be in the set APPROVED,
        NOT_APPLIED, or PENDING: a REVOKED REAL ID blocks fee
        assessment with ERR_OWNER_REAL_ID_REVOKED."
        """
        # Use a resident owner with REAL ID APPROVED then REVOKE it.
        owner = setup_owner_with_real_id_approved(residency_state="CA")
        vehicle = create_vehicle()
        app = create_transfer_application(
            owner["id"], vehicle["id"], application_type="TITLE_TRANSFER",
        )
        verify_vin(vehicle["id"], app["id"])
        drive_vehicle_to_emissions_passed(vehicle["id"])
        # Find the owner's APPROVED RealIDApplication via the cascade
        # path: re-create by approving anew is the implementation's
        # responsibility. Here we revoke the only APPROVED app on this
        # owner.
        # PRD §3.10 does not expose a GET /real-id-applications by
        # owner endpoint, but our fixture approve_owner_to_real_id
        # returned the application; capture it from a fresh approval
        # would be cleaner. Re-pattern: rebuild via approve helper to
        # get the app id.
        from test_helpers import approve_owner_to_real_id
        # An owner already approved cannot be re-approved; we need to
        # capture the original app id. Re-fetch by repeating the setup
        # with a fresh owner so we have the app id in hand:
        fresh_owner = create_owner(date_of_birth=date_for_age(30))
        fresh_app_obj = approve_owner_to_real_id(fresh_owner["id"])
        # Build a new transfer application on a new vehicle for this
        # fresh owner.
        fresh_vehicle = create_vehicle()
        fresh_t_app = create_transfer_application(
            fresh_owner["id"], fresh_vehicle["id"],
            application_type="TITLE_TRANSFER",
        )
        verify_vin(fresh_vehicle["id"], fresh_t_app["id"])
        drive_vehicle_to_emissions_passed(fresh_vehicle["id"])
        # Revoke this owner's REAL ID.
        revoke_real_id(fresh_app_obj["id"])
        resp = api.assess_fees(
            fresh_t_app["id"], TEST_USERS["tax_assessor_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_OWNER_REAL_ID_REVOKED.value)

    def test_invalid_state_when_not_in_emissions_passed(self, api):
        """PRD §3.7: "A TaxAssessor assesses fees on a TransferApplication
        whose status is EMISSIONS_PASSED."
        PRD §2.8 priority 6 ERR_INVALID_STATE.
        """
        owner = create_owner()
        vehicle = create_vehicle()
        app = create_transfer_application(
            owner["id"], vehicle["id"], application_type="TITLE_TRANSFER",
        )
        # App is in DRAFT.
        resp = api.assess_fees(
            app["id"], TEST_USERS["tax_assessor_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
