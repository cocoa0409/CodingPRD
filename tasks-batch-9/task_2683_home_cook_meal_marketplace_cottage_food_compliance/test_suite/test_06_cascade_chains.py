"""The two named multi-hop cascades of PRD 2.9, walked link by link.

The suspension cascade runs from a substantiated safety incident through the
cook's standing, the cook's approved dishes, that cook's open windows and the
orders sitting on them, ending at the recomputed payout balance. The window-close
cascade runs from a closing window through the capture of its handed-off
authorised orders, the cook's revenue counters, and the cap-driven delisting and
bouncing of menu items.

Both cascades are immediate and synchronous, so every assertion below reads the
downstream rows straight after the single triggering request returns. The harness
restarts the server before every test, so each test rebuilds the whole chain.
"""

from test_helpers import (
    DINER_TWO_HEADERS,
    OFFICER_TWO,
    fixtures as fx,
)


# ==========================================================================
# The suspension cascade: substantiated incident -> zeroed payout
# ==========================================================================
def _substantiation_chain(api):
    """An ACTIVE, CLEAR cook with one APPROVED dish, one OPEN window holding one
    ROUTED order of quantity 2, and one CRITICAL incident sitting in TRIAGED."""
    setup = fx.selling_cook(
        api,
        state_code="CA",
        cook_overrides={"legal_name": "Hana Iqbal", "weekly_capacity_meals": 10},
        item_overrides={
            "name": "Chana Masala Pot",
            "food_category": "NON_TCS",
            "allergens": ["SESAME"],
            "shelf_life_days": 6,
            "unit_price_cents": 1500,
        },
        window_overrides={"capacity_meals": 10},
    )
    order = fx.routed_order(api, setup, quantity=2)
    incident = fx.report_incident(
        api,
        setup.cook_id,
        subject_type="ORDER",
        order_id=order["id"],
        category="FOODBORNE_ILLNESS",
        severity="CRITICAL",
        description="hospitalisation reported after handoff",
        occurred_at="2026-08-01T12:00:00Z",
    )
    triaged = fx.triage_incident(api, incident["id"], "ACCEPT")
    assert triaged["status"] == "TRIAGED"
    setup.update(order=order, incident=incident)
    return setup


def test_01_substantiation_recomputes_the_authoritative_safety_score(api):
    """Link one and two: the incident becomes SUBSTANTIATED and charges the score down to 50.

    PRD: "The **authoritative** score — the one written to `safety_score` and the only one that ever moves `compliance_standing` — sums, over the cook's incidents whose `status` is `SUBSTANTIATED`, each incident's points multiplied by its decay weight, then subtracts that total charge from 100 and floors the result at zero."
    Design: Difficulty/transitive_cascade/cascade_a_substantiated_incident_to_payout_zeroing_depth_six
    """
    setup = _substantiation_chain(api)
    assert fx.read_cook(api, setup.cook_id)["safety_score"] == 100

    adjudicated = fx.adjudicate_incident(
        api, setup.incident["id"], "SUBSTANTIATE", resolution_note="lab confirmed pathogen match"
    )

    assert adjudicated["status"] == "SUBSTANTIATED"
    assert adjudicated["severity_points"] == 50
    assert adjudicated["adjudicated_by_user_id"] == OFFICER_TWO
    assert adjudicated["adjudicated_at"] is not None

    cook = fx.read_cook(api, setup.cook_id)
    assert cook["safety_score"] == 50


def test_02_the_recomputed_score_suspends_the_standing_dimension_alone(api):
    """Link three: a score below 60 selects SUSPENDED and leaves onboarding_status ACTIVE.

    PRD: "On the system-driven edges, `CLEAR → WARNED` fires when the recomputed score is at least 60 and below 80 and stamps `standing_reason` as the literal `SAFETY_SCORE_WARN`; `CLEAR → SUSPENDED` and `WARNED → SUSPENDED` fire when the recomputed score is below 60 and stamp `standing_reason` as the literal `SAFETY_SCORE_SUSPEND`."
    Design: Difficulty/transitive_cascade/cascade_a_substantiated_incident_to_payout_zeroing_depth_six
    """
    setup = _substantiation_chain(api)
    before = fx.read_cook(api, setup.cook_id)
    assert before["compliance_standing"] == "CLEAR"

    fx.adjudicate_incident(
        api, setup.incident["id"], "SUBSTANTIATE", resolution_note="lab confirmed pathogen match"
    )

    cook = fx.read_cook(api, setup.cook_id)
    assert cook["compliance_standing"] == "SUSPENDED"
    assert cook["standing_reason"] == "SAFETY_SCORE_SUSPEND"
    assert cook["onboarding_status"] == "ACTIVE"
    assert cook["version"] > before["version"]


def test_03_suspension_delists_every_approved_dish_of_that_cook(api):
    """Link four: the cook's APPROVED dish is delisted with delist_reason COOK_SUSPENDED.

    PRD: "Every `MenuItem` of that cook in `APPROVED` moves to `DELISTED` with `delist_reason` set to `COOK_SUSPENDED`."
    Design: Difficulty/transitive_cascade/cascade_a_substantiated_incident_to_payout_zeroing_depth_six
    """
    setup = _substantiation_chain(api)
    assert fx.read_menu_item(api, setup.menu_item["id"])["review_status"] == "APPROVED"

    fx.adjudicate_incident(
        api, setup.incident["id"], "SUBSTANTIATE", resolution_note="lab confirmed pathogen match"
    )

    item = fx.read_menu_item(api, setup.menu_item["id"])
    assert item["review_status"] == "DELISTED"
    assert item["delist_reason"] == "COOK_SUSPENDED"


def test_04_the_emptied_menu_cancels_the_open_production_window(api):
    """Link five: with zero approved dishes left, the OPEN window is cancelled NO_APPROVED_MENU.

    PRD: "Because the cook now has zero `APPROVED` menu items, every `ProductionWindow` of that cook in `OPEN` or `CUTOFF_PASSED` moves to `CANCELLED` with `cancelled_reason` set to `NO_APPROVED_MENU`."
    Design: Difficulty/transitive_cascade/cascade_a_substantiated_incident_to_payout_zeroing_depth_six
    """
    setup = _substantiation_chain(api)
    before = fx.read_window(api, setup.window["id"])
    assert before["status"] == "OPEN"
    assert before["cancelled_reason"] is None

    fx.adjudicate_incident(
        api, setup.incident["id"], "SUBSTANTIATE", resolution_note="lab confirmed pathogen match"
    )

    window = fx.read_window(api, setup.window["id"])
    assert window["status"] == "CANCELLED"
    assert window["cancelled_reason"] == "NO_APPROVED_MENU"
    assert window["version"] > before["version"]


def test_05_the_cancelled_window_voids_its_routed_order_and_returns_its_meals(api):
    """Link six: the ROUTED order is cancelled and voided, its meals return and the payout zeroes.

    PRD: "Because those windows were cancelled, every `Order` on them in `PLACED` or `ROUTED` moves to `CANCELLED` with `cancelled_reason` set to `WINDOW_CANCELLED`, its `payment_status` moves `AUTHORIZED → VOIDED`, the owning window's `committed_meals` is decremented by that order's `quantity`, and any pickup-hub slot the order held is released (the hub's `assigned_order_count` decremented, which may reopen a `CLOSED` hub)."
    Design: Difficulty/transitive_cascade/cascade_a_substantiated_incident_to_payout_zeroing_depth_six
    """
    setup = _substantiation_chain(api)
    before_order = fx.read_order(api, setup.order["id"])
    assert before_order["fulfillment_status"] == "ROUTED"
    assert before_order["payment_status"] == "AUTHORIZED"
    assert fx.read_window(api, setup.window["id"])["committed_meals"] == 2

    fx.adjudicate_incident(
        api, setup.incident["id"], "SUBSTANTIATE", resolution_note="lab confirmed pathogen match"
    )

    order = fx.read_order(api, setup.order["id"])
    assert order["fulfillment_status"] == "CANCELLED"
    assert order["cancelled_reason"] == "WINDOW_CANCELLED"
    assert order["payment_status"] == "VOIDED"

    window = fx.read_window(api, setup.window["id"])
    assert window["committed_meals"] == 0
    assert window["spoilage_reserve_meals"] == 0
    assert window["effective_capacity_meals"] == 10

    cook = fx.read_cook(api, setup.cook_id)
    assert cook["pending_payout_cents"] == 0
    assert cook["ytd_cottage_revenue_cents"] == 0


# ==========================================================================
# The window-close cascade: capture -> recognised revenue -> cap-reached menu
# ==========================================================================
def _cap_reaching_chain(api):
    """A VT cook whose 6000-cent annual cap is exactly met by two HANDED_OFF orders.

    Dish A is APPROVED and dish B sits UNDER_REVIEW with revision_round 0, so the
    cap arm of the close cascade has one item to delist and one to bounce.
    """
    setup = fx.selling_cook(
        api,
        state_code="VT",
        policy_overrides={
            "cottage_food_annual_cap_cents": 6000,
            "allowed_kitchen_types": ["HOME_COTTAGE"],
            "max_shelf_life_days_non_refrigerated": 21,
        },
        cook_overrides={
            "legal_name": "Ines Blanc",
            "claimed_kitchen_type": "HOME_COTTAGE",
            "weekly_capacity_meals": 10,
        },
        item_overrides={
            "name": "Maple Granola",
            "food_category": "BAKED_NON_TCS",
            "allergens": ["TREE_NUT"],
            "shelf_life_days": 14,
            "unit_price_cents": 1200,
        },
        window_overrides={"capacity_meals": 10},
        zone_overrides={"postal_codes": ["05401"]},
        inspection_decision="WAIVE",
    )
    item_b = fx.draft_menu_item(
        api,
        setup.cook,
        name="Cider Doughnuts",
        food_category="BAKED_NON_TCS",
        allergens=["WHEAT"],
        shelf_life_days=5,
        unit_price_cents=700,
    )
    item_b = fx.submit_menu_item(api, setup.cook_id, item_b["id"])
    assert item_b["review_status"] == "UNDER_REVIEW"
    assert item_b["revision_round"] == 0

    order_one = fx.routed_order(api, setup, quantity=2)
    order_two = fx.routed_order(api, setup, quantity=3, diner_headers=DINER_TWO_HEADERS)
    assert order_one["subtotal_cents"] == 2400
    assert order_two["subtotal_cents"] == 3600

    fx.open_window_into_production(api, setup)
    order_one = fx.hand_off_order(api, setup, order_one)
    order_two = fx.hand_off_order(api, setup, order_two)
    assert order_one["payment_status"] == "AUTHORIZED"
    assert order_two["payment_status"] == "AUTHORIZED"

    setup.update(item_a=setup.menu_item, item_b=item_b, order_one=order_one, order_two=order_two)
    return setup


def test_06_window_close_captures_every_handed_off_authorized_order(api):
    """Links one and two: the window closes and both handed-off authorised orders capture.

    PRD: "Every `Order` on that window whose `fulfillment_status` is `HANDED_OFF` and whose `payment_status` is still `AUTHORIZED` has its payment moved `AUTHORIZED → CAPTURED`, with `captured_at` and `effective_year` stamped."
    Design: Difficulty/transitive_cascade/cascade_b_window_close_to_cap_reached_menu_bounce_depth_four
    """
    setup = _cap_reaching_chain(api)

    window = fx.close_window(api, setup)
    assert window["status"] == "CLOSED"
    assert window["closed_at"] is not None
    assert window["closed_at"].startswith("2026-08-08T18:00:00")

    for order_id in (setup.order_one["id"], setup.order_two["id"]):
        order = fx.read_order(api, order_id)
        assert order["payment_status"] == "CAPTURED"
        assert order["fulfillment_status"] == "HANDED_OFF"
        assert order["effective_year"] == 2026
        assert order["captured_at"] is not None


def test_07_capture_recomputes_recognised_revenue_and_the_pending_payout(api):
    """Link three: the captured subtotals land in the cook's revenue and payout counters.

    PRD: "`pending_payout_cents` is the sum, over that cook's orders whose `payment_status` is `CAPTURED` or `PARTIALLY_REFUNDED` and which are not yet covered by a statement in `FINALIZED` or `PAID`, of the order's `cook_earnings_cents` less its `cook_chargeback_cents`."
    Design: Difficulty/transitive_cascade/cascade_b_window_close_to_cap_reached_menu_bounce_depth_four
    """
    setup = _cap_reaching_chain(api)
    before = fx.read_cook(api, setup.cook_id)
    assert before["ytd_cottage_revenue_cents"] == 0
    assert before["pending_payout_cents"] == 0

    fx.close_window(api, setup)

    order_one = fx.read_order(api, setup.order_one["id"])
    order_two = fx.read_order(api, setup.order_two["id"])
    assert order_one["platform_commission_cents"] == 540
    assert order_one["cook_earnings_cents"] == 1860
    assert order_two["platform_commission_cents"] == 810
    assert order_two["cook_earnings_cents"] == 2790

    cook = fx.read_cook(api, setup.cook_id)
    assert cook["ytd_gross_sales_cents"] == 6000
    assert cook["ytd_cottage_revenue_cents"] == 6000
    assert cook["pending_payout_cents"] == 4650


def test_08_cap_reached_delists_the_approved_item_and_bounces_the_reviewed_one(api):
    """Link four forks by menu-item state: APPROVED is delisted, UNDER_REVIEW is bounced.

    PRD: "Because recognised revenue moved, the cook's `cap_status` is recomputed; and when it becomes `CAP_REACHED`, every `MenuItem` of that cook in `APPROVED` moves to `DELISTED` with `delist_reason` set to `CAP_REACHED`, while every `MenuItem` of that cook in `UNDER_REVIEW` is bounced back — to `REVISION_REQUESTED` when its `revision_round` is below the two-round ceiling, or to `REJECTED` when `revision_round` has already reached that ceiling — and in either case `revision_round` is incremented by one."
    Design: Difficulty/transitive_cascade/cascade_b_window_close_to_cap_reached_menu_bounce_depth_four
    """
    setup = _cap_reaching_chain(api)
    assert fx.read_cook(api, setup.cook_id)["cap_status"] == "UNDER_CAP"

    fx.close_window(api, setup)

    cook = fx.read_cook(api, setup.cook_id)
    assert cook["cap_status"] == "CAP_REACHED"

    item_a = fx.read_menu_item(api, setup.item_a["id"])
    assert item_a["review_status"] == "DELISTED"
    assert item_a["delist_reason"] == "CAP_REACHED"

    item_b = fx.read_menu_item(api, setup.item_b["id"])
    assert item_b["review_status"] == "REVISION_REQUESTED"
    assert item_b["revision_round"] == 1
