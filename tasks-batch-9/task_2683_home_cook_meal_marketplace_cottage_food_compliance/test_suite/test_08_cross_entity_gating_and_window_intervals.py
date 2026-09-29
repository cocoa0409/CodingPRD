"""Preconditions read off another entity, plus the cook-level window overlap rule.

The first two families here decide one operation from state that lives on a
different row: an order's advance into production is decided by its parent
window's status, and a dish's approval is decided by the cook's verified kitchen
type together with the governing state policy's TCS flag. The third family pins
the half-open semantics of the cook's own handoff intervals.
"""

from datetime import datetime

from test_helpers import (
    ADMIN_HEADERS,
    DINER_TWO_HEADERS,
    REVIEWER_ONE,
    REVIEWER_ONE_HEADERS,
    ApiErrorId,
    factories,
    fixtures as fx,
    make_cook_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

AFTER_CUTOFF = "2026-08-06T00:00:00Z"
ROUTED_ORDER_QUANTITY = 2
PLACED_ORDER_QUANTITY = 2


def _instant(value):
    """Compare timestamps by the instant they name, not by their spelling."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


# ==========================================================================
# An order's ROUTED -> IN_PRODUCTION advance is gated by its parent window.
# ==========================================================================
def _cutoff_passed_window_scenario(api, with_placed_order=False):
    """One ROUTED order on a window that has only reached CUTOFF_PASSED."""
    setup = fx.selling_cook(
        api,
        cook_overrides={"legal_name": "Omar Diallo", "weekly_capacity_meals": 6},
        item_overrides={
            "name": "Thieboudienne Pot",
            "food_category": "NON_TCS",
            "allergens": ["FISH"],
            "shelf_life_days": 3,
            "unit_price_cents": 1200,
        },
        window_overrides={"capacity_meals": 6},
    )
    setup["order"] = fx.routed_order(api, setup, quantity=ROUTED_ORDER_QUANTITY)
    if with_placed_order:
        setup["placed_order"] = fx.order_in_scenario(
            api, setup, quantity=PLACED_ORDER_QUANTITY, diner_headers=DINER_TWO_HEADERS
        )
    fx.set_clock(api, AFTER_CUTOFF)
    setup["window"] = fx.advance_window(api, setup.window, "CUTOFF_PASSED")
    return setup


def _advance_order_to_production(api, setup):
    return api.advance_order(
        setup.order["id"],
        factories.order_advance_payload("IN_PRODUCTION"),
        make_cook_headers(setup.cook_id),
    )


def test_01_order_cannot_enter_production_while_its_window_is_only_cutoff_passed(api):
    """A legally ROUTED order is refused production because its parent window has not entered it.

    PRD: "This rule owns two things and only two: transitions absent from the declared table for the current state (including every request against a terminal state), and cross-entity preconditions with no dedicated code, such as the requirement that the owning window be `IN_PRODUCTION` before an order may move `ROUTED → IN_PRODUCTION`."
    Design: Difficulty/cross_entity_state_dependency/order_production_advance_gated_by_parent_window_status
    """
    setup = _cutoff_passed_window_scenario(api)
    assert setup.window["status"] == "CUTOFF_PASSED"

    resp = _advance_order_to_production(api, setup)

    validate_error(resp, ApiErrorId.INVALID_ORDER_TRANSITION, 409)
    order = fx.read_order(api, setup.order["id"])
    assert order["fulfillment_status"] == "ROUTED"
    assert order["payment_status"] == "AUTHORIZED"


def test_02_the_identical_advance_succeeds_once_the_window_is_in_production(api):
    """The same request that was refused is admitted after the window itself enters production.

    PRD: "`ROUTED → IN_PRODUCTION` is a cook action and carries a cross-entity guard with no dedicated error code of its own: the owning window's `status` must itself be `IN_PRODUCTION`, and if it is not, the advance is `ERR_INVALID_ORDER_TRANSITION`."
    Design: Difficulty/cross_entity_state_dependency/order_production_advance_gated_by_parent_window_status
    """
    setup = _cutoff_passed_window_scenario(api)
    validate_error(
        _advance_order_to_production(api, setup), ApiErrorId.INVALID_ORDER_TRANSITION, 409
    )

    window = fx.advance_window(api, setup.window, "IN_PRODUCTION")
    assert window["status"] == "IN_PRODUCTION"
    order = validate_success(_advance_order_to_production(api, setup), 200)

    assert order["fulfillment_status"] == "IN_PRODUCTION"
    assert order["payment_status"] == "AUTHORIZED"
    assert order["captured_at"] is None


def test_03_window_entering_production_sweeps_placed_orders_but_not_routed_ones(api):
    """The window's own advance cancels only the never-routed orders on it.

    PRD: "Orders already in `ROUTED` are left completely untouched by this sweep; they advance on their own."
    Design: Difficulty/cross_entity_state_dependency/order_production_advance_gated_by_parent_window_status
    """
    setup = _cutoff_passed_window_scenario(api, with_placed_order=True)

    fx.advance_window(api, setup.window, "IN_PRODUCTION")

    routed = fx.read_order(api, setup.order["id"])
    assert routed["fulfillment_status"] == "ROUTED"
    assert routed["payment_status"] == "AUTHORIZED"
    assert routed["cancelled_reason"] is None
    swept = fx.read_order(api, setup.placed_order["id"])
    assert swept["fulfillment_status"] == "CANCELLED"
    assert swept["payment_status"] == "VOIDED"
    assert swept["cancelled_reason"] == "WINDOW_CANCELLED"
    assert fx.read_window(api, setup.window["id"])["committed_meals"] == ROUTED_ORDER_QUANTITY


# ==========================================================================
# A TCS dish's approval is decided by the cook's verified kitchen type and the
# state policy's TCS flag. The Massachusetts profile below confines TCS dishes
# to COMMERCIAL_SHARED kitchens, while the cook's inspection was WAIVED and so
# wrote a verified kitchen type of HOME_COTTAGE.
# ==========================================================================
MA_POLICY_OVERRIDES = {
    "cottage_food_annual_cap_cents": 2_500_000,
    "allowed_kitchen_types": ["HOME_COTTAGE", "COMMERCIAL_SHARED"],
    "tcs_requires_commercial_kitchen": True,
}


def _cottage_kitchen_scenario(api):
    """An ACTIVE Massachusetts cook whose verified kitchen type is HOME_COTTAGE.

    Two dishes sit UNDER_REVIEW: one TCS and one NON_TCS, identical in every
    other declared field including `requires_refrigeration`.
    """
    setup = fx.onboard_active_cook(
        api,
        state_code="MA",
        policy_overrides=MA_POLICY_OVERRIDES,
        cook_overrides={
            "legal_name": "Quin Alves",
            "claimed_kitchen_type": "HOME_COTTAGE",
            "weekly_capacity_meals": 8,
        },
        inspection_overrides={"kitchen_type_claimed": "HOME_COTTAGE"},
        inspection_decision="WAIVE",
    )
    common = {
        "allergens": ["SOY"],
        "shelf_life_days": 3,
        "requires_refrigeration": True,
        "handoff_mode": "BATCH_COOK_AND_CHILL",
        "unit_price_cents": 1400,
    }
    tcs = fx.draft_menu_item(
        api, setup.cook, name="Chicken Rice Bowl", food_category="TCS", **common
    )
    setup["tcs_item"] = fx.submit_menu_item(api, setup.cook_id, tcs["id"])
    cold = fx.draft_menu_item(
        api, setup.cook, name="Chilled Beet Salad", food_category="NON_TCS", **common
    )
    setup["non_tcs_item"] = fx.submit_menu_item(api, setup.cook_id, cold["id"])
    return setup


def _approve_item(api, menu_item_id):
    return api.review_menu_item(
        menu_item_id,
        factories.approve_menu_item_payload(allergen_review_notes="soy declared"),
        REVIEWER_ONE_HEADERS,
    )


def test_04_tcs_dish_is_refused_when_the_verified_kitchen_is_not_commercial(api):
    """A TCS dish cannot be approved for a cottage kitchen under a policy that forbids it.

    PRD: "When the state policy sets `tcs_requires_commercial_kitchen` and the item's `food_category` is `TCS`, the cook's `verified_kitchen_type` is `COMMERCIAL_SHARED` — `ERR_TCS_REQUIRES_COMMERCIAL_KITCHEN`, 422, on menu-item approval."
    Design: Difficulty/cross_entity_state_dependency/tcs_approval_gated_by_verified_kitchen_type_and_state_policy
    """
    setup = _cottage_kitchen_scenario(api)

    resp = _approve_item(api, setup.tcs_item["id"])

    validate_error(resp, ApiErrorId.TCS_REQUIRES_COMMERCIAL_KITCHEN, 422)
    item = fx.read_menu_item(api, setup.tcs_item["id"])
    assert item["review_status"] == "UNDER_REVIEW"
    assert item["approved_at"] is None
    assert item["approved_by_user_id"] is None


def test_05_the_non_tcs_control_dish_of_the_same_cook_is_approved(api):
    """A dish differing only in `food_category` approves, so the block is the TCS conjunction.

    PRD: "When all of that passes, `approved_by_user_id` is stamped from `X-User-ID`, `approved_at` from the logical clock, and `delist_reason` is cleared to null."
    Design: Difficulty/cross_entity_state_dependency/tcs_approval_gated_by_verified_kitchen_type_and_state_policy
    """
    setup = _cottage_kitchen_scenario(api)
    validate_error(
        _approve_item(api, setup.tcs_item["id"]),
        ApiErrorId.TCS_REQUIRES_COMMERCIAL_KITCHEN,
        422,
    )

    item = validate_success(_approve_item(api, setup.non_tcs_item["id"]), 200)

    assert item["review_status"] == "APPROVED"
    assert item["approved_by_user_id"] == REVIEWER_ONE
    assert item["approved_at"] is not None
    assert item["delist_reason"] is None
    assert item["requires_refrigeration"] is True


def test_06_a_waived_inspection_writes_home_cottage_as_the_verified_kitchen_type(api):
    """The cook's verified kitchen type is taken from the WAIVED inspection document.

    PRD: "Crossing that edge writes `verified_kitchen_type` on the cook, taking the `kitchen_type_claimed` of the cook's most recent `KITCHEN_INSPECTION` document in `PASSED` or `WAIVED`, ordered by `created_at` descending, and increments the cook's `version`."
    Design: Difficulty/cross_entity_state_dependency/tcs_approval_gated_by_verified_kitchen_type_and_state_policy
    """
    setup = _cottage_kitchen_scenario(api)

    cook = fx.read_cook(api, setup.cook_id)
    document = fx.read_document(api, setup.inspection_document["id"])

    assert document["review_status"] == "WAIVED"
    assert document["kitchen_type_claimed"] == "HOME_COTTAGE"
    assert cook["verified_kitchen_type"] == "HOME_COTTAGE"
    assert cook["onboarding_status"] == "ACTIVE"
    assert cook["compliance_standing"] == "CLEAR"


# ==========================================================================
# The cook's own handoff intervals: half-open, so touching endpoints do not
# collide while a straddling interval does. Window A is [16:00, 18:00),
# window B is [18:00, 20:00) and the rejected candidate is [17:00, 19:00).
# ==========================================================================
WEEK_START = "2026-08-03"
CUTOFF_AT = "2026-08-05T00:00:00Z"
A_START, A_END = "2026-08-08T16:00:00Z", "2026-08-08T18:00:00Z"
B_START, B_END = "2026-08-08T18:00:00Z", "2026-08-08T20:00:00Z"
C_START, C_END = "2026-08-08T17:00:00Z", "2026-08-08T19:00:00Z"
WINDOW_CAPACITY_MEALS = 5


def _window_cook(api):
    """An ACTIVE, CLEAR cook with a weekly limit of 5 meals and no windows yet."""
    return fx.onboard_active_cook(
        api, cook_overrides={"legal_name": "Rui Tanaka", "weekly_capacity_meals": 5}
    )


def _create_window(api, setup, handoff_start_at, handoff_end_at):
    payload = factories.production_window_payload(
        setup.cook_id,
        week_start_date=WEEK_START,
        order_cutoff_at=CUTOFF_AT,
        handoff_start_at=handoff_start_at,
        handoff_end_at=handoff_end_at,
        capacity_meals=WINDOW_CAPACITY_MEALS,
    )
    return api.create_production_window(payload, make_cook_headers(setup.cook_id))


def test_07_a_window_starting_exactly_when_another_ends_is_admitted(api):
    """Exact adjacency at the shared endpoint is legal for two windows of one cook.

    PRD: "Because the interval is half-open, exact adjacency is legal: a new window may start at precisely the instant a previous one ends."
    Design: Difficulty/resource_temporal_overlap/cook_window_half_open_adjacency_allowed_overlap_rejected
    """
    setup = _window_cook(api)

    first = validate_success(_create_window(api, setup, A_START, A_END), 201)
    second = validate_success(_create_window(api, setup, B_START, B_END), 201)

    assert first["status"] == "OPEN"
    assert second["status"] == "OPEN"
    assert _instant(second["handoff_start_at"]) == _instant(A_END)
    assert _instant(second["handoff_end_at"]) == _instant(B_END)


def test_08_a_window_straddling_the_shared_endpoint_is_rejected_as_an_overlap(api):
    """An interval that genuinely overlaps two existing windows of the cook is refused.

    PRD: "The new window's handoff interval does not overlap any of that cook's non-terminal windows — `ERR_WINDOW_OVERLAP`, 409, on production-window creation."
    Design: Difficulty/resource_temporal_overlap/cook_window_half_open_adjacency_allowed_overlap_rejected
    """
    setup = _window_cook(api)
    validate_success(_create_window(api, setup, A_START, A_END), 201)
    validate_success(_create_window(api, setup, B_START, B_END), 201)

    resp = _create_window(api, setup, C_START, C_END)

    validate_error(resp, ApiErrorId.WINDOW_OVERLAP, 409)


def test_09_the_refused_overlap_leaves_exactly_two_uncommitted_windows(api):
    """Only the two admitted windows persist, each with a zero commitment and reserve.

    PRD: "At creation both are derived from a committed count of zero, so a brand-new window's effective capacity equals its declared capacity exactly."
    Design: Difficulty/resource_temporal_overlap/cook_window_half_open_adjacency_allowed_overlap_rejected
    """
    setup = _window_cook(api)
    validate_success(_create_window(api, setup, A_START, A_END), 201)
    validate_success(_create_window(api, setup, B_START, B_END), 201)
    validate_error(_create_window(api, setup, C_START, C_END), ApiErrorId.WINDOW_OVERLAP, 409)

    rows, meta = validate_paginated(
        api.list_production_windows(ADMIN_HEADERS, {"cook_id": setup.cook_id})
    )

    assert meta["total_count"] == 2, f"expected exactly two windows, got {meta['total_count']}"
    assert len(rows) == 2
    for window in rows:
        assert window["committed_meals"] == 0
        assert window["spoilage_reserve_meals"] == 0
        assert window["effective_capacity_meals"] == WINDOW_CAPACITY_MEALS


def test_10_a_cancelled_window_is_ignored_by_the_overlap_comparison(api):
    """An interval that overlapped a since-cancelled window is admitted.

    PRD: "The comparison treats each window's handoff interval as **half-open** — it includes `handoff_start_at` and excludes `handoff_end_at` — and compares the new window against every existing window of that cook whose `status` is `OPEN`, `CUTOFF_PASSED` or `IN_PRODUCTION`; windows already `CLOSED` or `CANCELLED` are ignored."
    Design: Difficulty/resource_temporal_overlap/cook_window_half_open_adjacency_allowed_overlap_rejected
    """
    setup = _window_cook(api)
    first = validate_success(_create_window(api, setup, A_START, A_END), 201)
    validate_error(_create_window(api, setup, C_START, C_END), ApiErrorId.WINDOW_OVERLAP, 409)

    cancelled = fx.cancel_window(api, first, "COOK_REQUEST")
    assert cancelled["status"] == "CANCELLED"
    admitted = validate_success(_create_window(api, setup, C_START, C_END), 201)

    assert admitted["status"] == "OPEN"
    assert _instant(admitted["handoff_start_at"]) == _instant(C_START)
