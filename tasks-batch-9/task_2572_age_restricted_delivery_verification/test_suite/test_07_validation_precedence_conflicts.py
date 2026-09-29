"""Which objection surfaces first, and the minute on which the hours window shuts."""

from test_helpers import (
    ApiErrorId,
    assert_units_equal,
    factories as f,
    fixtures as fx,
    make_customer_headers,
    validate_error,
    validate_success,
)

CLOCK_AUGUST = "2026-08-20T12:00:00Z"
CLOCK_SEPTEMBER = "2026-09-02T12:00:00Z"
LATE_NIGHT = "2026-08-21T04:00:00Z"
WINDOW_CLOSES = "2026-08-21T02:00:00Z"
ONE_MINUTE_EARLIER = "2026-08-21T01:59:00Z"
AUGUST_AFTERNOON = "2026-08-20T16:00:00Z"
SEPTEMBER_AFTERNOON = "2026-09-02T16:00:00Z"


def _cleared_purchaser(api, jurisdiction_id, validity_days=90):
    """A purchaser holding an adult attestation and a `MATCH` pre-verification."""
    customer = fx.create_customer(api, jurisdiction_id)
    fx.attest_customer(api, customer["id"], f.ADULT_DOB)
    fx.add_identity_check(api, customer["id"], validity_days=validity_days)
    return fx.read_customer(api, customer["id"])


def _dry_and_wet_worlds(api):
    """One dry destination and one wet control, both shut at local minute 1200.

    The dry jurisdiction still publishes a `PERMITTED` policy so that policy
    resolution succeeds and the two objections under test are the only ones left.
    """
    fx.set_clock(api, CLOCK_AUGUST)
    kansas = fx.create_jurisdiction(
        api, code="US-KS", name="Kansas", dry_status="DRY", utc_offset_minutes=-300
    )
    new_york = fx.create_jurisdiction(
        api, code="US-NY", name="New York", dry_status="WET", utc_offset_minutes=-240
    )
    for jurisdiction_id in (kansas["id"], new_york["id"]):
        fx.create_policy(
            api,
            jurisdiction_id,
            delivery_window_start_minute=600,
            delivery_window_end_minute=1200,
            unit_scale_factor=1.15,
            max_units_per_order=6.97,
        )
    wine = fx.create_product(api, f.wine_product_payload())
    customer = _cleared_purchaser(api, new_york["id"])
    partner = fx.create_partner(api, license_reference="NY-DEL-0001")

    orders = {}
    for key, jurisdiction in (("kansas", kansas), ("new_york", new_york)):
        order = fx.create_order(
            api, customer["id"], jurisdiction["id"], partner["id"], LATE_NIGHT, 600
        )
        fx.add_line(api, order, wine["id"], 3)
        orders[key] = order
    return {
        "kansas": kansas,
        "new_york": new_york,
        "customer": customer,
        "customer_headers": make_customer_headers(customer["id"]),
        "order_kansas": orders["kansas"],
        "order_new_york": orders["new_york"],
    }


def test_01_the_dry_destination_objection_outranks_the_hours_objection(api):
    """PRD 2.7: "A submission into a dry jurisdiction outside the permitted delivery
    hours reports `ERR_DRY_JURISDICTION_PROHIBITED`, not `ERR_OUTSIDE_RESTRICTED_HOURS`,
    because jurisdiction permissibility sits at tier 12 and hours at tier 17."

    Design: Difficulty/priority_pair_validation_conflict/dry_jurisdiction_safety_beats_restricted_hours_temporal
    """
    world = _dry_and_wet_worlds(api)

    response = api.submit_order(world["order_kansas"]["id"], world["customer_headers"])

    validate_error(response, ApiErrorId.DRY_JURISDICTION_PROHIBITED.value)
    body = response.json()
    assert body["data"]["error_id"] != ApiErrorId.OUTSIDE_RESTRICTED_HOURS.value, (
        "the promised instant is local minute 1380 under an offset of -300 and therefore "
        "also outside the window [600, 1200), but only the safety objection may surface"
    )


def test_02_the_hours_objection_is_live_on_an_identical_wet_order(api):
    """PRD 3.3: "And the local delivery minute of `scheduled_delivery_at` must fall
    inside every selected policy's half-open window under the geometry of 2.10, else
    `ERR_OUTSIDE_RESTRICTED_HOURS`."

    Design: Difficulty/priority_pair_validation_conflict/dry_jurisdiction_safety_beats_restricted_hours_temporal
    """
    world = _dry_and_wet_worlds(api)

    response = api.submit_order(world["order_new_york"]["id"], world["customer_headers"])

    validate_error(response, ApiErrorId.OUTSIDE_RESTRICTED_HOURS.value)


def test_03_neither_refused_submission_advances_either_dimension(api):
    """PRD 3.3: "Third, the jurisdiction must permit the delivery. Per restriction
    class, and in this sub-order: a selected policy whose `permissibility` is
    `PROHIBITED` reports `ERR_DELIVERY_PROHIBITED_IN_JURISDICTION`; then an `ALCOHOL`
    class delivered into a jurisdiction whose `dry_status` is `DRY` reports
    `ERR_DRY_JURISDICTION_PROHIBITED`; then a jurisdiction whose `dry_status` is
    `DAMP` combined with a selected policy whose `permissibility` is anything other
    than `PERMIT_REQUIRED` reports `ERR_PERMIT_REQUIRED`."

    Design: Difficulty/priority_pair_validation_conflict/dry_jurisdiction_safety_beats_restricted_hours_temporal
    """
    world = _dry_and_wet_worlds(api)

    validate_error(
        api.submit_order(world["order_kansas"]["id"], world["customer_headers"]),
        ApiErrorId.DRY_JURISDICTION_PROHIBITED.value,
    )
    validate_error(
        api.submit_order(world["order_new_york"]["id"], world["customer_headers"]),
        ApiErrorId.OUTSIDE_RESTRICTED_HOURS.value,
    )

    kansas_order = fx.read_order(api, world["order_kansas"]["id"])
    assert kansas_order["fulfillment_state"] == "CREATED"
    assert kansas_order["compliance_state"] == "DRAFT_UNVERIFIED"
    new_york_order = fx.read_order(api, world["order_new_york"]["id"])
    assert new_york_order["fulfillment_state"] == "CREATED"


# ===========================================================================
# A state objection outranking a ceiling the order only breached later
# ===========================================================================
def _three_line_basket(api, order, wine, beer, seltzer):
    """Three of the 1.50 item, two of the 0.75 item and one of the 0.05 item."""
    fx.add_line(api, order, wine["id"], 3)
    fx.add_line(api, order, beer["id"], 2)
    fx.add_line(api, order, seltzer["id"], 1)


def _order_submitted_before_the_ceiling_tightened(api):
    """One order submitted under the 6.97 ceiling, one created after it fell to 5.00.

    Both baskets are identical and both expose 6.97 units, so the September order is
    a live demonstration that the ceiling rule really does fire.
    """
    fx.set_clock(api, CLOCK_AUGUST)
    jurisdiction = fx.create_jurisdiction(
        api, code="US-NY", name="New York", dry_status="WET", utc_offset_minutes=-240
    )
    fx.create_policy(
        api,
        jurisdiction["id"],
        unit_scale_factor=1.15,
        max_units_per_order=6.97,
        effective_from="2026-08-01",
        effective_to="2026-08-31",
    )
    fx.create_policy(
        api,
        jurisdiction["id"],
        unit_scale_factor=1.15,
        max_units_per_order=5.00,
        effective_from="2026-09-01",
        effective_to="2026-09-30",
    )
    wine = fx.create_product(api, f.wine_product_payload())
    beer = fx.create_product(api, f.beer_product_payload())
    seltzer = fx.create_product(api, f.seltzer_product_payload())
    customer = _cleared_purchaser(api, jurisdiction["id"], validity_days=180)
    partner = fx.create_partner(api, license_reference="NY-DEL-0001")

    august_order = fx.create_order(
        api, customer["id"], jurisdiction["id"], partner["id"], AUGUST_AFTERNOON, 600
    )
    _three_line_basket(api, august_order, wine, beer, seltzer)
    submitted = fx.submit_order(api, august_order)

    fx.set_clock(api, CLOCK_SEPTEMBER)
    september_order = fx.create_order(
        api, customer["id"], jurisdiction["id"], partner["id"], SEPTEMBER_AFTERNOON, 600
    )
    _three_line_basket(api, september_order, wine, beer, seltzer)

    return {
        "customer_headers": make_customer_headers(customer["id"]),
        "august_order": submitted,
        "september_order": september_order,
    }


def test_04_resubmitting_a_submitted_order_reports_the_state_objection(api):
    """PRD 2.7: "A submission on an order that is no longer in `CREATED` and that
    would also breach its per-order unit ceiling reports `ERR_INVALID_ORDER_STATE`,
    not `ERR_ORDER_UNIT_LIMIT_EXCEEDED`, because the state precondition sits at tier
    10 and quantity ceilings at tier 20."

    Design: Difficulty/priority_pair_validation_conflict/order_state_check_beats_quantity_ceiling_after_policy_epoch_change
    """
    world = _order_submitted_before_the_ceiling_tightened(api)

    response = api.submit_order(world["august_order"]["id"], world["customer_headers"])

    validate_error(response, ApiErrorId.INVALID_ORDER_STATE.value)
    body = response.json()
    assert body["data"]["error_id"] != ApiErrorId.ORDER_UNIT_LIMIT_EXCEEDED.value, (
        "the 6.97-unit basket now exceeds the September ceiling of 5.00, but the state "
        "precondition is reached first and is the only objection that may surface"
    )


def test_05_the_ceiling_objection_is_live_under_the_tightened_policy(api):
    """PRD 3.3: "The resulting figure per class is compared to that class's policy
    `max_units_per_order`, and exceeding it reports `ERR_ORDER_UNIT_LIMIT_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/order_state_check_beats_quantity_ceiling_after_policy_epoch_change
    """
    world = _order_submitted_before_the_ceiling_tightened(api)

    response = api.submit_order(world["september_order"]["id"], world["customer_headers"])

    validate_error(response, ApiErrorId.ORDER_UNIT_LIMIT_EXCEEDED.value)
    refused = fx.read_order(api, world["september_order"]["id"])
    assert refused["fulfillment_state"] == "CREATED"
    assert_units_equal(
        refused["provisional_restricted_units"], 0.00, "provisional_restricted_units"
    )


def test_06_the_refused_resubmission_leaves_the_august_order_untouched(api):
    """PRD 3.3: "Fifth and last come the quantity ceilings, computed from the order's
    **provisional** restricted-unit exposure — the provisional-at-submit variant of the
    exposure calculation, of which the handover-time figure of 3.6 is the second
    variant."

    Design: Difficulty/priority_pair_validation_conflict/order_state_check_beats_quantity_ceiling_after_policy_epoch_change
    """
    world = _order_submitted_before_the_ceiling_tightened(api)

    validate_error(
        api.submit_order(world["august_order"]["id"], world["customer_headers"]),
        ApiErrorId.INVALID_ORDER_STATE.value,
    )

    august = fx.read_order(api, world["august_order"]["id"])
    assert august["fulfillment_state"] == "SUBMITTED"
    assert august["compliance_state"] == "PREVERIFIED"
    assert_units_equal(
        august["provisional_restricted_units"], 6.97, "provisional_restricted_units"
    )


# ===========================================================================
# The minute the window shuts, read from both sides
# ===========================================================================
def _two_orders_a_minute_apart(api):
    """Two baskets promised one minute apart across the window's closing minute."""
    fx.set_clock(api, CLOCK_AUGUST)
    jurisdiction = fx.create_jurisdiction(
        api, code="US-NY", name="New York", dry_status="WET", utc_offset_minutes=-240
    )
    fx.create_policy(
        api,
        jurisdiction["id"],
        delivery_window_start_minute=600,
        delivery_window_end_minute=1320,
        unit_scale_factor=1.15,
        max_units_per_order=6.97,
    )
    wine = fx.create_product(api, f.wine_product_payload())
    customer = _cleared_purchaser(api, jurisdiction["id"])
    partner = fx.create_partner(api, license_reference="NY-DEL-0001")

    orders = {}
    for key, scheduled_at in (("edge", WINDOW_CLOSES), ("inside", ONE_MINUTE_EARLIER)):
        order = fx.create_order(
            api, customer["id"], jurisdiction["id"], partner["id"], scheduled_at, 600
        )
        fx.add_line(api, order, wine["id"], 3)
        orders[key] = order
    return {
        "customer_headers": make_customer_headers(customer["id"]),
        "order_edge": orders["edge"],
        "order_inside": orders["inside"],
    }


def test_07_the_closing_minute_itself_falls_outside_the_window(api):
    """PRD 2.10: "As a boundary illustration, under an offset of -240 minutes and a
    window running from minute 600 to minute 1320, an instant of
    `2026-08-21T01:59:00Z` is local minute 1319 and is inside the window, while
    `2026-08-21T02:00:00Z` is local minute 1320 and is outside it."

    Design: Difficulty/boundary_precision_check/restricted_hours_window_end_minute_is_exclusive_to_the_minute
    """
    world = _two_orders_a_minute_apart(api)

    response = api.submit_order(world["order_edge"]["id"], world["customer_headers"])

    validate_error(response, ApiErrorId.OUTSIDE_RESTRICTED_HOURS.value)
    refused = fx.read_order(api, world["order_edge"]["id"])
    assert refused["fulfillment_state"] == "CREATED"
    assert refused["compliance_state"] == "DRAFT_UNVERIFIED"


def test_08_one_minute_earlier_is_still_inside_the_window(api):
    """PRD 2.10: "A policy's permitted delivery window runs from
    `delivery_window_start_minute` to `delivery_window_end_minute` on that local
    minute axis and is **half-open**: the start minute is inside the window and the
    end minute is outside it."

    Design: Difficulty/boundary_precision_check/restricted_hours_window_end_minute_is_exclusive_to_the_minute
    """
    world = _two_orders_a_minute_apart(api)

    accepted = validate_success(
        api.submit_order(world["order_inside"]["id"], world["customer_headers"])
    )

    assert accepted["compliance_state"] == "PREVERIFIED"
    assert accepted["fulfillment_state"] == "SUBMITTED"
    assert_units_equal(
        accepted["provisional_restricted_units"], 5.18, "provisional_restricted_units"
    )


def test_09_the_same_basket_splits_on_a_single_minute_of_arithmetic(api):
    """PRD 2.10: "When the end minute is strictly greater than the start minute, an
    instant is inside the window when its local minute is at or after the start and
    strictly before the end."

    Design: Difficulty/boundary_precision_check/restricted_hours_window_end_minute_is_exclusive_to_the_minute
    """
    world = _two_orders_a_minute_apart(api)

    validate_error(
        api.submit_order(world["order_edge"]["id"], world["customer_headers"]),
        ApiErrorId.OUTSIDE_RESTRICTED_HOURS.value,
    )
    validate_success(
        api.submit_order(world["order_inside"]["id"], world["customer_headers"])
    )

    edge = fx.read_order(api, world["order_edge"]["id"])
    inside = fx.read_order(api, world["order_inside"]["id"])
    assert edge["fulfillment_state"] == "CREATED"
    assert inside["fulfillment_state"] == "SUBMITTED"
    assert_units_equal(
        edge["provisional_restricted_units"], 0.00, "provisional_restricted_units"
    )
