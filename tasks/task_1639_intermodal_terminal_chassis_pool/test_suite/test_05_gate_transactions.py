"""Gate-transaction completion cascades, rejection semantics, driver turn time,
and the rail cutoff (PRD §3.6)."""
from test_helpers import (
    ApiErrorId,
    assert_appointment,
    assert_chassis,
    assert_container,
    assert_transaction,
    complete_transaction,
    get_appointment,
    get_chassis,
    get_container,
    get_pool,
    get_slot,
    get_terminal,
    get_transaction,
    list_ledger_entries,
    reject_transaction,
    set_clock,
    setup_checked_in_out_appointment,
    setup_completed_out_gate,
    setup_pending_out_transaction,
    TEST_USERS,
    validate_error,
    validate_success,
)

GC = TEST_USERS["gate_clerk_headers"]


class TestOutGateCompletionCascade:
    def test_out_gate_completion_full_cascade(self, api):
        """PRD §3.6: "The appointment moves to `COMPLETED` with `completed_at`
        equal to `processed_at`. The chassis moves `RESERVED` → `OUT`: the
        pool's `reserved_chassis_count` falls by one and `out_chassis_count`
        rises by one, the chassis's `out_gate_transaction_id` is set to this
        transaction, and its `current_container_id` records the container it
        now carries. The container, previously `ON_GROUND`, transitions to
        `MOUNTED` — releasing its yard slot exactly as described in §3.3 (slot
        back to `EMPTY`, counts decremented, `stack_height` cleared, posture
        recomputed) — and then immediately to `OUTBOUND_TRUCK`, recording this
        transaction in its `out_gate_transaction_id`."

        Design: Difficulty/transitive_cascade/out_gate_completion_cascade_depth3
        """
        ctx = setup_completed_out_gate(complete_clock="2026-08-02T11:00:00Z")
        tid = ctx["terminal"]["id"]

        transaction = ctx["transaction"]
        assert_transaction(transaction)
        assert transaction["status"] == "COMPLETED"
        assert transaction["processed_at"] == "2026-08-02T11:00:00Z"

        assert ctx["appointment"]["status"] == "COMPLETED", (
            "Link 2: the appointment follows its transaction to COMPLETED")

        chassis = ctx["chassis"]
        assert chassis["status"] == "OUT", "Link 2: chassis RESERVED -> OUT"

        container = ctx["container"]
        assert container["status"] == "OUTBOUND_TRUCK", (
            "Link 3: container traversed ON_GROUND -> MOUNTED -> OUTBOUND_TRUCK")

        slot = get_slot(tid, ctx["slot"]["id"])
        assert slot["status"] == "EMPTY", "Link 4: the yard slot is released"
        assert slot["occupied_container_id"] is None
        assert slot["current_height"] == 0

        terminal = ctx["terminal"]
        assert terminal["yard_slots_free"] == 20, (
            "Link 5: release lifts free capacity back from 19 to 20")
        assert terminal["yard_slots_in_use"] == 0
        assert terminal["posture"] == "OPEN"

        pool = ctx["pool"]
        assert pool["reserved_chassis_count"] == 0
        assert pool["out_chassis_count"] == 1
        assert pool["available_chassis_count"] == 0

    def test_out_gate_completion_linkage_fields(self, api):
        """PRD §3.6: "The appointment moves to `COMPLETED` with `completed_at`
        equal to `processed_at`."
        PRD §3.6: "the chassis's `out_gate_transaction_id` is set to this
        transaction, and its `current_container_id` records the container it
        now carries."
        PRD §3.6: "and then immediately to `OUTBOUND_TRUCK`, recording this
        transaction in its `out_gate_transaction_id`."
        PRD §3.6: "the fee equals the terminal's `flip_fee_cents`, charged
        against the appointment's carrier."

        Design: Difficulty/transitive_cascade/out_gate_completion_cascade_depth3
        """
        ctx = setup_completed_out_gate(complete_clock="2026-08-02T11:00:00Z")
        tid = ctx["terminal"]["id"]
        tx = ctx["transaction"]

        appointment = ctx["appointment"]
        assert appointment["completed_at"] == tx["processed_at"], (
            "appointment.completed_at must equal the transaction's processed_at")

        chassis = ctx["chassis"]
        assert chassis["out_gate_transaction_id"] == tx["id"]
        assert chassis["current_container_id"] == ctx["container"]["id"]

        container = ctx["container"]
        assert container["out_gate_transaction_id"] == tx["id"]

        flip_fees = list_ledger_entries(tid, entry_kind="FLIP_FEE",
                                        carrier_id=ctx["carrier"]["id"])
        assert len(flip_fees) == 1, (
            "No flip-fee credit was loaded, so completion creates one FLIP_FEE entry")
        assert flip_fees[0]["amount_cents"] == 5000
        assert flip_fees[0]["status"] == "OPEN"


class TestTransactionReject:
    def test_reject_releases_chassis_and_keeps_appointment(self, api):
        """PRD §3.6: "Rejection releases a reserved chassis back to `AVAILABLE`
        (with pool counters adjusted) but deliberately leaves the appointment
        in `CHECKED_IN` — the driver may retry with a fresh transaction."

        Design: Corner/endpoints/transaction_reject_releases_chassis_reservation
        """
        ctx = setup_pending_out_transaction()
        tid = ctx["terminal"]["id"]
        pid = ctx["pool"]["id"]

        rejected = reject_transaction(tid, ctx["transaction"]["id"])
        assert rejected["status"] == "REJECTED"

        chassis = get_chassis(tid, pid, ctx["chassis"]["id"])
        assert chassis["status"] == "AVAILABLE", (
            "Rejection releases the reserved chassis")
        pool = get_pool(tid, pid)
        assert pool["reserved_chassis_count"] == 0
        assert pool["available_chassis_count"] == 1

        appointment = get_appointment(tid, ctx["appointment"]["id"])
        assert appointment["status"] == "CHECKED_IN", (
            "Rejection deliberately leaves the appointment CHECKED_IN")


class TestDriverTurnMinutes:
    def test_driver_turn_minutes_exact_hour_boundary(self, api):
        """PRD §3.6: "`driver_turn_minutes` is the elapsed time from the
        appointment's `checked_in_at` to `processed_at`, expressed in whole
        minutes with any partial minute rounded up — exactly 3600 seconds is
        exactly 60 minutes, never 61."

        Design: Corner/calculations/driver_turn_minutes_ceil_boundary
        """
        ctx = setup_completed_out_gate(complete_clock="2026-08-02T11:00:00Z")
        transaction = ctx["transaction"]
        assert ctx["appointment"]["checked_in_at"] == "2026-08-02T10:00:00Z"
        assert transaction["processed_at"] == "2026-08-02T11:00:00Z"
        assert transaction["driver_turn_minutes"] == 60, (
            "Exactly 3600 seconds is exactly 60 minutes, never 61")

    def test_driver_turn_minutes_partial_minute_rounds_up(self, api):
        """PRD §3.6: "`driver_turn_minutes` is the elapsed time from the
        appointment's `checked_in_at` to `processed_at`, expressed in whole
        minutes with any partial minute rounded up — exactly 3600 seconds is
        exactly 60 minutes, never 61."

        3601 seconds carries a partial minute and must round up to 61.

        Design: Corner/calculations/driver_turn_minutes_ceil_boundary
        """
        ctx = setup_completed_out_gate(complete_clock="2026-08-02T11:00:01Z")
        transaction = ctx["transaction"]
        assert ctx["appointment"]["checked_in_at"] == "2026-08-02T10:00:00Z"
        assert transaction["processed_at"] == "2026-08-02T11:00:01Z"
        assert transaction["driver_turn_minutes"] == 61, (
            "3601 seconds carries a partial minute and rounds up to 61")


class TestRailCutoff:
    def test_rail_cutoff_exact_instant_rejected(self, api):
        """PRD §3.6: "the logical clock at completion must be strictly earlier
        than the train's `rail_cutoff_at` — a completion attempted exactly at
        the cutoff instant or any time after it is rejected with
        `ERR_RAIL_CUTOFF_MISSED`, while anything earlier is allowed".
        PRD §3.2: "its `rail_cutoff_at` is derived immediately as
        `scheduled_departure_utc` minus the terminal's
        `rail_cutoff_minutes_before_departure`."

        Departure 2026-08-10T12:00:00Z minus 60 minutes puts the cutoff at
        2026-08-10T11:00:00Z; completing at that exact instant is rejected.

        Design: Difficulty/boundary_precision_check/rail_cutoff_strict_less_than
        """
        ctx = setup_pending_out_transaction(
            train_departure="2026-08-10T12:00:00Z",
            window_start="2026-08-10T10:00:00Z",
            window_end="2026-08-10T12:00:00Z",
            checkin_clock="2026-08-10T10:30:00Z",
        )
        tid = ctx["terminal"]["id"]
        set_clock("2026-08-10T11:00:00Z")

        resp = api.complete_transaction(tid, ctx["transaction"]["id"], GC)
        validate_error(resp, ApiErrorId.ERR_RAIL_CUTOFF_MISSED)

    def test_rail_cutoff_one_second_before_allowed(self, api):
        """PRD §3.6: "the logical clock at completion must be strictly earlier
        than the train's `rail_cutoff_at` — a completion attempted exactly at
        the cutoff instant or any time after it is rejected with
        `ERR_RAIL_CUTOFF_MISSED`, while anything earlier is allowed".

        One second before the cutoff instant must complete.

        Design: Difficulty/boundary_precision_check/rail_cutoff_strict_less_than
        """
        ctx = setup_pending_out_transaction(
            train_departure="2026-08-10T12:00:00Z",
            window_start="2026-08-10T10:00:00Z",
            window_end="2026-08-10T12:00:00Z",
            checkin_clock="2026-08-10T10:30:00Z",
        )
        tid = ctx["terminal"]["id"]
        set_clock("2026-08-10T10:59:59Z")

        completed = complete_transaction(tid, ctx["transaction"]["id"])
        assert completed["status"] == "COMPLETED", (
            "processed_at strictly earlier than rail_cutoff_at must be allowed")
        assert completed["processed_at"] == "2026-08-10T10:59:59Z"
