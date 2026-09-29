"""Two scoring procedures that answer differently over identical stored rows.

A warranty claim is priced under one of two assessment bases, and a cabinet
carries two uniformity figures computed by the same procedure over two different
module sets. Both pairs are exercised here against byte-identical inputs.
"""

from test_helpers.assertions import (
    assert_2dp,
    assert_cabinet_fields,
    assert_case_fields,
    assert_cents,
    assert_module_fields,
)
from test_helpers.constants import (
    CASE_APPROVED,
    MODULE_INSTALLED,
    MODULE_RETURNED,
    WARRANTY_CASE_INSTANT,
)
from test_helpers.factories import FP16_STD


def _two_responded_degradation_claims(plant):
    """A commissioned GOLD wall with two identical brightness claims answered."""
    scene = plant.commissioned_scene()
    plant.set_clock(WARRANTY_CASE_INSTANT)
    case_a = plant.open_degradation_case(
        scene.contract["id"], scene.cabinet["id"], measured_brightness_nits=4600
    )
    case_b = plant.open_degradation_case(
        scene.contract["id"], scene.cabinet["id"], measured_brightness_nits=4600
    )
    plant.respond(case_a["id"])
    plant.respond(case_b["id"])
    scene.case_a = case_a
    scene.case_b = case_b
    return scene


class TestWarrantyCreditAssessmentBases:
    """The two bases are genuinely different theories of compensation."""

    def test_pro_rata_basis_pays_for_lost_warranty_life(self, plant):
        """Under `PRO_RATA_REMAINING_TERM` the credit is `cabinet_value_cents`
        multiplied by the months of warranty still to run — 60 less
        `elapsed_warranty_months` — divided by 60, rounded half up to whole cents
        as the last step; this basis ignores the size of the shortfall entirely
        and pays only for lost warranty life.

        Design: Difficulty/dual_variant_calc/warranty_credit_pro_rata_vs_shortfall_severity_diverge
        """
        scene = _two_responded_degradation_claims(plant)

        approved = plant.assess(
            scene.case_a["id"],
            decision="APPROVE",
            assessment_basis="PRO_RATA_REMAINING_TERM",
        )

        assert_case_fields(
            approved,
            case_state=CASE_APPROVED,
            assessment_basis="PRO_RATA_REMAINING_TERM",
            resolved_faulty_module_id=scene.modules[0]["id"],
        )
        assert approved["elapsed_warranty_months"] == 6
        assert_2dp(approved["allowed_degradation_pct"], 5.00, "allowed_degradation_pct")
        assert_2dp(approved["degradation_pct"], 8.00, "degradation_pct")
        assert_2dp(approved["shortfall_pct"], 3.00, "shortfall_pct")
        assert_cents(approved["credit_cents"], 92160, "credit_cents")

    def test_shortfall_severity_basis_pays_for_the_gap_below_the_curve(self, plant):
        """Under `SHORTFALL_SEVERITY` the credit is `cabinet_value_cents`
        multiplied by the lesser of two fractions: `shortfall_pct` divided by 100
        and then multiplied by 2.5, or the hard cap of 0.6; the product is
        rounded half up to whole cents as the last step.

        Design: Difficulty/dual_variant_calc/warranty_credit_pro_rata_vs_shortfall_severity_diverge
        """
        scene = _two_responded_degradation_claims(plant)

        approved = plant.assess(
            scene.case_b["id"],
            decision="APPROVE",
            assessment_basis="SHORTFALL_SEVERITY",
        )

        assert_case_fields(
            approved,
            case_state=CASE_APPROVED,
            assessment_basis="SHORTFALL_SEVERITY",
            resolved_faulty_module_id=scene.modules[0]["id"],
        )
        assert_2dp(approved["shortfall_pct"], 3.00, "shortfall_pct")
        assert_cents(approved["credit_cents"], 7680, "credit_cents")

    def test_the_two_bases_diverge_over_identical_stored_data(self, plant):
        """`credit_cents` then follows the `assessment_basis` the assessor chose,
        and the two bases are genuinely different theories of compensation over
        identical stored data.

        Design: Difficulty/dual_variant_calc/warranty_credit_pro_rata_vs_shortfall_severity_diverge
        """
        scene = _two_responded_degradation_claims(plant)

        pro_rata = plant.assess(
            scene.case_a["id"],
            decision="APPROVE",
            assessment_basis="PRO_RATA_REMAINING_TERM",
        )
        severity = plant.assess(
            scene.case_b["id"],
            decision="APPROVE",
            assessment_basis="SHORTFALL_SEVERITY",
        )

        assert_cents(pro_rata["credit_cents"], 92160, "credit_cents")
        assert_cents(severity["credit_cents"], 7680, "credit_cents")
        assert pro_rata["credit_cents"] - severity["credit_cents"] == 84480
        assert_2dp(pro_rata["shortfall_pct"], 3.00, "shortfall_pct")
        assert_2dp(severity["shortfall_pct"], 3.00, "shortfall_pct")
        assert pro_rata["resolved_faulty_module_id"] == scene.modules[0]["id"]
        assert severity["resolved_faulty_module_id"] == scene.modules[0]["id"]
        assert pro_rata["case_state"] == CASE_APPROVED
        assert severity["case_state"] == CASE_APPROVED


def _two_module_wall_with_approved_claim(plant):
    """A two-slot wall whose dimmer module has been approved for replacement."""
    scene = plant.warranty_case_scene(
        model_base=FP16_STD,
        revision_overrides={"structural_load_kg_per_sqm": 150.00},
        brightnesses=[4900, 4950],
        chroma=[(0.3130, 0.3292), (0.3128, 0.3291)],
    )
    scene.case = plant.assess(
        scene.case["id"], decision="APPROVE", assessment_basis="SHORTFALL_SEVERITY"
    )
    return scene


class TestCabinetUniformityBaselineVersusAsBuilt:
    """One scoring procedure, two module sets, two legitimately different scores."""

    def test_burn_in_freezes_the_baseline_over_the_modules_then_installed(self, plant):
        """The uniformity procedure of §3.5 is evaluated once, at that instant,
        over the modules then holding `module_state` `INSTALLED` in the cabinet,
        and the result is written to `baseline_uniformity_score` while the
        participating module ids — ordered ascending by their `created_at` — are
        written to `baseline_module_ids`.

        Design: Difficulty/dual_variant_calc/cabinet_uniformity_as_built_vs_qa_baseline_diverge
        """
        scene = _two_module_wall_with_approved_claim(plant)

        cabinet = plant.cabinet(scene.cabinet["id"])

        assert_2dp(cabinet["baseline_uniformity_score"], 97.88, "baseline_uniformity_score")
        assert cabinet["baseline_module_ids"] == [
            scene.modules[0]["id"],
            scene.modules[1]["id"],
        ]

    def test_as_built_score_drops_after_the_warranty_swap(self, plant):
        """The `as_built_uniformity_score` applies that procedure to the modules
        **currently** holding `module_state` `INSTALLED` in the cabinet, and is
        refreshed on every install, every removal and every warranty swap.

        Design: Difficulty/dual_variant_calc/cabinet_uniformity_as_built_vs_qa_baseline_diverge
        """
        scene = _two_module_wall_with_approved_claim(plant)

        plant.fulfil(scene.case["id"], scene.cabinet["id"], scene.spare["id"])

        cabinet = plant.cabinet(scene.cabinet["id"])
        assert_2dp(cabinet["as_built_uniformity_score"], 95.34, "as_built_uniformity_score")
        assert_cabinet_fields(
            cabinet,
            installed_module_count=2,
            occupied_slot_indexes=[1, 2],
            total_dead_pixel_count=2,
        )
        assert_2dp(cabinet["dead_pixel_ppm"], 488.28, "dead_pixel_ppm")

    def test_the_two_uniformity_figures_diverge_over_identical_stored_data(self, plant):
        """After a warranty swap the two figures legitimately diverge over
        identical stored data, and their difference is the degradation the QA
        report cites.

        Design: Difficulty/dual_variant_calc/cabinet_uniformity_as_built_vs_qa_baseline_diverge
        """
        scene = _two_module_wall_with_approved_claim(plant)
        outgoing, retained = scene.modules[0], scene.modules[1]

        fulfilled = plant.fulfil(scene.case["id"], scene.cabinet["id"], scene.spare["id"])

        cabinet = plant.cabinet(scene.cabinet["id"])
        assert_2dp(cabinet["baseline_uniformity_score"], 97.88, "baseline_uniformity_score")
        assert_2dp(cabinet["as_built_uniformity_score"], 95.34, "as_built_uniformity_score")
        assert (
            round(
                cabinet["baseline_uniformity_score"] - cabinet["as_built_uniformity_score"],
                2,
            )
            == 2.54
        )
        assert cabinet["baseline_module_ids"] == [outgoing["id"], retained["id"]]
        assert_module_fields(plant.module(outgoing["id"]), module_state=MODULE_RETURNED)
        assert_module_fields(
            plant.module(scene.spare["id"]),
            module_state=MODULE_INSTALLED,
            slot_index=1,
            replaces_module_id=outgoing["id"],
        )
        assert_cents(fulfilled["credit_cents"], 7680, "credit_cents")
