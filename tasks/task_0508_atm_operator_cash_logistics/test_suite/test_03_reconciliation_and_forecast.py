"""Cash counts, close-out cascade, the cash-load forecast, and ATM parallel state dimensions.

Covers queue-A difficulty instances (transitive_cascade close-out, boundary cash-count tolerance,
cross_entity_state_dependency confirm-load OOS, non_linear_state_machine parallel dims,
dual_variant_calc forecast) and queue-B corner instances (calculations cash-count OVER,
validations forecast input boundary).
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    TEST_USERS,
    provision_network, provision_armed_atm, create_cassette,
    schedule_and_dispatch_order, confirm_load_order,
    post_withdrawal, post_balance_inquiry, set_clock, seed_monthly_wd_count,
    approve_fee_disclosure_for_atm,
    schedule_order, read_vault, read_atm, read_order, open_ticket,
)

VAULT = TEST_USERS["vault_controller_headers"]
TECH = TEST_USERS["field_tech_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


# ============================================================================
# transitive_cascade — close-out depth-3 cascade (queue A)
# ============================================================================

def test_closeout_cascade_depth3_atm_order_vault(api):
    """PRD §3.6: "Close-out reduces each cassette's `loaded_cents` to its expected remaining — its
    `loaded_cents` minus its `dispensed_cents` — and resets each cassette's `dispensed_cents` to
    zero, moves the machine's `cash_status` back to `EMPTY`, and cascades to the cash supply chain:
    the machine's currently `LOADED` replenishment order moves to its terminal `SETTLED` status, and
    the vault's `in_machine_cents` is reduced by that order's `order_amount_cents`."

    Design: Difficulty/transitive_cascade/closeout_cascade_depth3_atm_order_vault
    """
    net = provision_network(provisioned_cents=100_000_000)
    create_cassette(net["atm"]["id"], position="C1")
    order = schedule_and_dispatch_order(net["atm"]["id"], net["route"]["id"], net["vault"]["id"],
                                        order_amount_cents=200_000)
    order = confirm_load_order(order["id"])
    cc = validate_success(api.create_cash_count(net["atm"]["id"], {"counted_cents": 200_000},
                                                headers=TECH), expected_status=201)
    # Close-out triggers the depth-3 cascade.
    validate_success(api.close_out_cash_count(net["atm"]["id"], cc["id"], headers=TECH))

    atm = read_atm(net["atm"]["id"])
    assert atm["cash_status"] == "EMPTY"
    ro = read_order(order["id"])
    assert ro["status"] == "SETTLED"
    vault = read_vault(net["vault"]["id"])
    assert vault["in_machine_cents"] == 0
    # PRD §2.7: balance_cents = provisioned_cents - in_transit_cents - in_machine_cents,
    # and the sum equals provisioned_cents at all times. Close-out empties in_machine, so
    # that cash returns to on-hand balance, restoring the full provisioned baseline.
    assert vault["balance_cents"] == 100_000_000


# ============================================================================
# boundary_precision_check — cash-count variance at tolerance (queue A)
# ============================================================================

def test_cash_count_variance_at_tolerance_boundary(api):
    """PRD §3.6: "The count's `outcome` — and each affected cassette's `balance_status` — is
    `BALANCED` when the absolute value of the variance is less than or equal to the `tolerance_cents`,
    `OVER` when the variance is strictly greater than zero and beyond tolerance, and `SHORT` when it
    is strictly less than zero and beyond tolerance."
    PRD §3.6: "the system computes the count's `expected_remaining_cents` as the machine's
    `loaded_cents` minus its `dispensed_cents_since_load`, and the `variance_cents` as the
    `counted_cents` minus that expected remaining."

    Design: Difficulty/boundary_precision_check/cash_count_variance_at_tolerance_boundary
    """
    net = provision_armed_atm(surcharge_cents=100, jurisdiction_code="CA",
                              note_denomination_cents=2000)
    create_cassette(net["atm"]["id"], position="C1")
    order = schedule_and_dispatch_order(net["atm"]["id"], net["route"]["id"], net["vault"]["id"],
                                        order_amount_cents=100_000)
    confirm_load_order(order["id"])
    post_withdrawal(net["atm"]["id"], amount_cents=40_000)  # expected_remaining 60000
    # counted 59500 -> variance -500, |−500| <= 500 -> BALANCED (inclusive boundary).
    resp = api.create_cash_count(net["atm"]["id"],
                                 {"counted_cents": 59_500, "tolerance_cents": 500}, headers=TECH)
    cc = validate_success(resp, expected_status=201)
    assert cc["expected_remaining_cents"] == 60_000
    assert cc["variance_cents"] == -500
    assert cc["outcome"] == "BALANCED"


# ============================================================================
# cross_entity_state_dependency — confirm-load blocked by OOS (queue A)
# ============================================================================

def test_confirm_load_blocked_by_atm_out_of_service(api):
    """PRD §3.6: "The only precondition beyond the order being dispatched is that the machine must
    not be `OUT_OF_SERVICE`; an attempt to load an out-of-service machine is rejected with
    `ERR_ATM_OUT_OF_SERVICE`."

    Design: Difficulty/cross_entity_state_dependency/confirm_load_blocked_by_atm_out_of_service
    """
    net = provision_network(provisioned_cents=100_000_000)
    create_cassette(net["atm"]["id"], position="C1")
    order = schedule_and_dispatch_order(net["atm"]["id"], net["route"]["id"], net["vault"]["id"],
                                        order_amount_cents=200_000)
    # A MAJOR ticket drives the ATM to OUT_OF_SERVICE.
    open_ticket(net["atm"]["id"], fault_kind="DISPENSER", severity="MAJOR")
    resp = api.confirm_load(order["id"], headers=TECH)
    validate_error(resp, ApiErrorId.ERR_ATM_OUT_OF_SERVICE, expected_status=409)
    ro = read_order(order["id"])
    assert ro["status"] == "DISPATCHED"


# ============================================================================
# non_linear_state_machine — ATM parallel dimensions independent (queue A)
# ============================================================================

def test_atm_parallel_dimensions_independent(api):
    """PRD §2.5: "a machine can be `FAULTED` and `LOADED` at the same time, and a fault never
    changes the cash dimension nor vice versa."
    PRD §3.6: "Notably, a `FAULTED` machine can still be loaded — only `OUT_OF_SERVICE` blocks it."

    Design: Difficulty/non_linear_state_machine/atm_parallel_dimensions_independent
    """
    net = provision_network(provisioned_cents=100_000_000)
    create_cassette(net["atm"]["id"], position="C1")
    order = schedule_and_dispatch_order(net["atm"]["id"], net["route"]["id"], net["vault"]["id"],
                                        order_amount_cents=200_000)
    # MINOR ticket -> operational_status FAULTED; cash dimension untouched.
    open_ticket(net["atm"]["id"], fault_kind="CARD_READER", severity="MINOR")
    # confirm-load must still succeed (FAULTED does not block; only OUT_OF_SERVICE does).
    loaded = validate_success(api.confirm_load(order["id"], headers=TECH))
    assert loaded["status"] == "LOADED"
    atm = read_atm(net["atm"]["id"])
    assert atm["operational_status"] == "FAULTED"
    assert atm["cash_status"] == "LOADED"


# ============================================================================
# dual_variant_calc — forecast FORWARD vs CHRONOLOGICAL (queue A)
# ============================================================================

def test_forecast_forward_vs_chronological_diverge(api):
    """PRD §3.3: "Under the **forward-looking** variant, selected when `basis` is `FORWARD`, the
    average daily dispense is the sum of the `amount_cents` of every `WITHDRAWAL` transaction whose
    creation time falls in the half-open window beginning fourteen days before the current logical
    clock instant and ending at — but not including — that instant, divided by a fixed divisor of
    fourteen."
    PRD §3.3: "Under the **chronological** variant, selected when `basis` is `CHRONOLOGICAL`, the
    average daily dispense counts only actuals since the machine's most recent confirmed load."
    PRD §3.3: "A raw figure is the average daily dispense multiplied by `days_until_next_visit` and
    then by a safety factor of 1.25 (a twenty-five percent buffer over the bare projection)."
    PRD §3.3: "That raw figure is then rounded **up** to the nearest whole multiple of the machine's
    `note_denomination_cents`, because a machine can only be loaded in whole notes — so a raw figure
    of any amount that is not already a clean multiple of the note value is lifted to the next
    multiple."

    Design: Difficulty/dual_variant_calc/forecast_forward_vs_chronological_diverge
    """
    net = provision_armed_atm(surcharge_cents=100, jurisdiction_code="CA",
                              note_denomination_cents=2000)
    atm_id = net["atm"]["id"]
    create_cassette(atm_id, position="C1")

    # Two 1,070,000c withdrawals on 2026-01-02.
    set_clock("2026-01-02T00:00:00Z")
    post_withdrawal(atm_id, amount_cents=1_070_000)
    post_withdrawal(atm_id, amount_cents=1_070_000)

    # A LOADED replenishment confirmed at 2026-01-12.
    order = schedule_order(atm_id, net["route"]["id"], order_amount_cents=4_000_000,
                           service_window_start="2026-01-12T08:00:00Z",
                           service_window_end="2026-01-12T10:00:00Z")
    set_clock("2026-01-12T00:00:00Z")
    vault = read_vault(net["vault"]["id"])
    validate_success(api.dispatch_order(order["id"],
                                        {"expected_vault_version": vault["version"]}, headers=VAULT))
    confirm_load_order(order["id"])

    # One 660,000c withdrawal after the load.
    post_withdrawal(atm_id, amount_cents=660_000)
    set_clock("2026-01-15T00:00:00Z")

    fwd = validate_success(api.get_forecast(
        atm_id, headers=VAULT, params={"basis": "FORWARD", "days_until_next_visit": 7}))
    chrono = validate_success(api.get_forecast(
        atm_id, headers=VAULT, params={"basis": "CHRONOLOGICAL", "days_until_next_visit": 7}))

    assert fwd["avg_daily_dispense_cents"] == 200_000
    assert fwd["forecast_cents"] == 1_750_000
    assert chrono["avg_daily_dispense_cents"] == 220_000
    assert chrono["forecast_cents"] == 1_926_000


# ============================================================================
# calculations — cash-count OVER outcome (queue B)
# ============================================================================

def test_cash_count_over_outcome(api):
    """PRD §3.6: "`OVER` when the variance is strictly greater than zero and beyond tolerance"
    PRD §3.6: "the `variance_cents` as the `counted_cents` minus that expected remaining."

    Design: Corner/calculations/cash_count_over_outcome
    """
    net = provision_armed_atm(surcharge_cents=100, jurisdiction_code="CA",
                              note_denomination_cents=2000)
    create_cassette(net["atm"]["id"], position="C1")
    order = schedule_and_dispatch_order(net["atm"]["id"], net["route"]["id"], net["vault"]["id"],
                                        order_amount_cents=100_000)
    confirm_load_order(order["id"])
    post_withdrawal(net["atm"]["id"], amount_cents=40_000)  # expected_remaining 60000
    resp = api.create_cash_count(net["atm"]["id"],
                                 {"counted_cents": 61_000, "tolerance_cents": 500}, headers=TECH)
    cc = validate_success(resp, expected_status=201)
    assert cc["variance_cents"] == 1000
    assert cc["outcome"] == "OVER"


# ============================================================================
# validations — forecast days_until_next_visit boundary (queue B)
# ============================================================================

def test_forecast_days_until_next_visit_zero_rejected(api):
    """PRD §3.3: "`days_until_next_visit`, the integer number of days until the next planned
    service, which must be at least 1. A `days_until_next_visit` below 1 is rejected with
    `ERR_VALIDATION`."

    Design: Corner/validations/forecast_days_until_next_visit_zero_rejected
    """
    net = provision_network(provisioned_cents=100_000, note_denomination_cents=2000)
    resp = api.get_forecast(net["atm"]["id"], headers=VAULT,
                            params={"basis": "FORWARD", "days_until_next_visit": 0})
    validate_error(resp, ApiErrorId.ERR_VALIDATION, expected_status=422)
