"""The two state machines: a filing's lifecycle and an action's disposition.

A filing is born in draft, is certified once by a human, is adjudicated, and may
be withdrawn — and every one of those edges has a from-set that refuses
everything outside it. An enforcement action's cure window governs its own.
"""

from test_helpers import (
    COMPLIANCE,
    ApiErrorId,
    api_client,
    approve_filing,
    attach_required_documents,
    create_financial_statement,
    create_organization,
    decide_action,
    extension_request_payload,
    issue_enforcement_action,
    open_filing,
    read_enforcement_action,
    read_organization,
    read_registration,
    remediate_action,
    seed_california_profile,
    seed_state_profile,
    setup_delinquent_filing,
    setup_draft_filing,
    setup_registered_filing,
    submit_filing,
    validate_error,
    validate_paginated,
    validate_success,
)


def _withdraw(registration_id: str, reason: str = "Filed in error."):
    return api_client.withdraw_state_registration(
        registration_id, {"withdraw_reason": reason}, COMPLIANCE
    )


class TestFilingInitialState:
    """A filing is born in draft with every stamped field still empty."""

    def test_a_new_filing_lands_in_draft_with_no_certification_and_no_extension(self):
        """PRD §3.3: "The new record lands in `status` of `DRAFT` with
        `deficiency_round_count` at 0, `deficiency_reasons` an empty list, and
        `submitted_at`, `registered_at` and `certified_by_officer_id` all null." PRD
        §3.3 on the third deadline step: "`extended_due_date` is `renewal_due_date`
        plus the `granted_days` of the one extension request on this filing whose
        `status` is `GRANTED`, and it is null while no request on the filing has been
        granted."

        Design: Corner/state_machines/new_state_registration_starts_in_draft
        """
        seed_california_profile()
        organization = create_organization()
        statement = create_financial_statement(organization)

        response = api_client.create_state_registration(
            {
                "organization_id": organization["id"],
                "state_code": "CA",
                "registration_type": "INITIAL",
                "fiscal_year": 2026,
                "coverage_start": "2025-07-01T00:00:00Z",
                "coverage_end": "2026-07-01T00:00:00Z",
                "financial_statement_id": statement["id"],
            },
            COMPLIANCE,
        )
        filing = validate_success(response, 201)

        assert filing["status"] == "DRAFT", (
            f"A filing is opened in DRAFT, got {filing['status']}"
        )
        assert filing["deficiency_round_count"] == 0, (
            f"No revision round has run yet, got {filing['deficiency_round_count']}"
        )
        assert filing["deficiency_reasons"] == [], (
            f"No reason has been recorded, got {filing['deficiency_reasons']}"
        )
        assert filing["submitted_at"] is None, (
            f"Nobody has submitted it, got {filing['submitted_at']}"
        )
        assert filing["registered_at"] is None, (
            f"Nobody has approved it, got {filing['registered_at']}"
        )
        assert filing["certified_by_officer_id"] is None, (
            f"Nobody has certified it, got {filing['certified_by_officer_id']}"
        )
        assert filing["extended_due_date"] is None, (
            f"No extension has been granted, got {filing['extended_due_date']}"
        )
        assert filing["renewal_due_date"] == "2026-11-14T00:00:00.000Z", (
            "A June 2026 fiscal year end plus four months and fifteen days, got "
            f"{filing['renewal_due_date']}"
        )
        assert filing["required_financial_attestation"] == "REVIEW", (
            "26,000,000 of gross revenue clears California's review threshold, got "
            f"{filing['required_financial_attestation']}"
        )
        assert filing["version"] == 1, (
            f"A freshly created row is at version 1, got {filing['version']}"
        )


class TestDraftToSubmitted:
    """Certification stamps the officer and re-prices the packet."""

    def test_a_conforming_submission_stamps_the_clock_the_officer_and_the_fee(self):
        """PRD §3.4: "A successful submission stamps `submitted_at` with the current
        logical clock, stamps `certified_by_officer_id` with the acting officer's
        identifier, recomputes `filing_fee_cents` and re-derives
        `required_financial_attestation` against the linked statement's current
        numbers, and increments the filing's `version` by one." PRD §3.3: a document's
        "`review_status` is server-owned and begins at `ATTACHED`; the regulator's
        adjudication later moves it to `ACCEPTED` or `REJECTED`."

        Design: Corner/state_machines/draft_to_submitted_stamps_certifier_and_recomputes_fee
        """
        ctx = setup_draft_filing()

        submitted = validate_success(
            submit_filing(
                ctx["registration"]["id"],
                ctx["certifier"]["id"],
                certification_note="Certified under penalty of perjury.",
            )
        )

        assert submitted["status"] == "SUBMITTED", (
            f"Certification advances DRAFT to SUBMITTED, got {submitted['status']}"
        )
        assert submitted["submitted_at"] == "2026-08-01T00:00:00.000Z", (
            f"The stamp is the logical clock, got {submitted['submitted_at']}"
        )
        assert submitted["certified_by_officer_id"] == ctx["certifier"]["id"], (
            "The acting officer is recorded, got "
            f"{submitted['certified_by_officer_id']}"
        )
        assert submitted["filing_fee_cents"] == 24_000, (
            "15,000 tier base plus 1,000 online surcharge, times 1.5 for an initial "
            f"filing, got {submitted['filing_fee_cents']}"
        )
        assert submitted["required_financial_attestation"] == "REVIEW", (
            f"The requirement is re-derived unchanged, got "
            f"{submitted['required_financial_attestation']}"
        )
        assert submitted["version"] == 2, (
            f"The submission is one mutation, got {submitted['version']}"
        )

        documents, _meta = validate_paginated(
            api_client.list_registration_documents(
                COMPLIANCE, params={"registration_id": ctx["registration"]["id"]}
            )
        )
        assert {doc["review_status"] for doc in documents} == {"ATTACHED"}, (
            "Documents are only accepted at approval, got "
            f"{[doc['review_status'] for doc in documents]}"
        )
        assert read_organization(ctx["organization"]["id"])[
            "registered_state_count"
        ] == 0, "A submitted filing is not yet a registration"


class TestReviewOnlyLeavesSubmitted:
    """A draft cannot be approved straight into registration."""

    def test_approving_a_draft_filing_is_refused_and_leaves_it_untouched(self):
        """PRD §2.11 rung 9: "The registration's `status` is in the requested
        transition's from-set → `ERR_INVALID_REGISTRATION_STATE` (409). Applies to
        filing submission, review, withdrawal, and registration-document creation."

        Design: Corner/state_machines/review_of_a_draft_filing_rejected
        """
        ctx = setup_draft_filing()

        response = approve_filing(ctx["registration"]["id"])

        validate_error(response, ApiErrorId.ERR_INVALID_REGISTRATION_STATE.value)
        filing = read_registration(ctx["registration"]["id"])
        assert filing["status"] == "DRAFT", (
            f"The refused review left the filing in DRAFT, got {filing['status']}"
        )
        assert filing["version"] == 1, (
            f"A refused request mutates nothing, got {filing['version']}"
        )
        assert filing["registered_at"] is None, (
            f"No registration instant was stamped, got {filing['registered_at']}"
        )


class TestWithdrawalIsNotIdempotent:
    """Withdrawal happens once; the replay is a conflict."""

    def test_the_second_identical_withdrawal_is_a_conflict_not_a_second_success(self):
        """PRD §3.4: "A `DRAFT` filing moves `DRAFT` → `WITHDRAWN` and leaves
        `registered_state_count` untouched, precisely because a draft was never
        counted." PRD §3.4: "`EXPIRED` and `WITHDRAWN` are the two terminal statuses
        of a filing; no transition leads out of either."

        Design: Corner/state_machines/withdraw_twice_second_attempt_rejected
        """
        ctx = setup_draft_filing()
        registration_id = ctx["registration"]["id"]

        first = validate_success(_withdraw(registration_id))
        second = _withdraw(registration_id)

        validate_error(second, ApiErrorId.ERR_INVALID_REGISTRATION_STATE.value)
        assert first["status"] == "WITHDRAWN", (
            f"The first call withdrew the filing, got {first['status']}"
        )
        filing = read_registration(registration_id)
        assert filing["status"] == "WITHDRAWN", (
            f"The filing stays withdrawn, got {filing['status']}"
        )
        assert filing["version"] == 2, (
            "Only the first withdrawal was a mutation, got "
            f"{filing['version']}"
        )
        assert read_organization(ctx["organization"]["id"])[
            "registered_state_count"
        ] == 0, "A withdrawn draft was never counted in the first place"


class TestTerminalWithdrawnIsLockedDown:
    """A withdrawn packet cannot be revived by its own certifying officer."""

    def test_submitting_a_withdrawn_filing_reports_the_state_error_not_the_document_error(
        self,
    ):
        """PRD §3.4: "the filing must currently be in `DRAFT` or `DEFICIENT`, or it is
        `ERR_INVALID_REGISTRATION_STATE`". The ladder decides which complaint wins:
        PRD §2.11 places rung 9 before rung 29, "The required document set is complete
        → `ERR_REQUIRED_DOCUMENT_MISSING` (422). Applies to filing submission."

        Design: Corner/state_machines/terminal_withdrawn_filing_cannot_be_submitted
        """
        ctx = setup_draft_filing(attach_documents=False)
        registration_id = ctx["registration"]["id"]
        validate_success(_withdraw(registration_id))

        response = submit_filing(
            registration_id,
            ctx["certifier"]["id"],
            certification_note="Attempting to revive.",
        )

        validate_error(response, ApiErrorId.ERR_INVALID_REGISTRATION_STATE.value)
        filing = read_registration(registration_id)
        assert filing["status"] == "WITHDRAWN", (
            f"The terminal status holds, got {filing['status']}"
        )
        assert filing["submitted_at"] is None, (
            f"No submission instant was stamped, got {filing['submitted_at']}"
        )
        assert filing["certified_by_officer_id"] is None, (
            f"No officer was recorded, got {filing['certified_by_officer_id']}"
        )


class TestExtensionPreconditionReadsTheFilingsState:
    """A state that entertains no extension refuses the request outright."""

    def test_a_request_on_a_filing_in_a_no_extension_state_creates_no_row(self):
        """PRD §3.5: "The state must actually allow extensions — its
        `extension_allowed` must be true (the default is false) and its
        `extension_max_days` must be at least 1 (the default is 0) — or the request is
        rejected with `ERR_EXTENSION_NOT_ALLOWED`; the same check is repeated when a
        regulator later grants the request, so a state whose configuration is
        corrected between request and decision cannot slip a grant through."

        Design: Corner/state_machines/extension_request_in_state_without_extensions_rejected
        """
        seed_state_profile(
            "NY",
            assurance_basis="CONTRIBUTIONS_ONLY",
            review_threshold_cents=25_000_000,
            audit_threshold_cents=100_000_000,
            extension_allowed=False,
            extension_max_days=0,
        )
        organization = create_organization(domicile_state_code="NY")
        statement = create_financial_statement(organization)
        filing = open_filing(organization["id"], statement["id"], "NY")

        response = api_client.create_extension_request(
            extension_request_payload(
                filing["id"], filing["version"], "IRS_990_EXTENSION", 60
            ),
            COMPLIANCE,
        )

        validate_error(response, ApiErrorId.ERR_EXTENSION_NOT_ALLOWED.value)
        reread = read_registration(filing["id"])
        assert reread["extended_due_date"] is None, (
            f"No deadline was moved, got {reread['extended_due_date']}"
        )
        assert reread["version"] == 1, (
            f"The filing was not mutated, got {reread['version']}"
        )
        _rows, meta = validate_paginated(
            api_client.list_registration_extension_requests(filing["id"], COMPLIANCE)
        )
        assert meta["total_count"] == 0, (
            f"No request row was created, got {meta['total_count']}"
        )


class TestRemediationLeavesTheLedgerAlone:
    """Answering an action prices the settlement but pays nothing off."""

    def test_remediation_stamps_the_settlement_and_keeps_the_penalty_outstanding(self):
        """PRD §3.9: "The transition sets `status` to `REMEDIATION_SUBMITTED`, records
        the supplied `remediation_note`, stamps `settlement_total_cents`, and
        increments the action's `version` by one. It deliberately leaves
        `penalty_outstanding_cents` alone, because a submitted remediation is still an
        outstanding matter: the penalty leaves the ledger only when the action is cured
        or vacated."

        Design: Corner/state_machines/remediation_stamps_settlement_without_moving_the_penalty_ledger
        """
        ctx = setup_registered_filing()
        action = issue_enforcement_action(
            ctx["organization"]["id"],
            ctx["registration"]["id"],
            "PENALTY_ASSESSMENT",
            penalty_cents_override=9_000,
        )

        remediated = validate_success(
            remediate_action(
                action["id"],
                "Delinquent renewal filed with supporting schedules.",
            )
        )

        assert remediated["status"] == "REMEDIATION_SUBMITTED", (
            f"The action awaits the regulator, got {remediated['status']}"
        )
        assert (
            remediated["remediation_note"]
            == "Delinquent renewal filed with supporting schedules."
        ), f"The note is recorded verbatim, got {remediated['remediation_note']}"
        assert remediated["settlement_total_cents"] == 21_500, (
            "A 9,000 subtotal earns no discount, so 9,000 plus 12,500, got "
            f"{remediated['settlement_total_cents']}"
        )
        assert remediated["cure_deadline"] == "2026-08-31T00:00:00.000Z", (
            f"The issuing clock plus thirty whole days, got {remediated['cure_deadline']}"
        )
        assert read_organization(ctx["organization"]["id"])[
            "penalty_outstanding_cents"
        ] == 9_000, "The penalty is still outstanding after a remediation"
        assert read_registration(ctx["registration"]["id"])["status"] == "REGISTERED", (
            "A directly issued assessment does not move the filing"
        )


class TestEscalationFromOpenNeedsAClosedCureWindow:
    """A regulator may not escalate while the charity can still answer."""

    def test_escalating_on_the_day_the_notice_issued_is_refused(self):
        """PRD §3.9: "From `OPEN` it requires the same filing-status condition **and**
        that the logical clock be strictly after the action's `cure_deadline`, because
        escalating without giving the charity a chance to answer is only permitted once
        the cure window has closed; escalating an `OPEN` action while the window is
        still open reports `ERR_CURE_WINDOW_EXPIRED`."

        Design: Corner/state_machines/escalation_from_open_inside_the_cure_window_rejected
        """
        ctx = setup_delinquent_filing(sweep_at="2026-11-15T00:00:00Z")
        action_id = ctx["enforcement_action"]["id"]

        response = decide_action(action_id, "ESCALATE")

        validate_error(response, ApiErrorId.ERR_CURE_WINDOW_EXPIRED.value)
        action = read_enforcement_action(action_id)
        assert action["status"] == "OPEN", (
            f"The refused escalation left the action OPEN, got {action['status']}"
        )
        assert action["cure_deadline"] == "2026-12-15T00:00:00.000Z", (
            "The window runs thirty days from the sweep, got "
            f"{action['cure_deadline']}"
        )
        assert action["action_type"] == "DELINQUENCY_NOTICE", (
            "No overwrite to a cease order happened, got "
            f"{action['action_type']}"
        )
        assert read_registration(ctx["registration"]["id"])["status"] == "DELINQUENT", (
            "The filing is delinquent but not ceased"
        )
        assert read_organization(ctx["organization"]["id"])[
            "solicitation_posture"
        ] == "CLEAR", "Nothing has been ceased, so solicitation is still clear"


class TestRenewalApprovalExpiresThePredecessor:
    """Approving a renewal retires the filing it supersedes in the same request."""

    def test_the_two_counter_movements_cancel_and_the_predecessor_expires(self):
        """PRD §3.4: "The first link expires the predecessor: a target in `REGISTERED`
        moves `REGISTERED` → `EXPIRED` and the organization's `registered_state_count`
        drops by one, while a target already swept into delinquency moves `DELINQUENT`
        → `EXPIRED` and it is `delinquent_registration_count` that drops by one
        instead." PRD §3.3: "a renewal skips the multiplier entirely."

        Design: Corner/state_machines/renewal_approval_expires_the_superseded_predecessor
        """
        ctx = setup_registered_filing()
        predecessor_id = ctx["registration"]["id"]

        renewal = open_filing(
            ctx["organization"]["id"],
            ctx["financial_statement"]["id"],
            "CA",
            "RENEWAL",
            fiscal_year=2027,
            coverage_start="2026-07-01T00:00:00Z",
            coverage_end="2027-07-01T00:00:00Z",
            supersedes_registration_id=predecessor_id,
        )
        attach_required_documents(
            renewal["id"],
            ctx["preparer"]["id"],
            renewal["required_financial_attestation"],
        )
        validate_success(
            submit_filing(
                renewal["id"],
                ctx["certifier"]["id"],
                certification_note="Annual renewal certified.",
            )
        )

        approved = validate_success(approve_filing(renewal["id"]))

        assert approved["status"] == "REGISTERED", (
            f"The renewal registers, got {approved['status']}"
        )
        assert approved["filing_fee_cents"] == 16_000, (
            "15,000 tier base plus 1,000 surcharge with no initial multiplier, got "
            f"{approved['filing_fee_cents']}"
        )
        assert approved["renewal_due_date"] == "2027-11-14T00:00:00.000Z", (
            "A June 2027 fiscal year end plus four months and fifteen days, got "
            f"{approved['renewal_due_date']}"
        )
        assert read_registration(predecessor_id)["status"] == "EXPIRED", (
            "The superseded predecessor is retired in the same request"
        )
        organization = read_organization(ctx["organization"]["id"])
        assert organization["registered_state_count"] == 1, (
            "One filing left, one filing arrived, got "
            f"{organization['registered_state_count']}"
        )
        assert organization["delinquent_registration_count"] == 0, (
            f"Nothing is delinquent, got {organization['delinquent_registration_count']}"
        )
        assert organization["filing_posture"] == "CURRENT", (
            f"The charity is current, got {organization['filing_posture']}"
        )
