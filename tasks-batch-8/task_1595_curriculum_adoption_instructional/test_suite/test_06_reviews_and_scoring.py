"""Teacher review rubric: provisional composite liveness, withdrawal
semantics, the trimmed official variant at close-pilots, and the
participation rate's input set."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_pilot,
    get_material,
    get_pilot,
    make_teacher_headers,
    setup_active_pilot,
    setup_cycle_in_pilot_open,
    setup_cycle_in_scoring,
    submit_review,
    transition_cycle,
    transition_pilot,
    validate_error,
)

TEACHER = TEST_USERS["teacher_headers"]
DIRECTOR = TEST_USERS["curriculum_director_headers"]


class TestProvisionalComposite:
    def test_provisional_null_without_reviews(self, api):
        """PRD §3.3: "The provisional composite is the untrimmed mean of the
        `review_composite` values over all `SUBMITTED` reviews attached to
        pilots that reference this material within this cycle and are in
        `ACTIVE` or `CLOSED` status, rounded half-up to two decimal places;
        while no such reviews exist it is null."
        PRD §3.3: "Both figures stay null on a material until the cycle
        enters `SCORING`."

        Design: Corner/calculations/provisional_null_without_reviews
        """
        ctx = setup_cycle_in_pilot_open()
        pilot = create_pilot(ctx["cycle"]["id"], ctx["material"]["id"],
                             school_code="SCH-A", teacher_count=2)
        transition_pilot(pilot["id"], "ACTIVE")
        material = get_material(ctx["material"]["id"])
        assert material["provisional_composite"] is None
        assert material["official_composite"] is None

    def test_provisional_recomputed_on_withdraw(self, api):
        """PRD §3.3: "Withdrawal moves the review to `WITHDRAWN` and
        recomputes the pilot's `submitted_review_count` and the material's
        `provisional_composite` with the withdrawn review excluded."

        Design: Corner/calculations/provisional_recomputed_on_withdraw
        """
        ctx = setup_active_pilot(
            reviews=[(4, 4, 4, 4), (2, 2, 2, 2), (4, 4, 4, 4)],
            teacher_count=3)
        assert get_material(ctx["material"]["id"])["provisional_composite"] == \
            pytest.approx(3.33, abs=0.01), "mean of 4.0, 2.0, 4.0"

        low_review = ctx["reviews"][1]
        resp = api.withdraw_review(low_review["id"], make_teacher_headers("t2"))
        assert resp.status_code == 200

        assert get_material(ctx["material"]["id"])["provisional_composite"] == \
            pytest.approx(4.00, abs=0.01), "mean of 4.0, 4.0 after exclusion"
        assert get_pilot(ctx["pilot"]["id"])["submitted_review_count"] == 2


class TestReviewSubmissionGates:
    def test_duplicate_review_then_withdraw_then_rereview(self, api):
        """PRD §3.3: "A teacher may hold at most one `SUBMITTED` review per
        pilot; a second submission is rejected with `ERR_DUPLICATE_REVIEW`."

        Design: Corner/validations/duplicate_review_then_withdraw_then_rereview
        """
        ctx = setup_active_pilot(reviews=((4, 4, 4, 4),), teacher_count=2)
        review = ctx["reviews"][0]

        # A second SUBMITTED review by the same teacher is rejected.
        validate_error(
            api.create_review(ctx["pilot"]["id"], {
                "pedagogy_score": 1, "alignment_score": 1,
                "usability_score": 1, "equity_score": 1},
                make_teacher_headers("t1")),
            ApiErrorId.ERR_DUPLICATE_REVIEW)

        # Withdrawing frees the slot: a fresh submission succeeds and the
        # WITHDRAWN one no longer counts.
        api.withdraw_review(review["id"], make_teacher_headers("t1"))
        resp = api.create_review(ctx["pilot"]["id"], {
            "pedagogy_score": 3, "alignment_score": 3,
            "usability_score": 3, "equity_score": 3},
            make_teacher_headers("t1"))
        assert resp.status_code == 201
        assert get_pilot(ctx["pilot"]["id"])["submitted_review_count"] == 1

    def test_review_withdraw_twice_rejected(self, api):
        """PRD §3.3: "withdrawing after the pilot has closed, or withdrawing
        a review that is not `SUBMITTED`, fails with `ERR_INVALID_STATE`"

        Design: Corner/state_machines/review_withdraw_twice_rejected
        """
        ctx = setup_active_pilot(reviews=((4, 4, 4, 4),), teacher_count=2)
        review = ctx["reviews"][0]
        first = api.withdraw_review(review["id"], make_teacher_headers("t1"))
        assert first.status_code == 200
        assert first.json()["data"]["status"] == "WITHDRAWN"
        validate_error(api.withdraw_review(review["id"],
                                           make_teacher_headers("t1")),
                       ApiErrorId.ERR_INVALID_STATE)

    def test_review_withdraw_ownership_denied(self, api):
        """PRD §3.3: "withdrawing after the pilot has closed, or withdrawing
        a review that is not `SUBMITTED`, fails with `ERR_INVALID_STATE`, and
        withdrawing another teacher's review fails with
        `ERR_INSUFFICIENT_PERMISSIONS`."

        Design: Corner/rbac/review_withdraw_ownership_denied
        """
        ctx = setup_active_pilot(reviews=((4, 4, 4, 4),), teacher_count=2)
        review = ctx["reviews"][0]  # submitted by t1
        validate_error(api.withdraw_review(review["id"],
                                           make_teacher_headers("t2")),
                       ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
        assert get_pilot(ctx["pilot"]["id"])["submitted_review_count"] == 1


class TestProvisionalVsOfficialTrim:
    def test_trimmed_official_differs_from_provisional(self, api):
        """PRD §3.3: "The `official_composite` is the trimmed variant of the
        pilot composite — when the review pool (as defined for the provisional
        composite) holds at least five reviews, exactly one lowest and one
        highest `review_composite` are discarded, one instance each even when
        several reviews tie at an extreme, and the mean of the remaining
        values is rounded half-up to two decimal places; with fewer than five
        reviews, the official value is identical to the provisional one."
        PRD §3.3: "The `participation_rate` is the count of `SUBMITTED`
        reviews across the material's pilots in this cycle that are `ACTIVE`
        or `CLOSED` at this moment, divided by the sum of those pilots'
        `teacher_count` values, rounded half-up to four decimal places"

        Design: Difficulty/dual_variant_calc/rubric_provisional_vs_official_trim
        """
        # Composites: 4.0, 3.0, 2.0, 3.6, 1.4 -> provisional 2.80; official
        # drops 1.4 and 4.0 -> mean(3.0, 2.0, 3.6) = 2.87.
        ctx = setup_cycle_in_scoring(
            reviews=[(4, 4, 4, 4), (3, 3, 3, 3), (2, 2, 2, 2),
                     (4, 3, 4, 3), (1, 2, 1, 2)],
            teacher_count=8)
        material = get_material(ctx["material"]["id"])
        assert material["provisional_composite"] == pytest.approx(2.80, abs=0.01)
        assert material["official_composite"] == pytest.approx(2.87, abs=0.01)
        assert material["participation_rate"] == pytest.approx(0.625, abs=0.0001)
        assert material["official_composite"] != material["provisional_composite"], (
            "the trimmed variant differs from the untrimmed mean on the same "
            "review data")

    def test_trim_drops_one_instance_each_even_when_tied(self, api):
        """PRD §3.3: "when the review pool (as defined for the provisional
        composite) holds at least five reviews, exactly one lowest and one
        highest `review_composite` are discarded, one instance each even when
        several reviews tie at an extreme, and the mean of the remaining
        values is rounded half-up to two decimal places"

        Design: Difficulty/dual_variant_calc/rubric_provisional_vs_official_trim
        """
        # Composites: 4.0, 4.0, 3.0, 1.0, 1.0 -> provisional 2.60; official
        # drops ONE 1.0 and ONE 4.0 -> mean(4.0, 3.0, 1.0) = 2.67.
        ctx = setup_cycle_in_scoring(
            reviews=[(4, 4, 4, 4), (4, 4, 4, 4), (3, 3, 3, 3),
                     (1, 1, 1, 1), (1, 1, 1, 1)],
            teacher_count=5)
        material = get_material(ctx["material"]["id"])
        assert material["provisional_composite"] == pytest.approx(2.60, abs=0.01)
        assert material["official_composite"] == pytest.approx(2.67, abs=0.01)


class TestParticipationInputSet:
    def test_participation_excludes_cancelled_pilots(self, api):
        """PRD §3.3: "The `participation_rate` is the count of `SUBMITTED`
        reviews across the material's pilots in this cycle that are `ACTIVE`
        or `CLOSED` at this moment, divided by the sum of those pilots'
        `teacher_count` values, rounded half-up to four decimal places;
        cancelled pilots contribute nothing, and when that denominator is
        zero the rate is null."

        Design: Corner/calculations/participation_excludes_cancelled_pilots
        """
        ctx = setup_cycle_in_pilot_open()
        cycle_id, material_id = ctx["cycle"]["id"], ctx["material"]["id"]
        p1 = create_pilot(cycle_id, material_id, school_code="SCH-A",
                          teacher_count=5)
        p2 = create_pilot(cycle_id, material_id, school_code="SCH-B",
                          teacher_count=9)
        transition_pilot(p1["id"], "ACTIVE")
        submit_review(p1["id"], "t1", (4, 4, 4, 4))   # composite 4.0
        submit_review(p1["id"], "t2", (3, 4, 3, 3))   # composite 3.3
        transition_pilot(p1["id"], "CLOSED")
        transition_pilot(p2["id"], "CANCELLED")  # cancelled while PLANNED

        transition_cycle(cycle_id, "SCORING")
        material = get_material(material_id)
        # 2 reviews / 5 seats (the 9-seat CANCELLED pilot contributes nothing).
        assert material["participation_rate"] == pytest.approx(0.40, abs=0.0001)
        # n=2 < 5 reviews: the official value equals the provisional mean.
        assert material["official_composite"] == pytest.approx(3.65, abs=0.01)
