"""Component assay mass calculation: per-component round-half-up discipline."""
import pytest

from test_helpers import (
    TEST_USERS,
    assert_component_assay,
    create_component_assay_payload,
    setup_intake_env,
    setup_released_receipt,
    validate_success,
)

LAB = TEST_USERS["lab_technician_headers"]


class TestComponentPoundsPerComponentRounding:
    def test_component_pounds_rounded_per_component(self, api):
        """PRD §3.5: "`butterfat_lbs` is the receipt's `net_weight_lbs`
        multiplied by `butterfat_pct` and divided by 100, rounded half-up to 2
        decimal places". PRD §2.9: "each of `butterfat_lbs`, `protein_lbs`, and
        `other_solids_lbs` is rounded half-up to 2 decimal places **per
        component**, and only the per-component rounded values flow downstream
        into pooling and settlement."
        net 33333 lbs at 3.33% -> 1109.9889 -> 1109.99 for each component.

        Design: Difficulty/combinatorial_formula/component_pounds_per_component_then_sum_mode_b
        """
        env = setup_intake_env()
        receipt = setup_released_receipt(
            env["producer"]["id"], env["hauler"]["id"], gross=63333, tare=30000
        )
        assert receipt["net_weight_lbs"] == 33333

        res = api.create_component_assay(
            receipt["id"],
            create_component_assay_payload(
                butterfat_pct=3.33, protein_pct=3.33, other_solids_pct=3.33
            ),
            LAB,
        )
        assay = validate_success(res, 201)
        assert_component_assay(assay)
        assert assay["butterfat_lbs"] == pytest.approx(1109.99, abs=1e-9)
        assert assay["protein_lbs"] == pytest.approx(1109.99, abs=1e-9)
        assert assay["other_solids_lbs"] == pytest.approx(1109.99, abs=1e-9)

    def test_component_pounds_round_half_up_asymmetric(self, api):
        """PRD §2.9: "each of `butterfat_lbs`, `protein_lbs`, and
        `other_solids_lbs` is rounded half-up to 2 decimal places **per
        component**". net 33333 lbs: 1.11% -> 369.9963 -> 370.00;
        2.22% -> 739.9926 -> 739.99; 3.33% -> 1109.9889 -> 1109.99.

        Design: Difficulty/combinatorial_formula/component_pounds_per_component_then_sum_mode_b
        """
        env = setup_intake_env()
        receipt = setup_released_receipt(
            env["producer"]["id"], env["hauler"]["id"], gross=63333, tare=30000
        )
        res = api.create_component_assay(
            receipt["id"],
            create_component_assay_payload(
                butterfat_pct=1.11, protein_pct=2.22, other_solids_pct=3.33
            ),
            LAB,
        )
        assay = validate_success(res, 201)
        assert assay["butterfat_lbs"] == pytest.approx(370.00, abs=1e-9)
        assert assay["protein_lbs"] == pytest.approx(739.99, abs=1e-9)
        assert assay["other_solids_lbs"] == pytest.approx(1109.99, abs=1e-9)


def test_component_pounds_exact_values(api):
    """PRD §3.5: "`butterfat_lbs` is the receipt's `net_weight_lbs` multiplied
    by `butterfat_pct` and divided by 100, rounded half-up to 2 decimal places;
    `protein_lbs` is `net_weight_lbs` multiplied by `protein_pct` and divided
    by 100, rounded half-up to 2 decimal places; and `other_solids_lbs` is
    `net_weight_lbs` multiplied by `other_solids_pct` and divided by 100, also
    rounded half-up to 2 decimal places."
    net 20000 lbs: 3.85% -> 770.00; 3.10% -> 620.00; 5.75% -> 1150.00.

    Design: Corner/calculations/component_pounds_formula
    """
    env = setup_intake_env()
    receipt = setup_released_receipt(
        env["producer"]["id"], env["hauler"]["id"], gross=50000, tare=30000
    )
    assert receipt["net_weight_lbs"] == 20000

    res = api.create_component_assay(
        receipt["id"],
        create_component_assay_payload(
            butterfat_pct=3.85, protein_pct=3.10, other_solids_pct=5.75
        ),
        LAB,
    )
    assay = validate_success(res, 201)
    assert assay["butterfat_lbs"] == pytest.approx(770.00, abs=1e-9)
    assert assay["protein_lbs"] == pytest.approx(620.00, abs=1e-9)
    assert assay["other_solids_lbs"] == pytest.approx(1150.00, abs=1e-9)
