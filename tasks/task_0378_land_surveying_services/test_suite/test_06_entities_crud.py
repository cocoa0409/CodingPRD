"""Entity CRUD surface: survey-order creation with computed fees and system
fields, not-found, required-field and enum validation, list pagination envelope,
and the instrument asset-tag uniqueness conflict.

Corner queue: entities section.
"""
from test_helpers import (
    fixtures as fx,
    make_coordinator_headers,
    create_instrument_payload,
    create_survey_order_payload,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
    ABSENT_UUID,
    ApiErrorId,
)


# ════════════════════════════════════════════════════════════════════════
# Corner/entities/create_survey_order_returns_201_with_computed_fees
# ════════════════════════════════════════════════════════════════════════
def test_create_survey_order_computes_fees(api):
    """PRD §3.1: "On creation the order's `status` is `INTAKE`."
    PRD §3.7: "At order creation the system sets `base_fee_cents` from the survey
    type using the firm's tariff: a `BOUNDARY` survey is 120000 cents."
    PRD §3.7: "The order's `estimated_fee_cents` is then the base fee plus the field
    fee plus the rush surcharge."

    A BOUNDARY 3ac no-rush order returns 201 with status INTAKE, base_fee_cents
    120000, estimated_fee_cents 144000, and version 1.

    Design: Corner/entities/create_survey_order_returns_201_with_computed_fees
    """
    crew = fx.full_crew()
    cid = crew["coord"]["id"]
    order = validate_success(
        api.create_survey_order(
            create_survey_order_payload(survey_type="BOUNDARY", acreage=3, rush=False),
            make_coordinator_headers(cid)), 201)
    assert order["status"] == "INTAKE"
    assert order["base_fee_cents"] == 120000
    assert order["estimated_fee_cents"] == 144000
    assert order["version"] == 1


# ════════════════════════════════════════════════════════════════════════
# Corner/entities/get_survey_order_not_found_returns_404
# ════════════════════════════════════════════════════════════════════════
def test_get_survey_order_not_found(api):
    """PRD §2.5: "any request whose path or body names a resource that does not exist
    is rejected with `ERR_NOT_FOUND`, evaluated in the order the identifiers appear,
    so the first missing identifier is the one reported."

    GET /survey-orders/{id} with a non-existent UUID is rejected with ERR_NOT_FOUND.

    Design: Corner/entities/get_survey_order_not_found_returns_404
    """
    crew = fx.full_crew()
    cid = crew["coord"]["id"]
    resp = api.get_survey_order(ABSENT_UUID, make_coordinator_headers(cid))
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


# ════════════════════════════════════════════════════════════════════════
# Corner/entities/create_survey_order_missing_required_field_returns_invalid_request
# ════════════════════════════════════════════════════════════════════════
def test_create_survey_order_missing_acreage(api):
    """PRD §2.9: "Request-body well-formedness — all required fields present with
    valid types and valid enum values (`ERR_INVALID_REQUEST`) — is checked fourth,
    on every write endpoint."
    PRD §3.1: "the parcel's `acreage` (which must be greater than zero)."

    Omitting the required `acreage` field on POST /survey-orders is rejected with
    ERR_INVALID_REQUEST.

    Design: Corner/entities/create_survey_order_missing_required_field_returns_invalid_request
    """
    crew = fx.full_crew()
    cid = crew["coord"]["id"]
    payload = create_survey_order_payload(survey_type="BOUNDARY")
    payload.pop("acreage", None)
    resp = api.create_survey_order(payload, make_coordinator_headers(cid))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


# ════════════════════════════════════════════════════════════════════════
# Corner/entities/create_survey_order_invalid_enum_survey_type_returns_invalid_request
# ════════════════════════════════════════════════════════════════════════
def test_create_survey_order_invalid_survey_type(api):
    """PRD §2.9: "Request-body well-formedness — all required fields present with
    valid types and valid enum values (`ERR_INVALID_REQUEST`) — is checked fourth,
    on every write endpoint."
    PRD §3.1: "the `survey_type` (one of `BOUNDARY`, `TOPO`, `ALTA`, or
    `ELEVATION`)."

    POST /survey-orders with survey_type "MAGNETIC" (not an allowed enum value) is
    rejected with ERR_INVALID_REQUEST.

    Design: Corner/entities/create_survey_order_invalid_enum_survey_type_returns_invalid_request
    """
    crew = fx.full_crew()
    cid = crew["coord"]["id"]
    payload = create_survey_order_payload(survey_type="MAGNETIC", acreage=3)
    resp = api.create_survey_order(payload, make_coordinator_headers(cid))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


# ════════════════════════════════════════════════════════════════════════
# Corner/entities/system_fields_generated_input_ignored_on_create
# ════════════════════════════════════════════════════════════════════════
def test_system_fields_generated_on_create(api):
    """PRD §3.1: "On creation the order's `status` is `INTAKE`."
    PRD §2.4: "`version` (integer): a server-managed integer that begins at 1 on
    creation."
    PRD §2.4: "`id` (string): a unique, server-minted identifier formatted as a UUID.
    It carries no type prefix."

    A POST /survey-orders that includes a client-supplied status is created with the
    server-minted INTAKE status, version 1, and a bare UUID id.

    Design: Corner/entities/system_fields_generated_input_ignored_on_create
    """
    crew = fx.full_crew()
    cid = crew["coord"]["id"]
    payload = create_survey_order_payload(survey_type="BOUNDARY", acreage=3, rush=False)
    payload["status"] = "DELIVERED"  # client-supplied; must be ignored
    order = validate_success(api.create_survey_order(payload, make_coordinator_headers(cid)), 201)
    assert order["status"] == "INTAKE"
    assert order["version"] == 1
    assert is_valid_uuid(order["id"])


# ════════════════════════════════════════════════════════════════════════
# Corner/entities/list_survey_orders_paginated_envelope
# ════════════════════════════════════════════════════════════════════════
def test_list_survey_orders_paginated_envelope(api):
    """PRD §2.3: "Paginated list responses include the following fields in the `meta`
    object of the response envelope: `limit`, `offset`, `total_count`, and
    `has_more`."
    PRD §2.3: "The `limit` parameter specifies the maximum number of items to return;
    if not provided it defaults to 10."

    GET /survey-orders returns an array envelope with pagination meta; with two orders
    created, total_count >= 2 and has_more is false at the default limit of 10.

    Design: Corner/entities/list_survey_orders_paginated_envelope
    """
    crew = fx.full_crew()
    cid = crew["coord"]["id"]
    validate_success(
        api.create_survey_order(create_survey_order_payload(survey_type="BOUNDARY", acreage=3),
                                make_coordinator_headers(cid)), 201)
    validate_success(
        api.create_survey_order(create_survey_order_payload(survey_type="TOPO", acreage=5),
                                make_coordinator_headers(cid)), 201)

    data, meta = validate_paginated(api.list_survey_orders(make_coordinator_headers(cid),
                                                           params={"limit": 10, "offset": 0}))
    assert isinstance(data, list)
    assert meta["total_count"] >= 2
    assert meta["has_more"] is False


# ════════════════════════════════════════════════════════════════════════
# Corner/entities/duplicate_asset_tag_returns_conflict
# ════════════════════════════════════════════════════════════════════════
def test_duplicate_asset_tag_conflict(api):
    """PRD §2.7: "Every `Instrument` carries an `asset_tag` that must be unique across
    all instruments, compared as a case-sensitive exact match; an attempt to register
    an instrument whose `asset_tag` already exists is rejected with
    `ERR_DUPLICATE_ASSET_TAG`."

    A second instrument registered with an already-used asset_tag is rejected with
    ERR_DUPLICATE_ASSET_TAG.

    Design: Corner/entities/duplicate_asset_tag_returns_conflict
    """
    crew = fx.full_crew()
    cid = crew["coord"]["id"]
    validate_success(
        api.create_instrument(
            create_instrument_payload(asset_tag="TAG-DUP-1", instrument_type="TOTAL_STATION"),
            make_coordinator_headers(cid)), 201)
    resp = api.create_instrument(
        create_instrument_payload(asset_tag="TAG-DUP-1", instrument_type="GPS_RTK"),
        make_coordinator_headers(cid))
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_ASSET_TAG)
