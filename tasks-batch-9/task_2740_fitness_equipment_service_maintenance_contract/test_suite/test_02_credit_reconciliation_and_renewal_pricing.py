"""
Multi-step money formulas where the rounding order is part of the contract.

Two derivations in FleetCare are built out of several priced steps, and in both the
answer depends on where the rounding happens:

* period credit reconciliation rounds every event to whole cents on its own grace
  allowance and only then sums the period;
* the renewal quote prices each machine into a rounded line, sums the lines, loads
  the base with a parts percentage and a capped service-history percentage,
  discounts the subtotal for preventive-maintenance compliance, and finally collars
  the result against the expiring annual price with the floor before the cap.

Each test builds its own world, because the database is empty when it starts.
"""

from test_helpers import (
    CONTRACT_ADMIN,
    arrive_call,
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
    read_contract,
    read_equipment,
    read_event,
    read_quote,
    renewal_quote_payload,
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


def _work_and_resolve(
    api,
    contract_id,
    equipment_id,
    technician_id,
    severity,
    symptom_code,
    dispatch_at,
    arrive_at,
    resolved_at,
):
    """
    Open a call at the current clock, dispatch it, arrive at ``arrive_at`` and
    resolve it at ``resolved_at``, returning the call row as opened.
    """
    call = open_call(
        api,
        contract_id,
        equipment_id,
        severity=severity,
        symptom_code=symptom_code,
    )
    dispatch_call(api, call["id"], dispatch_at, technician_id)
    if arrive_at is not None:
        set_clock(api, arrive_at)
    arrive_call(api, call["id"], technician_id)
    if resolved_at is not None:
        set_clock(api, resolved_at)
    get_success_data(
        api.resolve_service_call(
            call["id"],
            resolve_payload(resolution_code="PART_REPLACED"),
            technician_headers(technician_id),
        )
    )
    return call


def _two_equal_outages_world(api):
    """
    A GOLD/FULL club whose treadmill suffers two outages of exactly 181 trading
    minutes each on 2026-08-10 — one minute past the 180-minute GOLD grace.
    """
    set_clock(api, "2026-08-10T09:00:00Z")
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
        serial_number="SN-RD-1",
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
    set_clock(api, "2026-08-10T10:00:00Z")
    first = _work_and_resolve(
        api,
        contract["id"],
        unit["id"],
        technician["id"],
        "MINOR",
        "PANEL_RATTLE",
        "2026-08-10T10:00:00Z",
        None,
        "2026-08-10T13:01:00Z",
    )
    set_clock(api, "2026-08-10T14:00:00Z")
    second = _work_and_resolve(
        api,
        contract["id"],
        unit["id"],
        technician["id"],
        "MINOR",
        "BELT_NOISE",
        "2026-08-10T14:00:00Z",
        None,
        "2026-08-10T17:01:00Z",
    )
    return {
        "contract_id": contract["id"],
        "equipment_id": unit["id"],
        "first_event_id": event_for_call(api, first["id"])["id"],
        "second_event_id": event_for_call(api, second["id"])["id"],
    }


def test_reconciliation_rounds_each_events_final_credit_on_its_own_grace(api):
    """
    Two outages of 181 trading minutes each are billed one minute apiece and round
    to 27 cents apiece, because the grace allowance is spent per event.

    PRD 3.8: "The grace allowance is applied **per event**, never once per period,
    and each event is rounded to whole cents before any period-level sum is taken."

    Design: Difficulty/combinatorial_formula/credit_reconciliation_rounds_each_event_before_summing
    """
    world = _two_equal_outages_world(api)

    for label, event_id in (
        ("first", world["first_event_id"]),
        ("second", world["second_event_id"]),
    ):
        event = read_event(api, event_id)
        assert event["status"] == "CLOSED", f"{label}: {event['status']}"
        assert event["downtime_minutes"] == 181, f"{label}: {event['downtime_minutes']}"
        assert event["operating_downtime_minutes"] == 181, (
            f"{label}: {event['operating_downtime_minutes']}"
        )
        assert event["period_key"] == "2026-08", f"{label}: {event['period_key']}"

    version_before = contract_version(api, world["contract_id"])
    get_success_data(
        api.reconcile_credits(
            world["contract_id"],
            credit_reconciliation_payload("2026-08", version_before),
            CONTRACT_ADMIN,
        )
    )

    # 181 − 180 leaves one billable minute; 1 / 60 × 1600 is 26.67 cents, which
    # rounds half up to 27 on each event separately.
    for label, event_id in (
        ("first", world["first_event_id"]),
        ("second", world["second_event_id"]),
    ):
        event = read_event(api, event_id)
        assert event["status"] == "RECONCILED", f"{label}: {event['status']}"
        assert_money(
            event["final_credit_cents"],
            expected_credit_cents(181, "GOLD"),
            f"{label} final_credit_cents",
        )
        assert_money(event["final_credit_cents"], 27, f"{label} final_credit_cents")
        assert_money(event["posted_credit_cents"], 27, f"{label} posted_credit_cents")


def test_period_total_is_the_sum_of_the_per_event_rounded_credits(api):
    """
    The period settles 54 cents across two events, not the 53 that rounding a summed
    26.67 + 26.67 would produce, and the contract ledger carries the same 54.

    PRD 3.8: "The reconciliation answers with a computed summary rather than a stored
    row: the `period_key` just settled, the `reconciled_event_count`, the
    `final_credit_total_cents` summed across those events, the `posted_credit_cents`
    and `forgone_credit_cents` totals for the run, the contract's resulting
    `contract_credit_accrued_cents`, and the new `contract_version` — which the client
    will need as the `expected_contract_version` of its next write."

    Design: Difficulty/combinatorial_formula/credit_reconciliation_rounds_each_event_before_summing
    """
    world = _two_equal_outages_world(api)

    contract_before = read_contract(api, world["contract_id"])
    # Both events measured their whole outage inside trading hours, so the wall-clock
    # estimate already stands at 27 + 27.
    assert_money(
        contract_before["credit_provisional_cents"], 54, "credit_provisional_cents"
    )
    assert_money(contract_before["credit_cap_cents"], 37500, "credit_cap_cents")

    summary = get_success_data(
        api.reconcile_credits(
            world["contract_id"],
            credit_reconciliation_payload("2026-08", contract_before["version"]),
            CONTRACT_ADMIN,
        )
    )

    assert summary["period_key"] == "2026-08", summary["period_key"]
    assert summary["reconciled_event_count"] == 2, summary["reconciled_event_count"]
    # 27 + 27 = 54. Summing the unrounded credits first gives 53.33, which rounds to
    # 53 — one cent short, and the wrong answer.
    assert_money(summary["final_credit_total_cents"], 54, "final_credit_total_cents")
    assert_money(summary["posted_credit_cents"], 54, "posted_credit_cents")
    # The 15% cap stands at 37500 cents, far above the run, so nothing is clipped.
    assert_money(summary["forgone_credit_cents"], 0, "forgone_credit_cents")
    assert_money(
        summary["contract_credit_accrued_cents"], 54, "contract_credit_accrued_cents"
    )
    assert summary["contract_version"] == contract_before["version"] + 1, (
        summary["contract_version"]
    )

    contract = read_contract(api, world["contract_id"])
    assert_money(contract["credit_accrued_cents"], 54, "credit_accrued_cents")
    assert_money(contract["credit_forgone_cents"], 0, "credit_forgone_cents")
    assert contract["last_reconciled_period_key"] == "2026-08", (
        contract["last_reconciled_period_key"]
    )


def _priced_fleet_world(api):
    """
    A GOLD/FULL club with a seven-year-old treadmill and a two-year-old one, a
    service year holding two SLA breaches and one resolved CRITICAL call, and no
    preventive-visit history at all. The clock lands on the quote instant.
    """
    set_clock(api, "2026-08-15T08:00:00Z")
    club = new_club(api, name="Northside Fitness", region_code="NW")
    model = new_model(api, **TREADMILL_MODEL)
    first = new_equipment(
        api,
        club["id"],
        model["id"],
        serial_number="SN-RQ-1",
        install_date="2019-05-10",
        initial_usage_hours=6000,
    )
    second = new_equipment(
        api,
        club["id"],
        model["id"],
        serial_number="SN-RQ-2",
        install_date="2024-03-01",
        initial_usage_hours=4000,
    )
    contract = new_active_contract(api, club["id"], **GOLD_FULL_TERM)
    technician = new_technician(
        api,
        full_name="Dana Reyes",
        region_code="NW",
        skill_categories=["TREADMILL"],
    )

    # Two MAJOR calls answered in 121 minutes against a 120-minute target: both miss.
    _work_and_resolve(
        api,
        contract["id"],
        first["id"],
        technician["id"],
        "MAJOR",
        "BELT_SLIP",
        "2026-08-15T08:00:00Z",
        "2026-08-15T10:01:00Z",
        None,
    )
    _work_and_resolve(
        api,
        contract["id"],
        second["id"],
        technician["id"],
        "MAJOR",
        "ROLLER_WEAR",
        "2026-08-15T10:30:00Z",
        "2026-08-15T12:02:00Z",
        None,
    )
    # A CRITICAL call answered in 28 minutes against its 60-minute target: met.
    _work_and_resolve(
        api,
        contract["id"],
        first["id"],
        technician["id"],
        "CRITICAL",
        "EMERGENCY_STOP",
        "2026-08-15T12:30:00Z",
        "2026-08-15T12:30:00Z",
        "2026-08-15T13:00:00Z",
    )

    set_clock(api, "2026-08-20T12:00:00Z")
    return {
        "club_id": club["id"],
        "contract_id": contract["id"],
        "first_equipment_id": first["id"],
        "second_equipment_id": second["id"],
    }


def _issue_quote(api, contract_id):
    """Issue one renewal quote on the contract at the current clock."""
    return get_success_data(
        api.create_renewal_quote(
            contract_id,
            renewal_quote_payload(contract_version(api, contract_id)),
            CONTRACT_ADMIN,
        ),
        201,
    )


def test_renewal_quote_prices_each_unit_on_its_own_age_band_before_summing(api):
    """
    The two machines price at 1.35 and 1.00 of the model's annual service figure, and
    the rounded lines sum to a 282000-cent base with a 1.18 fleet age index.

    PRD 3.9: "The line is `line_cents = round_half_up(model.base_annual_service_cents ×
    age_multiplier × condition_multiplier)`, and one entry recording `equipment_id`,
    `age_years`, `age_multiplier`, `condition_multiplier` and `line_cents` is appended
    to `line_items`."

    Design: Difficulty/combinatorial_formula/renewal_quote_pricing_stacks_age_parts_history_and_compliance
    """
    world = _priced_fleet_world(api)

    # Neither machine is a replacement candidate, so no condition adder stacks onto
    # either line: 56.00 and 76.00 both sit above the 40.00 threshold.
    older = read_equipment(api, world["first_equipment_id"])
    assert_two_decimals(older["health_score"], 56.00, "older health_score")
    assert older["replacement_recommended"] is False
    assert older["support_status"] == "SUPPORTED", older["support_status"]
    newer = read_equipment(api, world["second_equipment_id"])
    assert_two_decimals(newer["health_score"], 76.00, "newer health_score")
    assert newer["replacement_recommended"] is False

    quote = _issue_quote(api, world["contract_id"])

    lines = quote["line_items"]
    assert len(lines) == 2, lines
    # Lines are pinned in equipment created_at order, oldest machine registered first.
    assert lines[0]["equipment_id"] == world["first_equipment_id"], lines[0]
    assert lines[1]["equipment_id"] == world["second_equipment_id"], lines[1]

    # 2019-05-10 to 2026-08-20 is 2659 days, seven whole years, inside the 6-8 band.
    assert lines[0]["age_years"] == 7, lines[0]["age_years"]
    assert_two_decimals(lines[0]["age_multiplier"], 1.35, "older age_multiplier")
    assert_two_decimals(
        lines[0]["condition_multiplier"], 1.00, "older condition_multiplier"
    )
    assert_money(lines[0]["line_cents"], 162000, "older line_cents")

    # 2024-03-01 to 2026-08-20 is 902 days, two whole years, inside the 0-2 band.
    assert lines[1]["age_years"] == 2, lines[1]["age_years"]
    assert_two_decimals(lines[1]["age_multiplier"], 1.00, "newer age_multiplier")
    assert_two_decimals(
        lines[1]["condition_multiplier"], 1.00, "newer condition_multiplier"
    )
    assert_money(lines[1]["line_cents"], 120000, "newer line_cents")

    assert_money(quote["quoted_base_cents"], 282000, "quoted_base_cents")
    # (1.35 + 1.00) / 2 is 1.175, which rounds half up to 1.18.
    assert_two_decimals(quote["fleet_age_index"], 1.18, "fleet_age_index")
    assert quote["status"] == "ISSUED", quote["status"]


def test_renewal_quote_loads_parts_and_history_then_discounts_inside_the_collar(api):
    """
    On the 282000-cent base the quote loads 18% for full parts cover and a capped
    7.5% service-history charge, discounts the 353910-cent subtotal by 5% for perfect
    preventive compliance, and settles at 336214 cents inside the 225000/337500 collar.

    PRD 3.9: "Then `history_load_pct = min(0.25, 0.03 × sla_breach_count + 0.015 ×
    critical_call_count)`, and `history_surcharge_cents = round_half_up(quoted_base_cents
    × history_load_pct)`."

    Design: Difficulty/combinatorial_formula/renewal_quote_pricing_stacks_age_parts_history_and_compliance
    """
    world = _priced_fleet_world(api)

    issued = _issue_quote(api, world["contract_id"])
    quote = read_quote(api, issued["id"])

    assert_money(quote["quoted_base_cents"], 282000, "quoted_base_cents")
    # FULL parts inclusion loads the base by 0.18: 282000 × 0.18 = 50760.
    assert_money(quote["parts_surcharge_cents"], 50760, "parts_surcharge_cents")

    # Two MAJOR calls arrived at 121 minutes against a 120-minute target; the CRITICAL
    # call arrived at 28 against 60 and is not a breach.
    assert quote["sla_breach_count"] == 2, quote["sla_breach_count"]
    assert quote["critical_call_count"] == 1, quote["critical_call_count"]
    # 0.03 × 2 + 0.015 × 1 = 0.075, well under the 0.25 ceiling.
    assert abs(float(quote["history_load_pct"]) - 0.075) < 1e-9, (
        quote["history_load_pct"]
    )
    assert_money(quote["history_surcharge_cents"], 21150, "history_surcharge_cents")

    # 282000 + 50760 + 21150 = 353910.
    assert_money(quote["subtotal_cents"], 353910, "subtotal_cents")

    # No visit was ever completed or missed, so compliance snapshots at 100.00 and
    # earns the top discount band: 353910 × 0.05 = 17695.5, rounded half up to 17696.
    assert_two_decimals(
        quote["pm_compliance_pct_snapshot"], 100.00, "pm_compliance_pct_snapshot"
    )
    assert abs(float(quote["compliance_discount_pct"]) - 0.05) < 1e-9, (
        quote["compliance_discount_pct"]
    )
    assert_money(quote["compliance_discount_cents"], 17696, "compliance_discount_cents")

    # 353910 − 17696 = 336214, above the 225000 floor and below the 337500 cap, so the
    # collar leaves it alone.
    assert_money(quote["quoted_annual_cents"], 336214, "quoted_annual_cents")
    assert quote["floor_applied"] is False
    assert quote["cap_applied"] is False

    assert_instant(quote["issued_at"], "2026-08-20T12:00:00Z", "issued_at")
    assert_instant(quote["expires_at"], "2026-09-19T12:00:00Z", "expires_at")

    contract = read_contract(api, world["contract_id"])
    assert contract["status"] == "RENEWAL_QUOTED", contract["status"]
