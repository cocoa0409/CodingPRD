"""Batch net computation, GL trial balance, cardinality invariants, recon."""
from test_helpers import (
    ApiErrorId,
    assert_gl_posting,
    assert_gl_trial_balance,
    cancel_file_ok,
    close_entry_ok,
    dispatch_batch_ok,
    entry_payload,
    get_success_data,
    list_gl_postings,
    make_finance_headers,
    read_batch,
    read_entry,
    read_file,
    reconcile_batch_ok,
    register_return_ok,
    represent_ok,
    setup_file_with_entries,
    setup_released_file,
    setup_settled_file,
    setup_standard_environment,
    settle_batch_ok,
    validate_error,
)


def _setup_two_files_one_batch():
    """Files A (DEBIT 3000000 + DEBIT 2000000) and B (CREDIT 1000000), both
    NEXT_DAY effective 2026-08-03, released into the same auto-created batch.
    Originator discount is 333 bps. Returns (org, file_a, file_b, batch_id)."""
    org = setup_standard_environment("Epsilon Co",
                                     exposure_limit_cents=100_000_000,
                                     fee_discount_bps=333,
                                     clock="2026-08-03T13:00:00Z")
    file_a, batch_id = setup_released_file(org, [
        entry_payload("DEBIT", 3_000_000, "e-1"),
        entry_payload("DEBIT", 2_000_000, "e-2"),
    ])
    file_b, batch_b = setup_released_file(org, [
        entry_payload("CREDIT", 1_000_000, "e-3"),
    ])
    assert batch_b == batch_id, \
        "same (window_kind, settlement_date) must land in one batch"
    return org, file_a, file_b, batch_id


class TestBatchNetPinnedEvaluationOrder:
    def test_release_computes_per_file_assessed_fees(self, api):
        """PRD 3.5: "Second, the fee total is the sum of `assessed_fee_cents`
        over the batch's dispatched files — each file's fee having been computed
        at release from that file's own entries, never from batch membership."

        Design: Difficulty/combinatorial_formula/batch_net_pinned_evaluation_order
        """
        _, file_a, file_b, batch_id = _setup_two_files_one_batch()

        # NEXT_DAY card 60/200/100 with 333 bps discount: rhu(60*.9667) = 58.
        assert read_file(file_a["id"])["assessed_fee_cents"] == 316  # 200+58+58
        assert read_file(file_b["id"])["assessed_fee_cents"] == 258  # 200+58

        dispatched = dispatch_batch_ok(batch_id)
        # principal 3000000 + 2000000 - 1000000 = 4000000; fees 574.
        assert dispatched["expected_net_cents"] == 3_999_426

    def test_settle_posts_matching_net_and_reconciles(self, api):
        """PRD 3.5: "First, the principal net is the sum over the batch's
        dispatched entries where each `DEBIT` entry contributes its
        `amount_cents` positively and each `CREDIT` entry contributes it
        negatively."
        PRD 3.5: "The expected net is the principal net minus the fee total plus
        this re-flow adjustment."
        PRD 3.5: "The batch's `posted_net_cents` is then computed as the signed
        sum of its own GlPosting rows — credits minus debits — on the
        `ORIGINATOR_RECEIVABLE` account code"
        PRD 3.5: "A successful reconcile moves the batch to `RECONCILED` and
        records the caller as `reconciled_by_user_id`, which stays unset until
        that moment."

        Design: Difficulty/combinatorial_formula/batch_net_pinned_evaluation_order
        """
        _, _, _, batch_id = _setup_two_files_one_batch()

        dispatch_batch_ok(batch_id)
        settled = settle_batch_ok(batch_id)
        assert settled["posted_net_cents"] == 3_999_426

        reconciled = reconcile_batch_ok(batch_id, user_id="fin-1")
        assert reconciled["status"] == "RECONCILED"
        assert reconciled["recon_variance_cents"] == 0
        assert reconciled["reconciled_by_user_id"] == "fin-1"


def _setup_return_and_represent_before_second_batch():
    """B1 settles entry X (DEBIT 2000000); X is returned R01 and re-presented
    BEFORE B2's dispatch, so both sweep items are inside B2's expected net.
    B2 carries file F2 (entry Y DEBIT 700000, fee 260).
    Returns (org, x_id, f2_id, b2_id)."""
    org = setup_standard_environment("Tau Ltd", exposure_limit_cents=100_000_000)
    _, _, entries = setup_settled_file(org, [entry_payload("DEBIT", 2_000_000, "t-x")])
    x_id = entries[0]["id"]

    register_return_ok(x_id, "R01")
    represent_ok(x_id)

    file_2, batch_2 = setup_released_file(
        org, [entry_payload("DEBIT", 700_000, "t-y")])
    return org, x_id, file_2, batch_2


class TestGlTrialBalanceAcrossReturnAndRepresent:
    def test_ledger_pairs_balance_across_swept_items(self, api):
        """PRD 3.5: "each settling entry posts a balanced settlement pair of
        **GlPosting** rows into the batch across the `SETTLEMENT_CLEARING` and
        `ORIGINATOR_RECEIVABLE` accounts: a `DEBIT` entry credits
        `ORIGINATOR_RECEIVABLE` for its `amount_cents`, while a `CREDIT` entry
        debits it, the clearing account taking the opposite leg."
        PRD 3.5: "its unposted return cases receive reversing ledger pairs here
        — debiting `ORIGINATOR_RECEIVABLE` when the returned entry was a
        `DEBIT`, crediting it when the entry was a `CREDIT` — and are marked
        `gl_posted` true"

        Design: Difficulty/compensating_invariant/gl_trial_balance_holds_across_return_and_represent
        """
        _, _, _, batch_2 = _setup_return_and_represent_before_second_batch()

        dispatch_batch_ok(batch_2)
        settle_batch_ok(batch_2)

        postings = list_gl_postings(batch_2)
        # Y settlement pair + F2 fee pair + X re-settlement pair + X's return
        # reversing pair = 8 rows.
        assert len(postings) == 8
        for posting in postings:
            assert_gl_posting(posting)
        total = assert_gl_trial_balance(postings)
        assert total == 4_700_260, \
            "700000 + 260 + 2000000 + 2000000 on each leg"

    def test_swept_representment_settles_and_nets_match(self, api):
        """PRD 3.5: "its re-presented entries (in `TRANSMITTED` with
        `representment_count` of at least 1, outside this batch's dispatch set)
        advance to `SETTLED` with settlement pairs posted here"
        PRD 3.5: "The attempt computes `recon_variance_cents` as
        `posted_net_cents` minus `expected_net_cents` and requires the variance
        to be exactly zero; any nonzero variance is rejected with
        `ERR_RECONCILIATION_MISMATCH`."

        Design: Difficulty/compensating_invariant/gl_trial_balance_holds_across_return_and_represent
        """
        _, x_id, _, batch_2 = _setup_return_and_represent_before_second_batch()

        dispatched = dispatch_batch_ok(batch_2)
        # 700000 - 260 + (-2000000 return + 2000000 re-presentment) snapshot.
        assert dispatched["expected_net_cents"] == 699_740

        settled = settle_batch_ok(batch_2)
        assert settled["posted_net_cents"] == 699_740
        assert read_entry(x_id)["status"] == "SETTLED"

        reconciled = reconcile_batch_ok(batch_2)
        assert reconciled["recon_variance_cents"] == 0
        assert reconciled["status"] == "RECONCILED"


def _setup_cardinality_scenario():
    """File A (DEBIT 100000 + DEBIT 200000, WAREHOUSED) and file B
    (DEBIT 400000, settled). Returns (org, file_a, file_b, entry_b)."""
    org = setup_standard_environment("Upsilon Ltd",
                                     exposure_limit_cents=100_000_000)
    file_a = setup_file_with_entries(org, [
        entry_payload("DEBIT", 100_000, "u-1"),
        entry_payload("DEBIT", 200_000, "u-2"),
    ])
    file_b, _, entries_b = setup_settled_file(
        org, [entry_payload("DEBIT", 400_000, "u-3")])
    return org, file_a, file_b, entries_b[0]


class TestFileEntryCardinalityConserved:
    def test_cancel_cascade_preserves_file_totals(self, api):
        """PRD 3.3: "`entry_count` and `total_amount_cents` are recomputed as
        the count and the `amount_cents` sum over all of the file's entries in
        every status — figures that only ever grow, since cancelled or returned
        entries still count"

        Design: Difficulty/compensating_invariant/file_entry_cardinality_conserved_through_lifecycle
        """
        org, file_a, _, _ = _setup_cardinality_scenario()

        cancelled = cancel_file_ok(file_a["id"], org["id"])
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["entry_count"] == 2
        assert cancelled["total_amount_cents"] == 300_000

    def test_return_and_close_preserve_file_totals(self, api,
                                                   operations_headers):
        """PRD 3.3: "`entry_count` and `total_amount_cents` are recomputed as
        the count and the `amount_cents` sum over all of the file's entries in
        every status — figures that only ever grow, since cancelled or returned
        entries still count"
        PRD 3.6: "Closing moves the entry to the terminal `CLOSED` status and
        moves any `OPEN` ReturnCase on the entry to its terminal `FINAL`
        disposition."

        Design: Difficulty/compensating_invariant/file_entry_cardinality_conserved_through_lifecycle
        """
        org, _, file_b, entry_b = _setup_cardinality_scenario()

        register_return_ok(entry_b["id"], "R01")
        closed = close_entry_ok(entry_b["id"], org["id"])
        assert closed["status"] == "CLOSED"

        after = read_file(file_b["id"])
        assert after["status"] == "SETTLED"
        assert after["entry_count"] == 1
        assert after["total_amount_cents"] == 400_000

        cases = get_success_data(
            api.list_return_cases(entry_b["id"], operations_headers))
        assert cases[0]["disposition"] == "FINAL"


def test_late_return_blocks_reconciliation(api, finance_headers):
    """PRD 3.5: "Because the expected net snapshots the sweep set at dispatch
    while settlement posts the set as it exists at settle, drift is possible by
    design: a return, re-presentment, or reversal that enters an affected
    originator's sweep set between dispatch and settle posts into the batch
    without ever having been in `expected_net_cents`, and the resulting variance
    will block reconciliation."
    PRD 3.5: "The attempt computes `recon_variance_cents` as `posted_net_cents`
    minus `expected_net_cents` and requires the variance to be exactly zero; any
    nonzero variance is rejected with `ERR_RECONCILIATION_MISMATCH`."

    Design: Corner/calculations/recon_mismatch_from_late_return
    """
    org = setup_standard_environment("Recon Co", exposure_limit_cents=100_000_000)
    _, batch_1, entries_1 = setup_settled_file(
        org, [entry_payload("DEBIT", 2_000_000, "rc-x")])
    x_id = entries_1[0]["id"]

    _, batch_2 = setup_released_file(org, [entry_payload("DEBIT", 700_000, "rc-y")])

    dispatched = dispatch_batch_ok(batch_2)
    # Empty sweep snapshot at dispatch: 700000 - 260 (fee) = 699740.
    assert dispatched["expected_net_cents"] == 699_740

    # The return lands between dispatch and settle — inside no expected net.
    register_return_ok(x_id, "R01")

    settled = settle_batch_ok(batch_2)
    # 700000 - 260 - 2000000 (late return reversing pair posted here).
    assert settled["posted_net_cents"] == -1_300_260

    res = api.reconcile_batch(batch_2, make_finance_headers("fin-1"))
    validate_error(res, ApiErrorId.ERR_RECONCILIATION_MISMATCH,
                   expected_status=422)

    after = read_batch(batch_2)
    assert after["recon_variance_cents"] == -2_000_000
    assert after["status"] == "SETTLED", \
        "a rejected reconcile must not advance the batch"
