"""Consignor onboarding, markdown schedules, and agreement preconditions.

Translates corner-design instances in the `entities` and `validations` sections
that exercise creation defaults, input validation, pagination, and the
cross-entity agreement precondition.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success, validate_error, validate_paginated,
    assert_consignor, assert_agreement,
    create_consignor_payload, create_markdown_schedule_payload,
    create_agreement_payload,
    TEST_USERS,
    NON_EXISTENT_UUID,
)

ADMIN = TEST_USERS["store_admin_headers"]


def test_create_consignor_returns_201_with_defaults(api):
    """PRD §3.1: "A freshly registered consignor starts in `ACTIVE` status, with
    `store_credit_cents`, `unsettled_payable_cents`, and `lifetime_payout_cents`
    all initialized to zero."

    Design: Corner/entities/create_consignor_returns_201_with_defaults
    """
    res = api.create_consignor(
        create_consignor_payload(full_name="New Nora", email="nora@x.com"), ADMIN)
    cons = validate_success(res, 201)
    assert_consignor(cons)
    assert cons["status"] == "ACTIVE", f"expected ACTIVE, got {cons['status']}"
    assert cons["store_credit_cents"] == 0
    assert cons["unsettled_payable_cents"] == 0
    assert cons["lifetime_payout_cents"] == 0


def test_get_consignor_not_found_returns_404(api):
    """PRD §2.5: "A single path identifier that does not exist likewise yields
    `ERR_NOT_FOUND`."

    Design: Corner/entities/get_consignor_not_found_returns_404
    """
    res = api.get_consignor(NON_EXISTENT_UUID, ADMIN)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_create_consignor_missing_email_returns_invalid_request(api):
    """PRD §2.3: "A request that omits a required field, carries a malformed type,
    or supplies an out-of-range scalar is rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_consignor_missing_email_returns_invalid_request
    """
    res = api.create_consignor({"full_name": "No Email"}, ADMIN)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_create_consignor_duplicate_email_returns_409(api):
    """PRD §3.1: "an `email`, which must be non-empty and unique across all
    consignors. A duplicate email is rejected with `ERR_DUPLICATE_EMAIL`."

    Design: Corner/entities/create_consignor_duplicate_email_returns_409
    """
    validate_success(api.create_consignor(
        create_consignor_payload(full_name="First", email="dup@x.com"), ADMIN), 201)
    res = api.create_consignor(
        create_consignor_payload(full_name="Second", email="dup@x.com"), ADMIN)
    validate_error(res, "ERR_DUPLICATE_EMAIL", expected_status=409)


def test_agreement_split_pct_out_of_range_returns_invalid_request(api):
    """PRD §2.3: "a `split_pct` must fall strictly between 0 and 1 ... A request
    that omits a required field, carries a malformed type, or supplies an
    out-of-range scalar is rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/agreement_split_pct_out_of_range_returns_invalid_request
    """
    sched = validate_success(api.create_markdown_schedule(
        create_markdown_schedule_payload(), ADMIN), 201)
    cons = validate_success(api.create_consignor(
        create_consignor_payload(full_name="Range Ray", email="range@x.com"), ADMIN), 201)
    res = api.create_agreement(
        create_agreement_payload(cons["id"], sched["id"], split_pct=1.0), ADMIN)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_list_consignors_pagination_envelope(api):
    """PRD §2.2: "Pagination-related fields in `meta` (`limit`, `offset`,
    `total_count`, `has_more`) are included for list endpoints."

    Design: Corner/entities/list_consignors_pagination_envelope
    """
    validate_success(api.create_consignor(
        create_consignor_payload(full_name="A", email="a@x.com"), ADMIN), 201)
    validate_success(api.create_consignor(
        create_consignor_payload(full_name="B", email="b@x.com"), ADMIN), 201)
    data, meta = validate_paginated(api.list_consignors(ADMIN, params={"limit": 1, "offset": 0}))
    assert meta["total_count"] == 2, f"expected total_count 2, got {meta['total_count']}"
    assert meta["has_more"] is True
    assert len(data) == 1, f"expected 1 record with limit=1, got {len(data)}"


def test_pagination_limit_out_of_bounds_returns_400(api):
    """PRD §2.3: "A `limit` or `offset` value outside its permitted bounds is
    rejected with `ERR_VALIDATION_PAGINATION`."

    Design: Corner/entities/pagination_limit_out_of_bounds_returns_400
    """
    res = api.list_consignors(ADMIN, params={"limit": 101})
    validate_error(res, "ERR_VALIDATION_PAGINATION", expected_status=400)


def test_invalid_schedule_tiers_returns_invalid_schedule(api):
    """PRD §3.1: "the very first tier must have a `min_age_days` of 0 ... A schedule
    violating any of these structural rules is rejected with `ERR_INVALID_SCHEDULE`."

    Design: Corner/validations/invalid_schedule_tiers_returns_invalid_schedule
    """
    res = api.create_markdown_schedule(
        {"name": "Bad", "tiers": [{"min_age_days": 10, "discount_pct": 0.10}],
         "base_floor_pct": 0.30}, ADMIN)
    validate_error(res, "ERR_INVALID_SCHEDULE", expected_status=422)


def test_agreement_archived_schedule_returns_agreement_precondition(api):
    """PRD §3.1: "If the named consignor is not `ACTIVE` or the named schedule is
    archived, the creation is rejected with `ERR_AGREEMENT_PRECONDITION`."

    Design: Corner/validations/agreement_archived_schedule_returns_agreement_precondition
    """
    sched = validate_success(api.create_markdown_schedule(
        create_markdown_schedule_payload(name="Old"), ADMIN), 201)
    validate_success(api.archive_markdown_schedule(sched["id"], ADMIN), 200)
    cons = validate_success(api.create_consignor(
        create_consignor_payload(full_name="Arc Art", email="arc@x.com"), ADMIN), 201)
    res = api.create_agreement(
        create_agreement_payload(cons["id"], sched["id"], split_pct=0.50), ADMIN)
    validate_error(res, "ERR_AGREEMENT_PRECONDITION", expected_status=409)
