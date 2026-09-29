"""State-machine coverage across the four lifecycles that have from-state guards:
the once-only safety decision and its conditional outcome, the permit that cannot
be re-issued after revocation, the agreement negotiation cap and its terminal
state, the cycle that closes from whichever dimension finishes last, and the
completion gate that counts closed cycles.
"""

from test_helpers import (
    COORDINATOR,
    DRAFTER,
    OFFICER,
    REVIEWER,
    ApiErrorId,
    api_client,
    accept_cycle_reflection,
    create_agreement_payload,
    create_work_permit_payload,
    decide_safety_review,
    decide_safety_review_payload,
    enrol_student,
    enrol_student_with_issued_permit,
    file_safety_review,
    issue_work_permit_payload,
    list_cycles,
    make_employer_supervisor_headers,
    read_agreement,
    read_partner,
    read_permit,
    read_placement,
    read_worksite,
    recruit_employer_partner,
    register_worksite,
    request_changes_payload,
    revoke_work_permit,
    set_clock,
    setup_active_placement,
    setup_agreement_ready,
    setup_partner_worksite_supervisor,
    submit_cycle_reflection,
    submit_evaluation_payload,
    validate_error,
    validate_success,
)

JUNCTION_POINT = {
    "legal_name": "Junction Point Media",
    "naics_code": "512110",
    "industry_sector": "PUBLIC_ADMINISTRATION",
    "workers_comp_policy_no": "WC-10071",
}
KESTREL_MACHINE = {
    "legal_name": "Kestrel Machine Shop",
    "naics_code": "332710",
    "industry_sector": "MANUFACTURING",
    "workers_comp_policy_no": "WC-10081",
}
LANTERN_BAY = {
    "legal_name": "Lantern Bay Grocers",
    "naics_code": "445110",
    "industry_sector": "HOSPITALITY",
    "workers_comp_policy_no": "WC-10091",
}
MERIDIAN_PRINT = {
    "legal_name": "Meridian Print Shop",
    "naics_code": "323113",
    "industry_sector": "MANUFACTURING",
    "workers_comp_policy_no": "WC-10101",
}
NORTHGATE_PHARMACY = {
    "legal_name": "Northgate Pharmacy",
    "naics_code": "456110",
    "industry_sector": "HEALTHCARE",
    "workers_comp_policy_no": "WC-10111",
}
OVERLOOK_HOTEL = {
    "legal_name": "Overlook Hotel Group",
    "naics_code": "721110",
    "industry_sector": "HOSPITALITY",
    "workers_comp_policy_no": "WC-10121",
}

NADIA_FENWICK = {
    "full_name": "Nadia Fenwick",
    "birth_date": "2009-07-07",
    "grade_level": 11,
    "gpa": 3.00,
    "attendance_rate": 0.93,
    "student_learner_certificate": True,
}
ORIN_VASQUEZ = {
    "full_name": "Orin Vasquez",
    "birth_date": "2009-08-16",
    "grade_level": 12,
    "gpa": 3.05,
    "attendance_rate": 0.92,
    "student_learner_certificate": True,
}
TOBIAS_REYNA = {
    "full_name": "Tobias Reyna",
    "birth_date": "2009-02-25",
    "grade_level": 12,
    "gpa": 3.40,
    "attendance_rate": 0.96,
    "student_learner_certificate": True,
}
VIV_LACHANCE = {
    "full_name": "Viv Lachance",
    "birth_date": "2009-11-11",
    "grade_level": 12,
    "gpa": 3.00,
    "attendance_rate": 0.90,
    "student_learner_certificate": True,
}


class TestSafetyReviewDecidesOnce:
    def test_a_second_decision_on_the_same_review_is_refused(self):
        """All three require the review to still be in `SUBMITTED`; a second decision on the
        same review is refused with `ERR_REVIEW_ALREADY_DECIDED`. The worksite's
        `safety_status` becomes `APPROVED`, its `safety_review_expires_on` copies the review's
        `expires_on`, its `corrective_actions_due_on` is set to null, and its `version`
        increases by 1.

        Design: Corner/state_machines/safety_review_second_decision_cannot_be_recorded
        """
        set_clock("2026-09-07T08:00:00Z")
        partner = recruit_employer_partner(**JUNCTION_POINT)
        worksite = register_worksite(
            partner["id"],
            site_name="Junction Point Edit Suite",
            address_line="4 Junction Way",
            max_concurrent_students=2,
        )
        review = file_safety_review(worksite["id"], worksite["version"])
        decide_safety_review(review["id"], "APPROVED")
        decided_worksite = read_worksite(worksite["id"])

        response = api_client.decide_safety_review(
            review["id"], decide_safety_review_payload("APPROVED"), REVIEWER
        )

        validate_error(response, ApiErrorId.ERR_REVIEW_ALREADY_DECIDED.value)
        assert response.status_code == 409

        after = read_worksite(worksite["id"])
        assert after["safety_status"] == "APPROVED"
        assert after["version"] == decided_worksite["version"]


class TestConditionalSafetyDecision:
    def test_a_conditional_clearance_sets_both_dates_and_costs_ten_points(self):
        """It requires `machinery_guarding_ok` true and `hazard_findings_count` between 1 and
        3 inclusive. The review's `decision_on` is set to the clock date, its
        `corrective_actions_due_on` to 30 days after `decision_on`, and its `expires_on` to
        365 days after `decision_on`. The worksite's `safety_status` becomes `CONDITIONAL`,
        its `corrective_actions_due_on` and `safety_review_expires_on` copy the review's
        values, and its `version` increases by 1. Subtract 10 points for each of the partner's
        worksites whose `safety_status` is `CONDITIONAL`.

        Design: Corner/state_machines/conditional_safety_review_sets_corrective_action_due_date_and_score_penalty
        """
        set_clock("2026-09-07T08:00:00Z")
        partner = recruit_employer_partner(**KESTREL_MACHINE)
        worksite = register_worksite(
            partner["id"],
            site_name="Kestrel Bench Area",
            address_line="21 Kestrel Rd",
            hazard_class="LIMITED_HAZARD",
            has_power_machinery=True,
            max_concurrent_students=1,
        )
        review = file_safety_review(
            worksite["id"], worksite["version"], hazard_findings_count=2
        )

        decided = validate_success(
            api_client.decide_safety_review(
                review["id"], decide_safety_review_payload("CONDITIONAL"), REVIEWER
            )
        )

        assert decided["status"] == "CONDITIONAL"
        assert decided["decision_on"] == "2026-09-07"
        assert decided["corrective_actions_due_on"] == "2026-10-07"
        assert decided["expires_on"] == "2027-09-07"

        stored_worksite = read_worksite(worksite["id"])
        assert stored_worksite["safety_status"] == "CONDITIONAL"
        assert stored_worksite["corrective_actions_due_on"] == "2026-10-07"
        assert stored_worksite["safety_review_expires_on"] == "2027-09-07"

        stored_partner = read_partner(partner["id"])
        assert stored_partner["safety_score"] == 90
        assert stored_partner["posture"] == "ELIGIBLE"


class TestWorkPermitLifecycle:
    def test_a_requested_permit_begins_unissued_with_no_expiry(self):
        """A requested permit begins at `status` of `REQUESTED` with `issued_on`,
        `expires_on`, `revoked_reason` and `issued_by_user_id` all null.

        Design: Corner/state_machines/work_permit_starts_in_requested_state
        """
        set_clock("2026-09-07T08:00:00Z")
        student = enrol_student(**NADIA_FENWICK)

        permit = validate_success(
            api_client.create_work_permit(
                create_work_permit_payload(
                    student["id"], permit_class="MINOR_16_17", hazardous_endorsement=False
                ),
                COORDINATOR,
            ),
            expected_status=201,
        )

        assert permit["status"] == "REQUESTED"
        assert permit["expires_on"] is None
        assert permit["issued_on"] is None
        assert permit["revoked_reason"] is None
        assert permit["issued_by_user_id"] is None
        assert permit["permit_class"] == "MINOR_16_17"
        assert permit["hazardous_endorsement"] is False

    def test_a_revoked_permit_cannot_be_issued_a_second_time(self):
        """Revocation moves the permit `ISSUED → REVOKED` and stores the supplied
        `revoked_reason`. Attempting issuance on a permit that is not `REQUESTED`, or
        revocation on a permit that is not `ISSUED`, is refused with
        `ERR_PERMIT_INVALID_STATE`.

        Design: Corner/state_machines/revoked_work_permit_cannot_be_issued_again
        """
        set_clock("2026-09-07T08:00:00Z")
        student, permit = enrol_student_with_issued_permit(
            permit_class="MINOR_16_17", **ORIN_VASQUEZ
        )
        revoke_work_permit(permit["id"], "Permit issued with the wrong permit class")

        response = api_client.issue_work_permit(
            permit["id"], issue_work_permit_payload("2027-06-30"), OFFICER
        )

        validate_error(response, ApiErrorId.ERR_PERMIT_INVALID_STATE.value)
        assert response.status_code == 409
        assert read_permit(student["id"], permit["id"])["status"] == "REVOKED"


class TestAgreementNegotiationStates:
    def test_a_terminated_agreement_cannot_be_returned_for_changes(self):
        """Termination moves an `EXECUTED` agreement to `TERMINATED` and takes its placements
        down with it. Requesting any agreement transition from the wrong state —
        countersignature when the agreement is not `PENDING_EMPLOYER`, change request or
        execution when it is not `PENDING_DISTRICT`, termination when it is not `EXECUTED` —
        is refused with `ERR_AGREEMENT_INVALID_STATE`.

        Design: Corner/state_machines/terminated_agreement_cannot_be_returned_for_changes
        """
        set_clock("2026-09-07T08:00:00Z")
        scenario = setup_agreement_ready(
            partner_overrides=LANTERN_BAY,
            worksite_overrides={
                "site_name": "Lantern Bay Deli",
                "address_line": "60 Lantern Bay",
                "max_concurrent_students": 2,
            },
            supervisor_overrides={"full_name": "Quinn Adeyemi", "max_student_load": 2},
        )
        validate_success(
            api_client.terminate_agreement(
                scenario.agreement_id,
                {"termination_reason": "Employer withdrew from the programme"},
                COORDINATOR,
            )
        )

        response = api_client.request_agreement_changes(
            scenario.agreement_id,
            request_changes_payload("Please add the transport clause"),
            COORDINATOR,
        )

        validate_error(response, ApiErrorId.ERR_AGREEMENT_INVALID_STATE.value)
        assert response.status_code == 409

        agreement = read_agreement(scenario.agreement_id)
        assert agreement["status"] == "TERMINATED"
        assert agreement["revision_round"] == 0

    def test_the_fourth_change_request_hits_the_negotiation_cap(self):
        """Requesting changes moves the agreement `PENDING_DISTRICT → PENDING_EMPLOYER`,
        stores the supplied `change_request_note`, and increments `revision_round` by 1. This
        negotiation loop between `PENDING_EMPLOYER` and `PENDING_DISTRICT` is capped: the
        request is only accepted while `revision_round` is below 3, and the fourth attempt is
        refused with `ERR_NEGOTIATION_ROUND_LIMIT`.

        Design: Corner/state_machines/fourth_request_changes_hits_the_negotiation_round_limit
        """
        set_clock("2026-09-07T08:00:00Z")
        scenario = setup_partner_worksite_supervisor(
            partner_overrides=MERIDIAN_PRINT,
            worksite_overrides={
                "site_name": "Meridian Bindery",
                "address_line": "12 Meridian Ave",
                "max_concurrent_students": 2,
            },
            supervisor_overrides={"full_name": "Rosa Delacroix", "max_student_load": 2},
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
        signer_headers = make_employer_supervisor_headers(scenario.supervisor_id)
        for note in (
            "Round 1: fix the supervision ratio clause",
            "Round 2: attach the insurance certificate",
            "Round 3: correct the worksite address",
        ):
            validate_success(
                api_client.employer_sign_agreement(agreement["id"], {}, signer_headers)
            )
            validate_success(
                api_client.request_agreement_changes(
                    agreement["id"], request_changes_payload(note), COORDINATOR
                )
            )
        validate_success(
            api_client.employer_sign_agreement(agreement["id"], {}, signer_headers)
        )

        response = api_client.request_agreement_changes(
            agreement["id"],
            request_changes_payload("Round 4: one more wording tweak"),
            COORDINATOR,
        )

        validate_error(response, ApiErrorId.ERR_NEGOTIATION_ROUND_LIMIT.value)
        assert response.status_code == 422

        stored = read_agreement(agreement["id"])
        assert stored["status"] == "PENDING_DISTRICT"
        assert stored["revision_round"] == 3


class TestCycleClosesFromTheSupervisorSide:
    def test_the_supervisor_rating_closes_a_cycle_whose_reflection_is_already_accepted(self):
        """When the supervisor submits their ratings on a cycle whose `reflection_status` is
        already `ACCEPTED` and whose `supervisor_eval_status` is `PENDING`, that submission
        sets `supervisor_eval_status` to `SUBMITTED`, sets `cycle_status` to `CLOSED` and
        `closed_on` to the clock date, increments the placement's `closed_cycle_count` by 1,
        re-derives `credit_eligible`, and creates the successor cycle under the same "still
        short of `required_evaluation_cycles`" condition. Submission sets
        `supervisor_eval_status` to `SUBMITTED` and computes the cycle's `competency_score` as
        the weighted rating: three tenths of `rating_technical`, plus two tenths each of
        `rating_communication`, `rating_reliability` and `rating_safety`, plus one tenth of
        `rating_initiative`, with the sum rounded half-up to two decimal places.

        Design: Corner/state_machines/evaluation_cycle_closes_from_the_supervisor_branch_after_reflection_accepted
        """
        scenario = setup_active_placement(
            clock="2026-09-07T08:00:00Z",
            course_code="PHR-130",
            credit_hours_target=100.00,
            partner_overrides=NORTHGATE_PHARMACY,
            worksite_overrides={
                "site_name": "Northgate Counter",
                "address_line": "5 Northgate Sq",
                "max_concurrent_students": 2,
            },
            supervisor_overrides={"full_name": "Sana Whitlock", "max_student_load": 2},
            student_overrides=TOBIAS_REYNA,
            permit_class="MINOR_16_17",
        )
        set_clock("2026-09-20T08:00:00Z")
        first_cycle = list_cycles(scenario.placement_id)[0]
        submit_cycle_reflection(
            scenario,
            first_cycle["id"],
            "Cycle 1 reflection: counter service and privacy practice.",
        )
        accept_cycle_reflection(
            first_cycle["id"], feedback_note="Accepted ahead of the supervisor rating."
        )
        partial = list_cycles(scenario.placement_id)[0]
        assert partial["cycle_status"] == "PARTIAL"
        assert partial["reflection_status"] == "ACCEPTED"
        assert partial["supervisor_eval_status"] == "PENDING"

        closed = validate_success(
            api_client.submit_evaluation(
                first_cycle["id"],
                submit_evaluation_payload(
                    rating_technical=5,
                    rating_communication=4,
                    rating_reliability=4,
                    rating_safety=4,
                    rating_initiative=3,
                ),
                scenario.supervisor_headers,
            )
        )

        assert closed["cycle_status"] == "CLOSED"
        assert closed["supervisor_eval_status"] == "SUBMITTED"
        assert float(closed["competency_score"]) == 4.20
        assert closed["closed_on"] == "2026-09-20"

        placement = read_placement(scenario.placement_id)
        assert placement["closed_cycle_count"] == 1
        assert placement["credit_eligible"] is False

        cycles = list_cycles(scenario.placement_id)
        assert len(cycles) == 2
        assert cycles[1]["cycle_index"] == 2
        assert cycles[1]["cycle_status"] == "OPEN"
        assert cycles[1]["window_start"] == "2026-10-05"
        assert cycles[1]["window_end"] == "2026-11-01"


class TestCompletionCountsClosedCycles:
    def test_completing_before_the_required_cycles_close_is_refused(self):
        """It requires the placement to be `ACTIVE`, its `compliance_status` to be anything
        other than `BLOCKED`, and its `closed_cycle_count` to be at least its
        `required_evaluation_cycles` — falling short is refused with
        `ERR_EVALUATION_CYCLES_INCOMPLETE`. On completion `completed_on` takes the clock date;
        the worksite's `slots_committed`, the supervisor's `active_student_load` and the
        student's `active_placement_count` are each decremented by 1; and any remaining
        evaluation cycle of the placement whose `cycle_status` is `OPEN` or `PARTIAL` moves to
        `CANCELLED`, permanently outside `closed_cycle_count`.

        Design: Corner/state_machines/placement_complete_before_required_cycles_close_rejected
        """
        scenario = setup_active_placement(
            clock="2026-09-07T08:00:00Z",
            course_code="HOS-120",
            credit_hours_target=60.00,
            partner_overrides=OVERLOOK_HOTEL,
            worksite_overrides={
                "site_name": "Overlook Front Desk",
                "address_line": "1 Overlook Dr",
                "max_concurrent_students": 2,
            },
            supervisor_overrides={"full_name": "Uma Castellan", "max_student_load": 2},
            student_overrides=VIV_LACHANCE,
            permit_class="MINOR_16_17",
        )
        set_clock("2026-09-20T08:00:00Z")

        response = api_client.complete_placement(scenario.placement_id, {}, COORDINATOR)

        validate_error(response, ApiErrorId.ERR_EVALUATION_CYCLES_INCOMPLETE.value)
        assert response.status_code == 422

        placement = read_placement(scenario.placement_id)
        assert placement["lifecycle_status"] == "ACTIVE"
        assert placement["closed_cycle_count"] == 0
        assert placement["completed_on"] is None
