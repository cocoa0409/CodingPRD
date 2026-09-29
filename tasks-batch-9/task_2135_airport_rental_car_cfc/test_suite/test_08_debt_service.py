"""Bond debt service, the coverage test and the deferral sweep."""

import pytest

from test_helpers import (
    ADMIN,
    TREASURY,
    ApiErrorId,
    assert_bond_coverage_posture,
    assert_obligation,
    assert_trust_conservation,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_success,
)


def _trust_with_five_million_reserve(api):
    """Two FINAL receipts totalling 6,000,000 cents against a 5,000,000 cent requirement,
    with no obligation in existence while the cash arrived, so nothing was auto-funded."""
    scenario = fx.setup_two_receipt_trust(api)
    scenario["obligation_over"] = fx.create_obligation(
        api, scenario["facility"]["id"],
        series_label="Series 2026B", due_date="2026-11-01",
        amount_due_cents=4_000_001, coverage_requirement_bps=12_500,
    )
    scenario["obligation_exact"] = fx.create_obligation(
        api, scenario["facility"]["id"],
        series_label="Series 2026A", due_date="2026-12-01",
        amount_due_cents=4_000_000, coverage_requirement_bps=12_500,
    )
    return scenario


def test_coverage_one_cent_short_refuses_to_fund(api):
    """PRD §3.7: "Only `trust_debt_service_reserve_cents` and `trust_unallocated_cents` are
    added together to form the available cents; `trust_debt_service_funded_cents`,
    `trust_om_reserve_cents`, `trust_capital_fund_cents`, `trust_encumbered_cents` and
    `trust_disbursed_cents` are all excluded. The test passes when the available cents
    multiplied by 10,000 is greater than or equal to the obligation's
    `coverage_requirement_bps` multiplied by its `amount_due_cents`."
    PRD §3.7: "The obligation must be in `SCHEDULED`, and the coverage test must pass, or the
    request is rejected with `ERR_COVERAGE_BELOW_REQUIREMENT` (HTTP 409)."

    Design: Difficulty/boundary_precision_check/coverage_ratio_exactly_at_12500_bps_funds_one_cent_over_does_not
    """
    scenario = _trust_with_five_million_reserve(api)
    obligation_id = scenario["obligation_over"]["id"]

    response = api.fund_obligation(obligation_id, TREASURY)

    validate_error(response, ApiErrorId.ERR_COVERAGE_BELOW_REQUIREMENT.value, 409)
    stored = validate_success(api.get_obligation(obligation_id, ADMIN))
    assert stored["status"] == "SCHEDULED", (
        "5,000,000 cents of coverage cash misses 1.25x of 4,000,001 by one cent of principal"
    )
    assert stored["funded_from_reserve_cents"] == 0
    facility = validate_success(api.get_facility(scenario["facility"]["id"], ADMIN))
    assert facility["trust_debt_service_reserve_cents"] == 5_000_000
    assert facility["funded_obligation_count"] == 0


def test_coverage_exactly_on_the_line_funds(api):
    """PRD §3.7: "It is evaluated as exact integer arithmetic with no floating point anywhere,
    and the comparison is inclusive: available cash of exactly one and a quarter times the
    payment passes a 12500 basis-point requirement."
    PRD §3.7: "On success `funded_from_reserve_cents` is set to `amount_due_cents`,
    `auto_funded` stays false, `coverage_ratio_at_funding` is recorded,
    `trust_debt_service_reserve_cents` falls by `amount_due_cents` while
    `trust_debt_service_funded_cents` rises by the same amount, and the facility's
    `funded_obligation_count` rises by 1."
    PRD §3.7: "Separately, and purely for display, `coverage_ratio_at_funding` records the
    available cents divided by `amount_due_cents`, rounded half up to four decimal places at
    the moment of funding; that display value never feeds the pass/fail test."

    Design: Difficulty/boundary_precision_check/coverage_ratio_exactly_at_12500_bps_funds_one_cent_over_does_not
    """
    scenario = _trust_with_five_million_reserve(api)
    api.fund_obligation(scenario["obligation_over"]["id"], TREASURY)

    funded = validate_success(
        api.fund_obligation(scenario["obligation_exact"]["id"], TREASURY), 200
    )

    assert_obligation(funded)
    assert funded["status"] == "FUNDED"
    assert funded["funded_from_reserve_cents"] == 4_000_000
    assert funded["auto_funded"] is False, "an explicit fund call leaves auto_funded false"
    assert funded["coverage_ratio_at_funding"] == pytest.approx(1.25, abs=0.00005)
    facility = validate_success(api.get_facility(scenario["facility"]["id"], ADMIN))
    assert facility["trust_debt_service_reserve_cents"] == 1_000_000
    assert facility["trust_debt_service_funded_cents"] == 4_000_000
    assert facility["funded_obligation_count"] == 1
    assert facility["bond_coverage_status"] == "SATISFIED"
    assert_trust_conservation(facility)
    assert_bond_coverage_posture(facility)


def test_paying_a_funded_obligation_disburses_and_flips_coverage(api):
    """PRD §3.7: "Paying a funded obligation carries it `FUNDED → PAID`, its terminal status:
    `trust_debt_service_funded_cents` falls by `amount_due_cents`, `trust_disbursed_cents`
    rises by the same amount, `bond_coverage_status` is recomputed and may fall back to
    `DEFICIENT` because the funded bucket has just emptied, and the obligation's `version` and
    the facility's `version` each advance by 1."

    Design: Corner/state_machines/paying_a_funded_obligation_moves_cash_out_and_can_flip_coverage
    """
    scenario = fx.setup_single_receipt_trust(api, with_project=False)
    obligation_id = scenario["obligation"]["id"]

    paid = validate_success(api.pay_obligation(obligation_id, TREASURY))

    assert paid["status"] == "PAID"
    facility = validate_success(api.get_facility(scenario["facility"]["id"], ADMIN))
    assert facility["trust_debt_service_funded_cents"] == 0
    assert facility["trust_disbursed_cents"] == 800_000
    assert facility["trust_debt_service_reserve_cents"] == 200_000
    assert facility["trust_capital_fund_cents"] == 1_000_000
    assert facility["bond_coverage_status"] == "DEFICIENT", (
        "200,000 cents of coverage cash no longer meets the 1,000,000 cent requirement"
    )
    assert facility["trust_lifetime_received_cents"] == 2_000_000
    assert_trust_conservation(facility)
    assert_bond_coverage_posture(facility)


def test_clock_defers_an_overdue_scheduled_obligation(api):
    """PRD §3.7: "An obligation still `SCHEDULED` when the logical clock passes its `due_date`
    moves instead to the terminal `DEFERRED`, advancing its `version` by 1 and counting toward
    the clock response's `deferred_obligation_count`."
    PRD §3.7: "A scheduled obligation opens in `SCHEDULED` status with `auto_funded` false,
    `funded_from_reserve_cents` of 0 and `coverage_ratio_at_funding` null."

    Design: Corner/state_machines/clock_advance_defers_an_overdue_scheduled_obligation
    """
    facility = fx.create_facility(
        api, ds_reserve_requirement_cents=1_000_000, om_reserve_requirement_cents=0
    )
    obligation = fx.create_obligation(
        api, facility["id"], due_date="2026-08-15", amount_due_cents=800_000
    )

    summary = validate_success(
        api.set_clock(f.clock_payload("2026-08-16T00:00:00Z"), ADMIN)
    )

    assert summary["deferred_obligation_count"] == 1
    stored = validate_success(api.get_obligation(obligation["id"], ADMIN))
    assert stored["status"] == "DEFERRED"
    assert stored["funded_from_reserve_cents"] == 0
    assert stored["auto_funded"] is False
    refreshed = validate_success(api.get_facility(facility["id"], ADMIN))
    assert refreshed["funded_obligation_count"] == 0
    assert refreshed["bond_coverage_status"] == "DEFICIENT"
