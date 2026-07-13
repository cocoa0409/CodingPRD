"""Reference-data creation, permit drafting defaults/system fields, not-found
resolution, pagination, and immediate consistency.

Every test translates exactly one corner-design instance (queue B).
"""
from test_helpers import (
    TEST_USERS, make_carrier_headers, NON_EXISTENT_UUID,
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
    create_carrier_payload, create_permit_payload, create_structure_payload,
    create_travel_restriction_payload, create_route_segment_payload,
    escrow_deposit_payload,
    new_carrier, new_structure,
)

ADMIN = TEST_USERS["dot_admin_headers"]
OFFICER = TEST_USERS["permit_officer_headers"]


def test_create_carrier_success(api):
    """PRD §3.1: "A newly registered carrier starts with its lifetime deposit
    total, escrow balance, active-bond total, and unpaid-fee balance all at zero
    and its `compliance_standing` at `GOOD_STANDING`."
    PRD §2.4: "`version`, an integer that begins at 1 on creation."

    Design: Corner/entities/create_carrier_success
    """
    resp = api.create_carrier(create_carrier_payload(usdot_number="USDOT-C1"), ADMIN)
    data = validate_success(resp, 201)
    assert data["version"] == 1
    assert data["escrow_balance_cents"] == 0
    assert data["total_escrow_deposited_cents"] == 0
    assert data["active_bond_amount_cents"] == 0
    assert data["unpaid_fee_balance_cents"] == 0
    assert data["compliance_standing"] == "GOOD_STANDING"


def test_create_permit_defaults_overhang(api):
    """PRD §3.2: "the load geometry — `length_in`, `width_in`, `height_in`, and
    the optional `front_overhang_in` and `rear_overhang_in` (each defaulting to
    0)".

    Design: Corner/entities/create_permit_default_overhang_applied
    """
    carrier = new_carrier(api, usdot_number="USDOT-C2")
    payload = create_permit_payload(carrier["id"])
    payload.pop("front_overhang_in")
    payload.pop("rear_overhang_in")
    resp = api.create_permit(payload, make_carrier_headers(carrier["id"]))
    data = validate_success(resp, 201)
    assert data["front_overhang_in"] == 0
    assert data["rear_overhang_in"] == 0


def test_permit_system_fields_on_create(api):
    """PRD §3.2: "A `Carrier` initiates an application, which is created in the
    `DRAFT` state with `version` 1."

    Design: Corner/entities/permit_system_fields_on_create
    """
    carrier = new_carrier(api, usdot_number="USDOT-C3")
    resp = api.create_permit(create_permit_payload(carrier["id"]), make_carrier_headers(carrier["id"]))
    data = validate_success(resp, 201)
    assert data["status"] == "DRAFT"
    assert data["version"] == 1


def test_create_permit_missing_gross_weight(api):
    """PRD §2.10: "request well-formedness — required fields present, enum values
    valid, and unknown fields rejected (`ERR_INVALID_REQUEST`)".

    Design: Corner/entities/error_missing_required_field_on_create_permit
    """
    carrier = new_carrier(api, usdot_number="USDOT-C4")
    payload = create_permit_payload(carrier["id"])
    payload.pop("gross_weight_lbs")
    resp = api.create_permit(payload, make_carrier_headers(carrier["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)


def test_create_permit_invalid_permit_type_enum(api):
    """PRD §2.10: "request well-formedness — required fields present, enum values
    valid, and unknown fields rejected (`ERR_INVALID_REQUEST`)".

    Design: Corner/entities/error_invalid_enum_permit_type_on_create
    """
    carrier = new_carrier(api, usdot_number="USDOT-C5")
    payload = create_permit_payload(carrier["id"], permit_type="WEEKLY")
    resp = api.create_permit(payload, make_carrier_headers(carrier["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_travel_restriction_immutable_no_version(api):
    """PRD §2.4: "The one exception is `TravelRestriction`, which is immutable
    after creation: it carries only `id` and `created_at`, and has neither an
    `updated_at` nor a `version` field."

    Design: Corner/entities/travel_restriction_immutable_no_version
    """
    resp = api.create_travel_restriction(create_travel_restriction_payload(), ADMIN)
    data = validate_success(resp, 201)
    assert "version" not in data, "TravelRestriction must not carry a version field"
    assert "updated_at" not in data, "TravelRestriction must not carry an updated_at field"


def test_get_permit_not_found(api):
    """PRD §2.8: "rejects the request at the first identifier that does not
    resolve, returning the corresponding not-found error (`ERR_CARRIER_NOT_FOUND`,
    `ERR_PERMIT_NOT_FOUND`, ...".

    Design: Corner/entities/error_permit_not_found
    """
    resp = api.get_permit(NON_EXISTENT_UUID, OFFICER)
    validate_error(resp, ApiErrorId.ERR_PERMIT_NOT_FOUND, 404)


def test_create_permit_carrier_not_found(api):
    """PRD §2.8: "The system resolves them left to right — carrier, permit,
    structure, pilot car, ... — and rejects the request at the first identifier
    that does not resolve, returning the corresponding not-found error".

    Design: Corner/entities/error_carrier_not_found_on_create_permit
    """
    payload = create_permit_payload(NON_EXISTENT_UUID)
    resp = api.create_permit(payload, make_carrier_headers(NON_EXISTENT_UUID))
    validate_error(resp, ApiErrorId.ERR_CARRIER_NOT_FOUND)


def test_route_segment_structure_not_found(api):
    """PRD §2.8: "The system resolves them left to right — carrier, permit,
    structure, pilot car, ... — and rejects the request at the first identifier
    that does not resolve, returning the corresponding not-found error".

    Design: Corner/entities/error_structure_not_found_on_route_segment
    """
    carrier = new_carrier(api, usdot_number="USDOT-C6")
    permit_resp = api.create_permit(create_permit_payload(carrier["id"]), make_carrier_headers(carrier["id"]))
    permit = validate_success(permit_resp, 201)
    seg = create_route_segment_payload(
        structure_id=NON_EXISTENT_UUID,
        planned_cross_start_utc="2026-06-05T10:00:00Z",
        planned_cross_end_utc="2026-06-05T10:30:00Z",
    )
    resp = api.add_route_segment(permit["id"], seg, make_carrier_headers(carrier["id"]))
    validate_error(resp, ApiErrorId.ERR_STRUCTURE_NOT_FOUND)


def test_structure_computed_fields_fresh(api):
    """PRD §3.1: "On creation its `committed_tonnage` is 0 and its
    `available_tonnage` equals its rated capacity."
    PRD §3.1: "it is `OPEN` when the ratio of `available_tonnage` to
    `rated_capacity_tonnage` is at least 0.5".

    Design: Corner/entities/structure_computed_available_and_posture
    """
    structure = new_structure(api, rated_capacity_tonnage=200, dead_load_tonnage=40)
    resp = api.get_structure(structure["id"], ADMIN)
    data = validate_success(resp, 200)
    assert data["committed_tonnage"] == 0
    assert data["available_tonnage"] == 200
    assert data["posture"] == "OPEN"


def test_escrow_deposit_immediate(api):
    """PRD §3.1: "an administrator records an escrow deposit of `amount_cents`
    against a carrier, which increases both `escrow_balance_cents` and
    `total_escrow_deposited_cents` by that amount."

    Design: Corner/consistency_model/immediate_consistency_on_escrow_deposit
    """
    carrier = new_carrier(api, usdot_number="USDOT-M1")
    resp = api.deposit_escrow(carrier["id"], escrow_deposit_payload(500000), ADMIN)
    data = validate_success(resp, 200)
    assert data["escrow_balance_cents"] == 500000
    assert data["total_escrow_deposited_cents"] == 500000


def test_route_segment_invalid_milepost(api):
    """PRD §3.2: "Adding a segment whose `to_milepost` does not exceed its
    `from_milepost`, or whose crossing end does not follow its start, is rejected
    with `ERR_INVALID_DIMENSIONS`."

    Design: Corner/validations/error_invalid_dimensions_milepost
    """
    carrier = new_carrier(api, usdot_number="USDOT-V1")
    permit = validate_success(
        api.create_permit(create_permit_payload(carrier["id"]), make_carrier_headers(carrier["id"])), 201)
    seg = create_route_segment_payload(from_milepost=10, to_milepost=5)
    resp = api.add_route_segment(permit["id"], seg, make_carrier_headers(carrier["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_DIMENSIONS)


def test_create_permit_invalid_validity_window(api):
    """PRD §2.10: "Separately, `valid_from` must be strictly before `valid_until`,
    or the request is rejected with `ERR_VALIDITY_WINDOW_INVALID` (HTTP 422)."

    Design: Corner/validations/error_validity_window_invalid_on_create
    """
    carrier = new_carrier(api, usdot_number="USDOT-V2")
    payload = create_permit_payload(carrier["id"],
                                    valid_from="2026-06-30T00:00:00Z", valid_until="2026-06-01T00:00:00Z")
    resp = api.create_permit(payload, make_carrier_headers(carrier["id"]))
    validate_error(resp, ApiErrorId.ERR_VALIDITY_WINDOW_INVALID)


def test_permits_list_pagination(api):
    """PRD §2.3: "List-based responses include the following fields in the `meta`
    object of the response envelope: `limit`, `offset`, `total_count`, and
    `has_more`."

    Design: Corner/endpoints/permits_list_pagination_fields
    """
    carrier = new_carrier(api, usdot_number="USDOT-E1")
    for _ in range(2):
        api.create_permit(create_permit_payload(carrier["id"]), make_carrier_headers(carrier["id"]))
    resp = api.list_permits(OFFICER, params={"carrier_id": carrier["id"], "limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1
