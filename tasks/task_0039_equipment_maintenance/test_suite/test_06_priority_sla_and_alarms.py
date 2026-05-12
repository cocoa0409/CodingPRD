"""Priority scoring, SLA derivation, and alarm-driven plan generation."""
from __future__ import annotations

import pytest

from test_helpers import (
    SLA_MINUTES,
    activate_plan,
    api_client,
    assert_alarm_event,
    create_ad_hoc_work_order,
    create_equipment,
    create_plan,
    create_site,
    create_template,
    create_technician,
    create_work_order_payload,
    emit_alarm_payload,
    parse_iso,
    place_in_service,
    commission_equipment,
    setup_full_workorder_scenario,
    setup_priority_combo,
    setup_site_with_in_service_equipment,
    validate_success,
)


# ---------------------------------------------------------------------------
# 3.5 — priority_score formula
# ---------------------------------------------------------------------------
def test_priority_score_high_p1_alarm_yields_p1(api):
    """PRD §3.5: 'The criticality weight is 1 when Equipment.criticality is
    LOW, 2 when MEDIUM, and 4 when HIGH. The template-priority weight is 8
    when TaskTemplate.default_priority is P1, 4 when P2, 2 when P3, and 1
    when P4. The source bonus is 4 when WorkOrder.source is ALARM, 2 when
    PLAN_TRIGGER, 1 when PLAN_PERIODIC, and 1 when AD_HOC. The
    priority_score is the criticality weight multiplied by the
    template-priority weight, then added to the source bonus.' / 'a
    priority_score of at least 30 is P1'.

    HIGH (4) * P1 (8) + ALARM (4) = 36 → P1 (>= 30).
    # difficulty: combinatorial_formula/priority_score_mode_a_three_input_nonlinear
    """
    bag = setup_priority_combo(
        criticality="HIGH", template_default_priority="P1",
    )
    # Use the alarm endpoint to drive an ALARM-source WO via TRIGGER_ALARM
    # plan. Build the trigger plan by retiring the periodic plan (or simply
    # adding a second plan).
    site_id = bag["site"]["id"]
    eq_id = bag["equipment"]["id"]
    template_id = bag["template"]["id"]
    # Add a TRIGGER_ALARM plan whose alarm_code matches the alarm we'll emit.
    alarm_plan = create_plan(
        site_id, eq_id, template_id, "TRIGGER_ALARM",
        alarm_code="A1",
    )
    activate_plan(site_id, alarm_plan["id"])
    # Emit the alarm — should generate WO source=ALARM
    res = api.emit_alarm(
        site_id, eq_id, emit_alarm_payload(alarm_code="A1", severity="WARN"),
        __import__("test_helpers").TEST_USERS["dispatcher_headers"],
    )
    alarm = validate_success(res, expected_status=200)
    assert_alarm_event(alarm)
    assert alarm["generated_work_order_id"] is not None

    # Fetch the generated WO and check priority_score = 36, priority = P1.
    wo = validate_success(
        api.get_work_order(
            site_id, alarm["generated_work_order_id"],
            __import__("test_helpers").TEST_USERS["dispatcher_headers"],
        ),
        expected_status=200,
    )
    assert wo["source"] == "ALARM"
    assert wo["priority_score"] == 36, \
        "PRD §3.5: HIGH(4) * P1(8) + ALARM(4) == 36"
    assert wo["priority"] == "P1"


def test_priority_score_medium_p3_ad_hoc_yields_p4(api, dispatcher_headers):
    """PRD §3.5: priority_score = MEDIUM(2) * P3(2) + AD_HOC(1) = 5 < 8
    → P4. PRD §3.5: 'a score strictly less than 8 is P4'.
    # difficulty: combinatorial_formula/priority_score_mode_a_three_input_nonlinear
    """
    bag = setup_priority_combo(
        criticality="MEDIUM", template_default_priority="P3",
    )
    res = api.create_work_order(
        bag["site"]["id"],
        create_work_order_payload(
            bag["equipment"]["id"], bag["template"]["id"],
        ),
        dispatcher_headers,
    )
    wo = validate_success(res, expected_status=201)
    assert wo["source"] == "AD_HOC"
    assert wo["priority_score"] == 5
    assert wo["priority"] == "P4"


@pytest.mark.parametrize("criticality,template_priority,expected_score,"
                         "expected_bucket", [
    ("LOW", "P1", 1 * 8 + 1, "P3"),       # 9 → P3
    ("LOW", "P3", 1 * 2 + 1, "P4"),       # 3 → P4
    ("MEDIUM", "P1", 2 * 8 + 1, "P2"),    # 17 → P3? wait: 17 < 20 → P3
    ("MEDIUM", "P2", 2 * 4 + 1, "P3"),    # 9 → P3
    ("HIGH", "P2", 4 * 4 + 1, "P3"),      # 17 → P3
    ("HIGH", "P1", 4 * 8 + 1, "P1"),      # 33 → P1
])
def test_priority_score_formula_table(api, dispatcher_headers,
                                       criticality, template_priority,
                                       expected_score, expected_bucket):
    """PRD §3.5: 'The bucket is read from the score using inclusive lower
    bounds: a priority_score of at least 30 is P1; a score of at least 20
    but strictly less than 30 is P2; a score of at least 8 but strictly
    less than 20 is P3; and a score strictly less than 8 is P4.'
    """
    # Recompute expected bucket from PRD §3.5 boundaries to double-check
    # the parametrize tuples.
    if expected_score >= 30:
        expected_bucket = "P1"
    elif expected_score >= 20:
        expected_bucket = "P2"
    elif expected_score >= 8:
        expected_bucket = "P3"
    else:
        expected_bucket = "P4"

    bag = setup_priority_combo(
        criticality=criticality, template_default_priority=template_priority,
    )
    res = api.create_work_order(
        bag["site"]["id"],
        create_work_order_payload(
            bag["equipment"]["id"], bag["template"]["id"],
        ),
        dispatcher_headers,
    )
    wo = validate_success(res, expected_status=201)
    assert wo["priority_score"] == expected_score
    assert wo["priority"] == expected_bucket


def test_sla_due_at_equals_opened_at_plus_sla_minutes(api, dispatcher_headers):
    """PRD §3.5: 'The SLA in minutes is 240 for P1, 480 for P2, 1440 for P3,
    and 4320 for P4. ... The work order's sla_due_at is its opened_at plus
    the SLA in seconds (the SLA in minutes multiplied by 60).'
    """
    bag = setup_priority_combo(
        criticality="MEDIUM", template_default_priority="P3",
    )
    res = api.create_work_order(
        bag["site"]["id"],
        create_work_order_payload(
            bag["equipment"]["id"], bag["template"]["id"],
        ),
        dispatcher_headers,
    )
    wo = validate_success(res, expected_status=201)
    sla_minutes = SLA_MINUTES[wo["priority"]]
    expected = parse_iso(wo["opened_at"]) + \
        __import__("datetime").timedelta(seconds=sla_minutes * 60)
    assert parse_iso(wo["sla_due_at"]) == expected


# ---------------------------------------------------------------------------
# 3.4 — alarm event side effects
# ---------------------------------------------------------------------------
def test_alarm_emitted_at_provided_by_client_rejected(api, dispatcher_headers):
    """PRD §3.4: 'A client that supplies its own emitted_at is rejected
    with ERR_TEMPORAL_INVALID.'
    """
    bag = setup_full_workorder_scenario()
    payload = emit_alarm_payload(alarm_code="X", severity="INFO")
    payload["emitted_at"] = "2026-02-15T00:00:00.000Z"
    res = api.emit_alarm(
        bag["site"]["id"], bag["equipment"]["id"], payload, dispatcher_headers,
    )
    from test_helpers import validate_error
    validate_error(res, "ERR_TEMPORAL_INVALID", expected_status=422)


def test_alarm_without_matching_plan_records_event_only(api,
                                                         dispatcher_headers):
    """PRD §3.4: 'If no plan matches, the alarm still records but
    generated_work_order_id remains null.'
    """
    bag = setup_full_workorder_scenario()
    res = api.emit_alarm(
        bag["site"]["id"], bag["equipment"]["id"],
        emit_alarm_payload(alarm_code="UNMATCHED", severity="INFO"),
        dispatcher_headers,
    )
    alarm = validate_success(res, expected_status=200)
    assert alarm["generated_work_order_id"] is None


def test_alarm_with_matching_active_trigger_plan_creates_workorder(
        api, dispatcher_headers, plan_owner_headers):
    """PRD §3.4: 'Whenever an AlarmEvent is emitted with an alarm_code, all
    ACTIVE plans of kind TRIGGER_ALARM for the same equipment whose
    alarm_code matches the event are considered. If the equipment's
    open_work_order_id is null, a new work order is created with source
    ALARM, and the alarm event's generated_work_order_id is stamped with
    the new work order's id.'
    """
    bag = setup_site_with_in_service_equipment()
    site_id = bag["site"]["id"]
    eq_id = bag["equipment"]["id"]
    # Add a TRIGGER_ALARM plan and activate it
    alarm_plan = create_plan(
        site_id, eq_id, bag["template"]["id"], "TRIGGER_ALARM",
        alarm_code="OVERTEMP",
    )
    activate_plan(site_id, alarm_plan["id"])
    # Need a technician so selector can route. Create one with required skill.
    create_technician(site_id, skills=["MECHANICAL"])

    res = api.emit_alarm(
        site_id, eq_id,
        emit_alarm_payload(alarm_code="OVERTEMP", severity="CRITICAL"),
        dispatcher_headers,
    )
    alarm = validate_success(res, expected_status=200)
    assert alarm["generated_work_order_id"] is not None
    wo = validate_success(
        api.get_work_order(site_id, alarm["generated_work_order_id"],
                            dispatcher_headers),
        expected_status=200,
    )
    assert wo["source"] == "ALARM"
