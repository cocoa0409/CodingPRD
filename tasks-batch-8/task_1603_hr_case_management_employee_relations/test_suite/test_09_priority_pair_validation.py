"""Validation priority pair tests (Difficulty rule 5)."""
import pytest

from test_helpers import (
    api_client,
    TEST_USERS,
    make_investigator_headers,
    setup_intake_channel,
    setup_employee,
    setup_investigator,
    setup_case,
    assign_case_to,
    setup_investigating_case,
    schedule_interview,
    complete_interview,
    log_evidence,
    admit_evidence,
    create_assessment,
    create_draft_finding,
    substantiate_finding,
    propose_action,
    submit_for_calibration,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
)


class TestAssignStateVsConflict:
    def test_invalid_state_wins_over_conflict_when_case_already_assigned(self):
        """PRD §2.6: "State legality follows existence: the requested transition
        must be defined from the resource's current state, or the request fails
        with `ERR_INVALID_STATE` (HTTP 409), and the litigation-hold freeze of
        §2.7 is applied at the same layer (`ERR_LITIGATION_HOLD`, HTTP 409).
        Only then do the business rules run, in their own fixed sequence."

        Design: Difficulty/priority_pair_validation_conflict/assign_state_vs_conflict_priority
        """
        channel = setup_intake_channel(
            channel_code="HOTLINE", display_name="Hotline E",
            default_category="HARASSMENT", default_severity="LOW",
            sla_business_days=10,
        )
        reporter = setup_employee()
        subject = setup_employee()
        _, inv1 = setup_investigator()
        _, inv2 = setup_investigator(conflicted_employee_ids=None)
        # make inv2 conflicted against the subject
        resp = api_client.create_investigator(
            {
                "employee_id": setup_employee()["id"],
                "certification_level": "LEVEL_3",
                "max_active_cases": 10,
                "conflicted_employee_ids": [subject["id"]],
            },
            TEST_USERS["er_manager_headers"],
        )
        inv2 = get_success_data(resp)
        # Case already ASSIGNED to inv1
        case = setup_case(channel["id"], subject["id"], reporter_employee_id=reporter["id"],
                          category="HARASSMENT", severity="LOW")
        assign_case_to(case["id"], inv1["id"], case["version"])
        current = get_success_data(api_client.get_case(case["id"], TEST_USERS["er_manager_headers"]))
        # Attempt to assign to inv2 (conflicted) from ASSIGNED — state error wins
        resp = api_client.assign_case(
            case["id"],
            {"investigator_id": inv2["id"], "expected_case_version": current["version"]},
            TEST_USERS["er_manager_headers"],
        )
        err = validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        assert err["error_id"] == "ERR_INVALID_STATE"

    def test_invalid_state_wins_over_conflict_case_in_investigating(self):
        """PRD §2.6: "State legality follows existence: the requested transition
        must be defined from the resource's current state, or the request fails
        with `ERR_INVALID_STATE` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/assign_state_vs_conflict_priority
        """
        channel = setup_intake_channel(
            channel_code="HOTLINE", display_name="Hotline E",
            default_category="HARASSMENT", default_severity="LOW",
            sla_business_days=10,
        )
        reporter = setup_employee()
        subject = setup_employee()
        _, inv1 = setup_investigator()
        resp = api_client.create_investigator(
            {
                "employee_id": setup_employee()["id"],
                "certification_level": "LEVEL_3",
                "max_active_cases": 10,
                "conflicted_employee_ids": [subject["id"]],
            },
            TEST_USERS["er_manager_headers"],
        )
        inv2 = get_success_data(resp)
        case = setup_investigating_case(
            channel["id"], subject["id"], inv1["id"],
            reporter_employee_id=reporter["id"],
            category="HARASSMENT", severity="LOW",
        )
        current = get_success_data(api_client.get_case(case["id"], TEST_USERS["er_manager_headers"]))
        resp = api_client.assign_case(
            case["id"],
            {"investigator_id": inv2["id"], "expected_case_version": current["version"]},
            TEST_USERS["er_manager_headers"],
        )
        err = validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        # Confirm the assignment did not change
        after = get_success_data(api_client.get_case(case["id"], TEST_USERS["er_manager_headers"]))
        assert after["assigned_investigator_id"] == inv1["id"]


class TestApproveSoDVotePrecedence:
    def test_author_self_approve_rejected_with_segregation_of_duties(self):
        """PRD §2.8: "an author voting on their own finding fails with
        `ERR_SEGREGATION_OF_DUTIES`."
        PRD §2.8: "On the approval path the segregation check runs first, per
        §2.6, so an author attempting to approve their own finding sees
        `ERR_SEGREGATION_OF_DUTIES` even when they are also conflicted."

        Design: Difficulty/priority_pair_validation_conflict/approve_sod_vs_documentation_priority
        """
        cast_channel = setup_intake_channel(
            channel_code="WEB_PORTAL", display_name="Portal F",
            default_category="DISCRIMINATION", default_severity="HIGH",
            sla_business_days=20,
        )
        reporter = setup_employee(location_code="CHI")
        subject = setup_employee(location_code="CHI")
        _, inv1 = setup_investigator()
        case = setup_investigating_case(
            cast_channel["id"], subject["id"], inv1["id"],
            reporter_employee_id=reporter["id"],
            category="DISCRIMINATION", severity="HIGH",
        )
        iv = schedule_interview(case["id"], inv1["id"], subject["id"])
        complete_interview(iv["id"], inv1["id"])
        ev = log_evidence(case["id"], inv1["id"], reporter["id"], evidence_type="EMAIL")
        admit_evidence(ev["id"], inv1["id"], weight=0.8)
        create_assessment(case["id"], inv1["id"], subject["id"],
                          corroboration_count=4, contradiction_count=0, account_age_days=2)
        finding = create_draft_finding(case["id"], inv1["id"])
        substantiate_finding(finding["id"], inv1["id"], outcome="SUBSTANTIATED")
        propose_action(finding["id"], inv1["id"],
                        action_type="FINAL_WARNING", severity_points=55,
                        justification="Final warning proportionate to the substantiated conduct here.")
        submit_for_calibration(finding["id"], inv1["id"])
        # Author attempts to approve their own finding
        resp = api_client.approve_finding(
            finding["id"], make_investigator_headers(inv1["id"])
        )
        err = validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 422)
        assert err["error_id"] == "ERR_SEGREGATION_OF_DUTIES"

    def test_author_self_approve_leaves_finding_unchanged(self):
        """PRD §2.8: "The investigator who authored a finding may not cast an
        approval or rejection vote on it."

        Design: Difficulty/priority_pair_validation_conflict/approve_sod_vs_documentation_priority
        """
        cast_channel = setup_intake_channel(
            channel_code="WEB_PORTAL", display_name="Portal F",
            default_category="DISCRIMINATION", default_severity="HIGH",
            sla_business_days=20,
        )
        reporter = setup_employee(location_code="CHI")
        subject = setup_employee(location_code="CHI")
        _, inv1 = setup_investigator()
        case = setup_investigating_case(
            cast_channel["id"], subject["id"], inv1["id"],
            reporter_employee_id=reporter["id"],
            category="DISCRIMINATION", severity="HIGH",
        )
        iv = schedule_interview(case["id"], inv1["id"], subject["id"])
        complete_interview(iv["id"], inv1["id"])
        ev = log_evidence(case["id"], inv1["id"], reporter["id"], evidence_type="EMAIL")
        admit_evidence(ev["id"], inv1["id"], weight=0.8)
        create_assessment(case["id"], inv1["id"], subject["id"],
                          corroboration_count=4, contradiction_count=0, account_age_days=2)
        finding = create_draft_finding(case["id"], inv1["id"])
        substantiate_finding(finding["id"], inv1["id"], outcome="SUBSTANTIATED")
        propose_action(finding["id"], inv1["id"],
                        action_type="FINAL_WARNING", severity_points=55,
                        justification="Final warning proportionate to the substantiated conduct here.")
        submit_for_calibration(finding["id"], inv1["id"])
        # Before author vote: capture approval_status
        before = get_success_data(api_client.get_finding(finding["id"], TEST_USERS["er_manager_headers"]))
        assert before["approval_status"] == "CALIBRATED"
        # Author self-approve fails
        resp = api_client.approve_finding(
            finding["id"], make_investigator_headers(inv1["id"])
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 422)
        after = get_success_data(api_client.get_finding(finding["id"], TEST_USERS["er_manager_headers"]))
        assert after["approval_status"] == "CALIBRATED", (
            f"approval_status must remain CALIBRATED after failed self-approve, got {after['approval_status']}"
        )
        assert after["calibrated_by_ids"] == [], (
            "calibrated_by_ids must not include the author"
        )
