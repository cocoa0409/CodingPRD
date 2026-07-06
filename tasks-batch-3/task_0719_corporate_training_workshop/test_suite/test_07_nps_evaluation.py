"""Post-delivery evaluations and the cohort Net Promoter Score roll-up."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    assert_evaluation,
    setup_open_cohort, setup_delivered_cohort_with_attendance,
    register_learner, register_and_confirm, lock_cohort, set_clock,
    make_learner_headers, make_facilitator_headers,
    TEST_USERS,
)

COORD = TEST_USERS["scheduling_coordinator_headers"]


def _submit_eval(api, reg_id, email, rating):
    return validate_success(
        api.create_evaluation(reg_id, {"nps_rating": rating}, make_learner_headers(email)),
        expected_status=201,
    )


def test_evaluation_not_allowed_from_enrolled(api):
    """PRD §3.7: "A submission from any other registration or cohort state is rejected with
    `ERR_EVALUATION_NOT_ALLOWED`."
    PRD §3.7: "After delivery, a `Learner` whose registration is `ATTENDED` or `NO_SHOW` within a
    cohort that is `DELIVERED` or `CLOSED` may submit an `Evaluation` carrying an `nps_rating` from
    0 through 10 and an optional free-text `comment` (defaulting to empty)."

    Design: Corner/validations/evaluation_not_allowed_from_enrolled_registration
    """
    ctx = setup_open_cohort(category="SALES", version_overrides={"per_seat_cents": 10000, "min_seats": 1})
    reg = register_learner(ctx["cohort"]["id"], "evn@example.com")  # ENROLLED, cohort OPEN
    resp = api.create_evaluation(reg["id"], {"nps_rating": 8}, make_learner_headers("evn@example.com"))
    validate_error(resp, ApiErrorId.ERR_EVALUATION_NOT_ALLOWED.value)


def test_evaluation_append_only_shape(api):
    """PRD §2.4: "The `Evaluation` resource is append-only feedback and carries only an `id` and a
    `created_at`; it has neither an `updated_at` nor a `version` field." PRD §3.7: "a `Learner`
    whose registration is `ATTENDED` or `NO_SHOW` within a cohort that is `DELIVERED` or `CLOSED`
    may submit an `Evaluation` carrying an `nps_rating` from 0 through 10".

    Design: Corner/entities/evaluation_immutable_entity_no_version_field
    """
    ctx = setup_delivered_cohort_with_attendance(
        num_confirmed=1, num_attended=1, delivery_mode="VIRTUAL", category="SALES",
        pricing_model="PER_SEAT", per_seat_cents=10000, min_seats=1, seat_capacity=2,
    )
    reg = ctx["registrations"][0]
    data = validate_success(
        api.create_evaluation(reg["id"], {"nps_rating": 9, "comment": "great"},
                              make_learner_headers("learner0@example.com")),
        expected_status=201,
    )
    assert_evaluation(data)
    assert data["nps_rating"] == 9
    assert "version" not in data, "append-only Evaluation has no version field"
    assert "updated_at" not in data, "append-only Evaluation has no updated_at field"


def test_nps_empty_set_is_null(api):
    """PRD §3.7: "When no evaluations exist, the `nps_score` is null rather than 0."

    Design: Corner/calculations/cohort_nps_empty_set_is_null
    """
    ctx = setup_delivered_cohort_with_attendance(
        num_confirmed=1, num_attended=1, delivery_mode="VIRTUAL", category="SALES",
        pricing_model="PER_SEAT", per_seat_cents=10000, min_seats=1, seat_capacity=2,
    )
    coh = validate_success(api.close_cohort(ctx["cohort"]["id"], COORD))
    assert coh["nps_score"] is None, "empty evaluation set -> null, not 0"


def test_nps_promoters_detractors_aggregation(api):
    """PRD §3.7: "promoters are those rated 9 or 10 (a rating of at least 9) and detractors are
    those rated 6 or below (a rating of at most 6); the score is 100 multiplied by the difference
    of the promoter count and the detractor count, divided by the number of ratings, rounded half
    up to a whole integer in the range -100 through 100."

    Design: Corner/calculations/cohort_nps_promoters_detractors_aggregation
    """
    ctx = setup_delivered_cohort_with_attendance(
        num_confirmed=3, num_attended=3, delivery_mode="VIRTUAL", category="SALES",
        pricing_model="PER_SEAT", per_seat_cents=10000, min_seats=1, seat_capacity=4,
    )
    regs = ctx["registrations"]
    _submit_eval(api, regs[0]["id"], "learner0@example.com", 9)
    _submit_eval(api, regs[1]["id"], "learner1@example.com", 9)
    _submit_eval(api, regs[2]["id"], "learner2@example.com", 7)
    coh = validate_success(api.close_cohort(ctx["cohort"]["id"], COORD))
    # promoters=2, detractors=0, n=3 -> round_half_up(100*2/3)=round_half_up(66.67)=67
    assert coh["nps_score"] == 67
