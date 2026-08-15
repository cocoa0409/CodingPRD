"""Case CLOSED -> REOPENED cyclic state machine tests (Difficulty rule 3, instance 1)."""
import pytest

from test_helpers import (
    api_client,
    TEST_USERS,
    setup_intake_channel,
    setup_employee,
    setup_investigator,
    run_case_to_closed,
    create_assessment,
    setup_investigating_case,
    schedule_interview,
    complete_interview,
    log_evidence,
    admit_evidence,
    validate_success,
    get_success_data,
)


def _setup_closed_case_with_assessment():
    """Closed anonymous-intake case with one credibility assessment."""
    channel = setup_intake_channel(
        channel_code="ANONYMOUS_LETTER", display_name="Anon",
        default_category="SAFETY", default_severity="MEDIUM", sla_business_days=15,
    )
    subject = setup_employee(location_code="SF")
    _, inv1 = setup_investigator()
    _, inv2 = setup_investigator()
    _, inv3 = setup_investigator()
    case = setup_investigating_case(
        channel["id"], subject["id"], inv1["id"],
        category="SAFETY", severity="MEDIUM",
    )
    iv = schedule_interview(case["id"], inv1["id"], subject["id"])
    complete_interview(iv["id"], inv1["id"])
    ev = log_evidence(case["id"], inv1["id"], subject["id"], evidence_type="PHOTO")
    admit_evidence(ev["id"], inv1["id"], weight=0.75)
    ca = create_assessment(case["id"], inv1["id"], subject["id"],
                            corroboration_count=3, contradiction_count=0, account_age_days=10)
    # finish pipeline
    from test_helpers import (
        create_draft_finding, substantiate_finding, propose_action,
        submit_for_calibration, approve_finding_as, create_closure_notice_payload,
    )
    finding = create_draft_finding(case["id"], inv1["id"])
    substantiate_finding(finding["id"], inv1["id"], outcome="SUBSTANTIATED")
    propose_action(finding["id"], inv1["id"],
                    action_type="POLICY_CHANGE", severity_points=25)
    submit_for_calibration(finding["id"], inv1["id"])
    approve_finding_as(finding["id"], inv2["id"])
    approve_finding_as(finding["id"], inv3["id"])
    notice_resp = api_client.create_closure_notice(
        case["id"],
        create_closure_notice_payload(
            subject["id"], recipient_role="SUBJECT",
            confidentiality_tier="TIER_2_LIMITED",
        ),
        TEST_USERS["er_manager_headers"],
    )
    notice = get_success_data(notice_resp)
    api_client.send_notice(notice["id"], TEST_USERS["er_manager_headers"])
    final_case = get_success_data(api_client.get_case(case["id"], TEST_USERS["er_manager_headers"]))
    closed_resp = api_client.close_case(
        case["id"], {"expected_case_version": final_case["version"]},
        TEST_USERS["er_manager_headers"],
    )
    closed_case = get_success_data(closed_resp)
    return closed_case, ca, inv1, inv2, inv3


class TestCaseReopenCycle:
    def test_reopen_flips_active_variant_to_recency_weighted(self):
        """PRD §3.4: "When a case transitions from `CLOSED` to `REOPENED`
        (§3.6), every credibility assessment on the case has its
        `active_variant` switched to `RECENCY_WEIGHTED` and both of its scores
        recomputed from the stored inputs."

        Design: Difficulty/non_linear_state_machine/case_closed_reopened_cycle_with_variant_flip
        """
        closed_case, ca, inv1, _, _ = _setup_closed_case_with_assessment()
        assert ca["active_variant"] == "CORROBORATION_WEIGHTED"
        resp = api_client.reopen_case(
            closed_case["id"],
            {"reopen_reason": "New corroborating witness came forward after closure with material testimony."},
            TEST_USERS["er_manager_headers"],
        )
        reopened = validate_success(resp, 200)
        assert reopened["status"] == "REOPENED"
        assert reopened["reopen_count"] == 1
        # Check the assessment variant flipped
        ca_after = get_success_data(api_client.get_credibility_assessment(
            ca["id"], TEST_USERS["er_manager_headers"]
        ))
        assert ca_after["active_variant"] == "RECENCY_WEIGHTED", (
            f"active_variant expected RECENCY_WEIGHTED after reopen, got {ca_after['active_variant']}"
        )

    def test_reopen_increments_count_and_retains_closed_at(self):
        """PRD §3.6: "Reopening moves the case to `REOPENED`, increments
        `reopen_count` by one, retains the prior closure's `closed_at` and
        `days_to_close` untouched, flips every credibility assessment's
        `active_variant` to `RECENCY_WEIGHTED` with both scores recomputed
        (§3.4), marks matching trend snapshots stale, and advances the case's
        `version`."

        Design: Difficulty/non_linear_state_machine/case_closed_reopened_cycle_with_variant_flip
        """
        closed_case, ca, inv1, _, _ = _setup_closed_case_with_assessment()
        prior_closed_at = closed_case["closed_at"]
        assert prior_closed_at is not None
        prior_version = closed_case["version"]
        resp = api_client.reopen_case(
            closed_case["id"],
            {"reopen_reason": "New corroborating witness came forward after closure with material testimony."},
            TEST_USERS["er_manager_headers"],
        )
        reopened = validate_success(resp, 200)
        assert reopened["status"] == "REOPENED"
        assert reopened["reopen_count"] == 1
        # closed_at retained
        assert reopened["closed_at"] == prior_closed_at, (
            f"closed_at must be retained from prior closure: {prior_closed_at} vs {reopened['closed_at']}"
        )
        # version advanced
        assert reopened["version"] > prior_version
