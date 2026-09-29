"""Optimistic-concurrency coverage on the two expected-version fields: a second
safety review filed against a version the decision already moved, a replacement
training plan built on a pre-approval placement version, and a placement created
against a worksite version the safety decision has since advanced.
"""

from test_helpers import (
    COORDINATOR,
    DRAFTER,
    REVIEWER,
    ApiErrorId,
    api_client,
    create_agreement_payload,
    create_placement_payload,
    create_safety_review_payload,
    create_training_plan_payload,
    decide_safety_review,
    enrol_student,
    file_safety_review,
    get_success_data,
    read_placement,
    read_plan,
    read_worksite,
    recruit_employer_partner,
    register_worksite,
    set_clock,
    setup_partner_worksite_supervisor,
    setup_proposed_placement,
    draft_plan_with_objectives,
    submit_and_approve_plan,
    validate_error,
)

VESPER_GLASSWORKS = {
    "legal_name": "Vesper Glassworks",
    "naics_code": "327215",
    "industry_sector": "MANUFACTURING",
    "workers_comp_policy_no": "WC-10251",
}
WINDROW_FARM_SUPPLY = {
    "legal_name": "Windrow Farm Supply",
    "naics_code": "424910",
    "industry_sector": "HOSPITALITY",
    "workers_comp_policy_no": "WC-10261",
}
BRAMBLETON_GARDEN_CENTRE = {
    "legal_name": "Brambleton Garden Centre",
    "naics_code": "444230",
    "industry_sector": "HOSPITALITY",
    "workers_comp_policy_no": "WC-10281",
}

ZEKE_ALVARADO = {
    "full_name": "Zeke Alvarado",
    "birth_date": "2009-06-06",
    "grade_level": 11,
    "gpa": 3.20,
    "attendance_rate": 0.94,
    "student_learner_certificate": True,
}
DARA_OKORO = {
    "full_name": "Dara Okoro",
    "birth_date": "2009-10-10",
    "grade_level": 11,
    "gpa": 3.10,
    "attendance_rate": 0.93,
    "student_learner_certificate": True,
}

SHORT_PLACEMENT = {
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


class TestSecondSafetyReviewOnAStaleWorksiteVersion:
    def test_filing_again_on_the_pre_decision_version_is_refused(self):
        """9. `expected_worksite_version` matches the worksite's `version` —
        `ERR_STALE_WORKSITE_VERSION` (412). The worksite's `safety_status` becomes `APPROVED`,
        its `safety_review_expires_on` copies the review's `expires_on`, its
        `corrective_actions_due_on` is set to null, and its `version` increases by 1.

        Design: Corner/cross-cutting complexity layers/stale_worksite_version_on_a_second_safety_review_returns_412
        """
        set_clock("2026-09-07T08:00:00Z")
        partner = recruit_employer_partner(**VESPER_GLASSWORKS)
        worksite = register_worksite(
            partner["id"],
            site_name="Vesper Kiln Room",
            address_line="23 Vesper St",
            hazard_class="LIMITED_HAZARD",
            has_power_machinery=True,
            max_concurrent_students=1,
        )
        stale_version = worksite["version"]
        first_review = file_safety_review(worksite["id"], stale_version)
        decide_safety_review(first_review["id"], "APPROVED")
        decided_worksite = read_worksite(worksite["id"])
        assert decided_worksite["version"] > stale_version

        response = api_client.create_safety_review(
            create_safety_review_payload(worksite["id"], stale_version), REVIEWER
        )

        validate_error(response, ApiErrorId.ERR_STALE_WORKSITE_VERSION.value)
        assert response.status_code == 412

        reviews = get_success_data(
            api_client.list_worksite_safety_reviews(worksite["id"], REVIEWER)
        )
        assert len(reviews) == 1
        assert reviews[0]["id"] == first_review["id"]
        assert reviews[0]["status"] == "APPROVED"

        after = read_worksite(worksite["id"])
        assert after["safety_status"] == "APPROVED"
        assert after["version"] == decided_worksite["version"]


class TestReplacementPlanOnAStalePlacementVersion:
    def test_drafting_a_second_plan_on_the_pre_approval_version_is_refused(self):
        """Creating a training plan requires `expected_placement_version` as a mandatory body
        field carrying the client's last observed `version` of the target `Placement`; a
        mismatch with the placement's current `version` is rejected with
        `ERR_STALE_PLACEMENT_VERSION` (HTTP 412). A new plan supersedes any existing plan on
        the placement, and the plan being superseded may already have been approved — advancing
        both of the placement's state dimensions — after the client's read.

        Design: Corner/cross-cutting complexity layers/stale_placement_version_on_a_replacement_training_plan_returns_412
        """
        scenario = setup_proposed_placement(
            clock="2026-09-07T08:00:00Z",
            partner_overrides=WINDROW_FARM_SUPPLY,
            worksite_overrides={
                "site_name": "Windrow Feed Store",
                "address_line": "26 Windrow Rd",
                "max_concurrent_students": 2,
            },
            supervisor_overrides={
                "full_name": "Yara Nowak",
                "email": "yara@windrow.example",
                "training_completed_on": "2026-07-24",
                "max_student_load": 2,
            },
            student_overrides=ZEKE_ALVARADO,
            permit_class="MINOR_16_17",
            placement_overrides=dict(SHORT_PLACEMENT),
        )
        stale_version = scenario.placement["version"]
        draft_plan_with_objectives(
            scenario, course_code="AGR-160", credit_hours_target=60.00
        )
        submit_and_approve_plan(scenario)
        approved_placement = read_placement(scenario.placement_id)
        assert approved_placement["version"] > stale_version

        response = api_client.create_training_plan(
            create_training_plan_payload(
                scenario.placement_id,
                stale_version,
                course_code="AGR-161",
                credit_hours_target=70.00,
            ),
            COORDINATOR,
        )

        validate_error(response, ApiErrorId.ERR_STALE_PLACEMENT_VERSION.value)
        assert response.status_code == 412

        assert read_plan(scenario.plan_id)["status"] == "APPROVED"
        placement = read_placement(scenario.placement_id)
        assert placement["lifecycle_status"] == "ACTIVE"
        assert placement["compliance_status"] == "CLEARED"
        assert placement["version"] == approved_placement["version"]
        assert (
            len(
                get_success_data(
                    api_client.list_placement_training_plans(
                        scenario.placement_id, COORDINATOR
                    )
                )
            )
            == 1
        )


class TestPlacementCreationOnAStaleWorksiteVersion:
    def test_the_stale_version_is_reported_ahead_of_the_agreement_and_permit_rules(self):
        """Creating a placement requires `expected_worksite_version` as a mandatory,
        non-optional body field carrying the client's last observed `version` of the target
        `Worksite`. If it does not equal the worksite's current `version`, the request is
        rejected with `ERR_STALE_WORKSITE_VERSION` (HTTP 412). The stale view is the whole
        point: a safety decision, an incident cascade or another placement creation may have
        changed the worksite's `safety_status` or `slots_committed` since the read, so the
        capacity and safety facts the request was built on no longer hold.

        Design: Corner/cross-cutting complexity layers/placement_create_against_a_stale_worksite_version_returns_412
        """
        set_clock("2026-09-07T08:00:00Z")
        scenario = setup_partner_worksite_supervisor(
            partner_overrides=BRAMBLETON_GARDEN_CENTRE,
            worksite_overrides={
                "site_name": "Brambleton Nursery Yard",
                "address_line": "40 Brambleton Rd",
                "max_concurrent_students": 2,
            },
            supervisor_overrides={
                "full_name": "Cy Ferraro",
                "email": "cy@brambleton.example",
                "training_completed_on": "2026-07-28",
                "max_student_load": 2,
            },
        )
        agreement = get_success_data(
            api_client.create_agreement(
                create_agreement_payload(
                    scenario.partner_id, scenario.worksite_id, scenario.supervisor_id
                ),
                DRAFTER,
            )
        )
        student = enrol_student(**DARA_OKORO)
        cleared_worksite = read_worksite(scenario.worksite_id)
        stale_version = 1
        assert cleared_worksite["version"] > stale_version

        response = api_client.create_placement(
            create_placement_payload(
                student["id"],
                scenario.worksite_id,
                agreement["id"],
                scenario.supervisor_id,
                stale_version,
                **SHORT_PLACEMENT,
            ),
            COORDINATOR,
        )

        validate_error(response, ApiErrorId.ERR_STALE_WORKSITE_VERSION.value)
        assert response.status_code == 412

        after = read_worksite(scenario.worksite_id)
        assert after["version"] == cleared_worksite["version"]
        assert after["slots_committed"] == 0
        assert get_success_data(api_client.list_placements(COORDINATOR)) == []
