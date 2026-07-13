"""Catalogue setup: plan enum validation, coach buffer default, and the list envelope."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    create_coach_entity,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]


def test_plan_invalid_enum_tier_returns_validation(api):
    """PRD §3.1: a CareerAdmin "defines a `PackagePlan` by supplying its `tier`, one of
    `BASIC`, `PRO`, or `EXECUTIVE`". PRD §2.12: body well-formedness requires "required
    fields present, enum values in range, types correct" — an out-of-range enum fails with
    `ERR_VALIDATION` (HTTP 422).

    Design: Corner/entities/plan_invalid_enum_tier_returns_validation
    """
    payload = {"tier": "GOLD", "base_price_cents": 20000, "included_deliverables": ["RESUME"],
               "included_revision_rounds": 1, "included_coaching_sessions": 0, "guarantee_type": "NONE"}
    resp = api.create_package_plan(payload, ADMIN)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_coach_default_buffer_minutes_applied(api):
    """PRD §3.1: a Coach is created with "an optional `buffer_minutes` that defaults to 15
    and must be at least zero".

    Design: Corner/entities/coach_default_buffer_minutes_applied
    """
    coach = create_coach_entity(name="Cy Coach", email="cy@x.com", specialty="GENERAL")
    fetched = validate_success(api.get_coach(coach["id"], ADMIN))
    assert fetched["buffer_minutes"] == 15


def test_list_package_plans_pagination_envelope(api):
    """PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` object of the envelope."

    Design: Corner/entities/list_package_plans_pagination_envelope
    """
    payload = {"tier": "BASIC", "base_price_cents": 20000, "included_deliverables": ["RESUME"],
               "included_revision_rounds": 1, "included_coaching_sessions": 0, "guarantee_type": "NONE"}
    validate_success(api.create_package_plan(payload, ADMIN), 201)
    data, meta = validate_paginated(api.list_package_plans(ADMIN))
    assert "total_count" in meta
    assert "has_more" in meta
