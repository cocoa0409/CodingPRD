"""Price plans: activation cascade, derived-field reconciliation, and activation
guards.

Translates queue B (Corner) instances from `state_machines` (PricePlan) and
`validations` (plan pricing / market-price requirements).
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    create_price_plan_payload,
)
from test_helpers import fixtures as fx

AM = TEST_USERS["account_manager_headers"]


def test_priceplan_activate_expires_prior_active(api):
    """PRD §3.2: "any plan that was previously `ACTIVE` on the same account is moved `ACTIVE → EXPIRED`, the account's `active_price_plan_id` is reconciled to point at the newly active plan"

    Design: Corner/state_machines/priceplan_activate_expires_prior_active
    """
    account = fx.create_account(customer_name="Plan Pam")
    plan1 = validate_success(api.create_price_plan(
        account["id"],
        create_price_plan_payload(plan_type="FIXED", locked_price_cents_per_gallon=300),
        AM), expected_status=201)
    validate_success(api.activate_price_plan(account["id"], plan1["id"], AM))
    plan2 = validate_success(api.create_price_plan(
        account["id"],
        create_price_plan_payload(plan_type="FIXED", locked_price_cents_per_gallon=280),
        AM), expected_status=201)
    validate_success(api.activate_price_plan(account["id"], plan2["id"], AM))

    p1 = validate_success(api.get_price_plan(plan1["id"], AM))
    assert p1["status"] == "EXPIRED"
    acct = validate_success(api.get_account(account["id"], AM))
    assert acct["active_price_plan_id"] == plan2["id"]


def test_activate_market_plan_without_market_price_rejected(api):
    """PRD §3.2: "activating a `MARKET` plan when no `ACTIVE` `MarketPrice` exists for the account's `region_code` and `fuel_type` pairing is rejected with `ERR_NO_MARKET_PRICE`."

    Design: Corner/validations/activate_market_plan_without_market_price_rejected
    """
    account = fx.create_account(region_code="NE_09", fuel_type="PROPANE",
                                customer_name="NoMkt Mo")
    plan = validate_success(api.create_price_plan(
        account["id"], create_price_plan_payload(plan_type="MARKET"), AM),
        expected_status=201)
    resp = api.activate_price_plan(account["id"], plan["id"], AM)
    validate_error(resp, ApiErrorId.ERR_NO_MARKET_PRICE.value)


def test_activate_fixed_plan_without_price_rejected(api):
    """PRD §3.2: "activating a `FIXED` plan whose `locked_price_cents_per_gallon` is unset, or a `CAP` plan whose `cap_price_cents_per_gallon` is unset, is rejected with `ERR_PLAN_PRICE_REQUIRED"

    Design: Corner/validations/activate_fixed_plan_without_price_rejected
    """
    account = fx.create_account(customer_name="NoPrice Pia")
    plan = validate_success(api.create_price_plan(
        account["id"], create_price_plan_payload(plan_type="FIXED"), AM),
        expected_status=201)
    resp = api.activate_price_plan(account["id"], plan["id"], AM)
    validate_error(resp, ApiErrorId.ERR_PLAN_PRICE_REQUIRED.value)
