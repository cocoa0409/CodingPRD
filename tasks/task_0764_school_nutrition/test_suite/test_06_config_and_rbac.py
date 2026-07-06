"""District configuration surface, listing/pagination, FK integrity, and RBAC."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, NON_EXISTENT_UUID,
    create_site, create_student, create_site_payload,
    TEST_USERS, NO_ROLE_HEADERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]
CAFETERIA = TEST_USERS["cafeteria_manager_headers"]
CLERK = TEST_USERS["pos_clerk_headers"]


def test_create_site_returns_common_fields_and_envelope(api):
    """PRD §2.4: "The `version` is an integer that starts at 1 (or the initial value assigned at creation) and increments by one on every mutation of the resource; it is the value used for optimistic concurrency control where that applies."
    PRD §3.1: "The site also exposes a computed `negative_balance_count`, initialized to 0 at creation, holding the number of that site's students currently in the `NEGATIVE` posture".
    PRD §2.2: "The `response_type` is either "object" for a single resource or "array" for a list of resources."

    Design: Corner/entities/create_site_returns_all_fields_and_envelope
    """
    resp = api.create_site(create_site_payload(name="Envelope School", site_code="ENV-1"), ADMIN)
    data = validate_success(resp, 201)
    body = resp.json()
    assert body["response_type"] == "object"
    assert body["meta"].get("api_request_id"), "meta.api_request_id must be present"
    assert data["version"] == 1, f"version must start at 1, got {data['version']}"
    assert data["negative_balance_count"] == 0, f"got {data['negative_balance_count']}"


def test_get_nonexistent_student_returns_not_found(api):
    """PRD §2.5: "existence — every path `id` and every foreign-key reference carried in the request body resolves to a real resource, validated left-to-right in the order they appear, else `ERR_NOT_FOUND` (404)".

    Design: Corner/entities/get_student_nonexistent_returns_not_found
    """
    resp = api.get_student(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_site_missing_site_code_returns_validation(api):
    """PRD §3.1: "A **school site** is created with a `name` and a `site_code`, the latter unique across all sites."
    PRD §2.5: "body shape — required fields present, enum values legal, numeric types and ranges valid, and any pagination `limit` within 1 to 100, else `ERR_VALIDATION` (400)."

    Design: Corner/entities/create_site_missing_required_field_returns_validation
    """
    resp = api.create_site({"name": "No Code"}, ADMIN)  # site_code omitted
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_list_students_returns_array_with_pagination_meta(api):
    """PRD §2.3: "Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope."

    Design: Corner/entities/list_students_pagination_shape
    """
    site = create_site(api)
    create_student(api, site["id"], first_name="P", last_name="One", grade="GRADES_K_5")

    resp = api.list_students(ADMIN, params={"site_id": site["id"], "limit": 10, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1, f"expected total_count 1, got {meta['total_count']}"
    assert meta["has_more"] is False, f"expected has_more False, got {meta['has_more']}"
    assert len(data) == 1


def test_production_with_unknown_menu_cycle_returns_not_found(api):
    """PRD §2.9: "A meal transaction, for example, that names a `site_id`, a `student_id`, and a `production_record_id` is checked in that order."
    PRD §2.5: "existence — every path `id` and every foreign-key reference carried in the request body resolves to a real resource, validated left-to-right in the order they appear, else `ERR_NOT_FOUND` (404)".

    Design: Corner/endpoints/production_create_unknown_menu_returns_not_found
    """
    site = create_site(api)
    resp = api.create_production_record(
        {"site_id": site["id"], "menu_cycle_id": NON_EXISTENT_UUID,
         "service_date": "2026-04-15", "meal_type": "LUNCH", "planned_qty": 100}, CAFETERIA)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_posclerk_creating_site_is_forbidden(api):
    """PRD §2.1: "If the role is recognized but is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/rbac_posclerk_create_site_forbidden
    """
    resp = api.create_site(create_site_payload(name="X", site_code="X-1"), CLERK)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


def test_request_without_recognized_role_is_unauthenticated(api):
    """PRD §2.1: "If `X-User-Role` is missing or is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/rbac_missing_role_unauthenticated
    """
    resp = api.create_site(create_site_payload(name="X", site_code="X-2"), NO_ROLE_HEADERS)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)
