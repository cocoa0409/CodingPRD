"""Validation coverage on the two gates that compare one row's parent against
another's: the nominated signer's worksite, and the hazard rules that apply to
minors only. Plus the authorisation rung, which outranks resource resolution even
when the addressed row does not exist.
"""

from test_helpers import (
    COORDINATOR,
    COORDINATOR_DRAFTER,
    DRAFTER,
    ApiErrorId,
    api_client,
    create_agreement_payload,
    create_placement_payload,
    enrol_student_with_issued_permit,
    get_success_data,
    issue_work_permit_payload,
    read_worksite,
    recruit_employer_partner,
    register_supervisor,
    register_worksite,
    set_clock,
    setup_agreement_ready,
    validate_error,
    validate_success,
)

CEDAR_LINE = {
    "legal_name": "Cedar Line Logistics",
    "naics_code": "484121",
    "industry_sector": "PUBLIC_ADMINISTRATION",
    "workers_comp_policy_no": "WC-10151",
}
DELTA_RIDGE = {
    "legal_name": "Delta Ridge Bakery",
    "naics_code": "311811",
    "industry_sector": "HOSPITALITY",
    "workers_comp_policy_no": "WC-10161",
}
FOXGLEN_METALWORKS = {
    "legal_name": "Foxglen Metalworks",
    "naics_code": "332999",
    "industry_sector": "MANUFACTURING",
    "workers_comp_policy_no": "WC-10171",
}

HAL_FERREIRA = {
    "full_name": "Hal Ferreira",
    "birth_date": "2008-02-11",
    "grade_level": 12,
    "gpa": 3.10,
    "attendance_rate": 0.93,
    "student_learner_certificate": False,
}

UNKNOWN_PERMIT_ID = "44444444-3333-4222-8111-000000000000"


class TestAgreementSignerBelongsToTheWorksite:
    def test_a_signer_from_a_sibling_worksite_is_refused(self):
        """The nominated signer must belong to the agreement's worksite; if the supervisor's
        `worksite_id` differs, drafting is rejected with `ERR_SUPERVISOR_WORKSITE_MISMATCH`.

        Design: Corner/validations/agreement_signer_from_another_worksite_rejected
        """
        set_clock("2026-09-01T08:00:00Z")
        partner = recruit_employer_partner(**CEDAR_LINE)
        site_a = register_worksite(
            partner["id"],
            site_name="Cedar Line Dock A",
            address_line="30 Cedar Line Rd",
            max_concurrent_students=2,
        )
        site_b = register_worksite(
            partner["id"],
            site_name="Cedar Line Dock B",
            address_line="32 Cedar Line Rd",
            max_concurrent_students=2,
        )
        supervisor_b = register_supervisor(
            site_b["id"],
            full_name="Dev Ramgoolam",
            email="dev@cedarline.example",
            training_completed_on="2026-06-10",
            max_student_load=2,
        )

        response = api_client.create_agreement(
            create_agreement_payload(partner["id"], site_a["id"], supervisor_b["id"]),
            DRAFTER,
        )

        validate_error(response, ApiErrorId.ERR_SUPERVISOR_WORKSITE_MISMATCH.value)
        assert response.status_code == 422
        assert (
            get_success_data(
                api_client.list_agreements(COORDINATOR, {"worksite_id": site_a["id"]})
            )
            == []
        )

    def test_a_signer_on_the_same_worksite_drafts_a_pending_employer_agreement(self):
        """The drafting operator's `X-User-ID` is stored as `created_by_user_id`; the
        agreement starts at `status` of `PENDING_EMPLOYER` with `revision_round` of 0 and with
        `executed_by_user_id`, `executed_on`, `change_request_note` and `termination_reason`
        all null.

        Design: Corner/validations/agreement_signer_on_the_same_worksite_is_accepted
        """
        set_clock("2026-09-01T08:00:00Z")
        partner = recruit_employer_partner(**DELTA_RIDGE)
        worksite = register_worksite(
            partner["id"],
            site_name="Delta Ridge Bake House",
            address_line="44 Delta Ridge",
            max_concurrent_students=2,
        )
        supervisor = register_supervisor(
            worksite["id"],
            full_name="Emi Takahashi",
            email="emi@deltaridge.example",
            training_completed_on="2026-06-12",
            max_student_load=2,
        )

        agreement = validate_success(
            api_client.create_agreement(
                create_agreement_payload(
                    partner["id"], worksite["id"], supervisor["id"]
                ),
                DRAFTER,
            ),
            expected_status=201,
        )

        assert agreement["status"] == "PENDING_EMPLOYER"
        assert agreement["revision_round"] == 0
        assert agreement["executed_on"] is None
        assert agreement["executed_by_user_id"] is None
        assert agreement["created_by_user_id"] == COORDINATOR_DRAFTER
        assert agreement["version"] == 1


class TestAuthorisationOutranksResolution:
    def test_a_coordinator_issuing_a_permit_is_refused_before_the_id_is_resolved(self):
        """2. Acting role authorised for the endpoint — `ERR_UNAUTHORIZED` (403). 6.
        Path-parameter resources exist, left to right — the matching not-found code (404).
        Either a `WblCoordinator` or a `ComplianceOfficer` may request one; only a
        `ComplianceOfficer` may act on it thereafter.

        Design: Corner/validations/coordinator_cannot_issue_a_permit_even_when_the_permit_id_is_unknown
        """
        set_clock("2026-09-01T08:00:00Z")

        response = api_client.issue_work_permit(
            UNKNOWN_PERMIT_ID, issue_work_permit_payload("2027-06-30"), COORDINATOR
        )

        validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value)
        assert response.status_code == 403


class TestHazardRulesApplyToMinorsOnly:
    def test_an_adult_needs_no_endorsement_at_a_power_machinery_worksite(self):
        """Two hazard rules apply only to minors, that is, to placements whose
        `permit_class_at_start` is `MINOR_14_15` or `MINOR_16_17`. When the worksite's
        `hazard_class` is `LIMITED_HAZARD`, or its `has_power_machinery` is true, a minor's
        issued permit must carry `hazardous_endorsement` set to true, and a missing endorsement
        is refused with `ERR_HAZARDOUS_ENDORSEMENT_MISSING`. `permit_class_at_start` follows
        from it: ages 14 and 15 give `MINOR_14_15`, ages 16 and 17 give `MINOR_16_17`, and age
        18 or above gives `ADULT_18_PLUS`.

        Design: Corner/validations/adult_placement_at_a_machinery_worksite_needs_no_hazardous_endorsement
        """
        set_clock("2026-09-14T08:00:00Z")
        scenario = setup_agreement_ready(
            partner_overrides=FOXGLEN_METALWORKS,
            worksite_overrides={
                "site_name": "Foxglen Press Line",
                "address_line": "6 Foxglen Ave",
                "hazard_class": "LIMITED_HAZARD",
                "has_power_machinery": True,
                "max_concurrent_students": 2,
            },
            supervisor_overrides={
                "full_name": "Gil Andrade",
                "email": "gil@foxglen.example",
                "training_completed_on": "2026-06-20",
                "max_student_load": 2,
            },
        )
        scenario.student, scenario.permit = enrol_student_with_issued_permit(
            permit_class="ADULT_18_PLUS", hazardous_endorsement=False, **HAL_FERREIRA
        )
        worksite = read_worksite(scenario.worksite_id)

        placement = validate_success(
            api_client.create_placement(
                create_placement_payload(
                    scenario.student_id,
                    scenario.worksite_id,
                    scenario.agreement_id,
                    scenario.supervisor_id,
                    worksite["version"],
                    pay_classification="PAID",
                    hourly_wage_cents=1600,
                    stipend_total_cents=0,
                    scheduled_weekly_hours=20.00,
                    start_on="2026-09-14",
                    end_on="2026-12-18",
                    credit_target_credits=0.50,
                    credit_award_mode="HOURS_BASED",
                    required_evaluation_cycles=1,
                    transportation_mode="DISTRICT_BUS",
                    commute_round_trip_miles=0.00,
                ),
                COORDINATOR,
            ),
            expected_status=201,
        )

        assert placement["permit_class_at_start"] == "ADULT_18_PLUS"
        assert placement["student_age_at_start"] == 18
        assert placement["lifecycle_status"] == "PROPOSED"
        assert placement["compliance_status"] == "PENDING_REVIEW"
        assert read_worksite(scenario.worksite_id)["slots_committed"] == 1
