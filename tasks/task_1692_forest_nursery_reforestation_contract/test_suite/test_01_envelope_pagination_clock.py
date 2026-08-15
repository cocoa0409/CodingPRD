"""Envelope shape, pagination, list filtering, and the logical-clock default."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    is_valid_uuid, ApiErrorId, TEST_USERS,
    create_seed_zone, create_seed_lot, create_landowner,
    create_seed_zone_payload,
)

NM = TEST_USERS["nursery_manager_headers"]
CO = TEST_USERS["contract_officer_headers"]


def test_success_envelope_shape(api):
    """PRD §2.2: "All successful API responses (those with 2xx status codes)
    follow this standard envelope format in their JSON body" and "The
    `response_type` is either "object" for a single resource or "array" for a
    list of resources."

    Design: Corner/endpoints/success_envelope_shape
    """
    res = api.create_seed_zone(
        create_seed_zone_payload(zone_code="Z-1", min_elevation_ft=100, max_elevation_ft=900),
        NM,
    )
    data = validate_success(res, 201)
    body = res.json()
    assert isinstance(body["meta"].get("api_request_id"), str)
    assert isinstance(body["meta"].get("api_request_timestamp"), str)
    assert body["response_type"] == "object", (
        f"single-resource create must carry response_type 'object', got {body['response_type']!r}"
    )
    assert is_valid_uuid(data.get("id", "")), f"data.id must be a UUID, got {data.get('id')!r}"


def test_error_envelope_shape(api):
    """PRD §2.2: "All error API responses (4xx status codes) follow this
    standard envelope format" with "The `error_id` is a unique, machine-readable
    string that identifies the specific error" and "The `message` provides a
    human-readable explanation of what went wrong."

    Design: Corner/endpoints/error_envelope_shape
    """
    res = api.get_crew("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", CO)
    err = validate_error(res, ApiErrorId.ERR_NOT_FOUND)
    body = res.json()
    assert body["response_type"] == "error"
    assert err["error_id"] == "ERR_NOT_FOUND"
    assert isinstance(err["message"], str) and err["message"].strip()


def test_pagination_defaults_and_filtering_on_lot_list(api):
    """PRD §2.3: "The `limit` parameter sets the maximum number of items
    returned: it defaults to 10, and accepts values from a minimum of 1 to a
    maximum of 100. The `offset` parameter sets the number of items skipped and
    defaults to 0." and "Paginated list responses carry four pagination fields
    in the `meta` object of the envelope: `limit`, `offset`, `total_count`, and
    `has_more`."

    Design: Corner/entities/pagination_defaults_and_filtering_on_lot_list
    """
    zone = create_seed_zone()
    for day in ("2026-07-15", "2026-07-16", "2026-07-17"):
        create_seed_lot(zone["id"], quantity_grams=100, germination_pct=0.8,
                        collected_on=day)

    data, meta = validate_paginated(
        api.list_seed_lots(NM, params={"source_zone_id": zone["id"], "limit": 2})
    )
    assert len(data) == 2, f"limit=2 must return 2 items, got {len(data)}"
    assert meta["total_count"] == 3
    assert meta["has_more"] is True

    data2, meta2 = validate_paginated(
        api.list_seed_lots(NM, params={"source_zone_id": zone["id"], "limit": 2, "offset": 2})
    )
    assert len(data2) == 1, f"offset=2 over 3 items must return the final row, got {len(data2)}"
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False


def test_fk_reverse_lookup_filtered_list(api):
    """PRD §3.1: "Lots can be listed with optional `source_zone_id`, `species`,
    and `status` filters."

    Design: Corner/entities/fk_reverse_lookup_filtered_list
    """
    z_src = create_seed_zone()
    z_empty = create_seed_zone(zone_min=100, zone_max=200)
    create_seed_lot(z_src["id"], species="WHITE_OAK", quantity_grams=100, germination_pct=0.7)
    create_seed_lot(z_src["id"], species="WHITE_OAK", quantity_grams=100, germination_pct=0.7,
                    collected_on="2026-07-16")

    data, meta = validate_paginated(api.list_seed_lots(NM, params={"source_zone_id": z_src["id"]}))
    assert meta["total_count"] == 2, f"expected exactly the 2 lots of the source zone, got {meta['total_count']}"

    data2, meta2 = validate_paginated(api.list_seed_lots(NM, params={"source_zone_id": z_empty["id"]}))
    assert meta2["total_count"] == 0
    assert data2 == []


def test_clock_default_startup_time(api, contract_officer_headers):
    """PRD §2.5: "The server never reads the wall clock. All temporal rules in
    this document evaluate against a logical clock that, before any adjustment,
    reads exactly 2026-08-01T00:00:00Z — the server-startup default." and
    PRD §2.4: "`created_at` (string): an ISO 8601 UTC timestamp with three
    fractional digits, set when the resource is created."

    Design: Corner/cross_cutting/clock_default_startup_time
    """
    landowner = create_landowner(legal_name="Owner X", contact_email="x@x.com", tax_id="T-X")
    assert landowner["created_at"] == "2026-08-01T00:00:00.000Z", (
        f"created_at must be the logical clock's startup default "
        f"2026-08-01T00:00:00.000Z, got {landowner['created_at']!r}"
    )
