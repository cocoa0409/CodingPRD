"""Lab creation defaults, container intake, catalog listing, and response envelope."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_container,
    assert_lab,
    create_area,
    create_container_payload,
    create_draft_pickup,
    create_lab_payload,
    create_lab_with_pi,
    create_lab_with_trained_pi,
    create_tagged_container,
    is_valid_uuid,
    make_pi_headers,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


def test_lab_create_applies_system_defaults(api):
    """PRD §3.1: "The new lab begins life with `status` equal to `ACTIVE` and
    `posture` equal to `NORMAL`."
    PRD §2.7: "The lab's `permit_report_required` is true whenever at least one
    class is flagged." (a fresh lab has no containers, so no class is flagged)
    PRD §4: "Creating a new resource returns HTTP 201 with the created resource"

    Design: Corner/entities/lab_create_applies_defaults
    """
    res = api.create_lab(
        create_lab_payload(name="Lab A", department="Chemistry", building="Hall A", room="101"),
        ADMIN,
    )
    lab = validate_success(res, 201)
    assert_lab(lab)
    assert lab["status"] == "ACTIVE", f"expected ACTIVE, got {lab['status']}"
    assert lab["posture"] == "NORMAL", f"expected NORMAL posture, got {lab['posture']}"
    assert lab["permit_report_required"] is False
    assert isinstance(lab["version"], int)

    fetched = validate_success(api.get_lab(lab["id"], ADMIN), 200)
    assert_lab(fetched)
    assert fetched["id"] == lab["id"]


def test_container_system_fields_server_minted(api):
    """PRD §2.4: "The `id` is a server-minted UUID without any type prefix"
    PRD §3.2: "The container begins in state `IN_USE`."
    PRD §2.7: "the `quantity_unit` records the original unit as received — one of
    `GAL`, `L`, `KG`, or `LB`, defaulting to `GAL` — and is informational only."
    PRD §2.5: "At server startup the logical clock reads 2026-08-01T00:00:00Z." and
    "Timestamps the server stamps onto entities as a consequence of mutations — such
    as a container's `tagged_at`, an inspection's `completed_at`, or a training
    assignment's `completed_at` — record the logical now at the moment of the mutation."

    Design: Corner/entities/container_system_fields_server_minted
    """
    lab, pi = create_lab_with_pi(name="Lab B", department="Biology", building="Hall B", room="201")
    payload = create_container_payload(
        lab["id"], barcode="SF-1", chemical_name="Ethanol", hazard_class="FLAMMABLE",
        quantity_value=1.0,
    )
    payload.pop("quantity_unit")  # exercise the documented default
    res = api.create_container(payload, make_pi_headers(pi["id"]))
    container = validate_success(res, 201)
    assert_container(container)
    assert is_valid_uuid(container["id"]), "id must be a UUID without any type prefix"
    assert container["state"] == "IN_USE"
    assert container["quantity_unit"] == "GAL", "omitted quantity_unit must default to GAL"
    assert isinstance(container["version"], int)
    assert container["created_at"].startswith("2026-08-01T00:00:00"), (
        f"created_at must record the logical now (startup default), got {container['created_at']}"
    )


def test_container_get_not_found_returns_404(api):
    """PRD §2.8: "Existence of referenced resources, validated left to right: path
    identifiers first, then body foreign keys such as `lab_id`, `container_id`,
    `accumulation_area_id`, and `worker_id`, else `ERR_NOT_FOUND`."
    PRD §5: ERR_NOT_FOUND maps to HTTP 404.

    Design: Corner/entities/container_get_not_found_returns_404
    """
    res = api.get_container(NON_EXISTENT_UUID, ADMIN)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND)


def test_containers_list_pagination(api):
    """PRD §2.3: "All list endpoints accept the query parameters `limit` and `offset`."
    and "The `meta` object of a list response carries the pagination fields `limit`,
    `offset`, `total_count`, and `has_more`, where `total_count` is the total number
    of resources matching the applied filters and `has_more` indicates whether
    further pages exist beyond the returned window."

    Design: Corner/entities/containers_list_pagination
    """
    lab, pi = create_lab_with_pi(name="Lab C", room="102")
    headers = make_pi_headers(pi["id"])
    for barcode in ("PG-1", "PG-2", "PG-3"):
        res = api.create_container(
            create_container_payload(lab["id"], barcode=barcode, quantity_value=1.0), headers
        )
        validate_success(res, 201)

    page1_res = api.list_containers(ADMIN, params={"lab_id": lab["id"], "limit": 2, "offset": 0})
    data1, meta1 = validate_paginated(page1_res)
    assert page1_res.json()["response_type"] == "array"
    assert meta1["total_count"] == 3, f"total_count must be 3, got {meta1['total_count']}"
    assert meta1["has_more"] is True
    assert len(data1) == 2

    data2, meta2 = validate_paginated(
        api.list_containers(ADMIN, params={"lab_id": lab["id"], "limit": 2, "offset": 2})
    )
    assert len(data2) == 1, f"second page must hold the remaining 1 item, got {len(data2)}"
    assert meta2["has_more"] is False


def test_container_invalid_enum_returns_invalid_request(api):
    """PRD §2.8: "Request-body well-formedness: required fields present, enum values
    in range, `quantity_value` greater than zero, `capacity_containers` greater than
    zero, else `ERR_INVALID_REQUEST`."
    PRD §5: ERR_INVALID_REQUEST maps to HTTP 400.

    Design: Corner/entities/container_invalid_enum_returns_invalid_request
    """
    lab, pi = create_lab_with_pi(name="Lab D", room="103")
    payload = create_container_payload(
        lab["id"], barcode="XX-1", chemical_name="Uranium", hazard_class="RADIOACTIVE",
        quantity_value=1.0,
    )
    res = api.create_container(payload, make_pi_headers(pi["id"]))
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)


def test_container_quantity_must_be_positive_rejected(api):
    """PRD §3.2: "Registration is refused with `ERR_INVALID_REQUEST` (HTTP 400) when
    the quantity is not greater than zero"
    PRD §2.8: "Request-body well-formedness: required fields present, enum values in
    range, `quantity_value` greater than zero, `capacity_containers` greater than
    zero, else `ERR_INVALID_REQUEST`."

    Design: Corner/entities/container_quantity_must_be_positive_rejected
    """
    lab, pi = create_lab_with_pi(name="Lab E", room="104")
    payload = create_container_payload(lab["id"], barcode="ZE-1", quantity_value=0)
    res = api.create_container(payload, make_pi_headers(pi["id"]))
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)


def test_success_envelope_shape(api):
    """PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources." and "Pagination-related fields in `meta`
    (`limit`, `offset`, `total_count`, `has_more`) are included for list endpoints."
    PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the
    request that starts with `req_`."

    Design: Corner/endpoints/success_envelope_shape
    """
    lab_res = api.create_lab(
        create_lab_payload(name="Lab EV", department="Chemistry", building="Hall A", room="119"),
        ADMIN,
    )
    lab = validate_success(lab_res, 201)

    single = api.get_lab(lab["id"], ADMIN)
    single_body = single.json()
    assert single_body["response_type"] == "object"
    assert single_body["data"]["id"] == lab["id"]
    assert isinstance(single_body["meta"]["api_request_id"], str)
    assert single_body["meta"]["api_request_id"].startswith("req_")
    assert isinstance(single_body["meta"]["api_request_timestamp"], str)

    list_res = api.list_labs(ADMIN)
    list_body = list_res.json()
    assert list_body["response_type"] == "array"
    _, meta = validate_paginated(list_res)
    for field in ("limit", "offset", "total_count", "has_more"):
        assert field in meta, f"list meta must carry {field}"


def test_containers_filterable_by_pickup_request(api):
    """PRD §3.2: "The container catalog is listed with optional filters `lab_id`,
    `accumulation_area_id`, `pickup_request_id`, `state`, and `hazard_class` — these
    filters are also the supported way to reach containers in reverse from the areas
    or pickup requests that reference them"

    Design: Corner/endpoints/containers_filterable_by_pickup_request
    """
    lab, pi = create_lab_with_trained_pi("FLAMMABLE", name="Lab FK", room="120")
    area = create_area(lab["id"])
    c1 = create_tagged_container(lab["id"], pi, area["id"], barcode="FK-1")
    create_tagged_container(lab["id"], pi, area["id"], barcode="FK-2", chemical_name="Methanol")
    pickup = create_draft_pickup(lab["id"], pi)

    # link only the first container
    validate_success(
        api.add_pickup_item(pickup["id"], {"container_id": c1["id"]}, make_pi_headers(pi["id"])),
        200,
    )

    data, meta = validate_paginated(
        api.list_containers(ADMIN, params={"pickup_request_id": pickup["id"]})
    )
    assert meta["total_count"] == 1, f"expected exactly 1 linked container, got {meta['total_count']}"
    assert len(data) == 1
    assert data[0]["id"] == c1["id"]
