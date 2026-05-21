"""Monthly billing sweep — utility apportionment, rent proration,
outstanding balance recomputation."""
from __future__ import annotations

import pytest

from test_helpers import (
    add_days,
    assert_utility_bill,
    create_park,
    create_park_with_lot_and_lease,
    create_signed_lease,
    create_lot,
    create_resident,
    iso_utc,
    setup_three_occupied_lots,
    sub_meter_billing,
    sweep_billing,
    utcnow,
    validate_success,
)


# ===========================================================================
# EQUAL_SPLIT apportionment — PRD §3.3
# ===========================================================================
class TestEqualSplitApportionment:
    def test_equal_split_divides_total_with_remainder_to_lowest_lot(self, api):
        """PRD §3.3: 'Under EQUAL_SPLIT, the integer division of
        master_total_cents by the number of occupied lots yields each
        lot's base share, and the residual is distributed one cent per
        lot in ascending lot_number order.'

        Claim: 10000 cents / 3 lots → 3333 each + 1 leftover → L01
        gets 3334, L02 & L03 get 3333.
        """
        park, lots, residents, leases = setup_three_occupied_lots(
            utility_apportionment_method="EQUAL_SPLIT",
        )
        _, _, bills = sub_meter_billing(park, master_total_cents=10_000)
        # Index bills by lot_id for predictable lookup.
        share_by_lot = {
            b["lot_id"]: b["lot_share_cents"] for b in bills
        }
        assert share_by_lot[lots[0]["id"]] == 3334, (
            "PRD §3.3: 'the residual is distributed one cent per lot "
            "in ascending lot_number order.' — L01 must receive the "
            "extra cent."
        )
        assert share_by_lot[lots[1]["id"]] == 3333
        assert share_by_lot[lots[2]["id"]] == 3333

    def test_equal_split_conserves_master_total(self, api):
        """PRD §3.3: 'the residual is distributed one cent per lot in
        ascending lot_number order' (so that the sum of shares exactly
        equals master_total_cents).

        Claim: sum of lot_share_cents across bills equals
        master_total_cents.
        """
        park, lots, residents, leases = setup_three_occupied_lots(
            utility_apportionment_method="EQUAL_SPLIT",
        )
        _, _, bills = sub_meter_billing(park, master_total_cents=10_000)
        total = sum(b["lot_share_cents"] for b in bills)
        assert total == 10_000


# ===========================================================================
# SUB_METER apportionment — PRD §3.3
# ===========================================================================
class TestSubMeterApportionment:
    def test_sub_meter_assigns_by_reading_ratio(self, api):
        """PRD §3.3: 'Under SUB_METER, the system sums the latest
        sub_meter_reading_kwh value ... across the occupied lots; if
        the sum is strictly greater than zero, each lot's raw share is
        the lot's reading divided by the total reading, multiplied by
        master_total_cents. Each raw share is truncated downward to a
        whole cent, the residual cents remaining after the floors are
        summed are redistributed one-per-lot in ascending lot_number
        order until the sum of the lot shares exactly equals
        master_total_cents.'

        Claim: with readings 1.0, 3.0, 6.0 (sum 10.0) and
        master_total_cents=10000, shares are 1000, 3000, 6000.
        """
        park, lots, residents, leases = setup_three_occupied_lots(
            utility_apportionment_method="SUB_METER",
            readings_kwh=(1.0, 3.0, 6.0),
        )
        _, _, bills = sub_meter_billing(park, master_total_cents=10_000)
        share_by_lot = {
            b["lot_id"]: b["lot_share_cents"] for b in bills
        }
        assert share_by_lot[lots[0]["id"]] == 1000
        assert share_by_lot[lots[1]["id"]] == 3000
        assert share_by_lot[lots[2]["id"]] == 6000

    def test_sub_meter_with_all_zero_readings_falls_back_to_equal_split(self, api):
        """PRD §3.3: 'If the total reading is exactly zero (every
        occupied lot reports a zero reading), the system falls back to
        equal-split: each lot receives the integer-divided share, and
        the residual is again distributed one cent per lot in
        ascending lot_number order.'

        Claim: two SUB_METER lots with 0.0 readings and
        master_total_cents=10001 → shares (5001, 5000).
        """
        park = create_park(utility_apportionment_method="SUB_METER")
        # Build two lots L01, L02 with reading 0.0.
        # PRD §3.1: base_rent_cents must be strictly > 0; use positive
        # value (rent_due_cents is not asserted here — only lot_share).
        from test_helpers import create_signed_lease, create_resident
        lots = []
        for i in (1, 2):
            lot = create_lot(
                park_id=park["id"], lot_number=f"L{i:02d}",
                base_rent_cents=100_000, sub_meter_reading_kwh=0.0,
            )
            r = create_resident()
            create_signed_lease(park["id"], lot["id"], r["id"])
            lots.append(lot)
        _, _, bills = sub_meter_billing(park, master_total_cents=10_001)
        share_by_lot = {
            b["lot_id"]: b["lot_share_cents"] for b in bills
        }
        assert share_by_lot[lots[0]["id"]] == 5001, (
            "PRD §3.3: zero-reading SUB_METER falls back to EQUAL_SPLIT; "
            "remainder cent goes to the lowest lot_number."
        )
        assert share_by_lot[lots[1]["id"]] == 5000

    def test_sub_meter_floor_then_remainder_order_pinned(self, api):
        """PRD §3.3: 'Each raw share is truncated downward to a whole
        cent, the residual cents remaining after the floors are summed
        are redistributed one-per-lot in ascending lot_number order
        until the sum of the lot shares exactly equals
        master_total_cents.'

        Claim: with three equal readings and master_total_cents=10001:
        floor((1/3)*10001) = floor(3333.6667) = 3333 for each → sum
        9999, remainder 2 → L01 and L02 each gain a cent, L03 unchanged.
        """
        park, lots, residents, leases = setup_three_occupied_lots(
            utility_apportionment_method="SUB_METER",
            readings_kwh=(1.0, 1.0, 1.0),
        )
        _, _, bills = sub_meter_billing(park, master_total_cents=10_001)
        share_by_lot = {
            b["lot_id"]: b["lot_share_cents"] for b in bills
        }
        assert share_by_lot[lots[0]["id"]] == 3334
        assert share_by_lot[lots[1]["id"]] == 3334
        assert share_by_lot[lots[2]["id"]] == 3333
        assert sum(share_by_lot.values()) == 10_001


# ===========================================================================
# Rent on bills — PRD §3.3
# ===========================================================================
class TestRentDueOnBills:
    def test_full_period_rent_when_lease_started_before_period(self, api):
        """PRD §3.3: 'When start_date is on or before
        billing_period_start, the lease was active for the entire
        period and rent_due_cents equals the lease's
        monthly_rent_cents.'

        Claim: lease started 60 days ago, billing window is 30 days
        ending today → rent_due_cents == lease.monthly_rent_cents.
        """
        park, lot, resident, lease = create_park_with_lot_and_lease(
            base_rent_cents=120_000, lease_start_offset_days=-60,
        )
        _, _, bills = sub_meter_billing(park, master_total_cents=0)
        assert len(bills) == 1
        assert bills[0]["rent_due_cents"] == 120_000

    def test_total_due_equals_rent_plus_share(self, api):
        """PRD §3.3: 'Each bill's total_due_cents is then the sum of
        its rent_due_cents and its lot_share_cents.'

        Claim: total_due_cents == rent_due_cents + lot_share_cents on
        every emitted bill.
        """
        park, lot, resident, lease = create_park_with_lot_and_lease(
            base_rent_cents=100_000, lease_start_offset_days=-60,
        )
        _, _, bills = sub_meter_billing(park, master_total_cents=2_500)
        for b in bills:
            assert_utility_bill(b)
            assert b["total_due_cents"] == (
                b["rent_due_cents"] + b["lot_share_cents"]
            )

    def test_utility_bill_is_lean_entity(self, api):
        """PRD §2.4: 'a UtilityBill carries id and created_at but no
        updated_at and no version.'

        Claim: emitted UtilityBills carry id+created_at and lack
        updated_at and version.
        """
        # PRD §3.1: base_rent_cents must be strictly > 0.
        park, lot, resident, lease = create_park_with_lot_and_lease(
            base_rent_cents=100_000, lease_start_offset_days=-60,
        )
        _, _, bills = sub_meter_billing(park, master_total_cents=1_000)
        for b in bills:
            assert "id" in b and "created_at" in b
            assert "updated_at" not in b or b.get("updated_at") is None
            assert "version" not in b or b.get("version") is None
