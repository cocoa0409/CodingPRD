"""Containment-requirement dual variants (PRD §3.10): identical measurements
grade DEFICIENT under SPCC_SIMPLE and COMPLIANT under SPCC_WITH_FREEBOARD."""
import pytest

from test_helpers import (
    api_client,
    assert_money_equals,
    create_environmental_inspection,
    create_substation,
    validate_success,
)
from test_helpers import TEST_USERS

COMPLIANCE = TEST_USERS["compliance_headers"]

MEASUREMENTS = dict(
    inspection_date="2026-07-15T00:00:00Z",
    largest_vessel_gal=1000,
    containment_capacity_gal=1050,
    rainfall_freeboard_gal=40,
)


def _setup_two_inspections() -> dict:
    sub = create_substation()
    simple = create_environmental_inspection(sub["id"], method="SPCC_SIMPLE", **MEASUREMENTS)
    freeboard = create_environmental_inspection(
        sub["id"], method="SPCC_WITH_FREEBOARD", **MEASUREMENTS
    )
    return {"substation": sub, "simple": simple, "freeboard": freeboard}


class TestContainmentDualVariant:
    def test_spcc_simple_variant_deficient(self):
        """PRD §3.10: "Under `SPCC_SIMPLE`, the required capacity is 1.10 times
        `largest_vessel_gal`."
        PRD §3.10: "`compliance` is `COMPLIANT` when `containment_capacity_gal`
        is at or above `required_capacity_gal` — the boundary is inclusive, so
        capacity exactly equal to required is `COMPLIANT` — and `DEFICIENT`
        otherwise. `next_inspection_due` is set to `inspection_date` plus 12
        months when `COMPLIANT`, and plus 6 months when `DEFICIENT`."

        Design: Difficulty/dual_variant_calc/containment_dual_variant
        """
        ctx = _setup_two_inspections()
        completed = validate_success(
            api_client.complete_environmental_inspection(ctx["simple"]["id"], COMPLIANCE)
        )
        assert_money_equals(completed["required_capacity_gal"], "1100.00")
        assert completed["compliance"] == "DEFICIENT"  # 1050 < 1100
        assert completed["next_inspection_due"] == "2027-01-15"

    def test_spcc_with_freeboard_variant_compliant(self):
        """PRD §3.10: "Under `SPCC_WITH_FREEBOARD`, it is 1.00 times
        `largest_vessel_gal` plus `rainfall_freeboard_gal`."
        PRD §3.10: "`next_inspection_due` is set to `inspection_date` plus 12
        months when `COMPLIANT`, and plus 6 months when `DEFICIENT`."

        Design: Difficulty/dual_variant_calc/containment_dual_variant
        """
        ctx = _setup_two_inspections()
        completed = validate_success(
            api_client.complete_environmental_inspection(ctx["freeboard"]["id"], COMPLIANCE)
        )
        assert_money_equals(completed["required_capacity_gal"], "1040.00")
        assert completed["compliance"] == "COMPLIANT"  # 1050 >= 1040
        assert completed["next_inspection_due"] == "2027-07-15"

        # The two variants diverge on identical measurements.
        simple = validate_success(
            api_client.complete_environmental_inspection(ctx["simple"]["id"], COMPLIANCE)
        )
        assert simple["compliance"] != completed["compliance"]
