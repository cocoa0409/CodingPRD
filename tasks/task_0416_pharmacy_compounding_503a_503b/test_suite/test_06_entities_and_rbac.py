"""Entity CRUD, computed/default fields, immutable readings, pagination,
self-referential and FK reverse-reach links, and role-based access control.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    TEST_USERS,
    create_facility,
    create_mfr,
    create_lot,
    create_draft_batch,
    charge_usage,
    create_facility_payload,
    create_mfr_payload,
    create_ingredient_lot_payload,
    create_environmental_log_payload,
    create_batch_ingredient_usage_payload,
    create_qc_test_payload,
    record_qc_payload,
    create_started_batch,
    assert_facility,
    assert_environmental_log,
)

ADMIN = TEST_USERS["admin_headers"]
COMP = TEST_USERS["compounding_headers"]
QA = TEST_USERS["qa_headers"]
DISP = TEST_USERS["dispensing_headers"]


# ─────────────────────────────────────────────────────────────────────────────
# Corner/entities/create_facility_returns_201_with_defaults
# ─────────────────────────────────────────────────────────────────────────────

def test_create_facility_defaults_clock_and_version(api):
    """PRD §3.1: "On creation the facility's current_utc clock is initialized to
    1970-01-01T00:00:00.000Z." and PRD §2.4: "an integer version that begins at its
    initial value".

    Design: Corner/entities/create_facility_returns_201_with_defaults
    """
    res = api.create_facility(
        create_facility_payload(name="Acme Pharmacy", registration_type="503A",
                                state_code="CA"), ADMIN)
    facility = validate_success(res, 201)
    assert_facility(facility)
    assert facility["current_utc"] == "1970-01-01T00:00:00.000Z"
    assert facility["version"] == 1
    assert res.json()["response_type"] == "object"


# ─────────────────────────────────────────────────────────────────────────────
# Corner/entities/get_facility_not_found_returns_404
# ─────────────────────────────────────────────────────────────────────────────

def test_get_facility_not_found(api):
    """PRD §3.11: "the system confirms that each path identifier resolves to an
    existing resource — returning the resource-specific not-found error such as
    ERR_FACILITY_NOT_FOUND".

    Design: Corner/entities/get_facility_not_found_returns_404
    """
    res = api.get_facility("00000000-0000-4000-8000-000000000000", ADMIN)
    validate_error(res, "ERR_FACILITY_NOT_FOUND", expected_status=404)


# ─────────────────────────────────────────────────────────────────────────────
# Corner/entities/create_mfr_missing_required_field_returns_invalid_request
# ─────────────────────────────────────────────────────────────────────────────

def test_create_mfr_missing_dosage_form_rejected(api):
    """PRD §3.11: "Malformed bodies, missing required fields, type mismatches, and
    out-of-range numerics ... are rejected with ERR_INVALID_REQUEST".

    Design: Corner/entities/create_mfr_missing_required_field_returns_invalid_request
    """
    facility = create_facility("503A", clock=None)
    payload = create_mfr_payload(facility["id"], name="No Form")
    del payload["dosage_form"]
    res = api.create_mfr(payload, COMP)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


# ─────────────────────────────────────────────────────────────────────────────
# Corner/entities/create_mfr_invalid_dosage_form_enum_returns_invalid_enum
# ─────────────────────────────────────────────────────────────────────────────

def test_create_mfr_invalid_dosage_form_enum_rejected(api):
    """PRD §3.11: "an enum field carrying a value outside its declared set is
    rejected with ERR_INVALID_ENUM_VALUE."

    Design: Corner/entities/create_mfr_invalid_dosage_form_enum_returns_invalid_enum
    """
    facility = create_facility("503A", clock=None)
    res = api.create_mfr(
        create_mfr_payload(facility["id"], name="Bad Form", dosage_form="GASEOUS"), COMP)
    validate_error(res, "ERR_INVALID_ENUM_VALUE", expected_status=400)


# ─────────────────────────────────────────────────────────────────────────────
# Corner/entities/mfr_is_sterile_computed_from_dosage_form
# ─────────────────────────────────────────────────────────────────────────────

def test_mfr_is_sterile_computed_from_dosage_form(api):
    """PRD §3.2: "From it the system computes the read-only is_sterile flag: the
    record is sterile exactly when its dosage form is STERILE_AQUEOUS or
    STERILE_NONAQUEOUS."

    Design: Corner/entities/mfr_is_sterile_computed_from_dosage_form
    """
    facility = create_facility("503B", clock=None)
    mfr = validate_success(
        api.create_mfr(
            create_mfr_payload(facility["id"], name="Oily Inj",
                               dosage_form="STERILE_NONAQUEOUS",
                               default_bud_days_nonsterile=1), COMP), 201)
    assert mfr["is_sterile"] is True


# ─────────────────────────────────────────────────────────────────────────────
# Corner/entities/create_mfr_default_anticipatory_window_days_applied
# ─────────────────────────────────────────────────────────────────────────────

def test_mfr_anticipatory_window_defaults_to_30(api):
    """PRD §3.2: "The rolling window length anticipatory_window_days may be
    supplied; when omitted it defaults to 30 days".

    Design: Corner/entities/create_mfr_default_anticipatory_window_days_applied
    """
    facility = create_facility("503B", clock=None)
    mfr = validate_success(
        api.create_mfr(
            create_mfr_payload(facility["id"], name="Default Window"), COMP), 201)
    assert mfr["anticipatory_window_days"] == 30


# ─────────────────────────────────────────────────────────────────────────────
# Corner/entities/ingredient_lot_remaining_grams_initialized_to_initial_grams
# ─────────────────────────────────────────────────────────────────────────────

def test_ingredient_lot_remaining_grams_initialized(api):
    """PRD §3.3: "A freshly received lot begins with status of AVAILABLE and with
    its remaining_grams equal to initial_grams."

    Design: Corner/entities/ingredient_lot_remaining_grams_initialized_to_initial_grams
    """
    facility = create_facility("503A", clock=None)
    lot = validate_success(
        api.create_ingredient_lot(
            create_ingredient_lot_payload(facility["id"], initial_grams=50,
                                          expiration_utc="2030-01-01T00:00:00.000Z"), COMP), 201)
    assert lot["remaining_grams"] == pytest.approx(50.0, abs=0.0001)
    assert lot["status"] == "AVAILABLE"


# ─────────────────────────────────────────────────────────────────────────────
# Corner/entities/environmental_log_in_spec_computed_and_no_version_field
# ─────────────────────────────────────────────────────────────────────────────

def test_environmental_log_in_spec_computed_and_immutable(api):
    """PRD §3.4: "the system computes the read-only in_spec flag as true exactly
    when the measured_value is at most the action_limit". PRD §2.4: "An
    EnvironmentalLog is an immutable monitoring reading: it carries only id and
    created_at, and has neither an updated_at field nor a version field."

    Design: Corner/entities/environmental_log_in_spec_computed_and_no_version_field
    """
    facility = create_facility("503B", clock="2026-06-01T00:00:00.000Z")
    res = api.create_environmental_log(
        create_environmental_log_payload(
            facility["id"], usp_chapter="USP_797", reading_type="VIABLE_AIR_CFU",
            measured_value=3, action_limit=5), QA)
    log = validate_success(res, 201)
    assert_environmental_log(log)
    assert log["in_spec"] is True
    assert log["reading_utc"] == "2026-06-01T00:00:00.000Z"


# ─────────────────────────────────────────────────────────────────────────────
# Corner/entities/ingredient_lot_self_referential_parent_lot_id_filter
# ─────────────────────────────────────────────────────────────────────────────

def test_ingredient_lot_parent_lot_id_self_reference_filter(api):
    """PRD §3.3: "The parent_lot_id may be supplied to mark this lot as a split or
    re-assayed child of a source lot, establishing a self-reference to another
    ingredient lot."

    Design: Corner/entities/ingredient_lot_self_referential_parent_lot_id_filter
    """
    facility = create_facility("503A", clock=None)
    parent = create_lot(facility["id"], lot_number="X-PARENT", initial_grams=50,
                        expiration_utc="2030-01-01T00:00:00.000Z")
    child = create_lot(facility["id"], lot_number="X-CHILD", labeled_potency_pct=99.4,
                       initial_grams=20, expiration_utc="2030-01-01T00:00:00.000Z",
                       parent_lot_id=parent["id"])

    data, meta = validate_paginated(
        api.list_ingredient_lots(COMP, params={"parent_lot_id": parent["id"]}))
    assert meta["total_count"] == 1
    assert any(row["id"] == child["id"] for row in data)


# ─────────────────────────────────────────────────────────────────────────────
# Corner/entities/list_ingredient_lots_pagination_envelope
# ─────────────────────────────────────────────────────────────────────────────

def test_list_ingredient_lots_pagination(api):
    """PRD §2.3: "The limit parameter specifies the maximum number of items to
    return ... Paginated list responses include the following fields in the meta
    object of the response envelope: limit, offset, total_count, and has_more."

    Design: Corner/entities/list_ingredient_lots_pagination_envelope
    """
    facility = create_facility("503A", clock=None)
    create_lot(facility["id"], lot_number="X-1", initial_grams=50,
               expiration_utc="2030-01-01T00:00:00.000Z")
    create_lot(facility["id"], lot_number="Y-1", initial_grams=50,
               expiration_utc="2030-01-01T00:00:00.000Z")

    data, meta = validate_paginated(
        api.list_ingredient_lots(
            COMP, params={"facility_id": facility["id"], "limit": 1, "offset": 0}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


# ─────────────────────────────────────────────────────────────────────────────
# Corner/entities/list_ingredient_lots_invalid_pagination_returns_error
# ─────────────────────────────────────────────────────────────────────────────

def test_list_ingredient_lots_invalid_pagination(api):
    """PRD §2.3: "A limit below 1 or above 100, or a negative offset, is rejected
    with ERR_INVALID_PAGINATION."

    Design: Corner/entities/list_ingredient_lots_invalid_pagination_returns_error
    """
    facility = create_facility("503A", clock=None)
    res = api.list_ingredient_lots(
        COMP, params={"facility_id": facility["id"], "limit": 0})
    validate_error(res, "ERR_INVALID_PAGINATION", expected_status=400)


# ─────────────────────────────────────────────────────────────────────────────
# Corner/endpoints/fk_reverse_reach_batch_ingredient_usages_by_batch
# ─────────────────────────────────────────────────────────────────────────────

def test_batch_ingredient_usages_filter_by_batch(api):
    """PRD §2.5: "The collections in this system are flat siblings under the common
    prefix, linked to one another by foreign-key fields carried in request bodies
    (such as ... compounding_batch_id ...)."

    Design: Corner/endpoints/fk_reverse_reach_batch_ingredient_usages_by_batch
    """
    facility = create_facility("503B", clock=None)
    mfr = create_mfr(facility["id"], dosage_form="ORAL_SOLID",
                     default_bud_days_nonsterile=90, theoretical_yield_units=100,
                     anticipatory_max_units=500)
    lot = create_lot(facility["id"], initial_grams=50,
                     expiration_utc="2030-01-01T00:00:00.000Z")
    batch = create_draft_batch(facility["id"], mfr["id"], purpose="OFFICE_USE")
    usage = charge_usage(batch["id"], lot["id"], grams_used=10)

    data, meta = validate_paginated(
        api.list_batch_ingredient_usages(
            COMP, params={"compounding_batch_id": batch["id"]}))
    assert meta["total_count"] == 1
    assert any(row["id"] == usage["id"] for row in data)


# ─────────────────────────────────────────────────────────────────────────────
# Corner/rbac/compounding_pharmacist_cannot_release_batch
# ─────────────────────────────────────────────────────────────────────────────

def test_compounding_pharmacist_cannot_release_batch(api):
    """PRD §2.1: "When a role attempts an operation it is not permitted to perform,
    the request is rejected with ERR_INSUFFICIENT_PERMISSIONS." PRD §4 lists POST
    .../release as authorized for QualityAssurancePharmacist only.

    Design: Corner/rbac/compounding_pharmacist_cannot_release_batch
    """
    from test_helpers import (create_compiled_batch, add_passing_required_qc,
                              quarantine_batch, create_prescription, release_payload,
                              make_compounding_headers)
    facility = create_facility("503A", clock="2026-06-01T00:00:00.000Z")
    mfr = create_mfr(facility["id"], dosage_form="ORAL_SOLID",
                     default_bud_days_nonsterile=90, theoretical_yield_units=5,
                     anticipatory_max_units=500)
    lot = create_lot(facility["id"], initial_grams=50,
                     expiration_utc="2030-01-01T00:00:00.000Z")
    rx = create_prescription(facility["id"], mfr["id"], units_prescribed=5)
    batch = create_compiled_batch(
        facility["id"], mfr["id"], lot["id"], 5, purpose="PRESCRIPTION",
        batch_overrides={"prescription_id": rx["id"]}, compiler_id="comp-user-1")
    add_passing_required_qc(batch["id"], is_sterile=False)
    quarantine_batch(batch["id"])
    cur = get_success_data(api.get_batch(batch["id"], COMP))

    res = api.release_batch(batch["id"], release_payload(cur["version"]),
                            make_compounding_headers("comp-user-1"))
    validate_error(res, "ERR_INSUFFICIENT_PERMISSIONS", expected_status=403)
    after = validate_success(api.get_batch(batch["id"], QA), 200)
    assert after["status"] == "QUARANTINED"


# ─────────────────────────────────────────────────────────────────────────────
# Corner/rbac/dispensing_pharmacist_cannot_create_facility
# ─────────────────────────────────────────────────────────────────────────────

def test_dispensing_pharmacist_cannot_create_facility(api):
    """PRD §2.1: "When a role attempts an operation it is not permitted to perform,
    the request is rejected with ERR_INSUFFICIENT_PERMISSIONS." PRD §4 lists POST
    /facilities as authorized for SystemAdmin only.

    Design: Corner/rbac/dispensing_pharmacist_cannot_create_facility
    """
    res = api.create_facility(
        create_facility_payload(name="Sneaky", registration_type="503A",
                                state_code="CA"), DISP)
    validate_error(res, "ERR_INSUFFICIENT_PERMISSIONS", expected_status=403)


# ─────────────────────────────────────────────────────────────────────────────
# Corner/rbac/missing_user_context_header_returns_401
# ─────────────────────────────────────────────────────────────────────────────

def test_unknown_role_returns_401(api):
    """PRD §2.1: "If either header is absent, or if X-User-Role carries a value that
    is not one of the recognized roles, the request is rejected with
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER."

    Design: Corner/rbac/missing_user_context_header_returns_401
    """
    bogus = {"X-User-ID": "x", "X-User-Role": "BogusRole", "Content-Type": "application/json"}
    res = api.list_facilities(bogus)
    validate_error(res, "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", expected_status=401)


# ─────────────────────────────────────────────────────────────────────────────
# Corner/rbac/shared_environmental_log_by_both_pharmacists
# ─────────────────────────────────────────────────────────────────────────────

def test_environmental_log_shared_by_both_pharmacists(api):
    """PRD §3.4: "Cleanroom conditions are documented as Environmental Log readings,
    which a QualityAssurancePharmacist or a CompoundingPharmacist may record."

    Design: Corner/rbac/shared_environmental_log_by_both_pharmacists
    """
    facility = create_facility("503B", clock="2026-06-01T00:00:00.000Z")
    log1 = validate_success(
        api.create_environmental_log(
            create_environmental_log_payload(
                facility["id"], usp_chapter="USP_795", reading_type="ROOM_TEMP_C",
                measured_value=22, action_limit=25), COMP), 201)
    log2 = validate_success(
        api.create_environmental_log(
            create_environmental_log_payload(
                facility["id"], usp_chapter="USP_797", reading_type="SURFACE_CFU",
                measured_value=1, action_limit=3), QA), 201)
    assert log1["in_spec"] is True
    assert log2["in_spec"] is True
