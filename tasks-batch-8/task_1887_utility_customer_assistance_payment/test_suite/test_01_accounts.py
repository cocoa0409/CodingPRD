"""Account creation defaults, 404 handling, delinquency tier boundaries, and
list pagination."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    ApiErrorId, NON_EXISTENT_UUID,
    assert_account,
    create_account, charge_arrearage, set_clock, get_account,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]


def test_account_create_applies_defaults(api):
    """PRD §3.1: "Three optional attributes complete the profile: `service_class`,
    one of `RESIDENTIAL` or `COMMERCIAL` and defaulting to `RESIDENTIAL`;
    `heating_fuel_type`, one of `ELECTRIC`, `GAS`, or `DUAL` and defaulting to
    `ELECTRIC`; and `deposit_held_cents`, the security deposit currently held,
    defaulting to 0 and never negative."
    PRD §3.1: "A new account begins with `service_status` of `CONNECTED`,
    `protection_status` of `UNPROTECTED`, all balances at zero, and `version` 1."

    Design: Corner/entities/account_create_defaults_applied
    """
    resp = api.create_account({"service_address": "1 Default Dr"}, ADMIN)
    data = validate_success(resp, 201)
    assert_account(data)
    assert data["service_class"] == "RESIDENTIAL"
    assert data["heating_fuel_type"] == "ELECTRIC"
    assert data["deposit_held_cents"] == 0
    assert data["arrearage_balance_cents"] == 0
    assert data["current_charges_balance_cents"] == 0
    assert data["credit_balance_cents"] == 0
    assert data["reconnection_fee_due_cents"] == 0
    assert data["service_status"] == "CONNECTED"
    assert data["protection_status"] == "UNPROTECTED"
    assert data["version"] == 1


def test_account_get_unknown_id_returns_not_found(api):
    """PRD §2.8: "5. **Existence** — every path identifier and every body-supplied
    foreign-key identifier must resolve to an existing resource, validated left to
    right; the first unresolvable identifier yields `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/account_get_not_found_returns_404
    """
    resp = api.get_account(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_delinquency_tier_inclusive_boundaries(api):
    """PRD §3.1: "An account is `SEVERELY_DELINQUENT` when its arrearage is at
    least 20000 cents ($200.00) and its age is at least 60 days; short of that,
    it is `DELINQUENT` when the arrearage is at least 5000 cents ($50.00) and
    the age at least 30 days; otherwise it is `CURRENT`."
    PRD §3.1: "Both boundaries are inclusive — exactly $50.00 at exactly 30 days
    is `DELINQUENT`, and exactly $200.00 at exactly 60 days is `SEVERELY_DELINQUENT`."

    Design: Corner/calculations/delinquency_tier_inclusive_boundaries
    """
    a1 = create_account(service_address="20 Tier Rd A1")
    charge_arrearage(a1["id"], 5_000, effective_on="2026-08-01")
    a2 = create_account(service_address="21 Tier Rd A2")
    charge_arrearage(a2["id"], 20_000, effective_on="2026-08-01")

    set_clock("2026-08-31T00:00:00Z")  # exactly 30 days of age
    a1_read = get_account(a1["id"])
    a2_read = get_account(a2["id"])
    assert a1_read["delinquency_tier"] == "DELINQUENT", (
        f"exactly 5000 cents at exactly 30 days is DELINQUENT, got {a1_read['delinquency_tier']}")
    assert a2_read["delinquency_tier"] == "DELINQUENT", (
        f"20000 cents at 30 days (< 60) is DELINQUENT, got {a2_read['delinquency_tier']}")

    set_clock("2026-09-30T00:00:00Z")  # exactly 60 days of age
    a1_read = get_account(a1["id"])
    a2_read = get_account(a2["id"])
    assert a1_read["delinquency_tier"] == "DELINQUENT", (
        f"5000 cents stays below the severe floor, got {a1_read['delinquency_tier']}")
    assert a2_read["delinquency_tier"] == "SEVERELY_DELINQUENT", (
        f"exactly 20000 cents at exactly 60 days is SEVERELY_DELINQUENT, "
        f"got {a2_read['delinquency_tier']}")


def test_accounts_list_pagination_envelope(api):
    """PRD §2.3: "The `limit` parameter sets the maximum number of items returned;
    when omitted it defaults to 10, and it must lie between 1 and 100 inclusive.
    The `offset` parameter sets the number of items skipped and defaults to 0."
    PRD §2.3: "The `meta` object of a list response carries the pagination fields
    `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/endpoints/accounts_list_pagination
    """
    for i in range(3):
        create_account(service_address=f"6{i} Page Rd")
    page1, meta1 = validate_paginated(api.list_accounts(ADMIN, params={"limit": 2, "offset": 0}))
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True
    page2, meta2 = validate_paginated(api.list_accounts(ADMIN, params={"limit": 2, "offset": 2}))
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False
