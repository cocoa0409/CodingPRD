"""Authorization-time purchase controls: card state, assignment resolution,
product whitelist, hour window, gallon cap, and the two fiscal gates."""
import pytest

from test_helpers import (
    MERCHANT,
    ApiErrorId,
    assert_transaction,
    authorize_transaction_payload,
    setup_fueling_scenario,
    validate_error,
    validate_success,
)


# --------------------------------------------------------------------------- #
# Per-transaction gallon cap — the boundary is `<=`
# --------------------------------------------------------------------------- #

def _gallon_limited_scenario(api):
    return setup_fueling_scenario(
        api,
        vehicle_overrides={"tank_capacity_gallons": 5000},
        card_overrides={"last4": "0100", "per_txn_gallon_limit": 100},
    )


@pytest.mark.parametrize("gallons", [99.5, 100])
def test_gallons_at_or_below_per_txn_limit_authorized(api, gallons):
    """PRD §3.4: "The `gallons` must not exceed `per_txn_gallon_limit`; exactly
    equal is allowed, strictly greater is rejected with `ERR_GALLON_LIMIT_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/gallon_limit_boundary_inclusive_vs_strict
    """
    scenario = _gallon_limited_scenario(api)

    payload = authorize_transaction_payload(
        scenario["card"]["id"], gallons=gallons, unit_price_cents=400, odometer=10,
    )
    txn = validate_success(api.authorize_transaction(payload, MERCHANT), 201)

    assert_transaction(txn)
    assert txn["posting_status"] == "AUTHORIZED"
    assert txn["gallons"] == gallons


def test_gallons_above_per_txn_limit_rejected(api):
    """PRD §3.4: "The `gallons` must not exceed `per_txn_gallon_limit`; exactly
    equal is allowed, strictly greater is rejected with `ERR_GALLON_LIMIT_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/gallon_limit_boundary_inclusive_vs_strict
    """
    scenario = _gallon_limited_scenario(api)

    payload = authorize_transaction_payload(
        scenario["card"]["id"], gallons=100.5, unit_price_cents=400, odometer=20,
    )
    resp = api.authorize_transaction(payload, MERCHANT)

    validate_error(resp, ApiErrorId.ERR_GALLON_LIMIT_EXCEEDED.value)


# --------------------------------------------------------------------------- #
# Precedence: transition state (rank 5) pre-empts the daily fiscal gate (rank 15)
# --------------------------------------------------------------------------- #

def _tiny_daily_limit_scenario(api, suspend=False):
    scenario = setup_fueling_scenario(
        api,
        card_overrides={"last4": "9999", "daily_dollar_limit_cents": 1000},
    )
    if suspend:
        suspended = validate_success(
            api.suspend_fuel_card(scenario["card"]["id"], scenario["fm"])
        )
        assert suspended["status"] == "SUSPENDED"
        scenario["card"] = suspended
    return scenario


def test_suspended_card_beats_daily_limit_on_authorize(api):
    """PRD §2.9: "Validations are evaluated in a fixed precedence so that a
    lower-ranked failure can never be masked by a higher-ranked one."
    PRD §2.9: "5. **Transition state** — the target is in a state that permits the
    requested transition, else the applicable state error: `ERR_CARD_NOT_ACTIVE`,
    `ERR_INVALID_CARD_STATE`, `ERR_INVALID_TXN_STATE`, `ERR_INVALID_ALERT_STATE`,
    `ERR_INVALID_FAULT_STATE`, or `ERR_INVALID_REPORT_STATE` (all 409)."
    PRD §2.9: "15. **Daily spend control** — on authorize, the card's same-UTC-day
    held-plus-settled spend plus this charge does not exceed
    `daily_dollar_limit_cents`, else `ERR_DAILY_LIMIT_EXCEEDED` (402)."

    The charge (40000 cents) also blows the card's 1000-cent daily cap, but the
    card is SUSPENDED and the state check ranks ahead of the fiscal one.

    Design: Difficulty/priority_pair_validation_conflict/card_state_beats_daily_fiscal_on_authorize
    """
    scenario = _tiny_daily_limit_scenario(api, suspend=True)

    payload = authorize_transaction_payload(
        scenario["card"]["id"], gallons=100, unit_price_cents=400, odometer=10,
    )
    resp = api.authorize_transaction(payload, MERCHANT)

    validate_error(resp, ApiErrorId.ERR_CARD_NOT_ACTIVE.value)


def test_daily_limit_surfaces_once_card_state_passes(api):
    """PRD §2.9: "Validations are evaluated in a fixed precedence so that a
    lower-ranked failure can never be masked by a higher-ranked one."
    PRD §3.4: "First, the card's daily control: the sum of this card's
    held-and-settled spend within the same UTC calendar day as `purchased_at`,
    plus this `gross_amount_cents`, must not exceed the card's
    `daily_dollar_limit_cents`, else `ERR_DAILY_LIMIT_EXCEEDED` (402)."

    Same 40000-cent charge against the same 1000-cent daily cap, but with the
    card left ACTIVE: the daily gate is the one that fires, proving the state
    error in the companion test genuinely pre-empted it.

    Design: Difficulty/priority_pair_validation_conflict/card_state_beats_daily_fiscal_on_authorize
    """
    scenario = _tiny_daily_limit_scenario(api, suspend=False)

    payload = authorize_transaction_payload(
        scenario["card"]["id"], gallons=100, unit_price_cents=400, odometer=10,
    )
    resp = api.authorize_transaction(payload, MERCHANT)

    validate_error(resp, ApiErrorId.ERR_DAILY_LIMIT_EXCEEDED.value)


# --------------------------------------------------------------------------- #
# Precedence: active-assignment (rank 7) pre-empts product control (rank 8)
# --------------------------------------------------------------------------- #

def test_missing_assignment_beats_product_control_on_authorize(api):
    """PRD §2.9: "Validations are evaluated in a fixed precedence so that a
    lower-ranked failure can never be masked by a higher-ranked one."
    PRD §2.9: "7. **Active assignment** — on authorize, an `ACTIVE` card
    assignment for the card covers `purchased_at` (resolving the transaction's
    vehicle and driver), else `ERR_NO_ACTIVE_ASSIGNMENT` (409)."
    PRD §2.9: "8. **Product control** — on authorize, the purchased `product` is
    in the card's `allowed_products`, else `ERR_PRODUCT_NOT_ALLOWED` (422)."

    UNLEADED is not on this DIESEL-only card AND the card has no assignment; the
    referential check ranks ahead of the product check.

    Design: Difficulty/priority_pair_validation_conflict/no_assignment_referential_beats_product_safety
    """
    scenario = setup_fueling_scenario(
        api,
        card_overrides={"last4": "0001", "allowed_products": ["DIESEL"]},
        create_assignment=False,
    )

    payload = authorize_transaction_payload(
        scenario["card"]["id"], product="UNLEADED", gallons=100,
        unit_price_cents=400, odometer=10,
    )
    resp = api.authorize_transaction(payload, MERCHANT)

    validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_ASSIGNMENT.value)


def test_product_control_surfaces_once_assignment_resolves(api):
    """PRD §2.9: "Validations are evaluated in a fixed precedence so that a
    lower-ranked failure can never be masked by a higher-ranked one."
    PRD §3.4: "The `product` must appear in the card's `allowed_products`, else
    `ERR_PRODUCT_NOT_ALLOWED`."

    The identical UNLEADED authorize on the identical DIESEL-only card, but with
    an ACTIVE assignment in place: the lower-ranked product check now fires,
    proving the referential error in the companion test masked it.

    Design: Difficulty/priority_pair_validation_conflict/no_assignment_referential_beats_product_safety
    """
    scenario = setup_fueling_scenario(
        api, card_overrides={"last4": "0001", "allowed_products": ["DIESEL"]},
    )

    payload = authorize_transaction_payload(
        scenario["card"]["id"], product="UNLEADED", gallons=100,
        unit_price_cents=400, odometer=10,
    )
    resp = api.authorize_transaction(payload, MERCHANT)

    validate_error(resp, ApiErrorId.ERR_PRODUCT_NOT_ALLOWED.value)


# --------------------------------------------------------------------------- #
# Authorization depends on the card's lifecycle state
# --------------------------------------------------------------------------- #

def test_authorize_on_issued_card_rejected(api):
    """PRD §3.4: "The card must be `ACTIVE`, else `ERR_CARD_NOT_ACTIVE`."
    PRD §3.2: "A card's `status` is system-managed and moves through `ISSUED`,
    `ACTIVE`, `SUSPENDED`, and the terminal `CANCELLED`, starting at `ISSUED`."

    Design: Difficulty/cross_entity_state_dependency/authorize_requires_card_active
    """
    scenario = setup_fueling_scenario(api, card_overrides={"last4": "0111"},
                                      activate_card=False)
    assert scenario["card"]["status"] == "ISSUED"

    payload = authorize_transaction_payload(
        scenario["card"]["id"], gallons=100, unit_price_cents=400, odometer=10,
    )
    resp = api.authorize_transaction(payload, MERCHANT)

    validate_error(resp, ApiErrorId.ERR_CARD_NOT_ACTIVE.value)


def test_authorize_succeeds_once_the_same_card_is_activated(api):
    """PRD §3.4: "The card must be `ACTIVE`, else `ERR_CARD_NOT_ACTIVE`."
    PRD §3.2: "A `FleetManager` activates a card that is currently `ISSUED` or
    `SUSPENDED`, moving it to `ACTIVE` and incrementing its `version`; activating
    a card that is `SUSPENDED` is a reinstatement."

    Design: Difficulty/cross_entity_state_dependency/authorize_requires_card_active
    """
    scenario = setup_fueling_scenario(api, card_overrides={"last4": "0111"},
                                      activate_card=False)
    card_id = scenario["card"]["id"]

    activated = validate_success(api.activate_fuel_card(card_id, scenario["fm"]))
    assert activated["status"] == "ACTIVE"

    payload = authorize_transaction_payload(
        card_id, gallons=100, unit_price_cents=400, odometer=20,
    )
    txn = validate_success(api.authorize_transaction(payload, MERCHANT), 201)

    assert_transaction(txn)
    assert txn["posting_status"] == "AUTHORIZED"
    assert txn["vehicle_id"] == scenario["vehicle"]["id"]
    assert txn["driver_id"] == scenario["driver"]["id"]


# --------------------------------------------------------------------------- #
# The remaining purchase controls, each in isolation
# --------------------------------------------------------------------------- #

def test_purchase_outside_allowed_hours_rejected(api):
    """PRD §3.4: "The UTC hour of `purchased_at` must fall in the card's permitted
    window — at least `allowed_start_hour` and strictly less than
    `allowed_end_hour` — else `ERR_OUTSIDE_ALLOWED_HOURS`."

    Design: Corner/validations/outside_allowed_hours_rejected
    """
    scenario = setup_fueling_scenario(
        api,
        clock="2026-06-01T03:00:00Z",
        card_overrides={"last4": "0700", "allowed_start_hour": 6, "allowed_end_hour": 18},
    )

    payload = authorize_transaction_payload(
        scenario["card"]["id"], gallons=10, unit_price_cents=400, odometer=10,
    )
    resp = api.authorize_transaction(payload, MERCHANT)

    validate_error(resp, ApiErrorId.ERR_OUTSIDE_ALLOWED_HOURS.value)


def test_product_not_in_allowed_products_rejected(api):
    """PRD §3.4: "The `product` must appear in the card's `allowed_products`, else
    `ERR_PRODUCT_NOT_ALLOWED`."

    Design: Corner/validations/product_not_allowed_with_valid_assignment
    """
    scenario = setup_fueling_scenario(
        api, card_overrides={"last4": "0701", "allowed_products": ["DIESEL"]},
    )

    payload = authorize_transaction_payload(
        scenario["card"]["id"], product="UNLEADED", gallons=10,
        unit_price_cents=400, odometer=10,
    )
    resp = api.authorize_transaction(payload, MERCHANT)

    validate_error(resp, ApiErrorId.ERR_PRODUCT_NOT_ALLOWED.value)


def test_charge_exceeding_available_credit_rejected(api):
    """PRD §3.4: "Second, the account's credit: `available_credit_cents` must be at
    least this `gross_amount_cents`, else `ERR_CREDIT_EXCEEDED` (402)."

    The card's daily cap is deliberately huge so only the account credit gate can
    fail: a 40000-cent charge against a 1000-cent credit limit.

    Design: Corner/validations/credit_exceeded_rejected
    """
    scenario = setup_fueling_scenario(
        api,
        account_overrides={"company_name": "Credit Co", "credit_limit_cents": 1000},
        card_overrides={"last4": "0702"},
    )

    payload = authorize_transaction_payload(
        scenario["card"]["id"], gallons=100, unit_price_cents=400, odometer=10,
    )
    resp = api.authorize_transaction(payload, MERCHANT)

    validate_error(resp, ApiErrorId.ERR_CREDIT_EXCEEDED.value)


def test_charge_exceeding_card_daily_limit_rejected(api):
    """PRD §3.4: "First, the card's daily control: the sum of this card's
    held-and-settled spend within the same UTC calendar day as `purchased_at`,
    plus this `gross_amount_cents`, must not exceed the card's
    `daily_dollar_limit_cents`, else `ERR_DAILY_LIMIT_EXCEEDED` (402)."

    Account credit is ample, so only the card's 1000-cent daily cap can fail
    against this 40000-cent charge.

    Design: Corner/errors/daily_limit_exceeded_triggerable
    """
    scenario = setup_fueling_scenario(
        api, card_overrides={"last4": "0900", "daily_dollar_limit_cents": 1000},
    )

    payload = authorize_transaction_payload(
        scenario["card"]["id"], gallons=100, unit_price_cents=400, odometer=10,
    )
    resp = api.authorize_transaction(payload, MERCHANT)

    validate_error(resp, ApiErrorId.ERR_DAILY_LIMIT_EXCEEDED.value)
