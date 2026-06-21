"""Configuration entities, CRUD, listing, and referential errors.

Translates corner-design instances from sections entities / endpoints / errors.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    TEST_USERS,
    make_carrier_headers,
    make_shipper_headers,
    assert_carrier,
    assert_reefer_unit,
    fixtures as fx,
)

ADMIN = TEST_USERS["platform_admin_headers"]


def test_create_carrier_applies_compliance_defaults(api):
    """PRD §3.1: "fsma_registered`, a boolean recording whether the carrier holds an active FSMA Sanitary Transport registration and defaulting to false; `sanitary_training_current`, a boolean recording whether driver sanitary-transport training is current and defaulting to false; and `liability_cap_cents`, the maximum the carrier will pay out on any single spoilage claim, defaulting to 5,000,000 cents (fifty thousand dollars)."
    PRD §2.4: "The `version` is an integer that starts at 1 on creation and increments by exactly 1 on every mutation of the resource".

    Design: Corner/entities/create_carrier_returns_201_with_defaults_applied
    """
    resp = api.create_carrier({"legal_name": "Solo Carrier"}, make_carrier_headers("carrier-c1"))
    data = validate_success(resp, expected_status=201)
    assert_carrier(data)
    assert data["fsma_registered"] is False
    assert data["sanitary_training_current"] is False
    assert data["liability_cap_cents"] == 5000000
    assert data["version"] == 1


def test_get_nonexistent_shipment_returns_not_found(api):
    """PRD §2.5: "The request fails with `ERR_NOT_FOUND` (HTTP 404) at the first identifier in the path that does not resolve, before any deeper identifier or business rule is considered."

    Design: Corner/entities/get_nonexistent_shipment_returns_not_found
    """
    resp = api.get_shipment("11111111-1111-4111-8111-111111111111",
                            make_shipper_headers("shipper-c2"))
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_shipment_missing_cargo_class_rejected(api):
    """PRD §2.6: "General request well-formedness — required fields present, enum values valid, numeric fields within their declared ranges, and pagination parameters within bounds — is enforced as `ERR_INVALID_REQUEST` (HTTP 400)."
    PRD §3.2: "A shipper tenders a shipment by naming the `carrier_id` it is offered to and the `cargo_class`, which is one of `FOOD`, `PHARMA`, or `GENERAL`."

    Design: Corner/entities/create_shipment_missing_cargo_class_returns_invalid_request
    """
    carrier = fx.create_carrier(legal_name="Req Carrier", op_id="carrier-c3")[0]
    resp = api.create_shipment({"carrier_id": carrier["id"]}, make_shipper_headers("shipper-c3"))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_shipment_invalid_cargo_class_enum_rejected(api):
    """PRD §2.6: "General request well-formedness — required fields present, enum values valid, numeric fields within their declared ranges, and pagination parameters within bounds — is enforced as `ERR_INVALID_REQUEST` (HTTP 400)."
    PRD §3.2: "the `cargo_class`, which is one of `FOOD`, `PHARMA`, or `GENERAL`."

    Design: Corner/entities/create_shipment_invalid_cargo_class_enum_rejected
    """
    carrier = fx.create_carrier(legal_name="Enum Carrier", op_id="carrier-c4")[0]
    resp = api.create_shipment(
        {"carrier_id": carrier["id"], "cargo_class": "LIVESTOCK"},
        make_shipper_headers("shipper-c4"),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_shipper_user_id_stamped_from_header(api):
    """PRD §3.2: "On tender the server stamps the shipper's `X-User-ID` onto the shipment's `shipper_user_id`; this stored value, not any record id, is what later authorizes the shipper-only cancel and claim-withdraw actions."

    Design: Corner/entities/shipper_user_id_stamped_from_header_input_ignored
    """
    carrier = fx.create_carrier(legal_name="Stamp Carrier", op_id="carrier-c5")[0]
    resp = api.create_shipment(
        {"carrier_id": carrier["id"], "cargo_class": "GENERAL"},
        make_shipper_headers("shipper-c5"),
    )
    data = validate_success(resp, expected_status=201)
    assert data["shipper_user_id"] == "shipper-c5", \
        f"shipper_user_id must be stamped from X-User-ID, got {data['shipper_user_id']}"


def test_list_carriers_pagination_envelope(api):
    """PRD §2.3: "List responses populate four fields inside the response envelope's `meta` object: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/list_carriers_pagination_envelope
    """
    fx.create_carrier(legal_name="C-A", op_id="admin-c6")
    fx.create_carrier(legal_name="C-B", op_id="admin-c6")
    resp = api.list_carriers(ADMIN, params={"limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] >= 2
    assert meta["has_more"] is True, "limit 1 over >=2 carriers must report has_more true"
    assert meta["limit"] == 1
    assert len(data) == 1


def test_filtered_list_reefer_units_by_carrier_id(api):
    """PRD §4: "List reefer units (filter by `carrier_id`, `status`)".
    PRD §2.3: "Unless a specific endpoint states otherwise, every list endpoint returns its resources sorted by creation timestamp (`created_at`) in ascending order."

    Design: Corner/endpoints/filtered_list_reefer_units_by_carrier_id
    """
    carrier, ch = fx.create_carrier(legal_name="FList Carrier", op_id="carrier-c20")
    unit = fx.create_unit(ch, carrier["id"], asset_tag="RU-C20", compartment_count=1)
    resp = api.list_reefer_units(ch, params={"carrier_id": carrier["id"]})
    data, meta = validate_paginated(resp)
    returned_ids = {u["id"] for u in data}
    assert returned_ids == {unit["id"]}, \
        f"carrier_id filter must return exactly that carrier's units, got {returned_ids}"
    for u in data:
        assert u["carrier_id"] == carrier["id"]


def test_retire_available_unit_sets_retired(api):
    """PRD §3.1: "An `AVAILABLE` unit may be retired; retiring a unit moves it to `RETIRED` and frees its `asset_tag` for reuse."

    Design: Corner/endpoints/retire_available_unit_sets_retired
    """
    carrier, ch = fx.create_carrier(legal_name="Retire Carrier", op_id="carrier-c21")
    unit = fx.create_unit(ch, carrier["id"], asset_tag="RU-C21", compartment_count=1)
    resp = api.retire_reefer_unit(unit["id"], ch)
    data = validate_success(resp)
    assert_reefer_unit(data)
    assert data["status"] == "RETIRED"


def test_duplicate_asset_tag_same_carrier_rejected(api):
    """PRD §3.1: "The `asset_tag` must be unique among that carrier's units that are not retired; registering a unit whose tag collides with an existing non-retired unit of the same carrier is rejected with `ERR_DUPLICATE_ASSET_TAG`."

    Design: Corner/errors/duplicate_asset_tag_same_carrier_returns_error
    """
    carrier, ch = fx.create_carrier(legal_name="Tag Carrier", op_id="carrier-c22")
    fx.create_unit(ch, carrier["id"], asset_tag="RU-DUP", compartment_count=1)
    resp = api.create_reefer_unit(
        {"carrier_id": carrier["id"], "asset_tag": "RU-DUP", "compartment_count": 1,
         "last_sanitation_at": "2026-02-28T00:00:00Z"},
        ch,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_ASSET_TAG.value)


def test_create_shipment_bad_carrier_fk_returns_fk_not_found(api):
    """PRD §2.5: "When a create or accept request names a related resource by id — a `carrier_id`, a `reefer_unit_id`, a `temp_lane_id`, a `compartment_id`, or a `shipment_id` — and that id does not resolve to an existing resource of the correct type, the request is rejected with `ERR_FK_NOT_FOUND` (HTTP 422)."

    Design: Corner/errors/accept_with_bad_carrier_fk_returns_fk_not_found
    """
    resp = api.create_shipment(
        {"carrier_id": "22222222-2222-4222-8222-222222222222", "cargo_class": "FOOD"},
        make_shipper_headers("shipper-c23"),
    )
    validate_error(resp, ApiErrorId.ERR_FK_NOT_FOUND.value)
