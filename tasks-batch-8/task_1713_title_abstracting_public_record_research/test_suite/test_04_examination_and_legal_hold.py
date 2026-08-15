"""Search examination loop and legal-description hold gating (PRD §3.4, §3.5, §3.6)."""
from test_helpers import (
    ApiErrorId,
    accept_assignment,
    create_document,
    create_legal_check,
    create_verified_document,
    get_order,
    make_abstracter_headers,
    make_examiner_headers,
    make_ops_headers,
    resolve_check,
    resume_assignment,
    return_assignment,
    setup_order_with_assignment,
    submit_assignment,
    submit_verdict,
    validate_error,
    validate_success,
)


class TestDocumentDispositionGuards:
    def test_verify_verified_document_returns_409(self, api):
        """PRD §3.4: "Verifying a document moves it from `REPORTED` to `VERIFIED`
        — or from `FLAGGED_FOR_CURATIVE` to `VERIFIED` once its issue is cured —
        and recomputes the assignment's `verified_count`."
        PRD §2.10: "then the terminal-order guard, then generic state-transition
        legality (409), and only then the domain business rules"

        Design: Corner/state_machines/verify_verified_document_returns_409
        """
        ctx = setup_order_with_assignment("client_811", "abs_811")
        doc = create_document(
            ctx["order"]["id"], ctx["assignment"]["id"], "abs_811",
            instrument_number="INST-811-A",
        )
        first = api.verify_record_document(doc["id"], make_abstracter_headers("abs_811"))
        validate_success(first, 200)

        second = api.verify_record_document(doc["id"], make_abstracter_headers("abs_811"))
        validate_error(second, ApiErrorId.ERR_INVALID_STATE)

    def test_void_document_terminal_then_verify_returns_409(self, api):
        """PRD §3.4: "Voiding moves a mistakenly recorded document from `REPORTED`
        to `VOID`; voiding is available both to the assigned abstracter and to an
        `OperationsManager`, accepts an optional `reason`, and recomputes the
        assignment's `document_count` — record-then-void is a compensating pair
        that leaves `document_count` unchanged."
        PRD §3.4: "Verifying a document moves it from `REPORTED` to `VERIFIED`
        — or from `FLAGGED_FOR_CURATIVE` to `VERIFIED` once its issue is cured —
        and recomputes the assignment's `verified_count`."

        Design: Corner/state_machines/void_document_terminal_then_verify_returns_409
        """
        ctx = setup_order_with_assignment("client_813", "abs_813")
        doc = create_document(
            ctx["order"]["id"], ctx["assignment"]["id"], "abs_813",
            instrument_number="INST-813-A",
        )
        voided = api.void_record_document(
            doc["id"], {"reason": "entered in error"}, make_ops_headers()
        )
        validate_success(voided, 200)

        verify = api.verify_record_document(doc["id"], make_abstracter_headers("abs_813"))
        validate_error(verify, ApiErrorId.ERR_INVALID_STATE)


class TestSubmissionGuards:
    def test_submit_assignment_with_unexamined_document_rejected(self, api):
        """PRD §3.5: "Submission enforces four checks in order: the caller must be
        the assignment's own abstracter (else `ERR_FORBIDDEN`); the parent order
        must not be terminal (else `ERR_ORDER_TERMINAL`); the assignment must link
        at least one non-`VOID` document (else `ERR_EMPTY_ASSIGNMENT`, HTTP 422);
        and no linked document may still sit in `REPORTED` (else
        `ERR_DOCUMENTS_NOT_EXAMINED`, HTTP 409) — the examiner expects everything
        either verified, flagged, or voided."

        Design: Corner/state_machines/submit_assignment_with_unexamined_document_rejected
        """
        ctx = setup_order_with_assignment("client_814", "abs_814")
        create_document(
            ctx["order"]["id"], ctx["assignment"]["id"], "abs_814",
            instrument_number="INST-814-A",
        )
        resp = api.submit_search_assignment(
            ctx["assignment"]["id"], make_abstracter_headers("abs_814")
        )
        validate_error(resp, ApiErrorId.ERR_DOCUMENTS_NOT_EXAMINED)

    def test_submit_empty_assignment_rejected(self, api):
        """PRD §3.5: "the assignment must link at least one non-`VOID` document
        (else `ERR_EMPTY_ASSIGNMENT`, HTTP 422)"

        Design: Corner/state_machines/submit_empty_assignment_rejected
        """
        ctx = setup_order_with_assignment("client_815", "abs_815")
        resp = api.submit_search_assignment(
            ctx["assignment"]["id"], make_abstracter_headers("abs_815")
        )
        validate_error(resp, ApiErrorId.ERR_EMPTY_ASSIGNMENT)

    def test_accept_in_progress_assignment_returns_409(self, api):
        """PRD §3.5: "An `Examiner` may accept a `SUBMITTED` assignment, moving it
        to `ACCEPTED`; or return it, moving it from `SUBMITTED` to
        `RETURNED_FOR_CORRECTION` with a mandatory `reason`, incrementing
        `revision_count` by one and recording `return_reason` from that reason."

        Design: Corner/state_machines/accept_in_progress_assignment_returns_409
        """
        ctx = setup_order_with_assignment("client_816", "abs_816")
        resp = api.accept_search_assignment(
            ctx["assignment"]["id"], make_examiner_headers("ex_816")
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_abstracter_cannot_submit_others_assignment(self, api):
        """PRD §3.5: "Submission enforces four checks in order: the caller must be
        the assignment's own abstracter (else `ERR_FORBIDDEN`); the parent order
        must not be terminal (else `ERR_ORDER_TERMINAL`); the assignment must link
        at least one non-`VOID` document (else `ERR_EMPTY_ASSIGNMENT`, HTTP 422);
        and no linked document may still sit in `REPORTED` (else
        `ERR_DOCUMENTS_NOT_EXAMINED`, HTTP 409) — the examiner expects everything
        either verified, flagged, or voided."
        PRD §2.1: "an `Abstracter` may submit, resume, verify, flag, or void work
        only on assignments whose `abstracter_ref` matches"

        Design: Corner/rbac/abstracter_cannot_submit_others_assignment
        """
        ctx = setup_order_with_assignment("client_864", "abs_864")
        resp = api.submit_search_assignment(
            ctx["assignment"]["id"], make_abstracter_headers("abs_864_intruder")
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestCorrectionLoop:
    def _setup_submitted(self, api):
        ctx = setup_order_with_assignment("client_721", "abs_721")
        doc = create_verified_document(
            ctx["order"]["id"], ctx["assignment"]["id"], "abs_721",
            instrument_number="INST-721-A", recording_date="2011-02-14",
        )
        submit_assignment(ctx["assignment"]["id"], "abs_721")
        ctx["document"] = doc
        return ctx

    def test_return_moves_assignment_for_correction_and_counts_revision(self, api):
        """PRD §3.5: "An `Examiner` may accept a `SUBMITTED` assignment, moving it
        to `ACCEPTED`; or return it, moving it from `SUBMITTED` to
        `RETURNED_FOR_CORRECTION` with a mandatory `reason`, incrementing
        `revision_count` by one and recording `return_reason` from that reason.
        The assigned abstracter resumes a returned assignment, moving it from
        `RETURNED_FOR_CORRECTION` back to `IN_PROGRESS`, and the loop may repeat."

        Design: Difficulty/non_linear_state_machine/assignment_submit_return_resume_cycle
        """
        ctx = self._setup_submitted(api)
        returned = return_assignment(
            ctx["assignment"]["id"], "missing deed book reference", "ex_721"
        )
        assert returned["status"] == "RETURNED_FOR_CORRECTION"
        assert returned["revision_count"] == 1, (
            f"first return increments revision_count to 1, got {returned['revision_count']}"
        )
        assert returned["return_reason"] == "missing deed book reference"

        resumed = resume_assignment(ctx["assignment"]["id"], "abs_721")
        assert resumed["status"] == "IN_PROGRESS", "the cycle loops back to IN_PROGRESS"

    def test_resumed_assignment_resubmits_and_accepts_with_revision_count_preserved(self, api):
        """PRD §3.5: "The assigned abstracter resumes a returned assignment, moving
        it from `RETURNED_FOR_CORRECTION` back to `IN_PROGRESS`, and the loop may
        repeat."
        PRD §3.3: "`revision_count`, which starts at 0 and increments by one each
        time the assignment is returned for correction."

        Design: Difficulty/non_linear_state_machine/assignment_submit_return_resume_cycle
        """
        ctx = self._setup_submitted(api)
        return_assignment(ctx["assignment"]["id"], "missing deed book reference", "ex_721")
        resume_assignment(ctx["assignment"]["id"], "abs_721")

        resubmitted = submit_assignment(ctx["assignment"]["id"], "abs_721")
        assert resubmitted["status"] == "SUBMITTED", "resubmission from the loop is legal"

        accepted = accept_assignment(ctx["assignment"]["id"], "ex_721")
        assert accepted["status"] == "ACCEPTED"
        assert accepted["revision_count"] == 1, (
            "revision count is monotonic across the loop, never reset"
        )


class TestLegalDescriptionHold:
    def test_legal_check_verified_sets_survey_exception_flag(self, api):
        """PRD §3.6: "A `verdict` of `VERIFIED` moves the check from `PENDING` to
        `VERIFIED` and records the supplied flag on `survey_exception_applied` —
        when true, a standard survey exception must be carried into the report."
        PRD §3.6: "A `verdict` of `MISMATCH` moves the check from `PENDING` to
        `MISMATCH`, likewise records the flag, and sets the order's `legal_hold` to
        true: the order now carries a read-only hold that remains true while any
        check on it is in `MISMATCH`."

        Design: Corner/state_machines/legal_check_verified_sets_survey_exception_flag
        """
        order = self._order_in_search("client_818", "abs_818")
        check = create_legal_check(order["id"], "SURV-2026-818", "LOT 8 BLK B")
        verdict = submit_verdict(check["id"], "VERIFIED", True)
        assert verdict["status"] == "VERIFIED"
        assert verdict["survey_exception_applied"] is True

        order_after = get_order(order["id"])
        assert order_after["legal_hold"] is False, (
            "a clean verification never raises legal hold"
        )

    @staticmethod
    def _order_in_search(client_ref, abstracter_ref):
        ctx = setup_order_with_assignment(client_ref, abstracter_ref)
        return ctx["order"]

    def _setup_held_order(self, api):
        ctx = setup_order_with_assignment("client_762", "abs_762")
        doc = create_verified_document(
            ctx["order"]["id"], ctx["assignment"]["id"], "abs_762",
            instrument_number="INST-762-A", recording_date="2014-12-01",
        )
        check = create_legal_check(
            ctx["order"]["id"], "SURV-2026-100", "LOT 15 BLK O EXCEPT S 10 FT"
        )
        submit_verdict(check["id"], "MISMATCH", True)
        submit_assignment(ctx["assignment"]["id"], "abs_762")
        ctx["document"] = doc
        ctx["check"] = check
        return ctx

    def test_accepted_search_cannot_complete_order_under_legal_hold(self, api):
        """PRD §3.5: "Acceptance is the trigger that re-evaluates the order's
        search-completion guard: the order advances from `SEARCH_IN_PROGRESS` to
        `SEARCH_COMPLETE` when at least one assignment exists for it outside
        `CANCELLED`, every non-`CANCELLED` assignment has reached `ACCEPTED`, and
        no legal hold is in effect — and when the guard passes, the order's
        `version` increments by one."

        Design: Difficulty/cross_entity_state_dependency/order_search_complete_blocked_by_legal_description_mismatch
        """
        ctx = self._setup_held_order(api)
        accepted = accept_assignment(ctx["assignment"]["id"], "ex_762")
        assert accepted["status"] == "ACCEPTED"

        order = get_order(ctx["order"]["id"])
        assert order["legal_hold"] is True
        assert order["status"] == "SEARCH_IN_PROGRESS", (
            "all assignments ACCEPTED yet the legal hold must block search completion"
        )

    def test_resolving_mismatch_clears_hold_and_completes_search(self, api):
        """PRD §3.6: "resolution overwrites the order's `legal_description_text`
        with the corrected value, clears `legal_hold` when no other `MISMATCH`
        check remains, increments the order's `version` by one, and re-evaluates
        the search-completion guard described in §3.5 — so clearing the last hold
        on a fully accepted order is itself enough to complete the search phase."

        Design: Difficulty/cross_entity_state_dependency/order_search_complete_blocked_by_legal_description_mismatch
        """
        ctx = self._setup_held_order(api)
        accept_assignment(ctx["assignment"]["id"], "ex_762")
        held = get_order(ctx["order"]["id"])
        assert held["legal_hold"] is True and held["status"] == "SEARCH_IN_PROGRESS"

        resolve_check(ctx["check"]["id"], "LOT 15 BLK O EXCEPT S 10 FT")
        freed = get_order(ctx["order"]["id"])
        assert freed["legal_hold"] is False
        assert freed["status"] == "SEARCH_COMPLETE", (
            "resolving the last mismatch releases the guarded transition"
        )
        assert freed["legal_description_text"] == "LOT 15 BLK O EXCEPT S 10 FT", (
            "order legal description overwritten by the resolution"
        )
