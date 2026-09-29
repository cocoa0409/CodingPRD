"""Which role may do what, and how early that question is answered."""

from test_helpers import (
    ApiErrorId,
    ParticipantStatus,
    SupportActivityStatus,
    SupportCategory,
    factories,
    fixtures,
    make_case_manager_headers,
    make_funder_analyst_headers,
    make_job_coach_headers,
    make_program_director_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import UNKNOWN_UUID_1, UNKNOWN_UUID_2, UNKNOWN_UUID_3


class TestBusinessLineCreationIsTheDirectorsAlone:
    """A reporting role may read the whole program and write none of it."""

    def test_the_analyst_is_refused_on_a_perfectly_valid_payload(self, api):
        """Authorization is settled before the body is looked at.

        "**Role authorization.** The acting role appears in the endpoint's
        authorized-role list — otherwise `ERR_ROLE_NOT_PERMITTED` (403). Applies
        to every endpoint."

        Design: Corner/rbac/funder_analyst_cannot_create_business_line
        """
        response = api.create_business_line(
            factories.business_line_payload(name="Analyst Line"),
            make_funder_analyst_headers(),
        )

        error = validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403)
        assert error["message"]

    def test_the_same_payload_is_accepted_from_the_director(self, api):
        """Only the role decided the outcome.

        "**Role authorization.** The acting role appears in the endpoint's
        authorized-role list — otherwise `ERR_ROLE_NOT_PERMITTED` (403). Applies
        to every endpoint."

        "| POST | `/business-lines` | Create a candidate business line with its
        viability, training-relevance and mission-alignment scores | ProgramDirector
        |"

        Design: Corner/rbac/funder_analyst_cannot_create_business_line
        """
        payload = factories.business_line_payload(name="Analyst Line")

        validate_error(
            api.create_business_line(payload, make_funder_analyst_headers()),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED,
            403,
        )

        line = validate_success(
            api.create_business_line(payload, make_program_director_headers()), 201
        )
        assert line["name"] == "Analyst Line"


class TestCertificationAndGraduationAreSplit:
    """The two halves of the graduation gate belong to two different roles."""

    def test_a_coach_may_not_graduate_even_an_unknown_participant(self, api):
        """Role authorization outranks existence, so the answer is 403 not 404.

        "**Role authorization.** The acting role appears in the endpoint's
        authorized-role list — otherwise `ERR_ROLE_NOT_PERMITTED` (403). Applies
        to every endpoint."

        "| POST | `/participants/{participantId}/graduate` | Graduate a certified
        participant, subject to segregation of duties | CaseManager |"

        Design: Corner/rbac/job_coach_cannot_graduate_participant
        """
        response = api.graduate_participant(
            UNKNOWN_UUID_1, make_job_coach_headers()
        )

        validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403)

    def test_a_case_manager_may_not_certify_readiness_either(self, api):
        """The mirror half of the split is just as exclusive.

        "**Role authorization.** The acting role appears in the endpoint's
        authorized-role list — otherwise `ERR_ROLE_NOT_PERMITTED` (403). Applies
        to every endpoint."

        "| POST | `/participants/{participantId}/certify-readiness` | Certify that
        graduation criteria are met | JobCoach |"

        Design: Corner/rbac/job_coach_cannot_graduate_participant
        """
        response = api.certify_readiness(
            UNKNOWN_UUID_1, make_case_manager_headers()
        )

        validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403)


class TestSupportActivityDeliveryIsTheCoachsAlone:
    """Planning is shared; the act that moves money is not."""

    def test_a_case_manager_may_not_deliver_a_service(self, api):
        """Delivery is reserved to the coach.

        "**Delivery** is reserved to a `JobCoach`."

        Design: Corner/rbac/case_manager_cannot_deliver_support_activity
        """
        response = api.deliver_support_activity(
            UNKNOWN_UUID_2, make_case_manager_headers()
        )

        validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403)

    def test_a_case_manager_may_not_void_one_either(self, api):
        """Voiding is the director's compensating action.

        "**Voiding** is a `ProgramDirector` action and has two shapes with
        deliberately different consequences."

        Design: Corner/rbac/case_manager_cannot_deliver_support_activity
        """
        response = api.void_support_activity(
            UNKNOWN_UUID_3,
            factories.void_payload(),
            make_case_manager_headers(),
        )

        validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403)


class TestPlanningASupportServiceIsShared:
    """Two roles may plan a service, and planning alone costs nothing."""

    def _one_trainee_and_two_planners(self, api):
        """A coach's coaching session and a case manager's case-management session."""
        program = fixtures.enrolled_participant_program(api)
        participant_id = program["participant"]["id"]
        program["coach_activity"] = validate_success(
            api.create_support_activity(
                factories.support_activity_payload(
                    participant_id,
                    category=SupportCategory.JOB_COACHING,
                    duration_minutes=90,
                    cost_cents=6000,
                ),
                make_job_coach_headers(),
            ),
            201,
        )
        program["case_manager_activity"] = validate_success(
            api.create_support_activity(
                factories.support_activity_payload(
                    participant_id,
                    category=SupportCategory.CASE_MANAGEMENT,
                    duration_minutes=45,
                    cost_cents=3000,
                ),
                make_case_manager_headers(),
            ),
            201,
        )
        return program

    def test_both_planners_land_a_planned_row_with_no_ledger_movement(self, api):
        """A planned service is an intention, not a cost.

        "A planned activity is created in `PLANNED` `status` with
        `delivered_by_user_id`, `delivered_at` and `voided_reason` null, and no ledger
        movement whatsoever — planning something costs nothing."

        Design: Corner/rbac/support_activity_create_shared_by_coach_and_case_manager
        """
        program = self._one_trainee_and_two_planners(api)

        for activity in (program["coach_activity"], program["case_manager_activity"]):
            assert activity["status"] == SupportActivityStatus.PLANNED
            assert activity["delivered_by_user_id"] is None
            assert activity["delivered_at"] is None
            assert activity["voided_reason"] is None

        assert (
            fixtures.cost_entry_count(
                api, {"subsidy_period_id": program["subsidy_period"]["id"]}
            )
            == 0
        )

    def test_the_analyst_reads_both_rows_it_could_not_have_written(self, api):
        """Creation alone never advances graduation readiness.

        "`support_activity_minutes` sums `duration_minutes` over their `DELIVERED`
        support activities."

        "`delivered_coaching_count` counts their `DELIVERED` support activities whose
        `category` is `JOB_COACHING`."

        Design: Corner/rbac/support_activity_create_shared_by_coach_and_case_manager
        """
        program = self._one_trainee_and_two_planners(api)

        _rows, meta = validate_paginated(
            api.list_support_activities(
                make_funder_analyst_headers(),
                {"participant_id": program["participant"]["id"]},
            )
        )
        assert meta["total_count"] == 2

        participant = fixtures.read_participant(api, program["participant"]["id"])
        assert participant["support_activity_minutes"] == 0
        assert participant["delivered_coaching_count"] == 0
        assert participant["status"] == ParticipantStatus.TRANSITIONAL_EMPLOYED
