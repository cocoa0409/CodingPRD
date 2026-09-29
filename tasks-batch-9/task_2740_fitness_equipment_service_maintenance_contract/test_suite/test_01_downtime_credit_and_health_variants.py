"""
Two-variant derivations on one row.

FleetCare produces two different numbers for the same underlying fact in two
places, and the row itself records which model produced the value:

* one ``DowntimeEvent`` carries a provisional wall-clock credit computed when the
  field technician closes the call, and a final operating-hours credit computed
  later by the administrator's reconciliation of the period;
* one ``Equipment`` row scores under the usage-based condition model until its
  third resolved call inside 365 days arrives, at which point the failure-based
  model takes over and the two formulas share no inputs at all.

Every world below is built from scratch through declared endpoints, because the
server restarts with an empty database before each test.
"""

from test_helpers import (
    CONTRACT_ADMIN,
    arrive_call,
    assert_fields,
    assert_instant,
    assert_money,
    assert_two_decimals,
    contract_version,
    credit_reconciliation_payload,
    dispatch_call,
    event_for_call,
    expected_credit_cents,
    get_success_data,
    new_active_contract,
    new_club,
    new_equipment,
    new_model,
    new_technician,
    open_call,
    read_call,
    read_contract,
    read_equipment,
    read_event,
    resolve_payload,
    set_clock,
    technician_headers,
)

TREADMILL_MODEL = {
    "manufacturer": "Pacemaster",
    "model_code": "TM-900",
    "category": "TREADMILL",
    "model_year": 2019,
    "pm_interval_hours": 250,
    "expected_service_life_hours": 20000,
    "base_annual_service_cents": 120000,
}

GOLD_FULL_TERM = {
    "coverage_tier": "GOLD",
    "parts_inclusion": "FULL",
    "pm_visits_per_year": 4,
    "annual_base_cents": 250000,
    "initial_parts_allowance_cents": 500000,
    "term_start_date": "2026-01-01",
    "term_end_date": "2026-12-31",
}


def _resolve_one_call(
    api,
    contract_id,
    equipment_id,
    technician_id,
    severity,
    symptom_code,
    dispatch_at,
    resolved_at,
):
    """Open a call at the current clock, work it, and resolve it at ``resolved_at``."""
    call = open_call(
        api,
        contract_id,
        equipment_id,
        severity=severity,
        symptom_code=symptom_code,
    )
    dispatch_call(api, call["id"], dispatch_at, technician_id)
    arrive_call(api, call["id"], technician_id)
    set_clock(api, resolved_at)
    resolved = get_success_data(
        api.resolve_service_call(
            call["id"],
            resolve_payload(resolution_code="PART_REPLACED"),
            technician_headers(technician_id),
        )
    )
    return resolved


def _overnight_outage_world(api):
    """
    A GOLD/FULL club open 05:00-23:00 UTC whose treadmill is down from
    2026-08-10T20:00Z to 2026-08-11T09:00Z, so the outage straddles the closure.
    """
    set_clock(api, "2026-08-10T19:00:00Z")
    club = new_club(
        api,
        name="Northside Fitness",
        region_code="NW",
        operating_open_minute=300,
        operating_close_minute=1380,
    )
    model = new_model(api, **TREADMILL_MODEL)
    unit = new_equipment(
        api,
        club["id"],
        model["id"],
        serial_number="SN-DT-1",
        install_date="2024-03-01",
        initial_usage_hours=100,
    )
    contract = new_active_contract(api, club["id"], **GOLD_FULL_TERM)
    technician = new_technician(
        api,
        full_name="Dana Reyes",
        region_code="NW",
        skill_categories=["TREADMILL"],
    )
    set_clock(api, "2026-08-10T20:00:00Z")
    call = open_call(
        api,
        contract["id"],
        unit["id"],
        severity="MAJOR",
        symptom_code="BELT_SLIP",
    )
    dispatch_call(api, call["id"], "2026-08-10T20:30:00Z", technician["id"])
    set_clock(api, "2026-08-10T20:30:00Z")
    arrive_call(api, call["id"], technician["id"])
    set_clock(api, "2026-08-11T09:00:00Z")
    get_success_data(
        api.resolve_service_call(
            call["id"],
            resolve_payload(resolution_code="BELT_REPLACED"),
            technician_headers(technician["id"]),
        )
    )
    return {
        "club_id": club["id"],
        "equipment_id": unit["id"],
        "contract_id": contract["id"],
        "technician_id": technician["id"],
        "call_id": call["id"],
        "event_id": event_for_call(api, call["id"])["id"],
    }


def test_closing_the_event_bills_every_wall_clock_minute_as_the_provisional_credit(api):
    """
    A 780-minute overnight outage closes with the wall-clock variant: 16000 cents
    on a GOLD term, alongside the 420 operating minutes the final variant will use.

    PRD 3.8: "The *provisional wall-clock* variant is computed at closure, by the
    field technician's own action. It takes `billable = max(0, downtime_minutes −
    grace)` and sets `provisional_credit_cents = round_half_up(billable / 60 ×
    rate)`."

    Design: Difficulty/dual_variant_calc/downtime_credit_wall_clock_provisional_vs_operating_hours_final
    """
    world = _overnight_outage_world(api)

    event = read_event(api, world["event_id"])
    assert_fields(event, status="CLOSED", period_key="2026-08")
    assert_instant(event["started_at"], "2026-08-10T20:00:00Z", "started_at")
    assert_instant(event["ended_at"], "2026-08-11T09:00:00Z", "ended_at")
    assert_instant(
        event["effective_end_at"], "2026-08-11T09:00:00Z", "effective_end_at"
    )

    # 20:00 -> 09:00 the next day is 780 wall-clock minutes; only 180 of them on
    # the 10th (20:00-23:00) and 240 on the 11th (05:00-09:00) fall inside trading
    # hours, so the operating span is 420 minutes.
    assert event["downtime_minutes"] == 780, event["downtime_minutes"]
    assert event["operating_downtime_minutes"] == 420, (
        event["operating_downtime_minutes"]
    )
    assert_money(
        event["provisional_credit_cents"],
        expected_credit_cents(780, "GOLD"),
        "provisional_credit_cents",
    )
    assert_money(event["provisional_credit_cents"], 16000, "provisional_credit_cents")

    contract = read_contract(api, world["contract_id"])
    assert_money(
        contract["credit_provisional_cents"], 16000, "credit_provisional_cents"
    )
    assert_money(contract["credit_accrued_cents"], 0, "credit_accrued_cents")
    assert_money(contract["credit_forgone_cents"], 0, "credit_forgone_cents")
    assert_money(contract["credit_cap_cents"], 37500, "credit_cap_cents")
    assert contract["last_reconciled_period_key"] is None

    assert read_call(api, world["call_id"])["status"] == "RESOLVED"


def test_reconciling_the_period_rebills_only_operating_minutes_as_the_final_credit(api):
    """
    The same event is re-derived at reconciliation from the 420 trading minutes and
    posts 6400 cents, while the 16000-cent estimate stays on the row for audit.

    PRD 3.8: "The *final operating-hours* variant is computed at reconciliation, by
    a contract administrator. It takes `billable = max(0,
    operating_downtime_minutes − grace)` and sets `final_credit_cents =
    round_half_up(billable / 60 × rate)`."

    Design: Difficulty/dual_variant_calc/downtime_credit_wall_clock_provisional_vs_operating_hours_final
    """
    world = _overnight_outage_world(api)

    version_before = contract_version(api, world["contract_id"])
    summary = get_success_data(
        api.reconcile_credits(
            world["contract_id"],
            credit_reconciliation_payload("2026-08", version_before),
            CONTRACT_ADMIN,
        )
    )

    assert summary["period_key"] == "2026-08", summary["period_key"]
    assert summary["reconciled_event_count"] == 1, summary["reconciled_event_count"]
    assert_money(
        summary["final_credit_total_cents"],
        expected_credit_cents(420, "GOLD"),
        "final_credit_total_cents",
    )
    assert_money(summary["final_credit_total_cents"], 6400, "final_credit_total_cents")
    assert_money(summary["posted_credit_cents"], 6400, "posted_credit_cents")
    assert_money(summary["forgone_credit_cents"], 0, "forgone_credit_cents")
    assert_money(
        summary["contract_credit_accrued_cents"], 6400, "contract_credit_accrued_cents"
    )
    assert summary["contract_version"] == version_before + 1, summary["contract_version"]

    event = read_event(api, world["event_id"])
    assert event["status"] == "RECONCILED", event["status"]
    assert_money(event["final_credit_cents"], 6400, "final_credit_cents")
    assert_money(event["posted_credit_cents"], 6400, "posted_credit_cents")
    # Reconciliation leaves the first estimate untouched: the two variants sit side
    # by side on the row, 16000 against 6400.
    assert_money(
        event["provisional_credit_cents"], 16000, "provisional_credit_cents"
    )

    contract = read_contract(api, world["contract_id"])
    assert_money(contract["credit_accrued_cents"], 6400, "credit_accrued_cents")
    assert_money(contract["credit_forgone_cents"], 0, "credit_forgone_cents")
    assert_money(
        contract["credit_provisional_cents"], 16000, "credit_provisional_cents"
    )
    assert contract["last_reconciled_period_key"] == "2026-08", (
        contract["last_reconciled_period_key"]
    )


def _repeatedly_repaired_treadmill(api):
    """
    A seven-year-old treadmill at 6000 of 20000 design hours with two resolved
    CRITICAL calls of one hour each, and a third CRITICAL call still ON_SITE.
    """
    set_clock(api, "2026-08-20T08:00:00Z")
    club = new_club(api, name="Northside Fitness", region_code="NW")
    model = new_model(api, **TREADMILL_MODEL)
    unit = new_equipment(
        api,
        club["id"],
        model["id"],
        serial_number="SN-HS-1",
        install_date="2019-05-10",
        initial_usage_hours=6000,
    )
    contract = new_active_contract(api, club["id"], **GOLD_FULL_TERM)
    technician = new_technician(
        api,
        full_name="Dana Reyes",
        region_code="NW",
        skill_categories=["TREADMILL"],
    )
    _resolve_one_call(
        api,
        contract["id"],
        unit["id"],
        technician["id"],
        "CRITICAL",
        "DECK_SEIZED",
        "2026-08-20T08:00:00Z",
        "2026-08-20T09:00:00Z",
    )
    _resolve_one_call(
        api,
        contract["id"],
        unit["id"],
        technician["id"],
        "CRITICAL",
        "MOTOR_FAULT",
        "2026-08-20T09:00:00Z",
        "2026-08-20T10:00:00Z",
    )
    return {
        "club_id": club["id"],
        "equipment_id": unit["id"],
        "contract_id": contract["id"],
        "technician_id": technician["id"],
    }


def test_two_resolved_calls_keep_the_condition_score_on_the_usage_based_variant(api):
    """
    With only two resolved calls in the trailing year the row stays USAGE_BASED and
    scores 56.00 from wear and age alone — three hours of downtime move it not at all.

    PRD 3.9: "The `USAGE_BASED` variant scores wear and age and ignores failures
    entirely. It takes `usage_ratio = usage_hours / model.expected_service_life_hours`
    and `age_years = floor((clock date − install_date) / 365 days)`, then `raw = 100
    − (100 × usage_ratio) − (2 × age_years)`."

    Design: Difficulty/dual_variant_calc/equipment_health_usage_based_vs_failure_based_after_third_call
    """
    world = _repeatedly_repaired_treadmill(api)

    unit = read_equipment(api, world["equipment_id"])
    assert unit["health_score_variant"] == "USAGE_BASED", unit["health_score_variant"]
    # 6000 / 20000 is 30% of the design life and the unit is seven years old:
    # 100 − 30 − 14 = 56.00, whatever the repair history says.
    assert_two_decimals(unit["health_score"], 56.00, "health_score")
    assert_two_decimals(unit["usage_hours"], 6000, "usage_hours")
    assert unit["downtime_minutes_ytd"] == 120, unit["downtime_minutes_ytd"]
    assert unit["replacement_recommended"] is False
    assert unit["support_status"] == "SUPPORTED", unit["support_status"]

    contract = read_contract(api, world["contract_id"])
    assert contract["replacement_candidate_count"] == 0, (
        contract["replacement_candidate_count"]
    )


def test_third_resolved_call_switches_the_condition_score_to_the_failure_variant(api):
    """
    Resolving the third call inside 365 days flips the variant and re-scores the same
    row from severity-weighted failures and accrued downtime: 77.00 instead of 56.00.

    PRD 3.9: "It takes `raw = 100 − (8 × critical count) − (4 × major count) − (2 ×
    minor count) − (1 × (downtime_minutes_ytd / 60))`, where the three counts are
    over the same trailing-365-day `RESOLVED` set that selected the variant, and the
    downtime term charges one point per hour of year-to-date downtime."

    Design: Difficulty/dual_variant_calc/equipment_health_usage_based_vs_failure_based_after_third_call
    """
    world = _repeatedly_repaired_treadmill(api)

    before = read_equipment(api, world["equipment_id"])
    assert before["health_score_variant"] == "USAGE_BASED", (
        before["health_score_variant"]
    )
    assert_two_decimals(before["health_score"], 56.00, "health_score before")

    _resolve_one_call(
        api,
        world["contract_id"],
        world["equipment_id"],
        world["technician_id"],
        "MAJOR",
        "CONSOLE_DEAD",
        "2026-08-20T10:00:00Z",
        "2026-08-20T11:00:00Z",
    )

    unit = read_equipment(api, world["equipment_id"])
    assert unit["health_score_variant"] == "FAILURE_BASED", unit["health_score_variant"]
    # Two CRITICAL and one MAJOR resolution plus three hours of downtime:
    # 100 − 16 − 4 − 3 = 77.00, and the hour meter is ignored entirely.
    assert_two_decimals(unit["health_score"], 77.00, "health_score")
    assert unit["downtime_minutes_ytd"] == 180, unit["downtime_minutes_ytd"]
    assert_two_decimals(unit["usage_hours"], 6000, "usage_hours")
    assert unit["replacement_recommended"] is False
    assert unit["version"] > before["version"], "the cascade must advance version"

    contract = read_contract(api, world["contract_id"])
    assert contract["replacement_candidate_count"] == 0, (
        contract["replacement_candidate_count"]
    )
