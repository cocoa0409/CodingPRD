"""Entity creation, retrieval, listing, defaults, and referential basics.

Queue B (corner) — entities, state_machines (initial state), errors (duplicate cultivar).
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    api_client,
    create_variety_payload, create_zone_payload, create_batch_payload,
    TEST_USERS, NON_EXISTENT_UUID,
    create_active_variety, create_zone, create_planned_batch, set_clock,
    setup_growing_batch,
)

GM = TEST_USERS["grower_manager_headers"]
PT = TEST_USERS["production_tech_headers"]


def test_create_variety_returns_201_with_fields(api):
    """PRD 3.1: "A newly created variety begins in `DRAFT` and is not yet eligible
    to back any batch."

    Design: Corner/entities/create_variety_returns_201_with_all_fields
    """
    payload = create_variety_payload(
        common_name="Petunia X", cultivar_code="PETX1", propagation_form="PLUG",
        grow_cycle_days=10, container_footprint_units=2,
        ship_ready_grade_min_height_cm=12, ship_ready_min_live_pct=0.80,
        requires_phyto=False,
    )
    data = validate_success(api.create_variety(payload, GM), expected_status=201)
    assert data["status"] == "DRAFT", f"new variety must be DRAFT, got {data['status']}"
    assert data["cultivar_code"] == "PETX1"
    assert data["grow_cycle_days"] == 10
    assert isinstance(data["version"], int), "version must be an integer"


def test_get_zone_returns_clean_occupancy(api):
    """PRD 3.2: "At creation the derived figures start clean: `occupied_units` is 0,
    `reserved_units` is 0, `free_units` equals `capacity_units`, `fill_state` is
    `OPEN`, and `status` is `OPEN_FOR_USE`."

    Design: Corner/entities/get_zone_returns_stored_entity
    """
    created = validate_success(api.create_zone(
        create_zone_payload(name="Z1", climate_class="WARM", capacity_units=500), GM),
        expected_status=201)
    data = validate_success(api.get_zone(created["id"], GM))
    assert data["occupied_units"] == 0
    assert data["reserved_units"] == 0
    assert data["free_units"] == 500
    assert data["fill_state"] == "OPEN"


def test_list_varieties_paginated_envelope(api):
    """PRD 2.3: "Every list response includes the following fields in the `meta`
    object of the envelope: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/list_varieties_paginated_envelope
    """
    for code in ("AAA1", "BBB1", "CCC1"):
        validate_success(api.create_variety(create_variety_payload(
            common_name=code, cultivar_code=code), GM), expected_status=201)
    resp = api.list_varieties(GM, params={"limit": 2, "offset": 0})
    data, meta = validate_paginated(resp)
    assert len(data) == 2, f"limit=2 must return 2 rows, got {len(data)}"
    assert meta["total_count"] == 3
    assert meta["has_more"] is True


def test_get_batch_nonexistent_returns_not_found(api):
    """PRD 2.6: "When any referenced resource — whether named in the path or as a
    foreign key in the body — does not exist, the request is rejected with
    `ERR_NOT_FOUND`."

    Design: Corner/entities/get_batch_nonexistent_returns_not_found
    """
    resp = api.get_batch(NON_EXISTENT_UUID, PT)
    validate_error(resp, "ERR_NOT_FOUND", expected_status=404)


def test_create_variety_missing_required_field_rejected(api):
    """PRD 2.8: "fourth, request well-formedness — required body fields must be
    present and correctly typed, enum values must fall within their allowed set,
    and numeric ranges must be honored (`ERR_INVALID_REQUEST`)."

    Design: Corner/entities/create_variety_missing_required_field_invalid_request
    """
    payload = {
        "common_name": "NoCycle", "cultivar_code": "NOCY1", "propagation_form": "PLUG",
        "container_footprint_units": 1, "ship_ready_grade_min_height_cm": 8,
        "ship_ready_min_live_pct": 0.5,
    }  # grow_cycle_days omitted (required, no default)
    validate_error(api.create_variety(payload, GM), "ERR_INVALID_REQUEST", expected_status=422)


def test_variety_requires_phyto_defaults_false(api):
    """PRD 3.1: "A variety may optionally declare `requires_phyto`, a boolean that
    flags whether interstate shipment of this variety requires a phytosanitary
    certificate; when omitted it defaults to false."

    Design: Corner/entities/variety_requires_phyto_default_false_applied
    """
    payload = create_variety_payload(common_name="DefPhyto", cultivar_code="DEFP1")
    data = validate_success(api.create_variety(payload, GM), expected_status=201)
    assert data["requires_phyto"] is False, "omitted requires_phyto must default to false"


def test_batch_lot_code_is_server_minted(api):
    """PRD 3.3: "On creation the server mints a unique traceability `lot_code`, sets
    the batch to `PLANNED`, and initializes `live_count` to 0 and `saleable_count`
    to 0."

    Design: Corner/entities/batch_lot_code_system_generated_input_ignored
    """
    set_clock(api, "2026-02-01T00:00:00Z")
    variety = create_active_variety(api, cultivar_code="LOT1", propagation_form="PLUG")
    zone = create_zone(api, capacity_units=100)
    data = validate_success(api.create_batch(create_batch_payload(
        variety_id=variety["id"], zone_id=zone["id"], source_supplier="S", sourced_count=10),
        PT), expected_status=201)
    assert isinstance(data["lot_code"], str) and len(data["lot_code"]) > 0, \
        "lot_code must be a non-empty server-minted string"
    assert data["status"] == "PLANNED"


def test_input_log_has_no_version_field(api):
    """PRD 2.4: "an input-log event carries only an `id` and a `created_at`. It has
    no `updated_at` and no `version`, because such an event is never modified after
    it is written."

    Design: Corner/entities/inputlog_immutable_no_version_field
    """
    base = setup_growing_batch(api, sourced=10, capacity=100, cultivar_code="ILG1")
    data = validate_success(api.create_input_log(
        base["batch"]["id"], {"event_type": "CLIMATE", "temperature_c": 22.5}, PT),
        expected_status=201)
    assert "version" not in data, "InputLog must not carry a version field"
    assert "updated_at" not in data, "InputLog must not carry an updated_at field"
    assert "id" in data and "created_at" in data


def test_variety_invalid_propagation_form_rejected(api):
    """PRD 3.1: "a `propagation_form` describing how new batches are sourced (one of
    `PLUG`, `LINER`, or `BARE_ROOT`)".

    Design: Corner/entities/variety_invalid_enum_propagation_form_rejected
    """
    payload = create_variety_payload(common_name="Bad", cultivar_code="BAD1",
                                     propagation_form="SEED")
    validate_error(api.create_variety(payload, GM), "ERR_INVALID_REQUEST", expected_status=422)


def test_batch_create_unknown_variety_not_found(api):
    """PRD 2.6: "Existence is checked left-to-right in the path first, then on the
    body foreign keys."

    Design: Corner/entities/batch_create_wrong_variety_id_not_found
    """
    zone = create_zone(api, capacity_units=100)
    resp = api.create_batch(create_batch_payload(
        variety_id=NON_EXISTENT_UUID, zone_id=zone["id"], source_supplier="S", sourced_count=10), PT)
    validate_error(resp, "ERR_NOT_FOUND", expected_status=404)


def test_list_batches_by_zone_reverse_lookup(api):
    """PRD 3.2: "A reverse-lookup capability lists every batch assigned to a given
    zone."

    Design: Corner/entities/fk_reverse_list_batches_by_zone
    """
    set_clock(api, "2026-02-01T00:00:00Z")
    variety = create_active_variety(api, cultivar_code="RVG1", propagation_form="PLUG")
    zone = create_zone(api, capacity_units=100)
    batch = create_planned_batch(api, variety["id"], zone["id"], sourced_count=10)
    resp = api.list_zone_batches(zone["id"], GM)
    data, _ = validate_paginated(resp)
    ids = [b["id"] for b in data]
    assert batch["id"] in ids, "reverse lookup must list the zone's batch"
    assert all(b["zone_id"] == zone["id"] for b in data)


def test_variety_initial_state_is_draft(api):
    """PRD 3.1: "A newly created variety begins in `DRAFT` and is not yet eligible
    to back any batch."

    Design: Corner/state_machines/variety_initial_state_is_draft
    """
    data = validate_success(api.create_variety(create_variety_payload(
        common_name="Init", cultivar_code="INIT1"), GM), expected_status=201)
    assert data["status"] == "DRAFT"


def test_duplicate_cultivar_on_activate_rejected(api):
    """PRD 3.1: "that the `cultivar_code` is unique among all varieties whose status
    is not `RETIRED`; a collision is rejected with `ERR_DUPLICATE_CULTIVAR`."

    Design: Corner/errors/duplicate_cultivar_on_activate_excluded
    """
    v1 = validate_success(api.create_variety(create_variety_payload(
        common_name="V1", cultivar_code="DUP1"), GM), expected_status=201)
    validate_success(api.activate_variety(v1["id"], GM))
    v2 = validate_success(api.create_variety(create_variety_payload(
        common_name="V2", cultivar_code="DUP1"), GM), expected_status=201)
    validate_error(api.activate_variety(v2["id"], GM), "ERR_DUPLICATE_CULTIVAR", expected_status=409)
