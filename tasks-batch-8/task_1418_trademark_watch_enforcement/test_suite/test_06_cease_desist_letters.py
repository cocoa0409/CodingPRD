"""Cease-and-desist letters: review loops, reissue cycle, fee ledger
conservation, settlement installments, litigation window, and segregation."""
import pytest

from test_helpers import (
    ApiErrorId,
    approve_letter,
    assert_instant_equal,
    draft_letter,
    get_client,
    get_letter,
    get_matter,
    make_associate_headers,
    make_partner_headers,
    set_clock,
    setup_approved_letter,
    setup_escalated_matter,
    setup_issued_letter,
    submit_letter_review,
    validate_error,
    validate_success,
)


class TestLetterLoops:
    def test_sendback_loop_returns_draft_without_approval_stamp(self, api):
        """PRD §3.6: "A `decision` of `APPROVED` moves the letter to `APPROVED` and
        stamps `approved_by_user_id`; a decision of `SENT_BACK` returns it to `DRAFT`
        with no approval stamp."

        Design: Difficulty/non_linear_state_machine/letter_sendback_and_reissue_cycles
        """
        _, _, _, _, letter = setup_approved_letter(
            budget=1000000, response_due_days=14)
        # The helper already walked DRAFT -> PENDING_REVIEW -> APPROVED once; redo
        # the send-back loop explicitly on a fresh letter for the cycle assertion.
        matter_id = letter["enforcement_matter_id"]
        letter2 = draft_letter(matter_id, user_id="assoc_1", response_due_days=14)
        submit_letter_review(letter2["id"], user_id="assoc_1")
        sent_back = approve_letter(letter2["id"], approver_id="partner_1",
                                   decision="SENT_BACK")
        assert sent_back["status"] == "DRAFT"
        assert sent_back["approved_by_user_id"] is None

        submit_letter_review(letter2["id"], user_id="assoc_1")
        approved = approve_letter(letter2["id"], approver_id="partner_1",
                                  decision="APPROVED")
        assert approved["status"] == "APPROVED"
        assert approved["approved_by_user_id"] == "partner_1"

    def test_negotiating_reissue_cycle_recomputes_response_due(self, api,
                                                               paralegal_headers):
        """PRD §3.6: "From `ISSUED`, `NEGOTIATION_STARTED` moves the letter to
        `NEGOTIATING`"
        PRD §3.6: "A letter in `NEGOTIATING` can be reissued by an
        `AssociateAttorney`, optionally overriding `response_due_days`; the reissue
        increments `reissue_count`, refreshes `issued_at`, recomputes
        `response_due_at`, and accrues the 25000-cent reissue fee — subject this time
        to the affordability check, unlike cascade reissues."
        PRD §2.6: "Letter issuance accrues a flat fee of 75000 cents; each reissue —
        manual or cascade-driven — accrues 25000 cents."

        Design: Difficulty/non_linear_state_machine/letter_sendback_and_reissue_cycles
        """
        client, _, _, _, letter = setup_issued_letter(budget=1000000,
                                                      response_due_days=14)
        negotiating = validate_success(
            api.record_letter_response(letter["id"],
                                       {"response_outcome": "NEGOTIATION_STARTED"},
                                       paralegal_headers), 200)
        assert negotiating["status"] == "NEGOTIATING"

        reissued = validate_success(
            api.reissue_letter(letter["id"], {"response_due_days": 10},
                               make_associate_headers("assoc_1")), 200)
        assert reissued["status"] == "ISSUED"
        assert reissued["reissue_count"] == 1
        # Issued at the startup clock 2026-08-01 (Saturday); 10 business days later:
        # Aug 3-7, 10-14 -> 2026-08-14T00:00:00Z.
        assert_instant_equal(reissued["response_due_at"], "2026-08-14T00:00:00Z",
                             "response_due_at after reissue")

        client_after = get_client(client["id"])
        assert client_after["budget_spent_cents"] == 75000 + 25000
        assert client_after["budget_remaining_cents"] == 1000000 - 100000


class TestBudgetLedgerConservation:
    def test_forward_accrual_on_issue_and_reissue(self, api, paralegal_headers):
        """PRD §2.6: "The ledger invariant is absolute: after every forward action
        (letter issue, letter reissue, takedown filing) and every compensating action
        (rescinding an issued letter), `budget_spent_cents` plus
        `budget_remaining_cents` equals `enforcement_budget_cents` exactly."
        PRD §3.6: "On issue, `issued_at` is set to the current instant,
        `response_due_at` is computed as `response_due_days` business days later
        under `BUSINESS_DAY_COUNT`, the fee accrues to both the matter's
        `accrued_fees_cents` and the client budget"

        Design: Difficulty/compensating_invariant/budget_conservation_across_issue_reissue_void
        """
        client, _, _, matter, letter = setup_issued_letter(budget=500000,
                                                           response_due_days=14)
        after_issue = get_client(client["id"])
        assert after_issue["budget_spent_cents"] == 75000
        assert after_issue["budget_remaining_cents"] == 425000
        assert get_matter(matter["id"])["accrued_fees_cents"] == 75000

        validate_success(
            api.record_letter_response(letter["id"],
                                       {"response_outcome": "NEGOTIATION_STARTED"},
                                       paralegal_headers), 200)
        validate_success(
            api.reissue_letter(letter["id"], {"response_due_days": 10},
                               make_associate_headers("assoc_1")), 200)
        after_reissue = get_client(client["id"])
        assert after_reissue["budget_spent_cents"] == 100000
        assert after_reissue["budget_remaining_cents"] == 400000
        assert get_matter(matter["id"])["accrued_fees_cents"] == 100000
        assert (after_reissue["budget_spent_cents"]
                + after_reissue["budget_remaining_cents"]
                == after_reissue["enforcement_budget_cents"])

    def test_void_from_issued_reverses_all_letter_fees(self, api,
                                                       paralegal_headers,
                                                       partner_headers):
        """PRD §3.6: "Voiding is the compensating path: an `AssociateAttorney` may
        void a letter in `DRAFT`, `PENDING_REVIEW`, or `APPROVED`, while voiding an
        `ISSUED` letter is a rescission reserved to a `PartnerAttorney`. Rescission
        reverses every fee the letter ever accrued — the issuance fee plus the
        reissue fee times `reissue_count` — crediting both the matter's
        `accrued_fees_cents` and the client budget by the same amount, restoring the
        ledger invariant of §2.6."

        Design: Difficulty/compensating_invariant/budget_conservation_across_issue_reissue_void
        """
        client, _, _, matter, letter = setup_issued_letter(budget=500000,
                                                           response_due_days=14)
        validate_success(
            api.record_letter_response(letter["id"],
                                       {"response_outcome": "NEGOTIATION_STARTED"},
                                       paralegal_headers), 200)
        validate_success(
            api.reissue_letter(letter["id"], {"response_due_days": 10},
                               make_associate_headers("assoc_1")), 200)
        assert get_client(client["id"])["budget_spent_cents"] == 100000

        voided = validate_success(api.void_letter(letter["id"], partner_headers), 200)
        assert voided["status"] == "VOID"

        client_after = get_client(client["id"])
        assert client_after["budget_spent_cents"] == 0
        assert client_after["budget_remaining_cents"] == 500000
        assert get_matter(matter["id"])["accrued_fees_cents"] == 0
        assert (client_after["budget_spent_cents"]
                + client_after["budget_remaining_cents"]
                == client_after["enforcement_budget_cents"])


class TestLetterTerminalAndLitigation:
    def test_letter_terminal_lockdown_after_complied(self, api, paralegal_headers):
        """PRD §3.6: "`COMPLIED`, `ESCALATED_LITIGATION`, and `VOID` are the letter's
        terminal states, with one systematic exception: the breach cascade of §3.7
        pulls a `COMPLIED` letter back to `ISSUED` as a reissue."
        PRD §2.10: "State — the target entity is in a state from which the requested
        transition is declared, including terminal-state lockdown, else
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/letter_terminal_lockdown_after_complied
        """
        _, _, _, _, letter = setup_issued_letter(response_due_days=14)
        complied = validate_success(
            api.record_letter_response(letter["id"], {"response_outcome": "COMPLIED"},
                                       paralegal_headers), 200)
        assert complied["status"] == "COMPLIED"

        res = api.record_letter_response(letter["id"], {"response_outcome": "REFUSED"},
                                         paralegal_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        assert get_letter(letter["id"])["status"] == "COMPLIED"

    def test_escalate_litigation_response_window_boundary(
        self, api, partner_headers
    ):
        """PRD §3.6: "From `ISSUED` this is permitted only after `response_due_at`
        has passed — earlier attempts are rejected with `ERR_RESPONSE_WINDOW_OPEN` —
        while from `REFUSED` it is always permitted; both land in
        `ESCALATED_LITIGATION`."
        PRD §3.6: "On issue, `issued_at` is set to the current instant,
        `response_due_at` is computed as `response_due_days` business days later
        under `BUSINESS_DAY_COUNT`"

        Design: Corner/validations/escalate_litigation_response_window_boundary
        """
        _, _, _, _, letter = setup_issued_letter(response_due_days=14)
        # Issued at the startup clock 2026-08-01 (Saturday); 14 business days land on
        # 2026-08-20T00:00:00Z.
        assert_instant_equal(letter["response_due_at"], "2026-08-20T00:00:00Z",
                             "response_due_at")

        set_clock("2026-08-20T00:00:00Z")
        res = api.escalate_letter_litigation(letter["id"], partner_headers)
        validate_error(res, ApiErrorId.ERR_RESPONSE_WINDOW_OPEN, expected_status=422)

        set_clock("2026-08-20T00:00:01Z")
        escalated = validate_success(
            api.escalate_letter_litigation(letter["id"], partner_headers), 200)
        assert escalated["status"] == "ESCALATED_LITIGATION"


class TestApprovalSegregationAndInstallments:
    def test_partner_cannot_approve_own_drafted_letter(self, api):
        """PRD §3.6: "The approval decision belongs exclusively to a
        `PartnerAttorney` other than the drafter: a self-approval or self-send-back
        is rejected with `ERR_SEGREGATION_OF_DUTIES`."
        PRD §2.1: "the caller approving or sending back a letter must differ from its
        `drafted_by_user_id`"

        Design: Corner/validations/partner_cannot_approve_own_drafted_letter
        """
        _, _, _, matter = setup_escalated_matter()
        letter = draft_letter(matter["id"], user_id="partner_1",
                              role="PartnerAttorney", response_due_days=14)
        submit_letter_review(letter["id"], user_id="partner_1", role="PartnerAttorney")

        res = api.approve_letter(letter["id"], {"decision": "APPROVED"},
                                 make_partner_headers("partner_1"))
        validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, expected_status=403)

        approved = validate_success(
            api.approve_letter(letter["id"], {"decision": "APPROVED"},
                               make_partner_headers("partner_2")), 200)
        assert approved["status"] == "APPROVED"
        assert approved["approved_by_user_id"] == "partner_2"

    def test_settlement_installments_remainder_to_final(self, api, paralegal_headers):
        """PRD §3.6: "Compliance with a `settlement_amount_cents` set triggers
        installment computation: the settlement is divided by `installment_count`
        using floor division to whole cents, and the remainder is added to the final
        installment, so the `installment_schedule` always sums exactly to the
        settlement amount."

        Design: Corner/calculations/settlement_installments_remainder_to_final
        """
        _, _, _, _, letter = setup_issued_letter(
            response_due_days=14, settlement_amount_cents=100000, installment_count=3)
        complied = validate_success(
            api.record_letter_response(letter["id"], {"response_outcome": "COMPLIED"},
                                       paralegal_headers), 200)
        assert complied["status"] == "COMPLIED"
        assert complied["installment_schedule"] == [33333, 33333, 33334]
        assert sum(complied["installment_schedule"]) == 100000
