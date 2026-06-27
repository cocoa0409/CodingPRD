"""Computed fields, CRUD basics (defaults, required fields, not-found,
pagination, reverse lookup), RBAC denials, and the invoice-pay OCC check.

Corner queue (B): entities + rbac + cross_cutting_complexity_layers instances.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    NON_EXISTENT_UUID,
    TEST_USERS,
    make_parent_headers,
    make_instructor_headers,
    set_clock,
    create_location,
    create_level,
    create_instructor,
    create_class_session,
    open_session,
    create_parent,
    create_student,
    setup_parent_with_student,
    create_active_enrollment,
    create_level_payload,
    create_invoice,
    issue_invoice,
)

ADMIN = TEST_USERS["school_admin_headers"]
BILLING = TEST_USERS["billing_admin_headers"]


# ─── Computed fields ───────────────────────────────────────────────────────
def test_student_age_months_computed_against_clock(api):
    """PRD §2.4: "A student's `age_months` is computed on read as the whole number
    of months elapsed from their birthdate to the current logical instant, taking
    the floor."

    A student born 2021-01-01 read with the clock at 2026-01-01 returns
    age_months == 60 (exactly 5 years).

    Design: Corner/entities/student_age_months_computed_against_clock
    """
    set_clock("2026-01-01T00:00:00Z")
    level = create_level(min_age_months=0, max_age_months=200)
    parent, student = setup_parent_with_student(
        level["id"], student_overrides={"birthdate": "2021-01-01T00:00:00Z"}
    )
    headers = make_parent_headers(parent["id"])
    read = validate_success(api.get_student(student["id"], headers), 200)
    assert read["age_months"] == 60, f"expected 60, got {read['age_months']}"


def test_create_location_default_status_open(api):
    """PRD §3.1: "A location begins life in `OPEN` status and is one of `OPEN` or
    `CLOSED`."

    POST /locations without a status returns status == OPEN.

    Design: Corner/entities/create_location_default_status_open
    """
    res = api.create_location({"name": "Main Pool"}, ADMIN)
    location = validate_success(res, 201)
    assert location["status"] == "OPEN"


def test_get_class_session_not_found(api):
    """PRD §2.6: "a missing class session `ERR_CLASS_SESSION_NOT_FOUND`"

    GET /class-sessions/{id} with a well-formed non-existent UUID returns
    ERR_CLASS_SESSION_NOT_FOUND.

    Design: Corner/entities/get_class_session_nonexistent_returns_not_found
    """
    res = api.get_class_session(NON_EXISTENT_UUID, ADMIN)
    validate_error(res, "ERR_CLASS_SESSION_NOT_FOUND")


def test_create_level_missing_required_field_rejected(api):
    """PRD §2.10: "required fields, types, and enum validity are checked
    (`ERR_INVALID_REQUEST`)"

    POST /levels missing monthly_tuition_cents (a required input field) is
    rejected ERR_INVALID_REQUEST.

    Design: Corner/entities/create_level_missing_required_field_returns_invalid_request
    """
    payload = create_level_payload()
    del payload["monthly_tuition_cents"]
    res = api.create_level(payload, ADMIN)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_list_class_sessions_pagination_envelope(api):
    """PRD §2.3: "Every list response surfaces `limit`, `offset`, `total_count`,
    and `has_more` inside the `meta` object: `total_count` is the count of all
    records matching the filter before the page window is applied, and `has_more`
    is true when records remain beyond the current window."

    With an empty DB, GET /class-sessions returns a well-formed paginated
    envelope with total_count 0 and has_more false.

    Design: Corner/entities/list_class_sessions_pagination_envelope
    """
    data, meta = validate_paginated(api.list_class_sessions(ADMIN))
    assert meta["total_count"] == 0, f"expected 0, got {meta['total_count']}"
    assert meta["has_more"] is False


def test_list_parent_students_reverse_lookup(api):
    """PRD §3.2: "the student records its owning `parent_id` automatically."

    GET /parents/{id}/students returns the parent's students; after one add the
    list has total_count 1 (the sub-resource reverse lookup for the student's
    owning parent_id).

    Design: Corner/entities/fk_reverse_lookup_students_by_parent_subresource
    """
    level = create_level(min_age_months=0, max_age_months=200)
    parent, student = setup_parent_with_student(level["id"])
    headers = make_parent_headers(parent["id"])
    data, meta = validate_paginated(api.list_parent_students(parent["id"], headers))
    assert meta["total_count"] == 1, f"expected 1, got {meta['total_count']}"


# ─── RBAC ──────────────────────────────────────────────────────────────────
def test_parent_cannot_create_level(api):
    """PRD §2.1: "When the headers are present but the named role is not permitted
    to perform the requested operation, the request is rejected with
    `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

    A Parent calling POST /levels (a SchoolAdmin-only operation) is rejected
    ERR_INSUFFICIENT_PERMISSIONS.

    Design: Corner/rbac/parent_cannot_create_level
    """
    parent = create_parent()
    headers = make_parent_headers(parent["id"])
    res = api.create_level(create_level_payload(), headers)
    validate_error(res, "ERR_INSUFFICIENT_PERMISSIONS")


def test_instructor_cannot_pay_invoice(api):
    """PRD §2.1: "When the headers are present but the named role is not permitted
    to perform the requested operation, the request is rejected with
    `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

    An Instructor calling POST /invoices/{id}/pay (a BillingAdmin-only operation)
    is rejected ERR_INSUFFICIENT_PERMISSIONS.

    Design: Corner/rbac/instructor_cannot_pay_invoice
    """
    set_clock("2026-01-05T00:00:00Z")
    location = create_location()
    level = create_level(min_age_months=0, max_age_months=200,
                         max_students_per_instructor=4)
    instructor = create_instructor(certified_level_ids=[level["id"]])
    session = create_class_session(location["id"], level["id"], instructor["id"])
    session = open_session(session["id"])
    parent, student = setup_parent_with_student(level["id"])
    create_active_enrollment(parent, student, session)
    inv = create_invoice(parent["id"], "2026-01-01T00:00:00Z",
                         "2026-02-01T00:00:00Z", "2026-02-15T00:00:00Z",
                         variant="FORWARD_LOOKING")
    issued = issue_invoice(inv["id"])
    instr_headers = make_instructor_headers(instructor["id"])
    res = api.pay_invoice(inv["id"], {"expected_invoice_version": issued["version"]},
                          instr_headers)
    validate_error(res, "ERR_INSUFFICIENT_PERMISSIONS")


def test_parent_cannot_withdraw_other_parents_student(api):
    """PRD §2.1: "Any entity-backed principal acting on a resource it does not own
    is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Parent P2 calling POST /students/{id}/withdraw on Parent P1's student is
    rejected ERR_NOT_RESOURCE_OWNER.

    Design: Corner/rbac/parent_cannot_withdraw_other_parents_student
    """
    set_clock("2026-01-05T00:00:00Z")
    level = create_level(min_age_months=0, max_age_months=200)
    p1 = create_parent(full_name="P1", email="p1@x.com")
    s1 = create_student(p1, level["id"], full_name="S1")
    p2 = create_parent(full_name="P2", email="p2@x.com")
    headers2 = make_parent_headers(p2["id"])
    res = api.withdraw_student(s1["id"], headers2)
    validate_error(res, "ERR_NOT_RESOURCE_OWNER")


# ─── Optimistic concurrency: invoice pay stale version ─────────────────────
def test_pay_invoice_stale_version_rejected(api):
    """PRD §2.9: "A request that pays an invoice must carry
    `expected_invoice_version`, holding the `version` of the target invoice the
    client last observed."
    PRD §2.9: "If that value does not match the invoice's current `version` —
    because another writer has already voided or settled the invoice, legitimately
    superseding the client's view — the payment is rejected with
    `ERR_STALE_VERSION` (HTTP 412)"

    Paying an ISSUED invoice with a stale expected_invoice_version (one less than
    current) is rejected ERR_STALE_VERSION.

    Design: Corner/cross_cutting_complexity_layers/occ_pay_invoice_stale_version_conflict
    """
    set_clock("2026-01-05T00:00:00Z")
    location = create_location()
    level = create_level(min_age_months=0, max_age_months=200,
                         max_students_per_instructor=4)
    instructor = create_instructor(certified_level_ids=[level["id"]])
    session = create_class_session(location["id"], level["id"], instructor["id"])
    session = open_session(session["id"])
    parent, student = setup_parent_with_student(level["id"])
    create_active_enrollment(parent, student, session)
    inv = create_invoice(parent["id"], "2026-01-01T00:00:00Z",
                         "2026-02-01T00:00:00Z", "2026-02-15T00:00:00Z",
                         variant="FORWARD_LOOKING")
    issued = issue_invoice(inv["id"])
    stale_version = issued["version"] - 1
    res = api.pay_invoice(inv["id"], {"expected_invoice_version": stale_version},
                          BILLING)
    validate_error(res, "ERR_STALE_VERSION")
