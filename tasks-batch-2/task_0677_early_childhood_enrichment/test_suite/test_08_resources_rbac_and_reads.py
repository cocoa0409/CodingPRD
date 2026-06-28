"""Resource creation/validation, RBAC denials/ownership, listing/pagination,
computed reads, immediate consistency, and invalid-state on invoice pay.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    TEST_USERS, ApiErrorId, NON_EXISTENT_UUID, build_user_headers,
    set_clock, create_program, create_room, create_instructor, create_session,
    create_active_membership, create_family, create_child, enroll_child,
    renew_membership,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx

ADMIN = TEST_USERS["studio_admin_headers"]
STAFF = TEST_USERS["front_desk_headers"]


# -------------------------------------------------------------------------
# Entities
# -------------------------------------------------------------------------
def test_create_family_returns_201_with_system_fields(api):
    """PRD §3.1: "A family account is registered by front-desk or admin staff with
    an account_email ... and a primary_contact_name. Each family exposes a computed
    child_count: the number of that family's Child rows whose status is
    ENROLLED_ELIGIBLE."
    PRD §2.4: "a version (an integer that begins at its initial value and increments
    by one on every mutation"

    Creating a family returns 201 with child_count 0 and version 1.

    Design: Corner/entities/create_family_returns_201_with_system_fields
    """
    resp = api.create_family(
        f.create_family_payload(account_email="new@x.com", primary_contact_name="New"), ADMIN,
    )
    family = validate_success(resp, 201)
    assert family["child_count"] == 0
    assert family["version"] == 1


def test_create_child_missing_birth_date_returns_invalid_request(api):
    """PRD §3.1: "A child is added under a family by supplying that family's
    identifier in the family_id field, along with the child's full_name and
    birth_date"
    PRD §2.12: "request-body well-formedness — required fields present and field
    types and enums valid"

    Creating a child without birth_date (a required input field) returns
    ERR_INVALID_REQUEST 400.

    Design: Corner/entities/create_child_missing_birth_date_returns_invalid_request
    """
    family = create_family()
    resp = api.create_child({"family_id": family["id"], "full_name": "NoDob"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_get_nonexistent_membership_returns_not_found(api):
    """PRD §2.5: "When a path contains a resource identifier, the system validates
    referenced resources left to right and rejects the first missing one with
    ERR_NOT_FOUND (HTTP 404)."

    GET on an unknown membership id returns ERR_NOT_FOUND 404.

    Design: Corner/entities/get_nonexistent_membership_returns_not_found
    """
    resp = api.get_membership(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_family_child_count_recomputed_on_child_add(api):
    """PRD §3.1: "Each family exposes a computed child_count: the number of that
    family's Child rows whose status is ENROLLED_ELIGIBLE."
    PRD §2.6: "the computed fields Family.child_count ... always reflect the live
    state the instant a request completes."

    After adding two ENROLLED_ELIGIBLE children, the family's child_count reads 2.

    Design: Corner/entities/family_child_count_recomputed_on_child_add
    """
    family = create_family()
    create_child(family["id"], full_name="A", birth_date="2024-01-01")
    create_child(family["id"], full_name="B", birth_date="2024-02-01")
    fetched = get_success_data(api.get_family(family["id"], ADMIN))
    assert fetched["child_count"] == 2


def test_program_age_band_max_not_greater_than_min_returns_invalid_request(api):
    """PRD §3.9: "the inclusive lower age bound min_age_months and the exclusive
    upper age bound max_age_months (which must be strictly greater than
    min_age_months)"

    A program with max_age_months equal to min_age_months returns
    ERR_INVALID_REQUEST 400.

    Design: Corner/entities/program_age_band_max_le_min_returns_invalid_request
    """
    resp = api.create_program(
        {"name": "Bad", "level_index": 0, "min_age_months": 24, "max_age_months": 24, "tuition_cents": 2500},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# -------------------------------------------------------------------------
# State machines
# -------------------------------------------------------------------------
def test_pay_already_paid_invoice_returns_invalid_state(api):
    """PRD §3.6: "Paying an invoice ... moves it from OPEN to PAID and increments
    its version; paying requires the invoice be OPEN (a non-OPEN invoice yields
    ERR_INVALID_STATE)"

    Paying an invoice that is already PAID returns ERR_INVALID_STATE 409.

    Design: Corner/state_machines/pay_already_paid_invoice_returns_invalid_state
    """
    set_clock("2026-05-01T00:00:00Z")
    ctx = fx.setup_billable_membership(num_children=1, tuition_cents=2500, tier="CORE")
    set_clock("2026-06-01T00:00:00Z")
    invoice = validate_success(api.renew_membership(ctx["membership"]["id"], STAFF), 201)
    validate_success(api.pay_invoice(invoice["id"], STAFF), 200)
    resp = api.pay_invoice(invoice["id"], STAFF)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# -------------------------------------------------------------------------
# Endpoints — listing, computed read
# -------------------------------------------------------------------------
def test_list_programs_pagination_envelope(api):
    """PRD §2.3: "Every list response carries limit, offset, total_count, and
    has_more in the meta object of the envelope."
    PRD §2.2: "The response_type is either "object" for a single resource or "array"
    for a list of resources."

    Three created programs yield total_count 3 and has_more false in an array
    envelope.

    Design: Corner/endpoints/list_programs_pagination_envelope
    """
    create_program(level_index=0, tuition_cents=2500)
    create_program(level_index=1, tuition_cents=3500)
    create_program(level_index=2, tuition_cents=5000)
    resp = api.list_programs(ADMIN)
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 3
    assert meta["has_more"] is False
    assert resp.json()["response_type"] == "array"


def test_session_enrolled_count_reflects_enrollments(api):
    """PRD §2.6: "the computed fields ... ClassSession.enrolled_count always reflect
    the live state the instant a request completes."
    PRD §3.4: "When a row is created ENROLLED, the session's enrolled_count is
    incremented by one."

    GET on a session after one enroll returns enrolled_count 1.

    Design: Corner/endpoints/session_enrolled_count_reflects_enrollments_computed_read
    """
    set_clock("2026-05-01T00:00:00Z")
    program = create_program(level_index=0, tuition_cents=2500)
    room = create_room(physical_capacity=12)
    instructor = create_instructor(certified_level_indices=[0])
    session = create_session(program["id"], room["id"], instructor["id"], capacity=5)
    family, membership = create_active_membership(tier="CORE")
    child = create_child(family["id"], birth_date="2024-01-01")
    enroll_child(child["id"], session["id"], membership["id"], kind="RECURRING")
    fetched = get_success_data(api.get_session(session["id"], STAFF))
    assert fetched["enrolled_count"] == 1


def test_enroll_response_immediately_reflects_enrolled_count(api):
    """PRD §2.6: "the governing principle here is that derived and computed fields
    are reconciled immediately and synchronously as part of the triggering request,
    never deferred. In particular, the computed fields ... ClassSession.enrolled_count
    always reflect the live state the instant a request completes."

    A GET right after an enroll shows enrolled_count 1 with no read delay.

    Design: Corner/consistency_model/enroll_response_immediately_reflects_enrolled_count
    """
    set_clock("2026-05-01T00:00:00Z")
    program = create_program(level_index=0, tuition_cents=2500)
    room = create_room(physical_capacity=12)
    instructor = create_instructor(certified_level_indices=[0])
    session = create_session(program["id"], room["id"], instructor["id"], capacity=5)
    family, membership = create_active_membership(tier="CORE")
    child = create_child(family["id"], birth_date="2024-01-01")
    enroll_child(child["id"], session["id"], membership["id"], kind="RECURRING")
    fetched = get_success_data(api.get_session(session["id"], STAFF))
    assert fetched["enrolled_count"] == 1


# -------------------------------------------------------------------------
# RBAC
# -------------------------------------------------------------------------
def test_parent_cannot_create_program(api):
    """PRD §2.1: "A StudioAdmin ... exclusively manages configuration and time:
    creating programs, creating rooms, creating instructors"
    PRD §2.1: "When the headers are well-formed but the role is not permitted to
    perform the requested operation, the request is rejected with ERR_UNAUTHORIZED
    (HTTP 403)."

    A Parent calling the StudioAdmin-exclusive create-program endpoint is denied
    with ERR_UNAUTHORIZED 403.

    Design: Corner/rbac/parent_cannot_create_program
    """
    family = create_family()
    parent_headers = fx.make_parent_headers(family["id"])
    resp = api.create_program(
        {"name": "Hack", "level_index": 0, "min_age_months": 6, "max_age_months": 60, "tuition_cents": 2500},
        parent_headers,
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_parent_cannot_freeze_other_familys_membership(api):
    """PRD §2.1: "A Parent attempting to act on a family that is not their own is
    rejected with ERR_UNAUTHORIZED."
    PRD §2.1: "ownership checks on any resource that references a Family compare the
    resource's family foreign key to X-User-ID."

    Family Y's parent attempting to freeze Family X's ACTIVE membership is denied
    with ERR_UNAUTHORIZED 403.

    Design: Corner/rbac/parent_cannot_freeze_other_familys_membership
    """
    family_x = create_family(account_email="fx@x.com")
    family_y = create_family(account_email="fy@x.com")
    _, membership = create_active_membership(family_id=family_x["id"], tier="CORE")
    parent_y_headers = fx.make_parent_headers(family_y["id"])
    resp = api.freeze_membership(membership["id"], parent_y_headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_missing_role_header_returns_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or X-User-Role is not one of the
    recognized roles, the request is rejected with ERR_UNAUTHENTICATED (HTTP 401)."

    A request whose X-User-Role is an unrecognized role returns ERR_UNAUTHENTICATED
    401 before any resource lookup.

    Design: Corner/rbac/missing_role_header_returns_unauthenticated
    """
    bad_headers = build_user_headers("nobody", "Anonymous")
    resp = api.list_programs(bad_headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)
