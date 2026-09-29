"""Role, scope and segregation-of-duties gates of the Nature Center Education API.

Covers the operation/role matrix, the four vantage points on a single booking read,
the school scope boundary, the assigned-educator boundary, and the three
same-actor prohibitions.
"""

import pytest

from test_helpers import (
    CS_ASSESSOR,
    ED,
    NON_EXISTENT_UUID,
    ApiErrorId,
    BOOKING_COORDINATOR_ID,
    CURRICULUM_SPECIALIST_ASSESSOR_ID,
    CURRICULUM_SPECIALIST_ID,
    EDUCATION_DIRECTOR_ID,
    GRANTS_OFFICER_ID,
    STEWARDSHIP_MANAGER_ID,
    assess_training_record_payload,
    create_animal_payload,
    create_booking_payload,
    create_cleared_educator,
    create_educator_payload,
    create_offering_under_review,
    create_onboarding_educator,
    create_program_offering_payload,
    create_scholarship_fund_payload,
    create_school,
    deliver_booking_payload,
    enroll_training,
    find_training_record,
    make_curriculum_specialist_headers,
    make_education_director_headers,
    make_headers,
    make_naturalist_headers,
    make_teacher_contact_headers,
    refresh_booking,
    refresh_offering,
    setup_booking_scenario,
    setup_naturalist_led_booking,
    setup_submitted_evaluation,
    validate_error,
    validate_paginated,
    validate_success,
)

# --- The operations each role is not authorised for ---------------------------------


def _attempt_create_booking(api, scenario, headers):
    return api.create_booking(
        create_booking_payload(
            scenario["school"]["id"],
            scenario["offering"]["id"],
            start_utc="2026-09-30T14:00:00Z",
            end_utc="2026-09-30T16:00:00Z",
        ),
        headers,
    )


def _attempt_create_program_offering(api, scenario, headers):
    return api.create_program_offering(
        create_program_offering_payload(title="Unauthorised Offering"), headers
    )


def _attempt_create_scholarship_fund(api, scenario, headers):
    return api.create_scholarship_fund(create_scholarship_fund_payload(), headers)


def _attempt_create_animal(api, scenario, headers):
    return api.create_animal(create_animal_payload(NON_EXISTENT_UUID), headers)


def _attempt_confirm_booking(api, scenario, headers):
    return api.confirm_booking(scenario["booking"]["id"], headers)


def _attempt_create_educator(api, scenario, headers):
    return api.create_educator(create_educator_payload(full_name="Unauthorised Hire"), headers)


def _fixed_actor(user_id):
    return lambda scenario: user_id


def _school_actor(scenario):
    return scenario["school"]["id"]


def _educator_actor(scenario):
    return scenario["educator"]["id"]


ROLE_MISMATCH_CASES = [
    ("CurriculumSpecialist", _fixed_actor(CURRICULUM_SPECIALIST_ID), _attempt_create_booking),
    ("BookingCoordinator", _fixed_actor(BOOKING_COORDINATOR_ID), _attempt_create_program_offering),
    ("StewardshipManager", _fixed_actor(STEWARDSHIP_MANAGER_ID), _attempt_create_scholarship_fund),
    ("GrantsOfficer", _fixed_actor(GRANTS_OFFICER_ID), _attempt_create_animal),
    ("Naturalist", _educator_actor, _attempt_confirm_booking),
    ("TeacherContact", _school_actor, _attempt_create_educator),
]

ROLE_MISMATCH_IDS = [
    "curriculum_specialist_cannot_open_a_booking",
    "booking_coordinator_cannot_author_an_offering",
    "stewardship_manager_cannot_open_a_fund",
    "grants_officer_cannot_register_an_animal",
    "naturalist_cannot_confirm_a_booking",
    "teacher_contact_cannot_register_an_educator",
]


class TestRoleMatrix:
    @pytest.mark.parametrize(
        ("role", "actor", "attempt"), ROLE_MISMATCH_CASES, ids=ROLE_MISMATCH_IDS
    )
    def test_a_role_outside_the_authorised_set_is_refused(self, api, role, actor, attempt):
        """PRD §2.1: "If the role is recognised but is not among the roles authorised for the target operation, the request is rejected with `ERR_ROLE_NOT_PERMITTED`."

        Design: Corner/rbac/each_role_is_confined_to_the_operations_its_own_duties_need
        """
        scenario = setup_booking_scenario(assign_educator=False)
        headers = make_headers(role, actor(scenario))

        validate_error(
            attempt(api, scenario, headers), ApiErrorId.ERR_ROLE_NOT_PERMITTED.value
        )

    @pytest.mark.parametrize(
        ("role", "actor", "attempt"), ROLE_MISMATCH_CASES, ids=ROLE_MISMATCH_IDS
    )
    def test_a_refused_role_leaves_the_booking_where_it_was(
        self, api, role, actor, attempt
    ):
        """PRD §2.9: "The acting role is authorised for the target operation — otherwise `ERR_ROLE_NOT_PERMITTED` (403). Applies to every endpoint."

        Design: Corner/rbac/each_role_is_confined_to_the_operations_its_own_duties_need
        """
        scenario = setup_booking_scenario(assign_educator=False)
        headers = make_headers(role, actor(scenario))

        validate_error(
            attempt(api, scenario, headers), ApiErrorId.ERR_ROLE_NOT_PERMITTED.value
        )

        assert refresh_booking(scenario["booking"]["id"])["delivery_status"] == "REQUESTED"


class TestFourVantagePointsOnOneBooking:
    @pytest.mark.parametrize(
        ("role", "user_id"),
        [
            ("BookingCoordinator", BOOKING_COORDINATOR_ID),
            ("EducationDirector", EDUCATION_DIRECTOR_ID),
        ],
        ids=["booking_coordinator", "education_director"],
    )
    def test_an_authorised_operator_role_reads_the_booking(self, api, role, user_id):
        """PRD §2.1: "If the role is recognised but is not among the roles authorised for the target operation, the request is rejected with `ERR_ROLE_NOT_PERMITTED`."

        Design: Corner/rbac/four_roles_share_the_booking_read_each_from_its_own_vantage_point
        """
        scenario = setup_naturalist_led_booking()

        booking = validate_success(
            api.get_booking(scenario["booking"]["id"], make_headers(role, user_id))
        )

        assert booking["id"] == scenario["booking"]["id"]
        assert booking["delivery_status"] == "CONFIRMED"

    def test_the_owning_teacher_reads_their_own_school_s_booking(self, api):
        """PRD §2.1: "A teacher may act only on bookings whose `school_id` equals `X-User-ID`, and only on aid applications and evaluation reports whose booking belongs to that school."

        Design: Corner/rbac/four_roles_share_the_booking_read_each_from_its_own_vantage_point
        """
        scenario = setup_naturalist_led_booking()
        school_id = scenario["school"]["id"]

        booking = validate_success(
            api.get_booking(
                scenario["booking"]["id"], make_teacher_contact_headers(school_id)
            )
        )

        assert booking["id"] == scenario["booking"]["id"]
        assert booking["school_id"] == school_id

    def test_the_assigned_naturalist_reads_the_booking_they_lead(self, api):
        """PRD §2.1: "Concretely, a `Naturalist` may act on a booking only when that booking's `lead_educator_id` equals `X-User-ID`, and may read an educator record only when the educator `id` in the path equals `X-User-ID`."

        Design: Corner/rbac/four_roles_share_the_booking_read_each_from_its_own_vantage_point
        """
        scenario = setup_naturalist_led_booking()
        educator_id = scenario["educator"]["id"]

        booking = validate_success(
            api.get_booking(scenario["booking"]["id"], scenario["naturalist_headers"])
        )

        assert booking["id"] == scenario["booking"]["id"]
        assert booking["lead_educator_id"] == educator_id


class TestSchoolScopeBoundary:
    def test_a_foreign_school_s_teacher_cannot_read_the_booking(self, api):
        """PRD §2.9: "A `TeacherContact` is acting inside their own school's scope — otherwise `ERR_SCHOOL_SCOPE_VIOLATION` (403)."

        Design: Corner/rbac/a_teacher_contact_cannot_reach_another_school_s_booking
        """
        scenario = setup_booking_scenario(assign_educator=False)
        other_school = create_school(
            name="Harborview Middle", district_code="LEA-31", title_i_pct=0.55
        )

        validate_error(
            api.get_booking(
                scenario["booking"]["id"],
                make_teacher_contact_headers(other_school["id"]),
            ),
            ApiErrorId.ERR_SCHOOL_SCOPE_VIOLATION.value,
        )

    def test_a_foreign_school_s_teacher_cannot_cancel_the_booking(self, api):
        """PRD §2.9: "A `TeacherContact` is acting inside their own school's scope — otherwise `ERR_SCHOOL_SCOPE_VIOLATION` (403)."

        Design: Corner/rbac/a_teacher_contact_cannot_reach_another_school_s_booking
        """
        scenario = setup_booking_scenario(assign_educator=False)
        other_school = create_school(
            name="Harborview Middle", district_code="LEA-31", title_i_pct=0.55
        )

        validate_error(
            api.cancel_booking(
                scenario["booking"]["id"],
                {"reason": "Not our trip"},
                make_teacher_contact_headers(other_school["id"]),
            ),
            ApiErrorId.ERR_SCHOOL_SCOPE_VIOLATION.value,
        )

        assert refresh_booking(scenario["booking"]["id"])["delivery_status"] == "REQUESTED"

    def test_the_owning_school_s_teacher_reads_the_booking(self, api):
        """PRD §2.1: "A teacher may act only on bookings whose `school_id` equals `X-User-ID`, and only on aid applications and evaluation reports whose booking belongs to that school."

        Design: Corner/rbac/a_teacher_contact_cannot_reach_another_school_s_booking
        """
        scenario = setup_booking_scenario(assign_educator=False)
        create_school(name="Harborview Middle", district_code="LEA-31", title_i_pct=0.55)

        booking = validate_success(
            api.get_booking(
                scenario["booking"]["id"],
                make_teacher_contact_headers(scenario["school"]["id"]),
            )
        )

        assert booking["id"] == scenario["booking"]["id"]

    def test_the_owning_school_s_teacher_cancels_the_requested_booking(self, api):
        """PRD §3.7: "From `REQUESTED`, cancellation sets `delivery_status` to `CANCELLED` with `resource_release_reason` of `CANCELLED_BY_SCHOOL` — or `SCHOOL_SUSPENSION` when the cancellation was driven by the suspension cascade rather than by a request — and then revokes money: every aid application of this booking whose status is `APPROVED` or `PARTIALLY_APPROVED` transitions to `REVOKED`, the fund's `committed_cents` and `available_cents` are recomputed, and the booking's `aid_amount_cents` and `net_due_cents` fall to 0."

        Design: Corner/rbac/a_teacher_contact_cannot_reach_another_school_s_booking
        """
        scenario = setup_booking_scenario(assign_educator=False)
        create_school(name="Harborview Middle", district_code="LEA-31", title_i_pct=0.55)

        cancelled = validate_success(
            api.cancel_booking(
                scenario["booking"]["id"],
                {"reason": "Buses unavailable"},
                make_teacher_contact_headers(scenario["school"]["id"]),
            )
        )

        assert cancelled["delivery_status"] == "CANCELLED"
        assert cancelled["resource_release_reason"] == "CANCELLED_BY_SCHOOL"


class TestAssignedEducatorBoundary:
    def test_an_unassigned_naturalist_cannot_record_the_delivery(self, api):
        """PRD §2.9: "A `Naturalist` is acting on their own assignment — otherwise `ERR_NOT_ASSIGNED_EDUCATOR` (403)."

        Design: Corner/rbac/a_naturalist_cannot_deliver_a_booking_another_educator_leads
        """
        scenario = setup_naturalist_led_booking()
        bystander = create_cleared_educator(full_name="Kim Fen")

        validate_error(
            api.deliver_booking(
                scenario["booking"]["id"],
                deliver_booking_payload(actual_student_count=30, actual_chaperone_count=3),
                make_naturalist_headers(bystander["educator"]["id"]),
            ),
            ApiErrorId.ERR_NOT_ASSIGNED_EDUCATOR.value,
        )

    def test_a_refused_delivery_leaves_the_booking_confirmed(self, api):
        """PRD §2.9: "A `Naturalist` is acting on their own assignment — otherwise `ERR_NOT_ASSIGNED_EDUCATOR` (403)."

        Design: Corner/rbac/a_naturalist_cannot_deliver_a_booking_another_educator_leads
        """
        scenario = setup_naturalist_led_booking()
        bystander = create_cleared_educator(full_name="Kim Fen")

        validate_error(
            api.deliver_booking(
                scenario["booking"]["id"],
                deliver_booking_payload(actual_student_count=30, actual_chaperone_count=3),
                make_naturalist_headers(bystander["educator"]["id"]),
            ),
            ApiErrorId.ERR_NOT_ASSIGNED_EDUCATOR.value,
        )

        still_open = refresh_booking(scenario["booking"]["id"])
        assert still_open["delivery_status"] == "CONFIRMED"
        assert still_open["lead_educator_id"] == scenario["educator"]["id"]

    def test_the_assigned_naturalist_records_the_delivery_and_the_final_fee(self, api):
        """PRD §3.7: "Both branches then compute `final_gross_fee_cents` through the final variant of the fee assessment, recompute `net_due_cents` from it, advance `funding_status` to `INVOICED`, transition every aid application of this booking whose status is `APPROVED` or `PARTIALLY_APPROVED` to `DISBURSED`, and recompute the school's `outstanding_balance_cents`."

        Design: Corner/rbac/a_naturalist_cannot_deliver_a_booking_another_educator_leads
        """
        scenario = setup_naturalist_led_booking()
        create_cleared_educator(full_name="Kim Fen")

        delivered = validate_success(
            api.deliver_booking(
                scenario["booking"]["id"],
                deliver_booking_payload(actual_student_count=30, actual_chaperone_count=3),
                scenario["naturalist_headers"],
            )
        )

        assert delivered["delivery_status"] == "DELIVERED"
        assert delivered["final_gross_fee_cents"] == 33300
        assert delivered["lead_educator_id"] == scenario["educator"]["id"]


class TestSameActorProhibitions:
    def test_a_catalog_review_by_the_authoring_actor_is_refused(self, api):
        """PRD §2.9: "On a catalog review decision, `X-User-ID` differs from the offering's `authored_by_user_id` — otherwise `ERR_SOD_REVIEW_SAME_ACTOR` (403)."

        Design: Corner/rbac/catalog_review_and_training_assessment_refuse_the_actor_who_authored_the_work
        """
        bundle = create_offering_under_review()
        offering = bundle["offering"]
        assert offering["authored_by_user_id"] == CURRICULUM_SPECIALIST_ID

        validate_error(
            api.review_program_offering(
                offering["id"],
                {"decision": "PUBLISH"},
                make_education_director_headers(CURRICULUM_SPECIALIST_ID),
            ),
            ApiErrorId.ERR_SOD_REVIEW_SAME_ACTOR.value,
        )

        assert refresh_offering(offering["id"])["status"] == "UNDER_REVIEW"

    def test_a_catalog_review_by_a_different_actor_publishes_the_offering(self, api):
        """PRD §3.1: "On success the offering moves `UNDER_REVIEW → PUBLISHED`, `published_at` is stamped with the logical clock, and `reviewed_by_user_id` records the deciding `X-User-ID`."

        Design: Corner/rbac/catalog_review_and_training_assessment_refuse_the_actor_who_authored_the_work
        """
        bundle = create_offering_under_review()

        reviewed = validate_success(
            api.review_program_offering(
                bundle["offering"]["id"], {"decision": "PUBLISH"}, ED
            )
        )

        assert reviewed["status"] == "PUBLISHED"
        assert reviewed["reviewed_by_user_id"] == EDUCATION_DIRECTOR_ID
        assert reviewed["authored_by_user_id"] == CURRICULUM_SPECIALIST_ID

    def test_a_training_assessment_by_the_enrolling_actor_is_refused(self, api):
        """PRD §2.9: "On a training assessment, `X-User-ID` differs from the training record's `enrolled_by_user_id` — otherwise `ERR_SOD_ASSESS_SAME_ACTOR` (403)."

        Design: Corner/rbac/catalog_review_and_training_assessment_refuse_the_actor_who_authored_the_work
        """
        educator = create_onboarding_educator()
        record = enroll_training(educator["id"], track="CURRICULUM", grade_band="G3_5")
        assert record["enrolled_by_user_id"] == CURRICULUM_SPECIALIST_ID

        validate_error(
            api.assess_training_record(
                record["id"],
                assess_training_record_payload(outcome="PASS", score=91),
                make_curriculum_specialist_headers(CURRICULUM_SPECIALIST_ID),
            ),
            ApiErrorId.ERR_SOD_ASSESS_SAME_ACTOR.value,
        )

        assert find_training_record(educator["id"], record["id"])["status"] == "ENROLLED"

    def test_a_training_assessment_by_a_different_specialist_records_the_pass(self, api):
        """PRD §3.3: "Both outcomes increment `attempt_count` by 1 and stamp `assessed_by_user_id` with the deciding `X-User-ID`."

        Design: Corner/rbac/catalog_review_and_training_assessment_refuse_the_actor_who_authored_the_work
        """
        educator = create_onboarding_educator()
        record = enroll_training(educator["id"], track="CURRICULUM", grade_band="G3_5")

        assessed = validate_success(
            api.assess_training_record(
                record["id"],
                assess_training_record_payload(outcome="PASS", score=91),
                CS_ASSESSOR,
            )
        )

        assert assessed["status"] == "ASSESSED_PASS"
        assert assessed["assessed_by_user_id"] == CURRICULUM_SPECIALIST_ASSESSOR_ID
        assert assessed["enrolled_by_user_id"] == CURRICULUM_SPECIALIST_ID


class TestEvaluationAcceptanceBarredToItsSubmitter:
    def test_submission_stamps_the_submitting_teacher_and_computes_the_index(self, api):
        """PRD §3.9: "Submission advances `DRAFT → SUBMITTED` and requires the parent booking's `delivery_status` to be `DELIVERED`; it stamps `submitted_by_user_id` from `X-User-ID` and computes `learning_gain_index`."

        Design: Corner/rbac/evaluation_acceptance_is_barred_to_the_teacher_who_submitted_it
        """
        scenario = setup_submitted_evaluation(
            actual_student_count=30,
            actual_chaperone_count=3,
            report_overrides={
                "teacher_score_standards_alignment": 5,
                "teacher_score_logistics": 4,
                "teacher_score_engagement": 4,
                "student_pre_score_avg": 8,
                "student_post_score_avg": 15,
            },
        )
        report = scenario["evaluation_report"]

        assert report["status"] == "SUBMITTED"
        assert report["submitted_by_user_id"] == scenario["school"]["id"]
        assert report["learning_gain_index"] == pytest.approx(0.64, abs=0.01)

    def test_acceptance_carrying_the_submitter_s_actor_id_is_refused(self, api):
        """PRD §2.9: "On an evaluation review decision, `X-User-ID` differs from the report's `submitted_by_user_id` — otherwise `ERR_SOD_EVALUATION_SAME_ACTOR` (403)."

        Design: Corner/rbac/evaluation_acceptance_is_barred_to_the_teacher_who_submitted_it
        """
        scenario = setup_submitted_evaluation(
            actual_student_count=30,
            actual_chaperone_count=3,
            report_overrides={
                "teacher_score_standards_alignment": 5,
                "teacher_score_logistics": 4,
                "teacher_score_engagement": 4,
                "student_pre_score_avg": 8,
                "student_post_score_avg": 15,
            },
        )
        school_id = scenario["school"]["id"]

        validate_error(
            api.review_evaluation_report(
                scenario["evaluation_report"]["id"],
                {"decision": "ACCEPT"},
                make_education_director_headers(school_id),
            ),
            ApiErrorId.ERR_SOD_EVALUATION_SAME_ACTOR.value,
        )

        rows, meta = validate_paginated(
            api.list_evaluation_reports(
                scenario["booking"]["id"], ED, {"status": "SUBMITTED"}
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == scenario["evaluation_report"]["id"]

    def test_acceptance_by_the_education_director_accepts_the_report(self, api):
        """PRD §3.9: "`ACCEPT` moves `SUBMITTED → ACCEPTED`, requires an accepting `X-User-ID` different from `submitted_by_user_id` per §2.11, and is terminal; only an `ACCEPTED` report becomes eligible for the funder outcome rollup."

        Design: Corner/rbac/evaluation_acceptance_is_barred_to_the_teacher_who_submitted_it
        """
        scenario = setup_submitted_evaluation(
            actual_student_count=30,
            actual_chaperone_count=3,
            report_overrides={
                "teacher_score_standards_alignment": 5,
                "teacher_score_logistics": 4,
                "teacher_score_engagement": 4,
                "student_pre_score_avg": 8,
                "student_post_score_avg": 15,
            },
        )

        accepted = validate_success(
            api.review_evaluation_report(
                scenario["evaluation_report"]["id"], {"decision": "ACCEPT"}, ED
            )
        )

        assert accepted["status"] == "ACCEPTED"
        assert accepted["reviewed_by_user_id"] == EDUCATION_DIRECTOR_ID
        assert accepted["submitted_by_user_id"] == scenario["school"]["id"]
