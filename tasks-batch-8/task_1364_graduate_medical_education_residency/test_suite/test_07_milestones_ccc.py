"""Milestone evaluations and the Clinical Competency Committee: immutability,
the six-competency rating rule, weighted composite scoring, the evaluation
quorum, the reopen cycle, outcome cascades, and segregation of duties
(PRD §3.7)."""
from test_helpers import (
    COMPETENCIES, PD, ApiClient, ApiErrorId, approx2, assert_evaluation,
    create_evaluation_payload, finalize_ccc_payload, list_probation_cases,
    list_remediation_plans, make_ccc_chair_headers, make_ccc_review,
    make_evaluation, make_faculty_headers, make_moonlighting, set_clock,
    setup_ccc_in_deliberation, setup_program_with_active_resident, six_ratings,
    validate_error, validate_success,
)


def _review(api, review_id):
    return validate_success(api.get_ccc_review(review_id, PD))


class TestEvaluationImmutability:
    def test_evaluation_carries_no_version_or_updated_at(self, api: ApiClient):
        """PRD §2.5: "One entity is the exception: a milestone evaluation is
        immutable once submitted. It carries `id` and `created_at` only — it
        has no `updated_at` and no `version` field, and no operation modifies
        it after creation."
        PRD §3.7: "The server stamps the submission with `evaluator_id` taken
        from `X-User-ID` and `evaluator_role` copied from `X-User-Role` —
        `FACULTY` for a `FacultyEvaluator`, `PROGRAM_DIRECTOR` for a
        `ProgramDirector`".

        Design: Corner/entities/evaluation_immutable_common_fields_absent
        """
        s = setup_program_with_active_resident()
        ev = make_evaluation(s["resident"], s["year"], user_id="ev-1")
        assert_evaluation(ev)
        assert ev["evaluator_id"] == "ev-1"
        assert ev["evaluator_role"] == "FACULTY"


class TestIncompleteRatings:
    def test_five_of_six_competencies_rejected(self, api: ApiClient):
        """PRD §3.7: "The payload's `competency_ratings` must contain exactly
        six entries, one for each of `PATIENT_CARE`, `MEDICAL_KNOWLEDGE`,
        `PROFESSIONALISM`, `COMMUNICATION`, `PRACTICE_BASED_LEARNING`, and
        `SYSTEMS_BASED_PRACTICE`, each with an integer level from 1 through 5;
        anything else is rejected with `ERR_INCOMPLETE_RATINGS` (HTTP 422)."

        Design: Corner/validations/incomplete_ratings_rejected
        """
        s = setup_program_with_active_resident()
        ratings = six_ratings(3)[:-1]  # SYSTEMS_BASED_PRACTICE missing
        resp = api.create_evaluation(
            create_evaluation_payload(s["resident"]["id"], s["year"]["id"],
                                      competency_ratings=ratings),
            make_faculty_headers("ev-1"))
        validate_error(resp, ApiErrorId.ERR_INCOMPLETE_RATINGS)
        assert resp.status_code == 422


class TestCompositeWeightedScoring:
    def test_program_director_ratings_weigh_double(self, api: ApiClient):
        """PRD §3.7: "for each of the six competencies, over all milestone
        evaluations of the triple, each evaluation's level is weighted — 2.0
        when its `evaluator_role` is `PROGRAM_DIRECTOR`, 1.0 when `FACULTY` —
        and the composite level is the sum of level-times-weight divided by the
        sum of weights, rounded half-up once, at the end, to 1 decimal place;
        the snapshot's keys are the six competency codes."

        Design: Corner/calculations/milestone_composite_weighted_scoring
        """
        s = setup_program_with_active_resident()
        resident, year = s["resident"], s["year"]
        make_evaluation(resident, year, user_id="ev-1", patient_care=2)
        make_evaluation(resident, year, user_id="pd-7", role="ProgramDirector",
                        patient_care=4)
        make_evaluation(resident, year, user_id="ev-2", patient_care=4)
        review = make_ccc_review(resident, year, chair_id="chair-1")
        review = validate_success(api.begin_deliberation(
            review["id"], make_ccc_chair_headers("chair-1")))

        finalized = validate_success(api.finalize_ccc_review(
            review["id"], finalize_ccc_payload("SATISFACTORY"),
            make_ccc_chair_headers("chair-1")))
        assert finalized["status"] == "FINALIZED"
        snapshot = finalized["composite_snapshot"]
        assert set(snapshot.keys()) == set(COMPETENCIES)
        # (2 x 1.0 + 4 x 2.0 + 4 x 1.0) / (1.0 + 2.0 + 1.0) = 14/4 = 3.5;
        # an unweighted mean (3.33) would round to 3.3.
        assert snapshot["PATIENT_CARE"] == approx2(3.5)
        for comp in COMPETENCIES:
            if comp != "PATIENT_CARE":
                assert snapshot[comp] == approx2(3.0)


class TestFinalizeQuorum:
    def test_two_evaluations_fail_quorum(self, api: ApiClient):
        """PRD §3.7: "at least three milestone evaluations must exist for the
        triple (`ERR_INSUFFICIENT_EVALUATIONS`, HTTP 409)".

        Design: Difficulty/cross_entity_state_dependency/ccc_finalize_requires_evaluation_quorum
        """
        s = setup_program_with_active_resident()
        resident, year = s["resident"], s["year"]
        review = setup_ccc_in_deliberation(resident, year, num_evals=2,
                                           chair_id="chair-1")
        resp = api.finalize_ccc_review(
            review["id"], finalize_ccc_payload("SATISFACTORY"),
            make_ccc_chair_headers("chair-1"))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_EVALUATIONS)
        assert resp.status_code == 409
        assert _review(api, review["id"])["status"] == "IN_DELIBERATION"

    def test_third_evaluation_unlocks_finalize(self, api: ApiClient):
        """PRD §3.7: "at least three milestone evaluations must exist for the
        triple (`ERR_INSUFFICIENT_EVALUATIONS`, HTTP 409)" and "Finalization
        records the `outcome` and `milestone_levels`, moves the review to its
        terminal `FINALIZED` state, and computes the `composite_snapshot`".

        Design: Difficulty/cross_entity_state_dependency/ccc_finalize_requires_evaluation_quorum
        """
        s = setup_program_with_active_resident()
        resident, year = s["resident"], s["year"]
        review = setup_ccc_in_deliberation(resident, year, num_evals=2,
                                           chair_id="chair-1")
        make_evaluation(resident, year, user_id="ev-3")

        finalized = validate_success(api.finalize_ccc_review(
            review["id"], finalize_ccc_payload("SATISFACTORY"),
            make_ccc_chair_headers("chair-1")))
        assert finalized["status"] == "FINALIZED"
        assert isinstance(finalized["composite_snapshot"], dict)
        assert set(finalized["composite_snapshot"].keys()) == set(COMPETENCIES)
        # Outcome SATISFACTORY fires no remediation/probation cascade.
        _, pmeta = list_probation_cases(resident_id=resident["id"])
        _, rmeta = list_remediation_plans(resident_id=resident["id"])
        assert pmeta["total_count"] == 0
        assert rmeta["total_count"] == 0


class TestReopenCycle:
    def test_deliberation_cycle_repeats(self, api: ApiClient):
        """PRD §3.7: "Beginning deliberation requires `OPEN` (otherwise
        `ERR_CCC_NOT_OPEN`, HTTP 409) and moves the review to
        `IN_DELIBERATION`; reopening returns an `IN_DELIBERATION` review to
        `OPEN` (otherwise `ERR_CCC_NOT_IN_DELIBERATION`, HTTP 409), and the
        open–deliberation cycle may repeat any number of times."

        Design: Corner/state_machines/ccc_reopen_deliberation_cycle
        """
        s = setup_program_with_active_resident()
        review = make_ccc_review(s["resident"], s["year"], chair_id="chair-1")
        assert review["status"] == "OPEN" and review["version"] == 1
        chair = make_ccc_chair_headers("chair-1")

        review = validate_success(api.begin_deliberation(review["id"], chair))
        assert review["status"] == "IN_DELIBERATION"
        review = validate_success(api.reopen_ccc_review(review["id"], chair))
        assert review["status"] == "OPEN"
        review = validate_success(api.begin_deliberation(review["id"], chair))
        assert review["status"] == "IN_DELIBERATION"
        assert review["version"] == 4  # create + 3 transitions


class TestUnsatisfactoryCascade:
    def _setup(self, api):
        s = setup_program_with_active_resident(approved_positions=4)
        resident, year = s["resident"], s["year"]
        moon = make_moonlighting(resident, type="INTERNAL",
                                 site_name="Metro ICU",
                                 start_date="2026-08-03", end_date="2026-10-01",
                                 hours_per_week=5.00, approve=True)
        set_clock("2026-08-10T12:00:00Z")
        review = setup_ccc_in_deliberation(resident, year, num_evals=3,
                                           chair_id="chair-1", level=2)
        return s, moon, review

    def test_finalize_creates_probation_and_flips_standing(self, api: ApiClient):
        """PRD §3.7: "An `UNSATISFACTORY` outcome creates a probation case with
        reason "CCC outcome UNSATISFACTORY" and status `ACTIVE`, firing the
        standing cascade, the moonlighting sweep, and a recomputation of the
        weekly hour aggregates."
        PRD §3.8: "The derivation is a strict priority: `ON_PROBATION` when any
        probation case of the resident is `ACTIVE` or `DISMISSAL_RECOMMENDED`".

        Design: Difficulty/transitive_cascade/ccc_unsatisfactory_probation_cascade
        """
        s, _, review = self._setup(api)
        resident = s["resident"]
        finalized = validate_success(api.finalize_ccc_review(
            review["id"], finalize_ccc_payload("UNSATISFACTORY", level=2),
            make_ccc_chair_headers("chair-1")))
        assert finalized["status"] == "FINALIZED"

        cases, meta = list_probation_cases(resident_id=resident["id"])
        assert meta["total_count"] == 1
        assert cases[0]["status"] == "ACTIVE"
        assert cases[0]["reason"] == "CCC outcome UNSATISFACTORY"
        r = validate_success(api.get_resident(resident["id"], PD))
        assert r["standing_status"] == "ON_PROBATION"
        # The standing cascade does not touch the lifecycle dimension.
        assert r["lifecycle_status"] == "ACTIVE"

    def test_sweep_revokes_active_moonlighting_and_recomputes(self, api: ApiClient):
        """PRD §3.6: "whenever a resident's standing leaves `GOOD_STANDING`
        (§3.8), every one of the resident's requests in `APPROVED` or `ACTIVE`
        is revoked with `decision_reason` set to `STANDING_CHANGE`, and the
        weekly aggregates are recomputed without those hours."

        Design: Difficulty/transitive_cascade/ccc_unsatisfactory_probation_cascade
        """
        s, moon, review = self._setup(api)
        resident = s["resident"]
        # The clock entered the window: the request is ACTIVE before finalize.
        before_req = validate_success(api.get_moonlighting(moon["id"], PD))
        assert before_req["status"] == "ACTIVE"
        before = validate_success(
            api.get_duty_hour_summary(resident["id"], "2026-08-10", PD))
        assert before["attributed_moonlighting_hours"] == approx2(5.00)

        validate_success(api.finalize_ccc_review(
            review["id"], finalize_ccc_payload("UNSATISFACTORY", level=2),
            make_ccc_chair_headers("chair-1")))

        after = validate_success(api.get_moonlighting(moon["id"], PD))
        assert after["status"] == "REVOKED"
        assert after["decision_reason"] == "STANDING_CHANGE"
        summary = validate_success(
            api.get_duty_hour_summary(resident["id"], "2026-08-10", PD))
        assert summary["attributed_moonlighting_hours"] == approx2(0.00)


class TestSegregationOfDuties:
    def test_faculty_cannot_finalize(self, api: ApiClient):
        """PRD §2.1: "an attempt to perform an action outside the caller's
        designated role is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
        (HTTP 403)."
        PRD §3.7: "The Clinical Competency Committee works through review
        records owned by the `CCCChair`."

        Design: Corner/rbac/faculty_cannot_finalize_ccc_review
        """
        s = setup_program_with_active_resident()
        review = setup_ccc_in_deliberation(s["resident"], s["year"],
                                           num_evals=3, chair_id="chair-1")
        resp = api.finalize_ccc_review(
            review["id"], finalize_ccc_payload("SATISFACTORY"),
            make_faculty_headers("ev-4"))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
        assert resp.status_code == 403
        assert _review(api, review["id"])["status"] == "IN_DELIBERATION"

    def test_evaluator_of_period_cannot_finalize_it(self, api: ApiClient):
        """PRD §3.7: "segregation of duties forbids the chair from finalizing a
        review of a period they personally evaluated — the caller's `X-User-ID`
        must not equal the `evaluator_id` of any evaluation for the triple
        (`ERR_COMMITTEE_ROLE_CONFLICT`, HTTP 403)."

        Design: Corner/rbac/sod_committee_evaluator_cannot_finalize_own_period
        """
        s = setup_program_with_active_resident()
        review = setup_ccc_in_deliberation(
            s["resident"], s["year"], num_evals=3, chair_id="chair-1",
            evaluator_ids=["ev-1", "ev-2", "ev-3"])
        # Chair whose operator id appears among the period's evaluators.
        resp = api.finalize_ccc_review(
            review["id"], finalize_ccc_payload("SATISFACTORY"),
            make_ccc_chair_headers("ev-1"))
        validate_error(resp, ApiErrorId.ERR_COMMITTEE_ROLE_CONFLICT)
        assert resp.status_code == 403

        # A non-evaluator chair finalizes successfully.
        finalized = validate_success(api.finalize_ccc_review(
            review["id"], finalize_ccc_payload("SATISFACTORY"),
            make_ccc_chair_headers("chair-1")))
        assert finalized["status"] == "FINALIZED"
