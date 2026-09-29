"""The audit review loop: submission variance, the remediation cycle and closure."""

from test_helpers import (
    ApiErrorId,
    assert_escrow_standing,
    assert_money_equal,
    assert_posture,
    assert_total_count,
    audit_findings,
    clear_finding,
    close_audit,
    create_audit,
    create_escrow_account,
    factories,
    post_snapshot,
    read_agency,
    require_remediation,
    review_audit,
    submit_audit,
    submit_remediation,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import AUDITOR, OFFICER


class TestAuditTransitionPreconditions:
    """Review is reachable only from `SUBMITTED`, and submission needs balances."""

    def test_draft_cannot_jump_straight_to_under_review(self, api, escrow_env):
        """`DRAFT` to `UNDER_REVIEW` is absent from the table, so it is a 409.

        PRD: "The requested transition exists from the resource's current state on the
        addressed dimension (`ERR_INVALID_STATE`, HTTP 409); the addressed dimension is
        not already terminal (`ERR_ALREADY_TERMINAL`, HTTP 409); and every other
        state-shaped precondition in this tier — frozen posture, closed escrow account,
        missing balance snapshot, empty statement, finding-population requirements, an
        issued policy blocking a void, and the escrow-standing bar on reinstatement."

        Design: Corner/state_machines/invalid_transition_escrow_audit_draft_to_under_review_returns_409
        """
        env, account = escrow_env
        audit = create_audit(api, env, account["id"])
        assert audit["status"] == "DRAFT", (
            f"the audit must start in DRAFT, got {audit['status']}"
        )

        response = api.transition_audit(
            audit["id"], factories.audit_state_payload("UNDER_REVIEW"), OFFICER
        )

        validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, 409)

        after = validate_success(api.get_escrow_audit(audit["id"], AUDITOR))
        assert after["status"] == "DRAFT", (
            f"the refused transition must leave the audit in DRAFT, got {after['status']}"
        )
        assert after["submitted_at"] is None, (
            f"submitted_at must still be null, got {after['submitted_at']!r}"
        )

    def test_an_empty_audit_can_only_be_closed_clean(self, api, env):
        """No snapshot, then no finding: three population preconditions in one run.

        PRD: "An adverse closure — `UNDER_REVIEW` to `CLOSED_ADVERSE` — instead requires
        that at least one finding have a `status` of `ESCALATED`, else
        `ERR_NO_ESCALATED_FINDING` (HTTP 409)."

        Design: Corner/errors/empty_audit_cannot_demand_remediation_or_close_adverse_returns_409
        """
        account = create_escrow_account(api, env)
        audit = create_audit(api, env, account["id"])

        no_snapshot = api.transition_audit(
            audit["id"], factories.audit_state_payload("SUBMITTED"), AUDITOR
        )
        validate_error(
            no_snapshot, ApiErrorId.ERR_BALANCE_SNAPSHOT_REQUIRED.value, 409
        )

        post_snapshot(api, env, account["id"])
        submitted = submit_audit(api, audit["id"])
        assert_money_equal(
            submitted["reconciliation_variance_cents"],
            0,
            "reconciliation_variance_cents on perfectly agreeing balances",
        )
        assert submitted["open_finding_count"] == 0, (
            f"no finding may be raised, got {submitted['open_finding_count']}"
        )
        assert submitted["risk_tier"] == "LOW", (
            f"an audit with no findings stays at LOW, got {submitted['risk_tier']}"
        )
        review_audit(api, audit["id"])

        no_open_finding = api.transition_audit(
            audit["id"],
            factories.audit_state_payload(
                "REMEDIATION_REQUIRED", note="Nothing to remediate"
            ),
            OFFICER,
        )
        validate_error(no_open_finding, ApiErrorId.ERR_NO_OPEN_FINDING.value, 409)

        no_escalated_finding = api.transition_audit(
            audit["id"],
            factories.audit_state_payload("CLOSED_ADVERSE", note="No escalation exists"),
            OFFICER,
        )
        validate_error(
            no_escalated_finding, ApiErrorId.ERR_NO_ESCALATED_FINDING.value, 409
        )

        closed = close_audit(
            api, audit["id"], "CLOSED_CLEAN", note="Reconciled with no exceptions"
        )
        assert closed["status"] == "CLOSED_CLEAN", (
            "the vacuously satisfied clean closure must be allowed, got "
            f"{closed['status']}"
        )
        agency = read_agency(api, env.agency_id)
        assert_money_equal(agency["defalcation_score"], 0, "defalcation_score")
        assert_escrow_standing(agency, "COMPLIANT")


class TestRemediationCycle:
    """The audit leaves `UNDER_REVIEW`, is re-submitted and re-enters it."""

    def test_a_corrected_snapshot_changes_the_variance_on_the_second_pass(
        self, api, env
    ):
        """6,000,000 on the first submission, 0 on the second, same audit row.

        PRD: "Because a re-submission reads the account's *current* snapshot, an agency
        that posts fresh balances between review loops will see a different
        `reconciliation_variance_cents` on the second pass than on the first."

        Design: Difficulty/non_linear_state_machine/escrow_audit_remediation_cycle_revisits_under_review
        """
        account = create_escrow_account(api, env)
        post_snapshot(api, env, account["id"], trial_balance_cents=4_000_000)
        audit = create_audit(api, env, account["id"])

        first_pass = submit_audit(api, audit["id"])
        assert_money_equal(
            first_pass["reconciliation_variance_cents"],
            6_000_000,
            "reconciliation_variance_cents on the first pass",
        )
        findings = audit_findings(api, audit["id"])
        assert len(findings) == 1, (
            f"one THREE_WAY_VARIANCE finding must be raised, got {len(findings)}"
        )
        assert findings[0]["severity"] == "CRITICAL", (
            "a 6,000,000 exposure is above 5,000,000, so the severity is CRITICAL, got "
            f"{findings[0]['severity']}"
        )
        review_audit(api, audit["id"])
        require_remediation(api, audit["id"], note="Restore the trust balance")
        submit_remediation(api, env, findings[0]["id"])
        post_snapshot(
            api,
            env,
            account["id"],
            trial_balance_cents=10_000_000,
            snapshot_as_of="2026-08-01",
        )

        second_pass = submit_audit(api, audit["id"])

        assert second_pass["status"] == "SUBMITTED", (
            f"the re-submission returns the audit to SUBMITTED, got {second_pass['status']}"
        )
        assert_money_equal(
            second_pass["reconciliation_variance_cents"],
            0,
            "reconciliation_variance_cents on the second pass",
        )

    def test_the_second_pass_re_enters_review_without_a_duplicate_finding(
        self, api, env
    ):
        """The cycle closes back on `UNDER_REVIEW` and the finding set stays at one.

        PRD: "On a re-submission out of `REMEDIATION_REQUIRED`, an auto-finding is created
        only for a condition that does not already have a finding on this audit whose
        `status` is `OPEN` or `REMEDIATION_SUBMITTED`, so the review loop does not
        accumulate duplicates."

        Design: Difficulty/non_linear_state_machine/escrow_audit_remediation_cycle_revisits_under_review
        """
        account = create_escrow_account(api, env)
        post_snapshot(api, env, account["id"], trial_balance_cents=4_000_000)
        audit = create_audit(api, env, account["id"])
        submit_audit(api, audit["id"])
        finding = audit_findings(api, audit["id"])[0]
        review_audit(api, audit["id"])
        require_remediation(api, audit["id"], note="Restore the trust balance")
        submit_remediation(api, env, finding["id"])
        post_snapshot(
            api,
            env,
            account["id"],
            trial_balance_cents=10_000_000,
            snapshot_as_of="2026-08-01",
        )
        submit_audit(api, audit["id"])

        second_review = review_audit(api, audit["id"])

        assert second_review["status"] == "UNDER_REVIEW", (
            "the audit must re-enter a state it had already left, got "
            f"{second_review['status']}"
        )
        _rows, meta = validate_paginated(api.list_findings(audit["id"], AUDITOR))
        assert_total_count(meta, 1)
        after = validate_success(api.get_finding(finding["id"], AUDITOR))
        assert after["status"] == "REMEDIATION_SUBMITTED", (
            "the original finding is untouched by the second pass, got "
            f"{after['status']}"
        )


class TestCleanClosureRequiresEveryFindingCleared:
    """The blocking condition is universal over the audit's children."""

    def test_a_finding_under_remediation_blocks_the_clean_closure(self, api, env):
        """One `REMEDIATION_SUBMITTED` child is enough to refuse `CLOSED_CLEAN`.

        PRD: "A clean closure — `UNDER_REVIEW` to `CLOSED_CLEAN` — additionally requires
        that *every* finding of the audit have a `status` of `CLEARED`, else
        `ERR_UNREMEDIATED_FINDING_PRESENT` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/audit_clean_closure_requires_every_finding_cleared_rejected
        """
        account = create_escrow_account(api, env)
        post_snapshot(api, env, account["id"], trial_balance_cents=9_800_000)
        audit = create_audit(api, env, account["id"])
        submitted = submit_audit(api, audit["id"])
        assert_money_equal(
            submitted["reconciliation_variance_cents"],
            200_000,
            "reconciliation_variance_cents",
        )
        finding = audit_findings(api, audit["id"])[0]
        assert finding["severity"] == "MEDIUM", (
            "a 200,000 exposure sits above 100,000 and at most 1,000,000, so the "
            f"severity is MEDIUM, got {finding['severity']}"
        )
        review_audit(api, audit["id"])
        under_remediation = submit_remediation(api, env, finding["id"])
        assert under_remediation["status"] == "REMEDIATION_SUBMITTED", (
            f"the finding must sit in REMEDIATION_SUBMITTED, got {under_remediation['status']}"
        )

        response = api.transition_audit(
            audit["id"],
            factories.audit_state_payload("CLOSED_CLEAN", note="Remediation accepted"),
            OFFICER,
        )

        validate_error(
            response, ApiErrorId.ERR_UNREMEDIATED_FINDING_PRESENT.value, 409
        )
        after = validate_success(api.get_escrow_audit(audit["id"], AUDITOR))
        assert after["status"] == "UNDER_REVIEW", (
            f"the audit must stay in UNDER_REVIEW, got {after['status']}"
        )
        assert after["closed_at"] is None, (
            f"closed_at must still be null, got {after['closed_at']!r}"
        )

    def test_clearing_the_only_finding_unblocks_the_same_closure(self, api, env):
        """The identical request succeeds once the child reaches `CLEARED`.

        PRD: "Both closures set `closed_by_user_id` to the acting `X-User-ID` and
        `closed_at` to the clock instant, both recompute the agency's `defalcation_score`
        under the rolling-window variant of Section 3.7 followed by `escrow_standing` and
        `oversight_posture`, and both increment `Agency.version` by 1."

        Design: Difficulty/cross_entity_state_dependency/audit_clean_closure_requires_every_finding_cleared_rejected
        """
        account = create_escrow_account(api, env)
        post_snapshot(api, env, account["id"], trial_balance_cents=9_800_000)
        audit = create_audit(api, env, account["id"])
        submit_audit(api, audit["id"])
        finding = audit_findings(api, audit["id"])[0]
        review_audit(api, audit["id"])
        submit_remediation(api, env, finding["id"])
        blocked = api.transition_audit(
            audit["id"],
            factories.audit_state_payload("CLOSED_CLEAN", note="Remediation accepted"),
            OFFICER,
        )
        validate_error(blocked, ApiErrorId.ERR_UNREMEDIATED_FINDING_PRESENT.value, 409)

        cleared = clear_finding(
            api,
            finding["id"],
            cleared_amount_cents=200_000,
            disposition_note="Funding verified against the bank statement",
        )
        assert cleared["status"] == "CLEARED", (
            f"the finding must reach CLEARED, got {cleared['status']}"
        )

        closed = close_audit(
            api, audit["id"], "CLOSED_CLEAN", note="Remediation accepted"
        )

        assert closed["status"] == "CLOSED_CLEAN", (
            f"the audit must now close clean, got {closed['status']}"
        )
        assert closed["closed_by_user_id"] == "officer-1", (
            "closed_by_user_id must hold the closing actor's identifier, got "
            f"{closed['closed_by_user_id']!r}"
        )
        assert closed["closed_at"] is not None, (
            "closed_at must be stamped with the clock instant, but it is null"
        )
        agency = read_agency(api, env.agency_id)
        assert_money_equal(agency["defalcation_score"], 0, "defalcation_score")
        assert_escrow_standing(agency, "COMPLIANT")


class TestImmediateDerivation:
    """Every consequence of a submission is visible in that submission's own response."""

    def test_the_submission_response_already_carries_its_derived_finding(
        self, api, env
    ):
        """The variance, the auto-finding and the tier land in one request.

        PRD: "When `reconciliation_variance_cents` is strictly greater than the
        reconciliation tolerance that governs the agency — the `three_way_tolerance_cents`
        of the state program attached to the agency's oldest appointment whose `status` is
        `ACTIVE`, taking the earliest `created_at` where several are active — a
        `THREE_WAY_VARIANCE` finding is created with its `exposure_cents` equal to that
        variance."

        Design: Corner/consistency_model/immediate_audit_submission_response_already_carries_its_derived_finding
        """
        account = create_escrow_account(api, env)
        snapshot = post_snapshot(
            api, env, account["id"], trial_balance_cents=4_000_000
        )
        assert_money_equal(
            snapshot["adjusted_bank_balance_cents"],
            10_000_000,
            "adjusted_bank_balance_cents",
        )
        assert_posture(read_agency(api, env.agency_id), "OPEN")
        audit = create_audit(api, env, account["id"])

        submitted = submit_audit(api, audit["id"])

        assert submitted["variance_method"] == "BANK_TO_TRIAL", (
            f"a SCHEDULED audit uses BANK_TO_TRIAL, got {submitted['variance_method']!r}"
        )
        assert_money_equal(
            submitted["reconciliation_variance_cents"],
            6_000_000,
            "reconciliation_variance_cents in the submission response",
        )
        assert submitted["open_finding_count"] == 1, (
            "the auto-raised finding is already counted in this response, got "
            f"{submitted['open_finding_count']}"
        )
        assert submitted["critical_finding_count"] == 1, (
            "the critical counter is already refreshed in this response, got "
            f"{submitted['critical_finding_count']}"
        )
        assert submitted["risk_tier"] == "CRITICAL", (
            f"the tier is already CRITICAL in this response, got {submitted['risk_tier']}"
        )

        rows, meta = validate_paginated(
            api.list_findings(
                audit["id"], AUDITOR, params={"code": "THREE_WAY_VARIANCE"}
            )
        )
        assert_total_count(meta, 1)
        assert_money_equal(rows[0]["exposure_cents"], 6_000_000, "exposure_cents")
        assert rows[0]["severity"] == "CRITICAL", (
            f"a 6,000,000 exposure is CRITICAL, got {rows[0]['severity']}"
        )
        assert rows[0]["status"] == "OPEN", (
            f"a new finding opens in OPEN, got {rows[0]['status']}"
        )
        assert rows[0]["is_repeat"] is False, (
            f"this is the account's first audit, so is_repeat is false, got {rows[0]['is_repeat']!r}"
        )

        agency = read_agency(api, env.agency_id)
        assert agency["open_critical_finding_count"] == 1, (
            "the mirrored agency counter is visible on the very next read, got "
            f"{agency['open_critical_finding_count']}"
        )
        assert_posture(agency, "RESTRICTED")
