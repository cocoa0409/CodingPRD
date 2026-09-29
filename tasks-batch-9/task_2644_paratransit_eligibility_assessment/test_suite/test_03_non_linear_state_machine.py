"""A packet's return-and-resubmit cycle, and one assessment's parallel dimensions."""
from test_helpers import factories, validate_success
from test_helpers.fixtures import attended_assessment, create_applicant, set_clock
from test_helpers.test_users import (
    CLERK_HEADERS,
    EVALUATOR_HEADERS,
    SPECIALIST_HEADERS,
)

_ANSWERS = factories.functional_answers(
    can_board_bus_steps=False,
    can_navigate_unfamiliar_route=False,
    max_walk_distance_meters=150,
    uses_mobility_aid_outdoors=True,
    has_cognitive_impairment=False,
)


def _returned_incomplete_packet(api):
    """A packet submitted on 2026-08-01 and then returned as incomplete."""
    set_clock(api, "2026-08-01T00:00:00Z")
    rider = create_applicant(
        api,
        full_name="Nadia Brant",
        date_of_birth="1954-06-03",
        residence_zone="IN_SERVICE_AREA",
        mobility_aid="WALKER",
    )
    application = validate_success(
        api.create_application(
            factories.application_payload(
                rider["id"], application_type="NEW", functional_answers=_ANSWERS
            ),
            CLERK_HEADERS,
        ),
        201,
    )
    validate_success(
        api.submit_application(application["id"], factories.submit_payload(), CLERK_HEADERS)
    )
    returned = validate_success(
        api.return_application_incomplete(
            application["id"],
            factories.return_incomplete_payload(missing_items=["proof of residence"]),
            CLERK_HEADERS,
        )
    )
    return {"rider": rider, "application": returned}


def test_returning_a_packet_as_incomplete_stops_the_statutory_clock(api):
    """The return edge nulls both the completeness stamp and the due date.

    "Returning a packet stops the statutory clock hard:
    `completeness_established_at` is set back to null and
    `determination_due_date` becomes null with it, and `days_pending_statutory`
    freezes at whatever value it held at the moment of the return."

    "The request must carry `missing_items` as a non-empty array of item labels —
    an empty array or a non-array value is `ERR_INVALID_REQUEST` — and those
    labels are stored verbatim on the packet so the rider knows what to supply."

    Design: Difficulty/non_linear_state_machine/application_return_incomplete_resubmit_cycle_resets_statutory_clock
    """
    context = _returned_incomplete_packet(api)
    application = context["application"]

    assert application["status"] == "RETURNED_INCOMPLETE"
    assert application["completeness_established_at"] is None
    assert application["determination_due_date"] is None
    assert application["missing_items"] == ["proof of residence"]


def test_resubmission_resets_the_statutory_clock_rather_than_resuming_it(api):
    """The second visit to SUBMITTED restarts the twenty-one-day count from zero.

    "Here the crucial rule is that the statutory clock is **reset, not resumed**.
    `completeness_established_at` is set to the new `submitted_at`, so the 21-day
    count restarts from zero and `determination_due_date` becomes the date of the
    new `submitted_at` plus 21 days; days that elapsed before the
    return-incomplete never enter the count again."

    Design: Difficulty/non_linear_state_machine/application_return_incomplete_resubmit_cycle_resets_statutory_clock
    """
    context = _returned_incomplete_packet(api)

    set_clock(api, "2026-08-15T00:00:00Z")
    resubmitted = validate_success(
        api.submit_application(
            context["application"]["id"],
            factories.submit_payload(functional_answers=_ANSWERS),
            CLERK_HEADERS,
        )
    )

    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["completeness_established_at"] == "2026-08-15T00:00:00.000Z"
    assert resubmitted["determination_due_date"] == "2026-09-05"

    set_clock(api, "2026-08-22T00:00:00Z")
    application = validate_success(
        api.get_application(context["application"]["id"], CLERK_HEADERS)
    )
    assert application["days_pending_statutory"] == 7
    assert application["days_pending_statutory"] != 21


def test_the_resubmission_counter_moves_only_on_the_cycle_edge(api):
    """Coming back from RETURNED_INCOMPLETE is the only edge that counts a cycle.

    "`resubmission_count` increases by one on this edge and only on this edge, so
    it reads as the number of completed return-and-resubmit cycles, and
    `missing_items` is cleared."

    Design: Difficulty/non_linear_state_machine/application_return_incomplete_resubmit_cycle_resets_statutory_clock
    """
    context = _returned_incomplete_packet(api)
    assert context["application"]["resubmission_count"] == 0

    set_clock(api, "2026-08-15T00:00:00Z")
    resubmitted = validate_success(
        api.submit_application(
            context["application"]["id"],
            factories.submit_payload(functional_answers=_ANSWERS),
            CLERK_HEADERS,
        )
    )

    assert resubmitted["resubmission_count"] == 1
    assert resubmitted["missing_items"] == []


def _attended_assessment_for_teo(api):
    set_clock(api, "2026-08-01T00:00:00Z")
    rider = create_applicant(
        api,
        full_name="Teo Halvorsen",
        date_of_birth="1966-09-21",
        residence_zone="IN_SERVICE_AREA",
        mobility_aid="CANE",
    )
    return attended_assessment(api, applicant=rider, attests_permanent=True)


def test_the_scoring_dimension_advances_while_attendance_stays_put(api):
    """Three scoring writes leave the attendance dimension exactly where it was.

    "A functional assessment carries two independent state dimensions that evolve
    separately. The attendance dimension starts at `SCHEDULED` and ends at one of
    `ATTENDED`, `NO_SHOW` or `CANCELLED_BY_AGENCY`. The scoring dimension starts
    at `NOT_STARTED`, passes through `SCORED`, and ends at `SIGNED_OFF`."

    "Scoring is guarded on attendance, but attendance never consults the scoring
    dimension."

    Design: Difficulty/non_linear_state_machine/assessment_attendance_and_scoring_dimensions_evolve_independently
    """
    context = _attended_assessment_for_teo(api)
    assessment_id = context["assessment"]["id"]
    assert context["assessment"]["attendance_recorded_at"] == "2026-08-05T09:30:00.000Z"

    first = validate_success(
        api.record_scores(
            assessment_id,
            factories.scores_payload(
                board_alight_score=2,
                wayfinding_score=3,
                distance_meters_walked=250,
                heat_sensitivity_flag=True,
            ),
            EVALUATOR_HEADERS,
        )
    )
    assert first["scoring_status"] == "SCORED"
    assert first["attendance_status"] == "ATTENDED"
    assert first["recommended_category"] == "CONDITIONAL"

    second = validate_success(
        api.record_scores(
            assessment_id,
            factories.scores_payload(
                board_alight_score=2,
                wayfinding_score=2,
                distance_meters_walked=250,
                heat_sensitivity_flag=True,
                evaluator_notes="wayfinding re-observed",
            ),
            EVALUATOR_HEADERS,
        )
    )
    assert second["scoring_status"] == "SCORED"
    assert second["recommended_category"] == "UNCONDITIONAL"

    signed = validate_success(
        api.sign_off_assessment(
            assessment_id, factories.sign_off_payload(), SPECIALIST_HEADERS
        )
    )
    assert signed["scoring_status"] == "SIGNED_OFF"
    assert signed["attendance_status"] == "ATTENDED"
    assert signed["attendance_recorded_at"] == "2026-08-05T09:30:00.000Z"
    assert signed["scored_by_user_id"] == "eval-1"
    assert signed["signed_off_by_user_id"] == "spec-1"


def test_only_the_terminal_scoring_step_carries_the_packet_forward(api):
    """The packet waits at ASSESSMENT_SCHEDULED until the sign-off lands.

    "A successful sign-off writes `signed_off_by_user_id` from the acting header,
    moves the scoring dimension `SCORED → SIGNED_OFF`, and bubbles up to the
    parent packet: an application sitting in `ASSESSMENT_SCHEDULED` whose
    assessment has attendance `ATTENDED` and scoring `SCORED` advances to
    `ASSESSMENT_COMPLETE`, and the packet's `version` increments with it."

    Design: Difficulty/non_linear_state_machine/assessment_attendance_and_scoring_dimensions_evolve_independently
    """
    context = _attended_assessment_for_teo(api)
    assessment_id = context["assessment"]["id"]
    application_id = context["application"]["id"]

    validate_success(
        api.record_scores(
            assessment_id,
            factories.scores_payload(
                board_alight_score=2,
                wayfinding_score=3,
                distance_meters_walked=250,
                heat_sensitivity_flag=True,
            ),
            EVALUATOR_HEADERS,
        )
    )
    after_first = validate_success(api.get_application(application_id, CLERK_HEADERS))
    assert after_first["status"] == "ASSESSMENT_SCHEDULED"

    validate_success(
        api.record_scores(
            assessment_id,
            factories.scores_payload(
                board_alight_score=2,
                wayfinding_score=2,
                distance_meters_walked=250,
                heat_sensitivity_flag=True,
            ),
            EVALUATOR_HEADERS,
        )
    )
    after_second = validate_success(api.get_application(application_id, CLERK_HEADERS))
    assert after_second["status"] == "ASSESSMENT_SCHEDULED"

    validate_success(
        api.sign_off_assessment(
            assessment_id, factories.sign_off_payload(), SPECIALIST_HEADERS
        )
    )
    after_sign_off = validate_success(api.get_application(application_id, CLERK_HEADERS))
    assert after_sign_off["status"] == "ASSESSMENT_COMPLETE"
