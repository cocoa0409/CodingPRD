"""Which of two simultaneously-violated checks is reported.

Every request in this file breaks two rules of the single ordered validation
ladder at once, and the PRD fixes exactly one answer: the lower-numbered check
is the one the caller learns about. Each pair is also fired one rule at a time
so that both rules are demonstrably live before the masking claim is made.
"""

from test_helpers import (
    DINER_THREE_HEADERS,
    DINER_TWO_HEADERS,
    REVIEWER_ONE_HEADERS,
    ApiErrorId,
    assert_capacity_triple,
    factories,
    fixtures as fx,
    validate_error,
)

# The cook of the cutoff/capacity pair: weekly limit 5, one window of capacity 5
# already holding a quantity-4 order, so committed_meals is 4, the ten-percent
# spoilage reserve is 1 meal and effective capacity is 4 (PRD 3.3).
FIRST_ORDER_QUANTITY = 4
SECOND_ORDER_QUANTITY = 3
WINDOW_CAPACITY_MEALS = 5
CUTOFF_AT = "2026-08-05T00:00:00Z"
AFTER_CUTOFF = "2026-08-06T00:00:00Z"


def _cutoff_capacity_scenario(api, with_first_order=True):
    """An ACTIVE cook, one APPROVED dish at 1200 cents and one OPEN window."""
    setup = fx.selling_cook(
        api,
        cook_overrides={"legal_name": "Jae Park", "weekly_capacity_meals": 5},
        item_overrides={
            "name": "Kimchi Jar",
            "food_category": "NON_TCS",
            "allergens": ["FISH"],
            "shelf_life_days": 10,
            "unit_price_cents": 1200,
        },
        window_overrides={
            "capacity_meals": WINDOW_CAPACITY_MEALS,
            "order_cutoff_at": CUTOFF_AT,
        },
    )
    if with_first_order:
        setup["first_order"] = fx.order_in_scenario(
            api, setup, quantity=FIRST_ORDER_QUANTITY
        )
    return setup


def _place(api, setup, quantity, headers):
    payload = factories.order_payload(
        setup.menu_item["id"],
        setup.window["id"],
        setup.zone["id"],
        quantity=quantity,
    )
    return api.create_order(payload, headers)


def test_01_capacity_alone_rejects_an_oversized_order_before_the_cutoff(api):
    """A quantity above remaining effective capacity is refused while the cutoff is still ahead.

    PRD: "Fourth, the order is admitted only when the pre-admission committed count plus the requested `quantity` is less than or equal to that effective capacity; a total exactly equal to the effective capacity is admitted, and one meal more is rejected with `ERR_WINDOW_CAPACITY_EXCEEDED`."
    Design: Difficulty/priority_pair_validation_conflict/cutoff_priority_14_beats_capacity_priority_46
    """
    setup = _cutoff_capacity_scenario(api)

    resp = _place(api, setup, SECOND_ORDER_QUANTITY, DINER_TWO_HEADERS)

    validate_error(resp, ApiErrorId.WINDOW_CAPACITY_EXCEEDED, 422)


def test_02_passed_cutoff_masks_the_capacity_violation(api):
    """When both the cutoff check and the capacity check fail, only the cutoff error is reported.

    PRD: "Lower-numbered checks are evaluated first and mask everything below them."
    Design: Difficulty/priority_pair_validation_conflict/cutoff_priority_14_beats_capacity_priority_46
    """
    setup = _cutoff_capacity_scenario(api)
    # Confirm the capacity rule is live on this exact payload first.
    validate_error(
        _place(api, setup, SECOND_ORDER_QUANTITY, DINER_TWO_HEADERS),
        ApiErrorId.WINDOW_CAPACITY_EXCEEDED,
        422,
    )

    fx.set_clock(api, AFTER_CUTOFF)
    resp = _place(api, setup, SECOND_ORDER_QUANTITY, DINER_THREE_HEADERS)

    error = validate_error(resp, ApiErrorId.WINDOW_CUTOFF_PASSED, 409)
    assert ApiErrorId.WINDOW_CAPACITY_EXCEEDED not in error["message"], (
        "the masked capacity error must not leak into the reported message: "
        f"{error['message']!r}"
    )


def test_03_neither_rejected_placement_moves_the_committed_meal_counter(api):
    """Two refused placements leave the window's conserved meal counter and status alone.

    PRD: "At every instant, a window's `committed_meals` equals the sum of `quantity` over the orders on that window whose `fulfillment_status` is `PLACED`, `ROUTED`, `IN_PRODUCTION`, `HANDED_OFF` or `DELIVERED`."
    Design: Difficulty/priority_pair_validation_conflict/cutoff_priority_14_beats_capacity_priority_46
    """
    setup = _cutoff_capacity_scenario(api)
    validate_error(
        _place(api, setup, SECOND_ORDER_QUANTITY, DINER_TWO_HEADERS),
        ApiErrorId.WINDOW_CAPACITY_EXCEEDED,
        422,
    )
    fx.set_clock(api, AFTER_CUTOFF)
    validate_error(
        _place(api, setup, SECOND_ORDER_QUANTITY, DINER_THREE_HEADERS),
        ApiErrorId.WINDOW_CUTOFF_PASSED,
        409,
    )

    window = fx.read_window(api, setup.window["id"])

    assert_capacity_triple(window, FIRST_ORDER_QUANTITY, WINDOW_CAPACITY_MEALS)
    assert window["status"] == "OPEN", (
        "a cutoff instant that has merely arrived does not advance the window: "
        f"{window['status']}"
    )


def test_04_arrival_of_the_cutoff_instant_alone_blocks_a_fitting_order(api):
    """At exactly `order_cutoff_at` an order well inside capacity is still refused.

    PRD: "The window must be `OPEN` and the logical clock must be strictly before its `order_cutoff_at`; a window that has moved past `OPEN`, or one whose cutoff instant has arrived, yields `ERR_WINDOW_CUTOFF_PASSED`."
    Design: Difficulty/priority_pair_validation_conflict/cutoff_priority_14_beats_capacity_priority_46
    """
    setup = _cutoff_capacity_scenario(api, with_first_order=False)
    fx.set_clock(api, CUTOFF_AT)

    resp = _place(api, setup, 1, DINER_TWO_HEADERS)

    validate_error(resp, ApiErrorId.WINDOW_CUTOFF_PASSED, 409)
    assert_capacity_triple(fx.read_window(api, setup.window["id"]), 0, WINDOW_CAPACITY_MEALS)


# ==========================================================================
# The certificate-expiry / shelf-life pair on menu-item approval.
# The dish declares a 30-day shelf life against a 14-day state ceiling, so the
# shelf-life check always fails; the certificate expires on 2026-09-01, so the
# expiry check fails only once the clock has moved past that date.
# ==========================================================================
CERT_ISSUED_ON = "2025-09-01"
CERT_EXPIRES_ON = "2026-09-01"
AFTER_CERT_EXPIRY = "2026-09-02T00:00:00Z"
POLICY_SHELF_LIFE_CEILING_DAYS = 14
ITEM_SHELF_LIFE_DAYS = 30


def _item_under_review_scenario(api, shelf_life_days=ITEM_SHELF_LIFE_DAYS):
    """An ACTIVE cook with a certificate expiring 2026-09-01 and one dish UNDER_REVIEW."""
    setup = fx.onboard_active_cook(
        api,
        policy_overrides={
            "max_shelf_life_days_non_refrigerated": POLICY_SHELF_LIFE_CEILING_DAYS
        },
        cook_overrides={"legal_name": "Kai Mendes", "weekly_capacity_meals": 8},
        cert_overrides={"issued_on": CERT_ISSUED_ON, "expires_on": CERT_EXPIRES_ON},
    )
    item = fx.draft_menu_item(
        api,
        setup.cook,
        name="Shelf-Stable Chutney",
        food_category="NON_TCS",
        allergens=["SOY"],
        shelf_life_days=shelf_life_days,
        requires_refrigeration=False,
        unit_price_cents=950,
    )
    setup["menu_item"] = fx.submit_menu_item(api, setup.cook_id, item["id"])
    return setup


def _approve(api, menu_item_id):
    return api.review_menu_item(
        menu_item_id,
        factories.approve_menu_item_payload(allergen_review_notes="soy declared"),
        REVIEWER_ONE_HEADERS,
    )


def test_05_shelf_life_alone_rejects_while_the_certificate_is_still_current(api):
    """A 30-day shelf life against a 14-day ceiling is refused on its own merits.

    PRD: "A non-refrigerated item's `shelf_life_days` is at most the state policy's `max_shelf_life_days_non_refrigerated` — `ERR_SHELF_LIFE_EXCEEDS_POLICY`, 422, on menu-item approval only."
    Design: Difficulty/priority_pair_validation_conflict/cert_expiry_priority_22_beats_shelf_life_priority_29
    """
    setup = _item_under_review_scenario(api)

    resp = _approve(api, setup.menu_item["id"])

    validate_error(resp, ApiErrorId.SHELF_LIFE_EXCEEDS_POLICY, 422)
    assert fx.read_menu_item(api, setup.menu_item["id"])["review_status"] == "UNDER_REVIEW"


def test_06_expired_certificate_masks_the_shelf_life_violation(api):
    """Once the certificate has lapsed the same approval reports the expiry, not the shelf life.

    PRD: "An expired certificate blocks approval even for a cook who is still `ACTIVE`."
    Design: Difficulty/priority_pair_validation_conflict/cert_expiry_priority_22_beats_shelf_life_priority_29
    """
    setup = _item_under_review_scenario(api)
    validate_error(
        _approve(api, setup.menu_item["id"]), ApiErrorId.SHELF_LIFE_EXCEEDS_POLICY, 422
    )

    fx.set_clock(api, AFTER_CERT_EXPIRY)
    resp = _approve(api, setup.menu_item["id"])

    error = validate_error(resp, ApiErrorId.CERT_EXPIRED, 409)
    assert ApiErrorId.SHELF_LIFE_EXCEEDS_POLICY not in error["message"], (
        "the masked shelf-life error must not leak into the reported message: "
        f"{error['message']!r}"
    )
    item = fx.read_menu_item(api, setup.menu_item["id"])
    assert item["review_status"] == "UNDER_REVIEW"
    assert item["approved_at"] is None
    assert item["approved_by_user_id"] is None


def test_07_moving_the_clock_past_expiry_does_not_rewrite_the_document_or_the_cook(api):
    """The lapse is measured against the clock; the verified document and the ACTIVE cook stand.

    PRD: "Moving the clock does **not** retroactively recompute stored entities, with one deliberate exception: because safety-score decay is a function of elapsed weeks, each cook's `safety_score` is re-evaluated at the new instant, and a cook sitting in `WARNED` whose recomputed score has recovered returns to `CLEAR` (see §3.7)."
    Design: Difficulty/priority_pair_validation_conflict/cert_expiry_priority_22_beats_shelf_life_priority_29
    """
    setup = _item_under_review_scenario(api)
    fx.set_clock(api, AFTER_CERT_EXPIRY)
    validate_error(_approve(api, setup.menu_item["id"]), ApiErrorId.CERT_EXPIRED, 409)

    document = fx.read_document(api, setup.cert_document["id"])
    cook = fx.read_cook(api, setup.cook_id)

    assert document["review_status"] == "VERIFIED", (
        f"the certificate row must not be rewritten by a clock move: {document['review_status']}"
    )
    assert cook["onboarding_status"] == "ACTIVE"
    assert cook["compliance_standing"] == "CLEAR"
    assert cook["safety_score"] == 100
