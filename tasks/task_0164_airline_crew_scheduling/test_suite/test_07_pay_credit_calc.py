"""Pay credit calculation: aggregate-then-floor, MIN floor, scheduled vs actual.

PRD §3.6 pins the five-step calculation, the aggregate-then-floor ordering
for deadhead minutes, and the 240-minute MIN_PAY_CREDIT_FLOOR_MINUTES
on the actual variant (and explicitly NOT on the scheduled variant).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    MIN_PAY_CREDIT_FLOOR_MINUTES,
    add_minutes_iso,
    advance_clock_to,
    build_pairing_with_deadhead_legs,
    build_pairing_with_revenue_legs,
    create_crew_member,
    expected_pay_credit_actual,
    expected_pay_credit_scheduled,
    get_assignment,
    iso_from_dt,
    publish_and_open_bidding,
    publish_pairing,
    run_pairing_to_completion,
    scheduler_headers,
    setup_pairing_admin_assigned,
    submit_bid,
    validate_success,
)


class TestPayCreditActualVariant:

    def test_two_35min_deadheads_aggregate_then_floor(self, api):
        """PRD §3.6: "the deadhead credit is derived by multiplying the
        integer deadhead-minute total by the deadhead pay ratio of one
        half and then taking the floor of the product — aggregate first,
        then floor, never floor each leg individually."

        PRD §3.6: "two deadhead legs of 35 minutes each at the half
        ratio yield an aggregate of 35 minutes (the floor of 70 times
        one half), not 34 minutes."

        # difficulty: combinatorial_formula/pay_credit_aggregate_then_floor
        Then the MIN_PAY_CREDIT_FLOOR_MINUTES=240 floor applies:
        max(35, 240) = 240.
        """
        pilot = create_crew_member(rank="CAPTAIN")
        # Build a pairing with two 35min DEADHEAD legs and zero REVENUE.
        pairing, _, _ = build_pairing_with_deadhead_legs(
            deadhead_durations_minutes=[35, 35],
            revenue_durations_minutes=[],
            duty_pad_minutes=120,
        )
        publish_pairing(pairing["id"])
        from test_helpers import admin_assign
        a = admin_assign(pairing["id"], pilot["id"], "CAPTAIN")
        run_pairing_to_completion(pairing)
        # Read assignment back.
        a = get_assignment(a["id"])
        # PRD §3.6 expected: aggregate=70→floor(0.5*70)=35; raw=0+35=35;
        # max(35, 240)=240.
        assert a["pay_credit_minutes"] == 240, (
            f"PRD §3.6 aggregate-then-floor + MIN floor; got "
            f"{a['pay_credit_minutes']}, expected 240."
        )

    def test_revenue_minus_deadhead_above_floor(self, api):
        """PRD §3.6: "the raw credit is the sum of the revenue minutes
        and the deadhead credit. Fifth, pay_credit_minutes is the
        greater of the raw credit and the minimum-pay-credit floor of
        240 minutes (four hours)."
        """
        pilot = create_crew_member(rank="CAPTAIN")
        # 300 REVENUE + 60 DEADHEAD → raw = 300 + floor(60*0.5) = 330.
        pairing, _, _ = build_pairing_with_deadhead_legs(
            deadhead_durations_minutes=[60],
            revenue_durations_minutes=[300],
            duty_pad_minutes=60,
        )
        publish_pairing(pairing["id"])
        from test_helpers import admin_assign
        a = admin_assign(pairing["id"], pilot["id"], "CAPTAIN")
        run_pairing_to_completion(pairing)
        a = get_assignment(a["id"])
        expected = expected_pay_credit_actual(
            revenue_minutes=300, deadhead_minutes=60,
        )
        assert expected == 330, (
            f"Test arithmetic: expected 330, computed {expected}"
        )
        assert a["pay_credit_minutes"] == 330, (
            f"PRD §3.6 raw=300+30=330 >= MIN floor 240; got "
            f"{a['pay_credit_minutes']}, expected 330."
        )


class TestPayCreditScheduledVariant:

    def test_scheduled_estimate_does_not_apply_min_floor(self, api):
        """PRD §3.6: "The scheduled variant of the pay-credit
        calculation treats every flight leg currently scheduled in the
        pairing as if it had flown, summing the revenue and deadhead
        block minutes as above and applying the same aggregate-then-
        floor deadhead arithmetic — but it does not apply the
        240-minute minimum-pay-credit floor."

        # difficulty: combinatorial_formula/pay_credit_aggregate_then_floor
        # difficulty: dual_variant_calc/pay_credit_scheduled_vs_actual
        Two 35min DEADHEAD legs → aggregate 35, no floor in scheduled.
        """
        pilot = create_crew_member(rank="CAPTAIN")
        pairing, _, _ = build_pairing_with_deadhead_legs(
            deadhead_durations_minutes=[35, 35],
            revenue_durations_minutes=[],
            duty_pad_minutes=120,
        )
        publish_pairing(pairing["id"])
        from test_helpers import admin_assign
        a = admin_assign(pairing["id"], pilot["id"], "CAPTAIN")
        # Estimate BEFORE pairing closes.
        from test_helpers import pilot_headers_for
        resp = api.get_pay_credit_estimate(
            a["id"], pilot_headers_for(pilot),
        )
        # The owner pilot can read their own pay-credit-estimate per
        # PRD §4.
        data = validate_success(resp)
        # PRD §3.6 names this field name verbatim:
        # "object containing scheduled_pay_credit_minutes".
        assert "scheduled_pay_credit_minutes" in data, (
            "PRD §3.6: The estimate endpoint returns an object "
            "containing scheduled_pay_credit_minutes."
        )
        assert data["scheduled_pay_credit_minutes"] == 35, (
            f"PRD §3.6 scheduled variant: aggregate-then-floor without "
            f"MIN floor → 35, got {data['scheduled_pay_credit_minutes']}"
        )

    def test_scheduled_and_actual_match_when_no_legs_dropped(self, api):
        """PRD §3.6: "As legs drop because of intra-pairing sick calls,
        the actual variant may differ from the scheduled variant."

        Negative direction — when no legs drop, both formulas land on
        the same value as long as the MIN floor doesn't activate.
        """
        pilot = create_crew_member(rank="CAPTAIN")
        # Pairing big enough that raw credit exceeds MIN floor.
        pairing, _, _ = build_pairing_with_revenue_legs(
            leg_durations_minutes=[300, 240],
            duty_pad_minutes=60,
        )
        publish_pairing(pairing["id"])
        from test_helpers import admin_assign, pilot_headers_for
        a = admin_assign(pairing["id"], pilot["id"], "CAPTAIN")
        # Estimate.
        resp = api.get_pay_credit_estimate(
            a["id"], pilot_headers_for(pilot),
        )
        est = validate_success(resp)["scheduled_pay_credit_minutes"]
        assert est == 540
        # Complete pairing.
        run_pairing_to_completion(pairing)
        a = get_assignment(a["id"])
        assert a["pay_credit_minutes"] == 540
