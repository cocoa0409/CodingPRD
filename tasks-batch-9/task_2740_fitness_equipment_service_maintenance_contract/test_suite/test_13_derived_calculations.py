"""
Derived calculations: PM thresholds, condition scores, SLA targets, downtime
credit, period reconciliation, the routing selector, the renewal collar and the
technician minute ceiling.

Every monetary figure is compared as an exact integer number of cents, because the
PRD forbids fractional cents and forbids storing money as a float. Every derived
score or percentage is compared with the two-decimal helper, and every instant with
the instant helper rather than by raw string equality.
"""

from decimal import Decimal

import pytest

from test_helpers import (
    AGE_MULTIPLIER_BANDS,
    COLLAR_CAP_PCT,
    COLLAR_FLOOR_PCT,
    CREDIT_CAP_PCT,
    DOWNTIME_GRACE_MINUTES,
    DOWNTIME_RATE_CENTS_PER_HOUR,
    ERR_TECHNICIAN_CAPACITY_EXCEEDED,
    PARTS_SURCHARGE_PCT,
    REPLACEMENT_THRESHOLD_DEFAULT,
    REPLACEMENT_THRESHOLD_UNSUPPORTED,
    SEVERITY_PLANNED_MINUTES,
    SEVERITY_SLA_FACTOR,
    SLA_RESPONSE_MINUTES,
    TECHNICIAN_DEFAULT_MAX_COMMITTED_MINUTES,
    arrive_call,
    assert_fields,
    assert_instant,
    assert_money,
    assert_null_fields,
    assert_score_precision,
    assert_technician_capacity_identity,
    assert_two_decimals,
    assignment_for_call,
    canonical_instant,
    contract_version,
    credit_reconciliation_payload,
    dispatch_call,
    dispatch_payload,
    event_for_call,
    expected_credit_cents,
    get_success_data,
    new_active_contract,
    new_club,
    new_equipment,
    new_model,
    new_part,
    new_technician,
    open_call,
    read_call,
    read_club,
    read_contract,
    read_equipment,
    read_event,
    read_technician,
    record_usage,
    renewal_quote_payload,
    resolve_payload,
    round_half_up,
    round_half_up_cents,
    rows_of,
    set_clock,
    technician_headers,
    validate_error,
    waive_payload,
)

# Region codes are two to four uppercase letters, so the two sites below read NW
# and SW rather than spelled-out compass points.
REGION_NORTH = "NW"
REGION_SOUTH = "SW"
REGION_WEST = "WEST"

GOLD_FULL_TERM = {
    "coverage_tier": "GOLD",
    "parts_inclusion": "FULL",
    "pm_visits_per_year": 4,
    "annual_base_cents": 250000,
    "initial_parts_allowance_cents": 500000,
    "term_start_date": "2026-01-01",
    "term_end_date": "2026-12-31",
}


def _treadmill_model(api, **overrides):
    """A treadmill model with a 250-hour PM interval and a 20,000-hour design life."""
    spec = {
        "manufacturer": "Pacemaster",
        "model_code": "TM-900",
        "category": "TREADMILL",
        "model_year": 2019,
        "pm_interval_hours": 250,
        "expected_service_life_hours": 20000,
        "base_annual_service_cents": 120000,
    }
    spec.update(overrides)
    return new_model(api, **spec)


def _age_multiplier(age_years):
    """The step table: 1.00 for 0-2 years, 1.15 for 3-5, 1.35 for 6-8, 1.60 for 9+."""
    for low, high, factor in AGE_MULTIPLIER_BANDS:
        if age_years >= low and (high is None or age_years <= high):
            return factor
    raise AssertionError(f"no age band covers {age_years} years")


def _resolve_outage(api, contract_id, equipment_id, technician_id, reported_at, resolved_at,
                    symptom_code="BELT_NOISE", resolution_code="BELT_TENSIONED"):
    """Open, dispatch, arrive and resolve one call, returning its closed event."""
    set_clock(api, reported_at)
    call = open_call(
        api, contract_id, equipment_id, severity="MAJOR", symptom_code=symptom_code
    )
    dispatch_call(api, call["id"], reported_at, technician_id)
    arrive_call(api, call["id"], technician_id)
    set_clock(api, resolved_at)
    get_success_data(
        api.resolve_service_call(
            call["id"],
            resolve_payload(resolution_code=resolution_code),
            technician_headers(technician_id),
        )
    )
    return event_for_call(api, call["id"])


@pytest.mark.parametrize(
    "readings, expected_pm_status, expected_health",
    [
        ([749], "OK", "92.26"),
        ([749, 750], "DUE", None),
        ([749, 750, 812.49], "DUE", None),
        ([749, 750, 812.49, 812.50], "OVERDUE", "91.94"),
    ],
    ids=[
        "249_hours_since_pm_is_still_OK",
        "exactly_the_250_hour_interval_is_DUE",
        "312_point_49_hours_is_still_DUE",
        "exactly_312_point_50_hours_is_OVERDUE",
    ],
)
def test_usage_readings_round_pm_status_and_health_at_every_boundary(
    api, readings, expected_pm_status, expected_health
):
    """
    Monotonic meter readings walk both edges of the PM interval table on one unit
    while pinning the condition score to two round-half-up decimals.

    "When they are at least the interval but strictly less than the interval
    multiplied by 1.25, the status is `DUE`; the boundary is inclusive on the
    interval itself, so a machine that has run exactly its interval reads `DUE`
    rather than `OK`."

    Design: Corner/calculations/usage_readings_round_pm_status_and_health_at_every_boundary
    """
    set_clock(api, "2026-08-15T08:00:00Z")
    club = new_club(api, name="Northside Fitness", region_code=REGION_NORTH)
    model = _treadmill_model(api)
    unit = new_equipment(
        api,
        club["id"],
        model["id"],
        serial_number="SN-PM-1",
        install_date="2024-03-01",
        initial_usage_hours=500,
    )
    assert_two_decimals(unit["usage_hours"], "500.00", "seeded usage_hours")
    assert_two_decimals(
        unit["usage_hours_at_last_pm"], "500.00", "seeded usage_hours_at_last_pm"
    )
    assert unit["pm_status"] == "OK"

    row = None
    for hours in readings:
        row = record_usage(api, unit["id"], hours)

    assert_fields(row, pm_status=expected_pm_status, health_score_variant="USAGE_BASED")
    assert_two_decimals(row["usage_hours"], readings[-1], "usage_hours")
    # Only a completed preventive visit moves the PM baseline; a reading never does.
    assert_two_decimals(row["usage_hours_at_last_pm"], "500.00", "usage_hours_at_last_pm")
    assert_score_precision(row["health_score"], "health_score")

    if expected_health is not None:
        # raw = 100 - 100 x (usage_hours / 20000) - 2 x age_years, age_years = 2 here.
        raw = (
            Decimal(100)
            - Decimal(100) * Decimal(str(readings[-1])) / Decimal(20000)
            - Decimal(2) * Decimal(2)
        )
        assert_two_decimals(row["health_score"], expected_health, "health_score")
        assert_two_decimals(row["health_score"], raw, "health_score re-derived")

    assert row["replacement_recommended"] is False
    assert Decimal(str(row["health_score"])) > REPLACEMENT_THRESHOLD_DEFAULT


def test_sla_target_scales_the_pinned_tier_minutes_by_severity(api, admin):
    """
    A critical call on a gold contract and a minor call on a silver contract carry
    targets scaled from the same tier table, and the arrival verdict is decided one
    minute either side of each target.

    "`reported_at` is stamped from the logical clock, `status` is `OPEN`,
    `parts_hold_count` starts at `0`, and `sla_target_minutes` is frozen onto the call
    as `round_half_up(contract.sla_response_minutes × SEVERITY_SLA_FACTOR[severity])`,
    where the severity factor is `0.5` for `CRITICAL`, `1.0` for `MAJOR` and `2.0` for
    `MINOR`."

    Design: Corner/calculations/sla_target_scales_the_pinned_tier_minutes_by_severity
    """
    set_clock(api, "2026-08-15T08:00:00Z")
    club_north = new_club(api, name="Northside Fitness", region_code=REGION_NORTH)
    club_south = new_club(api, name="Southgate Fitness", region_code=REGION_SOUTH)
    model = _treadmill_model(api)
    unit_north = new_equipment(
        api,
        club_north["id"],
        model["id"],
        serial_number="SN-SLA-N",
        install_date="2024-03-01",
        initial_usage_hours=500,
    )
    unit_south = new_equipment(
        api,
        club_south["id"],
        model["id"],
        serial_number="SN-SLA-S",
        install_date="2024-03-01",
        initial_usage_hours=500,
    )
    gold = new_active_contract(api, club_north["id"], **GOLD_FULL_TERM)
    silver = new_active_contract(
        api,
        club_south["id"],
        coverage_tier="SILVER",
        parts_inclusion="WEAR_ONLY",
        pm_visits_per_year=2,
        annual_base_cents=180000,
        initial_parts_allowance_cents=200000,
        term_start_date="2026-01-01",
        term_end_date="2026-12-31",
    )
    tech_north = new_technician(
        api, full_name="Dana Reyes", region_code=REGION_NORTH, skill_categories=["TREADMILL"]
    )
    tech_south = new_technician(
        api, full_name="Ravi Shah", region_code=REGION_SOUTH, skill_categories=["TREADMILL"]
    )

    # The tier pins the promise; severity only scales it.
    assert gold["sla_response_minutes"] == SLA_RESPONSE_MINUTES["GOLD"] == 120
    assert silver["sla_response_minutes"] == SLA_RESPONSE_MINUTES["SILVER"] == 240

    critical = open_call(
        api,
        gold["id"],
        unit_north["id"],
        severity="CRITICAL",
        symptom_code="MOTOR_DEAD",
    )
    minor = open_call(
        api,
        silver["id"],
        unit_south["id"],
        severity="MINOR",
        symptom_code="CONSOLE_DIM",
    )
    assert critical["sla_target_minutes"] == 60
    assert critical["sla_target_minutes"] == round_half_up(
        Decimal(SLA_RESPONSE_MINUTES["GOLD"]) * SEVERITY_SLA_FACTOR["CRITICAL"]
    )
    assert minor["sla_target_minutes"] == 480
    assert minor["sla_target_minutes"] == round_half_up(
        Decimal(SLA_RESPONSE_MINUTES["SILVER"]) * SEVERITY_SLA_FACTOR["MINOR"]
    )
    assert_instant(critical["reported_at"], "2026-08-15T08:00:00Z", "reported_at")
    assert_instant(minor["reported_at"], "2026-08-15T08:00:00Z", "reported_at")
    assert critical["parts_hold_count"] == 0
    assert minor["parts_hold_count"] == 0
    assert read_equipment(api, unit_north["id"])["lifecycle_status"] == "DOWN"
    assert read_equipment(api, unit_south["id"])["lifecycle_status"] == "DOWN"

    dispatch_call(api, critical["id"], "2026-08-15T08:00:00Z", tech_north["id"])
    dispatch_call(api, minor["id"], "2026-08-15T08:00:00Z", tech_south["id"])
    assert (
        assignment_for_call(api, critical["id"])["planned_minutes"]
        == SEVERITY_PLANNED_MINUTES["CRITICAL"]
        == 180
    )
    assert (
        assignment_for_call(api, minor["id"])["planned_minutes"]
        == SEVERITY_PLANNED_MINUTES["MINOR"]
        == 60
    )

    # One minute past a sixty-minute target is a breach.
    set_clock(api, "2026-08-15T09:01:00Z")
    arrived_critical = arrive_call(api, critical["id"], tech_north["id"])
    assert arrived_critical["response_minutes"] == 61
    assert arrived_critical["sla_met"] is False
    assert_instant(arrived_critical["arrived_at"], "2026-08-15T09:01:00Z", "arrived_at")

    # One minute inside an eight-hour target is met.
    set_clock(api, "2026-08-15T15:59:00Z")
    arrived_minor = arrive_call(api, minor["id"], tech_south["id"])
    assert arrived_minor["response_minutes"] == 479
    assert arrived_minor["sla_met"] is True
    assert_instant(arrived_minor["arrived_at"], "2026-08-15T15:59:00Z", "arrived_at")


def test_each_downtime_event_absorbs_its_own_grace_before_billing(api, admin):
    """
    Three separate outages on one gold unit each spend their own three-hour grace, so
    a 180-minute outage earns nothing, a 240-minute outage earns one full hour, and a
    181-minute outage earns a single rounded minute.

    "The grace allowance is applied **per event**, never once per period, and each
    event is rounded to whole cents before any period-level sum is taken."

    Design: Corner/calculations/each_downtime_event_absorbs_its_own_grace_before_billing
    """
    set_clock(api, "2026-08-15T08:00:00Z")
    club = new_club(api, name="Northside Fitness", region_code=REGION_NORTH)
    model = _treadmill_model(api)
    unit = new_equipment(
        api,
        club["id"],
        model["id"],
        serial_number="SN-GR-1",
        install_date="2024-03-01",
        initial_usage_hours=500,
    )
    contract = new_active_contract(api, club["id"], **GOLD_FULL_TERM)
    assert_money(contract["credit_cap_cents"], 37500, "credit_cap_cents")
    assert_money(
        contract["credit_cap_cents"],
        round_half_up_cents(Decimal(250000) * CREDIT_CAP_PCT),
        "credit_cap_cents re-derived",
    )
    assert DOWNTIME_GRACE_MINUTES["GOLD"] == 180
    assert DOWNTIME_RATE_CENTS_PER_HOUR["GOLD"] == 1600
    tech = new_technician(
        api, full_name="Dana Reyes", region_code=REGION_NORTH, skill_categories=["TREADMILL"]
    )

    # Exactly the grace: billable minutes are zero, so the credit is zero, not negative.
    event_at_grace = _resolve_outage(
        api,
        contract["id"],
        unit["id"],
        tech["id"],
        "2026-08-15T08:00:00Z",
        "2026-08-15T11:00:00Z",
    )
    assert event_at_grace["downtime_minutes"] == 180
    assert_money(event_at_grace["provisional_credit_cents"], 0, "grace-only credit")
    assert_money(
        event_at_grace["provisional_credit_cents"],
        expected_credit_cents(180, "GOLD"),
        "grace-only credit re-derived",
    )
    assert event_at_grace["status"] == "CLOSED"

    # One hour past the grace on a second event: a fresh grace, then a full hour billed.
    event_one_hour_over = _resolve_outage(
        api,
        contract["id"],
        unit["id"],
        tech["id"],
        "2026-08-15T12:00:00Z",
        "2026-08-15T16:00:00Z",
        symptom_code="DECK_WORN",
    )
    assert event_one_hour_over["downtime_minutes"] == 240
    assert_money(event_one_hour_over["provisional_credit_cents"], 1600, "one hour over grace")
    assert_money(
        event_one_hour_over["provisional_credit_cents"],
        expected_credit_cents(240, "GOLD"),
        "one hour over grace re-derived",
    )

    # One minute past the grace: 1/60 x 1600 = 26.67 rounds half-up to 27 cents.
    event_one_minute_over = _resolve_outage(
        api,
        contract["id"],
        unit["id"],
        tech["id"],
        "2026-08-16T06:00:00Z",
        "2026-08-16T09:01:00Z",
        symptom_code="CONSOLE_DIM",
    )
    assert event_one_minute_over["downtime_minutes"] == 181
    assert_money(event_one_minute_over["provisional_credit_cents"], 27, "one minute over grace")
    assert_money(
        event_one_minute_over["provisional_credit_cents"],
        expected_credit_cents(181, "GOLD"),
        "one minute over grace re-derived",
    )

    # A single period-level grace would have billed 601 - 180 = 421 minutes instead.
    summary = get_success_data(api.get_credit_summary(contract["id"], admin))
    assert_money(summary["credit_provisional_cents"], 1627, "credit_provisional_cents")
    assert_money(summary["credit_accrued_cents"], 0, "credit_accrued_cents")
    assert_money(summary["credit_cap_cents"], 37500, "credit_cap_cents")
    assert summary["closed_event_count"] == 3

    final_unit = read_equipment(api, unit["id"])
    assert final_unit["downtime_minutes_ytd"] == 601
    assert final_unit["lifecycle_status"] == "IN_SERVICE"
    # Three resolved calls in the last year switch the score to the failure variant:
    # 100 - 100 x (500/20000) - 2 x 2 - (4 + 4 + 4) - 601/60 = 77.98 after rounding.
    assert final_unit["health_score_variant"] == "FAILURE_BASED"
    assert_two_decimals(final_unit["health_score"], "77.98", "health_score")
    assert_score_precision(final_unit["health_score"], "health_score")
    assert final_unit["replacement_recommended"] is False


def test_reconciliation_filters_the_period_then_clips_at_the_annual_cap(api, admin):
    """
    Five events of four different shapes sit on one contract; only the two CLOSED
    events of the requested month are settled, and the cap is consumed in creation
    order so the earlier event is paid in full and the later one is paid nothing.

    "The candidate set is narrow: `DowntimeEvent` rows on that contract whose `status`
    is exactly `CLOSED` and whose `period_key` equals the requested key."

    Design: Corner/calculations/reconciliation_filters_the_period_then_clips_at_the_annual_cap
    """
    set_clock(api, "2026-08-14T07:00:00Z")
    club = new_club(api, name="Northside Fitness", region_code=REGION_NORTH)
    model = _treadmill_model(api)
    units = [
        new_equipment(
            api,
            club["id"],
            model["id"],
            serial_number=f"SN-RC-{index}",
            install_date="2024-03-01",
            initial_usage_hours=500,
        )
        for index in (1, 2, 3, 4)
    ]
    contract = new_active_contract(
        api,
        club["id"],
        coverage_tier="GOLD",
        parts_inclusion="FULL",
        pm_visits_per_year=4,
        annual_base_cents=100000,
        initial_parts_allowance_cents=500000,
        term_start_date="2026-01-01",
        term_end_date="2026-12-31",
    )
    # A deliberately small cap: fifteen percent of a 1,000-dollar base is 150 dollars.
    assert_money(contract["credit_cap_cents"], 15000, "credit_cap_cents")
    tech = new_technician(
        api, full_name="Dana Reyes", region_code=REGION_NORTH, skill_categories=["TREADMILL"]
    )

    # A waived event in the target month: forgiven, so never a candidate.
    waived_event = _resolve_outage(
        api,
        contract["id"],
        units[3]["id"],
        tech["id"],
        "2026-08-14T07:00:00Z",
        "2026-08-14T11:00:00Z",
    )
    get_success_data(
        api.waive_downtime_event(
            waived_event["id"], waive_payload("GOODWILL_GESTURE"), admin
        )
    )

    # Fourteen operating hours: 840 - 180 grace = 660 minutes at 1600 cents/hour.
    first_closed = _resolve_outage(
        api,
        contract["id"],
        units[0]["id"],
        tech["id"],
        "2026-08-15T06:00:00Z",
        "2026-08-15T20:00:00Z",
        symptom_code="MOTOR_HOT",
    )
    # Six operating hours: 360 - 180 grace = 180 minutes at 1600 cents/hour.
    second_closed = _resolve_outage(
        api,
        contract["id"],
        units[1]["id"],
        tech["id"],
        "2026-08-16T06:00:00Z",
        "2026-08-16T12:00:00Z",
        symptom_code="DECK_WORN",
    )

    # An OPEN event in the target month: its call is still unresolved.
    set_clock(api, "2026-08-17T06:00:00Z")
    open_target_call = open_call(
        api,
        contract["id"],
        units[2]["id"],
        severity="MAJOR",
        symptom_code="BELT_SLIP",
    )
    dispatch_call(api, open_target_call["id"], "2026-08-17T06:00:00Z", tech["id"])
    arrive_call(api, open_target_call["id"], tech["id"])
    still_open_event = event_for_call(api, open_target_call["id"])
    assert still_open_event["status"] == "OPEN"
    # An event acquires `period_key` only when it closes ("acquires `ended_at` ...
    # `period_key`", and the key is "the `YYYY-MM` of `effective_end_at`"), so the
    # still-open row is pinned to the target month through the `started_at` that
    # creation copies from `reported_at`.
    assert still_open_event["started_at"].startswith("2026-08")

    # A CLOSED event in the following month: right status, wrong period.
    next_month_event = _resolve_outage(
        api,
        contract["id"],
        units[0]["id"],
        tech["id"],
        "2026-09-01T06:00:00Z",
        "2026-09-01T10:00:00Z",
        symptom_code="CONSOLE_DIM",
    )
    assert next_month_event["period_key"] == "2026-09"

    provisional_before = read_contract(api, contract["id"])["credit_provisional_cents"]
    assert_money(provisional_before, 24000, "credit_provisional_cents before settling")
    version_before = contract_version(api, contract["id"])

    summary = get_success_data(
        api.reconcile_credits(
            contract["id"],
            credit_reconciliation_payload("2026-08", version_before),
            admin,
        )
    )
    assert summary["period_key"] == "2026-08"
    # Waived, OPEN and out-of-period rows are all excluded from the candidate set.
    assert summary["reconciled_event_count"] == 2
    assert_money(summary["final_credit_total_cents"], 22400, "final_credit_total_cents")
    assert_money(summary["posted_credit_cents"], 15000, "posted_credit_cents")
    assert_money(summary["forgone_credit_cents"], 7400, "forgone_credit_cents")
    assert_money(
        summary["contract_credit_accrued_cents"], 15000, "contract_credit_accrued_cents"
    )
    assert (
        summary["posted_credit_cents"] + summary["forgone_credit_cents"]
        == summary["final_credit_total_cents"]
    )
    # The PRD says the version is incremented by one when the loop finishes.
    assert summary["contract_version"] == version_before + 1

    settled_first = read_event(api, first_closed["id"])
    assert settled_first["status"] == "RECONCILED"
    assert settled_first["operating_downtime_minutes"] == 840
    assert_money(settled_first["final_credit_cents"], 17600, "first final_credit_cents")
    assert_money(
        settled_first["final_credit_cents"],
        expected_credit_cents(840, "GOLD"),
        "first final_credit_cents re-derived",
    )
    # The whole cap goes to the earlier row, leaving 2,600 cents of it unclaimed.
    assert_money(settled_first["posted_credit_cents"], 15000, "first posted_credit_cents")

    settled_second = read_event(api, second_closed["id"])
    assert settled_second["status"] == "RECONCILED"
    assert settled_second["operating_downtime_minutes"] == 360
    assert_money(settled_second["final_credit_cents"], 4800, "second final_credit_cents")
    assert_money(
        settled_second["final_credit_cents"],
        expected_credit_cents(360, "GOLD"),
        "second final_credit_cents re-derived",
    )
    # Nothing remains of the cap by the time the later row is considered.
    assert_money(settled_second["posted_credit_cents"], 0, "second posted_credit_cents")

    assert read_event(api, waived_event["id"])["status"] == "WAIVED"
    assert read_event(api, still_open_event["id"])["status"] == "OPEN"
    assert read_event(api, next_month_event["id"])["status"] == "CLOSED"

    final_contract = read_contract(api, contract["id"])
    assert_money(final_contract["credit_accrued_cents"], 15000, "credit_accrued_cents")
    assert_money(final_contract["credit_forgone_cents"], 7400, "credit_forgone_cents")
    # Reconciliation posts the final figure and leaves the provisional total untouched.
    assert_money(
        final_contract["credit_provisional_cents"], 24000, "credit_provisional_cents"
    )
    assert final_contract["last_reconciled_period_key"] == "2026-08"
    assert final_contract["version"] == summary["contract_version"]


def test_routing_ranks_by_committed_minutes_then_by_creation_order(api, admin):
    """
    With one technician already holding two committed hours, automatic routing picks
    the emptier of the two remaining technicians and then the still-emptier third,
    never consulting an identifier.

    "Otherwise the pool is ordered by `committed_minutes` ascending, ties broken by
    `created_at` ascending so that the earliest-registered technician wins, and the
    first row is the winner."

    Design: Corner/calculations/routing_ranks_by_committed_minutes_then_by_creation_order
    """
    set_clock(api, "2026-08-15T08:00:00Z")
    club = new_club(api, name="Northside Fitness", region_code=REGION_NORTH)
    model = _treadmill_model(api)
    units = [
        new_equipment(
            api,
            club["id"],
            model["id"],
            serial_number=f"SN-RT-{index}",
            install_date="2024-03-01",
            initial_usage_hours=500,
        )
        for index in (1, 2, 3)
    ]
    contract = new_active_contract(api, club["id"], **GOLD_FULL_TERM)
    first_tech = new_technician(
        api, full_name="Dana Reyes", region_code=REGION_NORTH, skill_categories=["TREADMILL"]
    )
    second_tech = new_technician(
        api, full_name="Ravi Shah", region_code=REGION_NORTH, skill_categories=["TREADMILL"]
    )
    third_tech = new_technician(
        api, full_name="Alba Ncube", region_code=REGION_NORTH, skill_categories=["TREADMILL"]
    )
    # Registration order is the documented tie-break, so pin it explicitly.
    assert (
        canonical_instant(first_tech["created_at"])
        <= canonical_instant(second_tech["created_at"])
        <= canonical_instant(third_tech["created_at"])
    )

    # Load the first technician by naming them, so only they hold minutes.
    named_call = open_call(
        api, contract["id"], units[0]["id"], severity="MAJOR", symptom_code="BELT_NOISE"
    )
    dispatch_call(api, named_call["id"], "2026-08-15T08:00:00Z", first_tech["id"])
    assert read_technician(api, first_tech["id"])["committed_minutes"] == 120
    assert read_technician(api, second_tech["id"])["committed_minutes"] == 0
    assert read_technician(api, third_tech["id"])["committed_minutes"] == 0

    # Two candidates tie at zero minutes; the earlier registration wins.
    routed_second = dispatch_call(api, open_call(
        api, contract["id"], units[1]["id"], severity="MAJOR", symptom_code="DECK_WORN"
    )["id"], "2026-08-15T08:00:00Z")
    assert routed_second["assigned_technician_id"] == second_tech["id"]
    assert routed_second["status"] == "DISPATCHED"

    # Now only the third is empty, so the minute ranking decides before any tie-break.
    routed_third = dispatch_call(api, open_call(
        api, contract["id"], units[2]["id"], severity="MAJOR", symptom_code="CONSOLE_DIM"
    )["id"], "2026-08-15T12:00:00Z")
    assert routed_third["assigned_technician_id"] == third_tech["id"]
    assert routed_third["status"] == "DISPATCHED"

    for technician in (first_tech, second_tech, third_tech):
        row = read_technician(api, technician["id"])
        assert row["committed_minutes"] == SEVERITY_PLANNED_MINUTES["MAJOR"] == 120
        assignments = rows_of(
            api.list_technician_assignments(admin, technician_id=technician["id"])
        )
        assert len(assignments) == 1
        # A reservation only becomes CONFIRMED on arrival, and nobody has arrived.
        assert assignments[0]["status"] == "RESERVED"
        assert assignments[0]["planned_minutes"] == 120
        assert_technician_capacity_identity(row, assignments)


def test_a_cheap_computed_renewal_is_lifted_to_the_ninety_percent_floor(api, admin):
    """
    A brand-new single-machine fleet on an expensive expiring term prices far below
    the floor, so the collar raises the quote to ninety percent of the old base and
    leaves the cap untouched.

    "**The floor is applied first and the cap second.** If `quoted` is below the floor
    it is raised to the floor and `floor_applied` is set `true`; then, separately, if
    `quoted` is above the cap it is lowered to the cap and `cap_applied` is set
    `true`."

    Design: Corner/calculations/a_cheap_computed_renewal_is_lifted_to_the_ninety_percent_floor
    """
    set_clock(api, "2026-08-15T08:00:00Z")
    club = new_club(api, name="Northside Fitness", region_code=REGION_NORTH)
    model = _treadmill_model(api, model_year=2025)
    unit = new_equipment(
        api,
        club["id"],
        model["id"],
        serial_number="SN-FLOOR-1",
        install_date="2026-01-01",
        initial_usage_hours=0,
    )
    contract = new_active_contract(
        api,
        club["id"],
        coverage_tier="GOLD",
        parts_inclusion="FULL",
        pm_visits_per_year=4,
        annual_base_cents=400000,
        initial_parts_allowance_cents=500000,
        term_start_date="2026-01-01",
        term_end_date="2026-12-31",
    )
    version_before = contract_version(api, contract["id"])

    quote = get_success_data(
        api.create_renewal_quote(
            contract["id"], renewal_quote_payload(version_before), admin
        ),
        201,
    )

    # Step one: one line at 120,000 x 1.00 x 1.00.
    lines = quote["line_items"]
    assert len(lines) == 1
    assert lines[0]["equipment_id"] == unit["id"]
    assert lines[0]["age_years"] == 0
    assert_two_decimals(lines[0]["age_multiplier"], _age_multiplier(0), "age_multiplier")
    assert_two_decimals(lines[0]["age_multiplier"], "1.00", "age_multiplier")
    assert_two_decimals(lines[0]["condition_multiplier"], "1.00", "condition_multiplier")
    assert_money(lines[0]["line_cents"], 120000, "line_cents")
    assert_money(quote["quoted_base_cents"], 120000, "quoted_base_cents")

    # Step two: eighteen percent of the base for FULL parts inclusion.
    assert_money(quote["parts_surcharge_cents"], 21600, "parts_surcharge_cents")
    assert_money(
        quote["parts_surcharge_cents"],
        round_half_up_cents(Decimal(120000) * PARTS_SURCHARGE_PCT["FULL"]),
        "parts_surcharge_cents re-derived",
    )

    # Step three: a clean service year loads nothing.
    assert quote["sla_breach_count"] == 0
    assert quote["critical_call_count"] == 0
    assert_two_decimals(quote["history_load_pct"], "0.00", "history_load_pct")
    assert_money(quote["history_surcharge_cents"], 0, "history_surcharge_cents")

    # Step four and five: subtotal, then the five percent perfect-compliance discount.
    assert_money(quote["subtotal_cents"], 141600, "subtotal_cents")
    assert_two_decimals(
        quote["pm_compliance_pct_snapshot"], "100.00", "pm_compliance_pct_snapshot"
    )
    assert_two_decimals(
        quote["compliance_discount_pct"], "0.05", "compliance_discount_pct"
    )
    assert_money(quote["compliance_discount_cents"], 7080, "compliance_discount_cents")

    # Step six: 134,520 is below the 360,000 floor and nowhere near the 540,000 cap.
    assert quote["subtotal_cents"] - quote["compliance_discount_cents"] == 134520
    assert_money(quote["quoted_annual_cents"], 360000, "quoted_annual_cents")
    assert_money(
        quote["quoted_annual_cents"],
        round_half_up_cents(Decimal(400000) * COLLAR_FLOOR_PCT),
        "quoted_annual_cents re-derived from the floor",
    )
    assert quote["floor_applied"] is True
    assert quote["cap_applied"] is False
    assert quote["quoted_annual_cents"] < round_half_up_cents(
        Decimal(400000) * COLLAR_CAP_PCT
    )

    # Step seven: the index over one line, and thirty days of validity.
    assert_two_decimals(quote["fleet_age_index"], "1.00", "fleet_age_index")
    assert_score_precision(quote["fleet_age_index"], "fleet_age_index")
    assert_instant(quote["issued_at"], "2026-08-15T08:00:00Z", "issued_at")
    assert_instant(quote["expires_at"], "2026-09-14T08:00:00Z", "expires_at")
    assert quote["status"] == "ISSUED"

    after = read_contract(api, contract["id"])
    assert after["status"] == "RENEWAL_QUOTED"
    assert after["version"] == version_before + 1


def test_an_aged_unsupported_fleet_is_held_down_to_the_135_percent_cap(api, admin, planner):
    """
    A ten-year-old machine stranded by an obsolete critical spare prices at more than
    three times the expiring base, so the collar lowers the quote to 135 percent and
    the floor never engages.

    "The adders stack, so a replacement-recommended unsupported machine carries
    `1.45`."

    Design: Corner/calculations/an_aged_unsupported_fleet_is_held_down_to_the_135_percent_cap
    """
    set_clock(api, "2026-08-15T08:00:00Z")
    club = new_club(api, name="Westline Fitness", region_code=REGION_WEST)
    model = _treadmill_model(api, model_code="TM-500", model_year=2015)
    unit = new_equipment(
        api,
        club["id"],
        model["id"],
        serial_number="SN-CAP-1",
        install_date="2016-01-01",
        initial_usage_hours=5000,
    )
    # 100 - 100 x (5000/20000) - 2 x 10 = 55.00, still above the ordinary threshold.
    assert_two_decimals(unit["health_score"], "55.00", "health_score")
    assert unit["support_status"] == "SUPPORTED"
    assert unit["replacement_recommended"] is False
    assert Decimal(str(unit["health_score"])) > REPLACEMENT_THRESHOLD_DEFAULT

    contract = new_active_contract(
        api,
        club["id"],
        coverage_tier="GOLD",
        parts_inclusion="FULL",
        pm_visits_per_year=4,
        annual_base_cents=100000,
        initial_parts_allowance_cents=500000,
        term_start_date="2026-01-01",
        term_end_date="2026-12-31",
    )

    part = new_part(
        api,
        model["id"],
        part_number="MOTOR-CTRL-500",
        category="ELECTRONIC",
        unit_price_cents=90000,
        is_critical_spare=True,
        initial_on_hand_qty=0,
        initial_refurb_qty=0,
    )
    declared = get_success_data(api.declare_end_of_support(part["id"], planner))
    # No refurbished stock survives, so the part goes straight to OBSOLETE.
    assert declared["lifecycle_status"] == "OBSOLETE"

    stranded = read_equipment(api, unit["id"])
    assert stranded["support_status"] == "UNSUPPORTED"
    assert_instant(stranded["eos_notified_at"], "2026-08-15T08:00:00Z", "eos_notified_at")
    assert_two_decimals(stranded["health_score"], "55.00", "health_score after stranding")
    # The relaxed threshold of 60.00 flips the flag without the score moving at all.
    assert Decimal(str(stranded["health_score"])) <= REPLACEMENT_THRESHOLD_UNSUPPORTED
    assert stranded["replacement_recommended"] is True

    version_before = contract_version(api, contract["id"])
    quote = get_success_data(
        api.create_renewal_quote(
            contract["id"], renewal_quote_payload(version_before), admin
        ),
        201,
    )

    line = quote["line_items"][0]
    assert len(quote["line_items"]) == 1
    assert line["age_years"] == 10
    assert_two_decimals(line["age_multiplier"], _age_multiplier(10), "age_multiplier")
    assert_two_decimals(line["age_multiplier"], "1.60", "age_multiplier")
    # 1.00 + 0.25 for the recommendation + 0.20 for being unsupported.
    assert_two_decimals(line["condition_multiplier"], "1.45", "condition_multiplier")
    assert_money(line["line_cents"], 278400, "line_cents")
    assert_money(
        line["line_cents"],
        round_half_up_cents(Decimal(120000) * Decimal("1.60") * Decimal("1.45")),
        "line_cents re-derived",
    )
    assert_money(quote["quoted_base_cents"], 278400, "quoted_base_cents")
    assert_money(quote["parts_surcharge_cents"], 50112, "parts_surcharge_cents")
    assert_money(quote["history_surcharge_cents"], 0, "history_surcharge_cents")
    assert_money(quote["subtotal_cents"], 328512, "subtotal_cents")
    assert_money(quote["compliance_discount_cents"], 16426, "compliance_discount_cents")

    # 312,086 is far above the 135,000 cap, so the 90,000 floor never engages.
    assert quote["subtotal_cents"] - quote["compliance_discount_cents"] == 312086
    assert quote["subtotal_cents"] - quote["compliance_discount_cents"] > round_half_up_cents(
        Decimal(100000) * COLLAR_FLOOR_PCT
    )
    assert_money(quote["quoted_annual_cents"], 135000, "quoted_annual_cents")
    assert_money(
        quote["quoted_annual_cents"],
        round_half_up_cents(Decimal(100000) * COLLAR_CAP_PCT),
        "quoted_annual_cents re-derived from the cap",
    )
    assert quote["cap_applied"] is True
    assert quote["floor_applied"] is False
    assert_two_decimals(quote["fleet_age_index"], "1.60", "fleet_age_index")

    after = read_contract(api, contract["id"])
    assert after["obsolete_unit_count"] == 1
    assert after["replacement_candidate_count"] == 1
    # A ratio of one is at or above 0.30, so the whole fleet reads HIGH risk.
    assert after["fleet_renewal_risk"] == "HIGH"
    assert read_club(api, club["id"])["covered_unit_count"] == 1


def test_capacity_gate_admits_the_exact_ceiling_and_refuses_one_minute_more(api, coordinator):
    """
    A technician capped at 240 minutes accepts two major calls that land exactly on
    the ceiling and then refuses a minor call that would need sixty minutes more.

    "(45) On the same two operations, the technician's `committed_minutes` plus the
    candidate's `planned_minutes` must not exceed their `max_committed_minutes`,
    otherwise `ERR_TECHNICIAN_CAPACITY_EXCEEDED` (409)."

    Design: Corner/calculations/capacity_gate_admits_the_exact_ceiling_and_refuses_one_minute_more
    """
    set_clock(api, "2026-08-15T08:00:00Z")
    club = new_club(api, name="Northside Fitness", region_code=REGION_NORTH)
    model = _treadmill_model(api)
    units = [
        new_equipment(
            api,
            club["id"],
            model["id"],
            serial_number=f"SN-CAP-{index}",
            install_date="2024-03-01",
            initial_usage_hours=500,
        )
        for index in (1, 2, 3)
    ]
    contract = new_active_contract(api, club["id"], **GOLD_FULL_TERM)
    tech = new_technician(
        api,
        full_name="Dana Reyes",
        region_code=REGION_NORTH,
        skill_categories=["TREADMILL"],
        max_committed_minutes=240,
    )
    assert tech["max_committed_minutes"] == 240
    assert tech["max_committed_minutes"] < TECHNICIAN_DEFAULT_MAX_COMMITTED_MINUTES
    assert tech["committed_minutes"] == 0

    first = open_call(
        api, contract["id"], units[0]["id"], severity="MAJOR", symptom_code="BELT_NOISE"
    )
    dispatch_call(api, first["id"], "2026-08-15T08:00:00Z", tech["id"])
    assert read_technician(api, tech["id"])["committed_minutes"] == 120

    # The second major call lands the technician exactly on the ceiling, and is admitted.
    second = open_call(
        api, contract["id"], units[1]["id"], severity="MAJOR", symptom_code="DECK_WORN"
    )
    admitted = dispatch_call(api, second["id"], "2026-08-15T11:00:00Z", tech["id"])
    assert admitted["status"] == "DISPATCHED"
    assert admitted["assigned_technician_id"] == tech["id"]
    at_ceiling = read_technician(api, tech["id"])
    assert at_ceiling["committed_minutes"] == 240 == at_ceiling["max_committed_minutes"]

    # One more minute of work is one minute too many, even for a sixty-minute call.
    third = open_call(
        api, contract["id"], units[2]["id"], severity="MINOR", symptom_code="CONSOLE_DIM"
    )
    refused = api.dispatch_service_call(
        third["id"],
        dispatch_payload("2026-08-15T14:00:00Z", tech["id"]),
        coordinator,
    )
    validate_error(refused, ERR_TECHNICIAN_CAPACITY_EXCEEDED, 409)

    unchanged = read_technician(api, tech["id"])
    assert unchanged["committed_minutes"] == 240
    assignments = rows_of(
        api.list_technician_assignments(coordinator, technician_id=tech["id"])
    )
    assert len(assignments) == 2
    assert_technician_capacity_identity(unchanged, assignments)

    rejected_call = read_call(api, third["id"])
    assert rejected_call["status"] == "OPEN"
    assert_null_fields(rejected_call, "assigned_technician_id", "dispatched_at")
    # The machine is still out of service; only the reservation was refused.
    assert read_equipment(api, units[2]["id"])["lifecycle_status"] == "DOWN"
