"""Optimistic concurrency on block booking, immediate-consistency of the estimate,
and CRUD breadth: facility defaults, required-field validation, not-found, computed
reserved_qty, append-only clearance checks, duplicate-key uniqueness, listing.

Difficulty queue: (none — OCC corners are difficulty-owned via cross_cutting layer below).
Corner queue: cross_cutting_complexity_layers (OCC succeed/stale), consistency_model
              (immediate estimate), entities, endpoints (listing / FK reverse-list).
"""
from test_helpers import validate_success, validate_error, validate_paginated, get_success_data, fixtures
from test_helpers.api_client import api_client
from test_helpers.test_users import TEST_USERS

SCHED = TEST_USERS["scheduler_headers"]
ORMGR = TEST_USERS["or_manager_headers"]
BILL = TEST_USERS["billing_analyst_headers"]


# ===========================================================================
# Corner / cross_cutting_complexity_layers / occ_correct_version_book_succeeds_and_bumps
# ===========================================================================
def test_booking_with_current_version_succeeds_and_bumps_version():
    """PRD §2.8: "Before any booking logic runs, the server compares `expected_block_version`
    to the block's current `version`."
    PRD §3.4: "Booking adds the case's `scheduled_minutes` to the block's `committed_minutes`,
    recomputes the owning day's `booked_minutes` and `utilization_pct`, computes the case's
    `estimated_cost_cents`, and increments the block's `version` by 1."

    A booking carrying the block's current version (1) succeeds (201) and advances the
    block's version 1 -> 2.

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_book_succeeds_and_bumps
    """
    world, block = fixtures.setup_world_with_block(start_min=480, end_min=600)
    assert block["version"] == 1, block["version"]
    resp = api_client.book_case(block["id"], {
        "expected_block_version": block["version"], "patient_id": world["patient"]["id"],
        "procedure_id": world["procedure"]["id"], "start_min": 480}, SCHED)
    validate_success(resp, 201)
    after = get_success_data(api_client.get_surgeon_block(block["id"], SCHED))
    assert after["version"] == 2, after["version"]


# ===========================================================================
# Corner / cross_cutting_complexity_layers / occ_stale_version_book_rejected_412
# ===========================================================================
def test_booking_with_stale_version_rejected_412():
    """PRD §2.8: "If they do not match — because another writer has committed minutes into
    that same block and thereby advanced its `version` since the client last read it — the
    booking is rejected with `ERR_STALE_BLOCK_VERSION` (HTTP 412)."

    After a first booking advances the block to version 2, a second booking still carrying
    the pre-book version 1 is rejected with ERR_STALE_BLOCK_VERSION (412).

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_book_rejected_412
    """
    world = fixtures.setup_facility_world()
    fac, room, surg, day, proc = (world["facility"], world["room"], world["surgeon"],
                                  world["day"], world["procedure"])
    pat1, pat2 = world["patient"], fixtures.create_patient(fac["id"], mrn="MRN2", full_name="Pat Two", date_of_birth="1981-01-01")
    block = fixtures.create_surgeon_block(day["id"], surg["id"], room["id"], 480, 720)
    stale_version = block["version"]
    fixtures.book_case(block["id"], stale_version, pat1["id"], proc["id"], 480)  # advances to 2
    resp = api_client.book_case(block["id"], {
        "expected_block_version": stale_version, "patient_id": pat2["id"],
        "procedure_id": proc["id"], "start_min": 600}, SCHED)
    validate_error(resp, "ERR_STALE_BLOCK_VERSION")


# ===========================================================================
# Corner / consistency_model / immediate_estimated_cost_in_create_response
# ===========================================================================
def test_estimate_present_in_booking_response():
    """PRD §3.9: "At booking, and again whenever an implant is attached to or released from
    the case while its `case_status` is still `SCHEDULED`, the system computes the case's
    `estimated_cost_cents` from its planned inputs."
    PRD §3.9: "The labor part is the procedure's `scheduled_minutes` multiplied by the OR
    minute rate of 1,200 cents per scheduled minute (twelve dollars a minute)."

    MAC 60-min: 60*1200 + 18000 = 90000, present in the same booking (201) response.

    Design: Corner/consistency_model/immediate_estimated_cost_in_create_response
    """
    world, block = fixtures.setup_world_with_block(start_min=480, end_min=600)
    resp = api_client.book_case(block["id"], {
        "expected_block_version": block["version"], "patient_id": world["patient"]["id"],
        "procedure_id": world["procedure"]["id"], "start_min": 480}, SCHED)
    data = validate_success(resp, 201)
    assert data["estimated_cost_cents"] == 90000, data["estimated_cost_cents"]


# ===========================================================================
# Corner / entities / create_facility_returns_201_with_defaults
# ===========================================================================
def test_create_facility_applies_defaults():
    """PRD §3.1: "optionally overriding three operational defaults: the `turnover_minutes`
    cleaning buffer (default 25, and never negative), the `hp_validity_days` H&P validity
    window (default 30), and the `utilization_target_pct` prime-time utilization target
    (default 75, on a scale of 0 to 100)."
    PRD §2.4: "The `version` field is an integer that starts at 1 on creation and increments
    by exactly 1 on every mutation of the resource."

    Design: Corner/entities/create_facility_returns_201_with_defaults
    """
    resp = api_client.create_facility({"name": "ASC Defaults"}, SCHED)
    data = validate_success(resp, 201)
    assert data["turnover_minutes"] == 25, data["turnover_minutes"]
    assert data["hp_validity_days"] == 30, data["hp_validity_days"]
    assert data["utilization_target_pct"] == 75, data["utilization_target_pct"]
    assert data["version"] == 1, data["version"]


# ===========================================================================
# Corner / entities / create_procedure_missing_required_field_rejected
# ===========================================================================
def test_create_procedure_missing_cms_indicator_rejected():
    """PRD §2.6: "fifth, that the body is well-formed — required fields present and correctly
    typed, enum values within their permitted set, minute quantities positive, an NPI exactly
    10 digits, a CPT code exactly 5 characters (`ERR_INVALID_REQUEST`, HTTP 400)..."

    cms_payment_indicator carries no default in §3.1, so omitting it from a procedure create
    is a missing required field -> ERR_INVALID_REQUEST.

    Design: Corner/entities/create_procedure_missing_required_field_rejected
    """
    fac = fixtures.create_facility()
    resp = api_client.create_procedure({
        "facility_id": fac["id"], "cpt_code": "29881", "description": "X",
        "scheduled_minutes": 60, "cms_base_rate_cents": 150000}, BILL)
    validate_error(resp, "ERR_INVALID_REQUEST")


# ===========================================================================
# Corner / entities / get_surgical_case_nonexistent_returns_not_found
# ===========================================================================
def test_get_nonexistent_case_returns_not_found():
    """PRD §2.5: "Path identifiers are resolved left to right, and the first one that does
    not resolve to an existing resource produces that resource's not-found error — ...
    `ERR_SURGICAL_CASE_NOT_FOUND`, ... each at HTTP 404."

    Design: Corner/entities/get_surgical_case_nonexistent_returns_not_found
    """
    resp = api_client.get_surgical_case("00000000-0000-4000-8000-000000000000", SCHED)
    validate_error(resp, "ERR_SURGICAL_CASE_NOT_FOUND")


# ===========================================================================
# Corner / entities / supply_item_computed_reserved_qty_input_ignored
# ===========================================================================
def test_supply_item_reserved_qty_starts_zero():
    """PRD §3.2: "Each item also exposes a computed `reserved_qty`, which begins at 0 and
    tracks how many units are currently spoken for."

    A freshly created supply item with on_hand 50 has reserved_qty 0 (no RESERVED implants).

    Design: Corner/entities/supply_item_computed_reserved_qty_input_ignored
    """
    fac = fixtures.create_facility()
    resp = api_client.create_supply_item({
        "facility_id": fac["id"], "sku": "SKU1", "description": "Gauze",
        "unit_cost_cents": 100, "on_hand_qty": 50}, ORMGR)
    data = validate_success(resp, 201)
    assert data["reserved_qty"] == 0, data["reserved_qty"]
    assert data["on_hand_qty"] == 50, data["on_hand_qty"]


# ===========================================================================
# Corner / entities / clearance_check_immutable_no_version_field
# ===========================================================================
def test_clearance_check_has_no_version_field():
    """PRD §2.4: "A `ClearanceCheck` is an **append-only event record**, not a mutable
    resource: it carries only an `id` and a `created_at`, and it has neither an `updated_at`
    nor a `version`."

    The clearance-check create response (201) carries id + created_at but no version field.

    Design: Corner/entities/clearance_check_immutable_no_version_field
    """
    world, block, case = fixtures.setup_booked_case(start_min=480, block_start=480, block_end=600)
    resp = api_client.record_clearance_check(case["id"], {"check_type": "LABS", "outcome": "PASS"}, TEST_USERS["preop_nurse_headers"])
    data = validate_success(resp, 201)
    assert "id" in data and "created_at" in data
    assert "version" not in data, "ClearanceCheck must not expose a version field"


# ===========================================================================
# Corner / entities / duplicate_surgeon_npi_within_facility_rejected
# ===========================================================================
def test_duplicate_surgeon_npi_rejected():
    """PRD §3.1: "Within a single facility, the following must each be unique, and a collision
    is rejected as `ERR_DUPLICATE_KEY`: a surgeon's `npi`, a procedure's `cpt_code`, a
    patient's `mrn`, a supply item's `sku`, and a surgical day's `service_date`."

    Design: Corner/entities/duplicate_surgeon_npi_within_facility_rejected
    """
    fac = fixtures.create_facility()
    fixtures.create_surgeon(fac["id"], full_name="Dr A", npi="1234567890")
    resp = api_client.create_surgeon({
        "facility_id": fac["id"], "full_name": "Dr B", "npi": "1234567890"}, SCHED)
    validate_error(resp, "ERR_DUPLICATE_KEY")


# ===========================================================================
# Corner / endpoints / list_surgical_cases_pagination_envelope
# ===========================================================================
def test_list_surgical_cases_pagination_meta():
    """PRD §2.3: "The `meta` block of a list response carries `limit`, `offset`,
    `total_count`, and `has_more`, where `total_count` is the count of records matching the
    filter before pagination is applied and `has_more` is true exactly when records remain
    beyond the current page."

    One booked case filtered by day -> array response with total_count 1 and has_more false.

    Design: Corner/endpoints/list_surgical_cases_pagination_envelope
    """
    world, block, case = fixtures.setup_booked_case(start_min=480, block_start=480, block_end=600)
    resp = api_client.list_surgical_cases(ORMGR, params={"surgical_day_id": world["day"]["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1, meta["total_count"]
    assert meta["has_more"] is False, meta["has_more"]


# ===========================================================================
# Corner / endpoints / fk_reverse_list_implants_by_case
# ===========================================================================
def test_list_case_implants_by_case():
    """PRD §2.5: "Relationships are carried as foreign-key fields on the body and resolved
    through filtered list endpoints rather than nested URLs."
    PRD §2.3: "where `total_count` is the count of records matching the filter before
    pagination is applied..."

    GET /asc/case-implants?surgical_case_id={case} returns the case's implants (FK
    reverse-reachability) -> total_count 1.

    Design: Corner/endpoints/fk_reverse_list_implants_by_case
    """
    world, block, case = fixtures.setup_booked_case(start_min=480, block_start=480, block_end=600)
    item = fixtures.create_supply_item(world["facility"]["id"], sku="DEV1", description="Implant",
                                       unit_cost_cents=5000, is_device=True, on_hand_qty=5)
    fixtures.attach_implant(case["id"], item["id"], 1)
    resp = api_client.list_case_implants(ORMGR, params={"surgical_case_id": case["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1, meta["total_count"]
