"""Loops: the deficiency revision loop and the escalation loop.

Neither a filing nor an enforcement action moves in a straight line. A packet
can be rejected and re-certified repeatedly, and a cease order can be answered,
escalated and answered again before it is finally cured.
"""

from test_helpers import (
    COMPLIANCE,
    api_client,
    approve_filing,
    decide_action,
    read_organization,
    read_registration,
    reject_filing,
    remediate_action,
    setup_delinquent_filing,
    setup_submitted_filing,
    submit_filing,
    validate_paginated,
    validate_success,
)


def _document_review_statuses(registration_id: str):
    """Every attached document's review status, keyed by its type."""
    response = api_client.list_registration_documents(
        COMPLIANCE, params={"registration_id": registration_id, "limit": 100}
    )
    documents, _meta = validate_paginated(response)
    return {doc["doc_type"]: doc["review_status"] for doc in documents}


class TestDeficiencyRevisionLoop:
    """A packet may go round the revision loop repeatedly before it registers."""

    def _three_round_loop(self):
        ctx = setup_submitted_filing()
        registration_id = ctx["registration"]["id"]
        certifier_id = ctx["certifier"]["id"]

        validate_success(
            reject_filing(registration_id, ["GOVERNING_DOCUMENT_ILLEGIBLE"])
        )
        validate_success(submit_filing(registration_id, certifier_id))
        validate_success(
            reject_filing(
                registration_id,
                ["OFFICER_LIST_INCOMPLETE", "REVIEW_REPORT_UNSIGNED"],
            )
        )
        validate_success(submit_filing(registration_id, certifier_id))
        ctx["registration"] = validate_success(approve_filing(registration_id))
        return ctx

    def test_two_rejections_leave_a_round_count_of_two_after_the_filing_registers(self):
        """PRD §3.4: "When the submission is closing a revision loop — that is,
        when it comes out of `DEFICIENT` — it also clears `deficiency_reasons` back
        to an empty list. What it deliberately does not do is reset
        `deficiency_round_count`: that counter accumulates across every round of
        the loop, so a filing on its third pass still shows a count of 2 from its
        two prior rejections."

        Design: Difficulty/non_linear_state_machine/registration_deficiency_revision_cycle_accumulates_rounds
        """
        ctx = self._three_round_loop()
        registration = ctx["registration"]

        assert registration["status"] == "REGISTERED", (
            f"The third pass was approved, got {registration['status']}"
        )
        assert registration["deficiency_round_count"] == 2, (
            "Two prior rejections accumulate and are never reset, got "
            f"{registration['deficiency_round_count']}"
        )
        assert registration["deficiency_reasons"] == [], (
            "The reasons were cleared by the resubmission, got "
            f"{registration['deficiency_reasons']}"
        )
        assert registration["filing_fee_cents"] == 24_000, (
            "The fee is recomputed on each submission and lands unchanged, got "
            f"{registration['filing_fee_cents']}"
        )
        assert (
            read_organization(ctx["organization"]["id"])["registered_state_count"] == 1
        ), "The approved filing is finally counted"

    def test_a_rejected_document_is_accepted_again_once_the_revised_packet_is_approved(
        self,
    ):
        """PRD §3.4: a `DEFICIENT` decision "sets `review_status` to `REJECTED` on
        every document of the filing", while an `APPROVE` decision "sets
        `review_status` to `ACCEPTED` on every document of the filing".

        Design: Difficulty/non_linear_state_machine/registration_deficiency_revision_cycle_accumulates_rounds
        """
        ctx = setup_submitted_filing()
        registration_id = ctx["registration"]["id"]

        validate_success(
            reject_filing(registration_id, ["GOVERNING_DOCUMENT_ILLEGIBLE"])
        )
        after_rejection = _document_review_statuses(registration_id)
        validate_success(submit_filing(registration_id, ctx["certifier"]["id"]))
        validate_success(approve_filing(registration_id))
        after_approval = _document_review_statuses(registration_id)

        assert after_rejection["GOVERNING_DOCUMENT"] == "REJECTED", (
            "The rejection marks every document, got "
            f"{after_rejection['GOVERNING_DOCUMENT']}"
        )
        assert after_approval["GOVERNING_DOCUMENT"] == "ACCEPTED", (
            "The same document row is accepted on the successful pass, got "
            f"{after_approval['GOVERNING_DOCUMENT']}"
        )
        assert set(after_approval.values()) == {"ACCEPTED"}, (
            f"Every document of the filing is accepted, got {after_approval}"
        )

    def test_a_rejection_leaves_the_charitys_aggregates_exactly_where_they_were(self):
        """PRD §3.4: a `DEFICIENT` decision "touches none of the organization's
        aggregates: `registered_state_count`, `penalty_outstanding_cents`,
        `solicitation_posture` and `filing_posture` are all left exactly as they
        were, because a rejected packet was never counted as a registration in the
        first place."

        Design: Difficulty/non_linear_state_machine/registration_deficiency_revision_cycle_accumulates_rounds
        """
        ctx = setup_submitted_filing()
        before = read_organization(ctx["organization"]["id"])

        rejected = validate_success(
            reject_filing(ctx["registration"]["id"], ["OFFICER_LIST_INCOMPLETE"])
        )
        after = read_organization(ctx["organization"]["id"])

        assert rejected["status"] == "DEFICIENT", (
            f"The packet was sent back, got {rejected['status']}"
        )
        assert rejected["deficiency_reasons"] == ["OFFICER_LIST_INCOMPLETE"], (
            f"The reasons are recorded verbatim, got {rejected['deficiency_reasons']}"
        )
        assert rejected["deficiency_round_count"] == 1, (
            f"The first round is counted, got {rejected['deficiency_round_count']}"
        )
        for field in (
            "registered_state_count",
            "penalty_outstanding_cents",
            "solicitation_posture",
            "filing_posture",
        ):
            assert after[field] == before[field], (
                f"{field} must be untouched by a rejection: "
                f"{before[field]} became {after[field]}"
            )


class TestEnforcementEscalationLoop:
    """An escalated order can be answered again, and the answer can cure it."""

    def _escalate_then_remediate_again(self):
        ctx = setup_delinquent_filing(sweep_at="2026-11-15T00:00:00Z")
        action_id = ctx["enforcement_action"]["id"]

        validate_success(remediate_action(action_id, "First remediation packet."))
        ctx["escalated"] = validate_success(decide_action(action_id, "ESCALATE"))
        ctx["re_remediated"] = validate_success(
            remediate_action(action_id, "Second remediation packet after cease order.")
        )
        return ctx

    def test_an_escalated_order_re_enters_remediation_and_then_cures(self):
        """PRD §3.9: "This is available from `OPEN` and from `ESCALATED` — an
        escalated cease-solicitation order can be remediated repeatedly, which is
        what makes the escalation loop cyclic". PRD §3.9 on the escalation itself:
        "The action's `status` becomes `ESCALATED` and its `action_type` is
        overwritten to `CEASE_SOLICITATION_ORDER`, whatever it was before."

        Design: Difficulty/non_linear_state_machine/enforcement_escalation_cycle_returns_to_remediation_then_cures
        """
        ctx = self._escalate_then_remediate_again()
        action_id = ctx["enforcement_action"]["id"]

        assert ctx["escalated"]["status"] == "ESCALATED", (
            f"The regulator escalated the matter, got {ctx['escalated']['status']}"
        )
        assert ctx["escalated"]["action_type"] == "CEASE_SOLICITATION_ORDER", (
            "Escalation overwrites the action type, got "
            f"{ctx['escalated']['action_type']}"
        )
        assert ctx["re_remediated"]["status"] == "REMEDIATION_SUBMITTED", (
            "The action re-enters a status it already occupied, got "
            f"{ctx['re_remediated']['status']}"
        )
        assert ctx["re_remediated"]["penalty_cents"] == 2_004, (
            "One day late is one accrual month at the plain base amount, got "
            f"{ctx['re_remediated']['penalty_cents']}"
        )
        assert ctx["re_remediated"]["settlement_total_cents"] == 14_504, (
            "2,004 of penalties plus an undiscounted 12,500 reinstatement fee, "
            f"got {ctx['re_remediated']['settlement_total_cents']}"
        )

        cured = validate_success(decide_action(action_id, "CURE"))
        assert cured["status"] == "CURED", (
            f"The second packet cured the order, got {cured['status']}"
        )
        assert read_registration(ctx["registration"]["id"])["status"] == "REGISTERED", (
            "The filing follows the DELINQUENT to CEASED to REGISTERED loop"
        )

    def test_closing_the_cease_order_cycle_returns_the_charity_to_a_clear_posture(self):
        """PRD §3.9: "The restoration from `CEASED` closes the full cease-order
        cycle `DELINQUENT` → `CEASED` → `REGISTERED`". Caused by that restoration
        "the organization's `ceased_state_codes`, `solicitation_posture`,
        `delinquent_registration_count`, `filing_posture`, `registered_state_count`
        and `penalty_outstanding_cents` are all recomputed".

        Design: Difficulty/non_linear_state_machine/enforcement_escalation_cycle_returns_to_remediation_then_cures
        """
        ctx = self._escalate_then_remediate_again()

        halted = read_organization(ctx["organization"]["id"])
        assert halted["solicitation_posture"] == "HALTED", (
            "A cease order in the domicile state halts solicitation, got "
            f"{halted['solicitation_posture']}"
        )

        validate_success(decide_action(ctx["enforcement_action"]["id"], "CURE"))
        organization = read_organization(ctx["organization"]["id"])

        assert organization["solicitation_posture"] == "CLEAR", (
            f"The cure lifts the halt, got {organization['solicitation_posture']}"
        )
        assert organization["filing_posture"] == "CURRENT", (
            f"Nothing is delinquent any more, got {organization['filing_posture']}"
        )
        assert organization["ceased_state_codes"] == [], (
            f"The ceased-state list is emptied, got {organization['ceased_state_codes']}"
        )
        assert organization["penalty_outstanding_cents"] == 0, (
            "A cured action contributes nothing to the ledger, got "
            f"{organization['penalty_outstanding_cents']}"
        )
        assert organization["registered_state_count"] == 1, (
            f"The restored filing is counted again, got {organization['registered_state_count']}"
        )
        assert organization["delinquent_registration_count"] == 0, (
            f"The delinquency is resolved, got {organization['delinquent_registration_count']}"
        )
