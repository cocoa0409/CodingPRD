"""Weekly box generation, meal selection, allergen/par/cutoff gating, and box listing.

Translates difficulty instances (queue A) and corner instances (queue B) that concern box
creation and selection into the box.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, make_admin_headers, make_customer_headers,
    create_box_payload, create_box_item_payload,
    setup_base, setup_cancelled_subscription, setup_scheduled_run_box,
    setup_open_box_no_run, setup_allergen_box, setup_run5_box_selected5, setup_run5_box_open,
    seed_run, seed_box, set_clock,
    CUTOFF_AT, DELIVERY_DATE,
)

ADMIN = make_admin_headers()


def test_box_computed_cutoff_and_first_box_flag(api):
    """PRD §2.6: "take the box's `delivery_date`, subtract the zone's `order_lead_days` whole
    days to obtain the cutoff calendar date, and place the cutoff at that date at the zone's
    `cutoff_time_utc` wall-clock time-of-day, interpreted in UTC."
    PRD §3.4: "The box is marked `is_first_box` true exactly when no other box of the same
    customer has an earlier `created_at`".
    PRD §3.4: "A newly created box normally opens with fulfillment `OPEN` and billing
    `UNCHARGED`."

    Design: Corner/entities/box_computed_cutoff_and_first_box_flag
    """
    ctx = setup_base(api)
    resp = api.create_box(ctx["sub_id"], create_box_payload(DELIVERY_DATE),
                          make_customer_headers(ctx["cust_id"]))
    data = validate_success(resp, 201)
    assert data["cutoff_at"].startswith("2026-03-12T18:00:00"), (
        f"expected cutoff_at at 2026-03-12T18:00:00Z, got {data['cutoff_at']!r}"
    )
    assert data["is_first_box"] is True
    assert data["fulfillment_status"] == "OPEN"
    assert data["billing_status"] == "UNCHARGED"


def test_box_create_on_cancelled_subscription_rejected(api):
    """PRD §3.4: "Generation is refused with `ERR_SUBSCRIPTION_NOT_ACTIVE` when the subscription
    is not `ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/box_create_requires_subscription_active
    """
    ctx = setup_cancelled_subscription(api)
    resp = api.create_box(ctx["sub_id"], create_box_payload(DELIVERY_DATE),
                          make_customer_headers(ctx["cust_id"]))
    validate_error(resp, ApiErrorId.ERR_SUBSCRIPTION_NOT_ACTIVE.value)


def test_box_create_on_active_subscription_succeeds(api):
    """PRD §3.4: "Generation is refused with `ERR_SUBSCRIPTION_NOT_ACTIVE` when the subscription
    is not `ACTIVE`." (Complement: an ACTIVE subscription admits box generation, opening OPEN.)

    Design: Difficulty/cross_entity_state_dependency/box_create_requires_subscription_active
    """
    ctx = setup_base(api)
    resp = api.create_box(ctx["sub_id"], create_box_payload(DELIVERY_DATE),
                          make_customer_headers(ctx["cust_id"]))
    data = validate_success(resp, 201)
    assert data["fulfillment_status"] == "OPEN"


def test_duplicate_box_delivery_date_returns_duplicate(api):
    """PRD §3.4: "a subscription may have only one box per `delivery_date` — a repeat date is
    refused with `ERR_DUPLICATE`."

    Design: Corner/validations/duplicate_box_delivery_date_returns_duplicate
    """
    ctx = setup_base(api)
    headers = make_customer_headers(ctx["cust_id"])
    validate_success(api.create_box(ctx["sub_id"], create_box_payload(DELIVERY_DATE), headers), 201)
    resp = api.create_box(ctx["sub_id"], create_box_payload(DELIVERY_DATE), headers)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE.value)


def test_select_when_only_run_is_scheduled_returns_sold_out(api):
    """PRD §3.4: "the system resolves an `AVAILABLE` production run for the pair of this
    `meal_id` and the box's `delivery_date` whose `par_remaining` is at least the requested
    `quantity`". "If no `AVAILABLE` run for that meal and date has enough remaining servings,
    the selection is refused with `ERR_MEAL_SOLD_OUT`."

    Design: Difficulty/cross_entity_state_dependency/box_item_select_requires_run_available
    """
    ctx = setup_scheduled_run_box(api)
    resp = api.create_box_item(ctx["box_id"], create_box_item_payload(ctx["m1_id"], 1),
                               make_customer_headers(ctx["cust_id"]))
    validate_error(resp, ApiErrorId.ERR_MEAL_SOLD_OUT.value)


def test_select_when_run_available_succeeds(api):
    """PRD §3.4: "the system resolves an `AVAILABLE` production run for the pair of this
    `meal_id` and the box's `delivery_date` whose `par_remaining` is at least the requested
    `quantity`, records that run as the item's `reserved_run_id`, and raises the run's
    `par_reserved` by `quantity`." "A successful line is created in `SELECTED` status".

    Design: Difficulty/cross_entity_state_dependency/box_item_select_requires_run_available
    """
    ctx = setup_base(api)
    seed_run(api, ctx["m1_id"], open_run=True, par_total=100)
    box = seed_box(api, ctx["sub_id"], ctx["cust_id"])
    resp = api.create_box_item(box["id"], create_box_item_payload(ctx["m1_id"], 1),
                               make_customer_headers(ctx["cust_id"]))
    data = validate_success(resp, 201)
    assert data["status"] == "SELECTED"


def test_add_item_after_cutoff_returns_cutoff_passed(api):
    """PRD §3.4: "Selection is only permitted while the logical clock is strictly before the
    box's `cutoff_at`; at or after cutoff the attempt is refused with `ERR_CUTOFF_PASSED`."

    Design: Corner/validations/add_item_after_cutoff_returns_cutoff_passed
    """
    ctx = setup_base(api)
    seed_run(api, ctx["m1_id"], open_run=True, par_total=100)
    box = seed_box(api, ctx["sub_id"], ctx["cust_id"])
    set_clock(api, "2026-03-13T00:00:00Z")
    resp = api.create_box_item(box["id"], create_box_item_payload(ctx["m1_id"], 1),
                               make_customer_headers(ctx["cust_id"]))
    validate_error(resp, ApiErrorId.ERR_CUTOFF_PASSED.value)


def test_skip_exactly_at_cutoff_rejected(api):
    """PRD §2.6: "Cutoff is therefore inclusive on the lock side: locking a box is permitted
    once the clock is at or after `cutoff_at`, while any selection-affecting action at or after
    that instant is refused."
    PRD §3.5: "a skip attempted at or after cutoff is refused with `ERR_CUTOFF_PASSED`."

    Design: Difficulty/boundary_precision_check/cutoff_inclusive_boundary_on_skip_rejected
    """
    ctx = setup_open_box_no_run(api, clock_iso=CUTOFF_AT)
    resp = api.skip_box(ctx["box_id"], make_customer_headers(ctx["cust_id"]))
    validate_error(resp, ApiErrorId.ERR_CUTOFF_PASSED.value)


def test_skip_one_second_before_cutoff_succeeds(api):
    """PRD §3.5: "A `Customer` may **skip** a week's box while it is still `OPEN` and the
    logical clock is strictly before its `cutoff_at`". "Skipping moves fulfillment
    `OPEN → SKIPPED` and billing to `WAIVED`".

    Design: Difficulty/boundary_precision_check/cutoff_inclusive_boundary_on_skip_rejected
    """
    ctx = setup_open_box_no_run(api, clock_iso="2026-03-12T17:59:59Z")
    resp = api.skip_box(ctx["box_id"], make_customer_headers(ctx["cust_id"]))
    data = validate_success(resp, 200)
    assert data["fulfillment_status"] == "SKIPPED"
    assert data["billing_status"] == "WAIVED"


def test_allergen_conflict_wins_over_sold_out(api):
    """PRD §2.9: "(6) the allergen-safety check, yielding `ERR_ALLERGEN_CONFLICT`; (7) domain
    business constraints such as available par, kitchen-line buffer, and pause overlap, yielding
    `ERR_MEAL_SOLD_OUT`, `ERR_LINE_CONFLICT`, or `ERR_PAUSE_OVERLAP`". "A lower priority number
    wins on conflict, so a mid-flight state problem surfaces ahead of an allergen conflict, and
    both surface ahead of a sold-out condition."

    Design: Difficulty/priority_pair_validation_conflict/priority_safety_beats_constraint_on_select_rejected
    """
    ctx = setup_allergen_box(api, par_total=0)  # meal is BOTH an allergen conflict AND sold out
    resp = api.create_box_item(ctx["box_id"], create_box_item_payload(ctx["mp_id"], 1),
                               make_customer_headers(ctx["cust_id"]))
    validate_error(resp, ApiErrorId.ERR_ALLERGEN_CONFLICT.value)


def test_allergen_conflict_isolated(api):
    """PRD §3.4: "The selected meal's `allergens` must share no token with the owning customer's
    `allergen_exclusions`; any shared token blocks the selection with `ERR_ALLERGEN_CONFLICT`."

    Design: Difficulty/priority_pair_validation_conflict/priority_safety_beats_constraint_on_select_rejected
    """
    ctx = setup_allergen_box(api, par_total=5)  # servings available; only the allergen check can fail
    resp = api.create_box_item(ctx["box_id"], create_box_item_payload(ctx["mp_id"], 1),
                               make_customer_headers(ctx["cust_id"]))
    validate_error(resp, ApiErrorId.ERR_ALLERGEN_CONFLICT.value)


def test_select_when_par_exhausted_returns_sold_out(api):
    """PRD §3.4: "If no `AVAILABLE` run for that meal and date has enough remaining servings,
    the selection is refused with `ERR_MEAL_SOLD_OUT`."

    Design: Difficulty/boundary_precision_check/par_exhaustion_boundary_on_select_rejected
    """
    ctx = setup_run5_box_selected5(api)  # par_total 5 fully reserved -> par_remaining 0
    resp = api.create_box_item(ctx["box_id"], create_box_item_payload(ctx["m1_id"], 1),
                               make_customer_headers(ctx["cust_id"]))
    validate_error(resp, ApiErrorId.ERR_MEAL_SOLD_OUT.value)


def test_select_exact_last_servings_succeeds_and_sells_out(api):
    """PRD §3.4: "When the reservation drives the run's `par_remaining` to exactly zero, the run
    flips `AVAILABLE → SOLD_OUT`."
    PRD §2.8: "`par_remaining`, always equal to `par_total` minus `par_reserved` and never
    negative."

    Design: Difficulty/boundary_precision_check/par_exhaustion_boundary_on_select_rejected
    """
    ctx = setup_run5_box_open(api)  # par_total 5, box OPEN, no items yet
    resp = api.create_box_item(ctx["box_id"], create_box_item_payload(ctx["m1_id"], 5),
                               make_customer_headers(ctx["cust_id"]))
    item = validate_success(resp, 201)
    assert item["status"] == "SELECTED"
    run = validate_success(api.get_production_run(ctx["run_id"], ADMIN), 200)
    assert run["status"] == "SOLD_OUT"
    assert run["par_remaining"] == 0


def test_reverse_reach_boxes_by_subscription_id(api):
    """PRD §3.4: "Boxes are fetchable with all of their computed money fields, and the box list
    may be filtered by `subscription_id`."
    PRD §2.3: "`total_count` (the total number of matching resources before the page window is
    applied)".

    Design: Corner/endpoints/reverse_reach_boxes_by_subscription_id
    """
    ctx = setup_base(api)
    box = seed_box(api, ctx["sub_id"], ctx["cust_id"])
    resp = api.list_boxes(make_customer_headers(ctx["cust_id"]),
                          params={"subscription_id": ctx["sub_id"]})
    data, meta = validate_paginated(resp)
    assert len(data) == 1 and data[0]["id"] == box["id"]
    assert meta["total_count"] == 1
