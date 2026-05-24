"""CRUD and input validation tests.

Covers Corner-design Section 1 (entities) — registration, retrieval,
listing, not-found, required-field, default-value, computed-field,
system-field, type-constraint, parent-relationship, uniqueness, and
foreign-key claims.
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    assert_applicant, assert_application,
    create_applicant_payload, create_application_payload,
    setup_clock_and_school, register_applicant, create_school,
    create_application,
    make_applicant_headers, admin_headers,
    NON_EXISTENT_UUID,
)


# ─── Section 1 / entity_applicant_register_returns_201_with_all_fields ──

def test_register_applicant_returns_201_with_full_profile(api):
    """PRD §3.1: "A new applicant joins the platform through the public
    self-registration capability, which takes the applicant's email,
    full_name, gpa, and optionally sat_total."
    PRD §3.1: "The newly created applicant starts with profile_status of DRAFT."

    Design: Corner/entities/entity_applicant_register_returns_201_with_all_fields
    """
    payload = create_applicant_payload(
        email="creation@example.com",
        full_name="Creation Test",
        gpa=3.5,
        sat_total=1300,
    )
    res = api.register_applicant(payload)
    applicant = validate_success(res, 201)
    assert_applicant(applicant)
    assert applicant["email"] == "creation@example.com"
    assert applicant["full_name"] == "Creation Test"
    assert applicant["profile_status"] == "DRAFT"
    assert applicant["version"] == 1


# ─── entity_applicant_get_by_id_returns_stored_record ───────────────────

def test_get_applicant_returns_stored_record(api):
    """PRD §4 / §3.8: "the applicant read ... return[s] the single targeted
    row with no additional query parameters."

    Design: Corner/entities/entity_applicant_get_by_id_returns_stored_record
    """
    applicant = register_applicant(
        email="ret@example.com", full_name="Ret Test", gpa=3.3, sat_total=1200)
    res = api.get_applicant(applicant["id"],
                            make_applicant_headers(applicant["id"]))
    fetched = validate_success(res, 200)
    assert fetched["id"] == applicant["id"]
    assert fetched["email"] == "ret@example.com"
    assert fetched["full_name"] == "Ret Test"


# ─── entity_application_list_paginated_with_total_and_has_more ──────────

def test_list_applications_pagination_total_count_and_has_more(api):
    """PRD §2.3: "The meta object on a list response carries limit, offset,
    total_count, and has_more so clients can determine whether to request
    a subsequent page."

    Design: Corner/entities/entity_application_list_paginated_with_total_and_has_more
    """
    setup_clock_and_school()  # advances test clock so applications can be created
    schools = [create_school() for _ in range(3)]
    applicant = register_applicant()
    for school in schools:
        create_application(applicant["id"], school["id"], "REGULAR")

    res = api.list_applications(make_applicant_headers(applicant["id"]),
                                params={"limit": 2, "offset": 0})
    data, meta = validate_paginated(res)
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert len(data) == 2


# ─── entity_applicant_not_found_returns_resource_not_found ──────────────

def test_get_applicant_unknown_uuid_returns_resource_not_found(api):
    """PRD §2.5: "The first identifier that does not resolve to an existing
    row produces an immediate ERR_RESOURCE_NOT_FOUND (HTTP 404)."

    Design: Corner/entities/entity_applicant_not_found_returns_resource_not_found
    """
    acting = register_applicant()
    res = api.get_applicant(NON_EXISTENT_UUID,
                            make_applicant_headers(acting["id"]))
    validate_error(res, "ERR_RESOURCE_NOT_FOUND")


# ─── entity_applicant_register_missing_required_field_rejected ──────────

def test_register_applicant_missing_required_gpa_rejected(api):
    """PRD §2.5: "Request-body field validation — required fields present,
    types correct, enum members within their declared set, numeric ranges
    respected — is ERR_INVALID_REQUEST (HTTP 422)."

    Design: Corner/entities/entity_applicant_register_missing_required_field_rejected
    """
    res = api.register_applicant({"email": "miss@example.com",
                                  "full_name": "Missing GPA"})
    validate_error(res, "ERR_INVALID_REQUEST")


# ─── entity_applicant_register_default_sat_total_null ───────────────────

def test_register_applicant_default_sat_total_null(api):
    """PRD §3.1: "the applicant's email, full_name, gpa, and optionally
    sat_total. ... the sat_total is either null or an integer from 400
    through 1600 inclusive."

    Design: Corner/entities/entity_applicant_register_default_sat_total_null
    """
    res = api.register_applicant({"email": "default-sat@example.com",
                                  "full_name": "Default Test",
                                  "gpa": 3.0})
    applicant = validate_success(res, 201)
    assert applicant["sat_total"] is None


# ─── entity_applicant_profile_status_computed_starts_draft ──────────────

def test_register_applicant_profile_status_computed_starts_draft(api):
    """PRD §3.1: "The newly created applicant starts with profile_status
    of DRAFT."

    Design: Corner/entities/entity_applicant_profile_status_computed_starts_draft
    """
    # Send profile_status=READY in the payload — must be ignored since it is
    # a computed field (PRD §3.1 — flips only when both conditions hold).
    res = api.register_applicant({"email": "ps@example.com",
                                  "full_name": "PS Test",
                                  "gpa": 3.2,
                                  "sat_total": 1200,
                                  "profile_status": "READY"})
    applicant = validate_success(res, 201)
    assert applicant["profile_status"] == "DRAFT"


# ─── entity_application_system_field_id_and_timestamps_minted ───────────

def test_create_application_system_fields_minted(api):
    """PRD §2.4: "Every entity in the system ... exposes a server-minted id
    formatted as a UUID with no type prefix, and a created_at timestamp
    formatted as an ISO 8601 UTC instant with three fractional digits."

    Design: Corner/entities/entity_application_system_field_id_and_timestamps_minted
    """
    school = setup_clock_and_school()
    applicant = register_applicant()

    payload = create_application_payload(applicant["id"], school["id"], "REGULAR")
    # Try to inject id from the client — must be ignored.
    payload["id"] = "deadbeef-dead-4dea-8dea-deaddeaddead"
    res = api.create_application(payload, make_applicant_headers(applicant["id"]))
    app = validate_success(res, 201)
    assert app["id"] != "deadbeef-dead-4dea-8dea-deaddeaddead", \
        "server must mint its own id, not echo client-supplied id"
    assert_application(app)


# ─── entity_application_invalid_plan_enum_rejected ──────────────────────

def test_create_application_invalid_plan_enum_rejected(api):
    """PRD §3.4: "the chosen plan, drawn from the set EARLY_DECISION,
    EARLY_ACTION, REGULAR, or ROLLING."
    PRD §2.5: "enum members within their declared set ... is
    ERR_INVALID_REQUEST (HTTP 422)."

    Design: Corner/entities/entity_application_invalid_plan_enum_rejected
    """
    school = setup_clock_and_school()
    applicant = register_applicant()
    res = api.create_application(
        {"applicant_id": applicant["id"], "school_id": school["id"],
         "plan": "EARLY_BIRD"},
        make_applicant_headers(applicant["id"]))
    validate_error(res, "ERR_INVALID_REQUEST")


# ─── entity_application_gpa_out_of_range_rejected ───────────────────────

def test_register_applicant_gpa_above_range_rejected(api):
    """PRD §3.1: "the gpa must be in the range from 0.0 through 4.0
    inclusive."
    PRD §2.5: "numeric ranges respected — is ERR_INVALID_REQUEST (HTTP 422)."

    Design: Corner/entities/entity_application_gpa_out_of_range_rejected
    """
    res = api.register_applicant({"email": "gpa@example.com",
                                  "full_name": "GPA OOR",
                                  "gpa": 4.5})
    validate_error(res, "ERR_INVALID_REQUEST")


# ─── entity_application_rolling_plan_requires_school_rolling_open ──────

def test_create_application_rolling_plan_requires_school_rolling_open(api):
    """PRD §3.4: "A plan of ROLLING is permitted only when the target
    school's rolling_open is true."

    Design: Corner/entities/entity_application_rolling_plan_requires_school_rolling_open
    """
    school = setup_clock_and_school(rolling_open=False)
    applicant = register_applicant()
    res = api.create_application(
        {"applicant_id": applicant["id"], "school_id": school["id"],
         "plan": "ROLLING"},
        make_applicant_headers(applicant["id"]))
    validate_error(res, "ERR_INVALID_REQUEST")


# ─── entity_applicant_email_unique_lowercase_normalized ─────────────────

def test_register_applicant_email_unique_case_insensitive(api):
    """PRD §3.1: "The email is globally unique and is normalized to
    lowercase before the uniqueness check."

    Design: Corner/entities/entity_applicant_email_unique_lowercase_normalized
    """
    validate_success(api.register_applicant(
        {"email": "dup@example.com", "full_name": "First", "gpa": 3.0}), 201)
    res = api.register_applicant(
        {"email": "DUP@EXAMPLE.COM", "full_name": "Second", "gpa": 3.1})
    validate_error(res, "ERR_DUPLICATE_RESOURCE")


# ─── entity_topology_flat_fk_validation_application_school_id ───────────

def test_create_application_with_nonexistent_school_id_returns_fk_not_found(api):
    """PRD §2.4: "When a foreign-key field in a request body does not
    resolve to an existing row, the server rejects with ERR_FK_NOT_FOUND
    (HTTP 404)."

    Design: Corner/entities/entity_topology_flat_fk_validation_application_school_id
    """
    applicant = register_applicant()
    res = api.create_application(
        {"applicant_id": applicant["id"],
         "school_id": "11111111-1111-4111-8111-111111111111",
         "plan": "REGULAR"},
        make_applicant_headers(applicant["id"]))
    validate_error(res, "ERR_FK_NOT_FOUND")


# ─── entity_application_applicant_school_unique_pair ────────────────────

def test_create_application_duplicate_applicant_school_pair_rejected(api):
    """PRD §3.4: "The pair (applicant_id, school_id) is unique — an
    applicant cannot create two applications to the same school."

    Design: Corner/entities/entity_application_applicant_school_unique_pair
    """
    school = setup_clock_and_school()
    applicant = register_applicant()
    create_application(applicant["id"], school["id"], "REGULAR")
    res = api.create_application(
        create_application_payload(applicant["id"], school["id"], "EARLY_ACTION"),
        make_applicant_headers(applicant["id"]))
    validate_error(res, "ERR_DUPLICATE_RESOURCE")
