"""Access control (authentication, role authorization, ownership), generic
field validation, weight normalization, listing/pagination, and not-found.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, NON_EXISTENT_UUID,
    create_service_level_payload, create_grading_standard_payload,
    create_item_payload, create_encapsulate_payload,
    make_customer_headers, TEST_USERS,
    setup_catalog, setup_draft_submission, setup_item_authenticated,
    create_customer,
)


LAB = TEST_USERS["lab_admin_headers"]
GRADER = TEST_USERS["grader_headers"]


# ---------------------------------------------------------------------------
# Authentication header guard
# ---------------------------------------------------------------------------
def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "Every request other than customer registration and the
    test-clock control endpoint must be authenticated through two mandatory HTTP
    headers."
    PRD §2.1: "If either header is missing or malformed, the request is rejected
    with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    resp = api.list_submissions(headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


# ---------------------------------------------------------------------------
# Role authorization
# ---------------------------------------------------------------------------
def test_customer_cannot_create_service_level(api):
    """PRD §2.1: "When the headers are present but the named role is not permitted
    to perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/customer_cannot_create_service_level
    """
    customer = create_customer(email="e22@x.com")
    cust_headers = make_customer_headers(customer["id"])
    resp = api.create_service_level(
        create_service_level_payload(code="SNEAK", base_fee_cents=1,
                                     max_declared_value_cents=1, insurance_rate_bps=0),
        cust_headers,
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_grader_cannot_encapsulate(api):
    """PRD §2.1: "When the headers are present but the named role is not permitted
    to perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN_ROLE`."
    PRD §4: encapsulate is authorized for Authenticator only.

    Design: Corner/rbac/grader_cannot_encapsulate
    """
    customer, sl, gs, sub, item, ga, auth = setup_item_authenticated(email="e23@x.com", title="AG")
    resp = api.encapsulate_item(item["id"], create_encapsulate_payload(ga["id"]), GRADER)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


# ---------------------------------------------------------------------------
# Ownership
# ---------------------------------------------------------------------------
def test_non_owner_customer_cannot_submit_others_submission(api):
    """PRD §2.1: "a `Customer` may submit, add items to, delete items from, or open
    a regrade request against a `Submission` only when the `customer_id` recorded on
    that `Submission` equals `X-User-ID`; otherwise the request is rejected with
    `ERR_NOT_OWNER`."

    Design: Corner/rbac/customer_not_owner_cannot_submit_others_submission
    """
    customer, sl, gs, sub = setup_draft_submission(email="owner@x.com")
    owner_headers = make_customer_headers(customer["id"])
    api.add_item(sub["id"], create_item_payload(gs["id"], title="AH", declared_value_cents=30000), owner_headers)
    intruder = create_customer(email="intruder@x.com")
    intruder_headers = make_customer_headers(intruder["id"])
    resp = api.submit_submission(sub["id"], intruder_headers)
    validate_error(resp, ApiErrorId.ERR_NOT_OWNER.value)


# ---------------------------------------------------------------------------
# Existence ordering
# ---------------------------------------------------------------------------
def test_get_nonexistent_submission_item_returns_not_found(api):
    """PRD §2.5: "The system validates every identifier in the path from left to
    right and rejects the request with `ERR_NOT_FOUND` at the first identifier that
    does not correspond to an existing resource, before evaluating anything
    further to its right."

    Design: Corner/entities/get_submission_item_nonexistent_returns_not_found
    """
    customer = create_customer(email="e2@x.com")
    cust_headers = make_customer_headers(customer["id"])
    resp = api.get_item(NON_EXISTENT_UUID, cust_headers)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


# ---------------------------------------------------------------------------
# Required field & semantic validation
# ---------------------------------------------------------------------------
def test_create_item_missing_declared_value_returns_invalid_request(api):
    """PRD §2.6: "a malformed body, a missing required field, or an invalid enum
    value is rejected with `ERR_INVALID_REQUEST`"

    Design: Corner/entities/create_item_missing_required_declared_value_returns_invalid_request
    """
    customer, sl, gs, sub = setup_draft_submission(email="e3@x.com")
    cust_headers = make_customer_headers(customer["id"])
    resp = api.add_item(sub["id"], {"grading_standard_id": gs["id"], "title": "No Value"}, cust_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_item_non_positive_declared_value_returns_validation(api):
    """PRD §2.6: "a semantically invalid field value that is otherwise well-formed
    (for example a non-positive `declared_value_cents`) is rejected with
    `ERR_VALIDATION`."

    Design: Corner/errors/negative_declared_value_returns_validation
    """
    customer, sl, gs, sub = setup_draft_submission(email="e20@x.com")
    cust_headers = make_customer_headers(customer["id"])
    resp = api.add_item(
        sub["id"], create_item_payload(gs["id"], title="AE", declared_value_cents=0), cust_headers,
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


# ---------------------------------------------------------------------------
# Weight normalization
# ---------------------------------------------------------------------------
def test_grading_standard_weights_not_normalized_rejected(api):
    """PRD §3.1: "The four weights must sum to exactly 10000 basis points; a
    standard whose `centering_weight_bps`, `corners_weight_bps`, `edges_weight_bps`,
    and `surface_weight_bps` do not add up to exactly 10000 is rejected with
    `ERR_WEIGHTS_NOT_NORMALIZED`."

    Design: Corner/validations/weights_not_normalized_rejected
    """
    resp = api.create_grading_standard(
        create_grading_standard_payload(
            code="BAD", centering_weight_bps=2000, corners_weight_bps=2500,
            edges_weight_bps=2500, surface_weight_bps=2000,
        ),
        LAB,
    )
    validate_error(resp, ApiErrorId.ERR_WEIGHTS_NOT_NORMALIZED.value)


# ---------------------------------------------------------------------------
# Listing & pagination
# ---------------------------------------------------------------------------
def test_list_submissions_returns_paginated_envelope(api):
    """PRD §2.3: "Paginated and non-paginated list-based responses include the
    following fields in the `meta` object of the response envelope: `limit`,
    `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/list_submissions_paginated_envelope
    """
    customer, sl, gs, sub = setup_draft_submission(email="e5@x.com")
    cust_headers = make_customer_headers(customer["id"])
    resp = api.list_submissions(cust_headers, params={"customer_id": customer["id"]})
    data, meta = validate_paginated(resp)
    assert "total_count" in meta and "has_more" in meta
    assert len(data) == 1, "exactly one submission exists for this customer"


def test_pagination_limit_over_max_rejected(api):
    """PRD §2.3: "The `limit` parameter specifies the maximum number of items to
    return. If not provided, it defaults to 10, with a minimum of 1 and a maximum
    of 100."
    PRD §2.3: "A `limit` or `offset` outside these bounds is rejected with
    `ERR_PAGINATION_INVALID`."

    Design: Corner/entities/pagination_limit_over_max_returns_invalid
    """
    customer = create_customer(email="e6@x.com")
    cust_headers = make_customer_headers(customer["id"])
    resp = api.list_submissions(cust_headers, params={"customer_id": customer["id"], "limit": 101})
    validate_error(resp, ApiErrorId.ERR_PAGINATION_INVALID.value)
