"""Ops-runs, quarter rollover, report snapshots, and the budget ledger trail."""
from test_helpers import (
    ADMIN,
    COORD,
    ApiErrorId,
    adjudicate_claim,
    assert_hours,
    assert_ledger_entry,
    assert_snapshot,
    assert_ts_equal,
    book_and_confirm,
    check_in_booking,
    check_out_visit,
    create_active_caregiver,
    create_active_provider,
    add_window,
    create_booking_payload,
    create_explicit_booking,
    create_program,
    decide_visit,
    api_client,
    get_claim_for_voucher,
    get_success_data,
    issue_voucher,
    make_caregiver_headers,
    make_provider_headers,
    pay_claim,
    run_ops_run,
    run_visit_through_checkout,
    set_clock,
    setup_service_world,
    setup_submitted_claim,
    setup_verified_service,
    submit_claim,
    validate_success,
)


def test_rollover_carryover_capped_at_25_percent(api):
    """PRD §3.13: "For each, the old allocation transitions to `CLOSED` with its
    buckets frozen as-is. A carryover is computed as the smaller of two quantities:
    the program's `quarterly_cap_hours` multiplied by `carryover_cap_pct` (default
    0.25), rounded half up to two decimal places; and the old allocation's
    `available_hours`. A new allocation is then created for the same caregiver for the
    next quarter with `granted_hours` equal to the program's `quarterly_cap_hours` plus
    the carryover, `available_hours` equal to `granted_hours`, all other buckets 0, and
    status `OPEN`."

    Design: Corner/calculations/rollover_carryover_capped_at_25_percent
    """
    program = create_program()
    ctx = create_active_caregiver(program=program)
    old_alloc = ctx["allocation"]
    issue_voucher(old_alloc["id"], ctx["caregiver"]["id"], 40)  # available 40.00
    set_clock("2026-07-01T00:00:00Z")  # Q2 period_end reached
    run_ops_run(program["id"], "QUARTER_ROLLOVER")

    old_after = validate_success(api.get_allocation(old_alloc["id"], COORD), 200)
    assert old_after["status"] == "CLOSED"

    open_allocs = get_success_data(
        api.list_allocations(COORD, params={"caregiver_id": ctx["caregiver"]["id"],
                                            "status": "OPEN"}))
    assert len(open_allocs) == 1
    new_alloc = open_allocs[0]
    # carryover = min(round(80 x 0.25, 2), 40.00) = 20.00; granted = 80 + 20 = 100.00.
    assert_hours(new_alloc["granted_hours"], 100.00, "new granted_hours")
    assert_hours(new_alloc["available_hours"], 100.00, "new available_hours")
    assert_ts_equal(new_alloc["period_start"], "2026-07-01T00:00:00Z", "new period_start")


def test_utilization_projected_vs_settled_snapshot(api):
    """PRD §3.13: "The snapshot's `utilization_projected_pct` is 100 multiplied by the
    sum of `consumed_hours` and `reserved_hours` across all of the program's
    allocations (in any status), divided by the sum of `granted_hours`, rounded half up
    to two decimal places"
    PRD §3.13: "The `utilization_settled_pct` is 100 multiplied by the program's
    `settled_cents` divided by `total_budget_cents`, rounded half up to two decimal
    places."
    PRD §3.13: "The two figures deliberately differ: projected counts
    reserved-not-yet-consumed hours, while settled counts only paid money."

    Design: Corner/calculations/utilization_projected_vs_settled_snapshot
    """
    ctx = setup_submitted_claim()  # Monday-evening 2h; claim 7500 SUBMITTED
    adjudicate_claim(ctx["claim"]["id"], "APPROVE")
    pay_claim(ctx["claim"]["id"])
    # consumed 2.00h on the allocation; settled 7500 cents.
    voucher2 = issue_voucher(ctx["allocation"]["id"], ctx["caregiver"]["id"], 10)
    set_clock("2026-05-04T22:00:00Z")
    snapshot = run_ops_run(ctx["program"]["id"], "STANDARD")
    assert_snapshot(snapshot)
    # projected = 100 x (2 consumed + 10 reserved) / 80 granted = 15.00
    assert_hours(snapshot["utilization_projected_pct"], 15.00, "utilization_projected_pct")
    # settled = 100 x 7500 / 50000000 = 0.015 -> 0.02 (round half up, 2dp)
    assert_hours(snapshot["utilization_settled_pct"], 0.02, "utilization_settled_pct")
    assert snapshot["total_paid_amount_cents"] == 7500
    assert snapshot["claims_paid_count"] == 1


def test_ops_run_generates_snapshot_and_bumps_index(api):
    """PRD §3.13: "The ops-run also creates a new `ReportSnapshot` in `GENERATED`
    status"
    PRD §2.10: "Each ops-run increments the program's `ops_run_index` (which starts at
    0 on program creation) by 1 and bumps `Program.version` by 1."
    PRD §3.13: "`ops_run_index` (the program's value at generation)".

    Design: Corner/endpoints/ops_run_generates_snapshot_and_bumps_index
    """
    program = create_program()
    assert program["ops_run_index"] == 0
    snapshot = run_ops_run(program["id"], "STANDARD")
    assert snapshot["status"] == "GENERATED"
    assert snapshot["ops_run_index"] == 1
    after = validate_success(api.get_program(program["id"], ADMIN), 200)
    assert after["ops_run_index"] == 1


def test_ledger_records_verify_swap_entries(api):
    """PRD §3.4: "A `BudgetLedgerEntry` of `entry_type` `ENCUMBER` is appended for the
    provisional amount"
    PRD §3.9: "On the budget side, the voucher's provisional encumbrance is released
    (a `RELEASE` ledger entry) and the claim's `amount_cents` is encumbered (an
    `ENCUMBER` ledger entry)."
    PRD §3.1: "The ledger itself is readable by `FunderAdmin` and `Coordinator` and may
    be filtered by `entry_type`; entries are returned newest first."

    Design: Corner/endpoints/budget_ledger_records_verify_swap_entries
    """
    ctx = setup_verified_service()  # voucher 20h: ENCUMBER 60000, then swap on verify
    entries = get_success_data(api.list_budget_ledger(ctx["program"]["id"], ADMIN))
    assert len(entries) == 3
    # Newest first: claim encumbrance, provisional release, voucher-issue encumbrance.
    assert entries[0]["entry_type"] == "ENCUMBER" and entries[0]["amount_cents"] == 7500
    assert entries[1]["entry_type"] == "RELEASE" and entries[1]["amount_cents"] == 60000
    assert entries[2]["entry_type"] == "ENCUMBER" and entries[2]["amount_cents"] == 60000


def test_ledger_entry_has_no_version(api):
    """PRD §2.4: "One entity deviates from this pattern: `BudgetLedgerEntry` is an
    append-only fact table and carries only `id` and `created_at`. It has no
    `updated_at` and no `version`, because ledger entries are never mutated after
    being written."
    PRD §3.4: "A `BudgetLedgerEntry` of `entry_type` `ENCUMBER` is appended for the
    provisional amount"

    Design: Corner/entities/budget_ledger_entry_immutable_no_version
    """
    ctx = create_active_caregiver()
    issue_voucher(ctx["allocation"]["id"], ctx["caregiver"]["id"], 5)
    entries = get_success_data(api.list_budget_ledger(ctx["program"]["id"], ADMIN))
    assert len(entries) == 1
    assert_ledger_entry(entries[0])
    assert entries[0]["entry_type"] == "ENCUMBER"
    assert entries[0]["amount_cents"] == 15000  # 5h x 3000 cents/h


class TestPerClaimRoundingThenSum:
    def _two_saturday_claims_paid(self, api):
        """Two 25-minute Saturday visits with an ENHANCED provider; both claims paid."""
        program = create_program()
        ctx = create_active_caregiver(program=program)
        provider = create_active_provider(name="Prov Enh", credential_level="ENHANCED")
        window = add_window(provider["id"], "2026-05-02T09:00:00Z",
                            "2026-05-02T13:00:00Z", 1)
        cg_id = ctx["caregiver"]["id"]
        claims = []
        for start, end, cin, cout in (
            ("2026-05-02T10:00:00Z", "2026-05-02T10:25:00Z",
             "2026-05-02T10:00:00Z", "2026-05-02T10:25:00Z"),
            ("2026-05-02T11:00:00Z", "2026-05-02T11:25:00Z",
             "2026-05-02T11:00:00Z", "2026-05-02T11:25:00Z"),
        ):
            voucher = issue_voucher(ctx["allocation"]["id"], cg_id, 1)
            booking = create_explicit_booking(voucher["id"], cg_id, provider["id"],
                                              window["id"], start, end)
            booking = get_success_data(api.confirm_booking(
                booking["id"], make_provider_headers(provider["id"])))
            visit = check_in_booking(booking["id"], provider["id"], cin)
            visit = check_out_visit(visit["id"], provider["id"], cout)
            decide_visit(visit["id"], "VERIFY")
            claims.append(get_claim_for_voucher(voucher["id"]))
        for claim in claims:
            submit_claim(claim["id"], provider["id"])
            adjudicate_claim(claim["id"], "APPROVE")
            pay_claim(claim["id"])
        return ctx, claims

    def test_each_claim_rounded_individually(self, api):
        """PRD §2.7: "Monetary amounts are integer cents; each claim is rounded
        individually at creation"
        PRD §3.9: "`payable_minutes` is the smaller of `verified_minutes` and the floor
        of the booking's `committed_minutes` multiplied by the program's
        `max_overage_pct`."

        Design: Difficulty/combinatorial_formula/per_claim_rounding_then_sum_in_report
        """
        _ctx, claims = self._two_saturday_claims_paid(api)
        # 25 committed minutes: cap floor(25 x 1.10) = 27 payable; verified 30 -> 27.
        # 27 x 3000 x 1.5 (Saturday) x 1.10 (ENHANCED) / 60 = 2227.5 -> 2228 half-up.
        for claim in claims:
            assert claim["amount_cents"] == 2228

    def test_report_sums_rounded_integers(self, api):
        """PRD §2.7: "downstream aggregates such as `total_paid_amount_cents` on a
        report snapshot sum those per-claim rounded integers rather than re-rounding a
        sum of unrounded values."
        PRD §3.13: "`total_paid_amount_cents` (the integer sum of `amount_cents` across
        those claims — note this sums per-claim rounded amounts and never re-rounds)".

        Design: Difficulty/combinatorial_formula/per_claim_rounding_then_sum_in_report
        """
        ctx, _claims = self._two_saturday_claims_paid(api)
        set_clock("2026-05-02T12:00:00Z")
        snapshot = run_ops_run(ctx["program"]["id"], "STANDARD")
        # 2228 + 2228 = 4456 (sum-then-round of 4455.0 would give 4455).
        assert snapshot["total_paid_amount_cents"] == 4456
