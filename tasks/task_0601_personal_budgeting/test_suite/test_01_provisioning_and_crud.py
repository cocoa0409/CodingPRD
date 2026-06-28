"""Household provisioning, defaults, computed fields, and basic CRUD error paths.

Translates Corner queue (B) section `entities`.
"""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, admin_headers, make_owner_headers,
    create_household, create_account, setup_goal_with_funding, contribute,
)


def test_create_household_returns_201_with_owner_and_healthy_posture(api):
    """PRD §3.1: "The act creates the Household with an initial posture of HEALTHY
    and a net_worth_cents of zero, and simultaneously creates the founding Member
    with role of OWNER, recording that member's id on the household as owner_member_id."
    PRD §2.5: "an integer version that starts at 1 and increments by one on every mutation."

    Design: Corner/entities/create_household_returns_201_with_owner
    """
    resp = api.create_household(
        {"name": "Acme", "owner_email": "o@x.com", "owner_display_name": "Owner"},
        admin_headers(),
    )
    data = validate_success(resp, expected_status=201)
    assert data["posture"] == "HEALTHY", f"expected HEALTHY, got {data['posture']}"
    assert data["net_worth_cents"] == 0, f"expected 0, got {data['net_worth_cents']}"
    assert data["version"] == 1, f"expected version 1, got {data['version']}"
    assert data["owner_member_id"], "owner_member_id must be non-null"


def test_get_household_not_found(api):
    """PRD §2.6: "The first identifier in the path that does not name an existing
    resource causes the request to fail with ERR_NOT_FOUND, before any deeper
    identifier or body rule is considered."

    Design: Corner/entities/get_household_not_found
    """
    resp = api.get_household("00000000-0000-0000-0000-000000000000", admin_headers())
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_create_household_missing_required_field(api):
    """PRD §2.7: "The catch-all ERR_INVALID_REQUEST (HTTP 400) covers a malformed body,
    a missing required field, a value of the wrong type, or an out-of-domain value".

    Design: Corner/entities/create_household_missing_required_field
    """
    resp = api.create_household(
        {"name": "Acme", "owner_display_name": "Owner"}, admin_headers()
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_household_base_currency_default_applied(api):
    """PRD §2.4: "Each household chooses a base_currency, one of USD, EUR, or GBP,
    defaulting to USD when not supplied at creation."

    Design: Corner/entities/household_base_currency_default_applied
    """
    resp = api.create_household(
        {"name": "Acme", "owner_email": "o@x.com", "owner_display_name": "Owner"},
        admin_headers(),
    )
    data = validate_success(resp, expected_status=201)
    assert data["base_currency"] == "USD", f"expected USD, got {data['base_currency']}"


def test_account_balances_computed_from_opening(api):
    """PRD §2.10: "The cleared_balance_cents is the account's opening_balance_cents plus
    the sum of the signed amount_cents of that account's POSTED (and not REMOVED)
    transactions."
    PRD §3.2: "each account ... begins life with a status of LINKED."

    Design: Corner/entities/account_balance_computed_input_ignored
    """
    hh, owner_headers = create_household()
    resp = api.create_account(
        hh["id"],
        {"institution_name": "Bank", "account_type": "DEPOSITORY",
         "opening_balance_cents": 10000},
        owner_headers,
    )
    data = validate_success(resp, expected_status=201)
    assert data["cleared_balance_cents"] == 10000, \
        f"expected 10000, got {data['cleared_balance_cents']}"
    assert data["available_balance_cents"] == 10000, \
        f"expected 10000, got {data['available_balance_cents']}"
    assert data["status"] == "LINKED"


def test_invalid_account_type_enum_rejected(api):
    """PRD §2.7: "The well-typedness check requires that body fields such as amount_cents
    be integers, day_of_month be an integer within 1 to 28, enum fields carry valid
    members, and target_cents be greater than zero".

    Design: Corner/entities/invalid_account_type_enum_rejected
    """
    hh, owner_headers = create_household()
    resp = api.create_account(
        hh["id"], {"institution_name": "Bank", "account_type": "BROKERAGE"},
        owner_headers,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_goal_contribution_immutable_no_version(api):
    """PRD §2.5: "The one exception is GoalContribution, which is an append-only event
    record: it carries only id and created_at, and has neither updated_at nor version."
    PRD §3.6: "A successful contribution creates a GoalContribution recording its
    goal_id, its amount_cents, and a reversed flag (default false)".

    Design: Corner/entities/goal_contribution_immutable_no_version
    """
    ctx = setup_goal_with_funding(allocated_cents=5000, target_cents=20000)
    resp = api.contribute_goal(
        ctx["household"]["id"], ctx["goal"]["id"], {"amount_cents": 2000},
        ctx["owner_headers"],
    )
    data = validate_success(resp, expected_status=201)
    assert data["amount_cents"] == 2000
    assert data["reversed"] is False, f"expected reversed False, got {data['reversed']}"
    assert "version" not in data, "GoalContribution must not carry a version field"
