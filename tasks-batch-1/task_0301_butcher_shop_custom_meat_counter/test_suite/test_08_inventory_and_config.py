"""Configuration and inventory CRUD corners: customer/cut-type creation and
validation, computed-field initialization, listing envelope, pricing-policy
activation, and the cut-type-mismatch / FK-not-found / invalid-request errors.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    is_valid_uuid,
    ensure_pricing_policy,
    create_cut_type,
    create_customer,
    receive_lot,
    place_and_confirm_order,
    create_pricing_policy_payload,
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
)

MGR = TEST_USERS["shift_manager_headers"]
CLERK = TEST_USERS["counter_clerk_headers"]
BUTCHER = TEST_USERS["butcher_headers"]


# ===========================================================================
# Corner: entities / create_customer_returns_201_with_defaults
# ===========================================================================
def test_create_customer_defaults(api):
    """PRD §3.1: "an optional `loyalty_tier` which is one of `STANDARD`,
    `PREFERRED`, or `WHOLESALE` and defaults to `STANDARD` when omitted. Every new
    customer starts with a `store_credit_cents` balance of 0".

    Design: Corner/entities/create_customer_returns_201_with_defaults
    """
    cust = validate_success(
        api.create_customer({"full_name": "New Customer", "phone": "555-1000"}, CLERK),
        expected_status=201,
    )
    assert cust["loyalty_tier"] == "STANDARD"
    assert cust["store_credit_cents"] == 0


# ===========================================================================
# Corner: entities / get_customer_not_found
# ===========================================================================
def test_get_customer_not_found(api):
    """PRD §2.5: "the system validates existence left to right and rejects the
    request with `ERR_NOT_FOUND` (HTTP 404) at the first identifier in the path
    that does not resolve to an existing resource."

    Design: Corner/entities/get_customer_not_found
    """
    resp = api.get_customer(NON_EXISTENT_UUID, MGR)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


# ===========================================================================
# Corner: entities / create_cut_type_missing_required_field
# ===========================================================================
def test_create_cut_type_missing_required_field(api):
    """PRD §3.1: "a `base_price_cents_per_kg` which is the list price per kilogram
    in cents before any tier discount or shrink and must be at least 1."
    PRD §2.10: "the generic request-shape check (`ERR_INVALID_REQUEST`, HTTP 400)
    for a missing required field".

    Omitting base_price_cents_per_kg -> ERR_INVALID_REQUEST.

    Design: Corner/entities/create_cut_type_missing_required_field
    """
    resp = api.create_cut_type({"code": "BAD", "species": "BEEF"}, MGR)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# ===========================================================================
# Corner: entities / create_cut_type_invalid_enum_species
# ===========================================================================
def test_create_cut_type_invalid_species_enum(api):
    """PRD §3.1: "a `species` which is one of `BEEF`, `PORK`, `LAMB`, or
    `POULTRY`".
    PRD §2.10: "the generic request-shape check (`ERR_INVALID_REQUEST`, HTTP 400)
    for ... an enum value outside its allowed set".

    species "FISH" -> ERR_INVALID_REQUEST.

    Design: Corner/entities/create_cut_type_invalid_enum_species
    """
    resp = api.create_cut_type(
        {"code": "FISHY", "species": "FISH", "base_price_cents_per_kg": 1000}, MGR
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# ===========================================================================
# Corner: entities / inventory_lot_computed_remaining_weight_initialized
# ===========================================================================
def test_inventory_lot_remaining_weight_initialized(api):
    """PRD §3.2: "On receipt the server initializes `remaining_weight_g` to
    `received_weight_g` and sets `lot_status` to `AVAILABLE`."

    Design: Corner/entities/inventory_lot_computed_remaining_weight_initialized
    """
    cut = create_cut_type(code="RIBEYE", species="BEEF", base_price_cents_per_kg=4000)
    lot = validate_success(
        api.create_inventory_lot({"cut_type_id": cut["id"], "received_weight_g": 3000}, BUTCHER),
        expected_status=201,
    )
    assert lot["remaining_weight_g"] == 3000
    assert lot["lot_status"] == "AVAILABLE"


# ===========================================================================
# Corner: entities / list_cut_types_pagination_envelope
# ===========================================================================
def test_list_cut_types_pagination_envelope(api):
    """PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` object of the envelope."
    PRD §2.3: "`limit` caps the number of items returned".

    Two cut types created, limit 1 -> total_count 2, has_more true, one item.

    Design: Corner/entities/list_cut_types_pagination_envelope
    """
    create_cut_type(code="RIBEYE", species="BEEF", base_price_cents_per_kg=4000)
    create_cut_type(code="BRISKET", species="BEEF", base_price_cents_per_kg=2500)
    resp = api.list_cut_types(CLERK, params={"limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


# ===========================================================================
# Corner: endpoints / pricing_policy_activation_deactivates_prior
# ===========================================================================
def test_pricing_policy_activation_deactivates_prior(api):
    """PRD §3.1: "Creating a new policy activates it: the server sets `is_active`
    to true on the new policy and sets `is_active` to false on whichever policy was
    previously active, so that exactly one policy is ever active."

    Design: Corner/endpoints/pricing_policy_activation_deactivates_prior
    """
    first = get_success_data(api.create_pricing_policy(create_pricing_policy_payload(), MGR))
    second = validate_success(
        api.create_pricing_policy(
            create_pricing_policy_payload(shrink_pct_whole_cut=0.05, shrink_pct_grind=0.12,
                                          bulk_threshold_g=6000),
            MGR,
        ),
        expected_status=201,
    )
    assert second["is_active"] is True
    first_after = get_success_data(api.get_pricing_policy(first["id"], MGR))
    assert first_after["is_active"] is False


# ===========================================================================
# Corner: errors / invalid_request_negative_weight
# ===========================================================================
def test_inventory_lot_zero_weight_invalid(api):
    """PRD §3.2: "a `received_weight_g` in grams (at least 1)".
    PRD §2.10: "the generic request-shape check (`ERR_INVALID_REQUEST`, HTTP 400)
    for ... a number outside its allowed range."

    received_weight_g 0 (constraint >= 1) -> ERR_INVALID_REQUEST.

    Design: Corner/errors/invalid_request_negative_weight
    """
    cut = create_cut_type(code="RIBEYE", species="BEEF", base_price_cents_per_kg=4000)
    resp = api.create_inventory_lot({"cut_type_id": cut["id"], "received_weight_g": 0}, BUTCHER)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# ===========================================================================
# Corner: errors / not_found_fk_referenced_cut_type
# ===========================================================================
def test_inventory_lot_unknown_cut_type_not_found(api):
    """PRD §2.5: "if a payload names a `cut_type_id` ... or any other reference
    that does not resolve, the request is rejected with `ERR_NOT_FOUND`."

    Design: Corner/errors/not_found_fk_referenced_cut_type
    """
    resp = api.create_inventory_lot(
        {"cut_type_id": NON_EXISTENT_UUID, "received_weight_g": 1000}, BUTCHER
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


# ===========================================================================
# Corner: validations / cut_type_mismatch_on_draw
# ===========================================================================
def test_draw_cut_type_mismatch(api):
    """PRD §3.5: "the lot's `cut_type_id` must equal the line's `cut_type_id`, or
    the draw is rejected with `ERR_CUT_TYPE_MISMATCH` (HTTP 422)".

    A RIBEYE line drawn from a BRISKET lot -> ERR_CUT_TYPE_MISMATCH.

    Design: Corner/validations/cut_type_mismatch_on_draw
    """
    ensure_pricing_policy()
    ribeye = create_cut_type(code="RIBEYE", species="BEEF", base_price_cents_per_kg=4000)
    brisket = create_cut_type(code="BRISKET", species="BEEF", base_price_cents_per_kg=2500)
    cust = create_customer(full_name="Moe Mismatch", phone="555-1007")
    order, line_ids = place_and_confirm_order(cust["id"], [(ribeye["id"], 1000)])
    lot = receive_lot(brisket["id"], received_weight_g=3000)
    resp = api.draw_line(
        line_ids[0],
        {"drawn_lot_id": lot["id"], "catch_weight_g": 1000,
         "expected_inventory_lot_version": lot["version"]},
        BUTCHER,
    )
    validate_error(resp, ApiErrorId.ERR_CUT_TYPE_MISMATCH.value)


# ===========================================================================
# Corner: validations / insufficient_lot_weight_on_draw
# ===========================================================================
def test_draw_insufficient_lot_weight(api):
    """PRD §3.5: "the lot's `remaining_weight_g` must be at least the supplied
    `catch_weight_g`, or the draw is rejected with `ERR_INSUFFICIENT_LOT_WEIGHT`
    (HTTP 409)".

    Drawing 2001g from an AVAILABLE 2000g lot -> ERR_INSUFFICIENT_LOT_WEIGHT.

    Design: Corner/validations/insufficient_lot_weight_on_draw
    """
    ensure_pricing_policy()
    cut = create_cut_type(code="RIBEYE", species="BEEF", base_price_cents_per_kg=4000)
    cust = create_customer(full_name="Iggy Insufficient", phone="555-1008")
    order, line_ids = place_and_confirm_order(cust["id"], [(cut["id"], 2000)])
    lot = receive_lot(cut["id"], received_weight_g=2000)
    resp = api.draw_line(
        line_ids[0],
        {"drawn_lot_id": lot["id"], "catch_weight_g": 2001,
         "expected_inventory_lot_version": lot["version"]},
        BUTCHER,
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_LOT_WEIGHT.value)
