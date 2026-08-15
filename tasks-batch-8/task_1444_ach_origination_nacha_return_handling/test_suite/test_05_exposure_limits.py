"""Outstanding-exposure variants, admission equality boundary, lifecycle reads."""
from test_helpers import (
    ApiErrorId,
    append_entries_ok,
    append_entries_payload,
    cancel_file_ok,
    create_warehoused_file,
    dispatch_batch_ok,
    entry_payload,
    make_originator_headers,
    read_file,
    read_originator,
    release_file_ok,
    setup_file_with_entries,
    setup_standard_environment,
    settle_batch_ok,
    validate_error,
    validate_success,
)


def _setup_gross_vs_debit():
    """ACTIVE originator (limit 10000000) + one NEXT_DAY file; appends run in
    the test body so each test controls the exact sequence."""
    org = setup_standard_environment("Gamma LLC", exposure_limit_cents=10_000_000)
    ach_file = create_warehoused_file(org, "CCD", "NEXT_DAY", "2026-08-03")
    return org, ach_file


def _run_three_appends(org, ach_file):
    """DEBIT 6000000, CREDIT 5000000, DEBIT 4000000 — debit lands on the limit."""
    f = append_entries_ok(ach_file["id"], [entry_payload("DEBIT", 6_000_000, "g-1")])
    f = append_entries_ok(ach_file["id"], [entry_payload("CREDIT", 5_000_000, "g-2")])
    f = append_entries_ok(ach_file["id"], [entry_payload("DEBIT", 4_000_000, "g-3")])
    return f


class TestGrossVsDebitExposure:
    def test_gross_counts_both_directions_debit_only_debits(self, api):
        """PRD 3.3: "The gross figure, `outstanding_exposure_gross_cents`, sums
        `amount_cents` across both directions and serves the reporting view on
        originator reads; the debit figure, `outstanding_exposure_debit_cents`,
        sums `DEBIT` entries only and is the figure the admission check
        enforces."

        Design: Difficulty/dual_variant_calc/exposure_gross_vs_debit_only
        """
        org, ach_file = _setup_gross_vs_debit()
        _run_three_appends(org, ach_file)

        after = read_originator(org["id"])
        assert after["outstanding_exposure_gross_cents"] == 15_000_000
        assert after["outstanding_exposure_debit_cents"] == 10_000_000

    def test_append_landing_exactly_on_limit_admitted(self, api):
        """PRD 3.3: "And the exposure admission check rejects the append with
        `ERR_EXPOSURE_LIMIT_EXCEEDED` whenever the originator's
        `outstanding_exposure_debit_cents` plus the incoming entries' debit
        total would come out strictly greater than `exposure_limit_cents`;
        landing exactly on the limit is admitted, and a batch of pure `CREDIT`
        entries never trips the check."

        Design: Difficulty/dual_variant_calc/exposure_gross_vs_debit_only
        """
        org, ach_file = _setup_gross_vs_debit()
        appended = _run_three_appends(org, ach_file)

        # 6000000 + 4000000 == 10000000 == exposure_limit_cents: admitted.
        assert appended["entry_count"] == 3
        assert appended["total_amount_cents"] == 15_000_000


def _setup_capacity_file():
    org = setup_standard_environment("Sigma SA", exposure_limit_cents=10_000_000)
    ach_file = create_warehoused_file(org, "CCD", "NEXT_DAY", "2026-08-03")
    f = append_entries_ok(ach_file["id"],
                          [entry_payload("DEBIT", 6_000_000, "s-1")])
    return org, f


class TestExposureAggregateCapacity:
    def test_exact_limit_admitted_crossing_rejected(self, api):
        """PRD 3.3: "And the exposure admission check rejects the append with
        `ERR_EXPOSURE_LIMIT_EXCEEDED` whenever the originator's
        `outstanding_exposure_debit_cents` plus the incoming entries' debit
        total would come out strictly greater than `exposure_limit_cents`;
        landing exactly on the limit is admitted, and a batch of pure `CREDIT`
        entries never trips the check."

        Design: Difficulty/resource_temporal_overlap/exposure_aggregate_capacity_equality
        """
        org, ach_file = _setup_capacity_file()

        at_limit = append_entries_ok(ach_file["id"],
                                     [entry_payload("DEBIT", 4_000_000, "s-2")])
        assert at_limit["entry_count"] == 2

        res = api.append_entries(
            ach_file["id"],
            append_entries_payload(at_limit["version"],
                                   [entry_payload("DEBIT", 1, "s-3")]),
            make_originator_headers(org["id"]))
        validate_error(res, ApiErrorId.ERR_EXPOSURE_LIMIT_EXCEEDED,
                       expected_status=422)

    def test_rejected_append_leaves_exposure_unchanged(self, api):
        """PRD 3.3: "The append is atomic: if any entry is rejected, no entry
        from the batch is persisted."

        Design: Difficulty/resource_temporal_overlap/exposure_aggregate_capacity_equality
        """
        org, ach_file = _setup_capacity_file()
        at_limit = append_entries_ok(ach_file["id"],
                                     [entry_payload("DEBIT", 4_000_000, "s-2")])

        res = api.append_entries(
            ach_file["id"],
            append_entries_payload(at_limit["version"],
                                   [entry_payload("DEBIT", 1, "s-3")]),
            make_originator_headers(org["id"]))
        validate_error(res, ApiErrorId.ERR_EXPOSURE_LIMIT_EXCEEDED,
                       expected_status=422)

        after = read_originator(org["id"])
        assert after["outstanding_exposure_debit_cents"] == 10_000_000
        assert read_file(ach_file["id"])["entry_count"] == 2


def test_exposure_read_tracks_lifecycle(api, operations_headers):
    """PRD 3.3: "Outstanding exposure itself is defined over the originator's
    entries in `WAREHOUSED` or `TRANSMITTED` status only — entries that have
    settled, returned, closed, or cancelled are excluded."
    PRD 3.3: "Exposure is recomputed whenever entries are created, whenever an
    entry changes status, and whenever a cancel or suspension cascade removes
    entries from the outstanding set."

    Design: Corner/endpoints/computed_exposure_read_after_lifecycle
    """
    org = setup_standard_environment("Comp Co")
    file_a = setup_file_with_entries(org, [entry_payload("DEBIT", 100_000, "cp-1")])
    file_b = setup_file_with_entries(org, [entry_payload("DEBIT", 200_000, "cp-2")])

    after_appends = read_originator(org["id"])
    assert after_appends["outstanding_exposure_debit_cents"] == 300_000
    assert after_appends["outstanding_exposure_gross_cents"] == 300_000

    cancel_file_ok(file_b["id"], org["id"])
    after_cancel = read_originator(org["id"])
    assert after_cancel["outstanding_exposure_debit_cents"] == 100_000

    released = release_file_ok(file_a["id"])
    dispatch_batch_ok(released["settlement_batch_id"])
    settle_batch_ok(released["settlement_batch_id"])
    after_settle = read_originator(org["id"])
    assert after_settle["outstanding_exposure_debit_cents"] == 0
    assert after_settle["outstanding_exposure_gross_cents"] == 0
