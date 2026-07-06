"""Entity creation defaults, uniqueness, FK/existence, RBAC role denials.

Translates queue B instances from `entities` and `rbac` sections plus the
authentication-priority instance from `errors`.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    make_homeowner_headers,
    make_board_member_headers,
    make_anonymous_headers,
    create_homeowner_payload,
    create_property_payload,
    create_assessment_payload,
    create_arc_request_payload,
    create_arc_review_payload,
    create_document_payload,
    assert_homeowner,
    assert_document,
    setup_homeowner_and_property,
    setup_arc_request_submitted,
    setup_arc_request_under_review,
    setup_board_member,
    create_homeowner,
)

_MANAGER = TEST_USERS["hoa_manager_headers"]
_COMPLIANCE = TEST_USERS["compliance_headers"]


def test_homeowner_creation_returns_201_with_defaults(api):
    """PRD §3.1: "A new homeowner is created with `standing` initialised to
    `GOOD_STANDING`, `delinquency_score` initialised to `0`, `booking_privilege`
    initialised to `ALLOWED`, and `version` initialised to `1`."

    Design: Corner/entities/homeowner_creation_returns_201_with_defaults
    """
    resp = api.create_homeowner(
        create_homeowner_payload(email="new@ex.com", full_name="New Owner"),
        _MANAGER,
    )
    data = validate_success(resp, expected_status=201)
    assert data["standing"] == "GOOD_STANDING"
    assert data["delinquency_score"] == 0
    assert data["booking_privilege"] == "ALLOWED"
    assert data["version"] == 1
    assert_homeowner(data)


def test_property_missing_required_homeowner_id(api):
    """PRD §3.1: "Property registration is likewise a manager-facing action:
    the payload provides a `homeowner_id` naming the owner of record"
    PRD §2.8: "Malformed payloads — a missing required field, a wrong type,
    an enum outside its declared set — are rejected with `ERR_INVALID_REQUEST`
    (HTTP 400)"

    Design: Corner/entities/property_missing_required_homeowner_id
    """
    resp = api.create_property(
        {"address": "1 Missing Ln", "monthly_dues_cents": 30000},
        _MANAGER,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_homeowner_get_non_existent_returns_not_found(api):
    """PRD §2.5: "For every endpoint that carries a path parameter, path
    parameters are validated in **strict left-to-right order**. The first
    path identifier that does not resolve to an existing row causes the
    request to be rejected immediately with `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/homeowner_get_non_existent_returns_not_found
    """
    resp = api.get_homeowner(NON_EXISTENT_UUID, _MANAGER)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_homeowner_email_uniqueness(api):
    """PRD §3.1: "Registering a homeowner accepts an `email` (unique across
    the roll, matched case-insensitively)"
    PRD §2.8: "uniqueness collisions on `Homeowner.email` or
    `Property.address` are rejected with `ERR_UNIQUE_VIOLATION` (HTTP 409)."

    Design: Corner/entities/homeowner_email_uniqueness
    """
    api.create_homeowner(
        create_homeowner_payload(email="uniq@ex.com", full_name="First"),
        _MANAGER,
    )
    resp = api.create_homeowner(
        create_homeowner_payload(email="uniq@ex.com", full_name="Second"),
        _MANAGER,
    )
    validate_error(resp, ApiErrorId.ERR_UNIQUE_VIOLATION)


def test_document_immutability_no_version(api):
    """PRD §2.4: "The `Document` resource is the sole exception: it is
    immutable after creation and therefore carries only `id` and `created_at`.
    It has no `updated_at` and no `version`."

    Design: Corner/entities/document_immutability_no_version
    """
    create_resp = api.create_document(
        create_document_payload(
            title="CC&R 2025", category="CCR", content_url="https://ex.com/ccr.pdf"
        ),
        _MANAGER,
    )
    doc = validate_success(create_resp, expected_status=201)
    resp = api.get_document(doc["id"], TEST_USERS["homeowner_headers"])
    data = validate_success(resp)
    assert data["title"] == "CC&R 2025"
    assert data["category"] == "CCR"
    assert_document(data)


def test_property_computed_total_outstanding_after_assessment(api):
    """PRD §2.6: "The property's `total_outstanding_cents` is the sum of
    `amount_due_cents` minus `amount_paid_cents` across every `Assessment`
    on the property whose `status` is `OPEN`, `PARTIALLY_PAID`, `OVERDUE`,
    or `DELINQUENT`, plus the sum of `fine_balance_cents` across every
    `Violation` on the property whose `status` is `FINED`, `APPEALED`, or
    `UPHELD`."

    Design: Corner/entities/property_computed_total_outstanding_after_assessment
    """
    _, prop = setup_homeowner_and_property(email="hcp@ex.com", address="20 CP Ln")
    api.create_assessment(create_assessment_payload(prop["id"]), _MANAGER)
    resp = api.get_property(prop["id"], _MANAGER)
    data = validate_success(resp)
    assert data["total_outstanding_cents"] == 30000


def test_assessment_system_field_amount_paid_ignored_on_input(api):
    """PRD §3.2: "`amount_paid_cents` and `late_fee_cents` start at `0`; the
    assessment's initial `status` is `OPEN`."

    Design: Corner/entities/assessment_system_field_amount_paid_ignored_on_input
    """
    _, prop = setup_homeowner_and_property(email="hsys@ex.com", address="21 Sys Ln")
    resp = api.create_assessment(create_assessment_payload(prop["id"]), _MANAGER)
    data = validate_success(resp, expected_status=201)
    assert data["amount_paid_cents"] == 0
    assert data["status"] == "OPEN"


def test_fk_property_missing_homeowner_returns_fk_not_found(api):
    """PRD §2.5: "Only after every path identifier has been resolved does the
    system proceed to body-referenced foreign keys; a body-level foreign key
    that does not resolve to an existing row is rejected with
    `ERR_FK_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/fk_property_missing_homeowner_returns_fk_not_found
    """
    resp = api.create_property(
        create_property_payload(
            NON_EXISTENT_UUID, address="22 FK Ln", monthly_dues_cents=30000
        ),
        _MANAGER,
    )
    validate_error(resp, ApiErrorId.ERR_FK_NOT_FOUND)


# ---------------------------------------------------------------------------
# RBAC role denials
# ---------------------------------------------------------------------------
def test_homeowner_cannot_finalize_arc(api):
    """PRD §2.1: "When the role is recognised but is not among the roles
    authorised for the requested endpoint, the request is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §4 endpoint row: "POST /arc-requests/{id}/finalize ... BoardMember"

    Design: Corner/rbac/homeowner_cannot_finalize_arc
    """
    board_member, homeowner, prop, arc = setup_arc_request_under_review(
        homeowner_email="hden@ex.com",
        board_email="bmden@ex.com",
        address="34 Den Ln",
    )
    resp = api.finalize_arc_request(
        arc["id"], make_homeowner_headers(homeowner["id"])
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_unauthenticated_returns_401(api, ah):
    """PRD §2.1: "When `X-User-Role` is missing or is not one of the four
    operational role names above, the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD §2.8 (priority 1): "Authentication — `X-User-Role` must be present
    and match one of the four operational roles from §2.1; otherwise
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/unauthenticated_returns_401
    """
    resp = api.create_homeowner(
        create_homeowner_payload(email="any@ex.com", full_name="Any"),
        ah(),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_compliance_cannot_create_assessment(api):
    """PRD §2.1: "When the role is recognised but is not among the roles
    authorised for the requested endpoint, the request is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §4 endpoint row: "POST /assessments ... HOAManager"

    Design: Corner/rbac/compliance_cannot_create_assessment
    """
    _, prop = setup_homeowner_and_property(email="hco@ex.com", address="35 CO Ln")
    resp = api.create_assessment(
        create_assessment_payload(prop["id"]), _COMPLIANCE
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
