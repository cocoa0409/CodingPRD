"""Repairs on two independent tracks: warranty billing, parallel dimensions, settlement gate."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, fixtures,
)

STAFF = fixtures.STAFF


# ---------------------------------------------------------------------------
# Queue A — non_linear_state_machine / repair_parallel_repair_and_billing_dimensions
# ---------------------------------------------------------------------------

def test_diagnose_out_of_warranty_bills_labor_and_parts(api):
    """PRD §3.6: "coverage is `COVERED` when the number of days between the
    `purchase_date` and the current clock date is at most 365, and `DENIED`
    otherwise. The computed `billed_cents` is 0 when the warranty is `COVERED`,
    and otherwise the sum of `labor_cents` and `parts_cents`."

    Design: Difficulty/non_linear_state_machine/repair_parallel_repair_and_billing_dimensions
    """
    fixtures.set_clock(api, "2026-07-01T00:00:00Z")
    member, member_headers, product, ro = fixtures.setup_diagnosed_repair(
        api, purchase_date="2020-01-01T00:00:00Z", labor_cents=5000, parts_cents=0)
    assert ro["warranty_status"] == "DENIED"
    assert ro["billed_cents"] == 5000


def test_billing_can_settle_while_repair_still_in_progress(api):
    """PRD §3.6: "Settlement of the invoice is a billing-dimension action that
    moves `billing_stage` from `INVOICED` to `SETTLED`, independent of where
    `repair_stage` sits".

    Design: Difficulty/non_linear_state_machine/repair_parallel_repair_and_billing_dimensions
    """
    fixtures.set_clock(api, "2026-07-01T00:00:00Z")
    member, member_headers, product, ro = fixtures.setup_diagnosed_repair(
        api, purchase_date="2020-01-01T00:00:00Z", labor_cents=5000, parts_cents=0)
    validate_success(api.start_repair_order(ro["id"], STAFF))
    settled = validate_success(api.settle_repair_order(ro["id"], STAFF))
    assert settled["repair_stage"] == "IN_REPAIR"
    assert settled["billing_stage"] == "SETTLED"


# ---------------------------------------------------------------------------
# Queue B — state_machines / repair_pickup_before_settled_returns_repair_unsettled
# ---------------------------------------------------------------------------

def test_pickup_before_invoice_settled_rejected(api):
    """PRD §3.6: "Picking up a repair moves `repair_stage` from `READY` to the
    terminal `PICKED_UP` state, but only when the money is resolved: the
    `billing_stage` must be `SETTLED`, or the `billed_cents` must be 0. A pickup
    attempted while billable work remains unsettled is rejected with
    `ERR_REPAIR_UNSETTLED`".

    Design: Corner/state_machines/repair_pickup_before_settled_returns_repair_unsettled
    """
    fixtures.set_clock(api, "2026-07-01T00:00:00Z")
    member, member_headers, product, ro = fixtures.setup_diagnosed_repair(
        api, purchase_date="2019-01-01T00:00:00Z", labor_cents=5000, parts_cents=0)
    validate_success(api.start_repair_order(ro["id"], STAFF))
    validate_success(api.ready_repair_order(ro["id"], STAFF))
    validate_error(api.pickup_repair_order(ro["id"], STAFF),
                   ApiErrorId.ERR_REPAIR_UNSETTLED.value)
