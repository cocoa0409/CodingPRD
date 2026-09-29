"""
Exact-edge behaviour of the two metrics whose boundary the PRD pins explicitly:
the SLA verdict frozen when a technician records arrival, and pm_compliance_pct
with an empty visit history as it is snapshotted onto a renewal quote.

Every test builds its world from scratch through declared endpoints and drives the
logical clock itself, because the database is empty when the test starts.
"""

from decimal import Decimal

import pytest

from test_helpers import (
    CONTRACT_ADMIN,
    SERVICE_COORDINATOR,
    SEVERITY_SLA_FACTOR,
    SLA_RESPONSE_MINUTES,
    arrive_call,
    assert_fields,
    assert_instant,
    assert_money,
    assert_two_decimals,
    build_fleet,
    contract_version,
    dispatch_call,
    expected_pm_compliance_pct,
    get_success_data,
    open_call,
    read_call,
    read_contract,
    read_visit,
    renewal_quote_payload,
    round_half_up,
    schedule_visit,
    set_clock,
    visit_cancel_payload,
)

GOLD_MAJOR_TARGET_MINUTES = int(
    round_half_up(SLA_RESPONSE_MINUTES["GOLD"] * SEVERITY_SLA_FACTOR["MAJOR"])
)


def _gold_club_with_one_treadmill_and_one_technician(api, clock):
    """A GOLD/FULL active contract on one NW treadmill with one skilled technician."""
    return build_fleet(
        api,
        clock=clock,
        serials=["SN-SLA-1"],
        equipment_kwargs={"install_date": "2024-03-01", "initial_usage_hours": 500},
        technicians=[{"full_name": "Dana Reyes", "region_code": "NW"}],
    )


@pytest.mark.parametrize(
    "arrival_instant, expected_response_minutes",
    [
        ("2026-08-18T09:59:00Z", GOLD_MAJOR_TARGET_MINUTES - 1),
        ("2026-08-18T10:00:00Z", GOLD_MAJOR_TARGET_MINUTES),
    ],
)
def test_arrival_at_or_one_minute_inside_the_gold_major_sla_target_is_met(
    api, arrival_instant, expected_response_minutes
):
    """
    A MAJOR call on a GOLD contract carries a 120-minute target, and arriving at
    minute 119 or at exactly minute 120 both freeze sla_met as true.

    PRD §3.6: "Arrival stamps `arrived_at` from the clock, computes `response_minutes`
    as `floor((arrived_at − reported_at) / 60 seconds)`, and freezes the verdict:
    `sla_met` is `true` when `response_minutes` is less than **or equal to**
    `sla_target_minutes`, so landing exactly on the target counts as met."

    Design: Difficulty/boundary_precision_check/sla_met_is_true_at_exactly_the_target_minute
    """
    fleet = _gold_club_with_one_treadmill_and_one_technician(
        api, "2026-08-18T08:00:00Z"
    )
    technician_id = fleet["technician_ids"][0]

    call = open_call(
        api,
        fleet["contract_id"],
        fleet["equipment_ids"][0],
        severity="MAJOR",
        symptom_code="BELT_SLIP",
    )
    assert call["sla_target_minutes"] == GOLD_MAJOR_TARGET_MINUTES == 120
    assert_instant(call["reported_at"], "2026-08-18T08:00:00Z", "reported_at")

    dispatch_call(api, call["id"], "2026-08-18T08:00:00Z", technician_id)
    set_clock(api, arrival_instant)
    arrived = arrive_call(api, call["id"], technician_id)

    assert arrived["response_minutes"] == expected_response_minutes
    assert arrived["sla_met"] is True
    assert_instant(arrived["arrived_at"], arrival_instant, "arrived_at")
    assert_fields(arrived, status="ON_SITE", sla_target_minutes=120)

    stored = read_call(api, call["id"])
    assert stored["response_minutes"] == expected_response_minutes
    assert stored["sla_met"] is True


def test_one_minute_past_the_sla_target_breaches_while_the_exact_minute_still_meets(api):
    """
    Two identical MAJOR calls reported at the same instant on one GOLD contract:
    the technician who lands at minute 120 meets the promise and the one who lands
    at minute 121 breaches it.

    PRD §3.6: "Arrival stamps `arrived_at` from the clock, computes `response_minutes`
    as `floor((arrived_at − reported_at) / 60 seconds)`, and freezes the verdict:
    `sla_met` is `true` when `response_minutes` is less than **or equal to**
    `sla_target_minutes`, so landing exactly on the target counts as met."

    Design: Difficulty/boundary_precision_check/sla_met_is_true_at_exactly_the_target_minute
    """
    fleet = build_fleet(
        api,
        clock="2026-08-18T08:00:00Z",
        serials=["SN-SLA-1", "SN-SLA-2"],
        equipment_kwargs={"install_date": "2024-03-01", "initial_usage_hours": 500},
        technicians=[
            {"full_name": "Dana Reyes", "region_code": "NW"},
            {"full_name": "Nils Okonjo", "region_code": "NW"},
        ],
    )
    first_technician, second_technician = fleet["technician_ids"]

    call_at_target = open_call(
        api,
        fleet["contract_id"],
        fleet["equipment_ids"][0],
        severity="MAJOR",
        symptom_code="BELT_SLIP",
    )
    call_past_target = open_call(
        api,
        fleet["contract_id"],
        fleet["equipment_ids"][1],
        severity="MAJOR",
        symptom_code="ROLLER_WEAR",
    )
    assert call_at_target["sla_target_minutes"] == 120
    assert call_past_target["sla_target_minutes"] == 120

    dispatch_call(api, call_at_target["id"], "2026-08-18T08:00:00Z", first_technician)
    dispatch_call(api, call_past_target["id"], "2026-08-18T08:00:00Z", second_technician)

    set_clock(api, "2026-08-18T10:00:00Z")
    met = arrive_call(api, call_at_target["id"], first_technician)
    assert met["response_minutes"] == 120
    assert met["sla_met"] is True

    set_clock(api, "2026-08-18T10:01:00Z")
    breached = arrive_call(api, call_past_target["id"], second_technician)
    assert breached["response_minutes"] == 121
    assert breached["sla_met"] is False
    assert_instant(breached["arrived_at"], "2026-08-18T10:01:00Z", "arrived_at")

    stored_met = read_call(api, call_at_target["id"])
    stored_breached = read_call(api, call_past_target["id"])
    assert stored_met["sla_met"] is True
    assert stored_breached["sla_met"] is False
    assert_fields(stored_met, status="ON_SITE", response_minutes=120)
    assert_fields(stored_breached, status="ON_SITE", response_minutes=121)


def _quotable_gold_club_with_one_unit(api, clock):
    """One 2024-03-01 treadmill at 4000 hours under a GOLD/FULL 140000-cent term."""
    return build_fleet(
        api,
        clock=clock,
        serials=["SN-PMC-1"],
        equipment_kwargs={"install_date": "2024-03-01", "initial_usage_hours": 4000},
        contract_kwargs={"annual_base_cents": 140000},
        technicians=[{"full_name": "Dana Reyes", "region_code": "NW"}],
    )


def test_a_cancelled_visit_leaves_compliance_at_exactly_100_pct_on_the_quote(api):
    """
    A cancelled visit enters neither compliance counter, so the denominator is still
    zero and the quote freezes pm_compliance_pct_snapshot at exactly 100.00, which is
    what earns the top discount step and a quoted_annual_cents of 134520.

    PRD §3.4: "When that denominator is zero — a contract with no visit history at all
    — the value is exactly `100.00`, not zero and not null."

    Design: Difficulty/boundary_precision_check/pm_compliance_empty_history_snapshots_exactly_100_pct_on_a_quote
    """
    fleet = _quotable_gold_club_with_one_unit(api, "2026-08-20T08:00:00Z")
    contract_id = fleet["contract_id"]

    visit = schedule_visit(
        api,
        contract_id,
        fleet["equipment_ids"][0],
        "2026-08-22T08:00:00Z",
        "2026-08-22T09:30:00Z",
        fleet["technician_ids"][0],
    )
    get_success_data(
        api.cancel_visit(
            visit["id"],
            visit_cancel_payload(reason="Club closed the cardio floor that morning"),
            SERVICE_COORDINATOR,
        )
    )
    assert_fields(read_visit(api, visit["id"]), visit_status="CANCELLED")

    before = read_contract(api, contract_id)
    assert_fields(before, pm_visits_completed_count=0, pm_visits_missed_count=0)
    assert_two_decimals(
        before["pm_compliance_pct"],
        expected_pm_compliance_pct(0, 0),
        "pm_compliance_pct",
    )
    assert_two_decimals(before["pm_compliance_pct"], Decimal("100.00"))

    set_clock(api, "2026-08-20T12:00:00Z")
    quote = get_success_data(
        api.create_renewal_quote(
            contract_id,
            renewal_quote_payload(contract_version(api, contract_id)),
            CONTRACT_ADMIN,
        ),
        201,
    )

    assert_two_decimals(
        quote["pm_compliance_pct_snapshot"], Decimal("100.00"), "snapshot"
    )
    assert_money(quote["quoted_base_cents"], 120000, "quoted_base_cents")
    assert_money(quote["parts_surcharge_cents"], 21600, "parts_surcharge_cents")
    assert quote["sla_breach_count"] == 0
    assert quote["critical_call_count"] == 0
    assert_two_decimals(quote["history_load_pct"], Decimal("0.00"), "history_load_pct")
    assert_money(quote["history_surcharge_cents"], 0, "history_surcharge_cents")
    assert_money(quote["subtotal_cents"], 141600, "subtotal_cents")
    assert_two_decimals(
        quote["compliance_discount_pct"], Decimal("0.05"), "compliance_discount_pct"
    )
    assert_money(quote["compliance_discount_cents"], 7080, "compliance_discount_cents")
    assert_money(quote["quoted_annual_cents"], 134520, "quoted_annual_cents")
    assert quote["floor_applied"] is False
    assert quote["cap_applied"] is False
    assert_two_decimals(quote["fleet_age_index"], Decimal("1.00"), "fleet_age_index")
    assert_instant(quote["issued_at"], "2026-08-20T12:00:00Z", "issued_at")
    assert_instant(quote["expires_at"], "2026-09-19T12:00:00Z", "expires_at")

    assert len(quote["line_items"]) == 1
    line = quote["line_items"][0]
    assert line["equipment_id"] == fleet["equipment_ids"][0]
    assert line["age_years"] == 2
    assert_two_decimals(line["age_multiplier"], Decimal("1.00"), "age_multiplier")
    assert_two_decimals(
        line["condition_multiplier"], Decimal("1.00"), "condition_multiplier"
    )
    assert_money(line["line_cents"], 120000, "line_cents")


def test_one_missed_visit_moves_the_denominator_off_zero_and_kills_the_discount(api):
    """
    The adjacent case to the empty history: a single missed visit makes the
    denominator 1, so pm_compliance_pct is 0.00 rather than the empty-history 100.00,
    the quote snapshots 0.00 and no compliance discount is applied at all.

    PRD §3.9: "`compliance_discount_pct` is `0.05` when that snapshot is at or above
    `90.00`, `0.02` when it is at or above `75.00`, and `0.00` otherwise;
    `compliance_discount_cents = round_half_up(subtotal_cents × compliance_discount_pct)`."

    Design: Difficulty/boundary_precision_check/pm_compliance_empty_history_snapshots_exactly_100_pct_on_a_quote
    """
    fleet = _quotable_gold_club_with_one_unit(api, "2026-08-20T08:00:00Z")
    contract_id = fleet["contract_id"]

    visit = schedule_visit(
        api,
        contract_id,
        fleet["equipment_ids"][0],
        "2026-08-22T08:00:00Z",
        "2026-08-22T09:30:00Z",
        fleet["technician_ids"][0],
    )
    set_clock(api, "2026-08-22T09:30:00Z")
    get_success_data(api.mark_visit_missed(visit["id"], SERVICE_COORDINATOR))
    assert_fields(read_visit(api, visit["id"]), visit_status="MISSED")

    before = read_contract(api, contract_id)
    assert_fields(before, pm_visits_completed_count=0, pm_visits_missed_count=1)
    assert_two_decimals(
        before["pm_compliance_pct"],
        expected_pm_compliance_pct(0, 1),
        "pm_compliance_pct",
    )
    assert_two_decimals(before["pm_compliance_pct"], Decimal("0.00"))

    quote = get_success_data(
        api.create_renewal_quote(
            contract_id,
            renewal_quote_payload(contract_version(api, contract_id)),
            CONTRACT_ADMIN,
        ),
        201,
    )

    assert_two_decimals(
        quote["pm_compliance_pct_snapshot"], Decimal("0.00"), "snapshot"
    )
    assert_money(quote["quoted_base_cents"], 120000, "quoted_base_cents")
    assert_money(quote["parts_surcharge_cents"], 21600, "parts_surcharge_cents")
    assert_money(quote["subtotal_cents"], 141600, "subtotal_cents")
    assert_two_decimals(
        quote["compliance_discount_pct"], Decimal("0.00"), "compliance_discount_pct"
    )
    assert_money(quote["compliance_discount_cents"], 0, "compliance_discount_cents")
    assert_money(quote["quoted_annual_cents"], 141600, "quoted_annual_cents")
    assert quote["floor_applied"] is False
    assert quote["cap_applied"] is False
