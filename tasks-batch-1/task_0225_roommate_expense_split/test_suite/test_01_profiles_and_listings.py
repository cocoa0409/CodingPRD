"""Profile registration, field validation, and uniqueness.

Translates queue-B (Corner) instances in the `entities` section that concern
RoommateProfile creation and immutability, plus the email-uniqueness validation.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    assert_roommate_profile,
    assert_immutable_child_row,
    find_split_for_profile,
    make_roommate_headers,
    make_operator_headers,
    create_profile_payload,
    create_listing_payload,
    create_match_request_payload,
    create_bill_payload,
    build_household_with_members,
    create_profile,
    issue_rent_bill,
    MISSING_UUID,
)

api = api_client


def test_create_profile_returns_201_with_minted_fields():
    """PRD §3.1: "A freshly registered profile starts with a `net_balance_cents` of zero."
    PRD §2.4: "a `version`, an integer that starts at its initial value and increments
    by one with every modification to the resource."

    Design: Corner/entities/create_roommate_profile_returns_201_with_fields
    """
    resp = api.create_profile(
        create_profile_payload(full_name="Creator", cleanliness=4, sleep_schedule="EARLY_BIRD")
    )
    data = validate_success(resp, 201)
    assert_roommate_profile(data)
    assert data["full_name"] == "Creator"
    assert data["version"] == 1, f"new profile version must be 1, got {data['version']}"
    assert data["net_balance_cents"] == 0


def test_get_profile_not_found_returns_404():
    """PRD §2.5: "the first identifier in the path that does not resolve to an
    existing resource causes the request to be rejected immediately with
    `ERR_NOT_FOUND`, before any deeper lookup or business rule is attempted."

    Design: Corner/entities/get_roommate_profile_not_found_404
    """
    actor = create_profile(api, full_name="Actor")
    resp = api.get_profile(MISSING_UUID, make_roommate_headers(actor["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_profile_missing_required_field_rejected():
    """PRD §2.11: "any request that omits a required field or supplies a field that
    violates its declared type or range constraint — a negative `monthly_income_cents`,
    a `cleanliness` outside 1 through 5, a non-positive `total_amount_cents`, and the
    like — is rejected with `ERR_VALIDATION`."

    Design: Corner/entities/create_profile_missing_required_field_422
    """
    payload = {
        "email": "missing@x.com",
        "full_name": "Missing",
        "monthly_income_cents": 500_000,
        "sleep_schedule": "FLEXIBLE",
        # cleanliness omitted
    }
    resp = api.create_profile(payload)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_create_profile_cleanliness_out_of_range_rejected():
    """PRD §2.11: "any request that omits a required field or supplies a field that
    violates its declared type or range constraint — a negative `monthly_income_cents`,
    a `cleanliness` outside 1 through 5, a non-positive `total_amount_cents`, and the
    like — is rejected with `ERR_VALIDATION`."

    Design: Corner/entities/create_profile_invalid_enum_cleanliness_422
    """
    resp = api.create_profile(create_profile_payload(cleanliness=7))
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_smoker_and_pets_default_false_when_omitted():
    """PRD §3.1: "two lifestyle booleans, `smoker` and `pets`, each of which defaults to
    false when omitted."

    Design: Corner/entities/smoker_default_false_applied
    """
    payload = {
        "email": "def@x.com",
        "full_name": "Def",
        "monthly_income_cents": 500_000,
        "cleanliness": 4,
        "sleep_schedule": "FLEXIBLE",
        # smoker and pets omitted
    }
    data = validate_success(api.create_profile(payload), 201)
    assert data["smoker"] is False
    assert data["pets"] is False


def test_duplicate_email_rejected():
    """PRD §3.1: "Email is the login and contact handle and must be non-empty and
    unique across all profiles; registering a second profile with an email already
    in use is rejected with `ERR_EMAIL_TAKEN`."

    Design: Corner/entities/email_uniqueness_conflict_409
    """
    validate_success(api.create_profile(create_profile_payload(email="dup@x.com")), 201)
    resp = api.create_profile(create_profile_payload(email="dup@x.com"))
    validate_error(resp, ApiErrorId.ERR_EMAIL_TAKEN.value)


def test_bill_split_row_has_no_version_field():
    """PRD §2.4: "A `BillSplit` (a single member's share of one bill) and an
    `ExpenseShare` (a single participant's portion of one expense) carry only an `id`
    and a `created_at`; they have no `updated_at` and no `version`."

    Design: Corner/entities/billsplit_immutable_no_version_field
    """
    env = build_household_with_members(api, [{"full_name": "M1"}])
    m1 = env["members"][0]
    bill = issue_rent_bill(api, env, total_amount_cents=200_000)

    splits = validate_success(
        api.list_bill_splits(bill["id"], make_roommate_headers(env["lister"]["id"]))
    )
    row = find_split_for_profile(splits, m1["id"])
    assert row["share_cents"] == 200_000
    assert_immutable_child_row(row)


def test_list_profiles_pagination_envelope():
    """PRD §2.3: "Paginated list responses include the following fields in the `meta`
    object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/endpoints/list_profiles_pagination_envelope
    """
    a = create_profile(api, full_name="Pg1")
    create_profile(api, full_name="Pg2")
    resp = api.list_profiles(make_roommate_headers(a["id"]), params={"limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] >= 2
    assert meta["has_more"] is True
