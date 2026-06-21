"""Work-order lifecycle tests: hold/re-diagnose cycle, terminal lockdown,
open-count recompute (PRD §3.9)."""
from test_helpers import (
    validate_success, validate_error,
    setup_work_order_awaiting_approval, setup_resolved_work_order,
    diagnose_payload, ApiErrorId, TEST_USERS,
)

FT = TEST_USERS["field_technician_headers"]
RM = TEST_USERS["route_manager_headers"]
AM = TEST_USERS["account_manager_headers"]


def test_work_order_hold_rediagnose_resubmit_cycle(api):
    """PRD §3.9: "A held order is not dead — a field technician may re-diagnose it,
    cycling it from `ON_HOLD` back to `DIAGNOSED` with a revised `quoted_parts_cents`
    and `labor_minutes`, after which it can be re-submitted and re-decided."

    Design: Difficulty/non_linear_state_machine/work_order_hold_rediagnose_cycle
    """
    ctx = setup_work_order_awaiting_approval(severity="MAJOR", component="HEATER",
                                             quoted_parts_cents=5000, labor_minutes=90)
    wo_id = ctx["work_order"]["id"]
    # Customer declines -> ON_HOLD
    held = validate_success(api.hold_work_order(wo_id, ctx["customer_headers"]))
    assert held["status"] == "ON_HOLD"
    # Field tech re-diagnoses with a revised quote -> DIAGNOSED
    re_diag = validate_success(api.re_diagnose_work_order(
        wo_id, diagnose_payload(quoted_parts_cents=9000, labor_minutes=120), FT))
    assert re_diag["status"] == "DIAGNOSED"
    # Re-submit -> AWAITING_APPROVAL with the revised quote
    resubmitted = validate_success(api.submit_work_order_for_approval(wo_id, FT))
    assert resubmitted["status"] == "AWAITING_APPROVAL"
    assert resubmitted["quoted_parts_cents"] == 9000


def test_rediagnosed_quote_replaces_prior_on_resolve(api):
    """PRD §3.9: "a field technician may re-diagnose it, cycling it from `ON_HOLD`
    back to `DIAGNOSED` with a revised `quoted_parts_cents` and `labor_minutes`".
    PRD §3.9: "the `quoted_parts_cents` is added to the multiplier-adjusted labor".

    The revised quote (not the original) drives the resolved repair total.

    Design: Difficulty/non_linear_state_machine/work_order_hold_rediagnose_cycle
    """
    ctx = setup_work_order_awaiting_approval(severity="MAJOR", component="HEATER",
                                             quoted_parts_cents=5000, labor_minutes=90)
    wo_id = ctx["work_order"]["id"]
    validate_success(api.hold_work_order(wo_id, ctx["customer_headers"]))
    validate_success(api.re_diagnose_work_order(
        wo_id, diagnose_payload(quoted_parts_cents=9000, labor_minutes=120), FT))
    validate_success(api.submit_work_order_for_approval(wo_id, FT))
    resolved = validate_success(api.resolve_work_order(wo_id, ctx["customer_headers"]))
    assert resolved["status"] == "RESOLVED"
    # ceil(120/60)=2*9000=18000 *1.15=20700 +9000=29700 *1.07=31779.0 -> 31779
    assert resolved["repair_total_cents"] == 31779, \
        f"expected 31779, got {resolved['repair_total_cents']}"


def test_cancel_resolved_work_order_rejected(api):
    """PRD §3.9: "A route manager may cancel a work order that is still `OPEN` or
    `ON_HOLD`, moving it to `CANCELLED`."
    PRD §2.9: "State validity is fifth: an operation invoked against a resource not
    in a state from which the transition is defined fails with `ERR_INVALID_STATE`."

    Cancel is undefined from RESOLVED (a terminal state).

    Design: Corner/state_machines/cancel_resolved_work_order_terminal_lockdown
    """
    ctx = setup_resolved_work_order(severity="MINOR", component="FILTER",
                                    quoted_parts_cents=0, labor_minutes=30)
    resp = api.cancel_work_order(ctx["work_order"]["id"], RM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_resolve_recomputes_pool_open_work_order_count(api):
    """PRD §3.1: "The `open_work_order_count` is the number of this pool's work
    orders whose status is `OPEN`, `DIAGNOSED`, `ON_HOLD`, or `AWAITING_APPROVAL`,
    and it is recomputed on every work-order transition."
    PRD §3.9: "Resolution computes the order's `repair_total_cents`".

    Resolving the only open order drops the count to 0.

    Design: Corner/cross_cutting_complexity_layers/work_order_resolve_recomputes_open_count
    """
    ctx = setup_work_order_awaiting_approval(severity="MINOR", component="CHLORINATOR",
                                             quoted_parts_cents=0, labor_minutes=30)
    pool_before = validate_success(api.get_pool(ctx["pool"]["id"], AM))
    assert pool_before["open_work_order_count"] == 1
    resolved = validate_success(api.resolve_work_order(ctx["work_order"]["id"], ctx["customer_headers"]))
    pool_after = validate_success(api.get_pool(ctx["pool"]["id"], AM))
    assert resolved["status"] == "RESOLVED"
    assert pool_after["open_work_order_count"] == 0
