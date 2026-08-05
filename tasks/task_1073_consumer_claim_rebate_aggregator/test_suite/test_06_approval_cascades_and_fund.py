"""Approval cascades, OCC, payout clearing/reversal, and program reporting."""
from test_helpers import (
    validate_error, get_success_data, ApiErrorId, TEST_USERS,
)
from test_helpers import fixtures as fx

PM = TEST_USERS["program_manager_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]
REVIEWER = TEST_USERS["claim_reviewer_headers"]


def _file_submit_review(api, consumer, program_id, claimed,
                        bstart="2026-01-01T00:00:00Z", bend="2026-02-01T00:00:00Z"):
    claim = fx.create_claim(api, consumer, program_id, claimed_amount_cents=claimed,
                           benefit_period_start=bstart, benefit_period_end=bend)
    doc = fx.add_document(api, claim, consumer)
    fx.submit_claim(api, claim, consumer)
    fx.verify_document(api, doc["id"])
    fx.start_review(api, claim["id"])
    return claim


def _exhaust_program(api):
    """FIXED program (fund 20000) exhausted by approving claim1; sibling claim2
    (SUBMITTED) is auto-REJECTED by the exhaustion cascade.
    Returns (program_id, claim1_id, consumer2, claim2_id)."""
    fx.set_clock(api)
    program = fx.create_open_program(
        api, fund_total_cents=20000, advertised_amount_cents=20000,
        per_claim_cap_cents=20000, eligibility_min_purchase_cents=5000)
    pid = program["id"]
    c1 = fx.register_verified_consumer(api)
    claim1 = _file_submit_review(api, c1, pid, 25000)
    c2 = fx.register_verified_consumer(api)
    claim2 = fx.create_claim(api, c2, pid, claimed_amount_cents=25000)
    fx.add_document(api, claim2, c2)
    fx.submit_claim(api, claim2, c2)  # claim2 -> SUBMITTED (a live sibling)
    fx.approve_claim(api, claim1["id"], pid)  # debits 20000 -> exhausts -> rejects claim2
    return pid, claim1["id"], c2, claim2["id"]


class TestFundExhaustionCascade:
    """Difficulty transitive_cascade — approve -> payout -> DEBIT fund to 0 ->
    program EXHAUSTED -> sibling claim auto-REJECTED."""

    def test_exhaustion_rejects_sibling_claim(self, api):
        """PRD §3.5: "If debiting the fund brings `fund_remaining_cents` to exactly
        zero, the program automatically transitions from `OPEN` to `EXHAUSTED`."
        PRD §3.5: "every other claim of that program still sitting in `SUBMITTED`,
        `UNDER_REVIEW`, or `NEEDS_INFO` is transitioned to `REJECTED`".

        Design: Difficulty/transitive_cascade/approval_payout_fund_exhaust_reject_siblings
        """
        pid, claim1_id, _c2, claim2_id = _exhaust_program(api)
        assert get_success_data(api.get_claim(claim1_id, ADMIN))["status"] == "APPROVED"
        program = get_success_data(api.get_program(pid, PM))
        assert program["fund_remaining_cents"] == 0
        assert program["status"] == "EXHAUSTED"
        assert get_success_data(api.get_claim(claim2_id, ADMIN))["status"] == "REJECTED"

    def test_exhaustion_notifies_rejected_consumer(self, api):
        """PRD §3.5: "every other claim of that program still sitting in
        `SUBMITTED`, `UNDER_REVIEW`, or `NEEDS_INFO` is transitioned to `REJECTED`,
        and each such claim's consumer receives a `CLAIM_REJECTED` notification."

        Design: Difficulty/transitive_cascade/approval_payout_fund_exhaust_reject_siblings
        """
        _pid, _c1, c2, _claim2_id = _exhaust_program(api)
        notes = get_success_data(api.list_notifications(c2["id"], ADMIN))
        assert any(n["event_type"] == "CLAIM_REJECTED" for n in notes), \
            "expected a CLAIM_REJECTED notification for the auto-rejected sibling's consumer"


class TestDocumentRejectCascade:
    """Difficulty transitive_cascade — reject document pushes parent claim to
    NEEDS_INFO."""

    def test_document_reject_moves_claim_to_needs_info(self, api):
        """PRD §3.4: "it triggers a cascade: if the document's parent claim is
        currently in `SUBMITTED` or `UNDER_REVIEW`, that claim is pushed into
        `NEEDS_INFO`, its `needs_info_count` increments by one, and a `NEEDS_INFO`
        notification is dispatched to the consumer".

        Design: Difficulty/transitive_cascade/document_reject_cascades_claim_to_needs_info
        """
        ctx = fx.setup_claim_under_review(api, verify_doc=False)  # doc stays PENDING
        doc = get_success_data(api.reject_document(
            ctx["document"]["id"], "blurry receipt", REVIEWER))
        assert doc["status"] == "REJECTED"
        claim = get_success_data(api.get_claim(ctx["claim"]["id"], ADMIN))
        assert claim["status"] == "NEEDS_INFO"
        assert claim["needs_info_count"] == 1

    def test_document_reject_notifies_consumer(self, api):
        """PRD §3.4: "that claim is pushed into `NEEDS_INFO`, its `needs_info_count`
        increments by one, and a `NEEDS_INFO` notification is dispatched to the
        consumer".

        Design: Difficulty/transitive_cascade/document_reject_cascades_claim_to_needs_info
        """
        ctx = fx.setup_claim_under_review(api, verify_doc=False)
        get_success_data(api.reject_document(ctx["document"]["id"], "unreadable", REVIEWER))
        notes = get_success_data(api.list_notifications(ctx["consumer"]["id"], ADMIN))
        assert any(n["event_type"] == "NEEDS_INFO" for n in notes), \
            "expected a NEEDS_INFO notification after document rejection cascade"


class TestApproveInvalidStateBeatsFiscal:
    """Difficulty priority_pair_validation_conflict — the state check (priority 5)
    precedes the fiscal fund check (priority 16)."""

    def test_approve_rejected_claim_on_exhausted_fund_reports_invalid_state(self, api):
        """PRD §2.11: "state — the target resource is in a state that permits the
        requested transition, else `ERR_INVALID_STATE`; and only then (6) the
        business-rule checks specific to the operation."

        Design: Difficulty/priority_pair_validation_conflict/approve_invalid_state_beats_fund_exhausted
        """
        pid, _claim1_id, _c2, claim2_id = _exhaust_program(api)  # claim2 is REJECTED, fund 0
        version = get_success_data(api.get_program(pid, PM))["version"]
        resp = api.approve_claim(claim2_id, version, REVIEWER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
        assert get_success_data(api.get_claim(claim2_id, ADMIN))["status"] == "REJECTED"
        assert get_success_data(api.get_program(pid, PM))["fund_remaining_cents"] == 0

    def test_approve_draft_claim_on_exhausted_fund_reports_invalid_state(self, api):
        """PRD §3.5: "first the claim must actually be `UNDER_REVIEW`, else
        `ERR_INVALID_STATE`".

        Design: Difficulty/priority_pair_validation_conflict/approve_invalid_state_beats_fund_exhausted
        """
        pid, _claim1_id, _c2, _claim2_id = _exhaust_program(api)  # fund exhausted (0)
        c3 = fx.register_verified_consumer(api)
        draft = fx.create_claim(api, c3, pid, claimed_amount_cents=25000,
                               benefit_period_start="2026-05-01T00:00:00Z",
                               benefit_period_end="2026-06-01T00:00:00Z")  # stays DRAFT
        version = get_success_data(api.get_program(pid, PM))["version"]
        resp = api.approve_claim(draft["id"], version, REVIEWER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


class TestPayoutClearRequiresVerified:
    """Difficulty cross_entity_state_dependency — payout clear gated on the
    recipient consumer's identity_status."""

    def _approved_claim_unverified(self, api):
        fx.set_clock(api)
        program = fx.create_open_program(api)  # fund 100000
        pid = program["id"]
        consumer = fx.register_consumer(api)  # UNVERIFIED; optimistic risk 20 < 50
        claim = _file_submit_review(api, consumer, pid, 25000)
        fx.approve_claim(api, claim["id"], pid)
        payout = fx.first_payout(api, claim["id"])
        return consumer, claim, payout

    def test_clear_unverified_consumer_rejected(self, api):
        """PRD §3.7: "the recipient consumer's `identity_status` must be
        `VERIFIED`, else `ERR_CONSUMER_NOT_VERIFIED`".

        Design: Difficulty/cross_entity_state_dependency/payout_clear_requires_consumer_verified
        """
        _consumer, claim, payout = self._approved_claim_unverified(api)
        resp = api.clear_payout(payout["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_CONSUMER_NOT_VERIFIED.value)
        still = get_success_data(api.list_payouts(claim["id"], ADMIN))[0]
        assert still["status"] == "INITIATED"

    def test_clear_succeeds_once_consumer_verified(self, api):
        """PRD §3.7: "On a successful clear, the consumer's `total_recovered_cents`
        grows by the payout's `net_amount_cents`, and the consumer receives a
        `PAYOUT_CLEARED` notification."

        Design: Difficulty/cross_entity_state_dependency/payout_clear_requires_consumer_verified
        """
        consumer, _claim, payout = self._approved_claim_unverified(api)
        fx.verify_consumer(api, consumer["id"])
        cleared = get_success_data(api.clear_payout(payout["id"], ADMIN))
        assert cleared["status"] == "CLEARED"


class TestPayoutReversalRestoresFund:
    """Difficulty compensating_invariant — reversal credits the program fund back."""

    def test_reversal_restores_fund_remaining(self, api):
        """PRD §3.7: "It credits the program's fund by the payout's
        `gross_amount_cents` — writing a `FundTransaction` of `type` `CREDIT` and
        `reason` `PAYOUT_REVERSAL` with the resulting `balance_after_cents`,
        recomputing `fund_remaining_cents`".

        Design: Difficulty/compensating_invariant/payout_reversal_restores_program_fund
        """
        ctx = fx.setup_cleared_payout(api)  # fund 100000, gross 20000 -> remaining 80000
        get_success_data(api.reverse_payout(ctx["payout"]["id"], ADMIN, {"reason": "clawback"}))
        program = get_success_data(api.get_program(ctx["program"]["id"], PM))
        assert program["fund_remaining_cents"] == 100000

    def test_reversal_writes_credit_ledger_entry(self, api):
        """PRD §2.8: "a credit at reversal — is recorded as an immutable
        `FundTransaction` capturing the `program_id`, the `related_claim_id` that
        caused it, a `type` of `DEBIT` or `CREDIT`, the absolute `amount_cents`
        moved, a `reason` of `PAYOUT_COMMIT` or `PAYOUT_REVERSAL`, and the
        `balance_after_cents` equal to the program's `fund_remaining_cents`
        immediately after the transaction."

        Design: Difficulty/compensating_invariant/payout_reversal_restores_program_fund
        """
        ctx = fx.setup_cleared_payout(api)
        get_success_data(api.reverse_payout(ctx["payout"]["id"], ADMIN, {"reason": "clawback"}))
        ledger = get_success_data(api.get_fund_transactions(ctx["program"]["id"], PM))
        credits = [t for t in ledger if t["reason"] == "PAYOUT_REVERSAL"]
        assert len(credits) == 1
        assert credits[0]["type"] == "CREDIT"
        assert credits[0]["amount_cents"] == 20000
        assert credits[0]["balance_after_cents"] == 100000


class TestPayoutReversalRestoresRecovery:
    """Difficulty compensating_invariant — reversal unwinds the consumer's
    total_recovered_cents."""

    def test_reversal_zeroes_total_recovered(self, api):
        """PRD §3.7: "It also unwinds the recovery it recorded, subtracting the
        payout's `net_amount_cents` from the consumer's `total_recovered_cents`."

        Design: Difficulty/compensating_invariant/payout_reversal_restores_consumer_recovery
        """
        ctx = fx.setup_cleared_payout(api)
        get_success_data(api.reverse_payout(ctx["payout"]["id"], ADMIN, {"reason": "clawback"}))
        consumer = get_success_data(api.get_consumer(ctx["consumer"]["id"], ADMIN))
        assert consumer["total_recovered_cents"] == 0
        assert ctx["payout"]["net_amount_cents"] == 16400

    def test_clear_grows_then_reversal_unwinds_recovery(self, api):
        """PRD §3.7: "On a successful clear, the consumer's `total_recovered_cents`
        grows by the payout's `net_amount_cents`". PRD §3.7: "A consumer's
        `total_recovered_cents` is precisely the sum of `net_amount_cents` across
        all of that consumer's payouts currently in `CLEARED` status."

        Design: Difficulty/compensating_invariant/payout_reversal_restores_consumer_recovery
        """
        ctx = fx.setup_cleared_payout(api)
        after_clear = get_success_data(api.get_consumer(ctx["consumer"]["id"], ADMIN))
        assert after_clear["total_recovered_cents"] == 16400
        get_success_data(api.reverse_payout(ctx["payout"]["id"], ADMIN))
        after_reverse = get_success_data(api.get_consumer(ctx["consumer"]["id"], ADMIN))
        assert after_reverse["total_recovered_cents"] == 0


def test_approve_stale_program_version_returns_412(api):
    """PRD §2.7: "When `expected_program_version` does not equal the program's
    current `version`, the approval is rejected with `ERR_STALE_PROGRAM_VERSION`
    (HTTP 412), preventing the reviewer from committing an allocation against a
    fund balance they have not actually observed."

    Design: Corner/validations/approve_stale_program_version_returns_412
    """
    fx.set_clock(api)
    program = fx.create_open_program(api)  # fund 100000
    pid = program["id"]
    stale_version = program["version"]
    c1 = fx.register_verified_consumer(api)
    claim1 = _file_submit_review(api, c1, pid, 25000)
    c2 = fx.register_verified_consumer(api)
    claim2 = _file_submit_review(api, c2, pid, 25000)
    fx.approve_claim(api, claim1["id"], pid)  # advances program.version
    resp = api.approve_claim(claim2["id"], stale_version, REVIEWER)
    validate_error(resp, ApiErrorId.ERR_STALE_PROGRAM_VERSION.value)
    assert get_success_data(api.get_claim(claim2["id"], ADMIN))["status"] == "UNDER_REVIEW"


def test_program_report_aggregates_after_payout(api):
    """PRD §3.9: "On the money side it reports `total_committed_cents` (the sum of
    `gross_amount_cents` across the program's payouts that have not been reversed)
    ... and `total_cleared_cents` (the sum of `net_amount_cents` across the
    program's payouts in `CLEARED` status)."

    Design: Corner/endpoints/program_report_aggregates_after_payout
    """
    ctx = fx.setup_cleared_payout(api)  # gross 20000, net 16400, fund 100000 -> 80000
    report = get_success_data(api.get_program_report(ctx["program"]["id"], PM))
    assert report["approved_claims"] == 1
    assert report["total_committed_cents"] == 20000
    assert report["total_cleared_cents"] == 16400
    assert report["fund_remaining_cents"] == 80000
