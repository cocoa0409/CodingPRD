"""Reversing an applied benefit by compensation rather than deletion."""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import assertions, fixtures
from test_helpers.test_users import BENEFITS_A_HEADERS

GROSS = 81977
CAPPED_BENEFIT = 40000
PATIENT_WITH_BENEFIT = 41977


def _order_with_the_benefit_applied(api):
    """A committed expedited progressive order whose benefit has been applied."""
    scenario = fixtures.surfaced_queued_job(api)
    assert fixtures.read_patient(api, scenario["patient_id"])["benefit_used_cents"] == 0

    order = validate_success(
        api.apply_benefit(scenario["order_id"], BENEFITS_A_HEADERS)
    )
    assert order["insurance_benefit_cents"] == CAPPED_BENEFIT
    assert order["patient_portion_cents"] == PATIENT_WITH_BENEFIT
    assert (
        fixtures.read_patient(api, scenario["patient_id"])["benefit_used_cents"]
        == CAPPED_BENEFIT
    )
    scenario["order"] = order
    return scenario


def test_the_void_returns_the_whole_gross_charge_to_the_patient(api):
    """The benefit is zeroed, the stamp cleared and the portion restored to 81977.

    PRD 3.9: "The void appends a `BENEFIT_REVERSAL` settlement entry for the positive
    amount of the benefit being reversed, sets `insurance_benefit_cents` to 0, sets
    `benefit_applied_at` back to null, recomputes `patient_portion_cents` as
    `gross_charge_cents` less `lab_writeoff_cents`, and moves the order
    `BENEFIT_APPLIED → BENEFIT_VOIDED`."

    Design: Difficulty/compensating_invariant/benefit_void_reverses_the_ledger_and_returns_rolling_benefit_used_to_zero
    """
    scenario = _order_with_the_benefit_applied(api)

    order = validate_success(api.void_benefit(scenario["order_id"], BENEFITS_A_HEADERS))

    assert order["billing_status"] == "BENEFIT_VOIDED"
    assert order["insurance_benefit_cents"] == 0
    assert order["patient_portion_cents"] == GROSS
    assert order["benefit_applied_at"] is None
    assert order["patient_balance_due_cents"] == GROSS
    assert order["gross_charge_cents"] == GROSS
    assert order["lab_writeoff_cents"] == 0
    assertions.assert_money_identity(order)


def test_the_rolling_window_returns_to_its_exact_pre_application_value(api):
    """A voided order contributes nothing, so the patient is back at zero used.

    PRD 3.9: "The patient's `benefit_used_cents` returns to its exact pre-application
    value, because the voided order has both left the qualifying billing states and
    had its benefit amount reset to zero."

    Design: Difficulty/compensating_invariant/benefit_void_reverses_the_ledger_and_returns_rolling_benefit_used_to_zero
    """
    scenario = _order_with_the_benefit_applied(api)

    validate_success(api.void_benefit(scenario["order_id"], BENEFITS_A_HEADERS))

    patient = fixtures.read_patient(api, scenario["patient_id"])
    assert patient["benefit_used_cents"] == 0


def test_the_ledger_compensates_and_never_deletes(api):
    """Three rows in effective order, the negative benefit row still intact.

    PRD 3.9: "The per-order ledger read returns the immutable settlement entries in
    `effective_at` order and may be narrowed by `entry_type`."

    Design: Difficulty/compensating_invariant/benefit_void_reverses_the_ledger_and_returns_rolling_benefit_used_to_zero
    """
    scenario = _order_with_the_benefit_applied(api)
    validate_success(api.void_benefit(scenario["order_id"], BENEFITS_A_HEADERS))

    entries, meta = validate_paginated(
        api.list_order_settlement_entries(scenario["order_id"], BENEFITS_A_HEADERS)
    )
    assert meta["total_count"] == 3
    assertions.assert_ledger_types_in_order(
        entries, ["ORDER_CHARGE", "INSURANCE_BENEFIT", "BENEFIT_REVERSAL"]
    )
    assert [entry["amount_cents"] for entry in entries] == [
        GROSS,
        -CAPPED_BENEFIT,
        CAPPED_BENEFIT,
    ]
    assert sum(entry["amount_cents"] for entry in entries) == GROSS
    for entry in entries:
        assertions.assert_settlement_sign(entry)
        assertions.assert_event_row_fields(entry)
