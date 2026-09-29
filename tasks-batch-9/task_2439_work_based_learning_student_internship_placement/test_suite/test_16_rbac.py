"""Authorisation coverage on the four rungs that sit above resolution and
business rules: an unauthorised role, the two operator-identity separations, and
the ownership check on employer countersignature.
"""

from test_helpers import (
    APPROVER,
    COORDINATOR,
    DRAFTER,
    REVIEWER,
    ApiErrorId,
    api_client,
    close_all_required_cycles,
    complete_placement,
    create_agreement_payload,
    create_placement_payload,
    get_success_data,
    make_employer_supervisor_headers,
    read_agreement,
    read_placement,
    recruit_employer_partner,
    register_reviewed_worksite,
    register_supervisor,
    register_worksite,
    set_clock,
    setup_active_placement,
    setup_partner_worksite_supervisor,
    validate_error,
    validate_success,
)

PINECREST_AUTO_CARE = {
    "legal_name": "Pinecrest Auto Care",
    "naics_code": "811111",
    "industry_sector": "PUBLIC_ADMINISTRATION",
    "workers_comp_policy_no": "WC-10221",
}
QUARRY_BEND_STONEWORKS = {
    "legal_name": "Quarry Bend Stoneworks",
    "naics_code": "327991",
    "industry_sector": "MANUFACTURING",
    "workers_comp_policy_no": "WC-10231",
}
TIDEWATER_PRINT_MEDIA = {
    "legal_name": "Tidewater Print Media",
    "naics_code": "323111",
    "industry_sector": "MANUFACTURING",
    "workers_comp_policy_no": "WC-10241",
}

ULI_STRAND = {
    "full_name": "Uli Strand",
    "birth_date": "2009-01-08",
    "grade_level": 12,
    "gpa": 3.60,
    "attendance_rate": 0.98,
    "student_learner_certificate": True,
}

ONE_CYCLE_PLACEMENT = {
    "pay_classification": "PAID",
    "hourly_wage_cents": 1600,
    "stipend_total_cents": 0,
    "scheduled_weekly_hours": 12.00,
    "start_on": "2026-09-07",
    "end_on": "2026-12-18",
    "credit_target_credits": 0.50,
    "credit_award_mode": "HOURS_BASED",
    "required_evaluation_cycles": 1,
    "transportation_mode": "DISTRICT_BUS",
    "commute_round_trip_miles": 0.00,
}

FABRICATED_STUDENT_ID = "aaaaaaaa-1111-4111-8111-111111111111"
FABRICATED_WORKSITE_ID = "bbbbbbbb-2222-4222-8222-222222222222"
FABRICATED_AGREEMENT_ID = "cccccccc-3333-4333-8333-333333333333"
FABRICATED_SUPERVISOR_ID = "dddddddd-4444-4444-8444-444444444444"


class TestRoleAuthorisationOnPlacementCreation:
    def test_a_safety_reviewer_may_not_create_a_placement_at_all(self):
        """If the headers are well-formed but the named role is not authorised for the
        endpoint being called, the rejection is `ERR_UNAUTHORIZED` (HTTP 403). 2. Acting role
        authorised for the endpoint — `ERR_UNAUTHORIZED` (403).

        Design: Corner/rbac/safety_reviewer_cannot_create_a_placement
        """
        set_clock("2026-09-01T08:00:00Z")

        response = api_client.create_placement(
            create_placement_payload(
                FABRICATED_STUDENT_ID,
                FABRICATED_WORKSITE_ID,
                FABRICATED_AGREEMENT_ID,
                FABRICATED_SUPERVISOR_ID,
                1,
                **ONE_CYCLE_PLACEMENT,
            ),
            REVIEWER,
        )

        validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value)
        assert response.status_code == 403
        assert get_success_data(api_client.list_placements(COORDINATOR)) == []


class TestSelfExecutionOfAnAgreement:
    def test_the_coordinator_who_drafted_the_agreement_cannot_execute_it(self):
        """An agreement may not be executed by the operator who drafted it: if `X-User-ID`
        equals the agreement's `created_by_user_id`, execution is refused with
        `ERR_SELF_EXECUTION_PROHIBITED` (HTTP 403). Both checks compare opaque
        `WblCoordinator` identifiers, so two different coordinators must be involved in each of
        these two chains.

        Design: Corner/rbac/drafter_cannot_execute_the_agreement_they_drafted
        """
        set_clock("2026-09-07T08:00:00Z")
        scenario = setup_partner_worksite_supervisor(
            partner_overrides=PINECREST_AUTO_CARE,
            worksite_overrides={
                "site_name": "Pinecrest Service Bay",
                "address_line": "7 Pinecrest Rd",
                "max_concurrent_students": 2,
            },
            supervisor_overrides={
                "full_name": "Omar Duarte",
                "email": "omar@pinecrest.example",
                "training_completed_on": "2026-07-10",
                "max_student_load": 2,
            },
        )
        agreement = validate_success(
            api_client.create_agreement(
                create_agreement_payload(
                    scenario.partner_id, scenario.worksite_id, scenario.supervisor_id
                ),
                DRAFTER,
            ),
            expected_status=201,
        )
        validate_success(
            api_client.employer_sign_agreement(
                agreement["id"],
                {},
                make_employer_supervisor_headers(scenario.supervisor_id),
            )
        )

        response = api_client.execute_agreement(agreement["id"], {}, DRAFTER)

        validate_error(response, ApiErrorId.ERR_SELF_EXECUTION_PROHIBITED.value)
        assert response.status_code == 403

        stored = read_agreement(agreement["id"])
        assert stored["status"] == "PENDING_DISTRICT"
        assert stored["executed_by_user_id"] is None


class TestOwnershipOfEmployerCountersignature:
    def test_a_supervisor_from_the_sibling_worksite_cannot_countersign(self):
        """Ownership is enforced on exactly four operations, and a mismatch on any of them is
        `ERR_NOT_RESOURCE_OWNER` (HTTP 403): employer countersignature of an agreement
        (`X-User-ID` must equal the agreement's `employer_signer_supervisor_id`), logging a
        timesheet entry (`X-User-ID` must equal the `supervisor_id` of the named placement),
        submitting an evaluation rating (`X-User-ID` must equal the `supervisor_id` of the
        cycle's placement), and submitting a reflection (`X-User-ID` must equal the
        `student_id` of the cycle's placement).

        Design: Corner/rbac/supervisor_from_another_worksite_cannot_countersign_the_agreement
        """
        set_clock("2026-09-07T08:00:00Z")
        partner = recruit_employer_partner(**QUARRY_BEND_STONEWORKS)
        site_a, _review = register_reviewed_worksite(
            partner["id"],
            site_name="Quarry Bend Cut Shop",
            address_line="11 Quarry Bend",
            max_concurrent_students=2,
        )
        supervisor_a = register_supervisor(
            site_a["id"],
            full_name="Rae Lindqvist",
            email="rae@quarrybend.example",
            training_completed_on="2026-07-14",
            max_student_load=2,
        )
        site_b = register_worksite(
            partner["id"],
            site_name="Quarry Bend Polish Room",
            address_line="13 Quarry Bend",
            max_concurrent_students=2,
        )
        supervisor_b = register_supervisor(
            site_b["id"],
            full_name="Sam Okonjo",
            email="sam@quarrybend.example",
            training_completed_on="2026-07-15",
            max_student_load=2,
        )
        agreement = validate_success(
            api_client.create_agreement(
                create_agreement_payload(
                    partner["id"], site_a["id"], supervisor_a["id"]
                ),
                DRAFTER,
            ),
            expected_status=201,
        )

        response = api_client.employer_sign_agreement(
            agreement["id"], {}, make_employer_supervisor_headers(supervisor_b["id"])
        )

        validate_error(response, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)
        assert response.status_code == 403
        assert read_agreement(agreement["id"])["status"] == "PENDING_EMPLOYER"


class TestSegregationBetweenApprovalAndAward:
    def test_the_coordinator_who_approved_the_plan_cannot_award_the_credit(self):
        """Academic credit may not be awarded by the operator who approved the training plan:
        if `X-User-ID` equals the plan's `approved_by_user_id`, the award is refused with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). 4. Credit award is not performed by the plan
        approver — `ERR_SEGREGATION_OF_DUTIES` (403).

        Design: Corner/rbac/plan_approver_cannot_also_award_the_credit
        """
        scenario = setup_active_placement(
            clock="2026-09-07T08:00:00Z",
            course_code="GRA-140",
            credit_hours_target=100.00,
            partner_overrides=TIDEWATER_PRINT_MEDIA,
            worksite_overrides={
                "site_name": "Tidewater Bindery",
                "address_line": "19 Tidewater Rd",
                "max_concurrent_students": 2,
            },
            supervisor_overrides={
                "full_name": "Tao Bergman",
                "email": "tao@tidewater.example",
                "training_completed_on": "2026-07-20",
                "max_student_load": 2,
            },
            student_overrides=ULI_STRAND,
            permit_class="MINOR_16_17",
            placement_overrides=dict(ONE_CYCLE_PLACEMENT),
        )
        set_clock("2026-09-20T08:00:00Z")
        close_all_required_cycles(
            scenario,
            ratings_per_cycle=[
                {
                    "rating_technical": 5,
                    "rating_communication": 4,
                    "rating_reliability": 4,
                    "rating_safety": 4,
                    "rating_initiative": 3,
                }
            ],
        )
        complete_placement(scenario)

        response = api_client.award_placement_credit(
            scenario.placement_id, {}, APPROVER
        )

        validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
        assert response.status_code == 403

        placement = read_placement(scenario.placement_id)
        assert placement["lifecycle_status"] == "COMPLETED"
        assert float(placement["credits_awarded"]) == 0.00
