"""
The declared consistency model, probed on the one write whose parent carries six
derived buckets: the cut's own response, the parent's re-read and the reverse
foreign-key list must all already agree.
"""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import assertions as A
from test_helpers import factories as F
from test_helpers import test_users as U


def test_the_cut_and_the_immediate_re_read_of_the_lot_report_the_same_ledger(api, lot_released):
    """
    The sawdust charged for this particular cut is already on the billet in the
    create response, and the parent's six buckets are already correct when the lot is
    read back in the very next request rather than catching up afterwards.

    PRD: "Three quantities in this system are conserved, and each identity must hold
    after every single write with no tolerance whatsoever."

    Design: Corner/consistency_model/a_cut_reports_its_ledger_movement_inside_its_own_response
    """
    billet = F.create_billet(api, lot_released["lot1"], lot_released["lot_v1"],
                             billet_code="BLT-001", board_feet=30.00, grade="AAA")
    assert billet["kerf_loss_board_feet"] == 0.90
    assert billet["status"] == "AVAILABLE"

    lot = validate_success(
        api.get_tonewood_lot(lot_released["lot1"], U.MACHINIST_HEADERS))
    A.assert_lot_ledger(lot, available=69.10, unassigned=30.00, reserved=0.00,
                        consumed=0.00, scrapped=0.00, kerf_loss=0.90)
    A.assert_wood_conserved(lot)
    assert lot["status"] == "RELEASED"


def test_the_reverse_lookup_on_the_parent_already_returns_the_new_billet(api, lot_released):
    """
    The third read of the same single write is the filtered collection, and it must
    already count the row it has just gained and report that no page remains beyond
    it.

    PRD: "List responses carry `limit`, `offset`, `total_count` and `has_more` inside
    `meta`, where `total_count` is the number of rows matching the filters before
    pagination is applied and `has_more` is true exactly when rows remain beyond the
    current page."

    Design: Corner/consistency_model/a_cut_reports_its_ledger_movement_inside_its_own_response
    """
    F.create_billet(api, lot_released["lot1"], lot_released["lot_v1"],
                    billet_code="BLT-001", board_feet=30.00, grade="AAA")

    rows, meta = validate_paginated(api.list_billets(
        U.MACHINIST_HEADERS, {"lot_id": lot_released["lot1"]}))
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert rows[0]["billet_code"] == "BLT-001"
