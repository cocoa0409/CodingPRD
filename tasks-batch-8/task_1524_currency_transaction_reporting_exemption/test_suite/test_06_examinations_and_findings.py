"""ExaminationCase + ExaminationFinding lifecycle (PRD §3.8)."""
from test_helpers import (
    ApiErrorId,
    create_exam_case,
    exam_case_in_status,
    get_success_data,
    make_examiner_headers,
    make_officer_headers,
    post_cash_txn,
    set_clock,
    setup_branch_and_customer,
    api_client,
    validate_error,
    NON_EXISTENT_UUID,
)


class TestExamCaseScopeOverlap:
    def test_exam_case_scope_half_open_overlap_per_regulator(self, api):
        """PRD §3.8: "The scope is a half-open interval: it includes the start
        date and excludes the end date, the start must be strictly earlier than
        the end (`ERR_INVALID_REQUEST`), and it must not overlap any other case
        for the same regulator in `OPEN`, `FIELDWORK`, or `FINDINGS_ISSUED`;
        touching boundaries are allowed, so a scope ending exactly where another
        begins does not conflict. An overlap is rejected with
        `ERR_CASE_SCOPE_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/exam_case_scope_half_open_overlap_per_regulator
        """
        k1 = create_exam_case(regulator="FINCEN", case_number="F-1",
                              scope_start_date="2025-01-01", scope_end_date="2025-06-30")
        # Touching boundary: starts exactly at the other's end -> allowed
        k2 = create_exam_case(regulator="FINCEN", case_number="F-2",
                              scope_start_date="2025-06-30", scope_end_date="2025-12-31")
        assert k2["id"]
        # One day of overlap -> rejected
        resp = api_client.create_examination_case(
            {
                "regulator": "FINCEN", "case_number": "F-3",
                "scope_start_date": "2025-06-29", "scope_end_date": "2025-09-30",
            },
            headers=make_examiner_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_CASE_SCOPE_OVERLAP)
        # Same dates, different regulator -> allowed (overlap is per-regulator)
        k4 = create_exam_case(regulator="OCC", case_number="O-1",
                              scope_start_date="2025-03-01", scope_end_date="2025-09-30")
        assert k4["id"]

    def test_exam_case_scope_contained_overlap_rejected(self, api):
        """PRD §3.8: "it must not overlap any other case for the same regulator
        in `OPEN`, `FIELDWORK`, or `FINDINGS_ISSUED`; touching boundaries are
        allowed, so a scope ending exactly where another begins does not
        conflict. An overlap is rejected with `ERR_CASE_SCOPE_OVERLAP`."

        Independent confirmation with a strictly-contained interior overlap.

        Design: Difficulty/resource_temporal_overlap/exam_case_scope_half_open_overlap_per_regulator
        """
        create_exam_case(regulator="FDIC", case_number="FD-1",
                         scope_start_date="2025-01-01", scope_end_date="2025-12-31")
        resp = api_client.create_examination_case(
            {
                "regulator": "FDIC", "case_number": "FD-2",
                "scope_start_date": "2025-03-01", "scope_end_date": "2025-06-01",
            },
            headers=make_examiner_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_CASE_SCOPE_OVERLAP)


class TestExamCaseLifecycle:
    def test_exam_case_reopen_fieldwork_cycle_and_close_guard(self, api):
        """PRD §3.8: "beginning fieldwork moves `OPEN → FIELDWORK`; issuing
        findings moves `FIELDWORK → FINDINGS_ISSUED`; reopening fieldwork cycles
        `FINDINGS_ISSUED → FIELDWORK`; and closing moves `FINDINGS_ISSUED →
        CLOSED`, the terminal state."
        PRD §2.10 step 6: "the requested action is a valid transition from the
        record's current status (else `ERR_INVALID_STATE_TRANSITION`)".

        Design: Corner/state_machines/exam_case_reopen_fieldwork_cycle_and_close_guard
        """
        case = create_exam_case(regulator="FINCEN", case_number="CASE-300",
                                scope_start_date="2025-01-01", scope_end_date="2026-01-01")
        assert case["status"] == "OPEN"
        get_success_data(api_client.begin_fieldwork(case["id"], headers=make_examiner_headers()))
        # Close from FIELDWORK (not FINDINGS_ISSUED) is rejected
        r1 = api_client.close_examination_case(case["id"], headers=make_examiner_headers())
        validate_error(r1, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        get_success_data(api_client.issue_findings(case["id"], headers=make_examiner_headers()))
        back = get_success_data(api_client.reopen_fieldwork(case["id"], headers=make_examiner_headers()))
        assert back["status"] == "FIELDWORK"
        again = get_success_data(api_client.issue_findings(case["id"], headers=make_examiner_headers()))
        assert again["status"] == "FINDINGS_ISSUED"


class TestFindingLifecycle:
    def test_finding_remediation_revert_loop(self, api):
        """PRD §3.8: "a `BSAOfficer` remediates an `OPEN` finding, supplying a
        `remediation_note` that is recorded on the finding, moving it `OPEN →
        REMEDIATED`—but only while the parent case is in `FIELDWORK` or
        `FINDINGS_ISSUED`. A finding in `REMEDIATED` then awaits examiner
        verdict: the `Examiner` either verifies the remediation, moving the
        finding `REMEDIATED → VERIFIED` (the terminal state), or rejects it,
        moving the finding `REMEDIATED → OPEN` and replacing the
        `remediation_note` with the supplied input `note`."

        Design: Difficulty/non_linear_state_machine/finding_remediation_revert_loop
        """
        branch, customer = setup_branch_and_customer()
        txn = post_cash_txn(customer["id"], branch["id"], amount_cents=500_000,
                            occurred_at="2026-08-01T08:00:00Z")
        bundle = exam_case_in_status(
            "FIELDWORK", findings=1, finding_target=("CASH_TRANSACTION", txn["id"]),
        )
        finding_id = bundle["findings"][0]["id"]
        r = get_success_data(api_client.remediate_finding(
            finding_id, {"remediation_note": "teller retrained"},
            headers=make_officer_headers("officer-y"),
        ))
        assert r["status"] == "REMEDIATED"
        r = get_success_data(api_client.reject_remediation(
            finding_id, {"note": "insufficient — no evidence of retraining"},
            headers=make_examiner_headers(),
        ))
        assert r["status"] == "OPEN"
        r = get_success_data(api_client.remediate_finding(
            finding_id, {"remediation_note": "retraining certificates attached"},
            headers=make_officer_headers("officer-y"),
        ))
        assert r["status"] == "REMEDIATED"
        r = get_success_data(api_client.verify_finding(finding_id, headers=make_examiner_headers()))
        assert r["status"] == "VERIFIED"
        final = get_success_data(api_client.get_examination_finding(
            finding_id, headers=make_examiner_headers(),
        ))
        assert final["remediation_note"] == "retraining certificates attached"

    def test_finding_remediation_revert_loop_records_rejection_note(self, api):
        """PRD §3.8: "the `Examiner` either verifies the remediation, moving the
        finding `REMEDIATED → VERIFIED` (the terminal state), or rejects it,
        moving the finding `REMEDIATED → OPEN` and replacing the
        `remediation_note` with the supplied input `note`."

        Independent confirmation: rejection replaces the recorded note.

        Design: Difficulty/non_linear_state_machine/finding_remediation_revert_loop
        """
        branch, customer = setup_branch_and_customer()
        txn = post_cash_txn(customer["id"], branch["id"], amount_cents=300_000,
                            occurred_at="2026-08-01T08:00:00Z")
        bundle = exam_case_in_status(
            "FIELDWORK", findings=1, finding_target=("CASH_TRANSACTION", txn["id"]),
        )
        finding_id = bundle["findings"][0]["id"]
        get_success_data(api_client.remediate_finding(
            finding_id, {"remediation_note": "first attempt"},
            headers=make_officer_headers("officer-y"),
        ))
        rejected = get_success_data(api_client.reject_remediation(
            finding_id, {"note": "needs more evidence"},
            headers=make_examiner_headers(),
        ))
        assert rejected["status"] == "OPEN"
        assert rejected["remediation_note"] == "needs more evidence"


class TestExamCaseCloseGuardedByFindings:
    def test_exam_case_close_requires_all_findings_verified(self, api):
        """PRD §3.8: "Closing is guarded: every finding recorded against the case
        must be in `VERIFIED` status, otherwise the close is rejected with
        `ERR_EXAMINATION_HAS_OPEN_FINDINGS`."

        Design: Difficulty/cross_entity_state_dependency/exam_case_close_requires_all_findings_verified
        """
        branch, customer = setup_branch_and_customer()
        txn = post_cash_txn(customer["id"], branch["id"], amount_cents=500_000,
                            occurred_at="2026-08-01T08:00:00Z")
        bundle = exam_case_in_status(
            "FINDINGS_ISSUED", findings=1, finding_target=("CASH_TRANSACTION", txn["id"]),
        )
        case = bundle["case"]
        finding_id = bundle["findings"][0]["id"]
        # Close blocked while finding is OPEN
        resp = api_client.close_examination_case(case["id"], headers=make_examiner_headers())
        validate_error(resp, ApiErrorId.ERR_EXAMINATION_HAS_OPEN_FINDINGS)
        # Remediate + verify the finding, then close succeeds
        get_success_data(api_client.remediate_finding(
            finding_id, {"remediation_note": "procedure updated"},
            headers=make_officer_headers("officer-y"),
        ))
        get_success_data(api_client.verify_finding(finding_id, headers=make_examiner_headers()))
        closed = get_success_data(api_client.close_examination_case(
            case["id"], headers=make_examiner_headers(),
        ))
        assert closed["status"] == "CLOSED"

    def test_exam_case_close_blocked_by_remediated_but_unverified_finding(self, api):
        """PRD §3.8: "Closing is guarded: every finding recorded against the case
        must be in `VERIFIED` status, otherwise the close is rejected with
        `ERR_EXAMINATION_HAS_OPEN_FINDINGS`."

        Independent confirmation: a finding in REMEDIATED (not yet VERIFIED)
        also blocks the close.

        Design: Difficulty/cross_entity_state_dependency/exam_case_close_requires_all_findings_verified
        """
        branch, customer = setup_branch_and_customer()
        txn = post_cash_txn(customer["id"], branch["id"], amount_cents=400_000,
                            occurred_at="2026-08-01T08:00:00Z")
        bundle = exam_case_in_status(
            "FINDINGS_ISSUED", findings=1, finding_target=("CASH_TRANSACTION", txn["id"]),
        )
        case = bundle["case"]
        finding_id = bundle["findings"][0]["id"]
        get_success_data(api_client.remediate_finding(
            finding_id, {"remediation_note": "in progress"},
            headers=make_officer_headers("officer-y"),
        ))
        resp = api_client.close_examination_case(case["id"], headers=make_examiner_headers())
        validate_error(resp, ApiErrorId.ERR_EXAMINATION_HAS_OPEN_FINDINGS)


class TestFindingTargetResolution:
    def test_finding_target_must_resolve_per_type(self, api):
        """PRD §3.8: "The `target_id` must resolve against the entity type named
        by `target_type`; an unresolvable target is rejected with
        `ERR_FINDING_TARGET_NOT_FOUND`."

        Design: Corner/validations/finding_target_must_resolve_per_type
        """
        bundle = exam_case_in_status("FIELDWORK")
        case = bundle["case"]
        resp = api_client.create_finding(
            case["id"],
            {
                "severity": "OBSERVATION", "target_type": "CTR",
                "target_id": NON_EXISTENT_UUID, "description": "ghost ctr",
            },
            headers=make_examiner_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_FINDING_TARGET_NOT_FOUND)
