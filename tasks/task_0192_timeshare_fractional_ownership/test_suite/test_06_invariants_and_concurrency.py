"""Compensating invariants, optimistic concurrency, banking, rollover, and
immediate-consistency reads.

Difficulty: compensating_invariant (points conservation; receivables
conservation). Corner: OCC stale-version on reservation create and on bank;
banking effects; bank-over-available rejection; rollover; immediate consistency.
"""
from test_helpers import (
    get_success_data, validate_error,
    ApiErrorId,
    create_resort, create_owner, create_inventory_unit, create_active_contract,
    create_issued_invoice, setup_active_contract_with_unit, get_points_account,
    create_reservation_payload, bank_points_payload, create_payment_payload,
    make_owner_headers, TEST_USERS,
)

_RM = TEST_USERS["resort_manager_headers"]


# =========================================================================== #
# Difficulty: compensating_invariant — points conservation (confirm then cancel)
# =========================================================================== #
def test_points_conserved_confirm_then_cancel(api):
    """PRD §3.4: "the source points account's `committed_points` increases by the non-borrowed portion
    of the cost (the `points_cost` minus the `borrowed_points`)".
    PRD §3.5: "Cancelling a `CONFIRMED` reservation marks it `CANCELLED` and unwinds the
    commitments made at confirm: the unit's `status` returns to `AVAILABLE`, the
    source account's `committed_points` is reduced by the non-borrowed portion (the
    `points_cost` minus the `borrowed_points`) as compensation".

    Design: Difficulty/compensating_invariant/points_conservation_confirm_then_cancel
    """
    resort, owner, contract, unit = setup_active_contract_with_unit(
        season="GOLD", week_number=12, contract_overrides={"annual_points_allotment": 5000})
    headers = make_owner_headers(owner["id"])
    acct = get_points_account(contract["id"], 2026, owner["id"])
    assert acct["available_points"] == 5000, f"pre-confirm available 5000, got {acct['available_points']}"

    resv = get_success_data(api.create_reservation(
        create_reservation_payload(contract["id"], unit["id"], 2026, acct["version"]), headers))
    get_success_data(api.confirm_reservation(resv["id"], headers))

    after_confirm = get_success_data(api.get_points_account(acct["id"], headers))
    assert after_confirm["committed_points"] == 1000, \
        f"committed 1000 after confirm, got {after_confirm['committed_points']}"
    assert after_confirm["available_points"] == 4000, \
        f"available 4000 after confirm, got {after_confirm['available_points']}"

    get_success_data(api.cancel_reservation(resv["id"], headers))
    after_cancel = get_success_data(api.get_points_account(acct["id"], headers))
    assert after_cancel["committed_points"] == 0, \
        f"committed 0 after cancel, got {after_cancel['committed_points']}"
    assert after_cancel["available_points"] == 5000, \
        f"available restored to 5000 (no drift), got {after_cancel['available_points']}"


def test_held_cancel_leaves_points_unchanged(api):
    """PRD §3.5: "Cancelling a `HELD` reservation simply marks it `CANCELLED`; because no points were
    committed at hold time, no points balances change."
    PRD §3.3: "The reported `available_points` is a derived figure: it is `allotment_points` plus
    `banked_in_points`, minus `banked_out_points`, minus `borrowed_out_points`,
    minus `committed_points`."

    Design: Difficulty/compensating_invariant/points_conservation_confirm_then_cancel
    """
    resort, owner, contract, unit = setup_active_contract_with_unit(
        season="GOLD", week_number=13, contract_overrides={"annual_points_allotment": 5000})
    headers = make_owner_headers(owner["id"])
    acct = get_points_account(contract["id"], 2026, owner["id"])
    resv = get_success_data(api.create_reservation(
        create_reservation_payload(contract["id"], unit["id"], 2026, acct["version"]), headers))
    # Cancel while still HELD (no commitment was made).
    get_success_data(api.cancel_reservation(resv["id"], headers))
    after = get_success_data(api.get_points_account(acct["id"], headers))
    assert after["committed_points"] == 0, f"committed must stay 0, got {after['committed_points']}"
    assert after["available_points"] == 5000, \
        f"available unchanged at 5000, got {after['available_points']}"


# =========================================================================== #
# Difficulty: compensating_invariant — receivables conservation (clear then reverse)
# =========================================================================== #
def test_receivables_conserved_clear_then_reverse(api):
    """PRD §3.7: "Each invoice whose `amount_due_cents` reaches 0 transitions to `PAID` as a cascade."
    PRD §3.7: "A `ResortManager` may reverse a `CLEARED` payment, moving it to `REVERSED`: this
    undoes the allocations by reducing each previously-credited invoice's
    `amount_paid_cents`, reverting any `PAID` invoice back to `ISSUED` (or to
    `DELINQUENT` if it is now past grace)".

    Design: Difficulty/compensating_invariant/receivables_conservation_payment_clear_then_reverse
    """
    resort = create_resort(points_per_week_base=1000, annual_fee_cents_per_1000_points=20000)
    owner = create_owner(resort["id"])
    contract = create_active_contract(resort["id"], owner["id"], annual_points_allotment=10000)
    invoice = create_issued_invoice(resort, contract, use_year=2026)  # 200000, ISSUED

    payment = get_success_data(api.create_payment(
        create_payment_payload(contract["id"], 200000, invoice_id=invoice["id"]), _RM))
    get_success_data(api.clear_payment(payment["id"], _RM))

    cleared_inv = get_success_data(api.get_invoice(invoice["id"], _RM))
    assert cleared_inv["status"] == "PAID", f"invoice PAID after clear, got {cleared_inv['status']}"
    assert cleared_inv["amount_due_cents"] == 0
    assert cleared_inv["amount_paid_cents"] == 200000

    get_success_data(api.reverse_payment(payment["id"], _RM))
    reversed_inv = get_success_data(api.get_invoice(invoice["id"], _RM))
    # Clock is at 2026-01-08 (within grace) so revert target is ISSUED.
    assert reversed_inv["status"] == "ISSUED", f"invoice reverts to ISSUED, got {reversed_inv['status']}"
    assert reversed_inv["amount_due_cents"] == 200000, \
        f"receivable restored to 200000, got {reversed_inv['amount_due_cents']}"
    assert reversed_inv["amount_paid_cents"] == 0, \
        f"amount_paid restored to 0, got {reversed_inv['amount_paid_cents']}"


def test_partial_payment_reduces_due_without_marking_paid(api):
    """PRD §3.7: "an `amount_paid_cents` accumulator (the sum of cleared payment allocations, starting
    at 0), and a derived `amount_due_cents` equal to `amount_cents` plus
    `late_charge_cents` minus `amount_paid_cents`."
    PRD §3.7: "Each invoice whose `amount_due_cents` reaches 0 transitions to `PAID` as a cascade."

    Design: Difficulty/compensating_invariant/receivables_conservation_payment_clear_then_reverse
    """
    # Forward leg with a partial allocation: amount_paid accumulates, amount_due
    # drops, but the invoice stays ISSUED because due has not reached 0.
    resort = create_resort(points_per_week_base=1000, annual_fee_cents_per_1000_points=20000)
    owner = create_owner(resort["id"])
    contract = create_active_contract(resort["id"], owner["id"], annual_points_allotment=10000)
    invoice = create_issued_invoice(resort, contract, use_year=2026)  # 200000

    payment = get_success_data(api.create_payment(
        create_payment_payload(contract["id"], 50000, invoice_id=invoice["id"]), _RM))
    get_success_data(api.clear_payment(payment["id"], _RM))
    inv = get_success_data(api.get_invoice(invoice["id"], _RM))
    assert inv["amount_paid_cents"] == 50000, f"amount_paid 50000, got {inv['amount_paid_cents']}"
    assert inv["amount_due_cents"] == 150000, f"amount_due 150000, got {inv['amount_due_cents']}"
    assert inv["status"] == "ISSUED", f"still ISSUED (not fully paid), got {inv['status']}"


# =========================================================================== #
# Corner: cross_cutting — OCC stale version on reservation create
# =========================================================================== #
def test_stale_version_on_second_reservation_create(api):
    """PRD §2.9: "Creating a reservation requires the request to carry
    `expected_points_account_version`, which must equal the current `version` of the
    source-use-year `PointsAccount` the reservation will draw from."
    PRD §3.4: "Creating the reservation increments the source use-year `PointsAccount`'s `version`
    by one."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_reservation_create
    """
    resort = create_resort(points_per_week_base=1000, annual_fee_cents_per_1000_points=20000)
    owner = create_owner(resort["id"])
    unit1 = create_inventory_unit(resort["id"], unit_label="U1", week_number=11, season="GOLD")
    unit2 = create_inventory_unit(resort["id"], unit_label="U2", week_number=12, season="GOLD")
    contract = create_active_contract(resort["id"], owner["id"], annual_points_allotment=5000)

    acct = get_points_account(contract["id"], 2026, owner["id"])
    v0 = acct["version"]
    headers = make_owner_headers(owner["id"])
    # First create bumps the account version.
    get_success_data(api.create_reservation(
        create_reservation_payload(contract["id"], unit1["id"], 2026, v0), headers))
    acct_after = get_success_data(api.get_points_account(acct["id"], headers))
    assert acct_after["version"] == v0 + 1, f"version must bump to {v0+1}, got {acct_after['version']}"

    # Second create with the stale v0 -> ERR_STALE_VERSION.
    resp = api.create_reservation(
        create_reservation_payload(contract["id"], unit2["id"], 2026, v0), headers)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


# =========================================================================== #
# Corner: cross_cutting — OCC stale version on bank
# =========================================================================== #
def test_stale_version_on_second_bank(api):
    """PRD §2.9: "Banking points forward likewise requires `expected_points_account_version` to equal
    the targeted account's current `version`; if the account has moved since the
    client observed it, the bank is rejected with `ERR_STALE_VERSION` (HTTP 412)".
    PRD §3.3: "The bank increments the source `PointsAccount`'s `version` by one."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_bank_points
    """
    resort = create_resort(points_per_week_base=1000, annual_fee_cents_per_1000_points=20000)
    owner = create_owner(resort["id"])
    contract = create_active_contract(resort["id"], owner["id"], annual_points_allotment=5000)
    acct = get_points_account(contract["id"], 2026, owner["id"])
    v0 = acct["version"]
    headers = make_owner_headers(owner["id"])

    first = get_success_data(api.bank_points(acct["id"], bank_points_payload(500, v0), headers))
    assert first["banked_out_points"] == 500
    assert first["version"] == v0 + 1, f"version must bump to {v0+1}, got {first['version']}"

    resp = api.bank_points(acct["id"], bank_points_payload(500, v0), headers)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)
    after = get_success_data(api.get_points_account(acct["id"], headers))
    assert after["banked_out_points"] == 500, \
        f"banked_out_points unchanged at 500, got {after['banked_out_points']}"


# =========================================================================== #
# Corner: endpoints — banking effects
# =========================================================================== #
def test_bank_reduces_available_and_credits_next_year(api):
    """PRD §3.3: "A successful bank increases the source account's `banked_out_points` by the banked
    `points` (which lowers its `available_points` by the same amount), and increases
    the next use-year account's `banked_in_points` by that same `points` quantity,
    creating the next-year account for the contract if it does not yet exist."

    Design: Corner/endpoints/bank_points_reduces_available_and_credits_next_year
    """
    resort = create_resort(points_per_week_base=1000, annual_fee_cents_per_1000_points=20000)
    owner = create_owner(resort["id"])
    contract = create_active_contract(resort["id"], owner["id"], annual_points_allotment=5000)
    acct = get_points_account(contract["id"], 2026, owner["id"])
    headers = make_owner_headers(owner["id"])

    banked = get_success_data(api.bank_points(acct["id"], bank_points_payload(1500, acct["version"]), headers))
    assert banked["banked_out_points"] == 1500, f"banked_out 1500, got {banked['banked_out_points']}"
    assert banked["available_points"] == 3500, f"available 3500, got {banked['available_points']}"

    next_acct = get_points_account(contract["id"], 2027, owner["id"])
    assert next_acct["banked_in_points"] == 1500, \
        f"2027 banked_in 1500, got {next_acct['banked_in_points']}"


def test_bank_exceeding_available_rejected(api):
    """PRD §3.3: "The banked amount cannot exceed the account's `available_points`; a request to bank
    more than is available is rejected with `ERR_INSUFFICIENT_POINTS`."

    Design: Corner/endpoints/bank_points_exceeding_available_rejected
    """
    resort = create_resort(points_per_week_base=1000, annual_fee_cents_per_1000_points=20000)
    owner = create_owner(resort["id"])
    contract = create_active_contract(resort["id"], owner["id"], annual_points_allotment=5000)
    acct = get_points_account(contract["id"], 2026, owner["id"])
    headers = make_owner_headers(owner["id"])
    resp = api.bank_points(acct["id"], bank_points_payload(6000, acct["version"]), headers)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_POINTS.value)
    after = get_success_data(api.get_points_account(acct["id"], headers))
    assert after["banked_out_points"] == 0, f"banked_out must stay 0, got {after['banked_out_points']}"


# =========================================================================== #
# Corner: cross_cutting — scheduled rollover
# =========================================================================== #
def test_rollover_advances_year_rolls_account_expires_held(api):
    """PRD §3.10: "Rolling over advances the resort's `current_use_year` by one".
    PRD §3.10: "every `OPEN` `PointsAccount` in the closing year is moved to `ROLLED_OVER".
    PRD §3.10: "every still-`HELD` reservation on the closing year is expired, moving from `HELD` to
    `EXPIRED`."

    Design: Corner/cross_cutting_complexity_layers/scheduled_rollover_expires_held_and_rolls_accounts
    """
    resort, owner, contract, unit = setup_active_contract_with_unit(
        season="GOLD", week_number=14, contract_overrides={"annual_points_allotment": 5000})
    acct = get_points_account(contract["id"], 2026, owner["id"])
    headers = make_owner_headers(owner["id"])
    resv = get_success_data(api.create_reservation(
        create_reservation_payload(contract["id"], unit["id"], 2026, acct["version"]), headers))
    assert resv["status"] == "HELD"

    rolled = get_success_data(api.rollover_use_year(resort["id"], _RM))
    assert rolled["current_use_year"] == 2027, \
        f"current_use_year -> 2027, got {rolled['current_use_year']}"
    acct_after = get_success_data(api.get_points_account(acct["id"], headers))
    assert acct_after["status"] == "ROLLED_OVER", \
        f"closing account ROLLED_OVER, got {acct_after['status']}"
    resv_after = get_success_data(api.get_reservation(resv["id"], headers))
    assert resv_after["status"] == "EXPIRED", \
        f"HELD reservation EXPIRED, got {resv_after['status']}"


# =========================================================================== #
# Corner: consistency_model — immediate visibility
# =========================================================================== #
def test_confirm_committed_points_visible_immediately(api):
    """PRD §3.4: "the source points account's `committed_points` increases by the non-borrowed portion
    of the cost (the `points_cost` minus the `borrowed_points`)".
    PRD §3.3: "The reported `available_points` is a derived figure: it is `allotment_points` plus
    `banked_in_points`, minus `banked_out_points`, minus `borrowed_out_points`,
    minus `committed_points`."

    Design: Corner/consistency_model/immediate_consistency_confirm_reflected_in_same_response
    """
    resort, owner, contract, unit = setup_active_contract_with_unit(
        season="GOLD", week_number=16, contract_overrides={"annual_points_allotment": 5000})
    headers = make_owner_headers(owner["id"])
    acct = get_points_account(contract["id"], 2026, owner["id"])
    resv = get_success_data(api.create_reservation(
        create_reservation_payload(contract["id"], unit["id"], 2026, acct["version"]), headers))
    get_success_data(api.confirm_reservation(resv["id"], headers))

    fetched = get_success_data(api.get_points_account(acct["id"], headers))
    assert fetched["committed_points"] == 1000, \
        f"committed 1000 visible immediately, got {fetched['committed_points']}"
    assert fetched["available_points"] == 4000, \
        f"available 4000 visible immediately, got {fetched['available_points']}"
