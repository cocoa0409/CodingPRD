"""CRUD input validation, role-based and ownership access control, and paginated
listing.
"""
from test_helpers import (
    validate_error, validate_paginated,
    create_property_payload, create_property,
    create_paid_approved_application, open_application, schedule_inspection,
    make_applicant_headers,
    NON_EXISTENT_UUID,
    TEST_USERS,
)

FIRE_MARSHAL = TEST_USERS["fire_marshal_headers"]
INSPECTOR = TEST_USERS["inspector_headers"]


# ─── Corner/entities/corner_get_property_not_found ─────────────────────────
def test_get_unknown_property_returns_not_found(api):
    """PRD §2.7: "the first identifier that fails to resolve determines the error — for
    example, a missing property yields `ERR_PROPERTY_NOT_FOUND`"

    Design: Corner/entities/corner_get_property_not_found
    """
    res = api.get_property(NON_EXISTENT_UUID, FIRE_MARSHAL)
    validate_error(res, "ERR_PROPERTY_NOT_FOUND", expected_status=404)


# ─── Corner/entities/corner_create_property_missing_required_returns_400 ────
def test_create_property_missing_required_field_rejected(api):
    """PRD §2.9: "Body well-formedness — required body fields are present and correctly
    typed (`ERR_VALIDATION`, 400)."

    Design: Corner/entities/corner_create_property_missing_required_returns_400
    """
    payload = create_property_payload(address="21 U St")
    del payload["occupancy_classification"]
    res = api.create_property(payload, FIRE_MARSHAL)
    validate_error(res, "ERR_VALIDATION", expected_status=400)


# ─── Corner/entities/corner_create_property_invalid_enum_returns_422 ───────
def test_create_property_invalid_enum_rejected(api):
    """PRD §2.9: "Enum membership — enum-valued body fields carry a declared member
    (`ERR_INVALID_ENUM`, 422)."

    Design: Corner/entities/corner_create_property_invalid_enum_returns_422
    """
    payload = create_property_payload(address="22 V St", occupancy_classification="MALL")
    res = api.create_property(payload, FIRE_MARSHAL)
    validate_error(res, "ERR_INVALID_ENUM", expected_status=422)


# ─── Corner/rbac/corner_inspector_cannot_issue_permit_returns_403 ──────────
def test_inspector_cannot_issue_permit(api):
    """PRD §2.1: "When an authenticated user attempts an operation their role is not
    permitted to perform, the request is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/corner_inspector_cannot_issue_permit_returns_403
    """
    _prop, app, _pr = create_paid_approved_application(applicant_user_id="app-13", amount_cents=20640)
    res = api.create_permit({"application_id": app["id"]}, INSPECTOR)
    validate_error(res, "ERR_UNAUTHORIZED", expected_status=403)


# ─── Corner/rbac/corner_applicant_cannot_submit_others_application_returns_403
def test_applicant_cannot_submit_other_applicants_application(api):
    """PRD §2.1: "for the applicant-owned actions (submitting an application, paying a
    fee, and resubmitting corrections) the server compares the caller's `X-User-ID`
    against the target application's stored `applicant_user_id`. A mismatch is rejected
    with `ERR_NOT_OWNER`."

    Design: Corner/rbac/corner_applicant_cannot_submit_others_application_returns_403
    """
    prop = create_property(address="36 JJ St")
    app = open_application(prop["id"], applicant_user_id="owner-x")
    res = api.submit_permit_application(app["id"], make_applicant_headers("intruder"))
    validate_error(res, "ERR_NOT_OWNER", expected_status=403)


# ─── Corner/endpoints/corner_list_inspections_pagination ───────────────────
def test_list_inspections_pagination_meta(api):
    """PRD §2.3: "The `limit` parameter bounds the number of items returned" and
    "Every list response carries the pagination bookkeeping in the `meta` object of the
    envelope: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/endpoints/corner_list_inspections_pagination
    """
    prop = create_property(address="33 GG St")
    schedule_inspection(prop["id"], scheduled_date="2026-03-05T00:00:00Z")
    schedule_inspection(prop["id"], scheduled_date="2026-04-05T00:00:00Z")
    data, meta = validate_paginated(
        api.list_inspections(INSPECTOR, params={"property_id": prop["id"], "limit": 1, "offset": 0}))
    assert len(data) == 1, f"limit=1 must return a single item, got {len(data)}"
    assert meta["total_count"] == 2, f"total_count expected 2, got {meta['total_count']}"
    assert meta["has_more"] is True
