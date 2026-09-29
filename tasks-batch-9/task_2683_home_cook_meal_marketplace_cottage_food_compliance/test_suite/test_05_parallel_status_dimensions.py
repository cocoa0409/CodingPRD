"""Two-dimensional status models and the bounded menu-item revision cycle.

A `Cook` carries `onboarding_status` beside `compliance_standing`, and an `Order`
carries `fulfillment_status` beside `payment_status`; neither pair's transition
table writes the other's field (PRD 2.7). The menu-item revision loop is bounded
at two rounds, and the counter itself chooses the exit edge (PRD 3.2).

The harness restarts the server before every test, so each test builds all of its
own state from scratch.
"""

from test_helpers import (
    ApiErrorId,
    fixtures as fx,
    get_success_data,
    make_cook_headers,
    validate_error,
)


# ==========================================================================
# Cook: onboarding_status and compliance_standing move independently
# ==========================================================================
def test_01_suspend_moves_standing_only_and_leaves_onboarding_active(api):
    """A direct SUSPEND writes compliance_standing and standing_reason while onboarding_status stays ACTIVE.

    PRD: "A cook may perfectly well be `ACTIVE` and `SUSPENDED` at the same time, and that combination is exactly what blocks new listings and new orders while leaving the onboarding record intact."
    Design: Difficulty/non_linear_state_machine/cook_onboarding_and_standing_dimensions_move_independently
    """
    setup = fx.onboard_active_cook(api, state_code="CA")
    fx.draft_menu_item(api, setup.cook, name="Congee Jar", unit_price_cents=900)

    before = fx.read_cook(api, setup.cook_id)
    assert before["onboarding_status"] == "ACTIVE"
    assert before["compliance_standing"] == "CLEAR"

    suspended = fx.suspend_cook(api, setup.cook_id, reason="MANUAL_SAFETY_REVIEW")

    assert suspended["compliance_standing"] == "SUSPENDED"
    assert suspended["onboarding_status"] == "ACTIVE"
    assert suspended["standing_reason"] == "MANUAL_SAFETY_REVIEW"
    assert suspended["version"] == before["version"] + 1

    persisted = fx.read_cook(api, setup.cook_id)
    assert persisted["compliance_standing"] == "SUSPENDED"
    assert persisted["onboarding_status"] == "ACTIVE"


def test_02_submit_is_blocked_while_active_and_suspended(api):
    """A cook who is ACTIVE but SUSPENDED cannot submit a draft dish for review.

    PRD: "All three require that the owning cook's `onboarding_status` be `ACTIVE` (`ERR_COOK_NOT_ACTIVE`) and that their `compliance_standing` be neither `SUSPENDED` nor `REVOKED` (`ERR_COOK_SUSPENDED`); the resubmission leg additionally requires that the cook's `cap_status` not be `CAP_REACHED`, because a cook who has exhausted the state's annual cottage-food revenue has nothing left to sell this year."
    Design: Difficulty/non_linear_state_machine/cook_onboarding_and_standing_dimensions_move_independently
    """
    setup = fx.onboard_active_cook(api, state_code="CA")
    item = fx.draft_menu_item(api, setup.cook, name="Congee Jar", unit_price_cents=900)
    fx.suspend_cook(api, setup.cook_id, reason="MANUAL_SAFETY_REVIEW")

    resp = api.submit_menu_item(item["id"], make_cook_headers(setup.cook_id))
    validate_error(resp, ApiErrorId.COOK_SUSPENDED, 409)

    unchanged = fx.read_menu_item(api, item["id"])
    assert unchanged["review_status"] == "DRAFT"
    assert unchanged["revision_round"] == 0

    cook = fx.read_cook(api, setup.cook_id)
    assert cook["onboarding_status"] == "ACTIVE"
    assert cook["compliance_standing"] == "SUSPENDED"


def test_03_reinstate_returns_standing_to_clear_without_replaying_onboarding(api):
    """REINSTATE moves the standing dimension back to CLEAR and the blocked submit then succeeds.

    PRD: "An `action` of `REINSTATE` is available only from `SUSPENDED` and only when the cook has zero incidents in `INTAKE` or `TRIAGED`; it returns the cook to `CLEAR` but un-delists nothing."
    Design: Difficulty/non_linear_state_machine/cook_onboarding_and_standing_dimensions_move_independently
    """
    setup = fx.onboard_active_cook(api, state_code="CA")
    item = fx.draft_menu_item(api, setup.cook, name="Congee Jar", unit_price_cents=900)
    fx.suspend_cook(api, setup.cook_id, reason="MANUAL_SAFETY_REVIEW")
    validate_error(
        api.submit_menu_item(item["id"], make_cook_headers(setup.cook_id)),
        ApiErrorId.COOK_SUSPENDED,
        409,
    )

    reinstated = fx.reinstate_cook(api, setup.cook_id, reason="REVIEW_CLOSED_NO_FINDING")

    assert reinstated["compliance_standing"] == "CLEAR"
    assert reinstated["onboarding_status"] == "ACTIVE"

    submitted = get_success_data(
        api.submit_menu_item(item["id"], make_cook_headers(setup.cook_id))
    )
    assert submitted["review_status"] == "UNDER_REVIEW"
    assert submitted["revision_round"] == 0


# ==========================================================================
# MenuItem: the revision cycle is a bounded loop whose exit a counter picks
# ==========================================================================
def _drafted_item_under_review(api):
    """An ACTIVE cook whose dish sits in UNDER_REVIEW with revision_round 0."""
    setup = fx.onboard_active_cook(api, state_code="CA")
    item = fx.draft_menu_item(
        api,
        setup.cook,
        name="Lemon Loaf",
        food_category="BAKED_NON_TCS",
        allergens=["WHEAT", "EGG"],
        shelf_life_days=7,
        unit_price_cents=800,
    )
    assert item["review_status"] == "DRAFT"
    assert item["revision_round"] == 0
    submitted = fx.submit_menu_item(api, setup.cook_id, item["id"])
    assert submitted["review_status"] == "UNDER_REVIEW"
    return setup, item


def test_04_two_revision_requests_stay_inside_the_loop(api):
    """The first two REQUEST_REVISION decisions land on REVISION_REQUESTED and count the rounds.

    PRD: "A `decision` of `REQUEST_REVISION` on an item that is `UNDER_REVIEW` increments `revision_round` by one and moves the item `UNDER_REVIEW → REVISION_REQUESTED` — but only while `revision_round` is still below two."
    Design: Difficulty/non_linear_state_machine/menu_item_revision_cycle_terminates_at_max_rounds
    """
    setup, item = _drafted_item_under_review(api)

    first = fx.review_menu_item(
        api, item["id"], "REQUEST_REVISION", revision_note="round one - clarify net weight"
    )
    assert first["review_status"] == "REVISION_REQUESTED"
    assert first["revision_round"] == 1

    back = fx.submit_menu_item(api, setup.cook_id, item["id"])
    assert back["review_status"] == "UNDER_REVIEW"
    assert back["revision_round"] == 1

    second = fx.review_menu_item(
        api, item["id"], "REQUEST_REVISION", revision_note="round two - allergen wording"
    )
    assert second["review_status"] == "REVISION_REQUESTED"
    assert second["revision_round"] == 2


def test_05_third_revision_request_rejects_and_still_counts_the_round(api):
    """The third REQUEST_REVISION lands on REJECTED and leaves revision_round at 3.

    PRD: "Once `revision_round` has already reached two, the very same decision still increments the counter and instead lands on `UNDER_REVIEW → REJECTED`: the third revision request is a rejection, and the loop terminates."
    Design: Difficulty/non_linear_state_machine/menu_item_revision_cycle_terminates_at_max_rounds
    """
    setup, item = _drafted_item_under_review(api)

    fx.review_menu_item(
        api, item["id"], "REQUEST_REVISION", revision_note="round one - clarify net weight"
    )
    fx.submit_menu_item(api, setup.cook_id, item["id"])
    fx.review_menu_item(
        api, item["id"], "REQUEST_REVISION", revision_note="round two - allergen wording"
    )
    fx.submit_menu_item(api, setup.cook_id, item["id"])

    third = fx.review_menu_item(
        api, item["id"], "REQUEST_REVISION", revision_note="round three - still non-compliant"
    )
    assert third["review_status"] == "REJECTED"
    assert third["revision_round"] == 3

    persisted = fx.read_menu_item(api, item["id"])
    assert persisted["review_status"] == "REJECTED"
    assert persisted["revision_round"] == 3


def test_06_rejected_item_cannot_be_submitted_again(api):
    """Submission against the terminal REJECTED state is an invalid menu-item transition.

    PRD: "Submitting from any other state — from `UNDER_REVIEW`, `APPROVED` or the terminal `REJECTED` — is `ERR_INVALID_MENU_ITEM_TRANSITION`."
    Design: Difficulty/non_linear_state_machine/menu_item_revision_cycle_terminates_at_max_rounds
    """
    setup, item = _drafted_item_under_review(api)
    for note in ("round one", "round two", "round three"):
        fx.review_menu_item(api, item["id"], "REQUEST_REVISION", revision_note=note)
        if note != "round three":
            fx.submit_menu_item(api, setup.cook_id, item["id"])
    rejected = fx.read_menu_item(api, item["id"])
    assert rejected["review_status"] == "REJECTED"
    assert rejected["revision_round"] == 3

    resp = api.submit_menu_item(item["id"], make_cook_headers(setup.cook_id))
    validate_error(resp, ApiErrorId.INVALID_MENU_ITEM_TRANSITION, 409)

    held = fx.read_menu_item(api, item["id"])
    assert held["review_status"] == "REJECTED"
    assert held["revision_round"] == 3


# ==========================================================================
# Order: fulfillment_status and payment_status move independently
# ==========================================================================
def test_07_walking_fulfillment_to_handed_off_leaves_payment_authorized(api):
    """PLACED -> ROUTED -> IN_PRODUCTION -> HANDED_OFF never touches the money dimension.

    PRD: "`IN_PRODUCTION → HANDED_OFF` is a cook action requiring that the logical clock have reached the window's `handoff_start_at`, an earlier attempt being `ERR_HANDOFF_NOT_STARTED`; again no money field moves, because capture happens either at delivery confirmation or at window close."
    Design: Difficulty/non_linear_state_machine/order_fulfillment_and_payment_dimensions_move_independently
    """
    setup = fx.handed_off_order_scenario(api, quantity=2)

    order = fx.read_order(api, setup.order["id"])
    assert order["fulfillment_status"] == "HANDED_OFF"
    assert order["payment_status"] == "AUTHORIZED"
    assert order["captured_at"] is None
    assert order["effective_year"] is None
    assert order["subtotal_cents"] == 2400
    assert order["diner_service_fee_cents"] == 216
    assert order["total_charge_cents"] == 2616

    cook = fx.read_cook(api, setup.cook_id)
    assert cook["ytd_gross_sales_cents"] == 0
    assert cook["ytd_cottage_revenue_cents"] == 0
    assert cook["pending_payout_cents"] == 0


def test_08_window_close_captures_without_moving_fulfillment(api):
    """The parent window's close drives AUTHORIZED -> CAPTURED while fulfilment stays HANDED_OFF.

    PRD: "Every `Order` on that window whose `fulfillment_status` is `HANDED_OFF` and whose `payment_status` is still `AUTHORIZED` has its payment moved `AUTHORIZED → CAPTURED`, with `captured_at` and `effective_year` stamped."
    Design: Difficulty/non_linear_state_machine/order_fulfillment_and_payment_dimensions_move_independently
    """
    setup = fx.handed_off_order_scenario(api, quantity=2)
    window = fx.close_window(api, setup)

    assert window["status"] == "CLOSED"
    assert window["closed_at"] is not None
    assert window["closed_at"].startswith("2026-08-08T18:00:00")

    order = fx.read_order(api, setup.order["id"])
    assert order["payment_status"] == "CAPTURED"
    assert order["fulfillment_status"] == "HANDED_OFF"
    assert order["effective_year"] == 2026
    assert order["captured_at"] is not None


def test_09_capture_through_window_close_recomputes_the_cook_counters(api):
    """Capture through the window-close cascade recomputes the cook's revenue and payout counters.

    PRD: "Because those payments captured, the cook's `ytd_gross_sales_cents`, `ytd_cottage_revenue_cents` and `pending_payout_cents` are all recomputed."
    Design: Difficulty/non_linear_state_machine/order_fulfillment_and_payment_dimensions_move_independently
    """
    setup = fx.handed_off_order_scenario(api, quantity=2)
    before = fx.read_cook(api, setup.cook_id)
    assert before["ytd_cottage_revenue_cents"] == 0

    fx.close_window(api, setup)

    order = fx.read_order(api, setup.order["id"])
    assert order["platform_commission_cents"] == 540
    assert order["cook_earnings_cents"] == 1860

    cook = fx.read_cook(api, setup.cook_id)
    assert cook["ytd_gross_sales_cents"] == 2400
    assert cook["ytd_cottage_revenue_cents"] == 2400
    assert cook["pending_payout_cents"] == 1860
    assert cook["cap_status"] == "UNDER_CAP"
