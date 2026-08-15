"""Order lifecycle edges: terminal lockdown on cancel, dispatch date gate,
the 24-hour delivery freshness window and its inclusive boundary (PRD §3.5,
§3.6)."""
from test_helpers import (
    TEST_USERS,
    accept_quote,
    assert_money_eq,
    create_batch,
    complete_batch,
    create_config,
    create_customer,
    create_field,
    create_quote,
    create_variety,
    factories,
    get_success_data,
    mini_chain,
    set_clock,
    validate_error,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId

FARM = TEST_USERS["farm_manager_headers"]
SALES = TEST_USERS["sales_rep_headers"]
HARVEST = TEST_USERS["harvest_supervisor_headers"]
FLEET = TEST_USERS["fleet_manager_headers"]


# ---------------------------------------------------------------------------
# Corner: state_machines / cancel_terminal_order_returns_already_terminal
# ---------------------------------------------------------------------------

def test_cancel_terminal_order_returns_already_terminal(api):
    """PRD §2.9: "6. **Terminal guard** — the target entity is not in a terminal state for this action; otherwise `ERR_ALREADY_TERMINAL`."
    PRD §3.6: "A `SalesRep` may cancel an order in `PLACED`, `CONFIRMED`, or `OUT_FOR_DELIVERY` provided nothing has been paid — a `total_paid` above zero rejects the cancel with `ERR_INVALID_STATE`, since paid orders require a credit workflow that is out of scope."

    Design: Corner/state_machines/cancel_terminal_order_returns_already_terminal
    """
    bundle = mini_chain(api, stage="placed")
    o_id = bundle["o"]["id"]
    cancelled = get_success_data(api.cancel_order(o_id, SALES))
    assert cancelled["status"] == "CANCELLED"

    resp = api.cancel_order(o_id, SALES)
    validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL, 409)


# ---------------------------------------------------------------------------
# Corner: state_machines / dispatch_on_wrong_date_returns_invalid_state
# ---------------------------------------------------------------------------

def test_dispatch_on_wrong_date_returns_invalid_state(api):
    """PRD §3.6: "Dispatch belongs to the `FleetManager` and is deliberately strict: the order must be `CONFIRMED`, every linked batch must be `COMPLETE`, and the clock's current date must equal the `delivery_date`; violations are rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/dispatch_on_wrong_date_returns_invalid_state
    """
    bundle = mini_chain(api, stage="confirmed")
    o_id = bundle["o"]["id"]
    # The day before delivery_date (2026-08-03).
    set_clock(api, "2026-08-02T08:00:00Z")
    resp = api.dispatch_order(o_id, FLEET)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
    after = get_success_data(api.get_order(o_id, SALES))
    assert after["status"] == "CONFIRMED", "rejected dispatch leaves the order unchanged"


# ---------------------------------------------------------------------------
# Corner: state_machines / mark_delivered_stale_returns_delivery_stale
# ---------------------------------------------------------------------------

def test_mark_delivered_stale_returns_delivery_stale(api):
    """PRD §3.6: "Freshness is enforced against the actual harvest: the hours from the earliest `actual_harvest_end` among the order's linked batches to the delivery instant must not exceed the card's `freshness_limit_hours` — 24 hours by default — or the delivery is rejected with `ERR_DELIVERY_STALE` and the order stays `OUT_FOR_DELIVERY`."

    Design: Corner/state_machines/mark_delivered_stale_returns_delivery_stale
    """
    bundle = mini_chain(api, stage="out_for_delivery")
    o_id = bundle["o"]["id"]
    # Harvest end was 2026-08-03T06:45; the truck arrives 24.25h later.
    set_clock(api, "2026-08-04T07:00:00Z")
    resp = api.mark_delivered(o_id, {"accepted_sqft": 300}, FLEET)
    validate_error(resp, ApiErrorId.ERR_DELIVERY_STALE, 409)
    after = get_success_data(api.get_order(o_id, SALES))
    assert after["status"] == "OUT_FOR_DELIVERY", "stale delivery changes nothing"
    assert_money_eq(after["delivered_sqft"], 0, "no sqft accepted")


# ---------------------------------------------------------------------------
# Corner: state_machines / freshness_exactly_24h_is_deliverable
# Batch completed with end 2026-08-02T08:00; delivery window 2026-08-03
# 06:00-08:00 (confirm-time projection exactly 24.0h); delivered at
# 2026-08-03T08:00 -> freshness_hours 24.00 (inclusive boundary).
# ---------------------------------------------------------------------------

def test_freshness_exactly_24h_is_deliverable(api):
    """PRD §3.5: "A candidate batch must be `PENDING` or `COMPLETE`, unlinked (its `order_id` null), matching the line's variety and grade, and projected fresh: for a `COMPLETE` batch the projected harvest end is its recorded `actual_harvest_end`, while for a `PENDING` batch it is the batch's `scheduled_date` at 08:00 UTC; the projected freshness is the hours from that projected end to the order's `delivery_window_end`, and the candidate is eligible only when the projection is at least zero and at most the card's `freshness_limit_hours` (24 hours by default) — a projection of exactly the limit remains eligible, while a negative projection (the batch would finish after the window ends) is ineligible."
    PRD §3.6: "Freshness is enforced against the actual harvest: the hours from the earliest `actual_harvest_end` among the order's linked batches to the delivery instant must not exceed the card's `freshness_limit_hours` — 24 hours by default — or the delivery is rejected with `ERR_DELIVERY_STALE` and the order stays `OUT_FOR_DELIVERY`. The first accepted delivery stamps `actual_delivered_at`, moves the order to `DELIVERED`, and sets `freshness_hours` (the same elapsed-hours figure, rounded half-up to two decimals); later deliveries follow a `DELIVERED` to `DELIVERED` self-loop under the same rules, accumulating `delivered_sqft` and recomputing `freshness_hours` from the latest delivery."

    Design: Corner/state_machines/freshness_exactly_24h_is_deliverable
    """
    create_config(api)
    v = create_variety(api)
    f = create_field(api, v["id"])
    b = create_batch(api, f["id"], pallet_count=3, scheduled_date="2026-08-02")
    c = create_customer(api)
    set_clock(api, "2026-08-01T09:00:00Z")
    q = create_quote(api, c["id"],
                     [factories.quote_line(v["id"], "PREMIUM", 2)], 1, 1, 0)
    o = accept_quote(api, q["id"])

    set_clock(api, "2026-08-02T08:05:00Z")
    complete_batch(api, b["id"], start="2026-08-02T06:00:00Z",
                   end="2026-08-02T08:00:00Z")

    # Confirm at 09:00 (before the 14:00 future-day cutoff); the projection
    # to window end 2026-08-03T08:00 is exactly 24.0h -> eligible.
    set_clock(api, "2026-08-02T09:00:00Z")
    confirmed = validate_success(api.confirm_order(
        o["id"],
        factories.confirm_order_payload(
            delivery_window_start="2026-08-03T06:00:00Z"
        ),
        SALES,
    ), 200)
    assert confirmed["status"] == "CONFIRMED", (
        "a projection of exactly the freshness limit remains eligible"
    )

    set_clock(api, "2026-08-03T06:30:00Z")
    get_success_data(api.dispatch_order(o["id"], FLEET))

    set_clock(api, "2026-08-03T08:00:00Z")  # exactly 24.0h after harvest end
    delivered = validate_success(
        api.mark_delivered(o["id"], {"accepted_sqft": 300}, FLEET), 200
    )
    assert delivered["status"] == "DELIVERED"
    assert_money_eq(delivered["freshness_hours"], 24.00,
                    "the <= boundary is inclusive")
