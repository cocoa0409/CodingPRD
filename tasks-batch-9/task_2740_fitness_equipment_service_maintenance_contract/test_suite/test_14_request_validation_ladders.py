"""
Request validation: the strictly ordered rejection ladder, the safety rules that
outrank every commercial one, the guards that fire at creation time, and the ledger
and stock guards that refuse impossible arithmetic.

Each rejection is checked as an exact error identifier together with the HTTP status
the PRD's catalogue assigns to it, and each rejection is followed by a read proving
that nothing was written. Money is compared as integer cents and every instant with
the instant helper.
"""

import pytest

from test_helpers import (
    CLUB_DEFAULT_CLOSE_MINUTE,
    CLUB_DEFAULT_OPEN_MINUTE,
    CREDIT_CAP_PCT,
    ERR_ACTIVE_CONTRACT_EXISTS,
    ERR_ALLOWANCE_ADJUSTMENT_INVALID,
    ERR_CHECKLIST_INCOMPLETE,
    ERR_CHECKLIST_ITEM_UNKNOWN,
    ERR_CONTRACT_NOT_ACTIVE,
    ERR_CONTRACT_NOT_FOUND,
    ERR_DUPLICATE_OPEN_CALL,
    ERR_EQUIPMENT_CLUB_MISMATCH,
    ERR_FLEET_EMPTY,
    ERR_INJURY_SEVERITY_MISMATCH,
    ERR_INVENTORY_ADJUSTMENT_INVALID,
    ERR_NO_ELIGIBLE_TECHNICIAN,
    ERR_PART_OUT_OF_STOCK,
    ERR_PERIOD_ALREADY_RECONCILED,
    ERR_PM_FREQUENCY_BELOW_TIER,
    ERR_SAFETY_CRITICAL_FAIL_BLOCKS_COMPLETION,
    ERR_SERIAL_DUPLICATE,
    ERR_TECHNICIAN_OFF_DUTY,
    ERR_TECHNICIAN_REGION_MISMATCH,
    ERR_TECHNICIAN_SKILL_MISMATCH,
    ERR_TIER_PARTS_MISMATCH,
    ERR_USAGE_REGRESSION,
    ERR_VISIT_WINDOW_INVALID,
    MAX_VISIT_WINDOW_MINUTES,
    SLA_RESPONSE_MINUTES,
    TECHNICIAN_DEFAULT_MAX_COMMITTED_MINUTES,
    TIER_MIN_PM_VISITS,
    UNKNOWN_UUID,
    activate_contract,
    allowance_adjustment_payload,
    arrive_call,
    assert_fields,
    assert_instant,
    assert_money,
    assert_null_fields,
    assert_part_inventory_identity,
    assert_parts_allowance_identity,
    assert_technician_capacity_identity,
    assert_two_decimals,
    assignment_for_visit,
    checklist_item,
    checklist_result_payload,
    contract_payload,
    contract_version,
    credit_reconciliation_payload,
    dispatch_payload,
    duty_status_payload,
    equipment_payload,
    event_for_call,
    get_success_data,
    inventory_adjustment_payload,
    new_active_contract,
    new_club,
    new_contract,
    new_equipment,
    new_model,
    new_part,
    new_technician,
    open_call,
    parts_hold_payload,
    preventive_visit_payload,
    read_call,
    read_club,
    read_contract,
    read_equipment,
    read_part,
    read_technician,
    read_visit,
    renewal_quote_payload,
    rows_of,
    round_half_up_cents,
    schedule_visit,
    service_call_payload,
    set_clock,
    start_visit,
    technician_headers,
    usage_reading_payload,
    validate_error,
)

# A region code is two to four uppercase letters, so the two sites read NW and SW.
REGION_NORTH = "NW"
REGION_SOUTH = "SW"

GOLD_FULL_TERM = {
    "coverage_tier": "GOLD",
    "parts_inclusion": "FULL",
    "pm_visits_per_year": 4,
    "annual_base_cents": 250000,
    "initial_parts_allowance_cents": 500000,
    "term_start_date": "2026-01-01",
    "term_end_date": "2026-12-31",
}

# The window every failing attempt carries: it ends before it starts, so the last
# rung of the ladder stays violated no matter how many earlier rungs are repaired.
REVERSED_WINDOW_START = "2026-08-15T09:30:00Z"
REVERSED_WINDOW_END = "2026-08-15T08:00:00Z"
GOOD_WINDOW_START = "2026-08-15T08:00:00Z"
GOOD_WINDOW_END = "2026-08-15T09:30:00Z"


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


def _ladder_world(api, admin):
    """
    Two clubs in different regions, a machine at each, one DRAFT contract on the
    northern club, and four technicians each broken in exactly one way.
    """
    set_clock(api, "2026-08-15T07:00:00Z")
    club_a = new_club(api, name="Northside Fitness", region_code=REGION_NORTH)
    club_b = new_club(api, name="Southgate Fitness", region_code=REGION_SOUTH)
    model = _treadmill_model(api)
    unit_a = new_equipment(
        api,
        club_a["id"],
        model["id"],
        serial_number="SN-LD-A",
        install_date="2024-03-01",
        initial_usage_hours=500,
    )
    unit_b = new_equipment(
        api,
        club_b["id"],
        model["id"],
        serial_number="SN-LD-B",
        install_date="2024-03-01",
        initial_usage_hours=500,
    )
    contract = new_contract(api, club_a["id"], **GOLD_FULL_TERM)
    assert contract["status"] == "DRAFT"
    tech_south = new_technician(
        api, full_name="Sol Marin", region_code=REGION_SOUTH, skill_categories=["TREADMILL"]
    )
    tech_no_skill = new_technician(
        api, full_name="Bo Iversen", region_code=REGION_NORTH, skill_categories=["BIKE"]
    )
    tech_off = new_technician(
        api, full_name="Kit Nolan", region_code=REGION_NORTH, skill_categories=["TREADMILL"]
    )
    off_duty = get_success_data(
        api.set_duty_status(tech_off["id"], duty_status_payload("OFF_DUTY"), admin)
    )
    assert off_duty["duty_status"] == "OFF_DUTY"
    tech_ok = new_technician(
        api, full_name="Dana Reyes", region_code=REGION_NORTH, skill_categories=["TREADMILL"]
    )
    return {
        "club_a": club_a,
        "club_b": club_b,
        "model": model,
        "unit_a": unit_a,
        "unit_b": unit_b,
        "contract": contract,
        "unknown": {"id": UNKNOWN_UUID},
        "tech_south": tech_south,
        "tech_no_skill": tech_no_skill,
        "tech_off": tech_off,
        "tech_ok": tech_ok,
    }


# One rung per row, repaired strictly left to right: everything below the named rung
# is already clean and everything above it is still broken.
LADDER_RUNGS = [
    (
        "an_unresolvable_body_reference_outranks_every_business_rule",
        False,
        "unknown",
        "unit_b",
        "tech_south",
        ERR_CONTRACT_NOT_FOUND,
        404,
    ),
    (
        "a_draft_contract_outranks_the_club_mismatch",
        False,
        "contract",
        "unit_b",
        "tech_south",
        ERR_CONTRACT_NOT_ACTIVE,
        409,
    ),
    (
        "a_foreign_clubs_machine_outranks_the_region_check",
        True,
        "contract",
        "unit_b",
        "tech_south",
        ERR_EQUIPMENT_CLUB_MISMATCH,
        422,
    ),
    (
        "the_wrong_region_outranks_the_skill_check",
        True,
        "contract",
        "unit_a",
        "tech_south",
        ERR_TECHNICIAN_REGION_MISMATCH,
        422,
    ),
    (
        "the_wrong_skill_outranks_the_duty_check",
        True,
        "contract",
        "unit_a",
        "tech_no_skill",
        ERR_TECHNICIAN_SKILL_MISMATCH,
        422,
    ),
    (
        "an_off_duty_technician_outranks_the_window_check",
        True,
        "contract",
        "unit_a",
        "tech_off",
        ERR_TECHNICIAN_OFF_DUTY,
        409,
    ),
    (
        "the_reversed_window_is_the_last_rung_left_standing",
        True,
        "contract",
        "unit_a",
        "tech_ok",
        ERR_VISIT_WINDOW_INVALID,
        422,
    ),
]


@pytest.mark.parametrize(
    "activate, contract_key, equipment_key, technician_key, expected_error, expected_status",
    [row[1:] for row in LADDER_RUNGS],
    ids=[row[0] for row in LADDER_RUNGS],
)
def test_visit_creation_rejects_each_rung_in_the_declared_order(
    api,
    admin,
    coordinator,
    activate,
    contract_key,
    equipment_key,
    technician_key,
    expected_error,
    expected_status,
):
    """
    One booking shape is repaired a rung at a time while every higher rung stays
    broken, so each response names the lowest rule still violated.

    "FleetCare evaluates a request against a single, strictly ordered ladder of
    checks, and the **first** check that fails decides the response."

    Design: Corner/validations/visit_creation_walks_seven_rungs_of_the_validation_ladder
    """
    world = _ladder_world(api, admin)
    if activate:
        assert activate_contract(api, world["contract"]["id"])["status"] == "ACTIVE"

    response = api.create_preventive_visit(
        preventive_visit_payload(
            world[contract_key]["id"],
            world[equipment_key]["id"],
            REVERSED_WINDOW_START,
            REVERSED_WINDOW_END,
            world[technician_key]["id"],
        ),
        coordinator,
    )
    validate_error(response, expected_error, expected_status)

    # A refusal writes nothing: no visit, no reservation, no committed minutes.
    assert rows_of(api.list_preventive_visits(coordinator)) == []
    assert rows_of(api.list_technician_assignments(coordinator)) == []
    assert read_technician(api, world["tech_ok"]["id"])["committed_minutes"] == 0


def test_visit_creation_succeeds_once_every_rung_of_the_ladder_is_clean(api, admin, coordinator):
    """
    The eighth attempt repairs the window as well, and only then is the booking
    created with the window span as its planned minutes.

    "`planned_minutes` is the window span in whole minutes, `assigned_technician_id`
    is the named technician or the routing winner, and the `checklist` array is copied
    element by element from the model's `checklist_template`."

    Design: Corner/validations/visit_creation_walks_seven_rungs_of_the_validation_ladder
    """
    world = _ladder_world(api, admin)
    activate_contract(api, world["contract"]["id"])

    visit = get_success_data(
        api.create_preventive_visit(
            preventive_visit_payload(
                world["contract"]["id"],
                world["unit_a"]["id"],
                GOOD_WINDOW_START,
                GOOD_WINDOW_END,
                world["tech_ok"]["id"],
            ),
            coordinator,
        ),
        201,
    )
    assert_fields(
        visit,
        visit_status="SCHEDULED",
        safety_doc_status="PENDING",
        planned_minutes=90,
        assigned_technician_id=world["tech_ok"]["id"],
        checklist_total_count=0,
        checklist_resolved_count=0,
        pm_credit_earned=False,
    )
    assert_instant(visit["window_start"], GOOD_WINDOW_START, "window_start")
    assert_instant(visit["window_end"], GOOD_WINDOW_END, "window_end")
    assert_null_fields(visit, "started_at", "completed_at", "cancellation_reason")

    assignment = assignment_for_visit(api, visit["id"])
    assert assignment["status"] == "RESERVED"
    assert assignment["planned_minutes"] == 90
    assert assignment["service_call_id"] is None
    booked_tech = read_technician(api, world["tech_ok"]["id"])
    assert booked_tech["committed_minutes"] == 90
    assert_technician_capacity_identity(booked_tech, [assignment])
    # The three technicians that each failed a rung hold nothing.
    for key in ("tech_south", "tech_no_skill", "tech_off"):
        assert read_technician(api, world[key]["id"])["committed_minutes"] == 0


def test_an_injury_report_is_only_accepted_at_critical_severity(api, admin, coordinator):
    """
    The same body differing only in severity flips the outcome: an injury filed at
    MAJOR is refused with nothing written, while the same injury at CRITICAL is
    accepted and locks the machine out rather than merely marking it down.

    "And a call that reports a member injury must be filed at the top severity —
    `injury_reported` `true` with any `severity` other than `CRITICAL` is
    `ERR_INJURY_SEVERITY_MISMATCH`."

    Design: Corner/validations/an_injury_report_is_only_accepted_at_critical_severity
    """
    set_clock(api, "2026-08-15T08:00:00Z")
    club = new_club(api, name="Northside Fitness", region_code=REGION_NORTH)
    model = _treadmill_model(api)
    unit = new_equipment(
        api,
        club["id"],
        model["id"],
        serial_number="SN-IN-1",
        install_date="2024-03-01",
        initial_usage_hours=500,
    )
    contract = new_active_contract(api, club["id"], **GOLD_FULL_TERM)
    assert read_equipment(api, unit["id"])["lifecycle_status"] == "IN_SERVICE"

    refused = api.create_service_call(
        service_call_payload(
            contract["id"],
            unit["id"],
            severity="MAJOR",
            symptom_code="MEMBER_FALL",
            injury_reported=True,
        ),
        coordinator,
    )
    validate_error(refused, ERR_INJURY_SEVERITY_MISMATCH, 422)

    # Nothing at all was written: no call, no downtime event, no lockout.
    assert rows_of(api.list_service_calls(coordinator)) == []
    assert rows_of(api.list_downtime_events(admin)) == []
    untouched = read_equipment(api, unit["id"])
    assert untouched["lifecycle_status"] == "IN_SERVICE"
    assert_null_fields(untouched, "safety_lockout_reason")
    assert read_club(api, club["id"])["open_safety_lockout_count"] == 0

    accepted = get_success_data(
        api.create_service_call(
            service_call_payload(
                contract["id"],
                unit["id"],
                severity="CRITICAL",
                symptom_code="MEMBER_FALL",
                injury_reported=True,
            ),
            coordinator,
        ),
        201,
    )
    assert_fields(
        accepted,
        status="OPEN",
        severity="CRITICAL",
        safety_review_required=True,
        sla_target_minutes=60,
        parts_hold_count=0,
    )
    assert_instant(accepted["reported_at"], "2026-08-15T08:00:00Z", "reported_at")

    # An injury locks the machine out; it never merely goes DOWN.
    locked_out = read_equipment(api, unit["id"])
    assert locked_out["lifecycle_status"] == "TAGGED_OUT"
    assert locked_out["safety_lockout_reason"] == "MEMBER_INJURY"
    assert read_club(api, club["id"])["open_safety_lockout_count"] == 1

    event = event_for_call(api, accepted["id"])
    assert event["status"] == "OPEN"
    assert_instant(event["started_at"], "2026-08-15T08:00:00Z", "started_at")
    assert event["equipment_id"] == unit["id"]
    assert event["contract_id"] == contract["id"]


def test_completion_is_blocked_by_an_unresolved_or_failed_safety_item(api, admin, coordinator):
    """
    Three checklist rules fire in sequence on one visit, and once completeness is
    satisfied the higher-priority safety-critical failure takes over the refusal.

    "A visit may not be completed while any safety-critical checklist element carries
    a `FAIL` result, which answers `ERR_SAFETY_CRITICAL_FAIL_BLOCKS_COMPLETION` (409)."

    Design: Corner/validations/completion_is_blocked_by_an_unresolved_or_failed_safety_item
    """
    set_clock(api, "2026-08-15T08:00:00Z")
    club = new_club(api, name="Northside Fitness", region_code=REGION_NORTH)
    model = _treadmill_model(
        api,
        checklist_template=[
            checklist_item("BELT_TENSION", is_safety_critical=False, consumable=True),
            checklist_item("EMERGENCY_STOP", is_safety_critical=True, consumable=False),
        ],
    )
    unit = new_equipment(
        api,
        club["id"],
        model["id"],
        serial_number="SN-CK-1",
        install_date="2024-03-01",
        initial_usage_hours=500,
    )
    contract = new_active_contract(api, club["id"], **GOLD_FULL_TERM)
    tech = new_technician(
        api, full_name="Dana Reyes", region_code=REGION_NORTH, skill_categories=["TREADMILL"]
    )
    visit = schedule_visit(
        api,
        contract["id"],
        unit["id"],
        "2026-08-15T08:00:00Z",
        "2026-08-15T09:30:00Z",
        tech["id"],
    )
    assert visit["checklist_total_count"] == 2
    started = start_visit(api, visit["id"], tech["id"])
    assert started["visit_status"] == "IN_PROGRESS"

    first_result = get_success_data(
        api.record_checklist_result(
            visit["id"],
            checklist_result_payload("BELT_TENSION", result="PASS", consumable_replaced=True),
            technician_headers(tech["id"]),
        )
    )
    assert first_result["checklist_resolved_count"] == 1

    # One of two elements is still PENDING, so completion is incomplete.
    incomplete = api.complete_visit(visit["id"], technician_headers(tech["id"]))
    validate_error(incomplete, ERR_CHECKLIST_INCOMPLETE, 409)

    # A code outside the copied template is not part of this visit's checklist.
    unknown = api.record_checklist_result(
        visit["id"],
        checklist_result_payload("FLUX_CAPACITOR", result="PASS"),
        technician_headers(tech["id"]),
    )
    validate_error(unknown, ERR_CHECKLIST_ITEM_UNKNOWN, 422)
    assert read_visit(api, visit["id"])["checklist_resolved_count"] == 1

    failed_result = get_success_data(
        api.record_checklist_result(
            visit["id"],
            checklist_result_payload(
                "EMERGENCY_STOP", result="FAIL", note="E-stop does not latch"
            ),
            technician_headers(tech["id"]),
        )
    )
    assert_fields(
        failed_result,
        checklist_resolved_count=2,
        checklist_failed_count=1,
        safety_critical_failed_count=1,
    )
    # The failure is a safety state in its own right, not merely bookkeeping.
    tagged_out = read_equipment(api, unit["id"])
    assert tagged_out["lifecycle_status"] == "TAGGED_OUT"
    assert tagged_out["safety_lockout_reason"] == "SAFETY_CRITICAL_FAIL"

    # Completeness is now satisfied, so the safety rung takes over the refusal.
    blocked = api.complete_visit(visit["id"], technician_headers(tech["id"]))
    validate_error(blocked, ERR_SAFETY_CRITICAL_FAIL_BLOCKS_COMPLETION, 409)

    final_visit = read_visit(api, visit["id"])
    assert final_visit["visit_status"] == "IN_PROGRESS"
    assert final_visit["pm_credit_earned"] is False
    assert_null_fields(final_visit, "completed_at", "usage_hours_at_visit")
    final_contract = read_contract(api, contract["id"])
    assert final_contract["pm_visits_completed_count"] == 0
    assert_two_decimals(final_contract["pm_compliance_pct"], "100.00", "pm_compliance_pct")
    # The reservation is untouched by any of the three refusals.
    assert read_technician(api, tech["id"])["committed_minutes"] == 90
    assert assignment_for_visit(api, visit["id"])["status"] == "CONFIRMED"


def test_requests_that_sit_exactly_on_their_limits_are_accepted(api, admin, coordinator):
    """
    Four rules are satisfied at their exact edges in one fixture: a distinct serial, a
    SILVER contract at the tier's minimum visit count with a permitted parts
    inclusion, and a 480-minute window flush with the club's opening that reserves the
    technician's whole 480-minute ceiling.

    "The boundary is inclusive: landing exactly on the ceiling is allowed, and one
    minute beyond it is refused with `ERR_TECHNICIAN_CAPACITY_EXCEEDED`."

    Design: Corner/validations/requests_that_sit_exactly_on_their_limits_are_accepted
    """
    set_clock(api, "2026-08-15T05:00:00Z")
    club = new_club(api, name="Northside Fitness", region_code=REGION_NORTH)
    assert club["operating_open_minute"] == CLUB_DEFAULT_OPEN_MINUTE == 300
    assert club["operating_close_minute"] == CLUB_DEFAULT_CLOSE_MINUTE == 1380
    assert club["max_concurrent_visits"] == 1
    model = _treadmill_model(api)
    first_unit = new_equipment(
        api,
        club["id"],
        model["id"],
        serial_number="SN-EDGE-1",
        install_date="2024-03-01",
        initial_usage_hours=500,
    )
    tech = new_technician(
        api, full_name="Dana Reyes", region_code=REGION_NORTH, skill_categories=["TREADMILL"]
    )
    assert tech["max_committed_minutes"] == TECHNICIAN_DEFAULT_MAX_COMMITTED_MINUTES == 480

    # A serial that differs by one character satisfies the uniqueness rule.
    second_unit = get_success_data(
        api.create_equipment(
            equipment_payload(
                club["id"],
                model["id"],
                serial_number="SN-EDGE-2",
                install_date="2024-03-01",
                initial_usage_hours=500,
            ),
            admin,
        ),
        201,
    )
    assert second_unit["serial_number"] == "SN-EDGE-2" != first_unit["serial_number"]
    assert read_club(api, club["id"])["covered_unit_count"] == 2

    # SILVER permits WEAR_ONLY, and two visits a year is exactly the SILVER minimum.
    contract = get_success_data(
        api.create_contract(
            contract_payload(
                club["id"],
                coverage_tier="SILVER",
                parts_inclusion="WEAR_ONLY",
                pm_visits_per_year=2,
                annual_base_cents=180000,
                initial_parts_allowance_cents=200000,
                term_start_date="2026-01-01",
                term_end_date="2026-12-31",
            ),
            admin,
        ),
        201,
    )
    assert contract["pm_visits_per_year"] == TIER_MIN_PM_VISITS["SILVER"] == 2
    assert contract["sla_response_minutes"] == SLA_RESPONSE_MINUTES["SILVER"] == 240
    assert_money(contract["credit_cap_cents"], 27000, "credit_cap_cents")
    assert_money(
        contract["credit_cap_cents"],
        round_half_up_cents(CREDIT_CAP_PCT * 180000),
        "credit_cap_cents re-derived",
    )
    assert activate_contract(api, contract["id"])["status"] == "ACTIVE"

    # Exactly 480 minutes, starting exactly on the 05:00 opening minute.
    visit = get_success_data(
        api.create_preventive_visit(
            preventive_visit_payload(
                contract["id"],
                first_unit["id"],
                "2026-08-15T05:00:00Z",
                "2026-08-15T13:00:00Z",
                tech["id"],
            ),
            coordinator,
        ),
        201,
    )
    assert_fields(
        visit,
        visit_status="SCHEDULED",
        safety_doc_status="PENDING",
        planned_minutes=MAX_VISIT_WINDOW_MINUTES,
    )
    assert visit["planned_minutes"] == 480
    assert_instant(visit["window_start"], "2026-08-15T05:00:00Z", "window_start")
    assert_instant(visit["window_end"], "2026-08-15T13:00:00Z", "window_end")

    # The capacity gate admits equality: 0 + 480 is at most 480.
    at_ceiling = read_technician(api, tech["id"])
    assert at_ceiling["committed_minutes"] == 480 == at_ceiling["max_committed_minutes"]
    assignment = assignment_for_visit(api, visit["id"])
    assert assignment["status"] == "RESERVED"
    assert assignment["planned_minutes"] == 480
    assert_instant(assignment["start_at"], "2026-08-15T05:00:00Z", "assignment start_at")
    assert_instant(assignment["end_at"], "2026-08-15T13:00:00Z", "assignment end_at")
    assert_technician_capacity_identity(at_ceiling, [assignment])


def test_creation_time_uniqueness_and_tier_rules_each_reject_their_own_shape(
    api, admin, coordinator
):
    """
    Six creation-time guards are provoked one at a time so that each answer is
    unambiguous: a repeated serial, BRONZE reaching for FULL parts, GOLD booked below
    its visit minimum, a second activation on an already-covered club, a meter reading
    that goes backwards, and a second open call on the same machine.

    "A machine's `serial_number` must be unique across all machines, otherwise
    `ERR_SERIAL_DUPLICATE` (409)."

    Design: Corner/validations/creation_time_uniqueness_and_tier_rules_each_reject_their_own_shape
    """
    set_clock(api, "2026-08-15T08:00:00Z")
    club = new_club(api, name="Northside Fitness", region_code=REGION_NORTH)
    model = _treadmill_model(api)
    unit = new_equipment(
        api,
        club["id"],
        model["id"],
        serial_number="SN-DUP-1",
        install_date="2024-03-01",
        initial_usage_hours=500,
    )
    covered = new_active_contract(api, club["id"], **GOLD_FULL_TERM)
    # A second contract for a future term may be drafted; only activation collides.
    future = new_contract(
        api,
        club["id"],
        coverage_tier="SILVER",
        parts_inclusion="WEAR_ONLY",
        pm_visits_per_year=2,
        annual_base_cents=180000,
        initial_parts_allowance_cents=200000,
        term_start_date="2027-01-01",
        term_end_date="2027-12-31",
    )
    first_call = open_call(
        api, covered["id"], unit["id"], severity="MAJOR", symptom_code="BELT_NOISE"
    )
    assert first_call["status"] == "OPEN"
    assert read_club(api, club["id"])["covered_unit_count"] == 1

    # A different install date does not make a repeated serial a different machine.
    duplicate_serial = api.create_equipment(
        equipment_payload(
            club["id"], model["id"], serial_number="SN-DUP-1", install_date="2024-06-01"
        ),
        admin,
    )
    validate_error(duplicate_serial, ERR_SERIAL_DUPLICATE, 409)
    assert read_club(api, club["id"])["covered_unit_count"] == 1

    # BRONZE is offered only with NONE or WEAR_ONLY parts.
    bronze_full = api.create_contract(
        contract_payload(
            club["id"],
            coverage_tier="BRONZE",
            parts_inclusion="FULL",
            pm_visits_per_year=1,
            annual_base_cents=90000,
            initial_parts_allowance_cents=0,
            term_start_date="2028-01-01",
            term_end_date="2028-12-31",
        ),
        admin,
    )
    validate_error(bronze_full, ERR_TIER_PARTS_MISMATCH, 422)

    # GOLD requires at least four preventive visits a year, so three is short.
    gold_three_visits = api.create_contract(
        contract_payload(
            club["id"],
            coverage_tier="GOLD",
            parts_inclusion="FULL",
            pm_visits_per_year=3,
            annual_base_cents=250000,
            initial_parts_allowance_cents=0,
            term_start_date="2029-01-01",
            term_end_date="2029-12-31",
        ),
        admin,
    )
    validate_error(gold_three_visits, ERR_PM_FREQUENCY_BELOW_TIER, 422)
    assert TIER_MIN_PM_VISITS["GOLD"] == 4

    # The club already carries an ACTIVE contract, so the drafted one cannot start.
    second_activation = api.activate_contract(future["id"], admin)
    validate_error(second_activation, ERR_ACTIVE_CONTRACT_EXISTS, 409)
    assert read_contract(api, future["id"])["status"] == "DRAFT"

    # A meter never runs backwards: 499 is below the stored 500 hours.
    backwards = api.record_usage_reading(unit["id"], usage_reading_payload(499), coordinator)
    validate_error(backwards, ERR_USAGE_REGRESSION, 422)
    assert_two_decimals(read_equipment(api, unit["id"])["usage_hours"], "500.00", "usage_hours")

    # The first call is still open on this machine, so a second one is refused.
    second_call = api.create_service_call(
        service_call_payload(
            covered["id"], unit["id"], severity="MINOR", symptom_code="CONSOLE_DIM"
        ),
        coordinator,
    )
    validate_error(second_call, ERR_DUPLICATE_OPEN_CALL, 409)

    calls = rows_of(api.list_service_calls(coordinator, equipment_id=unit["id"]))
    assert len(calls) == 1
    assert calls[0]["id"] == first_call["id"]
    assert calls[0]["status"] == "OPEN"
    events = rows_of(api.list_downtime_events(admin, service_call_id=first_call["id"]))
    assert len(events) == 1
    assert len(rows_of(api.list_downtime_events(admin))) == 1
    assert read_contract(api, covered["id"])["status"] == "ACTIVE"
    assert len(rows_of(api.list_contracts(admin, club_id=club["id"]))) == 2


def test_ledger_and_stock_guards_refuse_impossible_arithmetic(api, admin, coordinator, planner):
    """
    Six ledger-side guards are each provoked on its own endpoint: reconciling a period
    that holds no closed outage, quoting a club with no machines, clawing back more
    allowance than exists, driving a stock bucket negative, routing with an empty
    technician pool, and drawing new stock from an empty on-hand bucket while
    refurbished units sit next to it.

    "A reconciliation's `period_key` must differ from the contract's
    `last_reconciled_period_key` and at least one `CLOSED` event must exist in that
    period, otherwise `ERR_PERIOD_ALREADY_RECONCILED` (409)."

    Design: Corner/validations/ledger_and_stock_guards_refuse_impossible_arithmetic
    """
    set_clock(api, "2026-08-15T08:00:00Z")
    club_a = new_club(api, name="Northside Fitness", region_code=REGION_NORTH)
    club_b = new_club(api, name="Southgate Fitness", region_code=REGION_SOUTH)
    model = _treadmill_model(api)
    unit = new_equipment(
        api,
        club_a["id"],
        model["id"],
        serial_number="SN-LG-1",
        install_date="2024-03-01",
        initial_usage_hours=500,
    )
    contract_a = new_active_contract(api, club_a["id"], **GOLD_FULL_TERM)
    contract_b = new_active_contract(
        api,
        club_b["id"],
        coverage_tier="BRONZE",
        parts_inclusion="NONE",
        pm_visits_per_year=1,
        annual_base_cents=90000,
        initial_parts_allowance_cents=0,
        term_start_date="2026-01-01",
        term_end_date="2026-12-31",
    )
    assert read_club(api, club_b["id"])["covered_unit_count"] == 0
    part = new_part(
        api,
        model["id"],
        part_number="BELT-STD",
        category="WEAR",
        unit_price_cents=8000,
        initial_on_hand_qty=0,
        initial_refurb_qty=2,
    )
    call = open_call(
        api, contract_a["id"], unit["id"], severity="MAJOR", symptom_code="BELT_FRAY"
    )

    # July holds no CLOSED outage at all, so there is nothing to reconcile.
    version_before = contract_version(api, contract_a["id"])
    empty_period = api.reconcile_credits(
        contract_a["id"],
        credit_reconciliation_payload("2026-07", version_before),
        admin,
    )
    validate_error(empty_period, ERR_PERIOD_ALREADY_RECONCILED, 409)
    unreconciled = read_contract(api, contract_a["id"])
    assert unreconciled["version"] == version_before
    assert_null_fields(unreconciled, "last_reconciled_period_key")

    # A club with no machines has nothing to price a renewal against.
    empty_fleet = api.create_renewal_quote(
        contract_b["id"],
        renewal_quote_payload(contract_version(api, contract_b["id"])),
        admin,
    )
    validate_error(empty_fleet, ERR_FLEET_EMPTY, 422)
    assert rows_of(api.list_renewal_quotes(admin)) == []
    assert read_contract(api, contract_b["id"])["status"] == "ACTIVE"

    # A 600000-cent clawback against a 500000-cent allowance would go negative.
    overdraw = api.adjust_parts_allowance(
        contract_a["id"], allowance_adjustment_payload(-600000, memo="clawback"), admin
    )
    validate_error(overdraw, ERR_ALLOWANCE_ADJUSTMENT_INVALID, 422)
    ledger = read_contract(api, contract_a["id"])
    assert_money(ledger["parts_allowance_total_cents"], 500000, "parts_allowance_total_cents")
    assert_money(
        ledger["parts_allowance_remaining_cents"], 500000, "parts_allowance_remaining_cents"
    )
    assert_parts_allowance_identity(ledger, [])

    # Only two refurbished units exist, so removing five drives the bucket negative.
    oversubtract = api.adjust_inventory(
        part["id"], inventory_adjustment_payload(new_qty_delta=0, refurb_qty_delta=-5), planner
    )
    validate_error(oversubtract, ERR_INVENTORY_ADJUSTMENT_INVALID, 422)
    stock = read_part(api, part["id"])
    assert stock["refurb_on_hand_qty"] == 2
    assert stock["on_hand_qty"] == 0

    # Nobody has been hired yet, so automatic routing has no candidate to pick.
    unroutable = api.dispatch_service_call(
        call["id"], dispatch_payload("2026-08-15T08:00:00Z"), coordinator
    )
    validate_error(unroutable, ERR_NO_ELIGIBLE_TECHNICIAN, 422)
    assert read_call(api, call["id"])["status"] == "OPEN"
    assert rows_of(api.list_technician_assignments(coordinator)) == []

    tech = new_technician(
        api, full_name="Dana Reyes", region_code=REGION_NORTH, skill_categories=["TREADMILL"]
    )
    get_success_data(
        api.dispatch_service_call(
            call["id"], dispatch_payload("2026-08-15T08:00:00Z", tech["id"]), coordinator
        )
    )
    on_site = arrive_call(api, call["id"], tech["id"])
    assert on_site["status"] == "ON_SITE"

    # The NEW bucket is the one that is drawn, and it is empty; the refurbished
    # units standing beside it do not satisfy the request.
    out_of_stock = api.place_parts_hold(
        call["id"], parts_hold_payload(part["id"], 1, "NEW"), technician_headers(tech["id"])
    )
    validate_error(out_of_stock, ERR_PART_OUT_OF_STOCK, 409)

    after = read_part(api, part["id"])
    assert after["allocated_qty"] == 0
    assert after["on_hand_qty"] == 0
    assert after["refurb_on_hand_qty"] == 2
    assert_part_inventory_identity(after, [])
    final_call = read_call(api, call["id"])
    assert final_call["parts_hold_count"] == 0
    # The failed hold left the call exactly where it stood.
    assert final_call["status"] == "ON_SITE"
    assert rows_of(api.list_part_orders(planner, service_call_id=call["id"])) == []
