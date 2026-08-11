"""MSP determination ladder, ESRD window boundary, and MSP-related
finalization gating (PRD §3.4, §3.5, §2.9)."""
from test_helpers import (
    TEST_USERS,
    create_config,
    create_member,
    create_verified_coverage,
    draft_and_finalize_determination,
    draft_determination,
    set_clock,
    setup_member_with_our_plan,
    submit_and_adjudicate_msp,
    submit_msp_questionnaire,
    validate_error,
    validate_success,
)

COB = TEST_USERS["cob_analyst_headers"]


class TestMSPLadder:
    def test_msp_esrd_inside_window_is_secondary(self, api):
        """PRD §3.4: "2. If `esrd_flag` is true and the date
        `esrd_coordination_months` after `esrd_onset_date` is later than the
        current clock, the result is `MEDICARE_SECONDARY` — the member is still
        inside the ESRD coordination window." Onset 2026-01-15 + 30 months =
        2028-07-15, which is later than the 2026-06-01 clock, so rule 2 fires
        before any age-based rule.

        Design: Difficulty/combinatorial_formula/msp_determination_nested_branching
        """
        create_config()
        set_clock("2026-06-01T00:00:00Z")
        member = create_member(
            date_of_birth="1950-01-01", employer_size=10,
            medicare_entitlement_reason="ESRD_AND_AGE", esrd_onset_date="2026-01-15",
        )
        questionnaire = submit_msp_questionnaire(
            member["id"], has_employer_group_health=True, employer_size=10,
            disability_flag=False, esrd_flag=True, esrd_onset_date="2026-01-15",
        )
        res = api.adjudicate_msp_questionnaire(member["id"], questionnaire["id"], COB)
        adjudicated = validate_success(res, 200)
        assert adjudicated["status"] == "ADJUDICATED"
        assert adjudicated["msp_result"] == "MEDICARE_SECONDARY"

    def test_msp_esrd_member_age_65_plus_derived(self, api):
        """PRD §3.4: "At submission the system derives `age_at_submission` from
        the member's `date_of_birth` against the current logical clock, and
        `is_age_65_plus`, which is true when that age is at least 65." Born
        1950-01-01 against the 2026-06-01 clock, the member is 76.

        Design: Difficulty/combinatorial_formula/msp_determination_nested_branching
        """
        create_config()
        set_clock("2026-06-01T00:00:00Z")
        member = create_member(
            date_of_birth="1950-01-01", employer_size=10,
            medicare_entitlement_reason="ESRD_AND_AGE", esrd_onset_date="2026-01-15",
        )
        questionnaire = submit_msp_questionnaire(
            member["id"], has_employer_group_health=True, employer_size=10,
            disability_flag=False, esrd_flag=True, esrd_onset_date="2026-01-15",
        )
        assert questionnaire["age_at_submission"] == 76
        assert questionnaire["is_age_65_plus"] is True
        adjudicated = validate_success(
            api.adjudicate_msp_questionnaire(member["id"], questionnaire["id"], COB), 200
        )
        assert adjudicated["msp_result"] == "MEDICARE_SECONDARY"

    def test_msp_age_based_large_employer(self, api):
        """PRD §3.4: "4. If `is_age_65_plus` is true and `employer_size` is at
        least the configuration's `msp_employer_size_threshold`, the result is
        `MEDICARE_SECONDARY` — a large active-employer plan pays first for
        age-based entitlement."

        Design: Corner/calculations/msp_age_based_large_employer
        """
        create_config()
        set_clock("2026-06-01T00:00:00Z")
        member = create_member(
            date_of_birth="1955-01-01", employer_size=50,
            medicare_entitlement_reason="AGE",
        )
        adjudicated = submit_and_adjudicate_msp(
            member["id"], has_employer_group_health=True, employer_size=50,
            disability_flag=False, esrd_flag=False,
        )
        assert adjudicated["msp_result"] == "MEDICARE_SECONDARY"

    def test_msp_no_group_health(self, api):
        """PRD §3.4: "1. If `has_employer_group_health` is false, the result is
        `MEDICARE_PRIMARY` — with no group plan in the picture there is nothing
        to coordinate."

        Design: Corner/calculations/msp_no_group_health
        """
        create_config()
        set_clock("2026-06-01T00:00:00Z")
        member = create_member(
            date_of_birth="1955-01-01", employment_status="RETIRED",
            employer_size=0, medicare_entitlement_reason="AGE",
        )
        adjudicated = submit_and_adjudicate_msp(
            member["id"], has_employer_group_health=False, employer_size=0,
            disability_flag=False, esrd_flag=False,
        )
        assert adjudicated["msp_result"] == "MEDICARE_PRIMARY"


class TestESRDWindowBoundary:
    def test_esrd_window_exactly_at_end_is_medicare_primary(self, api):
        """PRD §3.4: "3. If `esrd_flag` is true and that coordination end date is
        on or before the current clock, the result is `MEDICARE_PRIMARY` — the
        ESRD window is exhausted." Onset 2026-01-15 + 30 months = 2028-07-15;
        with the clock exactly at 2028-07-15 the end date is on the clock, so
        rule 3 fires.

        Design: Difficulty/boundary_precision_check/esrd_window_exact_boundary
        """
        create_config()
        set_clock("2028-07-15T00:00:00Z")
        member = create_member(
            date_of_birth="1950-01-01", employer_size=30,
            medicare_entitlement_reason="ESRD_AND_AGE", esrd_onset_date="2026-01-15",
        )
        adjudicated = submit_and_adjudicate_msp(
            member["id"], has_employer_group_health=True, employer_size=30,
            disability_flag=False, esrd_flag=True, esrd_onset_date="2026-01-15",
        )
        assert adjudicated["msp_result"] == "MEDICARE_PRIMARY"

    def test_esrd_window_one_day_before_end_is_medicare_secondary(self, api):
        """PRD §3.4: "2. If `esrd_flag` is true and the date
        `esrd_coordination_months` after `esrd_onset_date` is later than the
        current clock, the result is `MEDICARE_SECONDARY` — the member is still
        inside the ESRD coordination window." At 2028-07-14 the end date
        (2028-07-15) is still later than the clock.

        Design: Difficulty/boundary_precision_check/esrd_window_exact_boundary
        """
        create_config()
        set_clock("2028-07-14T00:00:00Z")
        member = create_member(
            date_of_birth="1950-01-01", employer_size=30,
            medicare_entitlement_reason="ESRD_AND_AGE", esrd_onset_date="2026-01-15",
        )
        adjudicated = submit_and_adjudicate_msp(
            member["id"], has_employer_group_health=True, employer_size=30,
            disability_flag=False, esrd_flag=True, esrd_onset_date="2026-01-15",
        )
        assert adjudicated["msp_result"] == "MEDICARE_SECONDARY"


class TestFinalizationGating:
    def test_finalize_with_medicare_in_scope_requires_questionnaire(self, api):
        """PRD §3.5: "MSP compliance requires that whenever any in-scope coverage
        has a `coverage_kind` beginning with `MEDICARE_` — that is,
        `MEDICARE_PART_A`, `MEDICARE_PART_B`, or `MEDICARE_ADVANTAGE` — the
        `msp_questionnaire_id` must be supplied and must reference an
        `ADJUDICATED` questionnaire for this member; otherwise finalization is
        rejected with `ERR_MSP_QUESTIONNAIRE_REQUIRED` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_finalize
        """
        member, _own = setup_member_with_our_plan(dict(
            date_of_birth="1950-01-01", employment_status="RETIRED",
            employer_size=5, medicare_entitlement_reason="AGE",
        ))
        create_verified_coverage(
            member["id"], payer_id="MCR", plan_name="Medicare A",
            coverage_kind="MEDICARE_PART_A", subscriber_relationship="SELF",
            policy_holder_dob="1950-01-01", effective_from="2010-01-01",
            verification_source="DATA_MATCH_CMS",
        )
        draft = draft_determination(member["id"], "2026-02-01")
        res = api.finalize_primacy_determination(member["id"], draft["id"], COB)
        validate_error(res, "ERR_MSP_QUESTIONNAIRE_REQUIRED", expected_status=422)

    def test_refinalize_finalized_determination_rejected_invalid_state(self, api):
        """PRD §2.9: "the server evaluates them in a fixed family order, so an
        earlier family surfaces before a later one can mask it:".
        PRD §2.9: "4. Whether the entity is in a state from which the requested
        transition is valid (`ERR_INVALID_STATE`)."
        PRD §2.9: "8. MSP compliance (`ERR_MSP_QUESTIONNAIRE_REQUIRED`)."
        Finalizing an already-FINALIZED determination is a family-4 state
        violation and surfaces before the family-8 MSP-compliance failure that
        would also apply.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_finalize
        """
        member, _own = setup_member_with_our_plan(dict(
            date_of_birth="1950-01-01", employment_status="RETIRED",
            employer_size=5, medicare_entitlement_reason="AGE",
        ))
        determination = draft_and_finalize_determination(member["id"], "2026-02-01")
        assert determination["status"] == "FINALIZED"

        # Medicare coverage arrives afterwards; the incumbent is already final.
        create_verified_coverage(
            member["id"], payer_id="MCR", plan_name="Medicare A",
            coverage_kind="MEDICARE_PART_A", subscriber_relationship="SELF",
            policy_holder_dob="1950-01-01", effective_from="2010-01-01",
            verification_source="DATA_MATCH_CMS",
        )
        res = api.finalize_primacy_determination(member["id"], determination["id"], COB)
        validate_error(res, "ERR_INVALID_STATE", expected_status=409)
