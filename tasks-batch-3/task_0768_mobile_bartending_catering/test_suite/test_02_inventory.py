"""BYOB inventory plan: pinned rounding order and stale-on-edit reconciliation.

Design queues:
  A (Difficulty): combinatorial_formula/inventory_rounding_order_mode_b
  B (Corner): cross_cutting/inventory_plan_marked_stale_after_event_edit
"""
from test_helpers import (
    validate_success, get_success_data,
    create_draft_event, TEST_USERS, assert_inventory_plan,
)

COORD = TEST_USERS["coordinator_headers"]


def _plan_status(api, event_id):
    """Read the event's single inventory plan status via the list endpoint."""
    data = get_success_data(api.list_inventory_plan(event_id, COORD))
    if isinstance(data, list):
        return data[0]["status"]
    # Some list responses expose the array under data directly.
    return data[0]["status"]


# ---------------------------------------------------------------------------
# Queue A — combinatorial_formula / inventory_rounding_order_mode_b
# ---------------------------------------------------------------------------
def test_inventory_total_servings_split_beer_and_wine(api):
    """PRD §3.6: "The total servings (total_servings) are the guest_count
    multiplied by billable_hours multiplied by the package's
    drinks_per_guest_per_hour, rounded up to a whole serving."
    PRD §3.6: "the beer servings are the total servings multiplied by 40
    percent (rounded) and the wine servings are the total servings multiplied
    by 30 percent (rounded)".

    Design: Difficulty/combinatorial_formula/inventory_rounding_order_mode_b
    """
    bundle = create_draft_event(api, guest_count=80,
                                event_start="2026-06-01T18:00:00Z",
                                event_end="2026-06-01T23:00:00Z")
    ev_id = bundle["event"]["id"]
    plan = validate_success(api.create_inventory_plan(ev_id, COORD), 201)
    assert_inventory_plan(plan)
    assert plan["total_servings"] == 500
    assert plan["beer_units"] == 200
    assert plan["wine_bottles"] == 30


def test_inventory_spirit_bottles_absorb_remainder(api):
    """PRD §3.6: "the spirit servings are whatever remains after subtracting
    the beer and wine servings from the total, so the remainder absorbs any
    rounding drift."
    PRD §3.6: "spirit bottles (spirit_bottles) are the spirit servings divided
    by 16 servings per bottle, rounded up."

    Design: Difficulty/combinatorial_formula/inventory_rounding_order_mode_b
    """
    bundle = create_draft_event(api, guest_count=80,
                                event_start="2026-06-01T18:00:00Z",
                                event_end="2026-06-01T23:00:00Z")
    ev_id = bundle["event"]["id"]
    plan = validate_success(api.create_inventory_plan(ev_id, COORD), 201)
    assert plan["spirit_bottles"] == 10
    assert plan["ice_lbs"] == 120
    assert plan["glassware_needed"] == 200


# ---------------------------------------------------------------------------
# Queue B — cross_cutting / inventory_plan_marked_stale_after_event_edit
# ---------------------------------------------------------------------------
def test_inventory_plan_marked_stale_after_event_edit(api):
    """PRD §3.6: "it opens with `status` of `GENERATED`, flipping to `STALE`
    whenever the event is edited."
    PRD §3.2: "and marks any existing inventory plan as stale by setting its
    `status` to `STALE`."

    Design: Corner/cross_cutting/inventory_plan_marked_stale_after_event_edit
    """
    bundle = create_draft_event(api, guest_count=80,
                                event_start="2026-06-01T18:00:00Z",
                                event_end="2026-06-01T23:00:00Z")
    ev_id = bundle["event"]["id"]
    ev_v = bundle["event"]["version"]
    plan = validate_success(api.create_inventory_plan(ev_id, COORD), 201)
    assert plan["status"] == "GENERATED"
    validate_success(api.update_event(
        ev_id, {"expected_event_version": ev_v, "guest_count": 120},
        bundle["client_headers"]))
    assert _plan_status(api, ev_id) == "STALE"
