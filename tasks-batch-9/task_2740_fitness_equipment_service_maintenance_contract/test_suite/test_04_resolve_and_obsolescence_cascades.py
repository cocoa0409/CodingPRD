"""
Cascades that reach the contract from two different triggers.

One write at the edge of the system moves rows several hops away, and each hop is
caused by the hop before it:

* resolving a third critical call closes the downtime event, grows the machine's
  year-to-date outage, flips the condition model, promotes the machine to a
  replacement candidate and lifts the contract's renewal risk;
* declaring manufacturer end of support on a critical spare with no refurbished stock
  obsoletes the part, unsupports every machine of that model, relaxes the replacement
  threshold on each of them and re-derives the same contract counters — without moving
  a single condition score.

Every world below is built from scratch through declared endpoints, because the
server restarts with an empty database before each test.
"""

from test_helpers import (
    PARTS_PLANNER,
    arrive_call,
    assert_fields,
    assert_instant,
    assert_money,
    assert_two_decimals,
    dispatch_call,
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
    read_contract,
    read_equipment,
    read_event,
    read_part,
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


def _full_day_outage(api, contract_id, equipment_id, technician_id, day, symptom_code):
    """
    Run one CRITICAL call on ``day`` from 06:00 to 18:00 — twelve hours entirely inside
    the club's 05:00-23:00 trading window — and resolve it.
    """
    set_clock(api, f"{day}T06:00:00Z")
    call = open_call(
        api,
        contract_id,
        equipment_id,
        severity="CRITICAL",
        symptom_code=symptom_code,
    )
    dispatch_call(api, call["id"], f"{day}T06:00:00Z", technician_id)
    arrive_call(api, call["id"], technician_id)
    set_clock(api, f"{day}T18:00:00Z")
    get_success_data(
        api.resolve_service_call(
            call["id"],
            resolve_payload(resolution_code="PART_REPLACED"),
            technician_headers(technician_id),
        )
    )
    return call


def _two_unit_fleet_on_its_third_breakdown(api):
    """
    A two-machine club whose worn treadmill has already been repaired twice for twelve
    hours apiece, with a third CRITICAL call sitting ON_SITE at 2026-08-04T18:00Z.
    """
    set_clock(api, "2026-08-02T05:00:00Z")
    club = new_club(
        api,
        name="Northside Fitness",
        region_code="NW",
        operating_open_minute=300,
        operating_close_minute=1380,
    )
    model = new_model(api, **TREADMILL_MODEL)
    worn = new_equipment(
        api,
        club["id"],
        model["id"],
        serial_number="SN-CS-4",
        install_date="2021-06-01",
        initial_usage_hours=8000,
    )
    spare = new_equipment(
        api,
        club["id"],
        model["id"],
        serial_number="SN-CS-5",
        install_date="2025-01-01",
        initial_usage_hours=100,
    )
    contract = new_active_contract(api, club["id"], **GOLD_FULL_TERM)
    technician = new_technician(
        api,
        full_name="Dana Reyes",
        region_code="NW",
        skill_categories=["TREADMILL"],
        max_committed_minutes=600,
    )

    _full_day_outage(
        api, contract["id"], worn["id"], technician["id"], "2026-08-02", "DECK_SEIZED"
    )
    _full_day_outage(
        api, contract["id"], worn["id"], technician["id"], "2026-08-03", "MOTOR_FAULT"
    )

    # The third call is opened, dispatched and arrived, but deliberately left unresolved:
    # its resolution is the trigger under test.
    set_clock(api, "2026-08-04T06:00:00Z")
    third = open_call(
        api,
        contract["id"],
        worn["id"],
        severity="CRITICAL",
        symptom_code="FRAME_CRACK",
    )
    dispatch_call(api, third["id"], "2026-08-04T06:00:00Z", technician["id"])
    arrive_call(api, third["id"], technician["id"])
    set_clock(api, "2026-08-04T18:00:00Z")

    return {
        "club_id": club["id"],
        "contract_id": contract["id"],
        "worn_equipment_id": worn["id"],
        "spare_equipment_id": spare["id"],
        "technician_id": technician["id"],
        "third_call_id": third["id"],
    }


def _resolve_third_call(api, world):
    return get_success_data(
        api.resolve_service_call(
            world["third_call_id"],
            resolve_payload(resolution_code="FRAME_WELDED"),
            technician_headers(world["technician_id"]),
        )
    )


def test_third_resolution_closes_the_event_and_re_scores_the_machine(api):
    """
    Resolving the third call closes its event at 720 minutes and 14400 cents, carries the
    machine's outage to 2160 minutes and re-scores it on the failure model at exactly 40.00.

    PRD 3.6: "**Hop two:** because that event closed, the machine's `downtime_minutes_ytd`
    rises by the event's `downtime_minutes`, the contract's `credit_provisional_cents`
    rises by the event's `provisional_credit_cents`, and the machine's `lifecycle_status`
    returns to `IN_SERVICE` — always from `DOWN`, but from `TAGGED_OUT` only when a
    clearance was signed, in which case `last_safety_clearance_at` is stamped and
    `safety_lockout_reason` cleared."

    Design: Difficulty/transitive_cascade/third_critical_resolve_cascades_five_hops_to_fleet_renewal_risk
    """
    world = _two_unit_fleet_on_its_third_breakdown(api)

    # Two repairs in, the machine is still scored on wear: 8000 of 20000 hours and five
    # years old is 100 − 40 − 10 = 50.00, comfortably above the 40.00 threshold.
    unit_before = read_equipment(api, world["worn_equipment_id"])
    assert_two_decimals(unit_before["health_score"], 50.00, "health_score before")
    assert unit_before["health_score_variant"] == "USAGE_BASED", (
        unit_before["health_score_variant"]
    )
    assert unit_before["replacement_recommended"] is False
    assert unit_before["downtime_minutes_ytd"] == 1440, (
        unit_before["downtime_minutes_ytd"]
    )
    contract_before = read_contract(api, world["contract_id"])
    event_before = event_for_call(api, world["third_call_id"])
    assert event_before["status"] == "OPEN", event_before["status"]

    _resolve_third_call(api, world)

    # Hop one: the call is resolved and its event closes.
    assert read_call(api, world["third_call_id"])["status"] == "RESOLVED"
    event = read_event(api, event_before["id"])
    assert event["status"] == "CLOSED", event["status"]
    assert event["version"] > event_before["version"], "the closed event must advance"

    # Hop two: 06:00 to 18:00 is 720 minutes, all of them trading minutes, so both spans
    # agree; 720 − 180 grace is 540 billable minutes at 1600 cents an hour.
    assert event["downtime_minutes"] == 720, event["downtime_minutes"]
    assert event["operating_downtime_minutes"] == 720, (
        event["operating_downtime_minutes"]
    )
    assert_money(
        event["provisional_credit_cents"],
        expected_credit_cents(720, "GOLD"),
        "provisional_credit_cents",
    )
    assert_money(event["provisional_credit_cents"], 14400, "provisional_credit_cents")

    contract = read_contract(api, world["contract_id"])
    # Three identical outages: 14400 × 3.
    assert_money(
        contract["credit_provisional_cents"], 43200, "credit_provisional_cents"
    )
    assert contract["version"] > contract_before["version"], (
        "the contract must advance on the cascade"
    )

    # Hop three: the third resolved call inside 365 days switches the model, and the
    # accumulated outage is what lands the new score on the threshold —
    # 100 − 24 − (2160 / 60) = 40.00.
    unit = read_equipment(api, world["worn_equipment_id"])
    assert unit["downtime_minutes_ytd"] == 2160, unit["downtime_minutes_ytd"]
    assert unit["health_score_variant"] == "FAILURE_BASED", (
        unit["health_score_variant"]
    )
    assert_two_decimals(unit["health_score"], 40.00, "health_score")
    assert unit["version"] > unit_before["version"], "the machine must advance"


def test_the_re_scored_machine_becomes_a_candidate_and_lifts_the_fleet_risk(api):
    """
    A score of exactly 40.00 is inclusive, so the machine becomes a replacement candidate
    and one candidate out of two machines carries the contract from LOW risk to HIGH — while
    the other machine is not touched at all.

    PRD 3.6: "**Hop five:** because the flag may have flipped, the contract's
    `replacement_candidate_count` is recomputed and `fleet_renewal_risk` re-derived from
    the new ratio (§3.9)."

    Design: Difficulty/transitive_cascade/third_critical_resolve_cascades_five_hops_to_fleet_renewal_risk
    """
    world = _two_unit_fleet_on_its_third_breakdown(api)

    contract_before = read_contract(api, world["contract_id"])
    assert contract_before["fleet_renewal_risk"] == "LOW", (
        contract_before["fleet_renewal_risk"]
    )
    assert contract_before["replacement_candidate_count"] == 0, (
        contract_before["replacement_candidate_count"]
    )
    unit_before = read_equipment(api, world["worn_equipment_id"])
    spare_before = read_equipment(api, world["spare_equipment_id"])

    _resolve_third_call(api, world)

    # Hop four: 40.00 is at the threshold, and the boundary is inclusive.
    unit = read_equipment(api, world["worn_equipment_id"])
    assert_two_decimals(unit["health_score"], 40.00, "health_score")
    assert unit["replacement_recommended"] is True
    # The resolution also returned the machine to service.
    assert unit["lifecycle_status"] == "IN_SERVICE", unit["lifecycle_status"]
    assert unit["version"] > unit_before["version"], "the machine must advance"

    # Hop five: one candidate across a two-machine fleet is a ratio of 0.50, at or above
    # the 0.30 HIGH boundary.
    contract = read_contract(api, world["contract_id"])
    assert contract["replacement_candidate_count"] == 1, (
        contract["replacement_candidate_count"]
    )
    assert contract["fleet_renewal_risk"] == "HIGH", contract["fleet_renewal_risk"]
    assert contract["version"] > contract_before["version"], (
        "the contract must advance on the cascade"
    )

    # The second machine was never in the causal chain: 100 − 0.5 − 2 = 97.50 stands.
    spare = read_equipment(api, world["spare_equipment_id"])
    assert_two_decimals(spare["health_score"], 97.50, "spare health_score")
    assert spare["replacement_recommended"] is False
    assert spare["version"] == spare_before["version"], (
        "an untouched machine must not advance"
    )


def _fleet_with_one_critical_spare(api):
    """
    A two-machine club of one model, and a critical deck spare carrying four new units
    and no refurbished stock at all. No service work has ever been done.
    """
    set_clock(api, "2026-08-15T08:00:00Z")
    club = new_club(api, name="Northside Fitness", region_code="NW")
    model = new_model(api, **TREADMILL_MODEL)
    older = new_equipment(
        api,
        club["id"],
        model["id"],
        serial_number="SN-EOS-1",
        install_date="2019-05-10",
        initial_usage_hours=6000,
    )
    newer = new_equipment(
        api,
        club["id"],
        model["id"],
        serial_number="SN-EOS-2",
        install_date="2024-03-01",
        initial_usage_hours=4000,
    )
    contract = new_active_contract(api, club["id"], **GOLD_FULL_TERM)
    part = new_part(
        api,
        model["id"],
        part_number="DECK-900",
        category="STRUCTURAL",
        unit_price_cents=32000,
        is_critical_spare=True,
        initial_on_hand_qty=4,
        initial_refurb_qty=0,
    )
    return {
        "club_id": club["id"],
        "contract_id": contract["id"],
        "model_id": model["id"],
        "older_equipment_id": older["id"],
        "newer_equipment_id": newer["id"],
        "part_id": part["id"],
    }


def test_end_of_support_with_no_refurbished_stock_obsoletes_the_part_and_the_fleet(api):
    """
    With the refurbished bucket empty the declaration skips the announced state entirely,
    and both machines of that model are notified into UNSUPPORTED on the same clock.

    PRD 3.7: "Hop one: every machine whose `model_id` matches the part's takes a new
    `support_status` — `END_OF_SUPPORT_ANNOUNCED` when the part became announced,
    `UNSUPPORTED` when the part became obsolete — and has `eos_notified_at` stamped from
    the clock."

    Design: Difficulty/transitive_cascade/obsolete_critical_spare_cascades_four_hops_to_replacement_candidates
    """
    world = _fleet_with_one_critical_spare(api)

    part_before = read_part(api, world["part_id"])
    assert part_before["lifecycle_status"] == "ACTIVE", part_before["lifecycle_status"]
    older_before = read_equipment(api, world["older_equipment_id"])
    newer_before = read_equipment(api, world["newer_equipment_id"])
    assert older_before["support_status"] == "SUPPORTED", (
        older_before["support_status"]
    )
    assert newer_before["support_status"] == "SUPPORTED", (
        newer_before["support_status"]
    )

    get_success_data(api.declare_end_of_support(world["part_id"], PARTS_PLANNER))

    # Hop one: no refurbished unit survives the declaration, so the part goes straight
    # to the terminal state rather than pausing at END_OF_SUPPORT_ANNOUNCED.
    part = read_part(api, world["part_id"])
    assert part["lifecycle_status"] == "OBSOLETE", part["lifecycle_status"]
    assert_instant(part["eos_declared_at"], "2026-08-15T08:00:00Z", "eos_declared_at")
    assert part["version"] > part_before["version"], "the part must advance"

    # Hop two: the part is a critical spare, so every machine of its model is notified.
    for label, equipment_id, before in (
        ("older", world["older_equipment_id"], older_before),
        ("newer", world["newer_equipment_id"], newer_before),
    ):
        unit = read_equipment(api, equipment_id)
        assert unit["support_status"] == "UNSUPPORTED", (
            f"{label}: {unit['support_status']}"
        )
        assert_instant(
            unit["eos_notified_at"],
            "2026-08-15T08:00:00Z",
            f"{label} eos_notified_at",
        )
        assert unit["version"] > before["version"], f"{label} must advance"


def test_the_relaxed_threshold_promotes_only_the_weaker_machine(api):
    """
    Unsupporting the fleet moves no condition score at all, but the relaxed 60.00
    threshold catches the 56.00 machine, leaves the 76.00 one alone and carries the
    contract to HIGH renewal risk.

    PRD 3.7: "An `UNSUPPORTED` machine is judged against the relaxed threshold of
    `60.00`, so any unit whose `health_score` is at or below `60.00` flips to recommended
    immediately; an `END_OF_SUPPORT_ANNOUNCED` machine keeps the ordinary `40.00`
    threshold and is very often left untouched."

    Design: Difficulty/transitive_cascade/obsolete_critical_spare_cascades_four_hops_to_replacement_candidates
    """
    world = _fleet_with_one_critical_spare(api)

    # 6000 of 20000 hours at seven years is 56.00; 4000 at two years is 76.00. Neither is
    # a candidate while the ordinary 40.00 threshold applies.
    older_before = read_equipment(api, world["older_equipment_id"])
    assert_two_decimals(older_before["health_score"], 56.00, "older health_score")
    assert older_before["replacement_recommended"] is False
    newer_before = read_equipment(api, world["newer_equipment_id"])
    assert_two_decimals(newer_before["health_score"], 76.00, "newer health_score")
    assert newer_before["replacement_recommended"] is False
    contract_before = read_contract(api, world["contract_id"])
    assert contract_before["fleet_renewal_risk"] == "LOW", (
        contract_before["fleet_renewal_risk"]
    )
    assert contract_before["replacement_candidate_count"] == 0, (
        contract_before["replacement_candidate_count"]
    )
    assert contract_before["obsolete_unit_count"] == 0, (
        contract_before["obsolete_unit_count"]
    )

    get_success_data(api.declare_end_of_support(world["part_id"], PARTS_PLANNER))

    # Hop three: the score is untouched — only the threshold it is measured against moved.
    older = read_equipment(api, world["older_equipment_id"])
    assert_two_decimals(older["health_score"], 56.00, "older health_score")
    assert older["replacement_recommended"] is True
    # No service history exists, so the wear model still owns the number.
    assert older["health_score_variant"] == "USAGE_BASED", (
        older["health_score_variant"]
    )
    assert older["version"] > older_before["version"], "the older machine must advance"

    newer = read_equipment(api, world["newer_equipment_id"])
    assert_two_decimals(newer["health_score"], 76.00, "newer health_score")
    assert newer["replacement_recommended"] is False
    assert newer["version"] > newer_before["version"], "the newer machine must advance"

    # Hop four: both machines are unsupported, one of the two is a candidate, and a 0.50
    # ratio is at or above the 0.30 HIGH boundary.
    contract = read_contract(api, world["contract_id"])
    assert_fields(
        contract,
        obsolete_unit_count=2,
        replacement_candidate_count=1,
        fleet_renewal_risk="HIGH",
    )
    assert contract["version"] > contract_before["version"], (
        "the contract must advance on the cascade"
    )
