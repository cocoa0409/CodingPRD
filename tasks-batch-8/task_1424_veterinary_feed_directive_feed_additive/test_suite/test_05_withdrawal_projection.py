"""Withdrawal plans: dual-variant market-date projection (provisional vs final),
max() branch selection, and violation auto-opening a residue case
(PRD §2.6, §3.5, §3.6)."""
import pytest

from test_helpers import (
    validate_success, get_success_data,
    ApiErrorId, TEST_USERS,
    setup_validated_order, setup_shipped_order,
    get_withdrawal_plan_for_order, parse_timestamp, assert_timestamp_equals,
    make_producer_headers,
)
from datetime import datetime, timezone

INSPECTOR = TEST_USERS["inspector_headers"]


# ─── Difficulty: withdrawal_plan_provisional_vs_final ───

def test_provisional_market_date_uses_earliest_market_date_when_later(api):
    """PRD §3.5: "The plan's `provisional_market_date` is computed forward-looking:
    take the current logical time, add the `withdrawal_window_hours`, and compare
    the result to the animal group's `earliest_market_date`; the provisional market
    date is whichever of the two is later, truncated to whole-minute UTC."
    PRD §3.5: "A `WithdrawalPlan` is created in `PROVISIONAL` status with
    `withdrawal_window_hours` copied from the linked drug's `withdrawal_hours` at
    this moment."

    Setup: logical clock at the 2026-08-01 startup default, withdrawal 96h
    (now+96h = 2026-08-05), earliest_market_date 2026-09-15 — the later arm wins.

    Design: Difficulty/dual_variant_calc/withdrawal_plan_provisional_vs_final
    """
    chain = setup_validated_order(
        group_overrides={"earliest_market_date": "2026-09-15"},
        drug_overrides={"withdrawal_hours": 96},
        vfd_overrides={"authorized_animal_count": 100},
        order_overrides={"animal_count": 10, "tons_of_feed": 5},
    )
    plan = get_withdrawal_plan_for_order(chain["order"]["id"])
    assert plan["status"] == "PROVISIONAL"
    assert plan["withdrawal_window_hours"] == 96
    assert_timestamp_equals(plan["provisional_market_date"], 2026, 9, 15)


def test_final_market_date_recomputed_from_attested_last_feed(api):
    """PRD §3.6: "the plan's `final_market_date` is the attested
    `last_feed_consumed_at` plus the `withdrawal_window_hours`, truncated to
    whole-minute UTC. Because it uses the attested last-feed timestamp rather than
    the validation-time clock, this final value can differ from
    `provisional_market_date` by days. If the resulting `final_market_date` is on
    or before the animal group's `earliest_market_date`, the plan transitions from
    `PROVISIONAL` to `FINALIZED`."

    Setup: last_feed 2026-08-10 + 96h = 2026-08-14, on or before the 2026-09-15
    earliest market date, so the plan finalizes.

    Design: Difficulty/dual_variant_calc/withdrawal_plan_provisional_vs_final
    """
    chain = setup_shipped_order(
        group_overrides={"earliest_market_date": "2026-09-15"},
        drug_overrides={"withdrawal_hours": 96},
        vfd_overrides={"authorized_animal_count": 100},
        order_overrides={"animal_count": 10, "tons_of_feed": 5},
    )
    shipment = validate_success(api.deliver_shipment(
        chain["shipment"]["id"],
        {"last_feed_consumed_at": "2026-08-10T00:00:00Z"},
        make_producer_headers(chain["producer"]["id"]),
    ), 200)
    assert shipment["status"] == "DELIVERED"

    plan = get_withdrawal_plan_for_order(chain["order"]["id"])
    assert_timestamp_equals(plan["final_market_date"], 2026, 8, 14)
    assert_timestamp_equals(plan["provisional_market_date"], 2026, 9, 15)
    assert parse_timestamp(plan["provisional_market_date"]) != parse_timestamp(
        plan["final_market_date"]
    ), "Provisional (validation-time clock) and final (attested last-feed) must differ"
    assert plan["status"] == "FINALIZED"


# ─── Difficulty: provisional_market_date_three_input_max ───

def test_provisional_market_date_uses_now_plus_withdrawal_when_later(api):
    """PRD §3.5: "The plan's `provisional_market_date` is computed forward-looking:
    take the current logical time, add the `withdrawal_window_hours`, and compare
    the result to the animal group's `earliest_market_date`; the provisional market
    date is whichever of the two is later, truncated to whole-minute UTC."

    Setup: logical clock at the 2026-08-01 startup default, withdrawal 96h
    (now+96h = 2026-08-05), earliest_market_date 2026-08-03 — the now+withdrawal
    arm wins.

    Design: Difficulty/combinatorial_formula/provisional_market_date_three_input_max
    """
    chain = setup_validated_order(
        group_overrides={"earliest_market_date": "2026-08-03"},
        drug_overrides={"withdrawal_hours": 96},
        vfd_overrides={"authorized_animal_count": 30},
        order_overrides={"animal_count": 5},
    )
    plan = get_withdrawal_plan_for_order(chain["order"]["id"])
    assert_timestamp_equals(plan["provisional_market_date"], 2026, 8, 5)
    assert plan["withdrawal_window_hours"] == 96
    assert plan["status"] == "PROVISIONAL"


def test_provisional_market_date_branch_flips_with_earliest_market_date(api):
    """PRD §3.5: "The plan's `provisional_market_date` is computed forward-looking:
    take the current logical time, add the `withdrawal_window_hours`, and compare
    the result to the animal group's `earliest_market_date`; the provisional market
    date is whichever of the two is later, truncated to whole-minute UTC."

    Setup: identical to the companion test except earliest_market_date is
    2026-09-15, which is later than now+96h (2026-08-05) — the max() branch flips
    to the animal group's date.

    Design: Difficulty/combinatorial_formula/provisional_market_date_three_input_max
    """
    chain = setup_validated_order(
        group_overrides={"earliest_market_date": "2026-09-15"},
        drug_overrides={"withdrawal_hours": 96},
        vfd_overrides={"authorized_animal_count": 30},
        order_overrides={"animal_count": 5},
    )
    plan = get_withdrawal_plan_for_order(chain["order"]["id"])
    assert_timestamp_equals(plan["provisional_market_date"], 2026, 9, 15)
    assert plan["withdrawal_window_hours"] == 96
    assert plan["status"] == "PROVISIONAL"


# ─── Corner: withdrawal_plan_violated_when_market_after_earliest ───

def test_withdrawal_plan_violated_when_final_market_after_earliest(api):
    """PRD §3.6: "If the `final_market_date` falls after the `earliest_market_date`,
    the plan transitions from `PROVISIONAL` to `VIOLATED` and the delivery is still
    allowed to complete; the violation is surfaced by automatically opening a
    `ResidueCase` on the producer with `status` set to `OPEN`, `detected_at` set to
    the current logical time, and `residue_ppb` left null pending laboratory
    results."

    Setup: earliest_market_date 2026-08-05, withdrawal 96h, attested last feed
    2026-08-10 → final_market_date 2026-08-14, after the earliest market date.

    Design: Corner/endpoints/withdrawal_plan_violated_when_market_after_earliest
    """
    chain = setup_shipped_order(
        group_overrides={"earliest_market_date": "2026-08-05"},
        drug_overrides={"withdrawal_hours": 96},
        vfd_overrides={"authorized_animal_count": 10},
        order_overrides={"animal_count": 5},
    )
    shipment = validate_success(api.deliver_shipment(
        chain["shipment"]["id"],
        {"last_feed_consumed_at": "2026-08-10T00:00:00Z"},
        make_producer_headers(chain["producer"]["id"]),
    ), 200)
    assert shipment["status"] == "DELIVERED", "Delivery completes despite violation"

    plan = get_withdrawal_plan_for_order(chain["order"]["id"])
    assert plan["status"] == "VIOLATED"
    assert_timestamp_equals(plan["final_market_date"], 2026, 8, 14)

    cases = get_success_data(api.list_producer_residue_cases(
        chain["producer"]["id"], INSPECTOR))
    assert len(cases) == 1, f"Expected one auto-opened ResidueCase, got {len(cases)}"
    case = cases[0]
    assert case["status"] == "OPEN"
    assert case["feed_order_id"] == chain["order"]["id"]
    assert case.get("residue_ppb") is None
