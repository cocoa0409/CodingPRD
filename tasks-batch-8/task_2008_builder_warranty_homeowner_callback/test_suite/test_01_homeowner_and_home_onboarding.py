"""Onboarding the book of business: homeowners, homes, tier dates, reserves."""
from test_helpers import (
    ApiErrorId,
    create_home,
    create_home_payload,
    create_homeowner,
    create_homeowner_payload,
    get_reserve_for_home,
    assert_date_equal,
    assert_home,
    assert_homeowner,
    assert_instant_equal,
    assert_warranty_reserve,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.test_users import TEST_USERS

MANAGER = TEST_USERS["manager_headers"]
FINANCE = TEST_USERS["finance_headers"]


def test_homeowner_creation_applies_defaults(api):
    """PRD §3.1: "`phone` is optional and stays unset when not provided."
    PRD §2.5: "`version`: an integer that increments by one on every mutation."
    PRD §2.4: "At startup the logical clock reads exactly 2026-08-01T00:00:00Z".

    Design: Corner/entities/homeowner_creation_applies_defaults
    """
    resp = api.create_homeowner(
        create_homeowner_payload(full_name="Pat Hale", email="pat@example.com"),
        MANAGER,
    )
    data = validate_success(resp, 201)
    assert_homeowner(data)
    assert data.get("phone") is None, "phone omitted at intake must stay unset (null)"
    assert data["version"] == 1, f"new homeowner version must be 1, got {data['version']}"
    assert_instant_equal(data["created_at"], "2026-08-01T00:00:00Z", "created_at")
    assert is_valid_uuid(data["id"]), "id must be a server-minted UUID"


def test_home_creation_computes_tier_dates_and_reserve(api):
    """PRD §3.1: "The closing date anchors all three coverage tiers, and the server
    computes the tier end dates at creation: `workmanship_end_date` twelve months
    after closing, `systems_end_date` twenty-four months after, and
    `structural_end_date` one hundred twenty months — ten years — after."
    PRD §3.1: "Creating the home also creates its warranty reserve — version 1, zero
    balance, expected lifetime accrual computed from the sale price as described in
    §3.7 — and until the first accrual lands the reserve's alert reads `ELEVATED`,
    because a zero balance sits below the alert threshold whenever the expected
    accrual is positive."
    PRD §3.7: "`expected_lifetime_accrual_cents` is the `sale_price_cents` multiplied
    by the accrual rate of one-half of one percent — 0.005 — rounded half-up to
    whole cents."

    Design: Corner/entities/home_creation_computes_tier_dates_and_reserve
    """
    homeowner = create_homeowner()
    resp = api.create_home(
        create_home_payload(
            homeowner["id"],
            lot_number="L-901",
            community_name="Cedar Ridge",
            sale_price_cents=40_000_000,
            closing_date="2026-06-01",
            warranty_program="STANDARD",
        ),
        MANAGER,
    )
    home = validate_success(resp, 201)
    assert_home(home)
    assert_date_equal(home["workmanship_end_date"], "2027-06-01", "workmanship_end_date")
    assert_date_equal(home["systems_end_date"], "2028-06-01", "systems_end_date")
    assert_date_equal(home["structural_end_date"], "2036-06-01", "structural_end_date")

    reserve = get_reserve_for_home(home["id"])  # asserts exactly one reserve
    assert_warranty_reserve(reserve)
    assert reserve["expected_lifetime_accrual_cents"] == 200_000, (
        f"round_half_up(40000000 x 0.005) == 200000, got "
        f"{reserve['expected_lifetime_accrual_cents']}"
    )
    assert reserve["balance_cents"] == 0
    assert reserve["alert_status"] == "ELEVATED", (
        "a zero balance sits below the alert threshold whenever the expected "
        f"accrual is positive; got {reserve['alert_status']}"
    )
    assert reserve["version"] == 1


def test_home_invalid_program_enum_rejected(api):
    """PRD §3.1: "the `warranty_program`: either `STANDARD`, meaning the builder
    self-administers, or `THIRD_PARTY_ADMINISTERED`, meaning structural risk is
    ceded to an external administrator."
    PRD §2.7: "Request shape: required fields present, enum values in domain,
    numeric constraints honored — a strictly positive sale price, non-negative
    cost figures, a strictly positive claimed amount, a satisfaction score between
    one and five — and a visit window that ends strictly after it begins, else
    `ERR_INVALID_REQUEST`."

    Design: Corner/entities/home_invalid_program_enum_rejected
    """
    homeowner = create_homeowner()
    resp = api.create_home(
        create_home_payload(homeowner["id"], warranty_program="PREMIUM"),
        MANAGER,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    list_resp = api.list_homes(FINANCE, params={"homeowner_id": homeowner["id"]})
    data, meta = validate_paginated(list_resp)
    assert meta["total_count"] == 0 and data == [], (
        "rejected home creation must persist no home (and therefore no reserve)"
    )
