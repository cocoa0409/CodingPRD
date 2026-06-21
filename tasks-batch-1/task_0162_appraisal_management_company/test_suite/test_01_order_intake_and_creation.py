"""Order intake, creation, field validation, and projected SLA.

Covers queue B (Corner) instances in the entities and calculations sections that
exercise order placement, system-minted fields, defaults, enum/required-field
validation, FK existence, and the projected turnaround SLA.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    TEST_USERS, factories, assert_order, assert_appraiser,
)

COORD = TEST_USERS["coordinator_headers"]


def _make_lender_and_property(api, state_code="CA"):
    lender = validate_success(
        api.create_lender(factories.create_lender_payload(name="L Intake", monthly_fee_budget_cents=1_000_000), COORD),
        201,
    )
    prop = validate_success(
        api.create_property(factories.create_property_payload(state_code=state_code), COORD),
        201,
    )
    return lender, prop


def test_place_order_returns_201_placed_with_projected_sla(api):
    """PRD §3.1: "On successful placement the order enters `PLACED`, its `placed_at` is
    stamped from the server clock, and its turnaround `sla_hours` is computed from the
    product type and rush flag (see §3.9)."
    PRD §3.9: "the base SLA is 120 hours for `URAR_1004`, 96 hours for `CONDO_1073`, and
    72 hours for `EXTERIOR_2055`; when the order's `rush` flag is set, the projected SLA
    is the base less the rush shortening of 48 hours, and otherwise it is the base unchanged."

    Design: Corner/entities/create_order_returns_201_with_computed_sla_and_provisional_feesplit
    """
    lender, prop = _make_lender_and_property(api)
    data = validate_success(
        api.create_order(
            factories.create_order_payload(lender["id"], prop["id"], order_fee_cents=50000, product_type="URAR_1004"),
            COORD,
        ),
        201,
    )
    assert_order(data)
    assert data["status"] == "PLACED", f"new order must be PLACED, got {data['status']}"
    assert data["sla_hours"] == 120, f"URAR_1004 no-rush SLA must be 120, got {data['sla_hours']}"


def test_get_order_unknown_id_returns_not_found(api):
    """PRD §2.9: "the server validates the referenced resources from left to right and
    rejects the request with `ERR_NOT_FOUND` (HTTP 404) on the first identifier in the
    path that does not correspond to an existing resource."

    Design: Corner/entities/order_not_found_returns_404
    """
    resp = api.get_order("00000000-0000-0000-0000-000000000000", COORD)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, 404)


def test_place_order_missing_fee_returns_invalid_request(api):
    """PRD §2.10: "**Field-shape validation** last — required fields present, enums in
    range, numeric constraints satisfied — else `ERR_INVALID_REQUEST`."
    PRD §3.1: "submits a payload naming the `lender_id`, the `property_id`, the
    `order_fee_cents` (the borrower-paid total the lender pays the AMC for this order,
    which must be strictly greater than zero), the `product_type`, and an optional
    `rush` flag (defaulting to false)."

    Design: Corner/entities/create_order_missing_required_field_returns_invalid_request
    """
    lender, prop = _make_lender_and_property(api)
    payload = {"lender_id": lender["id"], "property_id": prop["id"], "product_type": "URAR_1004"}
    resp = api.create_order(payload, COORD)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 422)


def test_place_order_rush_default_false_yields_full_sla(api):
    """PRD §3.1: "the `product_type`, and an optional `rush` flag (defaulting to false)."
    PRD §3.9: "when the order's `rush` flag is set, the projected SLA is the base less
    the rush shortening of 48 hours, and otherwise it is the base unchanged."

    Design: Corner/entities/order_rush_default_false_applied_when_omitted
    """
    lender, prop = _make_lender_and_property(api)
    data = validate_success(
        api.create_order(
            factories.create_order_payload(lender["id"], prop["id"], order_fee_cents=50000, product_type="URAR_1004"),
            COORD,
        ),
        201,
    )
    assert data["rush"] is False, f"omitted rush must default to false, got {data['rush']!r}"
    assert data["sla_hours"] == 120, f"non-rush URAR_1004 SLA must be 120, got {data['sla_hours']}"


def test_create_appraiser_system_fields_minted(api):
    """PRD §2.6: "`id`: a unique, server-minted identifier formatted as a UUID, with no
    type prefix."
    PRD §3.1: "An appraiser's `status` is one of `ACTIVE`, `SUSPENDED`, or `RETIRED`,
    defaulting to `ACTIVE` at creation."

    Design: Corner/entities/appraiser_id_system_minted_input_ignored
    """
    data = validate_success(
        api.create_appraiser(
            factories.create_appraiser_payload(full_name="Sys A", license_state="CA", base_fee_share_pct=0.50),
            COORD,
        ),
        201,
    )
    assert_appraiser(data)
    assert data["status"] == "ACTIVE", f"new appraiser must default to ACTIVE, got {data['status']}"


def test_place_order_invalid_product_type_rejected(api):
    """PRD §3.1: "The `product_type` is one of `URAR_1004`, `CONDO_1073`, or `EXTERIOR_2055`."
    PRD §2.10: "**Field-shape validation** last — required fields present, enums in
    range, numeric constraints satisfied — else `ERR_INVALID_REQUEST`."

    Design: Corner/entities/order_invalid_product_type_enum_rejected
    """
    lender, prop = _make_lender_and_property(api)
    payload = factories.create_order_payload(lender["id"], prop["id"], order_fee_cents=50000, product_type="FHA_9999")
    resp = api.create_order(payload, COORD)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 422)


def test_place_order_unknown_property_returns_not_found(api):
    """PRD §2.9: "the server validates the referenced resources from left to right and
    rejects the request with `ERR_NOT_FOUND` (HTTP 404) on the first identifier in the
    path that does not correspond to an existing resource."

    Design: Corner/entities/order_requires_existing_property_parent_reference
    """
    lender = validate_success(
        api.create_lender(factories.create_lender_payload(name="L FK", monthly_fee_budget_cents=1_000_000), COORD),
        201,
    )
    payload = factories.create_order_payload(
        lender["id"], "00000000-0000-0000-0000-000000000000", order_fee_cents=50000, product_type="URAR_1004",
    )
    resp = api.create_order(payload, COORD)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, 404)


def test_rush_order_shortens_projected_sla(api):
    """PRD §3.9: "the base SLA is 120 hours for `URAR_1004`, 96 hours for `CONDO_1073`,
    and 72 hours for `EXTERIOR_2055`; when the order's `rush` flag is set, the projected
    SLA is the base less the rush shortening of 48 hours, and otherwise it is the base
    unchanged."

    Design: Corner/calculations/sla_rush_shortens_turnaround_target
    """
    lender, prop = _make_lender_and_property(api)
    data = validate_success(
        api.create_order(
            factories.create_order_payload(
                lender["id"], prop["id"], order_fee_cents=50000, product_type="URAR_1004", rush=True,
            ),
            COORD,
        ),
        201,
    )
    assert data["sla_hours"] == 72, f"rush URAR_1004 SLA must be 120-48=72, got {data['sla_hours']}"
