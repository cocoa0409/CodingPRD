"""The posting lifecycle: holds, the credit ledger, and the rebate schedule."""
from test_helpers import (
    ADMIN,
    MERCHANT,
    UNKNOWN_UUID,
    ApiErrorId,
    assert_credit_ledger_invariant,
    assert_transaction,
    authorize_transaction_payload,
    make_fleet_account,
    read_account,
    read_transaction,
    setup_captured_fills,
    setup_fueling_scenario,
    validate_error,
    validate_success,
)

# The two fills behind the provisional-vs-final divergence: 800 gallons rated at
# month-to-date 800 (tier 0, 5 cpg) but settled at a whole-month 1200 (tier 1, 8 cpg).
_DIVERGENCE_FILLS = [
    {"gallons": 800, "unit_price_cents": 400, "odometer": 10600},
    {"gallons": 400, "unit_price_cents": 400, "odometer": 11000},
]
_DIVERGENCE_VEHICLE = {
    "tank_capacity_gallons": 5000, "expected_mpg_min": 3,
    "expected_mpg_max": 12, "starting_odometer": 10000,
}


def _divergence_scenario(api):
    return setup_captured_fills(
        api, _DIVERGENCE_FILLS,
        account_overrides={"company_name": "Acme Fleet"},
        vehicle_overrides=_DIVERGENCE_VEHICLE,
    )


# --------------------------------------------------------------------------- #
# Provisional rebate (at capture) vs final rebate (at settlement)
# --------------------------------------------------------------------------- #

def test_final_rebate_upgrades_tier_and_diverges_from_provisional(api):
    """PRD §3.5: "Its default is a rate of 5 cents per gallon from 0 gallons, 8
    cents per gallon once month-to-date reaches 1000 gallons, and 12 cents per
    gallon once it reaches 5000 gallons."
    PRD §3.5: "The transaction's `provisional_rebate_cents` is its `gallons`
    multiplied by the selected per-gallon rate, rounded half up to whole cents."
    PRD §3.5: "Settlement recomputes the rebate as `final_rebate_cents` using the
    same tier-selection procedure, except that month-to-date gallons is replaced
    by the whole-month total: the sum of `gallons` across all of the account's
    non-`VOIDED` `CAPTURED`-or-`SETTLED` transactions in this transaction's UTC
    calendar month."
    PRD §3.5: "Because a later purchase can push the month total past a higher
    threshold, the final rate can exceed the provisional one, so
    `final_rebate_cents` can be larger than `provisional_rebate_cents`."

    Design: Difficulty/dual_variant_calc/rebate_provisional_vs_final_diverges_on_transaction
    """
    scenario = _divergence_scenario(api)
    tx1 = scenario["transactions"][0]
    assert tx1["provisional_rebate_cents"] == 4000, "800 gal at the 5 cpg tier 0 rate"

    settled = validate_success(api.settle_transaction(tx1["id"], MERCHANT))

    assert_transaction(settled)
    assert settled["posting_status"] == "SETTLED"
    assert settled["provisional_rebate_cents"] == 4000
    assert settled["final_rebate_cents"] == 6400, (
        "the whole-month total of 1200 gallons selects the 8 cpg tier: 800 * 8"
    )
    assert settled["final_rebate_cents"] != settled["provisional_rebate_cents"], (
        "the two rebate variants must diverge on this transaction"
    )


def test_rebate_accrual_absorbs_the_provisional_to_final_adjustment(api):
    """PRD §3.5: "To rate this transaction, compute its month-to-date gallons: the
    sum of `gallons` over the account's non-`VOIDED` transactions in `CAPTURED` or
    `SETTLED` posting status whose `purchased_at` lies in the same UTC calendar
    month as this transaction, counting those posted so far this month up to and
    including this one."
    PRD §3.5: "That amount is added to the account's `rebate_accrual_cents`."
    PRD §3.5: "The account's `rebate_accrual_cents` is then adjusted by
    `final_rebate_cents` minus `provisional_rebate_cents`."

    Design: Difficulty/dual_variant_calc/rebate_provisional_vs_final_diverges_on_transaction
    """
    scenario = _divergence_scenario(api)
    tx1, tx2 = scenario["transactions"]

    assert tx1["provisional_rebate_cents"] == 4000, (
        "at tx1's capture the month-to-date total is 800 gallons — the 5 cpg tier"
    )
    assert tx2["provisional_rebate_cents"] == 3200, (
        "at tx2's capture the month-to-date total including it is 1200 gallons — "
        "the 8 cpg tier: 400 * 8"
    )
    account = read_account(api, scenario["account"]["id"])
    assert account["rebate_accrual_cents"] == 7200, "4000 + 3200 accrued at capture"

    validate_success(api.settle_transaction(tx1["id"], MERCHANT))

    account = read_account(api, scenario["account"]["id"])
    assert account["rebate_accrual_cents"] == 9600, (
        "settling tx1 adjusts the accrual by final 6400 minus provisional 4000: "
        "7200 + 2400"
    )


# --------------------------------------------------------------------------- #
# Rounding order: round each transaction's rebate, then sum
# --------------------------------------------------------------------------- #

_ROUNDING_FILLS = [
    {"gallons": 12.5, "unit_price_cents": 400, "odometer": 10},
    {"gallons": 12.5, "unit_price_cents": 400, "odometer": 20},
]
_ROUNDING_VEHICLE = {
    "tank_capacity_gallons": 5000, "expected_mpg_min": 3,
    "expected_mpg_max": 30, "starting_odometer": 0,
}


def test_each_transaction_rebate_is_rounded_half_up_individually(api):
    """PRD §2.6: "Where a computation produces a non-integer intermediate — a
    charge in cents, a per-gallon rebate applied to fractional gallons, a
    per-jurisdiction tax — the result is rounded half up to a whole number of
    cents."
    PRD §3.5: "The transaction's `provisional_rebate_cents` is its `gallons`
    multiplied by the selected per-gallon rate, rounded half up to whole cents."

    12.5 gallons at the 5 cpg tier is 62.5 cents, which rounds half up to 63.

    Design: Difficulty/combinatorial_formula/rebate_accrual_round_per_transaction_then_sum
    """
    scenario = setup_captured_fills(
        api, _ROUNDING_FILLS,
        account_overrides={"company_name": "Round Fleet"},
        vehicle_overrides=_ROUNDING_VEHICLE,
    )
    txa, txb = scenario["transactions"]

    assert txa["provisional_rebate_cents"] == 63, "round_half_up(12.5 * 5) == 63"
    assert txb["provisional_rebate_cents"] == 63, "round_half_up(12.5 * 5) == 63"


def test_rebate_accrual_sums_rounded_parts_not_rounded_sum(api):
    """PRD §2.6: "When a total is formed from several rounded parts, each part is
    rounded first and the rounded parts are then summed; the system never sums raw
    quantities and rounds once at the end."
    PRD §3.5: "Throughout, `rebate_accrual_cents` is maintained as the running sum
    of each transaction's individually rounded rebate — rounded per transaction,
    then summed — never by summing gallons first and rounding once."

    Two 12.5-gallon fills at 5 cpg accrue 63 + 63 == 126. The forbidden
    sum-then-round path (25.0 gallons * 5 == 125) differs by one cent.

    Design: Difficulty/combinatorial_formula/rebate_accrual_round_per_transaction_then_sum
    """
    scenario = setup_captured_fills(
        api, _ROUNDING_FILLS,
        account_overrides={"company_name": "Round Fleet"},
        vehicle_overrides=_ROUNDING_VEHICLE,
    )

    account = read_account(api, scenario["account"]["id"])

    assert account["rebate_accrual_cents"] == 126, (
        "63 + 63 == 126; summing gallons first and rounding once would give 125"
    )


# --------------------------------------------------------------------------- #
# Compensation: the rebate liability is conserved across capture -> void
# --------------------------------------------------------------------------- #

def test_void_of_captured_transaction_reverses_its_accrued_rebate(api):
    """PRD §3.5: "That amount is added to the account's `rebate_accrual_cents`."
    PRD §3.5: "Voiding a `CAPTURED` transaction moves it to `VOIDED`, sets
    `hold_amount_cents` to 0, and subtracts the previously accrued
    `provisional_rebate_cents` from the account's `rebate_accrual_cents`."

    Design: Difficulty/compensating_invariant/rebate_accrual_conserved_across_capture_void
    """
    scenario = setup_captured_fills(
        api, [{"gallons": 100, "unit_price_cents": 400, "odometer": 100}],
        account_overrides={"company_name": "Inv1 Fleet"},
    )
    txn = scenario["transactions"][0]
    assert txn["provisional_rebate_cents"] == 500, "100 gal at the 5 cpg tier"

    account = read_account(api, scenario["account"]["id"])
    assert account["rebate_accrual_cents"] == 500, "capture accrues the provisional rebate"

    voided = validate_success(api.void_transaction(txn["id"], MERCHANT))

    assert voided["posting_status"] == "VOIDED"
    account = read_account(api, scenario["account"]["id"])
    assert account["rebate_accrual_cents"] == 0, (
        "void subtracts exactly the 500 it accrued, returning the liability to 0"
    )


def test_void_reverses_only_the_voided_transactions_rebate(api):
    """PRD §3.5: "Voiding a `CAPTURED` transaction moves it to `VOIDED`, sets
    `hold_amount_cents` to 0, and subtracts the previously accrued
    `provisional_rebate_cents` from the account's `rebate_accrual_cents`."
    PRD §3.5: "Throughout, `rebate_accrual_cents` is maintained as the running sum
    of each transaction's individually rounded rebate — rounded per transaction,
    then summed — never by summing gallons first and rounding once."

    Two captured 100-gallon fills accrue 500 each. Voiding one reverses exactly
    that one's 500 and leaves the survivor's 500 standing.

    Design: Difficulty/compensating_invariant/rebate_accrual_conserved_across_capture_void
    """
    scenario = setup_captured_fills(
        api,
        [
            {"gallons": 100, "unit_price_cents": 400, "odometer": 100},
            {"gallons": 100, "unit_price_cents": 400, "odometer": 200},
        ],
        account_overrides={"company_name": "Inv1 Fleet"},
    )
    first, second = scenario["transactions"]
    account = read_account(api, scenario["account"]["id"])
    assert account["rebate_accrual_cents"] == 1000, "500 + 500"

    validate_success(api.void_transaction(first["id"], MERCHANT))

    account = read_account(api, scenario["account"]["id"])
    assert account["rebate_accrual_cents"] == 500, (
        "only the voided transaction's 500 is reversed"
    )
    survivor = read_transaction(api, second["id"])
    assert survivor["posting_status"] == "CAPTURED"
    assert survivor["provisional_rebate_cents"] == 500


# --------------------------------------------------------------------------- #
# Compensation: available credit is conserved across authorize -> void
# --------------------------------------------------------------------------- #

def _credit_scenario(api):
    return setup_fueling_scenario(
        api,
        account_overrides={"company_name": "Inv2 Fleet", "credit_limit_cents": 1_000_000},
        card_overrides={"last4": "0302"},
    )


def test_void_of_authorized_transaction_releases_its_hold(api):
    """PRD §3.4: "A hold equal to the charge is placed: `hold_amount_cents` equals
    `gross_amount_cents` while the transaction is `AUTHORIZED` or `CAPTURED`, and
    becomes 0 once the transaction is `SETTLED` or `VOIDED`."
    PRD §3.5: "Voiding an `AUTHORIZED` transaction moves it to `VOIDED` and sets
    `hold_amount_cents` to 0, releasing the hold; no rebate had been accrued, so
    none is reversed."
    PRD §2.7: "`available_credit_cents` is `credit_limit_cents` minus
    `outstanding_holds_cents` minus `settled_spend_cents`."

    Design: Difficulty/compensating_invariant/available_credit_conserved_across_authorize_void
    """
    scenario = _credit_scenario(api)
    payload = authorize_transaction_payload(
        scenario["card"]["id"], gallons=100, unit_price_cents=400, odometer=100,
    )
    txn = validate_success(api.authorize_transaction(payload, MERCHANT), 201)
    assert txn["gross_amount_cents"] == 40_000
    assert txn["hold_amount_cents"] == 40_000

    voided = validate_success(api.void_transaction(txn["id"], MERCHANT))

    assert voided["posting_status"] == "VOIDED"
    assert voided["hold_amount_cents"] == 0, "voiding releases the credit hold"
    account = read_account(api, scenario["account"]["id"])
    assert account["available_credit_cents"] == 1_000_000, (
        "the released 40000 restores available credit to the whole limit"
    )
    assert account["rebate_accrual_cents"] == 0, "an AUTHORIZED void reverses no rebate"


def test_credit_ledger_conserved_through_authorize_and_void(api):
    """PRD §2.7: "These figures obey a conserved invariant at all times:
    `available_credit_cents` plus `outstanding_holds_cents` plus
    `settled_spend_cents` always equals `credit_limit_cents`."
    PRD §2.7: "`outstanding_holds_cents` is the sum of `gross_amount_cents` over
    the account's transactions whose `posting_status` is `AUTHORIZED` or
    `CAPTURED`."

    Design: Difficulty/compensating_invariant/available_credit_conserved_across_authorize_void
    """
    scenario = _credit_scenario(api)
    account_id = scenario["account"]["id"]

    before = read_account(api, account_id)
    assert_credit_ledger_invariant(before)
    assert before["available_credit_cents"] == 1_000_000

    payload = authorize_transaction_payload(
        scenario["card"]["id"], gallons=100, unit_price_cents=400, odometer=100,
    )
    txn = validate_success(api.authorize_transaction(payload, MERCHANT), 201)

    held = read_account(api, account_id)
    assert_credit_ledger_invariant(held)
    assert held["outstanding_holds_cents"] == 40_000
    assert held["available_credit_cents"] == 960_000, "1000000 - the 40000 hold"

    validate_success(api.void_transaction(txn["id"], MERCHANT))

    after = read_account(api, account_id)
    assert_credit_ledger_invariant(after)
    assert after["outstanding_holds_cents"] == 0
    assert after["available_credit_cents"] == 1_000_000


# --------------------------------------------------------------------------- #
# Single-transaction arithmetic, posting-state guards, and the GL view
# --------------------------------------------------------------------------- #

def test_gross_amount_and_hold_computed_at_authorization(api):
    """PRD §3.4: "The charge, `gross_amount_cents`, is `gallons` multiplied by
    `unit_price_cents`, rounded half up to whole cents."
    PRD §3.4: "A hold equal to the charge is placed: `hold_amount_cents` equals
    `gross_amount_cents` while the transaction is `AUTHORIZED` or `CAPTURED`, and
    becomes 0 once the transaction is `SETTLED` or `VOIDED`."

    Design: Corner/calculations/gross_amount_computed_from_gallons_and_price
    """
    scenario = setup_fueling_scenario(
        api, account_overrides={"company_name": "Gross Co"},
        card_overrides={"last4": "0600"},
    )

    payload = authorize_transaction_payload(
        scenario["card"]["id"], gallons=10, unit_price_cents=431, odometer=50,
    )
    txn = validate_success(api.authorize_transaction(payload, MERCHANT), 201)

    assert_transaction(txn)
    assert txn["gross_amount_cents"] == 4310, "10 * 431"
    assert txn["hold_amount_cents"] == 4310


def test_authorization_hold_visible_on_the_account_immediately(api):
    """PRD §2.7: "`outstanding_holds_cents` is the sum of `gross_amount_cents` over
    the account's transactions whose `posting_status` is `AUTHORIZED` or
    `CAPTURED`."
    PRD §2.7: "`available_credit_cents` is `credit_limit_cents` minus
    `outstanding_holds_cents` minus `settled_spend_cents`."

    Design: Corner/consistency_model/authorization_hold_visible_immediately
    """
    scenario = setup_fueling_scenario(
        api,
        account_overrides={"company_name": "Imm Co", "credit_limit_cents": 1_000_000},
        card_overrides={"last4": "1002"},
    )
    payload = authorize_transaction_payload(
        scenario["card"]["id"], gallons=10, unit_price_cents=400, odometer=10,
    )
    validate_success(api.authorize_transaction(payload, MERCHANT), 201)

    account = validate_success(api.get_fleet_account(scenario["account"]["id"], ADMIN))

    assert account["outstanding_holds_cents"] == 4000
    assert account["available_credit_cents"] == 996_000, "1000000 - the 4000 hold"
    assert_credit_ledger_invariant(account)


def test_capture_of_settled_transaction_rejected(api):
    """PRD §3.5: "A `Merchant` captures an `AUTHORIZED` transaction, moving
    `posting_status` to `CAPTURED`; capturing anything not `AUTHORIZED` is rejected
    with `ERR_INVALID_TXN_STATE`."
    PRD §3.5: "A `Merchant` settles a `CAPTURED` transaction, moving
    `posting_status` to `SETTLED`; settling anything not `CAPTURED` is rejected with
    `ERR_INVALID_TXN_STATE`."

    Design: Corner/state_machines/capture_already_settled_transaction_rejected
    """
    scenario = setup_captured_fills(
        api, [{"gallons": 100, "unit_price_cents": 400, "odometer": 100}],
        account_overrides={"company_name": "Inv Txn Co"},
        card_overrides={"last4": "0500"},
    )
    txn = scenario["transactions"][0]
    settled = validate_success(api.settle_transaction(txn["id"], MERCHANT))
    assert settled["posting_status"] == "SETTLED"

    resp = api.capture_transaction(txn["id"], MERCHANT)

    validate_error(resp, ApiErrorId.ERR_INVALID_TXN_STATE.value)
    unchanged = read_transaction(api, txn["id"])
    assert unchanged["posting_status"] == "SETTLED", "the rejected capture fired no side effects"


def test_capture_of_unknown_transaction_not_found(api):
    """PRD §2.9: "When a request references resources by path segment or by
    foreign-key body field, each referenced resource must exist; existence is
    checked left to right, and the first missing reference produces the
    corresponding not-found error (`ERR_FLEET_ACCOUNT_NOT_FOUND`,
    `ERR_VEHICLE_NOT_FOUND`, `ERR_DRIVER_NOT_FOUND`, `ERR_CARD_NOT_FOUND`,
    `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_TRANSACTION_NOT_FOUND`, `ERR_ALERT_NOT_FOUND`,
    `ERR_FAULT_NOT_FOUND`, or `ERR_REPORT_NOT_FOUND`, all 404)."

    Design: Corner/errors/transaction_not_found_triggerable
    """
    resp = api.capture_transaction(UNKNOWN_UUID, MERCHANT)

    validate_error(resp, ApiErrorId.ERR_TRANSACTION_NOT_FOUND.value)


def test_fleet_summary_exposes_ledger_snapshot_and_gl_lines(api):
    """PRD §3.1: "Anyone may retrieve an account; the account's GL/expense-export
    view additionally returns the ledger snapshot (`available_credit_cents`,
    `outstanding_holds_cents`, `settled_spend_cents`, `rebate_accrual_cents`)
    alongside `gl_lines`, an array of per-transaction expense lines for accounting
    export."

    Design: Corner/endpoints/fleet_summary_returns_gl_lines
    """
    account = make_fleet_account(api, company_name="Sum Co", credit_limit_cents=700_000)

    summary = validate_success(api.get_fleet_account_summary(account["id"], ADMIN))

    assert summary["available_credit_cents"] == 700_000
    assert summary["outstanding_holds_cents"] == 0
    assert summary["settled_spend_cents"] == 0
    assert summary["rebate_accrual_cents"] == 0
    assert summary["gl_lines"] == [], "no transactions means no per-transaction expense lines"
