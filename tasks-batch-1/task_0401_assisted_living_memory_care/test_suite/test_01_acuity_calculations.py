"""Acuity scoring: care-points calculation, the behavior-flag cap, the provisional vs
frozen variants, and the care-level tier boundary.

All citations are verbatim from PRD.md §3.2 and §3.3.
"""
import pytest
from test_helpers import (
    api_client, validate_success, get_success_data,
    create_facility, create_resident, create_assessment,
    TEST_USERS,
)

CLINICAL = TEST_USERS["clinical_director_headers"]
STAFF = TEST_USERS["staff_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]


class TestCarePointsProvisionalVsFrozen:
    """The provisional draft variant and the frozen finalized variant differ in whether
    the number is copied onto the resident."""

    def test_provisional_points_on_draft_not_copied_to_resident(self, api):
        """PRD §3.2: "At assessment creation a provisional `care_points_total` and `care_level`
        are computed and stored on the draft row, where they remain mutable while the assessment
        is `DRAFT`; they are not yet copied to the resident."

        Design: Difficulty/dual_variant_calc/care_points_provisional_vs_frozen_on_assessment
        """
        fac = create_facility(care_point_rate_cents=1500)
        res = create_resident(fac["id"], full_name="Ada Prospect", date_of_birth="1940-05-01")
        asmt = create_assessment(
            res["id"], adl_bathing=2, adl_dressing=2, adl_toileting=2,
            adl_transferring=2, adl_eating=2, cognition_score=0, behavior_flags=0,
        )
        assert asmt["care_points_total"] == 30
        # Before finalize, the resident has not yet received the points.
        res_before = validate_success(api.get_resident(res["id"], STAFF), 200)
        assert res_before["current_care_points"] == 0
        assert res_before["current_care_level"] is None
        assert res_before["status"] == "PROSPECT"

    def test_frozen_points_copied_to_resident_on_finalize(self, api):
        """PRD §3.3: "The newly finalized assessment's `care_level` is copied to the resident's
        `current_care_level`, and its `care_points_total` is copied to the resident's
        `current_care_points`."
        PRD §3.3: "a resident who was `PROSPECT` becomes `ASSESSED` on the first finalize"

        Design: Difficulty/dual_variant_calc/care_points_provisional_vs_frozen_on_assessment
        """
        fac = create_facility(care_point_rate_cents=1500)
        res = create_resident(fac["id"], full_name="Ada Prospect", date_of_birth="1940-05-01")
        asmt = create_assessment(
            res["id"], adl_bathing=2, adl_dressing=2, adl_toileting=2,
            adl_transferring=2, adl_eating=2, cognition_score=0, behavior_flags=0,
        )
        finalized = validate_success(
            api.finalize_assessment(asmt["id"], {"expected_resident_version": res["version"]}, CLINICAL), 200,
        )
        assert finalized["care_points_total"] == 30
        res_after = validate_success(api.get_resident(res["id"], STAFF), 200)
        assert res_after["current_care_points"] == 30
        assert res_after["current_care_level"] == "LEVEL_2"
        assert res_after["status"] == "ASSESSED"


class TestCarePointsCombinatorialFormula:
    """care_points_total is built from three components; the behavior term is capped at four
    before weighting."""

    def test_behavior_flag_cap_saturates_at_four(self, api):
        """PRD §3.2: "The behavior component takes the behavior-flag count but caps it at four
        before weighting — that is, the smaller of the flag count and four — and multiplies that
        capped value by a behavior weight of five."

        Design: Difficulty/combinatorial_formula/care_points_weighted_with_behavior_cap_mode_a
        """
        fac = create_facility(care_point_rate_cents=2000)
        res = create_resident(fac["id"], full_name="Cap Tester", date_of_birth="1945-03-03")
        # adl sum 10 -> 30, cognition 3 -> 6, behavior 10 capped to 4 -> 20. Total 56.
        asmt = create_assessment(
            res["id"], adl_bathing=2, adl_dressing=2, adl_toileting=2,
            adl_transferring=2, adl_eating=2, cognition_score=3, behavior_flags=10,
        )
        assert asmt["care_points_total"] == 56
        assert asmt["care_level"] == "LEVEL_3"

    def test_behavior_flag_cap_components_sum_to_total(self, api):
        """PRD §3.2: "The ADL component is the sum of the five ADL scores (which ranges from 0
        to 20) multiplied by an ADL point weight of three."
        PRD §3.2: "The cognition component is the cognition score multiplied by a cognition
        weight of two."

        Design: Difficulty/combinatorial_formula/care_points_weighted_with_behavior_cap_mode_a
        """
        fac = create_facility(care_point_rate_cents=2000)
        res = create_resident(fac["id"], full_name="Cap Two", date_of_birth="1946-04-04")
        # behavior_flags 4 also caps to 4 -> identical 20 points; total 56 again.
        asmt = create_assessment(
            res["id"], adl_bathing=2, adl_dressing=2, adl_toileting=2,
            adl_transferring=2, adl_eating=2, cognition_score=3, behavior_flags=4,
        )
        assert asmt["care_points_total"] == 56


class TestCareLevelTierBoundary:
    """The tier ladder is inclusive at the lower edge (>=, not >)."""

    def test_exactly_thirty_points_lands_in_level_2(self, api):
        """PRD §3.2: "a total below fifty-five but at least thirty is `LEVEL_2`"
        PRD §3.2: "a resident whose `care_points_total` is exactly equal to a tier minimum
        lands in the higher tier."

        Design: Difficulty/boundary_precision_check/care_level_tier_boundary_exactly_30_points
        """
        fac = create_facility(care_point_rate_cents=2000)
        res = create_resident(fac["id"], full_name="Exactly Thirty", date_of_birth="1940-01-01")
        # adl sum 10 -> 30, cognition 0, behavior 0 -> total exactly 30.
        asmt = create_assessment(
            res["id"], adl_bathing=2, adl_dressing=2, adl_toileting=2,
            adl_transferring=2, adl_eating=2, cognition_score=0, behavior_flags=0,
        )
        assert asmt["care_points_total"] == 30
        assert asmt["care_level"] == "LEVEL_2"

    def test_twenty_nine_points_lands_in_level_1(self, api):
        """PRD §3.2: "and any total below thirty is `LEVEL_1`."

        Design: Difficulty/boundary_precision_check/care_level_tier_boundary_exactly_30_points
        """
        fac = create_facility(care_point_rate_cents=2000)
        res = create_resident(fac["id"], full_name="Twenty Nine", date_of_birth="1940-02-02")
        # adl sum 9 -> 27, cognition 1 -> 2, behavior 0 -> total 29.
        asmt = create_assessment(
            res["id"], adl_bathing=2, adl_dressing=2, adl_toileting=1,
            adl_transferring=2, adl_eating=2, cognition_score=1, behavior_flags=0,
        )
        assert asmt["care_points_total"] == 29
        assert asmt["care_level"] == "LEVEL_1"
