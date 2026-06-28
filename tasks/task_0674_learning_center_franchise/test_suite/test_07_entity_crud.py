"""Entity CRUD corners: create defaults, not-found, required-field validation,
system-minted fields, and listing/pagination.

Queue B — Corner/entities.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId, NON_EXISTENT_UUID,
    set_clock, create_center_payload, assert_center,
    setup_operating_center_with_subject, create_family, create_student,
    make_franchise_admin_headers, make_center_director_headers,
)
from test_helpers import api_client as api

ADMIN = make_franchise_admin_headers()
DIRECTOR = make_center_director_headers()


def test_create_center_returns_201_with_defaults_applied():
    """PRD §3.1: "A freshly created center begins in `PROVISIONING` status with its
    `active_enrollment_count` at 0"
    PRD §3.1: "the `instructor_ratio_cap` (the most students one instructor may staff in
    a single session, defaulting to 6 ...), the one-time `enrollment_fee_cents` charged
    the first time a student enrolls (defaulting to 5000 ...), and the base
    `monthly_tuition_cents` per subject-enrollment before discounts (defaulting to 15000 ...)."

    Design: Corner/entities/create_center_returns_201_with_defaults_applied
    """
    set_clock("2026-05-01T00:00:00Z")
    resp = api.create_center({"name": "Solo Center", "territory_code": "TER-Z9"}, ADMIN)
    data = validate_success(resp, expected_status=201)
    assert_center(data)
    assert data["status"] == "PROVISIONING"
    assert data["instructor_ratio_cap"] == 6
    assert data["enrollment_fee_cents"] == 5000
    assert data["monthly_tuition_cents"] == 15000
    assert data["active_enrollment_count"] == 0


def test_get_center_not_found_returns_404():
    """PRD §2.8: "every resource referenced by the request ... must exist, or the
    request fails with `ERR_NOT_FOUND` (404), reporting the first missing reference
    encountered."

    Design: Corner/entities/get_center_not_found_returns_404
    """
    resp = api.get_center(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_center_missing_required_field_returns_invalid_request():
    """PRD §3.1: "Creating a center records its `name`, a `territory_code`, and three
    pricing knobs that default if omitted"
    PRD §2.8: "Request well-formedness is checked fourth: required fields must be present
    ... a violation yields `ERR_INVALID_REQUEST` (422)"

    Omitting the required `territory_code` -> ERR_INVALID_REQUEST.

    Design: Corner/entities/create_center_missing_required_field_returns_invalid_request
    """
    resp = api.create_center({"name": "No Territory"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_enrollment_computed_fields_system_minted_input_ignored():
    """PRD §3.3: "A new enrollment begins in `PLACEMENT_PENDING` status with its computed
    `monthly_rate_cents` at 0"
    PRD §2.4: "The `version` starts at its initial value when the resource is created"

    Design: Corner/entities/enrollment_computed_fields_system_minted_input_ignored
    """
    center, _ag, subject, _levels = setup_operating_center_with_subject(num_levels=1)
    family = create_family(center["id"])
    student = create_student(family["id"])
    resp = api.create_enrollment(
        {"center_id": center["id"], "student_id": student["id"],
         "subject_id": subject["id"], "diagnostic_raw_score": 40}, DIRECTOR)
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "PLACEMENT_PENDING"
    assert data["monthly_rate_cents"] == 0
    assert data["version"] == 1


def test_list_centers_pagination_envelope():
    """PRD §2.3: "The `limit` parameter caps how many items a response returns ... Every
    list response carries the pagination bookkeeping inside the envelope's `meta`
    object: `limit`, `offset`, `total_count`, and `has_more`."

    Two centers exist; a limit=1 page returns one item, total_count 2, has_more true.

    Design: Corner/entities/list_centers_pagination_envelope
    """
    set_clock("2026-05-01T00:00:00Z")
    validate_success(api.create_center(create_center_payload(name="CL1"), ADMIN), expected_status=201)
    validate_success(api.create_center(create_center_payload(name="CL2"), ADMIN), expected_status=201)
    resp = api.list_centers(ADMIN, {"limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1
