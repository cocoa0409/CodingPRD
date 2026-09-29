"""Permit issuance depends on rows that are not the permit: whether a credential
evaluation exists at all, and which applicant-and-profession pair already holds
practice authority."""

import pytest

from test_helpers import (
    ANALYST_HEADERS,
    APP_SUBMITTED,
    MILITARY_SPOUSE,
    PATHWAY_MILITARY_SPOUSE_EXPEDITED,
    PERMIT_ACTIVE,
    ApiErrorId,
    assert_application_fields,
    assert_permit_fields,
    temporary_permit_payload,
    validate_error,
    validate_success,
)

PT_PROFESSION = {
    "profession_code": "PT",
    "title": "Physical Therapist",
    "required_scope_elements": ["EVAL", "MANUAL", "MODALITY"],
    "critical_scope_elements": [],
    "required_practice_hours": 1000,
    "requirement_hours_total": 200.0,
    "exam_waiver_min_score": 70.00,
    "jurisprudence_exam_required": False,
    "universal_recognition_min_residency_months": 12,
    "standard_processing_days": 60,
    "base_fee_cents": 30000,
    "endorsement_fee_cents": 12000,
    "exam_fee_cents": 6000,
    "jurisprudence_fee_cents": 5000,
    "permit_fee_cents": 9000,
    "expedite_surcharge_pct": 0.10,
}


@pytest.fixture
def two_pathways_without_evaluations(setup):
    """A settled ENDORSEMENT file and a settled MILITARY_SPOUSE_EXPEDITED file, both
    SUBMITTED with nothing owing and neither carrying a credential evaluation."""
    profession = setup.profession()

    civilian = setup.applicant(full_name="Hana Lindqvist", state_code="TX", residency_months=24)
    civilian_credential = setup.credential(
        civilian["id"], license_number="OK-70071", scope_elements=["ASSESS", "TREAT", "SUPERVISE"]
    )
    civilian_application = setup.application(
        civilian["id"], profession["id"], civilian_credential["id"]
    )
    setup.submit(civilian_application["id"], civilian["id"])
    setup.pay(civilian_application["id"], civilian["id"], 48000)

    spouse = setup.applicant(
        full_name="Ada Whitfield",
        state_code="TX",
        residency_months=4,
        military_status=MILITARY_SPOUSE,
    )
    spouse_credential = setup.credential(
        spouse["id"], license_number="OK-70072", scope_elements=["ASSESS", "TREAT", "SUPERVISE"]
    )
    spouse_application = setup.application(
        spouse["id"],
        profession["id"],
        spouse_credential["id"],
        pathway=PATHWAY_MILITARY_SPOUSE_EXPEDITED,
    )
    setup.submit(spouse_application["id"], spouse["id"])

    return {
        "endorsement": {
            "app_id": civilian_application["id"],
            "app_version": setup.application_version(civilian_application["id"]),
        },
        "expedited": {
            "app_id": spouse_application["id"],
            "app_version": setup.application_version(spouse_application["id"]),
        },
    }


@pytest.fixture
def spouse_licensed_in_two_professions(setup):
    """One military spouse carrying an expedited file in each of two professions, both
    settled at zero and both exempt from the evaluation precondition."""
    nursing = setup.profession()
    therapy = setup.profession(**PT_PROFESSION)
    applicant = setup.applicant(
        full_name="Devi Anand",
        state_code="TX",
        residency_months=4,
        military_status=MILITARY_SPOUSE,
    )
    arms = {}
    for key, profession, license_number, scope, hours in (
        ("rn", nursing, "OK-70101", ["ASSESS", "TREAT", "SUPERVISE"], 1200),
        ("pt", therapy, "OK-70102", ["EVAL", "MANUAL", "MODALITY"], 1000),
    ):
        credential = setup.credential(
            applicant["id"],
            license_number=license_number,
            scope_elements=scope,
            practice_hours=hours,
        )
        application = setup.application(
            applicant["id"],
            profession["id"],
            credential["id"],
            pathway=PATHWAY_MILITARY_SPOUSE_EXPEDITED,
        )
        setup.submit(application["id"], applicant["id"])
        arms[key] = {"app_id": application["id"]}
    return {"ap_id": applicant["id"], **arms}


class TestEvaluationBeforePermit:
    def test_an_endorsement_permit_needs_a_scope_comparison_on_file_first(
        self, api, two_pathways_without_evaluations, setup
    ):
        """PRD §3.8: "On the `ENDORSEMENT` and `UNIVERSAL_RECOGNITION` pathways a
        credential evaluation must already exist for the application before a permit
        may issue, because the agency wants a scope comparison on file first; the
        rejection is `ERR_EVALUATION_REQUIRED_FOR_PERMIT`."

        Design: Difficulty/cross_entity_state_dependency/permit_requires_evaluation_except_on_military_spouse_expedited_pathway
        """
        arm = two_pathways_without_evaluations["endorsement"]
        response = api.create_temporary_permit(
            temporary_permit_payload(arm["app_id"], "2026-08-01T00:00:00Z", arm["app_version"]),
            ANALYST_HEADERS,
        )

        validate_error(response, ApiErrorId.ERR_EVALUATION_REQUIRED_FOR_PERMIT.value, 422)
        assert setup.read_permits(arm["app_id"]) == []
        assert_application_fields(setup.read_application(arm["app_id"]), fee_balance_cents=0)

    def test_the_military_spouse_pathway_issues_a_permit_during_full_review(
        self, api, two_pathways_without_evaluations
    ):
        """PRD §3.8: "The `MILITARY_SPOUSE_EXPEDITED` pathway is exempt from that
        requirement entirely — permits on that pathway issue during full review, which
        is the statutory point of the pathway."

        Design: Difficulty/cross_entity_state_dependency/permit_requires_evaluation_except_on_military_spouse_expedited_pathway
        """
        arm = two_pathways_without_evaluations["expedited"]
        permit = validate_success(
            api.create_temporary_permit(
                temporary_permit_payload(arm["app_id"], "2026-08-01T00:00:00Z", arm["app_version"]),
                ANALYST_HEADERS,
            ),
            201,
        )

        assert_permit_fields(
            permit,
            status=PERMIT_ACTIVE,
            effective_at="2026-08-01T00:00:00Z",
            converted_at=None,
            revoked_at=None,
            revocation_reason_code=None,
        )

    def test_the_thirty_day_grace_cap_beats_the_hundred_and_eighty_day_pathway_cap(
        self, api, two_pathways_without_evaluations, setup
    ):
        """PRD §3.4: "Its `review_deadline_at` is derived by choosing a processing
        allowance and adding it to `submitted_at` as whole days: the allowance is the
        expedite allowance of 30 days whenever `expedited` is true **or** the pathway
        is `MILITARY_SPOUSE_EXPEDITED`, and otherwise it is the profession's published
        `standard_processing_days`."  PRD §3.8: "One candidate end is the requested
        `effective_at` advanced by that many whole days. The other candidate end is the
        application's `review_deadline_at` advanced by a grace allowance of 30 whole
        days. The permit's `expires_at` is whichever of those two candidates is
        earlier, so a permit can never outlive the review it bridges by more than the
        grace allowance, and can never exceed its pathway's statutory maximum either."

        Design: Difficulty/cross_entity_state_dependency/permit_requires_evaluation_except_on_military_spouse_expedited_pathway
        """
        arm = two_pathways_without_evaluations["expedited"]
        assert_application_fields(
            setup.read_application(arm["app_id"]),
            status=APP_SUBMITTED,
            review_deadline_at="2026-08-31T00:00:00Z",
        )

        permit = validate_success(
            api.create_temporary_permit(
                temporary_permit_payload(arm["app_id"], "2026-08-01T00:00:00Z", arm["app_version"]),
                ANALYST_HEADERS,
            ),
            201,
        )
        assert_permit_fields(permit, permit_max_days=180, expires_at="2026-09-30T00:00:00Z")

    def test_the_expedited_pathway_drops_the_endorsement_component_into_a_full_waiver(
        self, api, two_pathways_without_evaluations, setup
    ):
        """PRD §3.4: "The endorsement component is the profession's
        `endorsement_fee_cents` when the pathway is `ENDORSEMENT` or
        `UNIVERSAL_RECOGNITION`, and zero on the `MILITARY_SPOUSE_EXPEDITED` pathway."

        Design: Difficulty/cross_entity_state_dependency/permit_requires_evaluation_except_on_military_spouse_expedited_pathway
        """
        arm = two_pathways_without_evaluations["expedited"]
        assert_application_fields(
            setup.read_application(arm["app_id"]),
            gross_total_cents=38000,
            statutory_waiver_pct=1.00,
            fee_balance_cents=0,
        )

        permit = validate_success(
            api.create_temporary_permit(
                temporary_permit_payload(arm["app_id"], "2026-08-01T00:00:00Z", arm["app_version"]),
                ANALYST_HEADERS,
            ),
            201,
        )
        assert_permit_fields(permit, permit_fee_cents=0)
        assert_application_fields(setup.read_application(arm["app_id"]), fee_balance_cents=0)


class TestOverlapScope:
    def test_identical_windows_coexist_when_the_professions_differ(
        self, api, spouse_licensed_in_two_professions, setup
    ):
        """PRD §3.8: "Issuance is refused when any temporary permit whose `status` is
        `ACTIVE` or `CONVERTED`, and whose own application shares both the same
        applicant and the same profession as this application, satisfies both of the
        following: the new permit's `effective_at` is strictly before that permit's
        `expires_at`, and that permit's `effective_at` is strictly before the new
        permit's `expires_at`."

        Design: Difficulty/resource_temporal_overlap/permit_overlap_scoped_to_applicant_profession_pair_not_across_professions
        """
        env = spouse_licensed_in_two_professions
        nursing_permit = setup.permit(env["rn"]["app_id"], "2026-08-01T00:00:00Z")
        therapy_permit = validate_success(
            api.create_temporary_permit(
                temporary_permit_payload(
                    env["pt"]["app_id"],
                    "2026-08-01T00:00:00Z",
                    setup.application_version(env["pt"]["app_id"]),
                ),
                ANALYST_HEADERS,
            ),
            201,
        )

        for permit in (nursing_permit, therapy_permit):
            assert_permit_fields(
                permit,
                status=PERMIT_ACTIVE,
                effective_at="2026-08-01T00:00:00Z",
                expires_at="2026-09-30T00:00:00Z",
            )
        # The requirements scope the collision test to the *application's* profession
        # ("whose own application shares both the same applicant and the same profession
        # as this application"), so the differing professions are read off the two
        # applications rather than off the permits.
        nursing_application = setup.read_application(env["rn"]["app_id"])
        therapy_application = setup.read_application(env["pt"]["app_id"])
        assert nursing_application["applicant_id"] == therapy_application["applicant_id"]
        assert nursing_application["profession_id"] != therapy_application["profession_id"]
        assert nursing_permit["application_id"] == nursing_application["id"]
        assert therapy_permit["application_id"] == therapy_application["id"]

    def test_a_second_permit_inside_the_live_nursing_window_still_collides(
        self, api, spouse_licensed_in_two_professions, setup
    ):
        """PRD §3.8: "Practice authority must not double up, and the collision test
        here is **half-open** — the interval runs from `effective_at` inclusive to
        `expires_at` exclusive."

        Design: Difficulty/resource_temporal_overlap/permit_overlap_scoped_to_applicant_profession_pair_not_across_professions
        """
        env = spouse_licensed_in_two_professions
        setup.permit(env["rn"]["app_id"], "2026-08-01T00:00:00Z")
        setup.permit(env["pt"]["app_id"], "2026-08-01T00:00:00Z")

        response = api.create_temporary_permit(
            temporary_permit_payload(
                env["rn"]["app_id"],
                "2026-09-01T00:00:00Z",
                setup.application_version(env["rn"]["app_id"]),
            ),
            ANALYST_HEADERS,
        )

        validate_error(response, ApiErrorId.ERR_PERMIT_WINDOW_OVERLAP.value, 409)
        assert len(setup.read_permits(env["rn"]["app_id"])) == 1

    def test_both_expedited_permits_take_the_pathway_maximum_and_cost_nothing(
        self, spouse_licensed_in_two_professions, setup
    ):
        """PRD §3.8: "The `permit_max_days` frozen onto the permit at issuance is
        selected by the application's `pathway`: 90 days for `ENDORSEMENT`, 120 days
        for `UNIVERSAL_RECOGNITION`, and 180 days for `MILITARY_SPOUSE_EXPEDITED`."
        PRD §3.8: "The permit's own `permit_fee_cents` is frozen at issuance as the
        profession's list `permit_fee_cents` less the waived portion, where the waived
        portion is that list price multiplied by the application's frozen
        `statutory_waiver_pct` and rounded half up to a whole cent."

        Design: Difficulty/resource_temporal_overlap/permit_overlap_scoped_to_applicant_profession_pair_not_across_professions
        """
        env = spouse_licensed_in_two_professions
        nursing_permit = setup.permit(env["rn"]["app_id"], "2026-08-01T00:00:00Z")
        therapy_permit = setup.permit(env["pt"]["app_id"], "2026-08-01T00:00:00Z")

        assert_permit_fields(nursing_permit, permit_max_days=180, permit_fee_cents=0)
        assert_permit_fields(therapy_permit, permit_max_days=180, permit_fee_cents=0)
        assert_application_fields(
            setup.read_application(env["rn"]["app_id"]), fee_balance_cents=0
        )
        assert_application_fields(
            setup.read_application(env["pt"]["app_id"]), fee_balance_cents=0
        )
