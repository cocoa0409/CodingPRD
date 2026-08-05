"""Route commitment: the nine compliance conditions, their fixed order, and the
reservation they move through the pesticide ledger."""

import test_helpers as fx
from test_helpers import (
    ECOLOGIST,
    MANAGER,
    ApiErrorId,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_expired_licence_is_reported_before_the_stock_shortfall(api):
    """PRD §3.9: "The applicator must be fit, which means three things at once:
    `status` is `ACTIVE`, `license_expires_on` falls on or after the calendar date
    of `window_start` (a licence expiring on the day of the work is still valid),
    and `license_category` covers the product's `application_method` under the
    coverage hierarchy of §3.2. Any of the three failing yields
    `ERR_APPLICATOR_LICENSE_INVALID` (HTTP 422)."
    PRD §2.11: "And because inventory sufficiency is last (step 21), a commitment
    that is both short of stock and outside its applicator's licence category
    reports the licence problem, not the stock problem."

    Design: Corner/validations/corner_expired_license_outranks_insufficient_inventory
    """
    bundle = fx.setup_plan_scenario(
        applicator_overrides={
            "full_name": "Lapsed Larry", "license_no": "L-2002",
            "license_category": "LARVICIDE_ONLY", "license_expires_on": "2026-06-04",
        },
        product_overrides={"received_total_ml": 500.0},
        routes=[{"planned_acres": 10.0}],
    )

    response = api.transition_treatment_route(
        bundle["route"]["id"], {"action": "COMMIT"}, MANAGER
    )
    validate_error(response, ApiErrorId.ERR_APPLICATOR_LICENSE_INVALID.value, 422)

    assert fx.read_route(bundle["route"]["id"])["status"] == "PLANNED"
    fx.assert_index(
        fx.read_product(bundle["product"]["id"])["on_hand_ml"], 500.00, "on_hand_ml"
    )


def test_product_method_and_assessment_area_must_match_their_plan(api):
    """PRD §3.9: "The product's `application_method` must equal the plan's
    `treatment_type`; loading an adulticide onto a larvicide plan is
    `ERR_PRODUCT_METHOD_MISMATCH` (HTTP 422)."
    PRD §3.7: "The named assessment must belong to the same area as the plan; an
    assessment that resolves but points at a different area is refused with
    `ERR_AREA_MISMATCH`."

    Design: Corner/validations/corner_product_method_mismatch_and_area_mismatch_rejected
    """
    bundle = fx.setup_plan_scenario(
        product_overrides={
            "name": "Permanone 30-30", "epa_reg_no": "EPA-101",
            "active_ingredient": "PERMETHRIN", "application_method": "ADULTICIDE",
            "reentry_interval_hours": 12,
        },
    )
    other_area = fx.create_area(name="Southeast Zone", code="SE2", population=12000)

    mismatch = api.transition_treatment_route(
        bundle["route"]["id"], {"action": "COMMIT"}, MANAGER
    )
    validate_error(mismatch, ApiErrorId.ERR_PRODUCT_METHOD_MISMATCH.value, 422)

    cross_area = api.create_treatment_plan(
        {
            "service_area_id": other_area["id"],
            "trigger_assessment_id": bundle["assessment"]["id"],
            "treatment_type": "LARVICIDE",
        },
        ECOLOGIST,
    )
    validate_error(cross_area, ApiErrorId.ERR_AREA_MISMATCH.value, 422)

    assert fx.read_route(bundle["route"]["id"])["status"] == "PLANNED"
    fx.assert_index(
        fx.read_product(bundle["product"]["id"])["committed_ml"], 0.00, "committed_ml"
    )


def test_third_application_in_a_season_is_refused(api):
    """PRD §3.9: "The **seasonal cap**: an area may absorb at most 2 applications
    in a season, so commitment requires the area's `seasonal_application_count` to
    be below 2 and is otherwise refused with `ERR_SEASONAL_LIMIT_EXCEEDED` (HTTP
    409)."

    Design: Corner/validations/corner_seasonal_application_limit_blocks_third_commit
    """
    bundle = fx.setup_area_at_seasonal_cap()

    response = api.transition_treatment_route(
        bundle["third_route"]["id"], {"action": "COMMIT"}, MANAGER
    )
    validate_error(response, ApiErrorId.ERR_SEASONAL_LIMIT_EXCEEDED.value, 409)

    assert fx.read_area(bundle["area"]["id"])["seasonal_application_count"] == 2
    assert fx.read_route(bundle["third_route"]["id"])["status"] == "PLANNED"
    product = fx.read_product(bundle["product"]["id"])
    fx.assert_index(product["applied_ml"], 200.00, "applied_ml")
    fx.assert_index(product["committed_ml"], 0.00, "committed_ml")
    fx.assert_index(product["on_hand_ml"], 99800.00, "on_hand_ml")


def test_plan_total_sums_route_volumes_that_were_rounded_at_commit(api):
    """PRD §3.9: "The plan's `estimated_total_ml` is then recomputed as the sum of
    `estimated_volume_ml` across the routes of that plan whose status is
    `COMMITTED`, `EXECUTED`, or `VERIFIED` — a sum of values that were each already
    rounded at their own commit time, never a fresh recomputation from acreage."
    PRD §2.6: "A plan's `estimated_total_ml` is likewise the sum of route volumes
    that were *already* rounded at commit time, not a fresh recomputation from
    acreage."

    Design: Corner/calculations/corner_plan_estimated_total_sums_rounded_route_volumes
    """
    bundle = fx.setup_plan_scenario(
        applicator_overrides={"license_category": "LARVICIDE_ONLY"},
        product_overrides={
            "name": "Altosid XR", "epa_reg_no": "EPA-404",
            "active_ingredient": "METHOPRENE", "label_rate_ml_per_acre": 33.3,
            "cost_cents_per_liter": 9000, "received_total_ml": 1000.0,
        },
        routes=[
            {"planned_acres": 0.15, "window_start": "2026-06-05T09:00:00.000Z",
             "window_end": "2026-06-05T10:00:00.000Z"},
            {"planned_acres": 0.15, "window_start": "2026-06-05T11:00:00.000Z",
             "window_end": "2026-06-05T12:00:00.000Z"},
        ],
    )

    first = validate_success(
        api.transition_treatment_route(
            bundle["routes"][0]["id"], {"action": "COMMIT"}, MANAGER
        )
    )
    second = validate_success(
        api.transition_treatment_route(
            bundle["routes"][1]["id"], {"action": "COMMIT"}, MANAGER
        )
    )

    fx.assert_index(first["estimated_volume_ml"], 5.00, "estimated_volume_ml")
    fx.assert_index(second["estimated_volume_ml"], 5.00, "estimated_volume_ml")
    fx.assert_index(
        fx.read_plan(bundle["plan"]["id"])["estimated_total_ml"], 10.00,
        "estimated_total_ml",
    )
    product = fx.read_product(bundle["product"]["id"])
    fx.assert_index(product["committed_ml"], 10.00, "committed_ml")
    fx.assert_index(product["on_hand_ml"], 990.00, "on_hand_ml")


def test_route_listing_filters_by_applicator_product_and_plan(api):
    """PRD §3.9: "Routes are listable with optional narrowing by
    `treatment_plan_id`, by `applicator_id`, by `pesticide_product_id`, and by
    `status`, and each route is readable individually with both volume variants
    exposed."
    PRD §3.7: "The server derives `duration_minutes` as the whole number of minutes
    between `window_start` and `window_end`, which is therefore always at least 1,
    opens the route with `status` of `PLANNED`, and leaves `estimated_volume_ml` at
    `0.00` until commitment."

    Design: Corner/endpoints/corner_treatment_routes_filtered_by_applicator_and_product
    """
    fx.set_clock(fx.CLOCK_BASE)
    area = fx.create_area()
    tech_a = fx.create_applicator(license_category="LARVICIDE_ONLY")
    tech_b = fx.create_applicator(
        full_name="Ravi Shah", license_no="L-1002", license_category="LARVICIDE_ONLY"
    )
    assessment = fx.open_assessment(area["id"], "2026-06-01")
    product_one = fx.create_product()
    product_two = fx.create_product(
        name="Altosid XR", epa_reg_no="EPA-404", active_ingredient="METHOPRENE",
        label_rate_ml_per_acre=33.3, cost_cents_per_liter=9000, received_total_ml=1000.0,
    )
    plan = fx.create_plan(area["id"], assessment["id"], "LARVICIDE")
    route_one = fx.add_route(plan["id"], tech_a["id"], product_one["id"], route_code="R-1")
    route_two = fx.add_route(plan["id"], tech_b["id"], product_two["id"], route_code="R-2")

    by_applicator, applicator_meta = validate_paginated(
        api.list_treatment_routes(
            MANAGER, params={"applicator_id": tech_b["id"], "limit": 10, "offset": 0}
        )
    )
    assert applicator_meta["total_count"] == 1
    assert [row["id"] for row in by_applicator] == [route_two["id"]]

    by_product, product_meta = validate_paginated(
        api.list_treatment_routes(
            MANAGER, params={"pesticide_product_id": product_one["id"], "limit": 10, "offset": 0}
        )
    )
    assert product_meta["total_count"] == 1
    assert [row["id"] for row in by_product] == [route_one["id"]]

    by_plan, plan_meta = validate_paginated(
        api.list_treatment_routes(
            MANAGER, params={"treatment_plan_id": plan["id"], "limit": 10, "offset": 0}
        )
    )
    assert plan_meta["total_count"] == 2
    assert {row["id"] for row in by_plan} == {route_one["id"], route_two["id"]}
    assert fx.read_route(route_one["id"])["status"] == "PLANNED"
    assert fx.read_route(route_two["id"])["duration_minutes"] == 60


def test_adulticide_commit_refused_while_area_posture_is_normal(api):
    """PRD §3.9: "The **posture gate**: when the plan's `treatment_type` is
    `ADULTICIDE` or `AERIAL`, the area's `risk_posture` must be `ELEVATED` or
    `EMERGENCY` at commit time. Adult spraying against a `NORMAL` posture is
    exactly the unjustified application this system exists to prevent, and it is
    refused with `ERR_POSTURE_TOO_LOW` (HTTP 409). Larvicide commitment is not
    posture-gated at all."

    Design: Difficulty/cross_entity_state_dependency/adulticide_commit_requires_elevated_area_posture
    """
    bundle = fx.setup_adulticide_plan_at_normal_posture()
    assert bundle["assessment"]["posture_at_confirm"] == "NORMAL"
    fx.assert_index(
        bundle["assessment"]["vector_index_confirmed"], 24.00, "vector_index_confirmed"
    )

    response = api.transition_treatment_route(
        bundle["route"]["id"], {"action": "COMMIT"}, MANAGER
    )
    validate_error(response, ApiErrorId.ERR_POSTURE_TOO_LOW.value, 409)

    assert fx.read_route(bundle["route"]["id"])["status"] == "PLANNED"
    assert fx.read_area(bundle["area"]["id"])["risk_posture"] == "NORMAL"


def test_adulticide_commit_succeeds_once_a_positive_override_raises_posture(api):
    """PRD §3.6: "Separately, ask whether a positive detection is recent: does
    there exist any test pool in `RESULT_POSITIVE` whose parent collection belongs
    to a trap site of this area and whose `result_recorded_at` is at or after the
    logical clock minus 14 days? If such a pool exists, the override reading is
    `ELEVATED`; if not, it is `NORMAL`."
    PRD §3.9: "On success it is written to the route's `estimated_volume_ml`, and
    the reservation moves through the ledger: `on_hand_ml` decreases by that
    amount, `committed_ml` increases by the same amount, and the product's
    `version` advances by 1."

    Design: Difficulty/cross_entity_state_dependency/adulticide_commit_requires_elevated_area_posture
    """
    bundle = fx.setup_adulticide_plan_at_normal_posture()
    fx.positive_pool(bundle["collection"]["id"], 40, 29.5)

    area = fx.read_area(bundle["area"]["id"])
    assert area["risk_posture"] == "ELEVATED"
    assert area["posture_source"] == "POSITIVE_OVERRIDE"
    fx.assert_index(
        area["latest_confirmed_vector_index"], 24.00, "latest_confirmed_vector_index"
    )

    committed = validate_success(
        api.transition_treatment_route(bundle["route"]["id"], {"action": "COMMIT"}, MANAGER)
    )

    assert committed["status"] == "COMMITTED"
    fx.assert_index(committed["estimated_volume_ml"], 200.00, "estimated_volume_ml")
    fx.assert_index(
        fx.read_product(bundle["product"]["id"])["committed_ml"], 200.00, "committed_ml"
    )


def test_unapproved_plan_is_reported_before_the_stock_shortfall(api):
    """PRD §3.9: "The parent plan must be `APPROVED`. A plan still in draft, still
    gathering signatures, returned, already scheduled, or already running cannot
    take new commitments — `ERR_PLAN_NOT_APPROVED` (HTTP 409)."
    PRD §3.9: "A route advances `PLANNED → COMMITTED` only when every one of them
    holds, and they are evaluated in the fixed order below so that the caller
    always learns about the most fundamental problem first:"

    Design: Difficulty/priority_pair_validation_conflict/plan_not_approved_outranks_insufficient_inventory
    """
    fx.set_clock(fx.CLOCK_BASE)
    area = fx.create_area()
    tech = fx.create_applicator()
    assessment = fx.open_assessment(area["id"], "2026-06-01")
    product = fx.create_product(received_total_ml=500.0, reentry_interval_hours=4)
    plan = fx.create_plan(area["id"], assessment["id"], "LARVICIDE")
    route = fx.add_route(
        plan["id"], tech["id"], product["id"], planned_acres=10.0,
        window_start="2026-06-05T09:00:00.000Z", window_end="2026-06-05T12:00:00.000Z",
    )

    response = api.transition_treatment_route(route["id"], {"action": "COMMIT"}, MANAGER)
    validate_error(response, ApiErrorId.ERR_PLAN_NOT_APPROVED.value, 409)

    refreshed = fx.read_route(route["id"])
    assert refreshed["status"] == "PLANNED"
    fx.assert_index(refreshed["estimated_volume_ml"], 0.00, "estimated_volume_ml")
    stock = fx.read_product(product["id"])
    fx.assert_index(stock["on_hand_ml"], 500.00, "on_hand_ml")
    fx.assert_index(stock["committed_ml"], 0.00, "committed_ml")


def test_stock_shortfall_surfaces_only_after_the_plan_is_approved(api):
    """PRD §3.9: "**Inventory sufficiency**, evaluated last: the product's
    `on_hand_ml` must be at least the route's estimated volume, or the commitment
    is refused with `ERR_INSUFFICIENT_INVENTORY` (HTTP 409)."
    PRD §3.9: "The **estimated volume** that condition 9 tests is computed from the
    plan on paper: multiply the route's `planned_acres` by the product's
    `label_rate_ml_per_acre` and round half up to two decimal places."

    Design: Difficulty/priority_pair_validation_conflict/plan_not_approved_outranks_insufficient_inventory
    """
    bundle = fx.setup_plan_scenario(
        product_overrides={"received_total_ml": 500.0, "reentry_interval_hours": 4},
        routes=[{"planned_acres": 10.0, "window_start": "2026-06-05T09:00:00.000Z",
                 "window_end": "2026-06-05T12:00:00.000Z"}],
    )

    response = api.transition_treatment_route(
        bundle["route"]["id"], {"action": "COMMIT"}, MANAGER
    )
    validate_error(response, ApiErrorId.ERR_INSUFFICIENT_INVENTORY.value, 409)

    assert fx.read_route(bundle["route"]["id"])["status"] == "PLANNED"
    stock = fx.read_product(bundle["product"]["id"])
    fx.assert_index(stock["on_hand_ml"], 500.00, "on_hand_ml")
    fx.assert_index(stock["committed_ml"], 0.00, "committed_ml")


def test_missing_apiary_clearance_is_reported_before_the_route_clash(api):
    """PRD §3.9: "**Protected-site clearance**: again only when `treatment_type` is
    `ADULTICIDE` or `AERIAL`, for every protected site of type `APIARY` or
    `ORGANIC_FARM` that this route encroaches upon by the geometric test of §3.8, a
    notice of this plan addressed to that site must already exist in `SENT` or
    `ACKNOWLEDGED`."
    PRD §3.8: "The comparison is inclusive: a separation exactly equal to the
    combined radius counts as encroachment."

    Design: Difficulty/priority_pair_validation_conflict/sensitive_site_clearance_outranks_applicator_route_conflict
    """
    bundle = fx.setup_clearance_vs_occupancy_scenario()
    candidate = bundle["routes"][1]

    response = api.transition_treatment_route(candidate["id"], {"action": "COMMIT"}, MANAGER)
    validate_error(response, ApiErrorId.ERR_SENSITIVE_SITE_NOT_CLEARED.value, 409)

    assert fx.read_route(candidate["id"])["status"] == "PLANNED"
    assert fx.read_route(bundle["routes"][0]["id"])["status"] == "COMMITTED"
    assert bundle["site"]["buffer_meters"] == 1600
    product = fx.read_product(bundle["product"]["id"])
    fx.assert_index(product["committed_ml"], 1000.00, "committed_ml")
    fx.assert_index(product["on_hand_ml"], 99000.00, "on_hand_ml")


def test_route_clash_surfaces_once_the_apiary_has_been_notified(api):
    """PRD §3.9: "Note the deliberate asymmetry with scheduling: clearance at
    commit time accepts a merely `SENT` notice, because the operator has been told
    and the work has not yet been dated, whereas scheduling demands `ACKNOWLEDGED`
    or `EXPIRED`."
    PRD §3.9: "Consider every other route with the same `applicator_id` whose
    status is `COMMITTED`, `EXECUTED`, or `VERIFIED`; the commitment is refused
    when this route's `window_start` falls strictly before that route's
    `window_end` plus 45 minutes **and** that route's `window_start` falls strictly
    before this route's `window_end` plus 45 minutes."

    Design: Difficulty/priority_pair_validation_conflict/sensitive_site_clearance_outranks_applicator_route_conflict
    """
    bundle = fx.setup_clearance_vs_occupancy_scenario()
    candidate = bundle["routes"][1]
    notice = fx.issue_notification(bundle["plan"]["id"], bundle["site"]["id"])
    fx.notification_action(notice["id"], "SEND")

    response = api.transition_treatment_route(candidate["id"], {"action": "COMMIT"}, MANAGER)
    validate_error(response, ApiErrorId.ERR_APPLICATOR_ROUTE_CONFLICT.value, 409)

    assert fx.read_route(candidate["id"])["status"] == "PLANNED"
    assert fx.read_notification(notice["id"])["status"] == "SENT"


def test_route_starting_one_minute_inside_the_turnaround_buffer_conflicts(api):
    """PRD §3.9: "**Applicator occupancy**, evaluated with a trailing turnaround
    buffer of 45 minutes for equipment cleanout and travel. A route's effective
    occupancy runs from its `window_start` up to but not including its `window_end`
    plus 45 minutes."
    PRD §3.9: "A genuine overlap is `ERR_APPLICATOR_ROUTE_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/applicator_occupancy_halfopen_with_forty_five_minute_trailing_buffer
    """
    bundle = fx.setup_occupancy_boundary_scenario()
    inside_buffer = bundle["routes"][1]

    response = api.transition_treatment_route(
        inside_buffer["id"], {"action": "COMMIT"}, MANAGER
    )
    validate_error(response, ApiErrorId.ERR_APPLICATOR_ROUTE_CONFLICT.value, 409)

    assert fx.read_route(inside_buffer["id"])["status"] == "PLANNED"
    assert fx.read_route(bundle["routes"][0]["id"])["status"] == "COMMITTED"
    assert fx.read_applicator(bundle["applicator"]["id"])["assigned_route_count"] == 1


def test_route_starting_exactly_at_the_buffer_boundary_is_accepted(api):
    """PRD §3.9: "Because both comparisons are strict, occupancies that merely
    touch at the buffer boundary do not conflict — a route starting exactly 45
    minutes after another ends is accepted."
    PRD §3.9: "The applicator's `assigned_route_count` increases by 1."

    Design: Difficulty/resource_temporal_overlap/applicator_occupancy_halfopen_with_forty_five_minute_trailing_buffer
    """
    bundle = fx.setup_occupancy_boundary_scenario()
    at_boundary = bundle["routes"][2]

    committed = validate_success(
        api.transition_treatment_route(at_boundary["id"], {"action": "COMMIT"}, MANAGER)
    )

    assert committed["status"] == "COMMITTED"
    assert fx.read_applicator(bundle["applicator"]["id"])["assigned_route_count"] == 2
    product = fx.read_product(bundle["product"]["id"])
    fx.assert_index(product["committed_ml"], 200.00, "committed_ml")
    fx.assert_index(product["on_hand_ml"], 99800.00, "on_hand_ml")
    fx.assert_index(
        fx.read_plan(bundle["plan"]["id"])["estimated_total_ml"], 200.00,
        "estimated_total_ml",
    )


def test_reentry_quarantine_boundary_instant_is_a_violation(api):
    """PRD §3.9: "The commitment is refused when this route's `window_start` falls
    at or before that earlier route's `window_end` plus that re-entry interval. The
    boundary is a violation: a start exactly at the end-of-quarantine instant is
    rejected, and only a start strictly after it is allowed."
    PRD §3.9: "The **re-entry interval**, evaluated per active ingredient across
    the whole service area rather than per route or per plan."

    Design: Difficulty/resource_temporal_overlap/area_reentry_interval_closed_boundary_per_active_ingredient
    """
    bundle = fx.setup_reentry_boundary_scenario()

    response = api.transition_treatment_route(
        bundle["boundary_route"]["id"], {"action": "COMMIT"}, MANAGER
    )
    validate_error(response, ApiErrorId.ERR_REENTRY_INTERVAL_VIOLATION.value, 409)

    assert fx.read_route(bundle["boundary_route"]["id"])["status"] == "PLANNED"
    assert fx.read_route(bundle["route"]["id"])["status"] == "VERIFIED"
    assert fx.read_area(bundle["area"]["id"])["seasonal_application_count"] == 1


def test_reentry_quarantine_allows_a_start_one_minute_later(api):
    """PRD §3.9: "Take the re-entry interval declared on the product this route
    will apply, and consider every *other* route in the same service area whose
    status is `EXECUTED` or `VERIFIED` and whose product shares this route's
    `active_ingredient`."
    PRD §3.9: "Routes still `PLANNED`, `COMMITTED`, `VOIDED`, or `RELEASED` never
    create a quarantine, because nothing was actually laid down."

    Design: Difficulty/resource_temporal_overlap/area_reentry_interval_closed_boundary_per_active_ingredient
    """
    bundle = fx.setup_reentry_boundary_scenario()

    committed = validate_success(
        api.transition_treatment_route(
            bundle["clear_route"]["id"], {"action": "COMMIT"}, MANAGER
        )
    )

    assert committed["status"] == "COMMITTED"
    product = fx.read_product(bundle["product"]["id"])
    fx.assert_inventory_partition(product)
    fx.assert_index(product["applied_ml"], 100.00, "applied_ml")
    fx.assert_index(product["committed_ml"], 100.00, "committed_ml")
    fx.assert_index(product["on_hand_ml"], 99800.00, "on_hand_ml")


def test_commitment_moves_millilitres_from_on_hand_into_committed(api):
    """PRD §2.9: "`on_hand_ml` plus `committed_ml` plus `applied_ml` always equals
    `received_total_ml`."
    PRD §2.9: "Committing a route moves its estimated volume out of `on_hand_ml`
    and into `committed_ml`."

    Design: Difficulty/compensating_invariant/pesticide_millilitre_partition_unchanged_by_commit_then_release
    """
    bundle = fx.setup_plan_scenario(
        applicator_overrides={"license_category": "LARVICIDE_ONLY"},
        product_overrides={"reentry_interval_hours": 4},
        routes=[{"window_start": "2026-06-05T09:00:00.000Z",
                 "window_end": "2026-06-05T12:00:00.000Z"}],
    )
    before = fx.read_product(bundle["product"]["id"])
    fx.assert_index(before["on_hand_ml"], 100000.00, "on_hand_ml")

    validate_success(
        api.transition_treatment_route(bundle["route"]["id"], {"action": "COMMIT"}, MANAGER)
    )

    during = fx.read_product(bundle["product"]["id"])
    fx.assert_index(during["on_hand_ml"], 99900.00, "on_hand_ml")
    fx.assert_index(during["committed_ml"], 100.00, "committed_ml")
    fx.assert_index(during["applied_ml"], 0.00, "applied_ml")
    fx.assert_inventory_partition(during)


def test_release_after_commitment_restores_every_ledger_field(api):
    """PRD §2.9: "Because each movement is exactly compensating, commitment
    followed by release leaves all four fields exactly as they were, and execution
    followed by a void does the same."
    PRD §3.9: "Releasing from `COMMITTED` advances `COMMITTED → RELEASED` and gives
    the reservation back: the route's `estimated_volume_ml` leaves `committed_ml`
    and returns to `on_hand_ml`, the product's `version` advances, the applicator's
    `assigned_route_count` decreases by 1, and the plan's `estimated_total_ml` is
    recomputed."

    Design: Difficulty/compensating_invariant/pesticide_millilitre_partition_unchanged_by_commit_then_release
    """
    bundle = fx.setup_committed_route(
        applicator_overrides={"license_category": "LARVICIDE_ONLY"},
        product_overrides={"reentry_interval_hours": 4},
        routes=[{"window_start": "2026-06-05T09:00:00.000Z",
                 "window_end": "2026-06-05T12:00:00.000Z"}],
    )

    released = validate_success(
        api.transition_treatment_route(bundle["route"]["id"], {"action": "RELEASE"}, MANAGER)
    )

    assert released["status"] == "RELEASED"
    product = fx.read_product(bundle["product"]["id"])
    fx.assert_index(product["on_hand_ml"], 100000.00, "on_hand_ml")
    fx.assert_index(product["committed_ml"], 0.00, "committed_ml")
    fx.assert_index(product["applied_ml"], 0.00, "applied_ml")
    fx.assert_index(product["received_total_ml"], 100000.00, "received_total_ml")
    fx.assert_inventory_partition(product)
    fx.assert_index(
        fx.read_plan(bundle["plan"]["id"])["estimated_total_ml"], 0.00,
        "estimated_total_ml",
    )
    assert fx.read_applicator(bundle["applicator"]["id"])["assigned_route_count"] == 0
    assert fx.read_area(bundle["area"]["id"])["seasonal_application_count"] == 0
