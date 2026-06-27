"""Member & waiver CRUD, computed fields, required-field and uniqueness
validation, the immutable-waiver shape, pagination, and duplicate-waiver error.

All instances here come from the corner-design entities/errors sections.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    assert_member, assert_waiver,
    create_member, create_waiver, set_clock,
    NONEXISTENT_UUID, TEST_USERS,
)

FD = TEST_USERS["frontdesk_headers"]


# ─── Member creation & computed fields ────────────────────────────────────
def test_create_member_returns_201_with_defaults(api):
    """PRD §3.1: "On creation the member's status is set to ACTIVE (the only other
    value being DEACTIVATED), the wallet_credit_cents balance starts at 0, and the
    system derives is_youth from the supplied date_of_birth measured against the
    logical clock at creation time: a member is a youth when their age in
    completed years as of the created_at date is under 18."

    Design: Corner/entities/create_member_returns_201_with_all_fields
    """
    set_clock("2026-06-01T00:00:00Z")
    member = validate_success(api.create_member({
        "full_name": "New Person", "email": "new-person@x.com",
        "date_of_birth": "1990-01-01",
    }, FD), 201)
    assert_member(member)
    assert member["status"] == "ACTIVE"
    assert member["wallet_credit_cents"] == 0
    assert member["is_youth"] is False


def test_member_is_youth_true_for_minor(api):
    """PRD §3.1: "the system derives is_youth from the supplied date_of_birth
    measured against the logical clock at creation time: a member is a youth when
    their age in completed years as of the created_at date is under 18."

    Design: Corner/entities/member_is_youth_true_for_minor_dob
    """
    set_clock("2026-06-01T00:00:00Z")
    member = validate_success(api.create_member({
        "full_name": "Young One", "email": "young-one@x.com",
        "date_of_birth": "2010-06-01",  # age 16 at 2026-06-01
    }, FD), 201)
    assert member["is_youth"] is True


def test_get_member_not_found(api):
    """PRD §2.8: "Any referenced resource that does not exist — whether it is a
    path id or a body foreign key — yields ERR_NOT_FOUND (HTTP 404)."

    Design: Corner/entities/get_member_not_found_returns_404
    """
    res = api.get_member(NONEXISTENT_UUID, FD)
    validate_error(res, "ERR_NOT_FOUND")


def test_create_member_missing_email_rejected(api):
    """PRD §3.1: "Front-desk staff register a member by supplying a full_name, an
    email, and a date_of_birth."
    PRD §2.9: "well-formedness of the request body — required fields present, enum
    values valid, and numeric ranges respected — yielding ERR_INVALID_REQUEST"

    Design: Corner/entities/create_member_missing_required_field_returns_invalid_request
    """
    res = api.create_member({
        "full_name": "No Email", "date_of_birth": "1990-01-01",
    }, FD)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_duplicate_member_email_rejected(api):
    """PRD §3.1: "The email must be unique across all members; an attempt to
    register a second member with an email already on file is rejected with
    ERR_DUPLICATE_EMAIL (HTTP 409)."

    Design: Corner/entities/duplicate_member_email_returns_conflict
    """
    set_clock("2026-06-01T00:00:00Z")
    validate_success(api.create_member({
        "full_name": "First", "email": "dup@x.com", "date_of_birth": "1990-01-01",
    }, FD), 201)
    res = api.create_member({
        "full_name": "Second", "email": "dup@x.com", "date_of_birth": "1991-01-01",
    }, FD)
    validate_error(res, "ERR_DUPLICATE_EMAIL")


# ─── Waiver shape & guardian rule ─────────────────────────────────────────
def test_waiver_carries_no_version_field(api):
    """PRD §2.4: "they have no `updated_at` and no `version`: the `Waiver` and the
    `Enrollment`."
    PRD §3.1: "Waivers carry only an `id` and a `created_at` and no version."

    Design: Corner/entities/waiver_immutable_no_version_field
    """
    set_clock("2026-06-01T00:00:00Z")
    member = create_member()
    waiver = create_waiver(member["id"])
    fetched = validate_success(api.get_waiver(waiver["id"], FD), 200)
    assert fetched["status"] == "VALID"
    assert "version" not in fetched, "Waiver must not carry a version field"
    assert "updated_at" not in fetched, "Waiver must not carry an updated_at field"


def test_youth_waiver_without_guardian_rejected(api):
    """PRD §3.1: "If the signer is a youth, a minor_guardian_name must be supplied;
    if the signer is not a youth, minor_guardian_name must be omitted or null.
    Violating that guardian rule is a malformed body and is rejected with
    ERR_INVALID_REQUEST."

    Design: Corner/entities/waiver_minor_requires_guardian_name
    """
    set_clock("2026-06-01T00:00:00Z")
    member = create_member(date_of_birth="2012-06-01")  # youth
    res = api.create_waiver({"member_id": member["id"]}, FD)
    validate_error(res, "ERR_INVALID_REQUEST")


# ─── Pagination ───────────────────────────────────────────────────────────
def test_list_members_pagination_meta(api):
    """PRD §2.3: "The meta block of a list response includes limit, offset,
    total_count, and has_more, where total_count is the number of records
    matching the filter before pagination and has_more is true when records remain
    beyond the current page."

    Design: Corner/entities/list_members_pagination_envelope
    """
    set_clock("2026-06-01T00:00:00Z")
    create_member(email="l1@x.com")
    create_member(email="l2@x.com")
    data, meta = validate_paginated(api.list_members(FD, params={"limit": 1, "offset": 0}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


# ─── Duplicate waiver while valid ─────────────────────────────────────────
def test_duplicate_valid_waiver_rejected(api):
    """PRD §3.1: "A member may hold only one valid waiver at a time: signing a
    second waiver while an existing one is still VALID is rejected with
    ERR_DUPLICATE_WAIVER (HTTP 409)."

    Design: Corner/errors/error_duplicate_waiver_while_valid
    """
    set_clock("2026-06-01T00:00:00Z")
    member = create_member()
    create_waiver(member["id"])
    res = api.create_waiver({"member_id": member["id"]}, FD)
    validate_error(res, "ERR_DUPLICATE_WAIVER")
