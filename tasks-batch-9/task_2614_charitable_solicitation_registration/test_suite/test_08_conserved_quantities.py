"""Ledgers and counters that must return to where they started.

Every figure the state keeps about a charity has a compensating action, and the
interesting part is the boundary between what that compensation reverses and
what it deliberately leaves stamped in the record.
"""

from test_helpers import (
    COMPLIANCE,
    api_client,
    issue_enforcement_action,
    open_filing,
    read_enforcement_action,
    read_organization,
    read_registration,
    remediate_action,
    setup_registered_filing,
    vacate_action,
    validate_paginated,
    validate_success,
)


def _document_review_statuses(registration_id: str):
    """Every attached document's review status, keyed by its type."""
    documents, _meta = validate_paginated(
        api_client.list_registration_documents(
            COMPLIANCE, params={"registration_id": registration_id, "limit": 100}
        )
    )
    return {doc["doc_type"]: doc["review_status"] for doc in documents}


def _withdraw(registration_id: str, reason: str):
    return api_client.withdraw_state_registration(
        registration_id, {"withdraw_reason": reason}, COMPLIANCE
    )


class TestPenaltyLedgerConservation:
    """Issuing raises the ledger; vacating puts it back with no drift."""

    def _remediated_assessment(self):
        ctx = setup_registered_filing()
        action = issue_enforcement_action(
            ctx["organization"]["id"],
            ctx["registration"]["id"],
            "PENALTY_ASSESSMENT",
            penalty_cents_override=25_000,
        )
        ctx["enforcement_action"] = validate_success(
            remediate_action(
                action["id"], "Assessment disputed; documentation attached."
            )
        )
        return ctx

    def test_vacating_an_assessment_returns_the_ledger_to_its_pre_issuance_value(self):
        """PRD §2.12: "`Organization.penalty_outstanding_cents` is at all times
        exactly the sum of `penalty_cents` over that organization's enforcement
        actions whose `status` is `OPEN`, `REMEDIATION_SUBMITTED` or `ESCALATED`;
        actions in `CURED` or `VACATED` contribute nothing. Issuing an action for a
        penalty raises the ledger by exactly that amount, and vacating that same
        action lowers it by exactly that amount, so the ledger returns to its
        pre-issuance value with no drift even though the intervening transitions
        moved several other fields."

        Design: Difficulty/compensating_invariant/penalty_ledger_conserved_when_assessment_is_vacated
        """
        ctx = self._remediated_assessment()
        organization_id = ctx["organization"]["id"]

        raised = read_organization(organization_id)
        assert raised["penalty_outstanding_cents"] == 25_000, (
            "The overridden assessment raised the ledger, got "
            f"{raised['penalty_outstanding_cents']}"
        )

        vacated = validate_success(
            vacate_action(
                ctx["enforcement_action"]["id"],
                "Assessment issued against the wrong organization.",
            )
        )

        assert vacated["status"] == "VACATED", (
            f"The assessment is withdrawn, got {vacated['status']}"
        )
        assert vacated["penalty_cents"] == 25_000, (
            "The penalty itself is not erased by the vacatur, got "
            f"{vacated['penalty_cents']}"
        )
        assert vacated["cure_deadline"] == "2026-08-31T00:00:00.000Z", (
            "The issuing clock plus thirty whole days is preserved, got "
            f"{vacated['cure_deadline']}"
        )
        assert read_organization(organization_id)["penalty_outstanding_cents"] == 0, (
            "The ledger sums only live actions, so a vacated action contributes "
            "nothing"
        )

    def test_a_vacatur_from_remediation_preserves_the_settlement_figure_and_the_filing(
        self,
    ):
        """PRD §3.9: "Vacating from `OPEN` or from `REMEDIATION_SUBMITTED` leaves the
        filing's own status alone, since neither of those statuses had moved it."
        PRD §3.9 on the settlement figure it leaves behind: "`settlement_total_cents`
        is the penalty subtotal plus that reinstatement charge."

        Design: Difficulty/compensating_invariant/penalty_ledger_conserved_when_assessment_is_vacated
        """
        ctx = self._remediated_assessment()
        action_id = ctx["enforcement_action"]["id"]

        assert ctx["enforcement_action"]["settlement_total_cents"] == 36_250, (
            "A 25,000 subtotal earns ten percent, so 25,000 plus 11,250, got "
            f"{ctx['enforcement_action']['settlement_total_cents']}"
        )

        validate_success(
            vacate_action(action_id, "Assessment issued against the wrong organization.")
        )

        assert read_enforcement_action(action_id)["settlement_total_cents"] == 36_250, (
            "The settlement figure stamped at remediation is not recomputed by the "
            "vacatur"
        )
        assert read_registration(ctx["registration"]["id"])["status"] == "REGISTERED", (
            "A vacatur from remediation never touched the filing's status"
        )

        organization = read_organization(ctx["organization"]["id"])
        assert organization["filing_posture"] == "CURRENT", (
            f"Nothing is delinquent, got {organization['filing_posture']}"
        )
        assert organization["registered_state_count"] == 1, (
            "The filing is still counted, got "
            f"{organization['registered_state_count']}"
        )


class TestRegisteredStateCountConservation:
    """Approval raises the count by one; withdrawal lowers it by exactly one."""

    def test_withdrawing_an_approved_filing_restores_the_pre_approval_count(self):
        """PRD §2.12: "`Organization.registered_state_count` is at all times exactly
        the number of that organization's registrations whose `status` is
        `REGISTERED` ... Approving a filing raises the registered count by exactly
        one; withdrawing that filing lowers it by exactly one, restoring the
        pre-approval count even though `registered_at` and the accepted
        `review_status` values on its documents remain stamped in the record."

        Design: Difficulty/compensating_invariant/registered_state_count_conserved_when_filing_is_withdrawn
        """
        ctx = setup_registered_filing()
        organization_id = ctx["organization"]["id"]

        assert read_organization(organization_id)["registered_state_count"] == 1, (
            "The approval raised the count to one"
        )

        withdrawn = validate_success(
            _withdraw(
                ctx["registration"]["id"],
                "Board resolved to cease California solicitation.",
            )
        )

        assert withdrawn["status"] == "WITHDRAWN", (
            f"The filing is withdrawn, got {withdrawn['status']}"
        )
        assert withdrawn["registered_at"] == "2026-08-01T00:00:00.000Z", (
            "The original registration stamp remains in the record, got "
            f"{withdrawn['registered_at']}"
        )
        assert withdrawn["filing_fee_cents"] == 24_000, (
            "The fee assessed on the packet is unchanged, got "
            f"{withdrawn['filing_fee_cents']}"
        )
        assert read_organization(organization_id)["registered_state_count"] == 0, (
            "The count returns to its pre-approval value of zero"
        )

    def test_withdrawal_leaves_the_accepted_documents_and_the_clear_posture_alone(self):
        """PRD §3.5: "A `REGISTERED` filing moves `REGISTERED` → `WITHDRAWN`,
        decrements the organization's `registered_state_count` by one, recomputes
        `filing_posture`, and increments `Organization.version` by one."

        Design: Difficulty/compensating_invariant/registered_state_count_conserved_when_filing_is_withdrawn
        """
        ctx = setup_registered_filing()
        registration_id = ctx["registration"]["id"]

        before = _document_review_statuses(registration_id)
        assert set(before.values()) == {"ACCEPTED"}, (
            f"The approval accepted every document, got {before}"
        )

        validate_success(
            _withdraw(registration_id, "Board resolved to cease California solicitation.")
        )

        assert _document_review_statuses(registration_id) == before, (
            "Withdrawal does not revert document review statuses"
        )

        organization = read_organization(ctx["organization"]["id"])
        assert organization["filing_posture"] == "CURRENT", (
            f"A withdrawn filing is not a delinquent one, got {organization['filing_posture']}"
        )
        assert organization["solicitation_posture"] == "CLEAR", (
            f"No cease order was ever issued, got {organization['solicitation_posture']}"
        )
        assert organization["ceased_state_codes"] == [], (
            f"No state is ceased, got {organization['ceased_state_codes']}"
        )

    def test_withdrawing_a_draft_filing_leaves_the_count_untouched(self):
        """PRD §3.5: "A `DRAFT` filing moves `DRAFT` → `WITHDRAWN` and leaves
        `registered_state_count` untouched, precisely because a draft was never
        counted." PRD §2.12 lists the statuses outside the count: "Filings in
        `DRAFT`, `SUBMITTED`, `DEFICIENT`, `EXPIRED`, `CEASED` or `WITHDRAWN`
        contribute to neither counter."

        Design: Difficulty/compensating_invariant/registered_state_count_conserved_when_filing_is_withdrawn
        """
        ctx = setup_registered_filing()
        draft = open_filing(
            ctx["organization"]["id"],
            ctx["financial_statement"]["id"],
            "CA",
            "RENEWAL",
            fiscal_year=2027,
            coverage_start="2026-07-01T00:00:00Z",
            coverage_end="2027-07-01T00:00:00Z",
            supersedes_registration_id=ctx["registration"]["id"],
        )

        withdrawn = validate_success(
            _withdraw(draft["id"], "Renewal abandoned before certification.")
        )

        assert withdrawn["status"] == "WITHDRAWN", (
            f"A draft may be withdrawn as well, got {withdrawn['status']}"
        )
        assert read_organization(ctx["organization"]["id"])[
            "registered_state_count"
        ] == 1, "The approved filing is still the only counted one"
        assert read_registration(ctx["registration"]["id"])["status"] == "REGISTERED", (
            "Withdrawing the draft renewal leaves the live filing alone"
        )
