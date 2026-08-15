"""Configuration entities, response envelope, and baseline auth checks."""
import pytest

from test_helpers import (
    api_client,
    ApiErrorId,
    TEST_USERS,
    NON_EXISTENT_UUID,
    validate_success,
    validate_error,
    validate_paginated,
    assert_common_fields,
    assert_species,
    assert_customer,
    assert_market_quote,
    create_vessel_payload,
    create_species_payload,
    create_market_quote_payload,
    create_dock_ticket_payload,
    create_vessel,
    create_catch_area,
    create_species,
    create_draft_quote,
)

OM = TEST_USERS["operations_manager_headers"]
DB = TEST_USERS["dock_buyer_headers"]
GI = TEST_USERS["grading_inspector_headers"]


def test_optional_defaults_and_initial_values_applied(api):
    """PRD §3.1: "an optional `discount_pct`, a fractional line discount such that 0.10 means ten percent, applied per line before rounding and defaulting to zero."
    PRD §3.1: "A new customer's `credit_exposure_cents` starts at zero; §3.6 defines how it moves."
    PRD §3.1: "and two compliance flags: `is_import`, true when the species requires import documentation before settlement, and `requires_cites`, true when CITES documentation is required to use the species as a substitute; both flags default to false."
    PRD §3.2: "A new quote starts in `DRAFT`, and the system records its author in `created_by_user_id` for the segregation-of-duties gate described below."
    PRD §3.2: "When no prior published quote exists for the species and grade, the guard is inert: the quote publishes directly and `volatility_pct` remains zero."
    PRD §2.4: "Every resource in this API — Vessel, Customer, CatchArea, Species, MarketQuote, DockTicket, LandingLine, GradeAssessment, InventoryLot, SalesOrder, OrderLine, Allocation, Shipment, ImportDocument, InspectionHold, and SubstitutionApproval alike — carries a standard set of system-managed fields"

    Design: Corner/entities/entity_creation_defaults_applied
    """
    species = create_species(species_code="COD", common_name="Atlantic Cod",
                             labeling_name="Cod", substitution_group="GADOID",
                             fresh_shelf_life_hours=72, frozen_shelf_life_days=30)
    assert_species(species)
    assert species["is_import"] is False, "is_import must default to false"
    assert species["requires_cites"] is False, "requires_cites must default to false"

    customer = validate_success(
        api_client.create_customer({"business_name": "Resto Group",
                                    "credit_limit_cents": 500000}, OM),
        expected_status=201)
    assert_customer(customer)
    assert customer["discount_pct"] == 0, "discount_pct must default to 0"
    assert customer["credit_exposure_cents"] == 0

    quote = validate_success(
        api_client.create_market_quote(
            create_market_quote_payload(species_id=species["id"], grade="GRADE_A",
                                        quote_date="2026-08-01",
                                        price_per_kg_cents=1200), OM),
        expected_status=201)
    assert_market_quote(quote)
    assert quote["status"] == "DRAFT"
    assert quote["volatility_pct"] == 0
    assert quote["created_by_user_id"] == "om_0"

    for entity in (species, customer, quote):
        assert_common_fields(entity)


def test_vessel_missing_registration_number_rejected(api):
    """PRD §2.8: "The request body is decoded first — required fields present, enum members in range, numeric bounds respected — else `ERR_INVALID_REQUEST` (400)."
    PRD §3.1: "A **Vessel** is registered with a `vessel_name`, a `registration_number`, and a `home_port`; the registration number is unique across vessels, and a duplicate is rejected with `ERR_DUPLICATE_UNIQUE_VALUE` (409)."

    Design: Corner/entities/entity_missing_required_field_returns_400
    """
    resp = api_client.create_vessel(
        {"vessel_name": "FV Aurora", "home_port": "Gloucester"}, OM)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_quote_grade_outside_enumeration_rejected(api):
    """PRD §2.8: "The request body is decoded first — required fields present, enum members in range, numeric bounds respected — else `ERR_INVALID_REQUEST` (400)."
    PRD §3.1: "Everywhere this API speaks of fish quality it uses the grade enumeration `GRADE_A`, `GRADE_B`, and `GRADE_C`."

    Design: Corner/entities/entity_invalid_enum_value_returns_400
    """
    species = create_species(species_code="COD")
    resp = api_client.create_market_quote(
        create_market_quote_payload(species_id=species["id"], grade="GRADE_X",
                                    quote_date="2026-08-01",
                                    price_per_kg_cents=1200), OM)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_get_unknown_vessel_returns_not_found(api):
    """PRD §2.8: "An unknown identifier yields the corresponding 404: `ERR_VESSEL_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`, `ERR_CATCH_AREA_NOT_FOUND`, `ERR_SPECIES_NOT_FOUND`, `ERR_QUOTE_NOT_FOUND`, `ERR_TICKET_NOT_FOUND`, `ERR_LINE_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`, `ERR_LOT_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_ORDER_LINE_NOT_FOUND`, `ERR_ALLOCATION_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`, `ERR_IMPORT_DOC_NOT_FOUND`, `ERR_HOLD_NOT_FOUND`, or `ERR_SUBSTITUTION_NOT_FOUND`."

    Design: Corner/entities/entity_get_unknown_id_returns_not_found
    """
    resp = api_client.get_vessel(NON_EXISTENT_UUID, OM)
    validate_error(resp, ApiErrorId.ERR_VESSEL_NOT_FOUND)


def test_market_quote_pagination_defaults_and_species_filter(api):
    """PRD §2.3: "The `limit` parameter specifies the maximum number of items to return; when omitted it defaults to 10, and it may not be lower than 1 or higher than 100. The `offset` parameter specifies the number of items to skip and defaults to 0."
    PRD §2.3: "List responses carry the pagination fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope."
    PRD §4: "List endpoints accept the pagination parameters of §2.3 plus filter query parameters named after the resource's own fields: `species_id`, `grade`, `quote_date`, and `status` on quotes"

    Design: Corner/entities/entity_pagination_defaults_and_filter_interaction
    """
    cod = create_species(species_code="COD")
    haddock = create_species(species_code="HADDOCK")
    for day in range(1, 8):
        create_draft_quote(cod["id"], quote_date=f"2026-08-0{day}",
                           price_per_kg_cents=1200)
    for day in range(1, 6):
        create_draft_quote(haddock["id"], quote_date=f"2026-08-0{day}",
                           price_per_kg_cents=999)

    page1, meta1 = validate_paginated(api_client.list_market_quotes(OM))
    assert len(page1) == 10, f"Default page must hold 10 items, got {len(page1)}"
    assert meta1["total_count"] == 12
    assert meta1["has_more"] is True
    assert meta1["limit"] == 10
    assert meta1["offset"] == 0

    page2, meta2 = validate_paginated(
        api_client.list_market_quotes(OM, params={"offset": 10}))
    assert len(page2) == 2, f"Second page must hold the remaining 2, got {len(page2)}"
    assert meta2["total_count"] == 12
    assert meta2["has_more"] is False

    filtered, meta3 = validate_paginated(
        api_client.list_market_quotes(OM, params={"species_id": haddock["id"]}))
    assert len(filtered) == 5
    assert meta3["total_count"] == 5
    assert meta3["has_more"] is False
    assert all(q["species_id"] == haddock["id"] for q in filtered)


def test_not_found_sweep_all_resources(api):
    """PRD §2.8: "An unknown identifier yields the corresponding 404: `ERR_VESSEL_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`, `ERR_CATCH_AREA_NOT_FOUND`, `ERR_SPECIES_NOT_FOUND`, `ERR_QUOTE_NOT_FOUND`, `ERR_TICKET_NOT_FOUND`, `ERR_LINE_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`, `ERR_LOT_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_ORDER_LINE_NOT_FOUND`, `ERR_ALLOCATION_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`, `ERR_IMPORT_DOC_NOT_FOUND`, `ERR_HOLD_NOT_FOUND`, or `ERR_SUBSTITUTION_NOT_FOUND`."

    Design: Corner/errors/err_not_found_sweep_all_resources
    """
    cases = [
        (api_client.get_customer, ApiErrorId.ERR_CUSTOMER_NOT_FOUND),
        (api_client.get_catch_area, ApiErrorId.ERR_CATCH_AREA_NOT_FOUND),
        (api_client.get_market_quote, ApiErrorId.ERR_QUOTE_NOT_FOUND),
        (api_client.get_dock_ticket, ApiErrorId.ERR_TICKET_NOT_FOUND),
        (api_client.get_landing_line, ApiErrorId.ERR_LINE_NOT_FOUND),
        (api_client.get_grade_assessment, ApiErrorId.ERR_ASSESSMENT_NOT_FOUND),
        (api_client.get_inventory_lot, ApiErrorId.ERR_LOT_NOT_FOUND),
        (api_client.get_sales_order, ApiErrorId.ERR_ORDER_NOT_FOUND),
        (api_client.get_order_line, ApiErrorId.ERR_ORDER_LINE_NOT_FOUND),
        (api_client.get_allocation, ApiErrorId.ERR_ALLOCATION_NOT_FOUND),
        (api_client.get_shipment, ApiErrorId.ERR_SHIPMENT_NOT_FOUND),
        (api_client.get_import_document, ApiErrorId.ERR_IMPORT_DOC_NOT_FOUND),
        (api_client.get_inspection_hold, ApiErrorId.ERR_HOLD_NOT_FOUND),
        (api_client.get_substitution_approval, ApiErrorId.ERR_SUBSTITUTION_NOT_FOUND),
    ]
    for getter, error_id in cases:
        resp = getter(NON_EXISTENT_UUID, OM)
        validate_error(resp, error_id)


def test_response_envelope_shapes(api):
    """PRD §2.2: "The `response_type` is either "object" for a single resource or "array" for a list of resources."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the specific error."
    PRD §2.2: "The `message` provides a human-readable explanation of what went wrong."
    PRD §2.2: "Pagination-related fields in `meta` (`limit`, `offset`, `total_count`, `has_more`) are included for list endpoints."

    Design: Corner/endpoints/ep_response_envelope_shape
    """
    species = create_species(species_code="COD")

    single = api_client.get_species(species["id"], OM)
    body = validate_success(single)
    assert single.json()["response_type"] == "object"
    assert isinstance(single.json()["meta"]["api_request_id"], str)
    assert isinstance(single.json()["meta"]["api_request_timestamp"], str)

    listed = api_client.list_market_quotes(OM, params={"species_id": species["id"]})
    _, meta = validate_paginated(listed)
    assert listed.json()["response_type"] == "array"
    for field in ("limit", "offset", "total_count", "has_more"):
        assert field in meta, f"List meta must carry {field}"

    failing = api_client.get_vessel(NON_EXISTENT_UUID, OM)
    err_body = failing.json()
    assert err_body["response_type"] == "error"
    assert err_body["data"]["error_id"] == ApiErrorId.ERR_VESSEL_NOT_FOUND
    assert isinstance(err_body["data"]["message"], str) and err_body["data"]["message"]


def test_duplicate_registration_number_rejected(api):
    """PRD §3.1: "A **Vessel** is registered with a `vessel_name`, a `registration_number`, and a `home_port`; the registration number is unique across vessels, and a duplicate is rejected with `ERR_DUPLICATE_UNIQUE_VALUE` (409)."

    Design: Corner/validations/val_duplicate_unique_value_rejected
    """
    create_vessel(vessel_name="FV Aurora", registration_number="REG-001",
                  home_port="Gloucester")
    resp = api_client.create_vessel(
        create_vessel_payload(vessel_name="FV Other", registration_number="REG-001",
                              home_port="New Bedford"), OM)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_UNIQUE_VALUE)


def test_missing_auth_headers_rejected(api):
    """PRD §2.1: "A request missing either header, or carrying a role the system does not declare, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."
    PRD §2.8: "Every request is validated in a fixed order, and the first failing check determines the error response."

    Design: Corner/validations/val_missing_auth_header_returns_400
    """
    # No X-User-ID / X-User-Role headers at all: auth (step 1) must precede the
    # not-found check (step 4) even though the id does not exist.
    resp = api_client.get_vessel(NON_EXISTENT_UUID, headers=None)
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


def test_grading_inspector_cannot_create_dock_ticket(api):
    """PRD §2.1: "A request whose role is valid but not permitted for the target operation is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
    PRD §4: "POST | `/dock-tickets` | Create a dock ticket (DRAFT); per-vessel half-open landing-window overlap check | DockBuyer, VesselAgent"

    Design: Corner/validations/val_wrong_role_returns_403
    """
    vessel = create_vessel()
    area = create_catch_area()
    resp = api_client.create_dock_ticket(
        create_dock_ticket_payload(vessel_id=vessel["id"], catch_area_id=area["id"]),
        GI)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    tickets, meta = validate_paginated(api_client.list_dock_tickets(OM))
    assert meta["total_count"] == 0, "No ticket may be created by a denied role"
