"""Notices and audit cases: the overdue sweep, late response, notice
lifecycle gating audit close, the negotiation loop, both close outcomes, and
the half-open exam-period overlap rule.
"""
from test_helpers import (
    ApiErrorId,
    create_audit_record,
    create_notice_record,
    create_us_fed_jurisdiction,
    set_logical_clock,
    setup_open_year_with_jurisdiction,
    validate_error,
    validate_success,
)


class TestNoticeSweep:
    def test_notice_auto_overdue_and_late_response(
            self, api, tax_manager_headers, auditor_headers):
        """PRD §2.7: "**Notices**: any notice in `RECEIVED` or `UNDER_REVIEW`
        whose `response_due_on` has passed transitions to `OVERDUE`."
        PRD §3.9: "A late response is permitted: responding from `OVERDUE`
        also moves the notice to `RESPONDED`, and the `OVERDUE` sojourn
        remains visible in `updated_at` history."
        PRD §2.7: "The response reports the new `current_utc` together with
        the lists `late_payment_ids`, `overdue_notice_ids`, and
        `lapsed_position_ids` naming every entity the sweeps transitioned."

        Design: Corner/state_machines/notice_auto_overdue_and_late_response
        """
        set_logical_clock("2026-01-10T00:00:00Z")
        jur = create_us_fed_jurisdiction()
        notice = create_notice_record(jur["id"], received_on="2026-01-10",
                                      response_due_on="2026-02-09")
        assert notice["status"] == "RECEIVED"

        clock_data = set_logical_clock("2026-02-10T00:00:00Z")
        assert notice["id"] in clock_data["overdue_notice_ids"]

        overdue = validate_success(api.get_notice(notice["id"],
                                                  auditor_headers), 200)
        assert overdue["status"] == "OVERDUE"

        responded = validate_success(
            api.respond_to_notice(notice["id"], "records enclosed",
                                  tax_manager_headers), 200)
        assert responded["status"] == "RESPONDED"
        assert responded["response_text"] == "records enclosed"


class TestAuditCloseGate:
    def test_audit_close_blocked_by_unresolved_notice(
            self, api, tax_manager_headers):
        """PRD §3.9: "Every close path requires all notices linked via
        `audit_case_id` to be `RESOLVED`, otherwise
        `ERR_UNRESOLVED_NOTICES`."

        Design: Corner/validations/audit_close_blocked_by_unresolved_notice
        """
        set_logical_clock("2026-01-05T00:00:00Z")
        ty, jur = setup_open_year_with_jurisdiction()
        audit = create_audit_record(ty["id"], jur["id"])
        validate_success(
            api.propose_adjustment(audit["id"], 400000, tax_manager_headers),
            200)
        notice = create_notice_record(
            jur["id"], audit_case_id=audit["id"],
            notice_type="PROPOSED_ADJUSTMENT", received_on="2026-01-10",
            response_due_on="2027-01-10")

        res = api.close_audit(audit["id"], "AGREED", tax_manager_headers,
                              agreed_adjustment_cents=350000)
        validate_error(res, ApiErrorId.ERR_UNRESOLVED_NOTICES,
                       expected_status=422)

        # Walk the notice to RESOLVED, then the close succeeds.
        validate_success(api.assign_notice_review(notice["id"],
                                                  tax_manager_headers), 200)
        validate_success(api.respond_to_notice(notice["id"],
                                               "accepted with revisions",
                                               tax_manager_headers), 200)
        validate_success(api.resolve_notice(notice["id"],
                                            tax_manager_headers), 200)
        closed = validate_success(
            api.close_audit(audit["id"], "AGREED", tax_manager_headers,
                            agreed_adjustment_cents=350000), 200)
        assert closed["status"] == "CLOSED_AGREED"
        assert closed["agreed_adjustment_cents"] == 350000


class TestAuditNegotiationLoop:
    def test_negotiation_loop_revises_proposal_then_closes(
            self, api, tax_manager_headers):
        """PRD §3.9: "Proposing an adjustment attaches
        `proposed_adjustment_cents` (nonnegative) and moves the case to
        `ADJUSTMENT_PROPOSED`; negotiating moves it to `NEGOTIATING`; revising
        the proposal cycles `NEGOTIATING → ADJUSTMENT_PROPOSED` with a revised
        nonnegative `proposed_adjustment_cents` — the negotiation loop."
        PRD §3.9: "Closing takes an `outcome`: `NO_CHANGE` from
        `UNDER_EXAMINATION` lands in `CLOSED_NO_CHANGE`, while `AGREED` from
        `ADJUSTMENT_PROPOSED` or `NEGOTIATING` lands in `CLOSED_AGREED` and
        requires `agreed_adjustment_cents` present and nonnegative, which is
        then recorded."

        Design: Corner/state_machines/audit_negotiation_loop_and_close
        """
        set_logical_clock("2026-01-05T00:00:00Z")
        ty, jur = setup_open_year_with_jurisdiction()
        audit = create_audit_record(ty["id"], jur["id"])
        assert audit["status"] == "UNDER_EXAMINATION"

        s1 = validate_success(
            api.propose_adjustment(audit["id"], 400000, tax_manager_headers),
            200)
        assert s1["status"] == "ADJUSTMENT_PROPOSED"

        s2 = validate_success(api.negotiate_audit(audit["id"],
                                                  tax_manager_headers), 200)
        assert s2["status"] == "NEGOTIATING"

        s3 = validate_success(
            api.revise_adjustment(audit["id"], 250000, tax_manager_headers),
            200)
        assert s3["status"] == "ADJUSTMENT_PROPOSED"
        assert s3["proposed_adjustment_cents"] == 250000, \
            "the revised proposal overwrites the earlier amount"

        s4 = validate_success(
            api.close_audit(audit["id"], "AGREED", tax_manager_headers,
                            agreed_adjustment_cents=275000), 200)
        assert s4["status"] == "CLOSED_AGREED"
        assert s4["agreed_adjustment_cents"] == 275000

    def test_close_no_change_from_under_examination(
            self, api, tax_manager_headers):
        """PRD §3.9: "Closing takes an `outcome`: `NO_CHANGE` from
        `UNDER_EXAMINATION` lands in `CLOSED_NO_CHANGE`, while `AGREED` from
        `ADJUSTMENT_PROPOSED` or `NEGOTIATING` lands in `CLOSED_AGREED` and
        requires `agreed_adjustment_cents` present and nonnegative, which is
        then recorded."

        Design: Corner/state_machines/audit_close_no_change_from_examination
        """
        set_logical_clock("2026-01-05T00:00:00Z")
        ty, jur = setup_open_year_with_jurisdiction()
        audit = create_audit_record(ty["id"], jur["id"])

        closed = validate_success(
            api.close_audit(audit["id"], "NO_CHANGE", tax_manager_headers),
            200)
        assert closed["status"] == "CLOSED_NO_CHANGE"
        # No AGREED close ever recorded an agreed amount.
        assert closed.get("agreed_adjustment_cents") is None


class TestExamPeriodOverlap:
    def test_adjacent_exam_periods_permitted_half_open(
            self, api, tax_manager_headers):
        """PRD §2.9: "Audit examination periods use **half-open** semantics:
        `exam_period_start` is inclusive and `exam_period_end` is exclusive,
        so a new audit whose start equals an existing non-closed audit's end
        for the same jurisdiction is legal adjacency, while any true
        intersection is rejected with `ERR_AUDIT_PERIOD_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/audit_exam_period_half_open_adjacency
        """
        set_logical_clock("2026-01-05T00:00:00Z")
        ty, jur = setup_open_year_with_jurisdiction()
        audit_a = create_audit_record(ty["id"], jur["id"],
                                      exam_period_start="2024-01-01",
                                      exam_period_end="2025-01-01")
        assert audit_a["status"] == "UNDER_EXAMINATION"

        # start == A's exclusive end is legal adjacency under half-open rules.
        audit_b = validate_success(api.create_audit(
            {
                "tax_year_id": ty["id"],
                "jurisdiction_id": jur["id"],
                "exam_period_start": "2025-01-01",
                "exam_period_end": "2026-01-01",
            }, tax_manager_headers), 201)
        assert audit_b["status"] == "UNDER_EXAMINATION"

    def test_overlapping_exam_period_rejected(self, api, tax_manager_headers):
        """PRD §2.9: "Audit examination periods use **half-open** semantics:
        `exam_period_start` is inclusive and `exam_period_end` is exclusive,
        so a new audit whose start equals an existing non-closed audit's end
        for the same jurisdiction is legal adjacency, while any true
        intersection is rejected with `ERR_AUDIT_PERIOD_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/audit_exam_period_half_open_adjacency
        """
        set_logical_clock("2026-01-05T00:00:00Z")
        ty, jur = setup_open_year_with_jurisdiction()
        create_audit_record(ty["id"], jur["id"],
                            exam_period_start="2024-01-01",
                            exam_period_end="2025-01-01")
        # Legal adjacency establishes the boundary, then a true intersection.
        validate_success(api.create_audit(
            {
                "tax_year_id": ty["id"],
                "jurisdiction_id": jur["id"],
                "exam_period_start": "2025-01-01",
                "exam_period_end": "2026-01-01",
            }, tax_manager_headers), 201)

        # 2024-06-01 lies strictly inside A's [2024-01-01, 2025-01-01).
        res = api.create_audit(
            {
                "tax_year_id": ty["id"],
                "jurisdiction_id": jur["id"],
                "exam_period_start": "2024-06-01",
                "exam_period_end": "2025-06-01",
            }, tax_manager_headers)
        validate_error(res, ApiErrorId.ERR_AUDIT_PERIOD_OVERLAP,
                       expected_status=409)
