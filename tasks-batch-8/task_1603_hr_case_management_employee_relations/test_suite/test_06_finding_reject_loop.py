"""Finding reject-revision loop tests (Difficulty rule 3, instance 2)."""
import pytest

from test_helpers import (
    api_client,
    TEST_USERS,
    make_investigator_headers,
    setup_standard_cast,
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
    approve_finding_as,
    reject_finding_as,
    validate_success,
    get_success_data,
)


def _setup_case_in_calibration(cast):
    """Returns (case, finding, action) with one vote already cast by inv_peer1."""
    case = setup_investigating_case(
        cast["channel"]["id"], cast["subject"]["id"], cast["inv_author"]["id"],
        reporter_employee_id=cast["reporter"]["id"],
        category="DISCRIMINATION", severity="HIGH",
    )
    iv = schedule_interview(case["id"], cast["inv_author"]["id"], cast["subject"]["id"])
    complete_interview(iv["id"], cast["inv_author"]["id"])
    ev = log_evidence(case["id"], cast["inv_author"]["id"], cast["reporter"]["id"],
                      evidence_type="EMAIL")
    admit_evidence(ev["id"], cast["inv_author"]["id"], weight=0.9)
    create_assessment(case["id"], cast["inv_author"]["id"], cast["subject"]["id"],
                      corroboration_count=4, contradiction_count=0, account_age_days=3)
    finding = create_draft_finding(case["id"], cast["inv_author"]["id"])
    substantiate_finding(finding["id"], cast["inv_author"]["id"], outcome="SUBSTANTIATED")
    action = propose_action(
        finding["id"], cast["inv_author"]["id"],
        action_type="FINAL_WARNING", severity_points=60,
        justification="Final warning is proportionate to the substantiated discrimination.",
    )
    submit_for_calibration(finding["id"], cast["inv_author"]["id"])
    approve_finding_as(finding["id"], cast["inv_peer1"]["id"])
    return case, finding, action


class TestFindingRejectLoop:
    def test_reject_resets_approval_status_to_pending_review(self):
        """PRD §3.5: "The rejection is recorded by landing the finding's
        `approval_status` in `REJECTED`, then the revision loop immediately
        restores it to `PENDING_REVIEW` with `substantiation_status` returned
        to `DRAFT` and `calibrated_by_ids` cleared, while the case drops back
        from `CALIBRATION` to `FINDINGS_DRAFT` with its `version` advanced."

        Design: Difficulty/non_linear_state_machine/finding_parallel_dimensions_reject_loop
        """
        cast = setup_standard_cast(
            channel_kwargs={
                "channel_code": "WEB_PORTAL", "display_name": "Web Portal B",
                "default_category": "DISCRIMINATION", "default_severity": "HIGH",
                "sla_business_days": 20,
            }
        )
        case, finding, action = _setup_case_in_calibration(cast)
        # Now inv_peer2 rejects
        resp = api_client.reject_finding(
            finding["id"],
            {"rejection_reason": "Calibration panel requires tighter rationale for severity choice."},
            make_investigator_headers(cast["inv_peer2"]["id"]),
        )
        after = validate_success(resp, 200)
        assert after["approval_status"] == "PENDING_REVIEW", (
            f"approval_status expected PENDING_REVIEW after reject loop, got {after['approval_status']}"
        )
        assert after["substantiation_status"] == "DRAFT", (
            f"substantiation_status expected DRAFT after reject loop, got {after['substantiation_status']}"
        )
        assert after["calibrated_by_ids"] == [], (
            f"calibrated_by_ids expected cleared to [], got {after['calibrated_by_ids']}"
        )

    def test_reject_drops_case_back_to_findings_draft(self):
        """PRD §3.5: "The rejection is recorded by landing the finding's
        `approval_status` in `REJECTED`, then the revision loop immediately
        restores it to `PENDING_REVIEW` with `substantiation_status` returned
        to `DRAFT` and `calibrated_by_ids` cleared, while the case drops back
        from `CALIBRATION` to `FINDINGS_DRAFT` with its `version` advanced."

        Design: Difficulty/non_linear_state_machine/finding_parallel_dimensions_reject_loop
        """
        cast = setup_standard_cast(
            channel_kwargs={
                "channel_code": "WEB_PORTAL", "display_name": "Web Portal B",
                "default_category": "DISCRIMINATION", "default_severity": "HIGH",
                "sla_business_days": 20,
            }
        )
        case, finding, action = _setup_case_in_calibration(cast)
        case_during_cal = get_success_data(
            api_client.get_case(case["id"], TEST_USERS["er_manager_headers"])
        )
        assert case_during_cal["status"] == "CALIBRATION"
        resp = api_client.reject_finding(
            finding["id"],
            {"rejection_reason": "Calibration panel requires tighter rationale for severity choice."},
            make_investigator_headers(cast["inv_peer2"]["id"]),
        )
        validate_success(resp, 200)
        case_after = get_success_data(
            api_client.get_case(case["id"], TEST_USERS["er_manager_headers"])
        )
        assert case_after["status"] == "FINDINGS_DRAFT", (
            f"Case status expected FINDINGS_DRAFT after reject, got {case_after['status']}"
        )
        # Action stays PROPOSED — reject resets the finding, not the proposed actions
        action_list = get_success_data(api_client.list_finding_actions(
            finding["id"], TEST_USERS["er_manager_headers"]
        ))
        items = action_list if isinstance(action_list, list) else action_list.get("data", [])
        target = next((a for a in items if a["id"] == action["id"]), None)
        assert target is not None
        assert target["status"] == "PROPOSED", (
            f"Action status expected PROPOSED after reject (unchanged), got {target['status']}"
        )
