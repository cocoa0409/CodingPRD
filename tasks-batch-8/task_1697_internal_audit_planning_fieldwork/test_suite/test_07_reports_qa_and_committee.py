"""Report issuance and its freeze cascade, QA reviews and the FAIL regression
cascade, and committee-pack snapshot pinning (PRD §3.8, §3.9)."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_audit_report,
    assert_committee_pack,
    assert_qa_review,
    complete_qa_review,
    create_active_rating_config,
    create_approved_report,
    create_audit_report_payload,
    create_auditor,
    create_committee_pack_payload,
    create_finding_payload,
    create_issued_finding,
    create_qa_review_payload,
    get_plan,
    get_success_data,
    is_iso8601_timestamp,
    make_field_auditor_headers,
    make_manager_headers,
    make_qa_headers,
    respond_to_finding,
    set_clock,
    setup_action_plan,
    setup_agreed_finding,
    setup_engagement_in_fieldwork,
    setup_engagement_in_reporting,
    setup_qa_review,
    validate_error,
    validate_success,
)


class TestReportApprovalCycle:
    def test_report_approval_return_cycle(self, api, cae_headers):
        """PRD §3.8: "The manager submits the draft, moving it to
        `PENDING_APPROVAL` (from any other state, `ERR_REPORT_INVALID_STATE`).
        The `ChiefAuditExecutive` then approves it to `APPROVED`, or returns it
        — a return moves the report from `PENDING_APPROVAL` back to `DRAFT` for
        rework, and both decisions require `PENDING_APPROVAL` as the from-state,
        else `ERR_REPORT_INVALID_STATE`."

        Design: Corner/state_machines/report_approval_return_cycle
        """
        ctx = setup_engagement_in_reporting(entity_name="E", budget_hours=100)
        mgr_h = make_manager_headers(ctx["mgr"]["id"])
        rep = get_success_data(api.create_audit_report(
            create_audit_report_payload(ctx["engagement"]["id"], title="Draft"), mgr_h,
        ))
        assert rep["status"] == "DRAFT"

        # Approving a DRAFT report directly is rejected.
        early = api.approve_audit_report(rep["id"], cae_headers)
        validate_error(early, ApiErrorId.ERR_REPORT_INVALID_STATE, expected_status=409)

        # The revision loop DRAFT -> PENDING_APPROVAL -> DRAFT -> ... -> APPROVED.
        get_success_data(api.submit_audit_report(rep["id"], mgr_h))
        returned = get_success_data(api.return_audit_report(rep["id"], cae_headers))
        assert returned["status"] == "DRAFT"
        get_success_data(api.submit_audit_report(rep["id"], mgr_h))
        approved = get_success_data(api.approve_audit_report(rep["id"], cae_headers))
        assert approved["status"] == "APPROVED"
        assert_audit_report(approved)


class TestPostIssuanceFreeze:
    def test_post_issuance_freeze_locks_and_repeat_issue(self, api, cae_headers):
        """PRD §3.8: "every workpaper of the engagement is frozen: `locked` is
        set to true, and from that moment any submit, sign-off, return, or
        revise attempt on those workpapers is rejected with
        `ERR_WORKPAPER_LOCKED` — a tamper-evident freeze of the evidence base
        underlying the issued report."
        PRD §3.8: "no other report of the same engagement may already be
        `ISSUED` or `DISTRIBUTED` (else `ERR_REPORT_ALREADY_ISSUED`)"
        PRD §3.6: "once the report is issued, the finding roster freezes and new
        findings are rejected with `ERR_REPORT_ALREADY_ISSUED`."
        PRD §3.8: "every finding of the engagement in `AGREED` or `ESCALATED`
        transitions to `FINAL` with its `finalized_at` stamped, and the
        engagement's `open_finding_count` is recomputed."

        Design: Corner/state_machines/post_issuance_freeze_locks_and_repeat_issue
        """
        ctx = setup_engagement_in_fieldwork(entity_name="E", budget_hours=100)
        create_active_rating_config()
        mgr, mgr2 = ctx["mgr"], create_auditor(full_name="Mike Mgr2", grade="MANAGER")
        mgr_h = make_manager_headers(mgr["id"])
        mgr2_h = make_manager_headers(mgr2["id"])
        staff_h = make_field_auditor_headers(ctx["staff"]["id"])

        wp = get_success_data(api.create_workpaper(
            {"engagement_id": ctx["engagement"]["id"], "reference": "A-1",
             "title": "WP A", "hours_worked": 10},
            staff_h,
        ))
        get_success_data(api.submit_workpaper(wp["id"], staff_h))
        get_success_data(api.sign_off_workpaper(wp["id"], mgr_h))

        finding = create_issued_finding(ctx, title="F", likelihood=4, impact=5, issuer=mgr2)
        resp = respond_to_finding(finding["id"])
        get_success_data(api.accept_management_response(resp["id"], mgr2_h))

        get_success_data(api.begin_reporting(ctx["engagement"]["id"], mgr_h))
        rep = get_success_data(api.create_audit_report(
            create_audit_report_payload(ctx["engagement"]["id"], title="R1"), mgr_h,
        ))
        get_success_data(api.submit_audit_report(rep["id"], mgr_h))
        get_success_data(api.approve_audit_report(rep["id"], cae_headers))

        issued = get_success_data(api.issue_audit_report(rep["id"], cae_headers))
        assert issued["status"] == "ISSUED"
        assert is_iso8601_timestamp(issued["issued_at"])

        # Issuance cascade: finding FINAL, workpaper frozen.
        finding_after = get_success_data(api.get_finding(finding["id"], mgr_h))
        assert finding_after["status"] == "FINAL"
        assert is_iso8601_timestamp(finding_after["finalized_at"])
        wp_after = get_success_data(api.get_workpaper(wp["id"], mgr_h))
        assert wp_after["locked"] is True

        locked = api.return_workpaper(wp["id"], {"note": "too late"}, mgr2_h)
        validate_error(locked, ApiErrorId.ERR_WORKPAPER_LOCKED, expected_status=409)

        # The finding roster freezes once the report is issued.
        late_finding = api.create_finding(
            create_finding_payload(ctx["engagement"]["id"], title="late finding",
                                   likelihood=2, impact=2),
            staff_h,
        )
        validate_error(late_finding, ApiErrorId.ERR_REPORT_ALREADY_ISSUED, expected_status=409)

        # A second issue on a fresh report of the same engagement is rejected.
        rep2 = get_success_data(api.create_audit_report(
            create_audit_report_payload(ctx["engagement"]["id"], title="R2"), mgr_h,
        ))
        get_success_data(api.submit_audit_report(rep2["id"], mgr_h))
        get_success_data(api.approve_audit_report(rep2["id"], cae_headers))
        reissue = api.issue_audit_report(rep2["id"], cae_headers)
        validate_error(reissue, ApiErrorId.ERR_REPORT_ALREADY_ISSUED, expected_status=409)

        eng_after = get_success_data(api.get_engagement(ctx["engagement"]["id"], mgr_h))
        assert eng_after["open_finding_count"] == 0


class TestFullLifecycle:
    def test_full_lifecycle_close_bubble_up_and_plan_close(self, api, cae_headers, committee_headers, owner_headers):
        """PRD §3.8: "every finding of the engagement must be resolved into
        `AGREED`, `ESCALATED`, or `FINAL` — any finding still in an earlier
        status blocks issuance with `ERR_FINDINGS_NOT_RESOLVED`."
        PRD §3.8: "Closing moves the engagement from `REPORTING` to `CLOSED` —
        any other from-state fails with `ERR_ENGAGEMENT_INVALID_STATE` — and
        requires two cross-entity conditions: an audit report of the engagement
        must exist in `ISSUED` or `DISTRIBUTED` status (else
        `ERR_REPORT_NOT_ISSUED`), and no QA review of the engagement may remain
        in `SCHEDULED` or `IN_PROGRESS` (else `ERR_QA_REVIEW_OPEN`)."
        PRD §3.8: "Distributing requires the report to be `ISSUED` (else
        `ERR_REPORT_INVALID_STATE`) and requires the request's
        `distribution_list` to be non-empty; an empty recipient list fails with
        `ERR_DISTRIBUTION_LIST_EMPTY`."
        PRD §3.8: "Closure bubbles up to the audit universe: the entity's
        `last_audit_completed_at` is set to the logical clock now"

        Design: Corner/state_machines/full_lifecycle_close_bubble_up_and_plan_close
        """
        set_clock()  # 2026-01-15
        ctx = setup_engagement_in_fieldwork(entity_name="E", budget_hours=200,
                                            lead_hours=60, staff_hours=60)
        create_active_rating_config()
        mgr, staff = ctx["mgr"], ctx["staff"]
        mgr_h = make_manager_headers(mgr["id"])
        mgr2 = create_auditor(full_name="Mike Mgr2", grade="MANAGER")
        mgr2_h = make_manager_headers(mgr2["id"])
        staff_h = make_field_auditor_headers(staff["id"])
        qa1 = create_auditor(full_name="Quinn QA", grade="MANAGER")

        wp = get_success_data(api.create_workpaper(
            {"engagement_id": ctx["engagement"]["id"], "reference": "A-1",
             "title": "WP A", "hours_worked": 10},
            staff_h,
        ))
        get_success_data(api.submit_workpaper(wp["id"], staff_h))
        get_success_data(api.sign_off_workpaper(wp["id"], mgr_h))

        # f1 AGREED; f2 left DRAFT.
        f1 = create_issued_finding(ctx, title="F1", likelihood=4, impact=5, issuer=mgr2)
        resp1 = respond_to_finding(f1["id"])
        get_success_data(api.accept_management_response(resp1["id"], mgr2_h))
        f2 = get_success_data(api.create_finding(
            create_finding_payload(ctx["engagement"]["id"], title="F2", likelihood=2, impact=3),
            staff_h,
        ))

        get_success_data(api.begin_reporting(ctx["engagement"]["id"], mgr_h))
        rep = get_success_data(api.create_audit_report(
            create_audit_report_payload(ctx["engagement"]["id"], title="R",
                                        overall_conclusion="NEEDS_IMPROVEMENT"),
            mgr_h,
        ))
        get_success_data(api.submit_audit_report(rep["id"], mgr_h))
        get_success_data(api.approve_audit_report(rep["id"], cae_headers))

        # Issuance blocked while f2 is still DRAFT.
        blocked = api.issue_audit_report(rep["id"], cae_headers)
        validate_error(blocked, ApiErrorId.ERR_FINDINGS_NOT_RESOLVED, expected_status=422)

        # Resolve f2 through the negotiation pipeline.
        get_success_data(api.issue_finding(f2["id"], mgr2_h))
        resp2 = respond_to_finding(f2["id"], proposed_due_date="2026-07-01T00:00:00Z")
        get_success_data(api.accept_management_response(resp2["id"], mgr2_h))

        # Close before issuance is rejected.
        early_close = api.close_engagement(ctx["engagement"]["id"], mgr_h)
        validate_error(early_close, ApiErrorId.ERR_REPORT_NOT_ISSUED, expected_status=422)

        get_success_data(api.issue_audit_report(rep["id"], cae_headers))

        # Distribution requires a non-empty recipient list.
        empty = api.distribute_audit_report(rep["id"], {"distribution_list": []}, cae_headers)
        validate_error(empty, ApiErrorId.ERR_DISTRIBUTION_LIST_EMPTY, expected_status=422)
        distributed = get_success_data(api.distribute_audit_report(
            rep["id"],
            {"distribution_list": ["audit-committee@example.com", "cfo@example.com"]},
            cae_headers,
        ))
        assert distributed["status"] == "DISTRIBUTED"
        assert distributed["distribution_list"] == [
            "audit-committee@example.com", "cfo@example.com",
        ]
        assert is_iso8601_timestamp(distributed["distributed_at"])

        # Close is blocked while a QA review is in flight.
        qa = get_success_data(api.create_qa_review(
            create_qa_review_payload(ctx["engagement"]["id"], scope="INTERNAL"), cae_headers,
        ))
        get_success_data(api.begin_qa_review(qa["id"], make_qa_headers(qa1["id"])))
        qa_open = api.close_engagement(ctx["engagement"]["id"], mgr_h)
        validate_error(qa_open, ApiErrorId.ERR_QA_REVIEW_OPEN, expected_status=422)

        # QA passes; close succeeds and bubbles the completion date up.
        completed = complete_qa_review(qa["id"], qa1, doc=4, fieldwork=5, reporting=4,
                                       independence=5)
        assert completed["rating"] == "PASS"
        assert completed["overall_score"] == pytest.approx(4.5)
        closed = get_success_data(api.close_engagement(ctx["engagement"]["id"], mgr_h))
        assert closed["status"] == "CLOSED"

        entity_after = get_success_data(api.get_auditable_entity(ctx["entity"]["id"], mgr_h))
        assert entity_after["last_audit_completed_at"] == "2026-01-15T00:00:00Z", (
            "Closure bubbles the logical clock onto the entity"
        )

        plan_closed = get_success_data(api.close_audit_plan(ctx["plan"]["id"], cae_headers))
        assert plan_closed["status"] == "CLOSED"

        assert get_success_data(api.get_finding(f1["id"], mgr_h))["status"] == "FINAL"
        assert get_success_data(api.get_finding(f2["id"], mgr_h))["status"] == "FINAL"


class TestQAReviewGuards:
    def test_qa_assessor_independence_and_ownership(self, api, cae_headers):
        """PRD §3.9: "Independence is enforced structurally: the caller's
        `X-User-ID`, interpreted as an `Auditor` id, must not hold an `ACTIVE`
        assignment on the engagement under review; an assigned assessor is
        rejected with `ERR_QA_ASSESSOR_ASSIGNED`."
        PRD §3.9: "Completion is the assessor's own action: only the caller
        whose `X-User-ID` matches `assessor_auditor_id` may complete the review,
        and anyone else is rejected with `ERR_NOT_QA_ASSESSOR`; the review must
        be `IN_PROGRESS` (else `ERR_QA_REVIEW_INVALID_STATE`)."
        PRD §3.9: "It is a `PASS` when every dimension score is at least 4 and
        the overall score is at least 4.0."

        Design: Corner/state_machines/qa_assessor_independence_and_ownership
        """
        ctx = setup_engagement_in_reporting(entity_name="E", budget_hours=100)
        qa1 = create_auditor(full_name="Quinn QA1", grade="MANAGER")
        qa2 = create_auditor(full_name="Quentin QA2", grade="DIRECTOR")
        qa = get_success_data(api.create_qa_review(
            create_qa_review_payload(ctx["engagement"]["id"], scope="INTERNAL"), cae_headers,
        ))

        # Completion before begin is an invalid-state error.
        early = api.complete_qa_review(qa["id"],
                                       {"doc_quality_score": 4, "fieldwork_quality_score": 4,
                                        "reporting_quality_score": 4, "independence_score": 4},
                                       make_qa_headers(qa1["id"]))
        validate_error(early, ApiErrorId.ERR_QA_REVIEW_INVALID_STATE, expected_status=409)

        # The engagement's LEAD cannot assess it (independence).
        assigned = api.begin_qa_review(qa["id"], make_qa_headers(ctx["mgr"]["id"]))
        validate_error(assigned, ApiErrorId.ERR_QA_ASSESSOR_ASSIGNED, expected_status=403)

        begun = get_success_data(api.begin_qa_review(qa["id"], make_qa_headers(qa1["id"])))
        assert begun["status"] == "IN_PROGRESS"
        assert begun["assessor_auditor_id"] == qa1["id"]

        # Only the assigned assessor may complete the review.
        wrong = api.complete_qa_review(qa["id"],
                                       {"doc_quality_score": 4, "fieldwork_quality_score": 5,
                                        "reporting_quality_score": 4, "independence_score": 5},
                                       make_qa_headers(qa2["id"]))
        validate_error(wrong, ApiErrorId.ERR_NOT_QA_ASSESSOR, expected_status=403)

        completed = complete_qa_review(qa["id"], qa1, doc=4, fieldwork=5, reporting=4,
                                       independence=5)
        assert completed["status"] == "COMPLETED"
        assert completed["overall_score"] == pytest.approx(4.5)
        assert completed["rating"] == "PASS"
        assert_qa_review(completed)

        # PASS causes no regression.
        mgr_h = make_manager_headers(ctx["mgr"]["id"])
        eng_after = get_success_data(api.get_engagement(ctx["engagement"]["id"], mgr_h))
        assert eng_after["status"] == "REPORTING"
        assert eng_after["qa_regression_count"] == 0

    def test_qa_rating_boundary_and_open_uniqueness(self, api, cae_headers):
        """PRD §3.9: "Anything in between — no dimension at 2 or below, overall
        at least 3.0, but the `PASS` bar not met — is `PASS_WITH_DEFICIENCIES`.
        Note the boundaries exactly: an overall score of exactly 3.0 escapes the
        `FAIL` gate, while `PASS` strictly requires 4.0 or better overall."
        PRD §3.9: "requires that no other review of the same engagement is
        currently `SCHEDULED` or `IN_PROGRESS`, else `ERR_QA_REVIEW_ALREADY_OPEN`."

        Design: Corner/calculations/qa_rating_boundary_and_open_uniqueness
        """
        ctx = setup_engagement_in_reporting(entity_name="E", budget_hours=100)
        qa1 = create_auditor(full_name="Quinn QA", grade="MANAGER")
        qa = get_success_data(api.create_qa_review(
            create_qa_review_payload(ctx["engagement"]["id"], scope="INTERNAL"), cae_headers,
        ))

        # A second review while the first is SCHEDULED is rejected.
        second = api.create_qa_review(
            create_qa_review_payload(ctx["engagement"]["id"], scope="EXTERNAL"), cae_headers,
        )
        validate_error(second, ApiErrorId.ERR_QA_REVIEW_ALREADY_OPEN, expected_status=409)

        get_success_data(api.begin_qa_review(qa["id"], make_qa_headers(qa1["id"])))
        # All dimensions 3: overall exactly 3.0 — escapes FAIL, below PASS.
        completed = complete_qa_review(qa["id"], qa1, doc=3, fieldwork=3, reporting=3,
                                       independence=3)
        assert completed["overall_score"] == pytest.approx(3.0)
        assert completed["rating"] == "PASS_WITH_DEFICIENCIES"

        # PASS_WITH_DEFICIENCIES causes no regression.
        mgr_h = make_manager_headers(ctx["mgr"]["id"])
        eng_after = get_success_data(api.get_engagement(ctx["engagement"]["id"], mgr_h))
        assert eng_after["status"] == "REPORTING"
        assert eng_after["qa_regression_count"] == 0


class TestQAFailCascade:
    def test_qa_fail_regression_four_hop_cascade(self, api, cae_headers, committee_headers):
        """PRD §3.9: "A failed review of an engagement still in `REPORTING`
        triggers the deepest cascade in the system. The engagement regresses
        from `REPORTING` back to `FIELDWORK` and its `qa_regression_count`
        increments by one. The regression reopens the evidence base: every
        workpaper of the engagement that was `SIGNED_OFF` transitions to
        `RETURNED`, with its `review_note` set to the marker QA_REOPEN and its
        `signed_off_at` cleared — workpapers in `DRAFT` or already `RETURNED`
        are untouched, as are any merely `SUBMITTED` — and the engagement's
        `signed_off_workpaper_count` and `actual_hours` are recomputed. Because
        issuance requires clean workpapers, the report pipeline unwinds too: any
        report of the engagement sitting in `PENDING_APPROVAL` automatically
        returns to `DRAFT`. And because the numbers a committee would see have
        now changed underneath a pack still being drafted, every committee pack
        of the engagement's plan that is still in `DRAFT` has its
        `is_stale_snapshot` flag set to true."

        Design: Difficulty/transitive_cascade/qa_fail_regression_four_hop_cascade
        """
        ctx = setup_engagement_in_reporting(entity_name="Entity Q", budget_hours=200,
                                            num_workpapers=2)
        mgr = ctx["mgr"]
        mgr_h = make_manager_headers(mgr["id"])
        qa1 = create_auditor(full_name="Quinn QA", grade="MANAGER")
        wp_a, wp_b = ctx["workpapers"]
        assert wp_a["status"] == "SIGNED_OFF"
        assert wp_b["status"] == "SIGNED_OFF"

        # Report in PENDING_APPROVAL and a DRAFT pack exist before the QA fail.
        rep = get_success_data(api.create_audit_report(
            create_audit_report_payload(ctx["engagement"]["id"], title="Draft Report"), mgr_h,
        ))
        get_success_data(api.submit_audit_report(rep["id"], mgr_h))
        pack = get_success_data(api.create_committee_pack(
            create_committee_pack_payload(ctx["plan"]["id"], title="Q1 Pack"), cae_headers,
        ))
        qa = get_success_data(api.create_qa_review(
            create_qa_review_payload(ctx["engagement"]["id"], scope="EXTERNAL"), cae_headers,
        ))
        get_success_data(api.begin_qa_review(qa["id"], make_qa_headers(qa1["id"])))

        # One dimension at 2 -> FAIL (min dimension <= 2).
        completed = complete_qa_review(qa["id"], qa1, doc=2, fieldwork=4, reporting=4,
                                       independence=4)
        assert completed["status"] == "COMPLETED"
        assert completed["overall_score"] == pytest.approx(3.5)
        assert completed["rating"] == "FAIL"

        # Cascade L1: engagement regresses REPORTING -> FIELDWORK.
        eng_after = get_success_data(api.get_engagement(ctx["engagement"]["id"], mgr_h))
        assert eng_after["status"] == "FIELDWORK"
        assert eng_after["qa_regression_count"] == 1

        # Cascade L2: both signed workpapers are reopened.
        for wp in (wp_a, wp_b):
            wp_after = get_success_data(api.get_workpaper(wp["id"], mgr_h))
            assert wp_after["status"] == "RETURNED"
            assert wp_after["review_note"] == "QA_REOPEN"
            assert wp_after["signed_off_at"] is None
        assert eng_after["signed_off_workpaper_count"] == 0
        assert eng_after["actual_hours"] == pytest.approx(0.0)

        # Cascade L3: the pending report auto-returns to DRAFT.
        rep_after = get_success_data(api.get_audit_report(rep["id"], mgr_h))
        assert rep_after["status"] == "DRAFT"

        # Cascade L4: the DRAFT pack is flagged stale.
        pack_after = get_success_data(api.get_committee_pack(pack["id"], cae_headers))
        assert pack_after["is_stale_snapshot"] is True
        assert pack_after["status"] == "DRAFT"

    def test_qa_fail_reopens_all_signed_workpapers(self, api, cae_headers):
        """PRD §3.9: "The regression reopens the evidence base: every workpaper
        of the engagement that was `SIGNED_OFF` transitions to `RETURNED`, with
        its `review_note` set to the marker QA_REOPEN and its `signed_off_at`
        cleared"
        PRD §3.9: "The engagement regresses from `REPORTING` back to `FIELDWORK`
        and its `qa_regression_count` increments by one."

        Design: Difficulty/transitive_cascade/qa_fail_regression_four_hop_cascade
        """
        # Two signed workpapers (10h and 12h) before reporting.
        ctx = setup_engagement_in_reporting(entity_name="Entity Q2", budget_hours=200,
                                            num_workpapers=2)
        mgr_h = make_manager_headers(ctx["mgr"]["id"])
        qa1 = create_auditor(full_name="Quinn QA", grade="MANAGER")
        qa = get_success_data(api.create_qa_review(
            create_qa_review_payload(ctx["engagement"]["id"], scope="INTERNAL"), cae_headers,
        ))
        get_success_data(api.begin_qa_review(qa["id"], make_qa_headers(qa1["id"])))

        completed = complete_qa_review(qa["id"], qa1, doc=2, fieldwork=4, reporting=4,
                                       independence=4)
        assert completed["rating"] == "FAIL"

        eng_after = get_success_data(api.get_engagement(ctx["engagement"]["id"], mgr_h))
        assert eng_after["status"] == "FIELDWORK"
        assert eng_after["qa_regression_count"] == 1
        assert eng_after["signed_off_workpaper_count"] == 0
        assert eng_after["actual_hours"] == pytest.approx(0.0)
        for wp in ctx["workpapers"]:
            wp_after = get_success_data(api.get_workpaper(wp["id"], mgr_h))
            assert wp_after["status"] == "RETURNED"
            assert wp_after["review_note"] == "QA_REOPEN"


class TestCommitteePackSnapshot:
    def test_committee_snapshot_pinned_after_finalize(self, api, cae_headers, committee_headers, owner_headers):
        """PRD §3.9: "Finalizing the pack — requiring it to be in `DRAFT`, else
        `ERR_PACK_INVALID_STATE` — computes and permanently pins four snapshot
        aggregates, stamps `finalized_at`, and moves the pack to `FINALIZED`.
        The snapshot is never recomputed afterwards, whatever happens to the
        underlying data."
        PRD §3.9: "Presentation is the committee's act: the `AuditCommittee`
        marks a `FINALIZED` pack as `PRESENTED` — any other from-state fails
        with `ERR_PACK_INVALID_STATE`"
        PRD §3.9: "Third and fourth, `snapshot_critical_findings` and
        `snapshot_high_findings` count the plan's findings whose status is
        `AGREED`, `ESCALATED`, or `FINAL` and whose severity is `CRITICAL` or
        `HIGH` respectively."

        Design: Corner/calculations/committee_snapshot_pinned_after_finalize
        """
        ctx = setup_action_plan(due_date="2026-06-01T00:00:00Z", entity_name="E",
                                likelihood=4, impact=5)
        # Finding (L=4, I=5 -> composite 20 -> CRITICAL under defaults) is AGREED.
        assert ctx["finding"]["severity"] == "CRITICAL"
        ap = ctx["action_plan"]
        mgr_h = make_manager_headers(ctx["mgr"]["id"])

        # Advance the clock so the action plan is 14 days overdue.
        set_clock("2026-06-15T00:00:00Z")
        pack = get_success_data(api.create_committee_pack(
            create_committee_pack_payload(
                ctx["plan"]["id"], meeting_date="2026-06-20T00:00:00Z", title="Q2 Pack",
            ),
            cae_headers,
        ))

        # Present before finalize is rejected.
        early = api.present_committee_pack(pack["id"], committee_headers)
        validate_error(early, ApiErrorId.ERR_PACK_INVALID_STATE, expected_status=409)

        finalized = get_success_data(api.finalize_committee_pack(pack["id"], cae_headers))
        assert finalized["status"] == "FINALIZED"
        # No CLOSED engagements -> completion 0.0; one overdue plan -> 1;
        # one AGREED CRITICAL finding -> critical 1, high 0.
        assert finalized["snapshot_plan_completion_pct"] == pytest.approx(0.0)
        assert finalized["snapshot_overdue_action_count"] == 1
        assert finalized["snapshot_critical_findings"] == 1
        assert finalized["snapshot_high_findings"] == 0
        assert is_iso8601_timestamp(finalized["finalized_at"])
        assert_committee_pack(finalized)

        # Later state changes (plan validated, no longer overdue) do not alter
        # the pinned snapshot.
        get_success_data(api.start_action_plan(ap["id"], owner_headers))
        get_success_data(api.submit_action_plan_validation(ap["id"], owner_headers))
        get_success_data(api.validate_action_plan(ap["id"], mgr_h))
        after = get_success_data(api.get_committee_pack(pack["id"], cae_headers))
        assert after["snapshot_overdue_action_count"] == 1, "Pinned at finalize"
        assert after["is_stale_snapshot"] is False

        presented = get_success_data(api.present_committee_pack(pack["id"], committee_headers))
        assert presented["status"] == "PRESENTED"
