"""CTR lifecycle: state machine, deadlines, filing channels, amendment lineage."""
from test_helpers import (
    ApiErrorId,
    create_ctr_in_draft,
    create_filed_ctr,
    create_validated_ctr,
    get_single_ctr_for_customer,
    get_success_data,
    list_ctrs_for_customer,
    make_admin_headers,
    make_analyst_headers,
    make_officer_headers,
    make_teller_headers,
    post_cash_txn,
    set_clock,
    setup_branch_and_customer,
    api_client,
    validate_error,
    validate_success,
)


class TestCtrDeadlineEfileVsPaperVariant:
    def test_efile_channel_marks_late_when_filed_after_efile_due(self, api):
        """PRD §3.5: "the filing is late exactly when `filed_at` is strictly later
        than 23:59:59.999 UTC on the applicable due date—the electronic deadline
        for `EFILE`, the paper deadline for `PAPER`—so filing on the due date
        itself is timely. The two channels diverge in practice: the same CTR
        filed on the same day is late under `EFILE` but timely under `PAPER`
        whenever the filing date falls after the fifteenth day and on or before
        the twenty-fifth."

        Design: Difficulty/dual_variant_calc/ctr_deadline_efile_vs_paper_variant
        """
        set_clock("2026-08-01T12:00:00Z")
        from test_helpers import create_branch, create_customer
        br1 = create_branch(name="Main", branch_code="BR1")
        ca = create_customer(legal_name="Alpha LLC", tin="11-1111111")
        cb = create_customer(legal_name="Beta LLC", tin="22-2222222")
        post_cash_txn(ca["id"], br1["id"], amount_cents=1_100_000,
                      occurred_at="2026-08-01T10:00:00Z")
        post_cash_txn(cb["id"], br1["id"], amount_cents=1_100_000,
                      occurred_at="2026-08-01T10:30:00Z")
        ctr_a = get_single_ctr_for_customer(ca["id"])
        ctr_b = get_single_ctr_for_customer(cb["id"])
        get_success_data(api_client.validate_ctr(ctr_a["id"], headers=make_analyst_headers("analyst-x")))
        get_success_data(api_client.validate_ctr(ctr_b["id"], headers=make_analyst_headers("analyst-x")))
        set_clock("2026-08-20T12:00:00Z")
        filed_a = get_success_data(api_client.file_ctr(
            ctr_a["id"], {"filing_channel": "EFILE"}, headers=make_officer_headers("officer-y"),
        ))
        filed_b = get_success_data(api_client.file_ctr(
            ctr_b["id"], {"filing_channel": "PAPER"}, headers=make_officer_headers("officer-y"),
        ))
        assert filed_a["business_date"] == "2026-08-01"
        assert filed_b["business_date"] == "2026-08-01"
        assert filed_a["due_date_efile"] == "2026-08-16"
        assert filed_a["due_date_paper"] == "2026-08-26"
        assert filed_a["filed_late"] is True
        assert filed_b["filed_late"] is False
        assert filed_a["status"] == "FILED"
        assert filed_b["status"] == "FILED"

    def test_due_dates_derived_at_creation(self, api):
        """PRD §3.5: "Deadline fields are derived at creation: `due_date_efile` is
        the business date plus 15 calendar days and `due_date_paper` is the
        business date plus 25 calendar days, both in `YYYY-MM-DD` form."

        Design: Difficulty/dual_variant_calc/ctr_deadline_efile_vs_paper_variant
        """
        branch, customer = setup_branch_and_customer()
        ctr = create_ctr_in_draft(customer["id"], branch["id"],
                                  occurred_at="2026-08-01T08:00:00Z")
        assert ctr["due_date_efile"] == "2026-08-16"
        assert ctr["due_date_paper"] == "2026-08-26"


class TestCtrBranchingRevertAndAutoAmendment:
    def test_ctr_revert_and_auto_amendment_required_full_chain(self, api):
        """PRD §3.5: "A `ComplianceAnalyst` may also return a validated report to
        draft, moving it `VALIDATED → DRAFT`, which clears `validated_by_id` to
        null and refreshes the snapshot from the current aggregation."
        PRD §3.5: "per §3.4 a CTR in `FILED` or `ACKNOWLEDGED` moves to
        `AMENDMENT_REQUIRED` when recomputed totals diverge from its snapshot".

        Design: Difficulty/non_linear_state_machine/ctr_branching_revert_and_auto_amendment_required
        """
        set_clock("2026-08-01T09:00:00Z")
        from test_helpers import create_branch, create_customer
        br1 = create_branch(name="Main", branch_code="BR1")
        c1 = create_customer(legal_name="Nora Lynn", tin="55-5555555")
        post_cash_txn(c1["id"], br1["id"], amount_cents=600_000,
                      occurred_at="2026-08-01T08:00:00Z")
        post_cash_txn(c1["id"], br1["id"], amount_cents=500_000,
                      occurred_at="2026-08-01T08:30:00Z")
        ctr = get_single_ctr_for_customer(c1["id"])
        v = get_success_data(api_client.validate_ctr(ctr["id"], headers=make_analyst_headers("analyst-x")))
        assert v["status"] == "VALIDATED"
        assert v["validated_by_id"] == "analyst-x"
        d = get_success_data(api_client.return_ctr_to_draft(ctr["id"], headers=make_analyst_headers("analyst-x")))
        assert d["status"] == "DRAFT"
        assert d["validated_by_id"] is None
        get_success_data(api_client.validate_ctr(ctr["id"], headers=make_analyst_headers("analyst-x")))
        f = get_success_data(api_client.file_ctr(
            ctr["id"], {"filing_channel": "EFILE"}, headers=make_officer_headers("officer-y"),
        ))
        assert f["status"] == "FILED"
        assert f["filed_late"] is False
        set_clock("2026-08-01T15:00:00Z")
        post_cash_txn(c1["id"], br1["id"], amount_cents=200_000,
                      occurred_at="2026-08-01T14:00:00Z")
        final = get_success_data(api_client.get_ctr(ctr["id"], headers=make_officer_headers()))
        assert final["status"] == "AMENDMENT_REQUIRED"
        assert final["snapshot_cash_in_cents"] == 1_100_000

    def test_validated_to_draft_refresh_drops_validator(self, api):
        """PRD §3.5: "A `ComplianceAnalyst` may also return a validated report to
        draft, moving it `VALIDATED → DRAFT`, which clears `validated_by_id` to
        null and refreshes the snapshot from the current aggregation."

        Independent confirmation: after return-to-draft, a new same-day deposit
        is visible in the refreshed DRAFT snapshot.

        Design: Difficulty/non_linear_state_machine/ctr_branching_revert_and_auto_amendment_required
        """
        branch, customer = setup_branch_and_customer()
        ctr = create_validated_ctr(customer["id"], branch["id"])
        assert ctr["snapshot_cash_in_cents"] == 1_100_000
        post_cash_txn(customer["id"], branch["id"], amount_cents=50_000,
                      occurred_at="2026-08-01T08:45:00Z")
        d = get_success_data(api_client.return_ctr_to_draft(
            ctr["id"], headers=make_analyst_headers("analyst-x"),
        ))
        assert d["status"] == "DRAFT"
        assert d["validated_by_id"] is None
        # Live refresh pulls the post-validation deposit
        assert d["snapshot_cash_in_cents"] == 1_150_000


class TestCtrSnapshotStaleness:
    def test_ctr_snapshot_stale_at_file_then_recover(self, api):
        """PRD §3.5: "Because aggregation may have moved since validation, filing
        additionally requires that the frozen snapshot still equal the current
        aggregation totals; a mismatch is rejected with `ERR_CTR_SNAPSHOT_STALE`."
        PRD §2.10 step 10: "Fiscal consistency at filing: the frozen CTR snapshot
        still equals the live aggregation totals, else `ERR_CTR_SNAPSHOT_STALE`."

        Design: Corner/validations/ctr_snapshot_stale_at_file_then_recover
        """
        branch, customer = setup_branch_and_customer()
        ctr = create_validated_ctr(customer["id"], branch["id"])
        assert ctr["snapshot_cash_in_cents"] == 1_100_000
        # one extra same-day deposit diverges the aggregation
        post_cash_txn(customer["id"], branch["id"], amount_cents=1,
                      occurred_at="2026-08-01T08:30:00Z")
        resp = api_client.file_ctr(
            ctr["id"], {"filing_channel": "EFILE"}, headers=make_officer_headers("officer-y"),
        )
        validate_error(resp, ApiErrorId.ERR_CTR_SNAPSHOT_STALE)
        # recovery: return-to-draft refreshes, then validate + file succeed
        get_success_data(api_client.return_ctr_to_draft(ctr["id"], headers=make_analyst_headers("analyst-x")))
        get_success_data(api_client.validate_ctr(ctr["id"], headers=make_analyst_headers("analyst-x")))
        filed = get_success_data(api_client.file_ctr(
            ctr["id"], {"filing_channel": "EFILE"}, headers=make_officer_headers("officer-y"),
        ))
        assert filed["status"] == "FILED"
        assert filed["snapshot_cash_in_cents"] == 1_100_001


class TestCtrTerminalLockdown:
    def test_ctr_superseded_terminal_lockdown(self, api):
        """PRD §3.5: "On success the original CTR transitions to the terminal
        `SUPERSEDED` state with its `version` incremented by one".
        PRD §2.10 step 6: "the requested action is a valid transition from the
        record's current status (else `ERR_INVALID_STATE_TRANSITION`)".

        Design: Corner/state_machines/ctr_superseded_terminal_lockdown
        """
        branch, customer = setup_branch_and_customer()
        filed = create_filed_ctr(customer["id"], branch["id"])
        amend = get_success_data(api_client.amend_ctr(
            filed["id"],
            {"amendment_reason": "fix", "expected_ctr_version": filed["version"]},
            headers=make_officer_headers("officer-y"),
        ))
        assert amend["filing_type"] == "CORRECTION"
        # SUPERSEDED is terminal: every action is rejected
        r1 = api_client.validate_ctr(filed["id"], headers=make_analyst_headers("analyst-x"))
        validate_error(r1, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        r2 = api_client.file_ctr(
            filed["id"], {"filing_channel": "EFILE"}, headers=make_officer_headers("officer-y"),
        )
        validate_error(r2, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        r3 = api_client.acknowledge_ctr(
            filed["id"], {"regulator_tracking_id": "TRK-1"}, headers=make_admin_headers(),
        )
        validate_error(r3, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    def test_ctr_voided_terminal_lockdown(self, api):
        """PRD §3.5: "a CTR in `DRAFT` or `VALIDATED` moves to the terminal
        `VOIDED` state when `ctr_required` flips false—with `validated_by_id`
        cleared to null when a validated report is voided."
        PRD §2.10 step 6: "the requested action is a valid transition from the
        record's current status (else `ERR_INVALID_STATE_TRANSITION`)".

        Design: Corner/state_machines/ctr_voided_terminal_lockdown
        """
        branch, customer = setup_branch_and_customer()
        post_cash_txn(customer["id"], branch["id"], amount_cents=700_000,
                      occurred_at="2026-08-01T08:00:00Z")
        txn2 = post_cash_txn(customer["id"], branch["id"], amount_cents=400_000,
                             occurred_at="2026-08-01T08:05:00Z")
        ctr = get_single_ctr_for_customer(customer["id"])
        # voiding the second transaction drops the total below threshold -> CTR voided
        get_success_data(api_client.void_cash_transaction(
            txn2["id"], {"void_reason": "error"}, headers=make_teller_headers("teller-1"),
        ))
        ctr_after = get_success_data(api_client.get_ctr(ctr["id"], headers=make_officer_headers()))
        assert ctr_after["status"] == "VOIDED"
        resp = api_client.validate_ctr(ctr["id"], headers=make_analyst_headers("analyst-x"))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)


class TestCtrAcknowledge:
    def test_ctr_acknowledge_requires_filed_and_acknowledge_happy_path(self, api):
        """PRD §3.5: "Regulator acknowledgement is recorded by a `SystemAdmin`,
        moving a `FILED` report `FILED → ACKNOWLEDGED`, stamping `acknowledged_at`
        and storing the supplied `regulator_tracking_id`."
        PRD §2.10 step 6: "the requested action is a valid transition from the
        record's current status (else `ERR_INVALID_STATE_TRANSITION`)".

        Design: Corner/state_machines/ctr_acknowledge_requires_filed_and_acknowledge_happy_path
        """
        set_clock("2026-08-01T09:00:00Z")
        from test_helpers import create_branch, create_customer
        br1 = create_branch(name="Main", branch_code="BR1")
        ca = create_customer(legal_name="Ack Ann", tin="70-7070707")
        cb = create_customer(legal_name="Ack Ben", tin="71-7171717")
        post_cash_txn(ca["id"], br1["id"], amount_cents=1_100_000,
                      occurred_at="2026-08-01T08:00:00Z")
        post_cash_txn(cb["id"], br1["id"], amount_cents=1_100_000,
                      occurred_at="2026-08-01T08:05:00Z")
        ctr_a = get_single_ctr_for_customer(ca["id"])
        ctr_b = get_single_ctr_for_customer(cb["id"])
        get_success_data(api_client.validate_ctr(ctr_b["id"], headers=make_analyst_headers("analyst-x")))
        get_success_data(api_client.file_ctr(
            ctr_b["id"], {"filing_channel": "EFILE"}, headers=make_officer_headers("officer-y"),
        ))
        # DRAFT cannot be acknowledged
        r1 = api_client.acknowledge_ctr(
            ctr_a["id"], {"regulator_tracking_id": "TRK-A"}, headers=make_admin_headers(),
        )
        validate_error(r1, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        # FILED -> ACKNOWLEDGED
        acked = get_success_data(api_client.acknowledge_ctr(
            ctr_b["id"], {"regulator_tracking_id": "TRK-B"}, headers=make_admin_headers(),
        ))
        assert acked["status"] == "ACKNOWLEDGED"
        assert acked["regulator_tracking_id"] == "TRK-B"
        assert acked["acknowledged_at"] == "2026-08-01T09:00:00.000Z"


class TestCtrFilingDeadlineBoundary:
    def test_filing_deadline_boundary_dates(self, api):
        """PRD §3.5: "the filing is late exactly when `filed_at` is strictly later
        than 23:59:59.999 UTC on the applicable due date—the electronic deadline
        for `EFILE`, the paper deadline for `PAPER`—so filing on the due date
        itself is timely."
        PRD §3.5: "each CTR exposes a read-time `is_late` flag: it is true exactly
        when the CTR's status is `DRAFT` or `VALIDATED` and the current logical
        date is later than `due_date_efile`."

        Design: Corner/calculations/filing_deadline_boundary_dates
        """
        set_clock("2026-08-01T09:00:00Z")
        from test_helpers import create_branch, create_customer
        br1 = create_branch(name="Main", branch_code="BR1")
        ca = create_customer(legal_name="Late Larry", tin="18-1818181")
        cb = create_customer(legal_name="Timely Tina", tin="19-1919191")
        post_cash_txn(ca["id"], br1["id"], amount_cents=1_100_000,
                      occurred_at="2026-08-01T08:00:00Z")
        post_cash_txn(cb["id"], br1["id"], amount_cents=1_100_000,
                      occurred_at="2026-08-01T08:05:00Z")
        ctr_a = get_single_ctr_for_customer(ca["id"])
        ctr_b = get_single_ctr_for_customer(cb["id"])
        get_success_data(api_client.validate_ctr(ctr_b["id"], headers=make_analyst_headers("analyst-x")))
        # On the due date itself: not late yet
        set_clock("2026-08-16T23:59:59Z")
        ctr_a_on_due = get_success_data(api_client.get_ctr(ctr_a["id"], headers=make_officer_headers()))
        assert ctr_a_on_due["is_late"] is False
        # Filing at the due instant is timely
        filed_b = get_success_data(api_client.file_ctr(
            ctr_b["id"], {"filing_channel": "EFILE"}, headers=make_officer_headers("officer-y"),
        ))
        assert filed_b["filed_late"] is False
        # After the due date: late
        set_clock("2026-08-17T00:00:00Z")
        ctr_a_after = get_success_data(api_client.get_ctr(ctr_a["id"], headers=make_officer_headers()))
        assert ctr_a_after["is_late"] is True


class TestAmendmentLineageInvariant:
    def test_amendment_lineage_conserves_single_live_ctr(self, api):
        """PRD §3.5: "On success the original CTR transitions to the terminal
        `SUPERSEDED` state with its `version` incremented by one, and a successor
        CTR is created in `DRAFT` with `filing_type` set to `CORRECTION`,
        `prior_ctr_id` set to the superseded report's id, `amendment_reason`
        recorded from the request, and its snapshot taken from the current
        aggregation. The successor then flows through validation and filing like
        any other report."
        PRD §3.5: "at most one live CTR exists per (`customer_id`, `business_date`)
        pair."

        Design: Difficulty/compensating_invariant/amendment_lineage_conserves_single_live_ctr
        """
        set_clock("2026-08-01T09:00:00Z")
        from test_helpers import create_branch, create_customer
        br1 = create_branch(name="Main", branch_code="BR1")
        c1 = create_customer(legal_name="Lineage Len", tin="22-3333333")
        post_cash_txn(c1["id"], br1["id"], amount_cents=1_100_000,
                      occurred_at="2026-08-01T08:00:00Z")
        ctr1 = get_single_ctr_for_customer(c1["id"])
        get_success_data(api_client.validate_ctr(ctr1["id"], headers=make_analyst_headers("analyst-x")))
        get_success_data(api_client.file_ctr(
            ctr1["id"], {"filing_channel": "EFILE"}, headers=make_officer_headers("officer-y"),
        ))
        ctr1_after = get_success_data(api_client.get_ctr(ctr1["id"], headers=make_officer_headers()))
        set_clock("2026-08-01T10:00:00Z")
        ctr2 = get_success_data(api_client.amend_ctr(
            ctr1["id"],
            {"amendment_reason": "correct box 4", "expected_ctr_version": ctr1_after["version"]},
            headers=make_officer_headers("officer-y"),
        ))
        assert ctr2["filing_type"] == "CORRECTION"
        assert ctr2["prior_ctr_id"] == ctr1["id"]
        get_success_data(api_client.validate_ctr(ctr2["id"], headers=make_analyst_headers("analyst-x")))
        get_success_data(api_client.file_ctr(
            ctr2["id"], {"filing_channel": "EFILE"}, headers=make_officer_headers("officer-y"),
        ))
        ctr2_after = get_success_data(api_client.get_ctr(ctr2["id"], headers=make_officer_headers()))
        set_clock("2026-08-02T09:00:00Z")
        ctr3 = get_success_data(api_client.amend_ctr(
            ctr2["id"],
            {"amendment_reason": "correct box 8", "expected_ctr_version": ctr2_after["version"]},
            headers=make_officer_headers("officer-y"),
        ))
        assert ctr3["prior_ctr_id"] == ctr2["id"]
        # Lineage: 3 CTRs total; exactly one non-SUPERSEDED
        resp = api_client.list_ctrs(
            headers=make_officer_headers(), params={"customer_id": c1["id"]},
        )
        body = resp.json()
        assert body["meta"]["total_count"] == 3
        statuses = [r["status"] for r in body["data"]]
        assert statuses == ["SUPERSEDED", "SUPERSEDED", "DRAFT"]
        non_superseded = [s for s in statuses if s != "SUPERSEDED"]
        assert len(non_superseded) == 1

    def test_amendment_lineage_chains_prior_id_per_hop(self, api):
        """PRD §3.5: "a successor CTR is created in `DRAFT` with `filing_type`
        set to `CORRECTION`, `prior_ctr_id` set to the superseded report's id,
        `amendment_reason` recorded from the request, and its snapshot taken
        from the current aggregation."
        PRD §3.5: "Clients can trace a correction lineage through the
        `prior_ctr_id` filter on the CTR list endpoint."

        Independent confirmation on a single amendment hop.

        Design: Difficulty/compensating_invariant/amendment_lineage_conserves_single_live_ctr
        """
        branch, customer = setup_branch_and_customer()
        filed = create_filed_ctr(customer["id"], branch["id"])
        successor = get_success_data(api_client.amend_ctr(
            filed["id"],
            {"amendment_reason": "typo fix", "expected_ctr_version": filed["version"]},
            headers=make_officer_headers("officer-y"),
        ))
        assert successor["filing_type"] == "CORRECTION"
        assert successor["prior_ctr_id"] == filed["id"]
        assert successor["amendment_reason"] == "typo fix"
        assert successor["status"] == "DRAFT"
        # predecessor is now SUPERSEDED with version bumped by one
        predecessor = get_success_data(api_client.get_ctr(filed["id"], headers=make_officer_headers()))
        assert predecessor["status"] == "SUPERSEDED"
        assert predecessor["version"] == filed["version"] + 1
