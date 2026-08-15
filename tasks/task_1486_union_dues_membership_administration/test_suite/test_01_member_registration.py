"""Member registration, classification setup, and user-context validation."""
import pytest

from test_helpers import (
    ApiErrorId,
    MISSING_UUID,
    assert_member,
    make_classification,
    make_local,
    make_member,
    set_clock,
    setup_pct_local_with_journeyman,
    validate_error,
    validate_success,
)
from test_helpers import (
    TEST_USERS,
    create_member_payload,
)


def test_member_creation_defaults_and_initial_state(api, office_clerk_headers):
    """PRD section on enrolling members: "A new member starts `ACTIVE` with zero
    arrears, a `suspension_count` of zero, and null `suspended_since` and
    `last_suspension_ended_at`." And on common properties: "The `version` field
    is an integer that starts at 1 at creation and increments by one on every
    mutation of the resource".

    Design: Corner/entities/member_creation_defaults_and_initial_state
    """
    local, cls = setup_pct_local_with_journeyman()
    resp = api.create_member(
        create_member_payload(local["id"], cls["id"], full_name="New Ned", member_number="M-001"),
        office_clerk_headers,
    )
    member = validate_success(resp, 201)
    assert_member(member)
    assert member["status"] == "ACTIVE", "new member must start ACTIVE"
    assert member["arrears_cents"] == 0 and member["credit_balance_cents"] == 0
    assert member["suspension_count"] == 0
    assert member["good_standing"] is True, "ACTIVE with zero arrears is good standing"
    assert member["version"] == 1, "version starts at 1 at creation"
    assert member["suspended_since"] is None and member["last_suspension_ended_at"] is None


def test_member_missing_required_field_returns_invalid_request(api, office_clerk_headers):
    """PRD section on validation order: "malformed requests as
    `ERR_INVALID_REQUEST` (HTTP 400)." The registration contract lists
    `full_name` among the values the clerk provides, with only `employer_id`
    marked optional ("The optional `employer_id` places the member on an
    employer's checkoff roster").

    Design: Corner/entities/member_missing_required_field_returns_invalid_request
    """
    local, cls = setup_pct_local_with_journeyman()
    payload = {
        "local_id": local["id"],
        "classification_id": cls["id"],
        "member_number": "M-001",
        "joined_at": "2026-01-15",
    }
    resp = api.create_member(payload, office_clerk_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_member_body_ref_employer_not_found_returns_422(api, office_clerk_headers):
    """PRD section on enrolling members: "it must reference an existing employer
    (`ERR_EMPLOYER_NOT_FOUND` as a body-reference error)". And on validation
    order: "Body-referenced existence failures surface as HTTP 422".

    Design: Corner/entities/member_body_ref_employer_not_found_returns_422
    """
    local, cls = setup_pct_local_with_journeyman()
    payload = create_member_payload(
        local["id"], cls["id"], full_name="Ghost Gary", member_number="M-001",
        employer_id=MISSING_UUID,
    )
    resp = api.create_member(payload, office_clerk_headers)
    validate_error(resp, ApiErrorId.ERR_EMPLOYER_NOT_FOUND, 422)


def test_duplicate_member_number_rejected(api, office_clerk_headers):
    """PRD section on enrolling members: "their union card `member_number` —
    unique within the local, with duplicates rejected as
    `ERR_DUPLICATE_MEMBER_NUMBER`".

    Design: Corner/entities/duplicate_member_number_rejected
    """
    local, cls = setup_pct_local_with_journeyman()
    make_member(local["id"], cls["id"], full_name="First Fred", member_number="M-001")
    resp = api.create_member(
        create_member_payload(
            local["id"], cls["id"], full_name="Second Fred",
            member_number="M-001", joined_at="2026-02-01",
        ),
        office_clerk_headers,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_MEMBER_NUMBER)


def test_classification_duplicate_code_rejected(api, local_admin_headers):
    """PRD section on chartering locals and defining classifications: "Each
    classification has a `code` — one of `JOURNEYMAN`, `APPRENTICE`,
    `PROBATIONARY`, or `RETIREE` — unique within the local, so that reusing a
    code is rejected with `ERR_DUPLICATE_CLASSIFICATION`."

    Design: Corner/entities/classification_duplicate_code_rejected
    """
    local = make_local("PCT", name="Local 100")
    make_classification(local["id"], "JOURNEYMAN", 3000)
    resp = api.create_classification(
        local["id"], {"code": "JOURNEYMAN", "min_monthly_dues_cents": 1000}, local_admin_headers
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_CLASSIFICATION)


def test_member_get_not_found_returns_404(api, secretary_treasurer_headers):
    """PRD section on nested resource resolution: "The request is rejected
    with the 404 error corresponding to the first identifier that does not
    resolve". A random UUID in the member position surfaces
    `ERR_MEMBER_NOT_FOUND` (HTTP 404 per the error catalogue).

    Design: Corner/entities/member_get_not_found_returns_404
    """
    set_clock()
    resp = api.get_member(MISSING_UUID, secretary_treasurer_headers)
    validate_error(resp, ApiErrorId.ERR_MEMBER_NOT_FOUND, 404)


def test_classification_from_wrong_local_rejected(api, office_clerk_headers):
    """PRD section on enrolling members: "a `classification_id` that must belong
    to that same local (a classification from another local is rejected with
    `ERR_CLASSIFICATION_NOT_FOUND` as a body-reference error)". Body-referenced
    existence failures surface as HTTP 422.

    Design: Corner/validations/classification_from_wrong_local_rejected
    """
    local1 = make_local("PCT", name="Local 100")
    local2 = make_local("PCT", name="Local 101")
    cls2 = make_classification(local2["id"], "JOURNEYMAN", 3000)
    resp = api.create_member(
        create_member_payload(local1["id"], cls2["id"], full_name="Wrong Walt", member_number="M-001"),
        office_clerk_headers,
    )
    validate_error(resp, ApiErrorId.ERR_CLASSIFICATION_NOT_FOUND, 422)


def test_parentbody_cannot_register_member(api, parentbody_admin_headers):
    """PRD section on roles: "A request whose role is declared but not permitted
    on the target endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
    (HTTP 403)." The endpoint table authorizes only OfficeClerk to register a
    member.

    Design: Corner/rbac/parentbody_cannot_register_member
    """
    local, cls = setup_pct_local_with_journeyman()
    resp = api.create_member(
        create_member_payload(local["id"], cls["id"], full_name="Boss Bert", member_number="M-001"),
        parentbody_admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, 403)


def test_closed_local_rejects_new_classification(api, parentbody_admin_headers, local_admin_headers):
    """PRD section on chartering locals: "no new classifications, elections,
    per-capita reports, or assessment runs may be created for a `CLOSED` local
    — such attempts fail with `ERR_LOCAL_NOT_ACTIVE`".

    Design: Corner/errors/closed_local_rejects_new_classification
    """
    local = make_local("PCT", name="Local 100")
    validate_success(api.close_local(local["id"], parentbody_admin_headers), 200)
    resp = api.create_classification(
        local["id"], {"code": "JOURNEYMAN", "min_monthly_dues_cents": 3000}, local_admin_headers
    )
    validate_error(resp, ApiErrorId.ERR_LOCAL_NOT_ACTIVE)


def test_create_member_missing_auth_header_returns_400(api):
    """PRD section on roles: "A request missing either header, or carrying a
    role value outside this declared set, is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

    Design: Corner/validations/create_member_missing_auth_header_returns_400
    """
    set_clock()
    payload = {
        "local_id": MISSING_UUID,
        "classification_id": MISSING_UUID,
        "full_name": "No Header",
        "member_number": "M-001",
        "joined_at": "2026-01-15",
    }
    resp = api.create_member(payload, None)
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, 400)
