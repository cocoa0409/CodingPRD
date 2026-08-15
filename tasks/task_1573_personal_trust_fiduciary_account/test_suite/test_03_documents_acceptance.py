"""Trust document interpretation lifecycle and acceptance preconditions
(PRD §3.1)."""
from test_helpers import (
    ApiErrorId,
    get_success_data,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    EXEC,
    OFFICER,
    OPS,
    add_beneficiary,
    create_approved_document,
    create_trust,
)


def _walk_document(api, doc_id, per_stirpes=False):
    """DRAFT -> SUBMITTED -> INTERPRETED."""
    assert api.submit_document(doc_id, OFFICER).status_code == 200
    assert api.interpret_document(
        doc_id, {"per_stirpes": per_stirpes, "interpretation_notes": "ok"}, OFFICER
    ).status_code == 200


class TestTerminalDocumentLockdown:
    def test_approve_rejected_document_returns_invalid_state(self, api):
        """PRD §2.8: "the target entity is in a valid from-state for the
        requested transition, including terminal-state lockdown
        (`ERR_INVALID_STATE`)."
        PRD §3.1: "A `TrustExecutive` then either approves the interpretation,
        moving INTERPRETED → APPROVED and stamping `approved_at`, or rejects
        it, moving INTERPRETED → REJECTED with a recorded `rejected_reason`."

        Design: Corner/state_machines/terminal_document_rejected_lockdown
        """
        trust = create_trust(trust_name="Lockdown Trust")
        resp = api.create_document(
            {"trust_id": trust["id"], "version_number": 1, "summary": "v1"}, OFFICER
        )
        doc = get_success_data(resp)
        _walk_document(api, doc["id"], per_stirpes=True)
        assert api.reject_interpretation(
            doc["id"], {"rejected_reason": "ambiguity in article 4"}, EXEC
        ).status_code == 200

        resp = api.approve_document(doc["id"], EXEC)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_rejected_document_keeps_status_and_reason(self, api):
        """PRD §3.1: "A `TrustExecutive` then either approves the
        interpretation, moving INTERPRETED → APPROVED and stamping
        `approved_at`, or rejects it, moving INTERPRETED → REJECTED with a
        recorded `rejected_reason`."

        Design: Corner/state_machines/terminal_document_rejected_lockdown
        """
        trust = create_trust(trust_name="Lockdown Reason")
        resp = api.create_document(
            {"trust_id": trust["id"], "version_number": 1, "summary": "v1"}, OFFICER
        )
        doc = get_success_data(resp)
        _walk_document(api, doc["id"], per_stirpes=True)
        assert api.reject_interpretation(
            doc["id"], {"rejected_reason": "ambiguity in article 4"}, EXEC
        ).status_code == 200

        api.approve_document(doc["id"], EXEC)  # rejected; must not mutate
        current = validate_success(api.get_document(doc["id"], OFFICER))
        assert current["status"] == "REJECTED"
        assert current["rejected_reason"] == "ambiguity in article 4"


class TestAcceptancePreconditions:
    def test_accept_without_approved_document_rejected(self, api):
        """PRD §3.1: "Acceptance — the transition to ACTIVE — enforces two
        preconditions in prose order: at least one TrustDocument of the trust
        must be APPROVED, otherwise `ERR_DOCUMENT_NOT_APPROVED`; and for every
        `beneficiary_class` that has at least one ACTIVE Beneficiary, the
        `share_bps` values of that class's ACTIVE members must sum to exactly
        10000, otherwise `ERR_SHARE_SUM_INVALID`."

        Design: Corner/state_machines/accept_without_approved_document_rejected
        """
        trust = create_trust(trust_name="Guarded Accept")
        resp = api.create_document(
            {"trust_id": trust["id"], "version_number": 1, "summary": "v1"}, OFFICER
        )
        doc = get_success_data(resp)
        _walk_document(api, doc["id"])  # INTERPRETED, never approved
        assert api.submit_for_acceptance(trust["id"], OFFICER).status_code == 200

        resp = api.accept_trust(trust["id"], EXEC)
        validate_error(resp, ApiErrorId.ERR_DOCUMENT_NOT_APPROVED)

    def test_interpreted_only_trust_stays_under_review(self, api):
        """PRD §3.1: "Acceptance — the transition to ACTIVE — enforces two
        preconditions in prose order: at least one TrustDocument of the trust
        must be APPROVED, otherwise `ERR_DOCUMENT_NOT_APPROVED`."

        Design: Corner/state_machines/accept_without_approved_document_rejected
        """
        trust = create_trust(trust_name="Guarded Accept State")
        resp = api.create_document(
            {"trust_id": trust["id"], "version_number": 1, "summary": "v1"}, OFFICER
        )
        doc = get_success_data(resp)
        _walk_document(api, doc["id"])
        assert api.submit_for_acceptance(trust["id"], OFFICER).status_code == 200

        api.accept_trust(trust["id"], EXEC)
        current = validate_success(api.get_trust(trust["id"], OFFICER))
        assert current["status"] == "UNDER_ACCEPTANCE_REVIEW"

    def test_share_sum_not_10000_blocks_acceptance(self, api):
        """PRD §3.1: "for every `beneficiary_class` that has at least one
        ACTIVE Beneficiary, the `share_bps` values of that class's ACTIVE
        members must sum to exactly 10000, otherwise `ERR_SHARE_SUM_INVALID`."

        Design: Corner/validations/share_sum_not_10000_blocks_acceptance
        """
        trust = create_trust(trust_name="Share Sum", distribution_standard="HEMS")
        create_approved_document(trust["id"])
        add_beneficiary(trust["id"], full_name="A", share_bps=6000, date_of_birth="1950-01-01")
        add_beneficiary(trust["id"], full_name="B", share_bps=3000, date_of_birth="1951-01-01")
        assert api.submit_for_acceptance(trust["id"], OFFICER).status_code == 200

        resp = api.accept_trust(trust["id"], EXEC)
        validate_error(resp, ApiErrorId.ERR_SHARE_SUM_INVALID)

    def test_share_sum_invalid_leaves_trust_under_review(self, api):
        """PRD §3.1: "for every `beneficiary_class` that has at least one
        ACTIVE Beneficiary, the `share_bps` values of that class's ACTIVE
        members must sum to exactly 10000, otherwise `ERR_SHARE_SUM_INVALID`."

        Design: Corner/validations/share_sum_not_10000_blocks_acceptance
        """
        trust = create_trust(trust_name="Share Sum State", distribution_standard="HEMS")
        create_approved_document(trust["id"])
        add_beneficiary(trust["id"], full_name="A", share_bps=6000, date_of_birth="1950-01-01")
        add_beneficiary(trust["id"], full_name="B", share_bps=3000, date_of_birth="1951-01-01")
        assert api.submit_for_acceptance(trust["id"], OFFICER).status_code == 200

        api.accept_trust(trust["id"], EXEC)
        current = validate_success(api.get_trust(trust["id"], OFFICER))
        assert current["status"] == "UNDER_ACCEPTANCE_REVIEW"


class TestVersionMonotonicity:
    def test_version_increments_on_every_trust_mutation(self, api):
        """PRD §2.4: "Any mutation of the trust — including recomputation of
        its derived fields `income_balance_cents`, `principal_balance_cents`,
        `reserved_income_cents`, `reserved_principal_cents`,
        `available_income_cents`, `available_principal_cents`,
        `total_market_value_cents`, or `pending_distribution_count` — updates
        `updated_at` and increments `version` by one."
        PRD §3.1: "Across all of these transitions — submit, accept, decline,
        suspend, reinstate, terminate — each one increments the trust's
        `version` by one."

        Design: Corner/cross_cutting_complexity_layers/occ_version_increments_on_every_mutation
        """
        created = create_trust(trust_name="Versions", trust_type="REVOCABLE",
                               distribution_standard="HEMS")
        assert created["version"] == 1
        # Document lifecycle mutates the TrustDocument, not the trust, so the
        # trust version is unchanged by satisfying the acceptance precondition.
        create_approved_document(created["id"])

        submitted = validate_success(api.submit_for_acceptance(created["id"], OFFICER))
        assert submitted["version"] == 2

        accepted = validate_success(api.accept_trust(created["id"], EXEC))
        assert accepted["version"] == 3

    def test_ledger_post_increments_trust_version_by_one(self, api):
        """PRD §3.5: "Posting recomputes the trust's balances and total market
        value, increments the trust's `version`, and — per the staleness rule
        of §2.6 — supersedes any DRAFT or FINALIZED annual statement whose
        fiscal year contains the entry's `value_date`."

        Design: Corner/cross_cutting_complexity_layers/occ_version_increments_on_every_mutation
        """
        created = create_trust(trust_name="Versions Ledger", trust_type="REVOCABLE",
                               distribution_standard="HEMS")
        create_approved_document(created["id"])
        assert api.submit_for_acceptance(created["id"], OFFICER).status_code == 200
        assert api.accept_trust(created["id"], EXEC).status_code == 200

        resp = api.create_ledger_entry(
            {
                "trust_id": created["id"],
                "entry_kind": "RECEIPT",
                "receipt_type": "INITIAL_FUNDING",
                "amount_cents": 100000,
                "value_date": "2026-08-05",
                "description": "funding",
            },
            OPS,
        )
        assert resp.status_code == 201
        after = validate_success(api.get_trust(created["id"], OFFICER))
        assert after["version"] == 4, (
            "create -> submit -> accept -> receipt must give version 4"
        )
