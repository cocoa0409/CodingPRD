"""Free-time billing (per-diem / storage), flip-fee settlement, and ledger
application (PRD §3.6, §3.8)."""
from test_helpers import (
    ApiErrorId,
    assert_ledger_entry,
    apply_ledger_payment,
    book_appointment,
    check_in,
    complete_transaction,
    create_arrived_train,
    create_carrier,
    create_chassis,
    create_pool,
    create_slot,
    create_terminal,
    enroll_carrier,
    get_carrier,
    get_ledger_entry,
    get_membership,
    ground_container,
    is_iso8601_timestamp,
    is_valid_uuid,
    list_ledger_entries,
    open_transaction,
    register_container,
    reserve_chassis,
    run_ops,
    set_clock,
    setup_completed_out_gate,
    setup_grounded_container,
    TEST_USERS,
    validate_error,
    validate_success,
)

TM = TEST_USERS["terminal_manager_headers"]
BC = TEST_USERS["billing_clerk_headers"]


class TestPerDiemProvisionalVsFinal:
    def test_run_ops_provisional_per_diem_snapshot(self, api):
        """PRD §3.8: "It takes the provisional billing snapshot: every container
        in `ON_GROUND` or `MOUNTED` whose `free_time_expires_at` is in the past
        receives a provisional `PER_DIEM` entry, and every such container still
        `ON_GROUND` additionally receives a provisional `STORAGE` entry." and
        "The charge is the number of days overdue — the elapsed time from
        `free_time_expires_at` to the evaluation moment, rounded up to whole
        days; zero when the evaluation moment has not passed expiry —
        multiplied by the terminal's `per_diem_rate_cents`."

        Grounded 2026-08-01T00:00:00Z with gate_free_hours=48, so free time
        expires 2026-08-03T00:00:00Z; the checkpoint at 2026-08-05T12:00:00Z is
        60 hours past expiry -> ceil(2.5) = 3 days -> 3 x 15000 = 45000 cents
        of per diem, plus 3 x 8000 = 24000 cents of storage.

        Design: Difficulty/dual_variant_calc/per_diem_provisional_vs_final_divergence
        """
        ctx = setup_grounded_container(
            gate_free_hours=48, ground_clock="2026-08-01T00:00:00Z")
        tid = ctx["terminal"]["id"]
        container = ctx["container"]
        assert container["free_time_expires_at"] == "2026-08-03T00:00:00Z"
        set_clock("2026-08-05T12:00:00Z")

        run_ops(tid)

        per_diem = list_ledger_entries(tid, entry_kind="PER_DIEM",
                                       container_id=container["id"])
        assert len(per_diem) == 1, "Exactly one provisional PER_DIEM entry"
        entry = per_diem[0]
        # PRD §3.8 provisional-row shape: opens OPEN with applied_cents at
        # zero, linked container_id, chassis_id null on per-diem rows. PRD §2.5
        # common fields also apply. "The billed carrier_id" is NOT asserted:
        # §3.2 registers containers with no carrier attribute and this setup
        # contains no appointment and no carrier entity, so no carrier linkage
        # is derivable from PRD for this row.
        assert is_valid_uuid(entry["id"])
        assert is_iso8601_timestamp(entry["created_at"])
        assert is_iso8601_timestamp(entry["updated_at"])
        assert isinstance(entry["version"], int) and entry["version"] >= 1
        assert isinstance(entry["terminal_id"], str)
        assert entry["entry_kind"] == "PER_DIEM"
        assert entry["container_id"] == container["id"]
        assert entry["chassis_id"] is None
        assert entry["applied_cents"] == 0
        assert entry["amount_cents"] == 45000, (
            "ceil(60h / 24h) = 3 days at 15000 cents/day")
        assert entry["status"] == "OPEN"

        storage = list_ledger_entries(tid, entry_kind="STORAGE",
                                      container_id=container["id"])
        assert len(storage) == 1, "Container is ON_GROUND: one provisional STORAGE"
        assert storage[0]["amount_cents"] == 24000, (
            "ceil(60h / 24h) = 3 days at 8000 cents/day")

    def test_final_per_diem_supersedes_provisional(self, api):
        """PRD §3.8: "The final variant is computed at outbound gate completion
        with the transaction's `processed_at` as the evaluation moment; the
        final charge supersedes every provisional per-diem or storage entry for
        that container — each provisional entry is `WAIVED` and replaced by a
        new entry covering the full period through gate-out."

        The provisional snapshot at 2026-08-05T12:00:00Z is 3 days; the driver
        out-gates at 2026-08-06T12:00:00Z, i.e. 84 hours past expiry ->
        ceil(3.5) = 4 days -> 4 x 15000 = 60000 cents. The variants diverge on
        the same container and the provisional entries are waived.

        Design: Difficulty/dual_variant_calc/per_diem_provisional_vs_final_divergence
        """
        terminal = create_terminal(gate_free_hours=48)
        tid = terminal["id"]
        create_slot(tid)
        pool = create_pool(tid)
        chassis = create_chassis(tid, pool["id"])
        carrier = create_carrier()
        enroll_carrier(tid, pool["id"], carrier["id"])
        train = create_arrived_train(tid)
        container = register_container(tid, train["id"])
        set_clock("2026-08-01T00:00:00Z")
        ground_container(tid, container["id"])

        set_clock("2026-08-05T12:00:00Z")
        run_ops(tid)
        provisional_pd = list_ledger_entries(
            tid, entry_kind="PER_DIEM", container_id=container["id"])[0]
        provisional_st = list_ledger_entries(
            tid, entry_kind="STORAGE", container_id=container["id"])[0]
        assert provisional_pd["amount_cents"] == 45000

        # Out-gate one day later than the checkpoint.
        set_clock("2026-08-06T11:00:00Z")
        appointment = book_appointment(
            tid, carrier["id"], container["id"], "OUT",
            "2026-08-06T10:00:00Z", "2026-08-06T13:00:00Z")
        check_in(tid, appointment["id"])
        reserve_chassis(tid, pool["id"], chassis["id"], appointment["id"])
        tx = open_transaction(tid, appointment["id"], chassis_id=chassis["id"])
        set_clock("2026-08-06T12:00:00Z")
        complete_transaction(tid, tx["id"])

        assert get_ledger_entry(tid, provisional_pd["id"])["status"] == "WAIVED", (
            "The provisional PER_DIEM entry is waived once the final supersedes it")
        assert get_ledger_entry(tid, provisional_st["id"])["status"] == "WAIVED", (
            "The provisional STORAGE entry is waived once the final supersedes it")

        final_pd = [e for e in list_ledger_entries(
            tid, entry_kind="PER_DIEM", container_id=container["id"])
            if e["id"] != provisional_pd["id"]]
        assert len(final_pd) == 1, "One replacement PER_DIEM entry is created"
        assert final_pd[0]["amount_cents"] == 60000, (
            "Final evaluation at 2026-08-06T12:00:00Z: ceil(84h/24h) = 4 days "
            "at 15000 cents/day — 15000 more than the 3-day provisional")
        assert final_pd[0]["status"] == "OPEN"


class TestPerDiemCeilBoundary:
    def test_per_diem_exact_day_boundary(self, api):
        """PRD §2.10: "Day counts for per-diem and storage accrue by rounding
        any partial day up to a whole day." and PRD §3.8: "The charge is the
        number of days overdue — the elapsed time from `free_time_expires_at`
        to the evaluation moment, rounded up to whole days; zero when the
        evaluation moment has not passed expiry — multiplied by the terminal's
        `per_diem_rate_cents`."

        gate_free_hours=24, grounded 2026-08-01T00:00:00Z, so expiry is
        2026-08-02T00:00:00Z; at exactly 2026-08-03T00:00:00Z the elapsed time
        is exactly one whole day: charge = 1 x 12000.

        Design: Difficulty/combinatorial_formula/per_diem_tiered_boundary_ceil
        """
        ctx = setup_grounded_container(
            gate_free_hours=24, per_diem_rate_cents=12000,
            ground_clock="2026-08-01T00:00:00Z")
        tid = ctx["terminal"]["id"]
        set_clock("2026-08-03T00:00:00Z")

        run_ops(tid)
        per_diem = list_ledger_entries(tid, entry_kind="PER_DIEM",
                                       container_id=ctx["container"]["id"])
        assert len(per_diem) == 1
        assert per_diem[0]["amount_cents"] == 12000, (
            "Exactly 86400 seconds past expiry is exactly one day — no rounding up")

    def test_per_diem_one_second_past_day_rounds_up(self, api):
        """PRD §2.10: "Day counts for per-diem and storage accrue by rounding
        any partial day up to a whole day."

        One second past the exact day boundary (86401 seconds) carries a
        partial day and rounds up: charge = 2 x 12000.

        Design: Difficulty/combinatorial_formula/per_diem_tiered_boundary_ceil
        """
        ctx = setup_grounded_container(
            gate_free_hours=24, per_diem_rate_cents=12000,
            ground_clock="2026-08-01T00:00:00Z")
        tid = ctx["terminal"]["id"]
        set_clock("2026-08-03T00:00:01Z")

        run_ops(tid)
        per_diem = list_ledger_entries(tid, entry_kind="PER_DIEM",
                                       container_id=ctx["container"]["id"])
        assert len(per_diem) == 1
        assert per_diem[0]["amount_cents"] == 24000, (
            "86401 seconds past expiry rounds up to two days")


class TestFlipFeeSettlement:
    def test_flip_fee_debits_sufficient_credit(self, api):
        """PRD §3.6: "If that carrier's membership on this pool holds
        `flip_fee_credit_cents` greater than or equal to the fee, the credit is
        debited by the fee amount and no ledger entry is created; otherwise a
        `FLIP_FEE` ledger entry for the full fee is created against the carrier
        and the membership credit is left untouched."

        Credit 10000 >= fee 5000: the credit absorbs the fee.

        Design: Difficulty/dual_variant_calc/flip_fee_membership_credit_vs_ledger_charge
        """
        ctx = setup_completed_out_gate(flip_credit_cents=10000,
                                       complete_clock="2026-08-02T11:00:00Z")
        tid = ctx["terminal"]["id"]

        membership = get_membership(tid, ctx["pool"]["id"], ctx["membership"]["id"])
        assert membership["flip_fee_credit_cents"] == 5000, (
            "The credit is debited by the fee amount: 10000 - 5000")

        flip_fees = list_ledger_entries(tid, entry_kind="FLIP_FEE",
                                        carrier_id=ctx["carrier"]["id"])
        assert flip_fees == [], (
            "No FLIP_FEE ledger entry is created when the credit covers the fee")

    def test_flip_fee_bills_when_credit_insufficient(self, api):
        """PRD §3.6: "otherwise a `FLIP_FEE` ledger entry for the full fee is
        created against the carrier and the membership credit is left
        untouched."
        PRD §3.8: "The sum of the unapplied remainder across a carrier's open
        entries is the carrier's `outstanding_billing_cents`".

        Credit 0 < fee 5000: the full fee is billed.

        Design: Difficulty/dual_variant_calc/flip_fee_membership_credit_vs_ledger_charge
        """
        ctx = setup_completed_out_gate(flip_credit_cents=0,
                                       complete_clock="2026-08-02T11:00:00Z")
        tid = ctx["terminal"]["id"]

        membership = get_membership(tid, ctx["pool"]["id"], ctx["membership"]["id"])
        assert membership["flip_fee_credit_cents"] == 0, "Credit left untouched"

        flip_fees = list_ledger_entries(tid, entry_kind="FLIP_FEE",
                                        carrier_id=ctx["carrier"]["id"])
        assert len(flip_fees) == 1
        assert_ledger_entry(flip_fees[0])
        assert flip_fees[0]["amount_cents"] == 5000
        assert flip_fees[0]["status"] == "OPEN"
        assert get_carrier(ctx["carrier"]["id"])["outstanding_billing_cents"] == 5000

    def test_flip_fee_credit_one_cent_short_bills_full_fee(self, api):
        """PRD §3.6: "If that carrier's membership on this pool holds
        `flip_fee_credit_cents` greater than or equal to the fee, the credit is
        debited by the fee amount and no ledger entry is created; otherwise a
        `FLIP_FEE` ledger entry for the full fee is created against the carrier
        and the membership credit is left untouched."

        Credit 4999 < fee 5000: the comparison is all-or-nothing — no partial
        debit, the full fee is billed, and the credit is unchanged.

        Design: Difficulty/combinatorial_formula/flip_fee_credit_partial_debit_ordering
        """
        ctx = setup_completed_out_gate(flip_credit_cents=4999,
                                       complete_clock="2026-08-02T11:00:00Z")
        tid = ctx["terminal"]["id"]

        membership = get_membership(tid, ctx["pool"]["id"], ctx["membership"]["id"])
        assert membership["flip_fee_credit_cents"] == 4999, (
            "4999 < 5000: the credit branch is not taken and no partial debit occurs")

        flip_fees = list_ledger_entries(tid, entry_kind="FLIP_FEE",
                                        carrier_id=ctx["carrier"]["id"])
        assert len(flip_fees) == 1
        assert flip_fees[0]["amount_cents"] == 5000

    def test_flip_fee_credit_exactly_equal_debits_credit(self, api):
        """PRD §3.6: "If that carrier's membership on this pool holds
        `flip_fee_credit_cents` greater than or equal to the fee, the credit is
        debited by the fee amount and no ledger entry is created".

        Credit 5000 == fee 5000: the inclusive boundary takes the credit
        branch, draining it to zero.

        Design: Difficulty/combinatorial_formula/flip_fee_credit_partial_debit_ordering
        """
        ctx = setup_completed_out_gate(flip_credit_cents=5000,
                                       complete_clock="2026-08-02T11:00:00Z")
        tid = ctx["terminal"]["id"]

        membership = get_membership(tid, ctx["pool"]["id"], ctx["membership"]["id"])
        assert membership["flip_fee_credit_cents"] == 0, (
            "5000 >= 5000: the credit is debited by the full fee amount")

        flip_fees = list_ledger_entries(tid, entry_kind="FLIP_FEE",
                                        carrier_id=ctx["carrier"]["id"])
        assert flip_fees == [], "No ledger entry is created on the credit branch"


class TestStorageInputSet:
    def test_run_ops_skips_mounted_container(self, api):
        """PRD §3.8: "It takes the provisional billing snapshot: every
        container in `ON_GROUND` or `MOUNTED` whose `free_time_expires_at` is
        in the past receives a provisional `PER_DIEM` entry, and every such
        container still `ON_GROUND` additionally receives a provisional
        `STORAGE` entry." and "**Storage** accrues only while the container is
        `ON_GROUND`."

        The container out-gated (OUTBOUND_TRUCK) before the checkpoint, so the
        checkpoint creates no new ledger entries for it at all.

        Design: Corner/calculations/storage_charge_only_when_on_ground
        """
        ctx = setup_completed_out_gate(
            gate_free_hours=24, complete_clock="2026-08-03T10:00:00Z",
            window_start="2026-08-03T09:00:00Z",
            window_end="2026-08-03T12:00:00Z",
            checkin_clock="2026-08-03T09:30:00Z",
        )
        tid = ctx["terminal"]["id"]
        container = ctx["container"]
        assert container["status"] == "OUTBOUND_TRUCK"

        before = {e["id"] for e in list_ledger_entries(
            tid, container_id=container["id"])}
        set_clock("2026-08-05T00:00:00Z")
        run_ops(tid)
        after = list_ledger_entries(tid, container_id=container["id"])

        assert {e["id"] for e in after} == before, (
            "run_ops must not snapshot an OUTBOUND_TRUCK container: the entry set "
            "is unchanged (no new PER_DIEM, and no STORAGE at any point)")
        assert [e for e in after if e["entry_kind"] == "STORAGE"] == [], (
            "Storage accrues only while the container is ON_GROUND")


class TestLedgerApplication:
    def test_overpay_rejected(self, api):
        """PRD §3.8: "Applying more than the remainder is rejected with
        `ERR_OVERPAY`."

        Design: Corner/validations/overpay_rejected_on_ledger_apply
        """
        ctx = setup_completed_out_gate(complete_clock="2026-08-02T11:00:00Z")
        tid = ctx["terminal"]["id"]
        entry = list_ledger_entries(tid, entry_kind="FLIP_FEE",
                                    carrier_id=ctx["carrier"]["id"])[0]
        version = get_carrier(ctx["carrier"]["id"])["version"]

        resp = api.apply_ledger_payment(
            tid, entry["id"],
            {"apply_cents": 6000, "expected_carrier_version": version}, BC)
        validate_error(resp, ApiErrorId.ERR_OVERPAY)

    def test_partial_apply_then_waive_restores_outstanding_zero(self, api):
        """PRD §3.8: "Applying less than the remaining balance moves an `OPEN`
        entry to `PARTIALLY_APPLIED`" and "Each application adds to the entry's
        `applied_cents` and reduces the carrier's `outstanding_billing_cents`
        by the same amount, incrementing the carrier's `version` by one. A
        `TerminalManager` may waive an `OPEN` or `PARTIALLY_APPLIED` entry,
        moving it to `WAIVED` and reducing the carrier's outstanding balance by
        the full unapplied remainder."

        Forward (apply 3000 of 5000) then compensate (waive the remaining
        2000): outstanding returns to zero and the entry reaches a terminal
        state.

        Design: Difficulty/compensating_invariant/carrier_outstanding_billing_invariant_under_apply_and_waive
        """
        ctx = setup_completed_out_gate(complete_clock="2026-08-02T11:00:00Z")
        tid = ctx["terminal"]["id"]
        carrier_id = ctx["carrier"]["id"]
        entry = list_ledger_entries(tid, entry_kind="FLIP_FEE",
                                    carrier_id=carrier_id)[0]
        assert get_carrier(carrier_id)["outstanding_billing_cents"] == 5000

        applied = apply_ledger_payment(tid, entry["id"], 3000, carrier_id)
        assert applied["status"] == "PARTIALLY_APPLIED"
        assert applied["applied_cents"] == 3000
        assert get_carrier(carrier_id)["outstanding_billing_cents"] == 2000, (
            "The application reduces outstanding_billing_cents by the same amount")

        waived = validate_success(api.waive_ledger_entry(tid, entry["id"], TM), 200)
        assert waived["status"] == "WAIVED"
        assert get_carrier(carrier_id)["outstanding_billing_cents"] == 0, (
            "Waiver reduces the balance by the full unapplied remainder: "
            "forward + compensate restores zero")

    def test_full_apply_marks_entry_applied(self, api):
        """PRD §3.8: "applying exactly the remaining balance moves an `OPEN`
        entry directly to `APPLIED`, or a `PARTIALLY_APPLIED` entry to
        `APPLIED`."
        PRD §3.8: "Each application adds to the entry's `applied_cents` and
        reduces the carrier's `outstanding_billing_cents` by the same amount,
        incrementing the carrier's `version` by one."

        Design: Difficulty/compensating_invariant/carrier_outstanding_billing_invariant_under_apply_and_waive
        """
        ctx = setup_completed_out_gate(complete_clock="2026-08-02T11:00:00Z")
        tid = ctx["terminal"]["id"]
        carrier_id = ctx["carrier"]["id"]
        entry = list_ledger_entries(tid, entry_kind="FLIP_FEE",
                                    carrier_id=carrier_id)[0]
        carrier_before = get_carrier(carrier_id)

        applied = apply_ledger_payment(tid, entry["id"], 5000, carrier_id)
        assert applied["status"] == "APPLIED", (
            "Applying exactly the remaining balance moves OPEN directly to APPLIED")
        assert applied["applied_cents"] == applied["amount_cents"] == 5000

        carrier_after = get_carrier(carrier_id)
        assert carrier_after["outstanding_billing_cents"] == 0
        assert carrier_after["version"] == carrier_before["version"] + 1, (
            "A successful apply increments the carrier's version by one")
