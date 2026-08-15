"""Interviews: scheduling well-formedness, half-open overlap rules, outcome /
documentation ownership, and the 72-hour documentation SLA."""
import pytest

from test_helpers import (
    ApiErrorId,
    attach_evidence,
    document_interview,
    get_case,
    hold_interview,
    make_analyst_headers,
    make_employee,
    make_manager_headers,
    make_store,
    schedule_interview,
    set_clock,
    setup_case_investigating,
    setup_case_interviewed,
    setup_case_ready_for_interview,
    validate_error,
    validate_success,
)
from test_helpers.constants import ANALYST_1, ANALYST_2, MANAGER_1


class TestInterviewScheduling:
    def test_interview_end_not_after_start_returns_invalid_request(self, api):
        """PRD §3.4: "Interviews are scheduled by the case's assigned analyst,
        who names the `case_id`, the `interviewer_id` of the analyst who will
        conduct it, a `scheduled_start`, a `scheduled_end` that must be
        strictly later than the start (`ERR_INVALID_REQUEST`), and — on
        employee-subject cases — the `subject_employee_id` of the employee
        being interviewed, subject to the same consistency rules as case
        creation."
        PRD §3.4: "A new interview starts `SCHEDULED`."

        Equal endpoints are rejected; a one-second window is legal.

        Design: Corner/entities/interview_end_not_after_start_returns_invalid_request
        """
        store = make_store(store_number="S025", name="Store 25")
        ctx = setup_case_investigating(store["id"], manual_loss_cents=1000)
        resp = api.create_interview(
            {"case_id": ctx["case"]["id"], "interviewer_id": ANALYST_1,
             "scheduled_start": "2026-08-10T10:00:00Z",
             "scheduled_end": "2026-08-10T10:00:00Z"},
            make_analyst_headers(ANALYST_1),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        ok = schedule_interview(
            ctx["case"]["id"], ANALYST_1, ANALYST_1,
            scheduled_start="2026-08-10T10:00:00Z",
            scheduled_end="2026-08-10T10:00:01Z",
        )
        assert ok["status"] == "SCHEDULED"

    def test_interview_overlap_half_open_adjacency_allowed(self, api):
        """PRD §3.4: "One employee cannot be double-booked: the new half-open
        window — including its start, excluding its end — must not overlap the
        window of any other `SCHEDULED` or `HELD` interview for the same
        employee, though windows that merely touch at an endpoint are allowed;
        violations fail with `ERR_INTERVIEW_OVERLAP`."

        [10:00, 11:00) and [11:00, 12:00) touch at 11:00 and both succeed.

        Design: Difficulty/resource_temporal_overlap/interview_overlap_half_open_adjacency_allowed
        """
        store = make_store(store_number="S220", name="Store 220")
        emp = make_employee(store["id"], employee_ref="E-220", full_name="Emp 220")
        ctx = setup_case_ready_for_interview(
            store["id"], subject_type="EMPLOYEE", employee_id=emp["id"],
            manual_loss_cents=50000, evidence_type="TRANSACTION_LOG",
        )
        i1 = schedule_interview(
            ctx["case"]["id"], ANALYST_1, ANALYST_1, subject_employee_id=emp["id"],
            scheduled_start="2026-08-10T10:00:00Z",
            scheduled_end="2026-08-10T11:00:00Z",
        )
        i2 = schedule_interview(
            ctx["case"]["id"], ANALYST_1, ANALYST_1, subject_employee_id=emp["id"],
            scheduled_start="2026-08-10T11:00:00Z",
            scheduled_end="2026-08-10T12:00:00Z",
        )
        assert i1["status"] == "SCHEDULED" and i2["status"] == "SCHEDULED", (
            "touching endpoints are adjacency, not overlap"
        )

    def test_interview_overlap_strict_intersection_rejected(self, api):
        """PRD §3.4: "One employee cannot be double-booked: the new half-open
        window — including its start, excluding its end — must not overlap the
        window of any other `SCHEDULED` or `HELD` interview for the same
        employee, though windows that merely touch at an endpoint are allowed;
        violations fail with `ERR_INTERVIEW_OVERLAP`."

        [10:30, 11:30) strictly intersects the existing [10:00, 11:00).

        Design: Difficulty/resource_temporal_overlap/interview_overlap_half_open_adjacency_allowed
        """
        store = make_store(store_number="S220", name="Store 220")
        emp = make_employee(store["id"], employee_ref="E-220", full_name="Emp 220")
        ctx = setup_case_ready_for_interview(
            store["id"], subject_type="EMPLOYEE", employee_id=emp["id"],
            manual_loss_cents=50000, evidence_type="TRANSACTION_LOG",
        )
        schedule_interview(
            ctx["case"]["id"], ANALYST_1, ANALYST_1, subject_employee_id=emp["id"],
            scheduled_start="2026-08-10T10:00:00Z",
            scheduled_end="2026-08-10T11:00:00Z",
        )
        resp = api.create_interview(
            {"case_id": ctx["case"]["id"], "interviewer_id": ANALYST_1,
             "subject_employee_id": emp["id"],
             "scheduled_start": "2026-08-10T10:30:00Z",
             "scheduled_end": "2026-08-10T11:30:00Z"},
            make_analyst_headers(ANALYST_1),
        )
        validate_error(resp, ApiErrorId.ERR_INTERVIEW_OVERLAP)


class TestInterviewOutcomeAndDocumentation:
    def test_interview_record_outcome_twice_returns_invalid_state(self, api):
        """PRD §3.4: "When the meeting happens, the interviewer alone —
        `ERR_INTERVIEWER_MISMATCH` for anyone else — records the outcome from
        `SCHEDULED`. An `outcome` of `ADMITTED`, `DENIED`, or `PARTIAL` moves
        the interview to `HELD` and stamps `conducted_at` from the logical
        clock."
        PRD §2.7: "6. The target entity's own state machine must permit the
        requested transition (`ERR_INVALID_STATE_TRANSITION`, or
        `ERR_DEMAND_NOT_PAYABLE` for a payment posting against a demand that is
        not payable)."

        Design: Corner/state_machines/interview_record_outcome_twice_returns_invalid_state
        """
        store = make_store(store_number="S037", name="Store 37")
        ctx = setup_case_ready_for_interview(store["id"], manual_loss_cents=1000)
        interview = schedule_interview(ctx["case"]["id"], ANALYST_1, ANALYST_1)
        held = hold_interview(interview["id"], ANALYST_1, outcome="ADMITTED")
        assert held["status"] == "HELD"
        resp = api.record_interview_outcome(
            interview["id"], {"outcome": "DENIED"}, make_analyst_headers(ANALYST_1)
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        after = validate_success(
            api.get_interview(interview["id"], make_analyst_headers(ANALYST_1))
        )
        assert after["outcome"] == "ADMITTED", "first recorded outcome stands"

    def test_interview_document_from_scheduled_returns_invalid_state(self, api):
        """PRD §3.4: "The interviewer files `notes` against a `HELD` interview,
        which stamps `documented_at` from the logical clock, computes the
        `doc_stale` flag, and moves the interview to `DOCUMENTED`."
        PRD §2.7: "6. The target entity's own state machine must permit the
        requested transition (`ERR_INVALID_STATE_TRANSITION`, or
        `ERR_DEMAND_NOT_PAYABLE` for a payment posting against a demand that is
        not payable)."

        Design: Corner/state_machines/interview_document_from_scheduled_returns_invalid_state
        """
        store = make_store(store_number="S038", name="Store 38")
        ctx = setup_case_investigating(store["id"], manual_loss_cents=1000)
        interview = schedule_interview(ctx["case"]["id"], ANALYST_1, ANALYST_1)
        resp = api.document_interview(
            interview["id"], {"notes": "premature"}, make_analyst_headers(ANALYST_1)
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    def test_interviewer_mismatch_on_outcome_and_document(self, api):
        """PRD §2.7: "3. Ownership: the actor must equal the case's
        `assigned_analyst_id` on assignee-scoped operations — case advancement,
        evidence attachment, interview scheduling, demand drafting, packet
        drafting, packet sealing, and packet revision — failing with
        `ERR_NOT_CASE_ASSIGNEE`; and the actor must equal the interview's
        `interviewer_id` on outcome recording and documentation, failing with
        `ERR_INTERVIEWER_MISMATCH`."

        Ownership (step 3) is evaluated before the state machine (step 6), so
        the mismatch error surfaces even where the transition would be valid.

        Design: Corner/errors/interviewer_mismatch_on_outcome_and_document
        """
        store = make_store(store_number="S092", name="Store 92")
        ctx = setup_case_ready_for_interview(store["id"], manual_loss_cents=1000)
        interview = schedule_interview(ctx["case"]["id"], ANALYST_1, ANALYST_1)
        resp1 = api.record_interview_outcome(
            interview["id"], {"outcome": "ADMITTED"}, make_analyst_headers(ANALYST_2)
        )
        validate_error(resp1, ApiErrorId.ERR_INTERVIEWER_MISMATCH)
        resp2 = api.document_interview(
            interview["id"], {"notes": "impostor"}, make_analyst_headers(ANALYST_2)
        )
        validate_error(resp2, ApiErrorId.ERR_INTERVIEWER_MISMATCH)
        after = validate_success(
            api.get_interview(interview["id"], make_analyst_headers(ANALYST_1))
        )
        assert after["status"] == "SCHEDULED", "no mutation by a non-interviewer"


class TestDocumentationSla:
    def test_doc_stale_exactly_72h_is_not_stale(self, api):
        """PRD §3.4: "The flag is true when the gap between `documented_at` and
        `conducted_at` is strictly greater than 72 hours — a gap of exactly 72
        hours and 0 seconds is not stale."

        Both interviews record their outcome at the default logical instant
        2026-08-01T00:00:00Z; documentation at +72h00m00s is not stale, at
        +72h00m01s it is.

        Design: Corner/calculations/doc_stale_exactly_72h_is_not_stale
        """
        store = make_store(store_number="S057", name="Store 57")
        ctx_a = setup_case_ready_for_interview(store["id"], manual_loss_cents=1000,
                                               evidence_type="AUDIO")
        ctx_b = setup_case_ready_for_interview(store["id"], manual_loss_cents=1000,
                                               evidence_type="AUDIO")
        iva = schedule_interview(ctx_a["case"]["id"], ANALYST_1, ANALYST_1,
                                 scheduled_start="2026-08-01T09:00:00Z",
                                 scheduled_end="2026-08-01T10:00:00Z")
        ivb = schedule_interview(ctx_b["case"]["id"], ANALYST_1, ANALYST_1,
                                 scheduled_start="2026-08-01T11:00:00Z",
                                 scheduled_end="2026-08-01T12:00:00Z")
        hold_interview(iva["id"], ANALYST_1)
        hold_interview(ivb["id"], ANALYST_1)
        # conducted_at stamped at the default logical clock 2026-08-01T00:00:00Z.
        set_clock("2026-08-04T00:00:00Z")
        doc_a = document_interview(iva["id"], ANALYST_1, notes="Exactly 72h later.")
        assert doc_a["doc_stale"] is False, "exactly 72h00m00s is NOT stale"
        set_clock("2026-08-04T00:00:01Z")
        doc_b = document_interview(ivb["id"], ANALYST_1, notes="One second past.")
        assert doc_b["doc_stale"] is True
        assert get_case(ctx_a["case"]["id"])["status"] == "INTERVIEWED"
        assert get_case(ctx_b["case"]["id"])["status"] == "INTERVIEWED"
