"""Entity-shape coverage: the initial figures a freshly created row carries, the
pagination envelope of a collection read, the not-found and malformed-body
rejections, the optional field that falls back to its declared default, and the
one entity in the model that has no version at all.
"""

from test_helpers import (
    COORDINATOR,
    ApiErrorId,
    api_client,
    create_employer_partner_payload,
    create_learning_objective_payload,
    create_placement_payload,
    create_worksite_payload,
    draft_plan_with_objectives,
    enrol_student_with_issued_permit,
    get_success_data,
    is_valid_uuid,
    list_objectives,
    read_plan,
    read_worksite,
    set_clock,
    setup_agreement_ready,
    setup_proposed_placement,
    validate_error,
    validate_paginated,
    validate_success,
)

VANTAGE = {
    "legal_name": "Vantage Hospitality Group",
    "naics_code": "721110",
    "industry_sector": "HOSPITALITY",
    "workers_comp_policy_no": "WC-10001",
}
ANCHOR_FOODS = {
    "legal_name": "Anchor Foods",
    "naics_code": "722511",
    "industry_sector": "HOSPITALITY",
    "workers_comp_policy_no": "WC-10011",
}
BASALT_ENGINEERING = {
    "legal_name": "Basalt Engineering",
    "naics_code": "541330",
    "industry_sector": "MANUFACTURING",
    "workers_comp_policy_no": "WC-10012",
}
CORDIAL_CARE = {
    "legal_name": "Cordial Care Clinic",
    "naics_code": "621111",
    "industry_sector": "HEALTHCARE",
    "workers_comp_policy_no": "WC-10013",
}
DUNMORE_FREIGHT = {
    "legal_name": "Dunmore Freight",
    "naics_code": "488510",
    "industry_sector": "PUBLIC_ADMINISTRATION",
    "workers_comp_policy_no": "WC-10021",
}
EVERLINE_FABRICATION = {
    "legal_name": "Everline Fabrication",
    "naics_code": "332323",
    "industry_sector": "MANUFACTURING",
    "workers_comp_policy_no": "WC-10031",
}
GLADSTONE_HARDWARE = {
    "legal_name": "Gladstone Hardware",
    "naics_code": "444140",
    "industry_sector": "HOSPITALITY",
    "workers_comp_policy_no": "WC-10051",
}
IRONWOOD_CABINETRY = {
    "legal_name": "Ironwood Cabinetry",
    "naics_code": "337110",
    "industry_sector": "MANUFACTURING",
    "workers_comp_policy_no": "WC-10061",
}

HANA_ILVES = {
    "full_name": "Hana Ilves",
    "birth_date": "2009-04-27",
    "grade_level": 11,
    "gpa": 3.10,
    "attendance_rate": 0.95,
    "student_learner_certificate": True,
}
MILO_BERGSTROM = {
    "full_name": "Milo Bergstrom",
    "birth_date": "2009-05-30",
    "grade_level": 12,
    "gpa": 3.20,
    "attendance_rate": 0.94,
    "student_learner_certificate": True,
}

UNKNOWN_WORKSITE_ID = "11111111-2222-4333-8444-555555555555"
UNKNOWN_STUDENT_ID = "99999999-8888-4777-8666-555555555555"

ONE_CYCLE_PLACEMENT = {
    "pay_classification": "PAID",
    "hourly_wage_cents": 1500,
    "stipend_total_cents": 0,
    "scheduled_weekly_hours": 12.00,
    "start_on": "2026-09-07",
    "end_on": "2026-12-18",
    "credit_target_credits": 0.50,
    "credit_award_mode": "HOURS_BASED",
    "required_evaluation_cycles": 1,
    "transportation_mode": "PUBLIC_TRANSIT",
    "commute_round_trip_miles": 0.00,
}


class TestEmployerPartnerInitialFigures:
    def test_a_newly_recruited_partner_starts_at_a_perfect_score_and_prospect(self):
        """A newly recruited partner is initialised with `safety_score` of 100 and `posture`
        of `PROSPECT`, and with all four of its derived ledgers at zero —
        `substantiated_minor_count`, `substantiated_moderate_count`,
        `substantiated_critical_count` and `wage_liability_cents`. Most resources also carry
        `updated_at`, refreshed on every mutation using the same format, and `version`, an
        integer that starts at 1 on creation and increases by exactly 1 on every mutation of
        that row — including mutations that arrive as a side effect of an operation aimed at a
        different resource.

        Design: Corner/entities/employer_partner_create_initialises_safety_score_and_prospect_posture
        """
        set_clock("2026-09-01T08:00:00Z")

        partner = validate_success(
            api_client.create_employer_partner(
                create_employer_partner_payload(**VANTAGE), COORDINATOR
            ),
            expected_status=201,
        )

        assert partner["legal_name"] == "Vantage Hospitality Group"
        assert partner["safety_score"] == 100
        assert partner["posture"] == "PROSPECT"
        assert partner["substantiated_minor_count"] == 0
        assert partner["substantiated_moderate_count"] == 0
        assert partner["substantiated_critical_count"] == 0
        assert partner["wage_liability_cents"] == 0
        assert partner["version"] == 1
        assert is_valid_uuid(partner["id"])


class TestEmployerPartnerListPagination:
    def test_a_two_row_page_of_three_partners_reports_the_full_count_and_more(self):
        """All four pagination fields — `limit`, `offset`, `total_count` and `has_more` — are
        reported in the `meta` block of a list response, where `total_count` is the number of
        rows matching the filters before pagination is applied and `has_more` indicates
        whether rows remain beyond the returned page.

        Design: Corner/entities/employer_partners_list_reports_total_count_and_has_more
        """
        set_clock("2026-09-01T08:00:00Z")
        for overrides in (ANCHOR_FOODS, BASALT_ENGINEERING, CORDIAL_CARE):
            validate_success(
                api_client.create_employer_partner(
                    create_employer_partner_payload(**overrides), COORDINATOR
                ),
                expected_status=201,
            )

        rows, meta = validate_paginated(
            api_client.list_employer_partners(COORDINATOR, {"limit": 2, "offset": 0})
        )

        assert len(rows) == 2
        assert meta["total_count"] == 3
        assert meta["has_more"] is True
        assert meta["limit"] == 2
        assert meta["offset"] == 0


class TestUnknownIdentifiers:
    def test_reading_a_worksite_that_does_not_exist_reports_the_worksite_code(self):
        """Each resource type has its own not-found code: `ERR_EMPLOYER_NOT_FOUND`,
        `ERR_WORKSITE_NOT_FOUND`, `ERR_REVIEW_NOT_FOUND`, `ERR_SUPERVISOR_NOT_FOUND`,
        `ERR_AGREEMENT_NOT_FOUND`, `ERR_STUDENT_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`,
        `ERR_PLACEMENT_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_ENTRY_NOT_FOUND`,
        `ERR_CYCLE_NOT_FOUND`, `ERR_INCIDENT_NOT_FOUND` and `ERR_OUTCOME_NOT_FOUND`, each
        HTTP 404.

        Design: Corner/entities/worksite_get_with_unknown_id_returns_worksite_not_found
        """
        set_clock("2026-09-01T08:00:00Z")

        response = api_client.get_worksite(UNKNOWN_WORKSITE_ID, COORDINATOR)

        validate_error(response, ApiErrorId.ERR_WORKSITE_NOT_FOUND.value)
        assert response.status_code == 404

    def test_requesting_a_permit_for_an_unknown_student_resolves_the_body_reference(self):
        """7. Body-supplied foreign keys resolve, in declaration order — the matching
        not-found code (404). Body-level foreign-key resolution applies to worksite
        registration, safety-review filing, supervisor registration, agreement drafting,
        work-permit requesting, placement creation, training-plan drafting,
        learning-objective creation, timesheet logging, incident reporting and outcome
        recording.

        Design: Corner/entities/work_permit_create_with_unknown_student_returns_student_not_found
        """
        set_clock("2026-09-01T08:00:00Z")

        response = api_client.create_work_permit(
            {
                "student_id": UNKNOWN_STUDENT_ID,
                "permit_class": "MINOR_16_17",
                "hazardous_endorsement": False,
            },
            COORDINATOR,
        )

        validate_error(response, ApiErrorId.ERR_STUDENT_NOT_FOUND.value)
        assert response.status_code == 404


class TestMalformedWorksiteRegistration:
    def test_omitting_the_declared_capacity_is_a_malformed_body(self):
        """Capacity is declared as `max_concurrent_students`, at least 1, and is interpreted
        as an aggregate ceiling over any overlapping date range rather than a headcount at an
        instant. 8. Request body shape is valid — `ERR_INVALID_REQUEST` (400).

        Design: Corner/entities/worksite_create_missing_required_max_concurrent_students_rejected
        """
        set_clock("2026-09-01T08:00:00Z")
        partner = validate_success(
            api_client.create_employer_partner(
                create_employer_partner_payload(**DUNMORE_FREIGHT), COORDINATOR
            ),
            expected_status=201,
        )
        payload = create_worksite_payload(
            partner["id"], site_name="Dunmore Cross Dock", address_line="9 Dunmore Way"
        )
        payload.pop("max_concurrent_students")

        response = api_client.create_worksite(payload, COORDINATOR)

        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)
        assert response.status_code == 400
        assert (
            get_success_data(
                api_client.list_employer_partner_worksites(partner["id"], COORDINATOR)
            )
            == []
        )

    def test_a_hazard_class_outside_the_enumeration_is_a_malformed_body(self):
        """`hazard_class` classifies the work performed on site as `NON_HAZARDOUS`,
        `LIMITED_HAZARD` or `PROHIBITED_HAZARD`. 8. Request body shape is valid —
        `ERR_INVALID_REQUEST` (400).

        Design: Corner/entities/worksite_create_with_invalid_hazard_class_enum_rejected
        """
        set_clock("2026-09-01T08:00:00Z")
        partner = validate_success(
            api_client.create_employer_partner(
                create_employer_partner_payload(**EVERLINE_FABRICATION), COORDINATOR
            ),
            expected_status=201,
        )

        response = api_client.create_worksite(
            create_worksite_payload(
                partner["id"],
                site_name="Everline Weld Shop",
                address_line="77 Everline Rd",
                hazard_class="SOMEWHAT_HAZARDOUS",
                has_power_machinery=True,
                max_concurrent_students=2,
            ),
            COORDINATOR,
        )

        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)
        assert response.status_code == 400
        assert (
            get_success_data(
                api_client.list_employer_partner_worksites(partner["id"], COORDINATOR)
            )
            == []
        )


class TestPlacementOptionalFieldDefault:
    def test_omitting_the_cycle_count_falls_back_to_two_required_cycles(self):
        """`required_evaluation_cycles` is optional, defaults to 2, and must be between 1 and
        4. `lifecycle_status` starts at `PROPOSED` and tracks the placement as an assignment.

        Design: Corner/entities/placement_create_omitting_required_evaluation_cycles_applies_default_two
        """
        set_clock("2026-09-07T08:00:00Z")
        scenario = setup_agreement_ready(
            partner_overrides=GLADSTONE_HARDWARE,
            worksite_overrides={
                "site_name": "Gladstone Sales Floor",
                "address_line": "15 Gladstone St",
                "max_concurrent_students": 2,
            },
            supervisor_overrides={"full_name": "Pat Ellery", "max_student_load": 2},
        )
        scenario.student, scenario.permit = enrol_student_with_issued_permit(
            permit_class="MINOR_16_17", **HANA_ILVES
        )
        worksite = read_worksite(scenario.worksite_id)
        payload = create_placement_payload(
            scenario.student_id,
            scenario.worksite_id,
            scenario.agreement_id,
            scenario.supervisor_id,
            worksite["version"],
            **ONE_CYCLE_PLACEMENT,
        )
        payload.pop("required_evaluation_cycles")

        placement = validate_success(
            api_client.create_placement(payload, COORDINATOR), expected_status=201
        )

        assert placement["required_evaluation_cycles"] == 2
        assert placement["lifecycle_status"] == "PROPOSED"
        assert placement["compliance_status"] == "PENDING_REVIEW"
        assert placement["permit_class_at_start"] == "MINOR_16_17"
        assert placement["student_age_at_start"] == 17
        assert read_worksite(scenario.worksite_id)["slots_committed"] == 1


class TestLearningObjectiveHasNoVersion:
    def test_an_objective_carries_only_an_id_and_a_creation_timestamp(self):
        """`LearningObjective` is the single exception. An objective is an immutable line
        item on a training plan: it carries only `id` and `created_at`. It has no `updated_at`
        and no `version`, and neither field appears in its representation.

        Design: Corner/entities/learning_objective_is_immutable_with_no_version_field
        """
        scenario = setup_proposed_placement(
            clock="2026-09-07T08:00:00Z",
            partner_overrides=IRONWOOD_CABINETRY,
            worksite_overrides={
                "site_name": "Ironwood Finishing Room",
                "address_line": "3 Ironwood Ct",
                "max_concurrent_students": 2,
            },
            supervisor_overrides={"full_name": "Lex Moreau", "max_student_load": 2},
            student_overrides=MILO_BERGSTROM,
            permit_class="MINOR_16_17",
            placement_overrides=dict(ONE_CYCLE_PLACEMENT),
        )
        draft_plan_with_objectives(
            scenario, course_code="CTE-500", credit_hours_target=60.00, objective_count=0
        )

        objective = validate_success(
            api_client.create_learning_objective(
                create_learning_objective_payload(
                    scenario.plan_id,
                    "CTE-500",
                    competency_code="IW-1",
                    description="Sand and seal a face frame to spec",
                ),
                COORDINATOR,
            ),
            expected_status=201,
        )

        assert is_valid_uuid(objective["id"])
        assert "created_at" in objective
        assert "version" not in objective
        assert "updated_at" not in objective

        listed = list_objectives(scenario.plan_id)
        assert len(listed) == 1
        assert listed[0]["id"] == objective["id"]
        assert "version" not in listed[0]

    def test_adding_an_aligned_objective_moves_both_plan_counters(self):
        """Adding an objective increments the plan's `objective_count`, and increments
        `aligned_objective_count` as well when the objective's `aligned_course_code` equals
        the plan's `course_code`; the plan's `version` increases by 1.

        Design: Corner/entities/learning_objective_is_immutable_with_no_version_field
        """
        scenario = setup_proposed_placement(
            clock="2026-09-07T08:00:00Z",
            partner_overrides=IRONWOOD_CABINETRY,
            worksite_overrides={
                "site_name": "Ironwood Finishing Room",
                "address_line": "3 Ironwood Ct",
                "max_concurrent_students": 2,
            },
            supervisor_overrides={"full_name": "Lex Moreau", "max_student_load": 2},
            student_overrides=MILO_BERGSTROM,
            permit_class="MINOR_16_17",
            placement_overrides=dict(ONE_CYCLE_PLACEMENT),
        )
        draft_plan_with_objectives(
            scenario, course_code="CTE-500", credit_hours_target=60.00, objective_count=0
        )
        before = read_plan(scenario.plan_id)

        validate_success(
            api_client.create_learning_objective(
                create_learning_objective_payload(
                    scenario.plan_id,
                    "CTE-500",
                    competency_code="IW-1",
                    description="Sand and seal a face frame to spec",
                ),
                COORDINATOR,
            ),
            expected_status=201,
        )

        plan = read_plan(scenario.plan_id)
        assert plan["objective_count"] == 1
        assert plan["aligned_objective_count"] == 1
        assert plan["version"] == before["version"] + 1

