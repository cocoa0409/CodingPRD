"""HAP split calculation tests (PRD §3.2)."""
import pytest

from test_helpers import (
    validate_success,
    setup_priced_unit, create_draft_contract,
    make_landlord_headers,
    assert_contract_portion_invariants,
)


class TestHapSplitThreeInputFormula:
    def test_tenant_minimum_wins_over_standard_excess(self, api):
        """PRD §3.2: "The family's minimum contribution is thirty percent of
        monthly income: `annual_income_cents` multiplied by 0.30, divided by 12,
        rounded half-up to cents. The tenant's base portion is the larger of
        that minimum and the excess of `approved_rent_cents` over the payment
        standard's `amount_cents` (this excess is zero when the approved rent is
        at or below the standard)."

        Design: Difficulty/combinatorial_formula/hap_split_three_input_threshold_formula
        """
        landlord, prop, unit, family = setup_priced_unit(
            zip_code="90003", bedroom_count=1, standard_cents=150_000,
            family_income_cents=2_400_000, family_code="F3",
        )
        contract = create_draft_contract(
            unit, family, landlord,
            contract_rent_cents=170_000, lease_start_date="2026-08-01",
        )
        data = validate_success(
            api.submit_contract(contract["id"], make_landlord_headers(landlord["id"]))
        )
        # approved = min(170000, 150000) = 150000
        assert data["approved_rent_cents"] == 150_000
        # tenant_minimum = round(2400000*0.30/12) = 60000; excess = 0
        assert data["tenant_portion_cents"] == 60_000, (
            f"tenant portion must be max(60000, 0) = 60000, got "
            f"{data['tenant_portion_cents']}"
        )
        assert data["hap_portion_cents"] == 90_000, (
            f"HAP portion must be 150000 - 60000 = 90000, got "
            f"{data['hap_portion_cents']}"
        )
        assert_contract_portion_invariants(data)

    def test_lower_income_scales_tenant_minimum(self, api):
        """PRD §3.2: "The tenant's base portion is the larger of that minimum
        and the excess of `approved_rent_cents` over the payment standard's
        `amount_cents` (this excess is zero when the approved rent is at or
        below the standard). The tenant portion is then capped at
        `approved_rent_cents`, and the housing authority's portion is whatever
        remains of `approved_rent_cents` after the tenant portion is
        subtracted."

        Design: Difficulty/combinatorial_formula/hap_split_three_input_threshold_formula
        """
        landlord, prop, unit, family = setup_priced_unit(
            zip_code="90003", bedroom_count=1, standard_cents=150_000,
            family_income_cents=1_200_000, family_code="F3b",
        )
        contract = create_draft_contract(
            unit, family, landlord,
            contract_rent_cents=200_000, lease_start_date="2026-08-01",
        )
        data = validate_success(
            api.submit_contract(contract["id"], make_landlord_headers(landlord["id"]))
        )
        # approved = min(200000, 150000) = 150000; tenant_minimum = 30000
        assert data["approved_rent_cents"] == 150_000
        assert data["tenant_portion_cents"] == 30_000, (
            f"tenant portion must be max(30000, 0) = 30000, got "
            f"{data['tenant_portion_cents']}"
        )
        assert data["hap_portion_cents"] == 120_000
        assert_contract_portion_invariants(data)


class TestIncomeRatioConstant:
    def test_income_ratio_thirty_percent_applied(self, api):
        """PRD §3.2: "The family's minimum contribution is thirty percent of
        monthly income: `annual_income_cents` multiplied by 0.30, divided by 12,
        rounded half-up to cents."

        Design: Corner/calculations/hap_split_income_ratio_constant
        """
        landlord, prop, unit, family = setup_priced_unit(
            zip_code="90304", bedroom_count=1, standard_cents=150_000,
            family_income_cents=3_600_000, family_code="CF7",
        )
        contract = create_draft_contract(
            unit, family, landlord,
            contract_rent_cents=150_000, lease_start_date="2026-08-01",
        )
        data = validate_success(
            api.submit_contract(contract["id"], make_landlord_headers(landlord["id"]))
        )
        # tenant_minimum = round(3600000*0.30/12) = 90000
        assert data["tenant_portion_cents"] == 90_000, (
            f"0.30 income ratio: expected tenant 90000, got "
            f"{data['tenant_portion_cents']}"
        )
        assert data["hap_portion_cents"] == 60_000, (
            f"expected HAP 60000 (150000 - 90000), got {data['hap_portion_cents']}"
        )
