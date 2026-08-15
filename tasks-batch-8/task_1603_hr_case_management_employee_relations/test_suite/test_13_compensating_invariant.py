"""Compensating invariant tests (Difficulty rule 9)."""
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
    exclude_evidence,
    run_case_to_closed,
    validate_success,
    get_success_data,
)


class TestCaseloadConservation:
    def test_assign_unassign_pair_conserves_active_case_count(self):
        """PRD §3.2: "A successful assignment writes the investigator into the
        case's `assigned_investigator_id`, recomputes that investigator's
        `active_case_count` (it rises by one), and increments the case's
        `version`."
        PRD §3.2: "Unassigning returns an `ASSIGNED` case to `TRIAGE` ... and
        it clears `assigned_investigator_id`, recomputes the departing
        investigator's `active_case_count` downward by one, and bumps the case
        `version`."

        Design: Difficulty/compensating_invariant/assign_unassign_consumes_and_releases_caseload
        """
        channel = setup_intake_channel(
            channel_code="WEB_PORTAL", display_name="Portal P",
            default_category="COMPENSATION", default_severity="LOW",
            sla_business_days=10,
        )
        reporter = setup_employee()
        subject = setup_employee()
        _, inv1 = setup_investigator(max_active_cases=3)
        case = setup_case(channel["id"], subject["id"],
                          reporter_employee_id=reporter["id"],
                          category="COMPENSATION", severity="LOW")
        # Before: 0
        inv_before = get_success_data(
            api_client.get_investigator(inv1["id"], TEST_USERS["er_manager_headers"])
        )
        assert inv_before["active_case_count"] == 0
        # Assign: 0 -> 1
        assign_case_to(case["id"], inv1["id"], case["version"])
        inv_mid = get_success_data(
            api_client.get_investigator(inv1["id"], TEST_USERS["er_manager_headers"])
        )
        assert inv_mid["active_case_count"] == 1
        # Unassign: 1 -> 0
        case_now = get_success_data(api_client.get_case(case["id"], TEST_USERS["er_manager_headers"]))
        resp = api_client.unassign_case(
            case["id"], {"expected_case_version": case_now["version"]},
            TEST_USERS["er_manager_headers"],
        )
        validate_success(resp, 200)
        inv_after = get_success_data(
            api_client.get_investigator(inv1["id"], TEST_USERS["er_manager_headers"])
        )
        assert inv_after["active_case_count"] == 0, (
            f"active_case_count must return to 0 after unassign; got {inv_after['active_case_count']}"
        )

    def test_unassign_restores_case_to_triage(self):
        """PRD §3.2: "Unassigning returns an `ASSIGNED` case to `TRIAGE`."

        Design: Difficulty/compensating_invariant/assign_unassign_consumes_and_releases_caseload
        """
        channel = setup_intake_channel(
            channel_code="WEB_PORTAL", display_name="Portal P",
            default_category="COMPENSATION", default_severity="LOW",
            sla_business_days=10,
        )
        reporter = setup_employee()
        subject = setup_employee()
        _, inv1 = setup_investigator(max_active_cases=3)
        case = setup_case(channel["id"], subject["id"],
                          reporter_employee_id=reporter["id"],
                          category="COMPENSATION", severity="LOW")
        assign_case_to(case["id"], inv1["id"], case["version"])
        case_now = get_success_data(api_client.get_case(case["id"], TEST_USERS["er_manager_headers"]))
        assert case_now["status"] == "ASSIGNED"
        resp = api_client.unassign_case(
            case["id"], {"expected_case_version": case_now["version"]},
            TEST_USERS["er_manager_headers"],
        )
        after = validate_success(resp, 200)
        assert after["status"] == "TRIAGE"
        assert after["assigned_investigator_id"] is None


class TestCustodySequenceConservation:
    def test_custody_sequence_never_reused(self):
        """PRD §3.3: "The server assigns the chain-of-custody ordinal
        `custody_sequence`: it starts at 1 for the case's first item and
        increments by one per item in creation order, and it is never reused
        or compacted — even after an item is archived, later items never
        inherit earlier numbers."

        Design: Difficulty/compensating_invariant/custody_sequence_space_conserved_through_exclude_archive
        """
        channel = setup_intake_channel(
            channel_code="HOTLINE", display_name="Hotline Q",
            default_category="POLICY_VIOLATION", default_severity="LOW",
            sla_business_days=10,
        )
        reporter = setup_employee()
        subject = setup_employee()
        _, inv1 = setup_investigator()
        _, inv2 = setup_investigator()
        _, inv3 = setup_investigator()
        # Drive a case where we log 2 evidence items, exclude #1, admit #2, then close.
        case = setup_investigating_case(
            channel["id"], subject["id"], inv1["id"],
            reporter_employee_id=reporter["id"],
            category="POLICY_VIOLATION", severity="LOW",
        )
        iv = schedule_interview(case["id"], inv1["id"], subject["id"])
        complete_interview(iv["id"], inv1["id"])
        ev1 = log_evidence(case["id"], inv1["id"], reporter["id"], description="Item one — will be excluded.")
        ev2 = log_evidence(case["id"], inv1["id"], reporter["id"], description="Item two — will be admitted.")
        assert ev1["custody_sequence"] == 1
        assert ev2["custody_sequence"] == 2
        exclude_evidence(ev1["id"], inv1["id"])
        admit_evidence(ev2["id"], inv1["id"], weight=0.65)
        # Findings pipeline
        from test_helpers import (
            create_draft_finding, substantiate_finding, propose_action,
            submit_for_calibration, approve_finding_as, create_closure_notice_payload,
        )
        finding = create_draft_finding(case["id"], inv1["id"])
        substantiate_finding(finding["id"], inv1["id"], outcome="UNSUBSTANTIATED")
        propose_action(finding["id"], inv1["id"],
                        action_type="NO_ACTION", severity_points=0,
                        justification="No action warranted for the custody case outcome.")
        submit_for_calibration(finding["id"], inv1["id"])
        approve_finding_as(finding["id"], inv2["id"])
        approve_finding_as(finding["id"], inv3["id"])
        # Notices
        for recipient_id, role, tier in (
            (subject["id"], "SUBJECT", "TIER_2_LIMITED"),
            (reporter["id"], "REPORTER", "TIER_1_SUMMARY"),
        ):
            n = get_success_data(api_client.create_closure_notice(
                case["id"],
                create_closure_notice_payload(recipient_id, recipient_role=role,
                                                confidentiality_tier=tier),
                TEST_USERS["er_manager_headers"],
            ))
            api_client.send_notice(n["id"], TEST_USERS["er_manager_headers"])
        final_case = get_success_data(api_client.get_case(case["id"], TEST_USERS["er_manager_headers"]))
        api_client.close_case(
            case["id"], {"expected_case_version": final_case["version"]},
            TEST_USERS["er_manager_headers"],
        )
        # Archive the excluded item
        arch_resp = api_client.archive_evidence(ev1["id"], TEST_USERS["er_manager_headers"])
        archived = validate_success(arch_resp, 200)
        assert archived["status"] == "ARCHIVED"
        # Confirm custody_sequence values are unchanged
        ev1_after = get_success_data(api_client.get_evidence_item(ev1["id"], TEST_USERS["er_manager_headers"]))
        ev2_after = get_success_data(api_client.get_evidence_item(ev2["id"], TEST_USERS["er_manager_headers"]))
        assert ev1_after["custody_sequence"] == 1, (
            f"Item 1 custody_sequence must remain 1, got {ev1_after['custody_sequence']}"
        )
        assert ev2_after["custody_sequence"] == 2, (
            f"Item 2 custody_sequence must remain 2 (no compaction), got {ev2_after['custody_sequence']}"
        )

    def test_custody_sequence_total_items_conserved(self):
        """PRD §3.3: "it is never reused or compacted — even after an item is
        archived, later items never inherit earlier numbers."

        Design: Difficulty/compensating_invariant/custody_sequence_space_conserved_through_exclude_archive
        """
        channel = setup_intake_channel(
            channel_code="HOTLINE", display_name="Hotline Q",
            default_category="POLICY_VIOLATION", default_severity="LOW",
            sla_business_days=10,
        )
        reporter = setup_employee()
        subject = setup_employee()
        _, inv1 = setup_investigator()
        _, inv2 = setup_investigator()
        _, inv3 = setup_investigator()
        case = setup_investigating_case(
            channel["id"], subject["id"], inv1["id"],
            reporter_employee_id=reporter["id"],
            category="POLICY_VIOLATION", severity="LOW",
        )
        iv = schedule_interview(case["id"], inv1["id"], subject["id"])
        complete_interview(iv["id"], inv1["id"])
        ev1 = log_evidence(case["id"], inv1["id"], reporter["id"], description="Item one.")
        ev2 = log_evidence(case["id"], inv1["id"], reporter["id"], description="Item two.")
        exclude_evidence(ev1["id"], inv1["id"])
        admit_evidence(ev2["id"], inv1["id"], weight=0.65)
        from test_helpers import (
            create_draft_finding, substantiate_finding, propose_action,
            submit_for_calibration, approve_finding_as, create_closure_notice_payload,
        )
        finding = create_draft_finding(case["id"], inv1["id"])
        substantiate_finding(finding["id"], inv1["id"], outcome="UNSUBSTANTIATED")
        propose_action(finding["id"], inv1["id"],
                        action_type="NO_ACTION", severity_points=0,
                        justification="No action warranted for the custody case outcome.")
        submit_for_calibration(finding["id"], inv1["id"])
        approve_finding_as(finding["id"], inv2["id"])
        approve_finding_as(finding["id"], inv3["id"])
        for recipient_id, role, tier in (
            (subject["id"], "SUBJECT", "TIER_2_LIMITED"),
            (reporter["id"], "REPORTER", "TIER_1_SUMMARY"),
        ):
            n = get_success_data(api_client.create_closure_notice(
                case["id"],
                create_closure_notice_payload(recipient_id, recipient_role=role,
                                                confidentiality_tier=tier),
                TEST_USERS["er_manager_headers"],
            ))
            api_client.send_notice(n["id"], TEST_USERS["er_manager_headers"])
        final_case = get_success_data(api_client.get_case(case["id"], TEST_USERS["er_manager_headers"]))
        api_client.close_case(
            case["id"], {"expected_case_version": final_case["version"]},
            TEST_USERS["er_manager_headers"],
        )
        # Archive ev1 — items for the case should still total 2
        api_client.archive_evidence(ev1["id"], TEST_USERS["er_manager_headers"])
        items_resp = api_client.list_case_evidence(case["id"], TEST_USERS["er_manager_headers"])
        data = get_success_data(items_resp)
        items = data if isinstance(data, list) else data.get("data", [])
        assert len(items) == 2, (
            f"Expected 2 evidence items for the case after archive, got {len(items)}"
        )
