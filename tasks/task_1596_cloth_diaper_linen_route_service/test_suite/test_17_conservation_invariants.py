"""Conservation ledgers under forward + compensating actions: pool units across
a swap round-trip (PRD 2.7, 3.6) and deposit cents across charge + termination
refund (PRD 2.8, 3.2, 3.8)."""
from test_helpers import (
    assert_deposit_ledger_conserved,
    assert_pool,
    assert_pool_conservation,
    case_event,
    create_case,
    create_swap,
    fund_pool,
    read_customer,
    read_pool,
    read_pool_version,
    read_subscription,
    setup_active_subscription,
    settle_kit,
    subscription_event,
    swap_event,
    validate_success,
)
from test_helpers import api_client as _client
from test_helpers.fixtures import ADMIN


def _run_swap(ctx, to_size_code, pool):
    """Drive one swap REQUESTED -> APPROVED -> STAGED -> COMPLETED with a full
    return of the old kit (88 items)."""
    swap = create_swap(ctx["subscription"]["id"], to_size_code, ctx["customer_headers"])
    validate_success(
        _client.approve_swap(
            swap["id"],
            {"expected_inventory_pool_version": read_pool_version(pool["id"])},
            ADMIN,
        )
    )
    swap_event(swap["id"], "STAGE")
    completed = swap_event(swap["id"], "COMPLETE", returned_old_count=88)
    return completed


class TestSwapRoundTrip:
    def _setup_round_trip(self):
        """ACTIVE MEDIUM subscription (88-item kit issued); MEDIUM pool at 500,
        LARGE pool at 200; then a forward MEDIUM -> LARGE swap and its reverse."""
        ctx = setup_active_subscription()
        ctx["pool_l"] = fund_pool("LARGE", 200)
        forward = _run_swap(ctx, "LARGE", ctx["pool_l"])
        reverse = _run_swap(ctx, "MEDIUM", ctx["pool"])
        ctx.update({"forward": forward, "reverse": reverse})
        return ctx

    def test_forward_reverse_swaps_restore_bucket_values(self, api):
        """PRD 3.6: "in the target pool, `quantity` units move from
        `in_transit_units` to `checked_out_units`; in the old-size pool,
        `returned_old_count` units move from `checked_out_units` to `in_wash_units`"
        PRD 3.6: "the subscription's `current_size_code` becomes `to_size_code`, and
        the kit's `size_code` and `item_count` are rewritten to `to_size_code` and
        `quantity`."

        Design: Difficulty/compensating_invariant/swap_forward_reverse_conserves_units
        """
        ctx = self._setup_round_trip()
        assert ctx["forward"]["status"] == "COMPLETED"
        assert ctx["reverse"]["status"] == "COMPLETED"

        subscription = read_subscription(ctx["subscription"]["id"])
        assert subscription["current_size_code"] == "MEDIUM", (
            "forward then reverse returns the subscription to its original size"
        )

        medium = read_pool(ctx["pool"]["id"])
        assert medium["on_hand_units"] == 324
        assert medium["reserved_units"] == 0
        assert medium["in_transit_units"] == 0
        assert medium["checked_out_units"] == 88
        assert medium["in_wash_units"] == 88

    def test_conservation_holds_on_both_pools_after_round_trip(self, api):
        """PRD 2.7: "At all times the pool obeys a conservation invariant: the eight
        buckets — on-hand, reserved, in-transit, checked-out, in-wash, quarantined,
        lost, and retired — sum exactly to `total_acquired_units`."

        Design: Difficulty/compensating_invariant/swap_forward_reverse_conserves_units
        """
        ctx = self._setup_round_trip()
        medium = read_pool(ctx["pool"]["id"])
        large = read_pool(ctx["pool_l"]["id"])
        assert_pool(medium)
        assert_pool(large)
        assert medium["total_acquired_units"] == 500
        assert large["total_acquired_units"] == 200
        assert_pool_conservation(medium)
        assert_pool_conservation(large)
        assert large["on_hand_units"] == 112
        assert large["in_wash_units"] == 88


class TestDepositLedgerConservation:
    def test_charge_then_terminate_conserves_ledger(self, api):
        """PRD 3.8: "The charge then posts to the deposit ledger — provided
        `deposit_held_cents` covers it, else `ERR_DEPOSIT_INSUFFICIENT`:
        `charge_cents` is recorded on the case, the held balance drops by the charge,
        and `deposit_applied_cents` rises by the charge, moving the case `OPEN` →
        `CHARGED`."
        PRD 2.8: "At all times, the charged amount equals the sum of held, applied,
        and refunded."

        Design: Difficulty/compensating_invariant/deposit_charge_and_refund_conserve_cents
        """
        ctx = setup_active_subscription()
        case = create_case(
            ctx["subscription"]["id"], ctx["pool"]["id"],
            case_type="LOST", item_count=4, first_issued_date="2026-06-01",
        )
        charged = case_event(case["id"], "CHARGE")
        assert charged["charge_cents"] == 1200, (
            f"4 MEDIUM items at age 61 days charge 4 x 300 x 1.00 = 1200, got "
            f"{charged['charge_cents']}"
        )

        mid = read_customer(ctx["customer"]["id"])
        assert mid["deposit_held_cents"] == 16800
        assert mid["deposit_applied_cents"] == 1200
        assert_deposit_ledger_conserved(mid)

        case_event(case["id"], "SETTLE")
        settle_kit(ctx["kit"]["id"], 88)
        terminated = subscription_event(ctx["subscription"]["id"], "TERMINATE")
        assert terminated["service_status"] == "TERMINATED"

        final = read_customer(ctx["customer"]["id"])
        assert final["deposit_charged_cents"] == 18000
        assert final["deposit_held_cents"] == 0
        assert final["deposit_applied_cents"] == 1200
        assert final["deposit_refunded_cents"] == 16800, (
            "the compensating termination refund returns exactly what was still held"
        )
        assert_deposit_ledger_conserved(final)

    def test_clean_customer_refund_equals_charged(self, api):
        """PRD 2.8: "A customer with no lost or damaged charges therefore ends a
        clean termination with the refunded amount exactly equal to the charged
        amount and nothing held."
        PRD 3.2: "In every case the deposit settlement runs: the refund equals
        whatever is in `deposit_held_cents`, the held balance is zeroed, and the
        refund is added to `deposit_refunded_cents` — preserving the ledger invariant
        of §2.8."

        Design: Difficulty/compensating_invariant/deposit_charge_and_refund_conserve_cents
        """
        ctx = setup_active_subscription()
        settle_kit(ctx["kit"]["id"], 88)
        subscription_event(ctx["subscription"]["id"], "TERMINATE")

        customer = read_customer(ctx["customer"]["id"])
        assert customer["deposit_charged_cents"] == 18000
        assert customer["deposit_refunded_cents"] == 18000, (
            "no charges: the refund equals the full charged deposit"
        )
        assert customer["deposit_held_cents"] == 0
        assert_deposit_ledger_conserved(customer)
