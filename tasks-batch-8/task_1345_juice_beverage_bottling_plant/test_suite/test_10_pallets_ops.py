"""Pallet escrow ledger and the housekeeping epoch sweeps."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, factories,
    create_customer, create_formula, create_tank, create_line,
    create_container_lot, create_zone, create_released_batch, quote_run,
    confirm_run, schedule_run, set_clock, setup_completed_run, place_order,
    allocate_order, ship_allocated_order, get_pallet_account,
)

PM = TEST_USERS["plant_manager_headers"]
FIN = TEST_USERS["finance_clerk_headers"]
QA = TEST_USERS["qa_inspector_headers"]
WH = TEST_USERS["warehouse_lead_headers"]


def _shipped_one_pallet(**pipeline_kwargs):
    """Completed run + a shipped 500-unit FOODSERVICE order (1 pallet)."""
    ctx = setup_completed_run(actual_units_filled=1000, avg_fill_ml=473,
                              **pipeline_kwargs)
    order = place_order(ctx["customer"]["id"], ctx["formula"]["id"],
                        channel="FOODSERVICE", requested_delivery_date="2026-08-20",
                        units_requested=500)
    shipped = ship_allocated_order(order["id"])
    ctx["order"] = shipped
    ctx["pallet_account"] = get_pallet_account(ctx["customer"]["id"])
    return ctx


class TestPalletEntryShape:
    def test_ship_entry_shape_is_append_only(self, api):
        """PRD §2.5: "A pallet ledger entry and a housekeeping epoch record are
        append-only facts: each carries only `id` and `created_at`, and both
        `updated_at` and `version` are absent from them." and §3.10: "Each ledger
        entry records its `pallet_account_id`, an `entry_type` of `SHIP`,
        `RETURN`, or `CONVERSION`, a positive `pallet_count`, the originating
        `shipment_order_id` for `SHIP` entries (absent otherwise), the
        `entry_date` — the calendar date of the logical clock when the entry
        posted — and a `running_balance` equal to the account's
        `pallets_outstanding` immediately after posting."

        Design: Corner/entities/pallet_entry_immutable_shape
        """
        ctx = _shipped_one_pallet()
        entries = get_success_data(api.list_pallet_entries(
            ctx["pallet_account"]["id"], PM))
        assert isinstance(entries, list) and len(entries) == 1
        entry = entries[0]
        assert entry["entry_type"] == "SHIP"
        assert entry["pallet_count"] == 1
        assert entry["shipment_order_id"] == ctx["order"]["id"]
        assert entry["entry_date"] == "2026-08-11"
        assert entry["running_balance"] == 1
        assert "version" not in entry
        assert "updated_at" not in entry


class TestPalletReturnBounds:
    def test_return_above_outstanding_rejected(self, api):
        """PRD §3.10: "the count must not exceed the account's
        `pallets_outstanding`, else `ERR_PALLET_RETURN_EXCEEDS_OUTSTANDING`."

        Design: Corner/validations/pallet_return_exceeds_outstanding
        """
        ctx = _shipped_one_pallet()
        assert ctx["pallet_account"]["pallets_outstanding"] == 1
        resp = api.post_pallet_return(ctx["pallet_account"]["id"],
                                      {"pallet_count": 2}, WH)
        validate_error(resp, ApiErrorId.ERR_PALLET_RETURN_EXCEEDS_OUTSTANDING)
        assert resp.status_code == 422

    def test_return_of_exact_outstanding_zeroes_escrow(self, api):
        """PRD §3.10: "A return posts a `RETURN` entry that raises
        `pallets_returned_total`, and credits both the escrow balance and the
        customer's outstanding balance by the count times the deposit."

        Design: Corner/validations/pallet_return_exceeds_outstanding
        """
        ctx = _shipped_one_pallet()
        entry = get_success_data(api.post_pallet_return(
            ctx["pallet_account"]["id"], {"pallet_count": 1}, WH))
        assert entry["entry_type"] == "RETURN"
        assert entry["running_balance"] == 0
        account = get_pallet_account(ctx["customer"]["id"])
        assert account["pallets_outstanding"] == 0
        assert account["escrow_balance_cents"] == 0


class TestPalletLedgerConservation:
    def test_ship_then_return_compensates_exactly(self, api):
        """PRD §3.10: "Shipping posts the outward leg: a `SHIP` entry carrying the
        order's `pallet_count` — computed per §3.9 as the per-lot ceilings of each
        allocation summed together — raises `pallets_out_total` by that count,
        raises `escrow_balance_cents` by the count times the customer's
        `pallet_deposit_cents`, and charges the same amount into the customer's
        `outstanding_balance_cents`." and "A return posts a `RETURN` entry that
        raises `pallets_returned_total`, and credits both the escrow balance and
        the customer's outstanding balance by the count times the deposit."

        Design: Difficulty/compensating_invariant/pallet_ledger_conservation
        """
        ctx = _shipped_one_pallet()
        customer_id = ctx["customer"]["id"]
        # provisional 149400 + 1 pallet * 1500 deposit
        customer = get_success_data(api.get_customer(customer_id, PM))
        assert customer["outstanding_balance_cents"] == 150_900
        account = ctx["pallet_account"]
        assert account["pallets_outstanding"] == 1
        assert account["escrow_balance_cents"] == 1500
        set_clock("2026-08-12T09:00:00Z")
        entry = get_success_data(api.post_pallet_return(
            account["id"], {"pallet_count": 1}, WH))
        assert entry["running_balance"] == 0
        customer = get_success_data(api.get_customer(customer_id, PM))
        assert customer["outstanding_balance_cents"] == 149_400  # pre-ship value
        account = get_pallet_account(customer_id)
        assert account["escrow_balance_cents"] == 0
        assert account["pallets_outstanding"] == 0

    def test_conversion_at_thirty_days_forfeits_deposit(self, api):
        """PRD §3.10: "any `SHIP` entry with a net outstanding count whose
        `entry_date` lies at least thirty days before the current logical date —
        an entry exactly thirty days old converts — posts a `CONVERSION` entry for
        its net count, raising `pallets_converted_total` and reducing
        `escrow_balance_cents` by the converted count times the deposit while
        leaving `pallets_outstanding` untouched: the deposit on converted pallets
        is forfeited, having already been collected at ship." and §2.9: "On a
        pallet account, `pallets_outstanding` always equals `pallets_out_total`
        minus `pallets_returned_total` minus `pallets_converted_total`"

        Design: Difficulty/compensating_invariant/pallet_ledger_conservation
        """
        ctx = _shipped_one_pallet()
        customer_id = ctx["customer"]["id"]
        # return the first pallet, then ship a second one on 2026-08-12
        set_clock("2026-08-12T09:00:00Z")
        get_success_data(api.post_pallet_return(
            ctx["pallet_account"]["id"], {"pallet_count": 1}, WH))
        order2 = place_order(customer_id, ctx["formula"]["id"],
                             channel="FOODSERVICE", requested_delivery_date="2026-08-20",
                             units_requested=300)
        ship_allocated_order(order2["id"])  # 1 more pallet out on 2026-08-12
        # 2026-09-11 is exactly 30 days after the second SHIP entry: converts
        set_clock("2026-09-11T00:00:00Z")
        ops = get_success_data(api.post_ops_run(PM))
        assert ops["pallets_converted_count"] == 1
        account = get_pallet_account(customer_id)
        assert account["pallets_out_total"] == 2
        assert account["pallets_returned_total"] == 1
        assert account["pallets_converted_total"] == 1
        assert account["pallets_outstanding"] == 0
        assert account["escrow_balance_cents"] == 0
        # the forfeited deposit stays in the customer's outstanding balance
        customer = get_success_data(api.get_customer(customer_id, PM))
        assert customer["outstanding_balance_cents"] == 150_900


class TestCloseBlockedByPallets:
    def test_close_blocked_until_pallets_returned(self, api):
        """PRD §3.1: "Closure from `ACTIVE` or `SUSPENDED` to `CLOSED` — again a
        `FinanceClerk` action — is refused with `ERR_CUSTOMER_STATE_INVALID`
        while ... its pallet account still shows a non-zero
        `pallets_outstanding`."

        Design: Corner/state_machines/customer_close_blocked_by_pallet_balance
        """
        ctx = _shipped_one_pallet()
        customer_id = ctx["customer"]["id"]
        assert ctx["pallet_account"]["pallets_outstanding"] == 1
        resp = api.close_customer(customer_id, FIN)
        validate_error(resp, ApiErrorId.ERR_CUSTOMER_STATE_INVALID)
        # the run is COMPLETED and the order SHIPPED: both terminal
        get_success_data(api.post_pallet_return(
            ctx["pallet_account"]["id"], {"pallet_count": 1}, WH))
        closed = get_success_data(api.close_customer(customer_id, FIN))
        assert closed["status"] == "CLOSED"


class TestOpsRunExpirySweep:
    def _lot_with_label_expiry(self):
        """PASTE pipeline, shelf 30 days, completed at 2026-08-11T09:00Z so the
        lot's label expiry is 2026-09-10."""
        return setup_completed_run(
            formula_overrides={"shelf_life_days": 30})

    def test_expiry_equality_boundary(self, api):
        """PRD §3.9: "The housekeeping epoch flips a lot to `EXPIRED` when the
        current logical date reaches `expiry_label_date` — equality expires."

        Design: Corner/cross_cutting_layers/ops_run_expiry_equality_sweep
        """
        ctx = self._lot_with_label_expiry()
        lot = ctx["lot"]
        assert lot["expiry_label_date"] == "2026-09-10"  # 2026-08-11 + 30 d
        set_clock("2026-09-09T00:00:00Z")
        ops1 = get_success_data(api.post_ops_run(PM))
        assert ops1["lots_expired_count"] == 0
        assert get_success_data(api.get_finished_lot(lot["id"], PM))["status"] == "AVAILABLE"
        set_clock("2026-09-10T00:00:00Z")
        ops2 = get_success_data(api.post_ops_run(PM))
        assert ops2["lots_expired_count"] == 1
        assert get_success_data(api.get_finished_lot(lot["id"], PM))["status"] == "EXPIRED"

    def test_sweep_counters_and_expired_recall(self, api):
        """PRD §3.10: "Four sweeps run per epoch." and §3.9: "a `QAInspector` may
        recall a lot standing in `AVAILABLE` or `EXPIRED` (else
        `ERR_LOT_STATE_INVALID`), moving it to `RECALLED`."

        Design: Corner/cross_cutting_layers/ops_run_expiry_equality_sweep
        """
        ctx = self._lot_with_label_expiry()
        lot_id = ctx["lot"]["id"]
        set_clock("2026-09-10T00:00:00Z")
        ops = get_success_data(api.post_ops_run(PM))
        assert ops["lots_expired_count"] == 1
        # no open orders, no credit breach, no aged pallets
        assert ops["orders_backordered_count"] == 0
        assert ops["orders_cancelled_count"] == 0
        assert ops["customers_suspended_count"] == 0
        assert ops["pallets_converted_count"] == 0
        # EXPIRED -> RECALLED is a valid transition
        recalled = get_success_data(api.recall_finished_lot(lot_id, QA))
        assert recalled["status"] == "RECALLED"


class TestOpsRunStaleOrderSweep:
    def test_stale_order_strictly_past_seven_days(self, api):
        """PRD §3.10: "The stale-order sweep cancels every shipment order standing
        in `PLACED` or `BACKORDERED` whose `requested_delivery_date` lies more
        than a full calendar week — seven days — in the past; an order exactly
        seven days stale keeps its place, and cancellation releases its
        allocations."

        Design: Corner/cross_cutting_layers/ops_run_stale_order_boundary
        """
        customer = create_customer()
        formula = create_formula(customer["id"], approve=False)
        order = place_order(customer["id"], formula["id"], channel="DIRECT_RETAIL",
                            requested_delivery_date="2026-08-20", units_requested=100)
        # 2026-08-20 + 7 == 2026-08-27: NOT strictly before 2026-08-27 -> survives
        set_clock("2026-08-27T00:00:00Z")
        ops1 = get_success_data(api.post_ops_run(PM))
        assert ops1["orders_cancelled_count"] == 0
        assert get_success_data(api.get_shipment_order(order["id"], PM))["status"] == "PLACED"
        # one day later it is strictly more than a week stale
        set_clock("2026-08-28T00:00:00Z")
        ops2 = get_success_data(api.post_ops_run(PM))
        assert ops2["orders_cancelled_count"] == 1
        assert get_success_data(api.get_shipment_order(order["id"], PM))["status"] == "CANCELLED"
