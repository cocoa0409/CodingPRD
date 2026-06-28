"""Plan catalogue, member registration, and basic shape/validation rules.

Covers corner-design entities-section instances: creation, not-found, required
fields, defaults, system fields, type/enum constraints, plan-shape, and listing.
"""
from test_helpers import (
    api_client,
    validate_success, validate_error, validate_paginated,
    ApiErrorId, NON_EXISTENT_UUID,
    TEST_USERS,
    create_unlimited_plan_payload, register_member_payload,
)

BOX = TEST_USERS["box_manager_headers"]
ANON = TEST_USERS["anonymous_headers"]


def test_create_unlimited_plan_returns_201_active_version_1(api):
    """PRD §3.1: "Every plan is born with `active` set to true; archiving a plan flips `active` to false so it can no longer back new memberships, and bumps the plan's `version`."
    PRD §2.4: "The `version` field is an integer that starts at its initial value on creation and increments by one on every mutation".

    Design: Corner/entities/create_membership_plan_returns_201_with_all_fields
    """
    payload = create_unlimited_plan_payload(
        name="Unlimited", monthly_fee_cents=12000,
        commitment_months=0, requires_foundations=False,
    )
    resp = api.create_membership_plan(payload, BOX)
    data = validate_success(resp, expected_status=201)
    assert data["active"] is True
    assert data["plan_type"] == "UNLIMITED"
    assert data["version"] == 1


def test_get_member_not_found_returns_404(api):
    """PRD §2.9: "Before any business rule runs, the system confirms that every referenced resource exists — members, plans, memberships, sessions, reservations, tracks, coaches, benchmark results, teams, and team-member slots — validating them left to right in the order they appear, and rejecting the first missing reference with `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/get_member_not_found_returns_404
    """
    resp = api.get_member(NON_EXISTENT_UUID, BOX)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_register_member_missing_email_returns_invalid_request(api):
    """PRD §2.10: "Only then are request-body shape and type checks applied, yielding `ERR_INVALID_REQUEST` for missing required fields, wrong types, out-of-range numbers, or out-of-set enum values".

    Design: Corner/entities/create_member_missing_required_email_returns_invalid_request
    """
    resp = api.register_member({"full_name": "No Email"}, ANON)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_register_member_default_home_box_member_true(api):
    """PRD §3.1: "The `home_box_member` flag (defaulting to true) distinguishes home-box athletes, who hold memberships, from visiting and drop-in athletes".
    PRD §3.1: "Every new member starts with `no_show_strikes` at 0 and is not reservation-suspended."

    Design: Corner/entities/register_member_default_home_box_member_true
    """
    resp = api.register_member({"email": "def@x.com", "full_name": "Def"}, ANON)
    data = validate_success(resp, expected_status=201)
    assert data["home_box_member"] is True
    assert data["no_show_strikes"] == 0
    assert data["reservation_suspended"] is False


def test_register_member_system_fields_default_regardless_of_input(api):
    """PRD §3.1: "Every new member starts with `no_show_strikes` at 0 and is not reservation-suspended."

    Design: Corner/entities/member_system_fields_ignored_on_input
    """
    resp = api.register_member({"email": "sys@x.com", "full_name": "Sys"}, ANON)
    data = validate_success(resp, expected_status=201)
    assert data["no_show_strikes"] == 0
    assert data["reservation_suspended"] is False


def test_create_plan_invalid_plan_type_enum_returns_invalid_request(api):
    """PRD §3.1: "a `plan_type` that is one of `UNLIMITED` or `PUNCH`, fixing its usage model."
    PRD §2.10: "Only then are request-body shape and type checks applied, yielding `ERR_INVALID_REQUEST` for missing required fields, wrong types, out-of-range numbers, or out-of-set enum values".

    Design: Corner/entities/create_plan_invalid_enum_plan_type_returns_invalid_request
    """
    resp = api.create_membership_plan(
        {"name": "Bad", "plan_type": "GOLD", "monthly_fee_cents": 5000}, BOX
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_punch_plan_missing_punch_count_returns_plan_shape_invalid(api):
    """PRD §3.1: "A request that violates this pairing — a `PUNCH` plan omitting `punch_count` or an `UNLIMITED` plan supplying it — is rejected with `ERR_PLAN_SHAPE_INVALID`."

    Design: Corner/entities/punch_plan_missing_punch_count_returns_plan_shape_invalid
    """
    resp = api.create_membership_plan(
        {"name": "PunchNoCount", "plan_type": "PUNCH", "monthly_fee_cents": 0}, BOX
    )
    validate_error(resp, ApiErrorId.ERR_PLAN_SHAPE_INVALID.value)


def test_list_membership_plans_pagination_envelope(api):
    """PRD §2.3: "Every list response surfaces four pagination fields inside the envelope's `meta` object: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/list_membership_plans_pagination_envelope
    """
    api.create_membership_plan(
        create_unlimited_plan_payload(name="P1", monthly_fee_cents=10000), BOX
    )
    api.create_membership_plan(
        create_unlimited_plan_payload(name="P2", monthly_fee_cents=11000), BOX
    )
    resp = api.list_membership_plans(ANON, params={"limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert len(data) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
