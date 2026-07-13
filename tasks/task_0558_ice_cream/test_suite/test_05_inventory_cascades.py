"""Pay/refund inventory cascades, par-level stock boundary, batch volume conservation.

Each test docstring cites the verbatim PRD sentence it asserts and ends with a
Design: traceability tag mapping it to its originating design-index instance.
"""
import pytest
from test_helpers import (
    validate_error,
    make_flavor, make_size, make_batch,
    open_drawer, open_order, add_line, pay,
    get_flavor, get_batch,
    assert_batch_volume_conserved,
    api_client, get_success_data,
    TEST_USERS,
)

SCOOP = TEST_USERS["scooper_headers"]
LEAD = TEST_USERS["shift_lead_headers"]
BAKER = TEST_USERS["baker_headers"]


def _double_line_order(flavor, size, batch_initial=180):
    batch = make_batch(flavor["id"], initial_volume_ml=batch_initial)
    drawer = open_drawer()
    order = open_order(drawer["id"])
    line = add_line(order["id"], size["id"], flavor["id"])
    return batch, drawer, order, line


# ─────────────── transitive_cascade / pay_deplete_cascade_depth3 ───────────────

def test_pay_depletes_batch_and_flags_flavor_out_of_stock(api):
    """PRD 3.4: "any batch whose `remaining_volume_ml` reaches zero as a result
    auto-transitions from `AVAILABLE` to the terminal `DEPLETED` state and is
    excluded from future reservations. Third, every affected flavor's
    `total_available_ml` and `stock_status` are recomputed, possibly falling to
    `OUT_OF_STOCK`."
    PRD 2.7: "when `total_available_ml` is exactly zero the status is
    `OUT_OF_STOCK`".

    Design: Difficulty/transitive_cascade/pay_deplete_cascade_depth3
    """
    flavor = make_flavor(par_level_ml=500)
    size = make_size(code="DOUBLE", scoop_count=2, base_price_cents=550)
    batch, drawer, order, line = _double_line_order(flavor, size, batch_initial=180)
    pay(order["id"], payment_method="CARD")
    b = get_batch(batch["id"])
    f = get_flavor(flavor["id"])
    assert b["remaining_volume_ml"] == 0
    assert b["status"] == "DEPLETED"
    assert f["total_available_ml"] == 0
    assert f["stock_status"] == "OUT_OF_STOCK"


def test_depleted_batch_excluded_from_future_reservation(api):
    """PRD 3.4: "any batch whose `remaining_volume_ml` reaches zero as a result
    auto-transitions from `AVAILABLE` to the terminal `DEPLETED` state and is
    excluded from future reservations."
    PRD 3.3: "If the combined headroom across all candidate batches is less than
    the needed volume, the line is rejected with `ERR_INSUFFICIENT_BATCH_VOLUME`
    and nothing is reserved."

    Design: Difficulty/transitive_cascade/pay_deplete_cascade_depth3
    """
    flavor = make_flavor(par_level_ml=500)
    size = make_size(code="DOUBLE", scoop_count=2, base_price_cents=550)
    batch, drawer, order, line = _double_line_order(flavor, size, batch_initial=180)
    pay(order["id"], payment_method="CARD")  # batch now DEPLETED
    order2 = open_order(drawer["id"])
    res = api.add_line(order2["id"], {"size_option_id": size["id"], "flavor_id": flavor["id"]}, SCOOP)
    validate_error(res, "ERR_INSUFFICIENT_BATCH_VOLUME")


# ─────────────── transitive_cascade / refund_restore_cascade_depth3 ───────────────

def test_refund_restores_batch_and_flavor_stock(api):
    """PRD 3.5: "Refunding runs the commit cascade in reverse: for each `COMMITTED`
    line, the touched batches have their `committed_volume_ml` lowered and their
    `remaining_volume_ml` raised by the drawn volumes; any batch that had gone
    `DEPLETED` and whose `remaining_volume_ml` rises back above zero
    auto-transitions from `DEPLETED` back to `AVAILABLE`; and every affected
    flavor's `total_available_ml` and `stock_status` are recomputed, possibly
    rising to `BELOW_PAR` or `IN_STOCK`."

    Design: Difficulty/transitive_cascade/refund_restore_cascade_depth3
    """
    flavor = make_flavor(par_level_ml=500)
    size = make_size(code="DOUBLE", scoop_count=2, base_price_cents=550)
    batch, drawer, order, line = _double_line_order(flavor, size, batch_initial=180)
    pay(order["id"], payment_method="CARD")
    get_success_data(api.refund_order(order["id"], LEAD))
    b = get_batch(batch["id"])
    f = get_flavor(flavor["id"])
    assert b["remaining_volume_ml"] == 180
    assert b["status"] == "AVAILABLE"
    assert f["total_available_ml"] == 180
    assert f["stock_status"] == "BELOW_PAR"


def test_refunded_batch_available_for_new_reservation(api):
    """PRD 3.5: "any batch that had gone `DEPLETED` and whose `remaining_volume_ml`
    rises back above zero auto-transitions from `DEPLETED` back to `AVAILABLE`".

    Design: Difficulty/transitive_cascade/refund_restore_cascade_depth3
    """
    flavor = make_flavor(par_level_ml=500)
    size = make_size(code="DOUBLE", scoop_count=2, base_price_cents=550)
    batch, drawer, order, line = _double_line_order(flavor, size, batch_initial=180)
    pay(order["id"], payment_method="CARD")
    get_success_data(api.refund_order(order["id"], LEAD))
    # Batch is back AVAILABLE: a new line can reserve its restored 180 ml.
    order2 = open_order(drawer["id"])
    new_line = add_line(order2["id"], size["id"], flavor["id"])
    assert new_line["status"] == "ACTIVE"
    b = get_batch(batch["id"])
    assert b["reserved_volume_ml"] == 180
    assert b["remaining_volume_ml"] == 180


# ─────────────── boundary_precision_check / par_threshold_at_par_vs_below ───────────────

class TestParLevelBoundary:
    """PRD 2.7: "when it is at least `par_level_ml` (equal to or greater than) the
    status is `IN_STOCK`. The boundary is deliberate: `total_available_ml` equal to
    `par_level_ml` is `IN_STOCK`, while one milliliter less is `BELOW_PAR`."""

    def test_exactly_at_par_is_in_stock_then_below_after_1ml_waste(self, api):
        """PRD 2.7: "The boundary is deliberate: `total_available_ml` equal to
        `par_level_ml` is `IN_STOCK`, while one milliliter less is `BELOW_PAR`."

        Design: Difficulty/boundary_precision_check/par_threshold_at_par_vs_below
        """
        flavor = make_flavor(par_level_ml=500)
        batch = make_batch(flavor["id"], initial_volume_ml=500)
        f = get_flavor(flavor["id"])
        assert f["total_available_ml"] == 500
        assert f["stock_status"] == "IN_STOCK"
        get_success_data(api.create_waste_event({"batch_id": batch["id"], "waste_type": "MELT", "volume_ml": 1}, BAKER))
        f = get_flavor(flavor["id"])
        assert f["total_available_ml"] == 499
        assert f["stock_status"] == "BELOW_PAR"

    def test_one_below_par_is_below_par(self, api):
        """PRD 2.7: "one milliliter less is `BELOW_PAR`."

        Design: Difficulty/boundary_precision_check/par_threshold_at_par_vs_below
        """
        flavor = make_flavor(par_level_ml=500)
        make_batch(flavor["id"], initial_volume_ml=499)
        f = get_flavor(flavor["id"])
        assert f["total_available_ml"] == 499
        assert f["stock_status"] == "BELOW_PAR"

    def test_one_above_par_is_in_stock(self, api):
        """PRD 2.7: "when it is at least `par_level_ml` (equal to or greater than)
        the status is `IN_STOCK`."

        Design: Difficulty/boundary_precision_check/par_threshold_at_par_vs_below
        """
        flavor = make_flavor(par_level_ml=500)
        make_batch(flavor["id"], initial_volume_ml=501)
        f = get_flavor(flavor["id"])
        assert f["total_available_ml"] == 501
        assert f["stock_status"] == "IN_STOCK"


# ─────────────── compensating_invariant / batch_volume_conserved_across_pay_refund ───────────────

def test_batch_volume_conserved_across_pay_then_refund(api):
    """PRD 2.7: "The physical on-hand quantity, `remaining_volume_ml`, is always
    the initial volume minus committed minus wasted."

    Design: Difficulty/compensating_invariant/batch_volume_conserved_across_pay_refund
    """
    flavor = make_flavor(par_level_ml=500)
    size = make_size(code="DOUBLE", scoop_count=2, base_price_cents=550)
    batch, drawer, order, line = _double_line_order(flavor, size, batch_initial=180)
    pay(order["id"], payment_method="CARD")
    get_success_data(api.refund_order(order["id"], LEAD))
    b = get_batch(batch["id"])
    assert b["remaining_volume_ml"] == 180
    assert b["committed_volume_ml"] == 0
    assert b["wasted_volume_ml"] == 0
    assert b["initial_volume_ml"] == 180
    assert_batch_volume_conserved(b)


def test_batch_volume_invariant_holds_at_paid_midpoint(api):
    """PRD 2.7: "The physical on-hand quantity, `remaining_volume_ml`, is always
    the initial volume minus committed minus wasted."
    PRD 3.4: "its `committed_volume_ml` rises by that volume, and its
    `remaining_volume_ml` drops by that volume."

    Design: Difficulty/compensating_invariant/batch_volume_conserved_across_pay_refund
    """
    flavor = make_flavor(par_level_ml=500)
    size = make_size(code="DOUBLE", scoop_count=2, base_price_cents=550)
    batch, drawer, order, line = _double_line_order(flavor, size, batch_initial=180)
    pay(order["id"], payment_method="CARD")
    mid = get_batch(batch["id"])
    # After pay: 180 == 0 remaining + 180 committed + 0 wasted.
    assert mid["remaining_volume_ml"] == 0
    assert mid["committed_volume_ml"] == 180
    assert mid["wasted_volume_ml"] == 0
    assert_batch_volume_conserved(mid)
    get_success_data(api.refund_order(order["id"], LEAD))
    after = get_batch(batch["id"])
    assert_batch_volume_conserved(after)
    assert after["remaining_volume_ml"] == 180
