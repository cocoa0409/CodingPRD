"""Corner section: entities (creation, required fields, not-found, computed
defaults, type constraints, immutability, listing)."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    setup_issuing_context,
    make_enforcement_officer_headers,
    is_valid_uuid,
)

ADMIN = TEST_USERS["admin_headers"]


def test_create_officer_returns_201_with_id(api):
    """PRD §4: "Operations that create a new stand-alone resource return
    `201 Created`."
    PRD §2.4: "`version` — an integer that starts at creation and increments by one
    on every mutation."

    Design: Corner/entities/create_officer_returns_201_with_id
    """
    officer = validate_success(
        api.create_officer({"badge_number": "B-100", "full_name": "Jane Officer"}, ADMIN),
        201)
    assert is_valid_uuid(officer["id"])
    assert officer["badge_number"] == "B-100"
    assert officer["version"] == 1, f"new officer version must be 1, got {officer['version']}"


def test_officer_missing_full_name_returns_validation(api):
    """PRD §2.10: "10. **Field-level** — required fields are present, enums are valid,
    each `scheduled_end` is strictly after its `scheduled_start`, and pagination is in
    bounds, else `ERR_VALIDATION` (400). Applies to every endpoint."

    Design: Corner/entities/officer_missing_full_name_returns_validation
    """
    validate_error(
        api.create_officer({"badge_number": "B-101"}, ADMIN),
        ApiErrorId.ERR_VALIDATION.value)


def test_get_vehicle_nonexistent_returns_not_found(api):
    """PRD §2.9: "The first reference that does not resolve produces the corresponding
    not-found error, one per entity, all carrying HTTP 404: `ERR_OFFICER_NOT_FOUND`,
    `ERR_BEAT_NOT_FOUND`, `ERR_VIOLATION_CODE_NOT_FOUND`, `ERR_HEARING_ROOM_NOT_FOUND`,
    `ERR_SHIFT_NOT_FOUND`, `ERR_VEHICLE_NOT_FOUND`, `ERR_CITATION_NOT_FOUND`,
    `ERR_PAYMENT_NOT_FOUND`, `ERR_CONTEST_NOT_FOUND`, `ERR_HEARING_NOT_FOUND`,
    `ERR_BOOT_TOW_ORDER_NOT_FOUND`, and `ERR_REGISTRATION_HOLD_NOT_FOUND`."

    Design: Corner/entities/get_vehicle_nonexistent_returns_not_found
    """
    validate_error(
        api.get_vehicle(NON_EXISTENT_UUID, ADMIN),
        ApiErrorId.ERR_VEHICLE_NOT_FOUND.value)


def test_vehicle_ledger_fields_default_zero_on_create(api):
    """PRD §3.4: "Every `Vehicle` is registered with a `plate` and a two-letter
    `state` and starts with a `scofflaw_status` of `NONE` and zero balances."

    Design: Corner/entities/vehicle_ledger_fields_default_zero_on_create
    """
    veh = validate_success(
        api.create_vehicle({"plate": "NEW1", "state": "NV"}, ADMIN), 201)
    assert veh["outstanding_balance_cents"] == 0
    assert veh["projected_balance_cents"] == 0
    assert veh["unpaid_citation_count"] == 0
    assert veh["scofflaw_status"] == "NONE"
    assert veh["has_active_registration_hold"] is False


def test_citation_issued_via_invalid_enum_returns_validation(api):
    """PRD §2.10: "10. **Field-level** — required fields are present, enums are valid,
    each `scheduled_end` is strictly after its `scheduled_start`, and pagination is in
    bounds, else `ERR_VALIDATION` (400). Applies to every endpoint."

    Design: Corner/entities/citation_issued_via_invalid_enum_returns_validation
    """
    ctx = setup_issuing_context()
    validate_error(
        api.create_citation(
            {"vehicle_id": ctx["vehicle"]["id"], "shift_id": ctx["shift"]["id"],
             "violation_code_id": ctx["violation_code"]["id"],
             "issued_via": "DRONE", "evidence_photo_url": "https://ev/en1.jpg"},
            make_enforcement_officer_headers(ctx["officer"]["id"])),
        ApiErrorId.ERR_VALIDATION.value)


def test_beat_created_has_no_version_field(api):
    """PRD §2.4: "Two resource types are immutable configuration records and therefore
    carry only `id` and `created_at` — they have no `updated_at` and no `version`: the
    `Beat` and the `HearingRoom`."

    Design: Corner/entities/beat_created_has_no_version_field
    """
    beat = validate_success(
        api.create_beat(
            {"beat_code": "IMMB", "name": "Immutable Beat", "patrol_zone": "SCHOOL"},
            ADMIN), 201)
    assert beat["patrol_zone"] == "SCHOOL"
    assert "version" not in beat, "Beat must not carry a version field"
    assert "updated_at" not in beat, "Beat must not carry an updated_at field"


def test_citations_list_pagination_envelope(api):
    """PRD §2.3: "The `limit` parameter caps the number of items returned; it defaults
    to 10, with a minimum of 1 and a maximum of 100. ... Each list response carries
    `limit`, `offset`, `total_count`, and `has_more` in the envelope's `meta` object."

    Design: Corner/entities/citations_list_pagination_envelope
    """
    ctx = setup_issuing_context(base_fine_cents=6000, code="STREET_CLEAN",
                                is_booting_eligible=False)
    officer_headers = make_enforcement_officer_headers(ctx["officer"]["id"])
    api.create_citation(
        {"vehicle_id": ctx["vehicle"]["id"], "shift_id": ctx["shift"]["id"],
         "violation_code_id": ctx["violation_code"]["id"], "issued_via": "LPR",
         "evidence_photo_url": "https://ev/pg1.jpg"}, officer_headers)
    api.create_citation(
        {"vehicle_id": ctx["vehicle"]["id"], "shift_id": ctx["shift"]["id"],
         "violation_code_id": ctx["violation_code"]["id"], "issued_via": "LPR",
         "evidence_photo_url": "https://ev/pg2.jpg"}, officer_headers)

    data, meta = validate_paginated(
        api.list_citations(ADMIN, params={"vehicle_id": ctx["vehicle"]["id"],
                                          "limit": 1, "offset": 0}))
    assert meta["total_count"] == 2, f"expected total_count 2, got {meta['total_count']}"
    assert meta["has_more"] is True
    assert len(data) == 1, f"limit=1 must return exactly 1 element, got {len(data)}"
