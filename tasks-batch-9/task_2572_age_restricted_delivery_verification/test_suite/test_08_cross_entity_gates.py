"""Gates an order cannot pass because of some *other* row's state."""

from test_helpers import (
    ApiErrorId,
    assert_score_equal,
    factories as f,
    fixtures as fx,
    make_courier_headers,
    make_customer_headers,
    make_partner_manager_headers,
    validate_error,
    validate_success,
)

CLOCK = "2026-08-20T12:00:00Z"
BAD_DELIVERY = "2026-08-20T16:00:00Z"
GOOD_DELIVERY = "2026-08-20T18:00:00Z"
DECOY_ONE = "2026-08-22T16:00:00Z"
DECOY_TWO = "2026-08-22T17:00:00Z"
MIXED_DOORSTEP = "2026-08-20T16:00:00Z"
ALCOHOL_DOORSTEP = "2026-08-20T17:00:00Z"


def _cleared_purchaser(api, jurisdiction_id):
    """A purchaser holding an adult attestation and a `MATCH` pre-verification."""
    customer = fx.create_customer(api, jurisdiction_id)
    fx.attest_customer(api, customer["id"], f.ADULT_DOB)
    fx.add_identity_check(api, customer["id"])
    return fx.read_customer(api, customer["id"])


def _one_suspended_partner_and_one_clean_one(api):
    """Two identical orders routed to two partners whose postures differ.

    The suspended partner earns its posture from two open `CRITICAL` cases, so its
    `license_risk_score` is still 0.00 and the case-count arm of the ladder is the
    only thing under test.
    """
    fx.set_clock(api, CLOCK)
    jurisdiction = fx.create_jurisdiction(
        api, code="US-NY", name="New York", dry_status="WET", utc_offset_minutes=-240
    )
    fx.create_policy(api, jurisdiction["id"], unit_scale_factor=1.15, max_units_per_order=6.97)
    wine = fx.create_product(api, f.wine_product_payload())
    customer = _cleared_purchaser(api, jurisdiction["id"])
    suspended_partner = fx.create_partner(
        api, legal_name="Empire Last Mile", license_reference="NY-DEL-0001"
    )
    clean_partner = fx.create_partner(
        api, legal_name="Harbor Courier Co", license_reference="NY-DEL-0002"
    )
    courier = fx.create_courier(api, suspended_partner["id"])

    for scheduled_at, scenario in (
        (DECOY_ONE, "UNDERAGE_PRESENTER"),
        (DECOY_TWO, "INTOXICATION_CUES"),
    ):
        decoy = fx.create_order(
            api, customer["id"], jurisdiction["id"], suspended_partner["id"], scheduled_at, 0
        )
        probe = fx.schedule_shopper_test(
            api, courier["id"], decoy["id"], scenario_type=scenario, scheduled_at=scheduled_at
        )
        fx.open_manual_case(
            api,
            suspended_partner["id"],
            secret_shopper_test_id=probe["id"],
            severity="CRITICAL",
            summary="Critical case awaiting investigation",
        )

    orders = {}
    for key, partner, scheduled_at in (
        ("bad", suspended_partner, BAD_DELIVERY),
        ("good", clean_partner, GOOD_DELIVERY),
    ):
        order = fx.create_order(
            api, customer["id"], jurisdiction["id"], partner["id"], scheduled_at, 600
        )
        fx.add_line(api, order, wine["id"], 3)
        orders[key] = fx.submit_order(api, order)

    return {
        "suspended_partner": suspended_partner,
        "clean_partner": clean_partner,
        "courier": courier,
        "customer_headers": make_customer_headers(customer["id"]),
        "order_bad": orders["bad"],
        "order_good": orders["good"],
    }


def test_01_two_open_critical_cases_suspend_the_partner_on_count_alone(api):
    """PRD 3.4: "The derivation is a two-step threshold ladder evaluated in this order: if
    the partner's `license_risk_score` is at or above 60.00, **or** its
    `open_critical_case_count` is at least 2, the posture becomes `SUSPENDED`; otherwise, if
    `license_risk_score` is at or above 25.00, **or** `open_case_count` is at least 3, the
    posture becomes `RESTRICTED`; otherwise it becomes `OPEN`."

    Design: Difficulty/cross_entity_state_dependency/order_dispatch_depends_on_delivery_partner_posture
    """
    world = _one_suspended_partner_and_one_clean_one(api)

    partner = fx.read_partner(api, world["suspended_partner"]["id"])
    assert partner["open_critical_case_count"] == 2
    assert_score_equal(partner["license_risk_score"], 0.00, "license_risk_score")
    assert partner["posture"] == "SUSPENDED", (
        "neither case has been decided, so the count arm of the ladder is the only one "
        f"that can be reached; got {partner['posture']}"
    )


def test_02_a_flawless_order_cannot_dispatch_through_a_suspended_partner(api):
    """PRD 3.4: "Both edges require the order's `compliance_state` to be one of
    `AUTO_CLEARED`, `PREVERIFIED` or `COMPLIANCE_CLEARED`, and both require the
    partner's `posture` to be something other than `SUSPENDED`, else
    `ERR_PARTNER_SUSPENDED`."

    Design: Difficulty/cross_entity_state_dependency/order_dispatch_depends_on_delivery_partner_posture
    """
    world = _one_suspended_partner_and_one_clean_one(api)
    ready = fx.read_order(api, world["order_bad"]["id"])
    assert ready["compliance_state"] == "PREVERIFIED"
    assert ready["fulfillment_state"] == "SUBMITTED"

    response = api.dispatch_order(
        world["order_bad"]["id"],
        make_partner_manager_headers(world["suspended_partner"]["id"]),
    )

    validate_error(response, ApiErrorId.PARTNER_SUSPENDED.value)
    refused = fx.read_order(api, world["order_bad"]["id"])
    assert refused["fulfillment_state"] == "SUBMITTED"
    assert refused["dispatched_at"] is None
    assert refused["compliance_state"] == "PREVERIFIED"


def test_03_the_identical_order_dispatches_through_the_clean_partner(api):
    """PRD 3.5: "`dispatch_eligible` is then true exactly when `certification_state`
    is `CERTIFIED` **and** the employing partner's `posture` is something other than
    `SUSPENDED`; in every other combination it is false."

    Design: Difficulty/cross_entity_state_dependency/order_dispatch_depends_on_delivery_partner_posture
    """
    world = _one_suspended_partner_and_one_clean_one(api)
    assert fx.read_partner(api, world["clean_partner"]["id"])["posture"] == "OPEN"

    validate_success(
        api.dispatch_order(
            world["order_good"]["id"],
            make_partner_manager_headers(world["clean_partner"]["id"]),
        )
    )

    assert fx.read_order(api, world["order_good"]["id"])["fulfillment_state"] == "DISPATCHED"
    courier = fx.read_courier(api, world["courier"]["id"])
    assert courier["dispatch_eligible"] is False, (
        "the courier's own employer is SUSPENDED, so the conjunction fails however good "
        "the courier's own record is"
    )


# ===========================================================================
# The door check reaches past the courier into the certification rows
# ===========================================================================
def _one_certified_class_and_a_two_class_basket(api):
    """A courier certified for alcohol alone, at two doors an hour apart.

    The first door carries an order needing two classes, the second the very same
    courier and document against an alcohol-only order.
    """
    fx.set_clock(api, CLOCK)
    jurisdiction = fx.create_jurisdiction(
        api, code="US-NY", name="New York", dry_status="WET", utc_offset_minutes=-240
    )
    fx.create_policy(
        api,
        jurisdiction["id"],
        restriction_type="ALCOHOL",
        unit_scale_factor=1.15,
        max_units_per_order=6.97,
    )
    fx.create_policy(
        api,
        jurisdiction["id"],
        restriction_type="TOBACCO_VAPE",
        unit_scale_factor=1.00,
        max_units_per_order=5.00,
        max_units_per_window=20.00,
    )
    wine = fx.create_product(api, f.wine_product_payload())
    cigar = fx.create_product(api, f.cigar_product_payload())
    customer = _cleared_purchaser(api, jurisdiction["id"])
    partner = fx.create_partner(api, license_reference="NY-DEL-0001")
    courier = fx.create_courier(api, partner["id"])
    fx.issue_certification(api, courier, restriction_type="ALCOHOL")

    mixed_order = fx.create_order(
        api, customer["id"], jurisdiction["id"], partner["id"], MIXED_DOORSTEP, 600
    )
    fx.add_line(api, mixed_order, wine["id"], 3)
    fx.add_line(api, mixed_order, cigar["id"], 1)
    mixed_order = fx.submit_order(api, mixed_order)
    fx.dispatch_order(api, mixed_order)
    mixed_attempt = fx.open_attempt(api, mixed_order, courier, MIXED_DOORSTEP)

    alcohol_order = fx.create_order(
        api, customer["id"], jurisdiction["id"], partner["id"], ALCOHOL_DOORSTEP, 600
    )
    fx.add_line(api, alcohol_order, wine["id"], 3)
    alcohol_order = fx.submit_order(api, alcohol_order)
    fx.dispatch_order(api, alcohol_order)
    alcohol_attempt = fx.open_attempt(api, alcohol_order, courier, ALCOHOL_DOORSTEP)

    return {
        "customer": customer,
        "courier": courier,
        "courier_headers": make_courier_headers(courier["id"]),
        "mixed_order": mixed_order,
        "mixed_attempt": mixed_attempt,
        "alcohol_order": alcohol_order,
        "alcohol_attempt": alcohol_attempt,
    }


def test_04_the_door_check_demands_a_certification_for_every_class_in_the_box(api):
    """PRD 3.6: "Before the document is examined, the courier's authority is
    confirmed once more: for every element of the order's `restriction_types` the
    courier must hold a certification for that class that is in `state` `ACTIVE` as at
    the attempt's `started_at`, else `ERR_CERTIFICATION_MISSING_FOR_RESTRICTION`."

    Design: Difficulty/cross_entity_state_dependency/door_id_check_depends_on_courier_certification_state_per_restriction_type
    """
    world = _one_certified_class_and_a_two_class_basket(api)
    mixed = fx.read_order(api, world["mixed_order"]["id"])
    assert mixed["restriction_types"] == ["ALCOHOL", "TOBACCO_VAPE"]
    assert fx.read_courier(api, world["courier"]["id"])["certification_state"] == "CERTIFIED"

    response = api.record_id_check(
        world["mixed_attempt"]["id"],
        f.id_check_payload(recipient_name=world["customer"]["full_name"]),
        world["courier_headers"],
    )

    validate_error(response, ApiErrorId.CERTIFICATION_MISSING_FOR_RESTRICTION.value)


def test_05_the_refused_door_check_writes_none_of_the_document_fields(api):
    """PRD 3.6: "A newly created attempt sits in `state` `INITIATED`, with
    `document_type`, `document_expires_on`, `scan_performed`, `scanned_dob`,
    `recipient_name`, `recipient_age_years`, `refusal_reason` and `abort_reason` all
    null, `observed_indicators` empty, and `id_check_compliant` false."

    Design: Difficulty/cross_entity_state_dependency/door_id_check_depends_on_courier_certification_state_per_restriction_type
    """
    world = _one_certified_class_and_a_two_class_basket(api)

    validate_error(
        api.record_id_check(
            world["mixed_attempt"]["id"],
            f.id_check_payload(recipient_name=world["customer"]["full_name"]),
            world["courier_headers"],
        ),
        ApiErrorId.CERTIFICATION_MISSING_FOR_RESTRICTION.value,
    )

    attempt = fx.read_attempt(api, world["mixed_attempt"]["id"])
    assert attempt["state"] == "INITIATED"
    assert attempt["document_type"] is None
    assert attempt["recipient_age_years"] is None
    assert attempt["id_check_compliant"] is False
    order = fx.read_order(api, world["mixed_order"]["id"])
    assert order["fulfillment_state"] == "OUT_FOR_DELIVERY"


def test_06_the_same_courier_and_document_clear_a_single_class_basket(api):
    """PRD 3.6: "The system computes `recipient_age_years` as the completed years
    between `scanned_dob` and `started_at` by calendar comparison, and writes it
    alongside the five document fields on both branches. If `recipient_age_years` is at
    least the largest `min_age_years` among the selected policies, the attempt takes
    `INITIATED → ID_VERIFIED` and `id_check_compliant` is set to true."

    Design: Difficulty/cross_entity_state_dependency/door_id_check_depends_on_courier_certification_state_per_restriction_type
    """
    world = _one_certified_class_and_a_two_class_basket(api)
    assert fx.read_order(api, world["alcohol_order"]["id"])["restriction_types"] == ["ALCOHOL"]

    validate_success(
        api.record_id_check(
            world["alcohol_attempt"]["id"],
            f.id_check_payload(recipient_name=world["customer"]["full_name"]),
            world["courier_headers"],
        )
    )

    attempt = fx.read_attempt(api, world["alcohol_attempt"]["id"])
    assert attempt["state"] == "ID_VERIFIED"
    assert attempt["recipient_age_years"] == 26
    assert attempt["id_check_compliant"] is True
