"""Restricted-unit exposure: the two variants and the double-rounding rule."""

from test_helpers import (
    ADMIN_HEADERS,
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
AUGUST_DELIVERY = "2026-08-20T16:00:00Z"
SECOND_AUGUST_DELIVERY = "2026-08-20T17:00:00Z"
SEPTEMBER_DOORSTEP = "2026-09-02T16:00:00Z"

AUGUST_SCALE = 1.15
SEPTEMBER_SCALE = 1.30
NEW_YORK_CEILING = 6.97
VERMONT_CEILING = 6.96


def _three_alcohol_products(api):
    """The catalogue triple whose per-item unit figures are 1.50, 0.75 and 0.05."""
    return (
        fx.create_product(api, f.wine_product_payload()),
        fx.create_product(api, f.beer_product_payload()),
        fx.create_product(api, f.seltzer_product_payload()),
    )


def _cleared_purchaser(api, jurisdiction_id):
    """A purchaser holding an adult attestation and a `MATCH` pre-verification."""
    customer = fx.create_customer(api, jurisdiction_id)
    fx.attest_customer(api, customer["id"], f.ADULT_DOB)
    fx.add_identity_check(api, customer["id"])
    return fx.read_customer(api, customer["id"])


def _three_line_basket(api, order, wine, beer, seltzer):
    """Three of the 1.50 item, two of the 0.75 item and one of the 0.05 item."""
    return [
        fx.add_line(api, order, wine["id"], 3),
        fx.add_line(api, order, beer["id"], 2),
        fx.add_line(api, order, seltzer["id"], 1),
    ]


def _read_line(api, order_line_id):
    return validate_success(api.get_order_line(order_line_id, ADMIN_HEADERS))


def _two_epoch_world(api):
    """One jurisdiction carrying an August policy and a September successor."""
    fx.set_clock(api, CLOCK_AUGUST)
    jurisdiction = fx.create_jurisdiction(
        api, code="US-NY", name="New York", dry_status="WET", utc_offset_minutes=-240
    )
    august_policy = fx.create_policy(
        api,
        jurisdiction["id"],
        unit_scale_factor=AUGUST_SCALE,
        max_units_per_order=NEW_YORK_CEILING,
        effective_from="2026-08-01",
        effective_to="2026-08-31",
    )
    september_policy = fx.create_policy(
        api,
        jurisdiction["id"],
        unit_scale_factor=SEPTEMBER_SCALE,
        max_units_per_order=20.00,
        effective_from="2026-09-01",
        effective_to="2026-12-31",
    )
    wine, beer, seltzer = _three_alcohol_products(api)
    customer = _cleared_purchaser(api, jurisdiction["id"])
    partner = fx.create_partner(api, license_reference="NY-DEL-0001")
    courier = fx.create_courier(api, partner["id"])
    certification = fx.issue_certification(api, courier)
    order = fx.create_order(
        api, customer["id"], jurisdiction["id"], partner["id"], AUGUST_DELIVERY, 600
    )
    lines = _three_line_basket(api, order, wine, beer, seltzer)
    return {
        "jurisdiction": jurisdiction,
        "august_policy": august_policy,
        "september_policy": september_policy,
        "wine": wine,
        "beer": beer,
        "seltzer": seltzer,
        "customer": customer,
        "customer_headers": make_customer_headers(customer["id"]),
        "partner": partner,
        "courier": courier,
        "certification": certification,
        "order": order,
        "lines": lines,
    }


def _walk_to_september_doorstep(api, world, order):
    """Dispatch, then cross the epoch boundary and complete a handover."""
    fx.dispatch_order(api, order)
    fx.set_clock(api, CLOCK_SEPTEMBER)
    courier_id = world["courier"]["id"]
    attempt = fx.open_attempt(api, order, world["courier"], SEPTEMBER_DOORSTEP)
    verified = fx.record_id_check(api, attempt, courier_id, scanned_dob=f.ADULT_DOB)
    fx.add_capture(
        api, verified, courier_id, "SIGNATURE", f.SIGNATURE_HASH,
        captured_at="2026-09-02T16:05:00Z",
    )
    fx.add_capture(
        api, verified, courier_id, "PHOTO_ID", f.PHOTO_ID_HASH,
        captured_at="2026-09-02T16:06:00Z",
    )
    fx.add_capture(
        api, verified, courier_id, "PHOTO_HANDOFF", f.PHOTO_HANDOFF_HASH,
        captured_at="2026-09-02T16:07:00Z",
    )
    fx.record_handover(api, verified, courier_id)
    return fx.read_order(api, order["id"]), fx.read_attempt(api, verified["id"])


def test_01_provisional_exposure_uses_the_policy_of_the_promised_delivery_date(api):
    """PRD 3.3: "Provisional exposure is evaluated once per element of
    `restriction_types`, against the policy effective on the local date of the
    *promised* delivery instant, and using each line's frozen
    `units_per_item_snapshot` rather than the live catalogue figure."

    Design: Difficulty/dual_variant_calc/order_exposure_provisional_versus_final_policy_epoch
    """
    world = _two_epoch_world(api)

    submitted = validate_success(
        api.submit_order(world["order"]["id"], world["customer_headers"])
    )

    assert_units_equal(
        submitted["provisional_restricted_units"], 6.97, "provisional_restricted_units"
    )
    assert submitted["applied_policy_ids"] == [world["august_policy"]["id"]], (
        "the promised delivery instant falls on the local date 2026-08-20, inside the "
        "August effective period, so the August policy is the one applied; got "
        f"{submitted['applied_policy_ids']}"
    )
    assert submitted["compliance_state"] == "PREVERIFIED"
    assert submitted["fulfillment_state"] == "SUBMITTED"


def test_02_final_exposure_uses_the_policy_of_the_actual_doorstep_instant(api):
    """PRD 3.6: "Its evaluation instant is the attempt's `started_at`, so it
    selects the policy effective on the local date of the **actual** doorstep
    instant rather than the promised one; and it multiplies by the **live**
    `restricted_units_per_item` read from the product row rather than the line's
    frozen `units_per_item_snapshot`."

    Design: Difficulty/dual_variant_calc/order_exposure_provisional_versus_final_policy_epoch
    """
    world = _two_epoch_world(api)

    submitted = validate_success(
        api.submit_order(world["order"]["id"], world["customer_headers"])
    )
    assert_units_equal(
        submitted["provisional_restricted_units"], 6.97, "provisional_restricted_units"
    )

    delivered, attempt = _walk_to_september_doorstep(api, world, submitted)

    assert_units_equal(delivered["final_restricted_units"], 7.87, "final_restricted_units")
    assert attempt["state"] == "HANDED_OVER"
    assert delivered["fulfillment_state"] == "DELIVERED"
    assert delivered["compliance_state"] == "PREVERIFIED"


def test_03_the_final_variant_leaves_the_provisional_figure_and_policy_set_alone(api):
    """PRD 3.6: "When a later policy row for the same jurisdiction and class
    carries a different `unit_scale_factor`, the two variants return different
    numbers from byte-identical order data — an order whose provisional exposure
    was 6.97 under a scale factor of 1.15 records a final exposure of 7.87 if the
    doorstep instant falls under a policy whose scale factor is 1.30."

    Design: Difficulty/dual_variant_calc/order_exposure_provisional_versus_final_policy_epoch
    """
    world = _two_epoch_world(api)

    submitted = validate_success(
        api.submit_order(world["order"]["id"], world["customer_headers"])
    )
    provisional = float(submitted["provisional_restricted_units"])

    delivered, _ = _walk_to_september_doorstep(api, world, submitted)

    assert_units_equal(
        delivered["provisional_restricted_units"], 6.97, "provisional_restricted_units"
    )
    assert delivered["applied_policy_ids"] == [world["august_policy"]["id"]], (
        "the doorstep evaluation writes `final_restricted_units` and leaves the "
        "submit-time `applied_policy_ids` in place; got "
        f"{delivered['applied_policy_ids']}"
    )
    final = float(delivered["final_restricted_units"])
    assert_units_equal(round(final - provisional, 2), 0.90, "exposure divergence")


# ===========================================================================
# The rounding order itself, read through two ceilings one hundredth apart
# ===========================================================================
def _two_ceiling_world(api):
    """Two jurisdictions identical but for a per-order ceiling of 6.97 against 6.96."""
    fx.set_clock(api, CLOCK_AUGUST)
    new_york = fx.create_jurisdiction(
        api, code="US-NY", name="New York", dry_status="WET", utc_offset_minutes=-240
    )
    vermont = fx.create_jurisdiction(
        api, code="US-VT", name="Vermont", dry_status="WET", utc_offset_minutes=-240
    )
    ny_policy = fx.create_policy(
        api,
        new_york["id"],
        unit_scale_factor=AUGUST_SCALE,
        max_units_per_order=NEW_YORK_CEILING,
    )
    vt_policy = fx.create_policy(
        api,
        vermont["id"],
        unit_scale_factor=AUGUST_SCALE,
        max_units_per_order=VERMONT_CEILING,
    )
    wine, beer, seltzer = _three_alcohol_products(api)
    customer = _cleared_purchaser(api, new_york["id"])
    partner = fx.create_partner(api, license_reference="NY-DEL-0001")
    courier = fx.create_courier(api, partner["id"])
    fx.issue_certification(api, courier)

    ny_order = fx.create_order(
        api, customer["id"], new_york["id"], partner["id"], AUGUST_DELIVERY, 600
    )
    ny_lines = _three_line_basket(api, ny_order, wine, beer, seltzer)
    vt_order = fx.create_order(
        api, customer["id"], vermont["id"], partner["id"], SECOND_AUGUST_DELIVERY, 600
    )
    vt_lines = _three_line_basket(api, vt_order, wine, beer, seltzer)

    return {
        "new_york": new_york,
        "vermont": vermont,
        "ny_policy": ny_policy,
        "vt_policy": vt_policy,
        "customer": customer,
        "customer_headers": make_customer_headers(customer["id"]),
        "partner": partner,
        "courier": courier,
        "ny_order": ny_order,
        "ny_lines": ny_lines,
        "vt_order": vt_order,
        "vt_lines": vt_lines,
    }


def test_04_per_line_rounding_is_written_to_every_line_and_summed(api):
    """PRD 3.3: "Visiting the order's lines in `created_at` ascending order and skipping any
    line whose product does not carry the class under evaluation as well as any line whose
    `line_state` is not `INCLUDED`, the system multiplies the line's `quantity` by its
    `units_per_item_snapshot` and by the policy's `unit_scale_factor`, rounds that product
    half up to two decimal places, and writes it to the line's `line_restricted_units`; it
    then adds those rounded per-line values together and rounds the total half up to two
    decimal places again, exactly as 2.9 requires."

    Design: Difficulty/combinatorial_formula/exposure_per_line_rounding_order_decides_quota_verdict
    """
    world = _two_ceiling_world(api)

    submitted = validate_success(
        api.submit_order(world["ny_order"]["id"], world["customer_headers"])
    )

    assert_units_equal(
        submitted["provisional_restricted_units"], 6.97, "provisional_restricted_units"
    )
    wine_line, beer_line, seltzer_line = (
        _read_line(api, line["id"]) for line in world["ny_lines"]
    )
    assert_units_equal(wine_line["line_restricted_units"], 5.18, "wine line_restricted_units")
    assert_units_equal(beer_line["line_restricted_units"], 1.73, "beer line_restricted_units")
    assert_units_equal(
        seltzer_line["line_restricted_units"], 0.06, "seltzer line_restricted_units"
    )
    assert submitted["compliance_state"] == "PREVERIFIED"


def test_05_rounding_before_summing_pushes_the_total_past_the_tighter_ceiling(api):
    """PRD 2.9: "Restricted-unit exposure is carried to two decimal places and
    rounded half up, and the rounding is applied **twice** in a pinned order: once
    to each individual line's contribution, and once again to the sum of those
    already-rounded line values. Summing the unrounded per-line products and
    rounding only at the end is forbidden and produces a different figure, which
    matters because the result is compared against a policy ceiling."

    Design: Difficulty/combinatorial_formula/exposure_per_line_rounding_order_decides_quota_verdict
    """
    world = _two_ceiling_world(api)

    validate_success(api.submit_order(world["ny_order"]["id"], world["customer_headers"]))

    response = api.submit_order(world["vt_order"]["id"], world["customer_headers"])
    validate_error(response, ApiErrorId.ORDER_UNIT_LIMIT_EXCEEDED.value)

    rejected = fx.read_order(api, world["vt_order"]["id"])
    assert rejected["fulfillment_state"] == "CREATED"
    assert rejected["compliance_state"] == "DRAFT_UNVERIFIED"
    assert_units_equal(
        rejected["provisional_restricted_units"], 0.00, "provisional_restricted_units"
    )


def test_06_the_two_ceilings_one_hundredth_apart_split_an_identical_basket(api):
    """PRD 2.9: "To make the divergence concrete: lines of quantity 3, 2 and 1 whose
    per-item unit figures are 1.50, 0.75 and 0.05, under a jurisdiction scale factor of
    1.15, round per line to 5.18, 1.73 and 0.06 and sum to 6.97; rounding only the unrounded
    total 6.9575 would give 6.96 instead. A ceiling of 6.96 therefore rejects that order
    under the required arithmetic and would wrongly accept it under the forbidden
    arithmetic."

    Design: Difficulty/combinatorial_formula/exposure_per_line_rounding_order_decides_quota_verdict
    """
    world = _two_ceiling_world(api)

    accepted = validate_success(
        api.submit_order(world["ny_order"]["id"], world["customer_headers"])
    )
    refused = api.submit_order(world["vt_order"]["id"], world["customer_headers"])
    validate_error(refused, ApiErrorId.ORDER_UNIT_LIMIT_EXCEEDED.value)

    total = float(accepted["provisional_restricted_units"])
    assert total > VERMONT_CEILING, (
        "the double-rounded total 6.97 must exceed the Vermont ceiling 6.96, which is "
        f"exactly what a single trailing round would have hidden; got {total}"
    )
    assert total <= NEW_YORK_CEILING, (
        f"the same total must sit inside the New York ceiling {NEW_YORK_CEILING}; got {total}"
    )
    assert accepted["fulfillment_state"] == "SUBMITTED"
