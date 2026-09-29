"""Pairs of simultaneously violated rules, where only the earliest is reported."""

from test_helpers import (
    LINES_THREE_1000,
    ApiErrorId,
    add_employee_with_period,
    create_group_order,
    draft_order,
    grace_close,
    place_order_raw,
    read_group_order,
    read_order,
    read_period,
    set_clock,
    setup_drafted_order,
    setup_scenario,
    validate_error,
)


def test_period_not_open_beats_personal_card_required():
    """A GRACE period and a missing card both fail; rank 9 outranks rank 39.

    PRD §2.10: "Validations are evaluated strictly in the priority order below.
    The first rule that is violated determines the response, and nothing after it
    runs. This ordering is observable and is part of the contract: a request that
    violates several rules at once reports only the earliest."

    Design: Difficulty/priority_pair_validation_conflict/period_not_open_p9_beats_personal_card_required_p39
    """
    ns = setup_drafted_order(
        employee_overrides={"personal_card_on_file": False},
        order_overrides={"lines": LINES_THREE_1000, "tip_cents": 200},
    )
    grace_close(ns.period["id"])

    response = place_order_raw(ns.order, ns.employee)
    validate_error(response, ApiErrorId.ERR_PERIOD_NOT_OPEN)

    order = read_order(ns.order["id"])
    assert order["fulfillment_status"] == "DRAFT"
    assert order["settlement_status"] == "UNSETTLED"


def test_personal_card_required_is_the_control_arm_when_the_period_stays_open():
    """With the period OPEN the same order reaches the last gate and gets 402.

    PRD §3.5: "Last, if `employee_card_cents` is positive and the employee's
    `personal_card_on_file` is false, the placement is refused with
    `ERR_PERSONAL_CARD_REQUIRED`, which is the only condition in this system
    answered with HTTP 402."

    Design: Difficulty/priority_pair_validation_conflict/period_not_open_p9_beats_personal_card_required_p39
    """
    ns = setup_drafted_order(
        employee_overrides={"personal_card_on_file": False},
        order_overrides={"lines": LINES_THREE_1000, "tip_cents": 200},
    )

    response = place_order_raw(ns.order, ns.employee)
    validate_error(response, ApiErrorId.ERR_PERSONAL_CARD_REQUIRED)
    assert response.status_code == 402

    assert read_order(ns.order["id"])["fulfillment_status"] == "DRAFT"
    assert read_period(ns.period["id"])["reserved_cents"] == 0


def test_group_cutoff_passed_beats_per_person_limit_exceeded():
    """Once the clock reaches the cutoff, rank 19 fires before rank 33.

    PRD §2.10: "The logical clock is strictly before the group order's
    `cutoff_at` — otherwise `ERR_GROUP_CUTOFF_PASSED` (409). Applies to order
    drafting, placement, and group-order reopening."

    Design: Difficulty/priority_pair_validation_conflict/group_cutoff_passed_p19_beats_per_person_limit_p33
    """
    ns = setup_scenario(clock="2026-08-04T10:00:00Z")
    group_order = create_group_order(
        ns,
        ns.employee,
        cutoff_at="2026-08-04T11:00:00Z",
        window_start="2026-08-04T12:00:00Z",
        window_end="2026-08-04T12:30:00Z",
        per_person_limit_cents=3000,
    )
    order = draft_order(
        ns.employee,
        ns.period,
        ns.restaurant,
        ns.location,
        group_order_id=group_order["id"],
        lines=LINES_THREE_1000,
        requested_delivery_at="2026-08-04T12:00:00Z",
    )

    set_clock("2026-08-04T11:00:00Z")
    response = place_order_raw(order, ns.employee)
    validate_error(response, ApiErrorId.ERR_GROUP_CUTOFF_PASSED)
    assert response.status_code == 409, (
        "the cutoff answer is a 409, not the 422 the per-person limit would give"
    )

    refreshed = read_group_order(group_order["id"])
    assert refreshed["status"] == "COLLECTING"
    assert refreshed["member_order_count"] == 0
    assert read_order(order["id"])["fulfillment_status"] == "DRAFT"


def test_per_person_limit_exceeded_is_the_control_arm_before_the_cutoff():
    """Before the cutoff the same 3,264-cent pre-fee base trips rank 33.

    PRD §3.6: "`per_person_limit_cents` is a ceiling of at least 1 cent on each
    member order's pre-fee base — that is, on `subtotal_cents` plus `tax_cents` —
    and it is independent of, and typically stricter than, the budget rule's
    per-meal cap; the fees a member order will later attract do not count against
    it."

    Design: Difficulty/priority_pair_validation_conflict/group_cutoff_passed_p19_beats_per_person_limit_p33
    """
    ns = setup_scenario(clock="2026-08-04T10:00:00Z")
    group_order = create_group_order(
        ns,
        ns.employee,
        cutoff_at="2026-08-04T11:00:00Z",
        window_start="2026-08-04T12:00:00Z",
        window_end="2026-08-04T12:30:00Z",
        per_person_limit_cents=3000,
    )
    ben, ben_period = add_employee_with_period(
        ns, employee_overrides={"full_name": "Ben Barnes", "email": "ben@acme.test"}
    )
    order = draft_order(
        ben,
        ben_period,
        ns.restaurant,
        ns.location,
        group_order_id=group_order["id"],
        lines=LINES_THREE_1000,
        requested_delivery_at="2026-08-04T12:00:00Z",
    )

    response = place_order_raw(order, ben)
    validate_error(response, ApiErrorId.ERR_PER_PERSON_LIMIT_EXCEEDED)
    assert response.status_code == 422

    assert read_order(order["id"])["fulfillment_status"] == "DRAFT"
    assert read_period(ben_period["id"])["reserved_cents"] == 0


def test_outside_eligible_weekday_beats_restaurant_out_of_range():
    """Two 422s collide on one request and rank 17 wins over rank 30.

    PRD §2.10: "The ISO weekday of `requested_delivery_at` is among the pinned
    rule's `eligible_weekdays` — otherwise `ERR_OUTSIDE_ELIGIBLE_WEEKDAY` (422).
    Applies to placement. Weekday eligibility precedes window eligibility, so a
    Saturday noon order reports the weekday, not the window."

    Design: Difficulty/priority_pair_validation_conflict/eligible_weekday_p17_beats_restaurant_out_of_range_p30_same_http_status
    """
    ns = setup_drafted_order(
        program_overrides={"eligible_cuisines": ["THAI", "SALAD", "PIZZA"]},
        restaurant_overrides={
            "name": "Pizza Rim",
            "cuisine": "PIZZA",
            "grid_x_km": 0.0,
            "grid_y_km": 9.0,
            "delivery_radius_km": 12.0,
        },
        order_overrides={"requested_delivery_at": "2026-08-01T12:00:00Z"},
    )

    response = place_order_raw(ns.order, ns.employee)
    error = validate_error(response, ApiErrorId.ERR_OUTSIDE_ELIGIBLE_WEEKDAY)
    assert error["error_id"] != ApiErrorId.ERR_RESTAURANT_OUT_OF_RANGE.value, (
        "2026-08-01 is ISO weekday 6, which is checked before the radius test"
    )
    assert error["error_id"] != ApiErrorId.ERR_CUISINE_NOT_ELIGIBLE.value

    assert read_order(ns.order["id"])["fulfillment_status"] == "DRAFT"
    assert read_period(ns.period["id"])["reserved_cents"] == 0


def test_restaurant_out_of_range_is_the_control_arm_on_an_eligible_weekday():
    """On a Monday the weekday gate passes and the 9.000 km reach test fires.

    PRD §2.10: "The rounded distance from dock to restaurant is within the
    tighter of the two radius limits — otherwise `ERR_RESTAURANT_OUT_OF_RANGE`
    (422). Applies to placement and group-order creation."

    Design: Difficulty/priority_pair_validation_conflict/eligible_weekday_p17_beats_restaurant_out_of_range_p30_same_http_status
    """
    ns = setup_drafted_order(
        program_overrides={"eligible_cuisines": ["THAI", "SALAD", "PIZZA"]},
        restaurant_overrides={
            "name": "Pizza Rim",
            "cuisine": "PIZZA",
            "grid_x_km": 0.0,
            "grid_y_km": 9.0,
            "delivery_radius_km": 12.0,
        },
        order_overrides={"requested_delivery_at": "2026-08-03T12:00:00Z"},
    )

    response = place_order_raw(ns.order, ns.employee)
    error = validate_error(response, ApiErrorId.ERR_RESTAURANT_OUT_OF_RANGE)
    assert error["error_id"] != ApiErrorId.ERR_CUISINE_NOT_ELIGIBLE.value, (
        "PIZZA is in the program's allow-list, so only the reach test fails"
    )

    assert read_order(ns.order["id"])["fulfillment_status"] == "DRAFT"
    assert read_period(ns.period["id"])["reserved_cents"] == 0
