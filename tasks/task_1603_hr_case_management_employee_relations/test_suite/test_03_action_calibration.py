"""Calibration score nested median tests (Difficulty rule 2, instance 1)."""
import pytest

from test_helpers import (
    api_client,
    TEST_USERS,
    make_investigator_headers,
    setup_intake_channel,
    setup_employee,
    setup_investigator,
    set_clock,
    run_case_to_closed,
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
    validate_success,
    get_success_data,
)


def _drive_case_to_calibration(channel_id, subject_id, reporter_id,
                                inv_author, severity, action_specs):
    """Drive a case to CALIBRATION with given PROPOSED actions. Returns (case, finding, actions)."""
    case = setup_investigating_case(
        channel_id, subject_id, inv_author["id"],
        reporter_employee_id=reporter_id,
        category="HARASSMENT", severity=severity,
    )
    iv = schedule_interview(case["id"], inv_author["id"], subject_id)
    complete_interview(iv["id"], inv_author["id"])
    ev = log_evidence(case["id"], inv_author["id"], reporter_id)
    admit_evidence(ev["id"], inv_author["id"])
    create_assessment(case["id"], inv_author["id"], subject_id,
                      corroboration_count=4, contradiction_count=0, account_age_days=5)
    finding = create_draft_finding(case["id"], inv_author["id"])
    substantiate_finding(finding["id"], inv_author["id"], outcome="SUBSTANTIATED")
    actions = []
    for spec in action_specs:
        actions.append(propose_action(finding["id"], inv_author["id"], **spec))
    submit_for_calibration(finding["id"], inv_author["id"])
    return case, finding, actions


def _close_historical_case(channel_id, subject_id, reporter_id,
                            inv_author, inv_peer1, inv_peer2,
                            severity, accepted_points):
    """Drive a HARASSMENT case to CLOSED with a single action that becomes ACCEPTED."""
    run_case_to_closed(
        channel_id, subject_id, inv_author, inv_peer1, inv_peer2,
        reporter_employee_id=reporter_id,
        category="HARASSMENT", severity=severity,
        action_type="WRITTEN_WARNING", severity_points=accepted_points,
        substantiation_outcome="SUBSTANTIATED",
        assessment_kwargs={"corroboration_count": 4, "contradiction_count": 0,
                            "account_age_days": 5},
    )


class TestActionCalibration:
    def test_calibration_score_computed_from_history_median(self):
        """PRD §3.5: "When at least three historical findings exist, the
        reference point is the median of those numbers ... The deviation is the
        absolute difference between the proposal's number and the reference
        point; the score itself is one hundred minus that deviation, floored
        at zero so it can never go negative, divided by one hundred, and
        rounded half-up to two decimal places."

        Design: Difficulty/combinatorial_formula/action_calibration_nested_minmax_median
        """
        set_clock("2026-08-01T00:00:00Z")
        channel = setup_intake_channel(
            channel_code="HR_DIRECT", display_name="HR Direct",
            default_category="HARASSMENT", default_severity="HIGH",
            sla_business_days=20,
        )
        reporter = setup_employee(location_code="LA")
        subject = setup_employee(location_code="LA")
        _, inv1 = setup_investigator()
        _, inv2 = setup_investigator()
        _, inv3 = setup_investigator()

        # Three historical cases with accepted severities 20, 40, 60 → median 40
        for accepted in (20, 40, 60):
            _close_historical_case(channel["id"], subject["id"], reporter["id"],
                                    inv1, inv2, inv3, "MEDIUM", accepted)

        # Target case with two PROPOSED actions: 20 and 70 → proposed_max 70
        case, finding, actions = _drive_case_to_calibration(
            channel["id"], subject["id"], reporter["id"], inv1, "HIGH",
            [
                {"action_type": "WRITTEN_WARNING", "severity_points": 20,
                 "justification": "Lenient proposal for the target case outcome."},
                {"action_type": "SUSPENSION", "severity_points": 70,
                 "justification": "Severe proposal for the target case outcome."},
            ],
        )
        approve_finding_as(finding["id"], inv2["id"])
        resp = api_client.approve_finding(
            finding["id"], make_investigator_headers(inv3["id"])
        )
        result = validate_success(resp, 200)
        # |70 - 40| = 30 → score = (100 - 30)/100 = 0.70
        assert result["approval_status"] == "APPROVED"
        assert result["calibration_score"] == pytest.approx(0.70, abs=1e-6), (
            f"calibration_score expected 0.70, got {result['calibration_score']}"
        )

    def test_calibration_winner_flips_to_accepted_others_superseded(self):
        """PRD §3.5: "The calibration winner is the `PROPOSED` action carrying
        the highest `severity_points`, with ties broken in favor of the action
        created earliest; that winner flips to `ACCEPTED`, and every other
        `PROPOSED` action on the finding flips to `SUPERSEDED`."

        Design: Difficulty/combinatorial_formula/action_calibration_nested_minmax_median
        """
        set_clock("2026-08-01T00:00:00Z")
        channel = setup_intake_channel(
            channel_code="HR_DIRECT", display_name="HR Direct",
            default_category="HARASSMENT", default_severity="HIGH",
            sla_business_days=20,
        )
        reporter = setup_employee(location_code="LA")
        subject = setup_employee(location_code="LA")
        _, inv1 = setup_investigator()
        _, inv2 = setup_investigator()
        _, inv3 = setup_investigator()

        for accepted in (20, 40, 60):
            _close_historical_case(channel["id"], subject["id"], reporter["id"],
                                    inv1, inv2, inv3, "MEDIUM", accepted)

        case, finding, actions = _drive_case_to_calibration(
            channel["id"], subject["id"], reporter["id"], inv1, "HIGH",
            [
                {"action_type": "WRITTEN_WARNING", "severity_points": 20,
                 "justification": "Lenient proposal for the target case outcome."},
                {"action_type": "SUSPENSION", "severity_points": 70,
                 "justification": "Severe proposal for the target case outcome."},
            ],
        )
        lenient = actions[0]
        severe = actions[1]
        approve_finding_as(finding["id"], inv2["id"])
        approve_finding_as(finding["id"], inv3["id"])

        severe_after = get_success_data(
            api_client.list_findings(TEST_USERS["er_manager_headers"],
                                      params={"approval_status": "APPROVED"})
        )
        # Fetch each action to check status
        leni_fetched = None
        sev_fetched = None
        actions_list = get_success_data(api_client.list_finding_actions(
            finding["id"], TEST_USERS["er_manager_headers"]
        ))
        # the response is paginated-ish; handle either shape
        items = actions_list if isinstance(actions_list, list) else actions_list.get("data", [])
        for a in items:
            if a["id"] == lenient["id"]:
                leni_fetched = a
            elif a["id"] == severe["id"]:
                sev_fetched = a
        # Fallback: fetch each via list by id filter (some APIs return envelope)
        if leni_fetched is None or sev_fetched is None:
            # query directly — list with status filter
            accepted_list = get_success_data(api_client.list_finding_actions(
                finding["id"], TEST_USERS["er_manager_headers"], params={"status": "ACCEPTED"}
            ))
            superseded_list = get_success_data(api_client.list_finding_actions(
                finding["id"], TEST_USERS["er_manager_headers"], params={"status": "SUPERSEDED"}
            ))
            accepted_items = accepted_list if isinstance(accepted_list, list) else accepted_list.get("data", [])
            superseded_items = superseded_list if isinstance(superseded_list, list) else superseded_list.get("data", [])
            assert any(a["id"] == severe["id"] for a in accepted_items), (
                f"Severe action {severe['id']} must be ACCEPTED"
            )
            assert any(a["id"] == lenient["id"] for a in superseded_items), (
                f"Lenient action {lenient['id']} must be SUPERSEDED"
            )
        else:
            assert sev_fetched["status"] == "ACCEPTED"
            assert leni_fetched["status"] == "SUPERSEDED"

        # Case moved to PENDING_CLOSURE
        case_after = get_success_data(api_client.get_case(case["id"], TEST_USERS["er_manager_headers"]))
        assert case_after["status"] == "PENDING_CLOSURE"
