"""Entity creation, defaults, system fields, computed counters, required-field
and FK/enum validation corners (PRD §2.4, §2.5, §2.8, §3.1, §3.2, §3.3).
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    NON_EXISTENT_UUID,
    create_section,
    create_account,
    create_season_plan,
    TEST_USERS,
)

_BOX = TEST_USERS["box_office_headers"]


def test_create_section_starts_with_zero_counts(api):
    """PRD §3.1: "A freshly created section reports `total_seats` of zero and
    `available_seats` of zero; both grow only as seats are added beneath it."
    PRD §2.4: "The `version` field is an integer that starts at 1."

    Design: Corner/entities/create_section_returns_201_with_computed_counts_zero
    """
    resp = api.create_section({"name": "Lower 300", "tier": "PREMIUM", "base_price_cents": 250000}, _BOX)
    sec = validate_success(resp, expected_status=201)
    assert sec["total_seats"] == 0, sec["total_seats"]
    assert sec["available_seats"] == 0, sec["available_seats"]
    assert sec["version"] == 1, sec["version"]


def test_get_section_nonexistent_not_found(api):
    """PRD §2.8: "The system then resolves every resource identifier named in the URL
    path, left to right, and rejects the first one that does not exist with
    `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/get_section_nonexistent_returns_not_found
    """
    resp = api.get_section(NON_EXISTENT_UUID, _BOX)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_seat_missing_required_field_rejected(api):
    """PRD §2.8: "the system checks that required body fields are present and
    well-typed, that every enum value falls inside its declared set, and that every
    integer falls inside its declared range; any violation yields
    `ERR_INVALID_REQUEST` (HTTP 422)."
    PRD §3.1: "each seat also carries the season window it is being sold for: an
    inclusive `season_start_date` and an inclusive `season_end_date`."

    Omitting season_end_date is rejected.

    Design: Corner/entities/create_seat_missing_required_field_returns_invalid_request
    """
    section = create_section(name="Lower 310")
    resp = api.create_seat(
        {"section_id": section["id"], "row_label": "A", "seat_number": 1,
         "season_start_date": "2026-10-01T00:00:00.000Z"},
        _BOX,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_account_applies_defaults(api):
    """PRD §3.2: "this value must be non-negative, defaults to 0 when omitted."
    PRD §3.2: "On registration the account's `priority_points` balance is 0, its
    `status` is `ACTIVE`, and its `loyalty_tier` is `BRONZE`."

    Design: Corner/entities/create_account_default_points_and_tier_applied
    """
    resp = api.create_account({"full_name": "Default Acc", "email": "defacc-unique@example.com"}, _BOX)
    acc = validate_success(resp, expected_status=201)
    assert acc["priority_points"] == 0, acc["priority_points"]
    assert acc["loyalty_tier"] == "BRONZE", acc["loyalty_tier"]
    assert acc["consecutive_seasons"] == 0, acc["consecutive_seasons"]
    assert acc["status"] == "ACTIVE", acc["status"]


def test_create_season_plan_invalid_plan_type_rejected(api):
    """PRD §3.3: "a `plan_type` of either `FULL` or `PARTIAL`."
    PRD §2.8: "that every enum value falls inside its declared set ... any violation
    yields `ERR_INVALID_REQUEST` (HTTP 422)."

    Design: Corner/entities/create_subscription_invalid_plan_type_enum_rejected
    """
    resp = api.create_season_plan(
        {"name": "Bad", "plan_type": "BOGUS", "game_count": 41, "price_multiplier_bps": 10000}, _BOX
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_subscription_unknown_account_fk_rejected(api):
    """PRD §2.8: "it confirm[s] that every foreign-key field carried in the request
    body — including `account_id`, `season_plan_id` ... points at an existing
    resource, rejecting the first dangling reference with
    `ERR_REFERENCED_RESOURCE_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/create_subscription_unknown_account_fk_not_found
    """
    plan = create_season_plan(plan_type="FULL", price_multiplier_bps=10000)
    resp = api.create_subscription({"account_id": NON_EXISTENT_UUID, "season_plan_id": plan["id"]}, _BOX)
    validate_error(resp, ApiErrorId.ERR_REFERENCED_RESOURCE_NOT_FOUND.value)


def test_new_seat_status_is_available_system_set(api):
    """PRD §3.1: "A new seat begins life with `status` of `AVAILABLE`."
    PRD §2.4: "The `version` field is an integer that starts at 1."

    Design: Corner/entities/system_fields_generated_input_ignored_on_seat
    """
    section = create_section(name="Lower 320")
    resp = api.create_seat(
        {"section_id": section["id"], "row_label": "A", "seat_number": 1,
         "season_start_date": "2026-10-01T00:00:00.000Z", "season_end_date": "2027-04-01T00:00:00.000Z"},
        _BOX,
    )
    seat = validate_success(resp, expected_status=201)
    assert seat["status"] == "AVAILABLE", seat["status"]
    assert seat["version"] == 1, seat["version"]


def test_section_counts_recomputed_on_seat_add(api):
    """PRD §3.1: "The act of creating a seat increments its section's `total_seats`
    and `available_seats` by one apiece, reconciled atomically."

    Adding two seats drives total_seats==2 and available_seats==2.

    Design: Corner/entities/section_available_seats_recomputed_on_seat_add
    """
    from test_helpers import create_seat
    section = create_section(name="Lower 330")
    create_seat(section["id"], row_label="A", seat_number=1)
    create_seat(section["id"], row_label="A", seat_number=2)
    sec = validate_success(api.get_section(section["id"], _BOX))
    assert sec["total_seats"] == 2, sec["total_seats"]
    assert sec["available_seats"] == 2, sec["available_seats"]
