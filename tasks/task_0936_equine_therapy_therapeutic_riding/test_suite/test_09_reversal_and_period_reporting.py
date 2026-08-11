"""The charge-reversal cascade and the period report's frozen aggregates."""

import pytest

from test_helpers import (
    ApiErrorId,
    allocations_for_charge,
    assert_same_instant,
    book_session,
    complete_session,
    confirm_session,
    finalize_period_report,
    make_grant,
    make_period_report,
    make_scholarship_award,
    only_charge_for_session,
    read_award,
    read_charge,
    read_grant,
    read_period_report,
    read_session,
    set_clock,
    setup_active_rider,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import ADMIN, CLERK


def _reversal_scenario_with_finalized_report():
    """A 6750-cent charge covered by grant + scholarship inside a FINALIZED report."""
    scenario = setup_active_rider(rider={"household_income_band": "BAND_B"})
    scenario["grant"] = make_grant(
        grant_name="Hooves Fund",
        funder_name="County",
        awarded_amount_cents=3000,
        period_start="2026-01-01",
        period_end="2026-12-31",
    )
    scenario["award"] = make_scholarship_award(
        scenario["rider_id"],
        cap_pct=0.5,
        period_cap_cents=5000,
        period_start="2026-01-01",
        period_end="2026-12-31",
    )
    session = book_session(
        scenario["rider_id"], scenario["horse_id"], scenario["instructor_id"]
    )
    confirm_session(session["id"], scenario["instructor_id"])
    complete_session(session["id"], scenario["instructor_id"], 45)
    charge = only_charge_for_session(session["id"])

    report = make_period_report(period_start="2026-05-01", period_end="2026-05-31")
    finalize_period_report(report["id"])

    scenario.update(
        {
            "session": session,
            "session_id": session["id"],
            "charge": charge,
            "charge_id": charge["id"],
            "report": report,
            "report_id": report["id"],
        }
    )
    return scenario


def test_reversal_hops_one_to_three_release_the_ledgers(api):
    """PRD 3.8: "Hop one moves the charge to `REVERSED`, stamps `reversed_at`
    with the logical clock, stores `reversal_reason`, zeroes both
    `allocated_cents` and `balance_due_cents`, and increments the charge's
    `version`."
    PRD 3.8: "Hop three, caused by hop two, restores each released line's source
    ledger: a grant line reduces the grant's `allocated_amount_cents` and raises
    its `remaining_amount_cents` by the line's `amount_cents`, flipping the grant
    from `EXHAUSTED` back to `OPEN` once anything remains; a scholarship line
    reduces the award's `period_used_cents` by the same amount, flipping the
    award from `EXHAUSTED` back to `ACTIVE` once usage falls below
    `period_cap_cents`."

    Design: Difficulty/transitive_cascade/charge_reversal_five_hop_cascade_to_finalized_report_amendment
    """
    scenario = _reversal_scenario_with_finalized_report()

    validate_success(
        api.reverse_charge(
            scenario["charge_id"], {"reason": "Session billed in error"}, CLERK
        )
    )

    charge = read_charge(scenario["charge_id"])
    assert charge["status"] == "REVERSED"
    assert charge["allocated_cents"] == 0
    assert charge["balance_due_cents"] == 0
    assert charge["reversal_reason"] == "Session billed in error"

    allocations = allocations_for_charge(scenario["charge_id"])
    assert allocations, "The reversed charge still exposes its allocation ledger"
    assert all(line["status"] == "RELEASED" for line in allocations)

    grant = read_grant(scenario["grant"]["id"])
    assert grant["allocated_amount_cents"] == 0
    assert grant["remaining_amount_cents"] == 3000
    assert grant["status"] == "OPEN"

    award = read_award(scenario["award"]["id"])
    assert award["period_used_cents"] == 0
    assert award["status"] == "ACTIVE"


def test_reversal_hops_four_and_five_reach_the_finalized_report(api):
    """PRD 3.8: "Hop four, caused by hop three, moves the parent session's
    `billing_status` from `CHARGED` or `FUNDED` to `REVERSED` — but only once
    every charge of that session is `REVERSED` and every touched source ledger
    has been restored — and increments the session's `version`."
    PRD 3.8: "Late-arriving money does not disturb the frozen numbers: when hop
    five of a reversal reaches a `FINALIZED` report, `amendment_count` increases
    by 1 and `amendment_net_cents` decreases by the reversed charge's gross
    `amount_cents`, while every aggregate — `total_charged_cents` included —
    stays exactly where finalization left it."

    Design: Difficulty/transitive_cascade/charge_reversal_five_hop_cascade_to_finalized_report_amendment
    """
    scenario = _reversal_scenario_with_finalized_report()

    validate_success(
        api.reverse_charge(
            scenario["charge_id"], {"reason": "Session billed in error"}, CLERK
        )
    )

    session = read_session(scenario["session_id"])
    assert session["billing_status"] == "REVERSED"
    assert session["schedule_status"] == "COMPLETED"

    report = read_period_report(scenario["report_id"])
    assert report["status"] == "FINALIZED"
    assert report["total_charged_cents"] == 6750, "The frozen aggregate never moves"
    assert report["grant_utilization_cents"] == 3000
    assert report["amendment_count"] == 1
    assert report["amendment_net_cents"] == -6750


def test_charge_reversal_is_terminal(api):
    """PRD 3.8: "The charge must be `PENDING` or `FUNDED`; reversing an
    already-reversed charge is `ERR_INVALID_STATE`."
    PRD 2.12: "once the charge is `REVERSED`, its `allocated_cents` and
    `balance_due_cents` are both 0 and every one of its allocation lines is
    `RELEASED`."

    Design: Corner/state_machines/charge_reverse_twice_returns_invalid_state
    """
    scenario = setup_active_rider()
    session = book_session(
        scenario["rider_id"],
        scenario["horse_id"],
        scenario["instructor_id"],
        duration_minutes=30,
    )
    confirm_session(session["id"], scenario["instructor_id"])
    complete_session(session["id"], scenario["instructor_id"], 30)
    charge = only_charge_for_session(session["id"])

    first = validate_success(
        api.reverse_charge(charge["id"], {"reason": "Billed in error"}, CLERK)
    )
    version_after_first = first["version"]

    second = api.reverse_charge(
        charge["id"], {"reason": "Billed in error again"}, CLERK
    )
    validate_error(second, ApiErrorId.ERR_INVALID_STATE.value)

    unchanged = read_charge(charge["id"])
    assert unchanged["status"] == "REVERSED"
    assert unchanged["version"] == version_after_first
    assert unchanged["allocated_cents"] == 0
    assert unchanged["balance_due_cents"] == 0

    allocations = allocations_for_charge(charge["id"])
    assert allocations, "The allocation ledger survives the reversal"
    assert all(line["status"] == "RELEASED" for line in allocations)
    assert read_session(session["id"])["billing_status"] == "REVERSED"


def _three_fifty_minute_rides():
    """A VETERAN rider with three 60-minute bookings each ridden for 50 minutes."""
    scenario = setup_active_rider(rider={"demographic_group": "VETERAN"})
    for start in (
        "2026-05-11T10:00:00Z",
        "2026-05-12T10:00:00Z",
        "2026-05-13T10:00:00Z",
    ):
        session = book_session(
            scenario["rider_id"],
            scenario["horse_id"],
            scenario["instructor_id"],
            scheduled_start=start,
            duration_minutes=60,
        )
        confirm_session(session["id"], scenario["instructor_id"])
        complete_session(session["id"], scenario["instructor_id"], 50)
    return scenario


def test_period_report_rounds_each_session_then_sums(api):
    """PRD 2.6: "Three fifty-minute sessions contribute 0.83 hours each and
    therefore 2.49 hours in total; summing the minutes first and converting once
    would give 2.5, and that answer is wrong."
    PRD 3.8: "From that set the report derives `total_service_hours`, which sums
    the per-session `service_hours` of the `COMPLETED` sessions — each already
    rounded to 2 decimal places — and rounds the sum to 2 decimal places again"

    Design: Difficulty/combinatorial_formula/period_report_service_hours_round_each_session_then_sum
    """
    _three_fifty_minute_rides()

    report = validate_success(
        api.create_period_report(
            {"period_start": "2026-05-01", "period_end": "2026-05-31"}, ADMIN
        ),
        expected_status=201,
    )
    assert report["total_service_hours"] == pytest.approx(2.49, abs=0.001)
    assert report["total_service_hours"] != pytest.approx(2.5, abs=0.001)
    assert report["status"] == "DRAFT"


def test_period_report_counts_riders_and_money(api):
    """PRD 3.8: "`rider_count`, the number of distinct riders with at least one
    `COMPLETED` session in the range; `veteran_rider_count`, the subset of those
    riders whose `demographic_group` is `VETERAN`"
    PRD 3.8: "and `total_charged_cents`, the sum of `amount_cents` over in-period
    charges whose `status` is not `REVERSED`."
    PRD 3.8: "it derives `grant_utilization_cents`, `scholarship_spend_cents` and
    `private_pay_cents` — the sums of `amount_cents` over `ALLOCATED` lines whose
    `source_type` is `GRANT`, `SCHOLARSHIP` and `PRIVATE_PAY` respectively"

    Design: Difficulty/combinatorial_formula/period_report_service_hours_round_each_session_then_sum
    """
    _three_fifty_minute_rides()

    report = validate_success(
        api.create_period_report(
            {"period_start": "2026-05-01", "period_end": "2026-05-31"}, ADMIN
        ),
        expected_status=201,
    )
    assert report["rider_count"] == 1
    assert report["veteran_rider_count"] == 1
    assert report["total_charged_cents"] == 22500
    assert report["private_pay_cents"] == 22500


def test_finalizing_twice_and_overlapping_report_are_report_finalized(api):
    """PRD 3.8: "From that instant the report is immutable and the
    finalized-period gate begins refusing new bookings and new completions whose
    session date falls inside the period, and refusing the creation of any report
    whose period overlaps this one, all with `ERR_REPORT_FINALIZED`; finalizing
    an already-finalized report is the same error."
    PRD 3.8: "Finalizing a report recomputes every aggregate once from live data,
    freezes all of them, moves the report `DRAFT → FINALIZED`, stamps
    `finalized_at` with the logical clock and increments the report's `version`."

    Design: Corner/state_machines/finalizing_an_already_finalized_period_report_returns_report_finalized
    """
    set_clock("2026-05-01T00:00:00Z")
    report = validate_success(
        api.create_period_report(
            {"period_start": "2026-05-01", "period_end": "2026-05-31"}, ADMIN
        ),
        expected_status=201,
    )
    finalized = validate_success(api.finalize_period_report(report["id"], ADMIN))
    assert_same_instant(finalized["finalized_at"], "2026-05-01T00:00:00.000Z")

    again = api.finalize_period_report(report["id"], ADMIN)
    validate_error(again, ApiErrorId.ERR_REPORT_FINALIZED.value)

    overlapping = api.create_period_report(
        {"period_start": "2026-05-15", "period_end": "2026-06-15"}, ADMIN
    )
    validate_error(overlapping, ApiErrorId.ERR_REPORT_FINALIZED.value)

    frozen = read_period_report(report["id"])
    assert frozen["total_service_hours"] == pytest.approx(0, abs=0.001)
    assert frozen["rider_count"] == 0
    assert frozen["total_charged_cents"] == 0
