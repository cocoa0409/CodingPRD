"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) so setup failures produce a clear
"setup failed" error rather than a confusing assertion failure.

Each fixture maps to one or more PRD-stated workflows (request → approve →
schedule → confirm → start → complete, sterilization cycle, settlement
lifecycle, emergency-insert preemption, etc.). The difficulty-design recipes
each have a dedicated `setup_*` helper at the bottom of this file so tests
can reproduce the exact pre-conditions the recipe demands.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_operating_room_payload,
    create_staff_payload,
    create_instrument_set_payload,
    create_surgical_case_payload,
    create_schedule_payload,
    create_emergency_insert_payload,
    create_pre_authorize_payload,
    create_itemize_payload,
    create_clock_advance_payload,
    create_complete_payload,
    make_staff_assignment,
)
from .test_users import TEST_USERS


SCHED = TEST_USERS["scheduler_headers"]
DEPT = TEST_USERS["department_head_headers"]
COORD = TEST_USERS["surgical_coordinator_headers"]
BILLING = TEST_USERS["billing_admin_headers"]
ANY_HEADERS = TEST_USERS["any_headers"]


# ────────────────────────────────────────────────────────────────────────────
# Tier 0: Atomic resource creators
# ────────────────────────────────────────────────────────────────────────────

def create_operating_room(**overrides) -> dict:
    payload = create_operating_room_payload(**overrides)
    return get_success_data(api_client.create_operating_room(payload, SCHED))


def create_staff(**overrides) -> dict:
    payload = create_staff_payload(**overrides)
    return get_success_data(api_client.create_staff(payload, SCHED))


def create_instrument_set(sterilize: bool = False, **overrides) -> dict:
    """Create an instrument set; if sterilize=True, also start+complete sterilization
    so the set ends in CLEAN_STERILIZED at current_minute."""
    payload = create_instrument_set_payload(**overrides)
    inst = get_success_data(api_client.create_instrument_set(payload, SCHED))
    if sterilize:
        get_success_data(api_client.start_sterilization(inst["id"], SCHED))
        inst = get_success_data(api_client.complete_sterilization(inst["id"], SCHED))
    return inst


def create_surgical_case(**overrides) -> dict:
    payload = create_surgical_case_payload(**overrides)
    return get_success_data(api_client.create_surgical_case(payload, COORD))


def create_anesthesiologist(qualifications=None, hourly_rate=200.00, shift_start=0, shift_end=1440, **overrides) -> dict:
    return create_staff(
        staff_name="Dr. A",
        staff_role="ANESTHESIOLOGIST",
        qualifications=qualifications if qualifications is not None else ["GENERAL"],
        hourly_rate=hourly_rate,
        shift_start_minute=shift_start,
        shift_end_minute=shift_end,
        **overrides,
    )


def create_scrub_nurse(qualifications=None, hourly_rate=80.00, shift_start=0, shift_end=1440, **overrides) -> dict:
    return create_staff(
        staff_name="Nurse S",
        staff_role="SCRUB_NURSE",
        qualifications=qualifications if qualifications is not None else ["GENERAL"],
        hourly_rate=hourly_rate,
        shift_start_minute=shift_start,
        shift_end_minute=shift_end,
        **overrides,
    )


def create_circulating_nurse(qualifications=None, hourly_rate=70.00, shift_start=0, shift_end=1440, **overrides) -> dict:
    return create_staff(
        staff_name="Nurse C",
        staff_role="CIRCULATING_NURSE",
        qualifications=qualifications if qualifications is not None else ["GENERAL"],
        hourly_rate=hourly_rate,
        shift_start_minute=shift_start,
        shift_end_minute=shift_end,
        **overrides,
    )


# ────────────────────────────────────────────────────────────────────────────
# Tier 1: Lifecycle progression helpers
# ────────────────────────────────────────────────────────────────────────────

def approve_case(case_id: str) -> dict:
    return get_success_data(api_client.approve_case(case_id, DEPT))


def reject_case(case_id: str, rejected_reason: str = None) -> dict:
    body = {}
    if rejected_reason is not None:
        body["rejected_reason"] = rejected_reason
    return get_success_data(api_client.reject_case(case_id, DEPT, payload=body))


def schedule_case(
    case_id: str,
    *,
    room_id: str,
    planned_start_minute: int,
    planned_end_minute: int,
    staff_assignments: list,
    instrument_set_id: str,
) -> dict:
    payload = create_schedule_payload(
        scheduled_room_id=room_id,
        planned_start_minute=planned_start_minute,
        planned_end_minute=planned_end_minute,
        staff_assignments=staff_assignments,
        instrument_set_id=instrument_set_id,
    )
    return get_success_data(api_client.schedule_case(case_id, payload, SCHED))


def list_assignments_for_case(case_id: str) -> list:
    resp = api_client.list_assignments(case_id, SCHED)
    body = resp.json()
    return body["data"]


def confirm_all_assignments(case_id: str) -> list:
    """Confirm every assignment under the given case; returns the confirmed list."""
    assignments = list_assignments_for_case(case_id)
    confirmed = []
    for a in assignments:
        confirmed.append(
            get_success_data(api_client.confirm_assignment(case_id, a["id"], SCHED))
        )
    return confirmed


def start_case(case_id: str) -> dict:
    return get_success_data(api_client.start_case(case_id, SCHED))


def complete_case(case_id: str, implant_cost_actual=None) -> dict:
    payload = create_complete_payload()
    if implant_cost_actual is not None:
        payload["implant_cost_actual"] = implant_cost_actual
    return get_success_data(api_client.complete_case(case_id, SCHED, payload=payload))


def cancel_case(case_id: str) -> dict:
    return get_success_data(api_client.cancel_case(case_id, SCHED))


def advance_clock(delta_minutes: int) -> dict:
    return get_success_data(
        api_client.advance_clock(create_clock_advance_payload(delta_minutes), SCHED)
    )


def get_settlement_for_case(case_id: str) -> dict:
    """Locate the (single) Settlement whose case_id == case_id by paginating list."""
    offset = 0
    page = 100
    while True:
        resp = api_client.list_settlements(SCHED, params={"limit": page, "offset": offset})
        body = resp.json()
        for s in body["data"]:
            if s.get("case_id") == case_id:
                return s
        meta = body.get("meta") or {}
        if not meta.get("has_more"):
            return None
        offset += page


def get_audit_entries(entity_type=None, entity_id=None, action=None) -> list:
    params = {}
    if entity_type:
        params["entity_type"] = entity_type
    if entity_id:
        params["entity_id"] = entity_id
    if action:
        params["action"] = action
    resp = api_client.list_audit_entries(SCHED, params=params or None)
    return resp.json()["data"]


# ────────────────────────────────────────────────────────────────────────────
# Tier 2: Common composite scenarios
# ────────────────────────────────────────────────────────────────────────────

def setup_basic_general_environment(*, room_overrides=None, sterilize_instrument=True):
    """Create one GENERAL_OR room, one anesthesiologist (GENERAL), one scrub nurse
    (GENERAL), and one GENERAL instrument set (sterilized at current_minute=0 by
    default). Returns a dict with all four entities."""
    room = create_operating_room(**(room_overrides or {}))
    anesth = create_anesthesiologist()
    scrub = create_scrub_nurse()
    instrument = create_instrument_set(specialty="GENERAL", sterilize=sterilize_instrument)
    return {"room": room, "anesth": anesth, "scrub": scrub, "instrument": instrument}


def setup_approved_general_case(*, case_overrides=None) -> dict:
    """Create + approve a GENERAL case. Returns the APPROVED case."""
    case = create_surgical_case(specialty_required="GENERAL", **(case_overrides or {}))
    return approve_case(case["id"])


def setup_scheduled_general_case(
    *,
    case_overrides=None,
    planned_start_minute=0,
    planned_end_minute=60,
    sterilize_instrument=True,
):
    """Build a GENERAL case in SCHEDULED state with anesth+scrub assignments and
    a sterilized GENERAL instrument set. Returns dict with all keys."""
    env = setup_basic_general_environment(sterilize_instrument=sterilize_instrument)
    case = create_surgical_case(specialty_required="GENERAL", **(case_overrides or {}))
    case = approve_case(case["id"])
    case = schedule_case(
        case["id"],
        room_id=env["room"]["id"],
        planned_start_minute=planned_start_minute,
        planned_end_minute=planned_end_minute,
        staff_assignments=[
            make_staff_assignment(env["anesth"]["id"], "LEAD_ANESTHESIOLOGIST"),
            make_staff_assignment(env["scrub"]["id"], "SCRUB_NURSE"),
        ],
        instrument_set_id=env["instrument"]["id"],
    )
    return {**env, "case": case}


def setup_in_progress_general_case(**kwargs):
    bundle = setup_scheduled_general_case(**kwargs)
    confirm_all_assignments(bundle["case"]["id"])
    bundle["case"] = start_case(bundle["case"]["id"])
    return bundle


def setup_completed_general_case(*, advance_after_start: int = 0, **kwargs):
    bundle = setup_in_progress_general_case(**kwargs)
    if advance_after_start > 0:
        advance_clock(advance_after_start)
    bundle["case"] = complete_case(bundle["case"]["id"])
    return bundle


# ────────────────────────────────────────────────────────────────────────────
# Tier 3: Difficulty-Design recipes (one helper per recipe instance)
# ────────────────────────────────────────────────────────────────────────────

# --- Rule 1.1: settlement estimate vs final ---------------------------------
def setup_dual_variant_settlement(
    *,
    room_hourly_rate=500.00,
    anesth_hourly_rate=200.00,
    scrub_hourly_rate=80.00,
    planned_duration=60,
    actual_duration=90,
    implant_cost_estimate=0.00,
):
    """Difficulty Rule 1, instance settlement_estimate_vs_final_on_settlement.
    GENERAL_OR room, one anesthesiologist + one scrub nurse, planned interval
    0..planned_duration, actual interval 0..actual_duration. Returns the
    completed bundle and the Settlement post-completion."""
    room = create_operating_room(
        room_type="GENERAL_OR",
        hourly_rate=room_hourly_rate,
        turnover_buffer_minutes=30,
        specialty_required="GENERAL",
    )
    anesth = create_anesthesiologist(hourly_rate=anesth_hourly_rate)
    scrub = create_scrub_nurse(hourly_rate=scrub_hourly_rate)
    instrument = create_instrument_set(specialty="GENERAL", sterilize=True)
    case = create_surgical_case(
        specialty_required="GENERAL",
        pre_op_assessment_attached=True,
        informed_consent_verified=True,
        implant_cost_estimate=implant_cost_estimate,
    )
    case = approve_case(case["id"])
    case = schedule_case(
        case["id"],
        room_id=room["id"],
        planned_start_minute=0,
        planned_end_minute=planned_duration,
        staff_assignments=[
            make_staff_assignment(anesth["id"], "LEAD_ANESTHESIOLOGIST"),
            make_staff_assignment(scrub["id"], "SCRUB_NURSE"),
        ],
        instrument_set_id=instrument["id"],
    )
    confirm_all_assignments(case["id"])
    case = start_case(case["id"])
    if actual_duration > 0:
        advance_clock(actual_duration)
    case = complete_case(case["id"])
    settlement = get_settlement_for_case(case["id"])
    return {
        "room": room,
        "anesth": anesth,
        "scrub": scrub,
        "instrument": instrument,
        "case": case,
        "settlement": settlement,
    }


# --- Rule 1.2: planned vs actual workload on a single staff member ---------
def setup_dual_variant_workload():
    """Difficulty Rule 1, instance staff_workload_planned_vs_actual_on_staff.
    Single anesthesiologist with two cases:
      C1: planned 0..60 → completed at actual 0..90
      C2: planned 100..200 → only RESERVED (no confirm/start)
    Returns dict with the staff member id; tests should GET /staff/{id}
    AFTER both cases are in their target states."""
    room = create_operating_room(
        room_type="GENERAL_OR",
        hourly_rate=500.00,
        specialty_required="GENERAL",
    )
    anesth = create_anesthesiologist(hourly_rate=200.00, shift_start=0, shift_end=1440)
    inst1 = create_instrument_set(specialty="GENERAL", sterilize=True)
    inst2 = create_instrument_set(specialty="GENERAL", sterilize=True)

    case1 = create_surgical_case(specialty_required="GENERAL")
    case1 = approve_case(case1["id"])
    case1 = schedule_case(
        case1["id"],
        room_id=room["id"],
        planned_start_minute=0,
        planned_end_minute=60,
        staff_assignments=[make_staff_assignment(anesth["id"], "LEAD_ANESTHESIOLOGIST")],
        instrument_set_id=inst1["id"],
    )
    confirm_all_assignments(case1["id"])
    case1 = start_case(case1["id"])
    advance_clock(90)  # current_minute -> 90
    case1 = complete_case(case1["id"])

    case2 = create_surgical_case(specialty_required="GENERAL")
    case2 = approve_case(case2["id"])
    case2 = schedule_case(
        case2["id"],
        room_id=room["id"],
        planned_start_minute=100,
        planned_end_minute=200,
        staff_assignments=[make_staff_assignment(anesth["id"], "LEAD_ANESTHESIOLOGIST")],
        instrument_set_id=inst2["id"],
    )
    return {"anesth": anesth, "case1": case1, "case2": case2}


# --- Rule 2.1: cardiac combinatorial cost -----------------------------------
def setup_combinatorial_cardiac_scheduled():
    """Difficulty Rule 2, instance provisional_cost_tiered_rate_selection_mode_a.
    Cardiac room@1000, anesth@200, scrub@80, circ@70, implant=5000, planned 0..180.
    Schedules the case and returns the post-schedule Settlement."""
    room = create_operating_room(
        room_type="CARDIAC_OR",
        hourly_rate=1000.00,
        turnover_buffer_minutes=30,
        specialty_required="CARDIAC",
    )
    anesth = create_anesthesiologist(qualifications=["CARDIAC"], hourly_rate=200.00)
    scrub = create_scrub_nurse(qualifications=["CARDIAC"], hourly_rate=80.00)
    circ = create_circulating_nurse(qualifications=["CARDIAC"], hourly_rate=70.00)
    instrument = create_instrument_set(specialty="CARDIAC", sterilize=True)
    case = create_surgical_case(
        specialty_required="CARDIAC",
        implant_cost_estimate=5000.00,
    )
    case = approve_case(case["id"])
    case = schedule_case(
        case["id"],
        room_id=room["id"],
        planned_start_minute=0,
        planned_end_minute=180,
        staff_assignments=[
            make_staff_assignment(anesth["id"], "LEAD_ANESTHESIOLOGIST"),
            make_staff_assignment(scrub["id"], "SCRUB_NURSE"),
            make_staff_assignment(circ["id"], "CIRCULATING_NURSE"),
        ],
        instrument_set_id=instrument["id"],
    )
    settlement = get_settlement_for_case(case["id"])
    return {
        "room": room,
        "anesth": anesth,
        "scrub": scrub,
        "circ": circ,
        "instrument": instrument,
        "case": case,
        "settlement": settlement,
    }


# --- Rule 2.2: insurance split with rounding remainder ---------------------
def setup_insurance_split_rounding():
    """Difficulty Rule 2, instance insurance_split_rounding_order_mode_b.
    Build a completed case whose final_total_amount lands at exactly 500.05.
    Room@200, single anesthesiologist@150.05, no implants, planned == actual == 60.
      room_component = round(1*200) = 200.00
      staff_component = round(1*150.05) = 150.05
      instrument = 150.00; implant = 0.00
      final_total = 500.05
    Returns the completed bundle."""
    room = create_operating_room(
        room_type="GENERAL_OR",
        hourly_rate=200.00,
        turnover_buffer_minutes=30,
        specialty_required="GENERAL",
    )
    anesth = create_anesthesiologist(hourly_rate=150.05)
    instrument = create_instrument_set(specialty="GENERAL", sterilize=True)
    case = create_surgical_case(
        specialty_required="GENERAL",
        implant_cost_estimate=0.00,
    )
    case = approve_case(case["id"])
    case = schedule_case(
        case["id"],
        room_id=room["id"],
        planned_start_minute=0,
        planned_end_minute=60,
        staff_assignments=[make_staff_assignment(anesth["id"], "LEAD_ANESTHESIOLOGIST")],
        instrument_set_id=instrument["id"],
    )
    confirm_all_assignments(case["id"])
    case = start_case(case["id"])
    advance_clock(60)  # actual_end = current_minute at complete; need 60-min actual duration
    case = complete_case(case["id"], implant_cost_actual=0.00)
    settlement = get_settlement_for_case(case["id"])
    return {
        "room": room,
        "anesth": anesth,
        "instrument": instrument,
        "case": case,
        "settlement": settlement,
    }


# --- Rule 3.1: SurgicalCase branching at REQUESTED -------------------------
def setup_branching_state_machine():
    """Difficulty Rule 3, instance surgical_case_branching_at_requested.
    Two cases: one approve, one reject."""
    case1 = create_surgical_case(specialty_required="GENERAL")
    case2 = create_surgical_case(specialty_required="GENERAL")
    case1 = approve_case(case1["id"])
    case2 = reject_case(case2["id"], rejected_reason="clinical contraindication")
    return {"case1_approved": case1, "case2_rejected": case2}


# --- Rule 3.2: InstrumentSet cyclic state machine --------------------------
def setup_cyclic_instrument_state_machine():
    """Difficulty Rule 3, instance instrument_set_cyclic_state_machine.
    Drive InstrumentSet through SOILED → IN_STERILIZATION → CLEAN_STERILIZED →
    CHECKED_OUT → SOILED → IN_STERILIZATION (loop).
    Captures the InstrumentSet snapshot at each waypoint so the test can verify
    the entire cycle."""
    room = create_operating_room(
        room_type="GENERAL_OR",
        hourly_rate=500.00,
        specialty_required="GENERAL",
    )
    anesth = create_anesthesiologist()
    instrument = create_instrument_set(specialty="GENERAL", sterilize=False)
    initial = instrument
    # SOILED -> IN_STERILIZATION
    get_success_data(api_client.start_sterilization(instrument["id"], SCHED))
    # IN_STERILIZATION -> CLEAN_STERILIZED
    after_sterilize = get_success_data(
        api_client.complete_sterilization(instrument["id"], SCHED)
    )

    case = create_surgical_case(specialty_required="GENERAL")
    case = approve_case(case["id"])
    case = schedule_case(
        case["id"],
        room_id=room["id"],
        planned_start_minute=0,
        planned_end_minute=60,
        staff_assignments=[make_staff_assignment(anesth["id"], "LEAD_ANESTHESIOLOGIST")],
        instrument_set_id=instrument["id"],
    )
    after_schedule = get_success_data(api_client.get_instrument_set(instrument["id"], SCHED))

    confirm_all_assignments(case["id"])
    case = start_case(case["id"])
    case = complete_case(case["id"])
    after_complete = get_success_data(api_client.get_instrument_set(instrument["id"], SCHED))

    # Re-start sterilization (loop closes back to IN_STERILIZATION)
    after_restart = get_success_data(
        api_client.start_sterilization(instrument["id"], SCHED)
    )
    return {
        "instrument_initial": initial,
        "instrument_after_sterilize": after_sterilize,
        "instrument_after_schedule": after_schedule,
        "instrument_after_complete": after_complete,
        "instrument_after_restart": after_restart,
        "case": case,
    }


# --- Rule 4.1: emergency-insert cascade depth 3 ----------------------------
def setup_emergency_preempt_cardiac_cascade():
    """Difficulty Rule 4, instance emergency_preempt_cascade_depth_three.

    Existing CARDIAC SurgicalCase A scheduled in CARDIAC_OR with
    [A1 LEAD_ANESTHESIOLOGIST, S1 SCRUB_NURSE, CN1 CIRCULATING_NURSE], I1,
    planned 0..120; then emergency insertion of a new EMERGENCY case in the
    same room with disjoint staff [A2,S2,CN2] and I2, planned 0..60.

    Expected: A is preempted; refund_amount on A's settlement = 2850.00:
      billable_hours=ceil(120/60)=2;
      room=2000.00, anesth=400.00, scrub=160.00, circ=140.00,
      instrument=150.00, implant=0.00 → 2850.00.
    """
    room = create_operating_room(
        room_type="CARDIAC_OR",
        hourly_rate=1000.00,
        turnover_buffer_minutes=30,
        specialty_required="CARDIAC",
    )
    a1 = create_anesthesiologist(qualifications=["CARDIAC"], hourly_rate=200.00)
    s1 = create_scrub_nurse(qualifications=["CARDIAC"], hourly_rate=80.00)
    cn1 = create_circulating_nurse(qualifications=["CARDIAC"], hourly_rate=70.00)
    a2 = create_anesthesiologist(qualifications=["CARDIAC"], hourly_rate=200.00)
    s2 = create_scrub_nurse(qualifications=["CARDIAC"], hourly_rate=80.00)
    cn2 = create_circulating_nurse(qualifications=["CARDIAC"], hourly_rate=70.00)
    inst1 = create_instrument_set(specialty="CARDIAC", sterilize=True)
    inst2 = create_instrument_set(specialty="CARDIAC", sterilize=True)

    case_a = create_surgical_case(
        specialty_required="CARDIAC",
        priority="ROUTINE",
        implant_cost_estimate=0.00,
    )
    case_a = approve_case(case_a["id"])
    case_a = schedule_case(
        case_a["id"],
        room_id=room["id"],
        planned_start_minute=0,
        planned_end_minute=120,
        staff_assignments=[
            make_staff_assignment(a1["id"], "LEAD_ANESTHESIOLOGIST"),
            make_staff_assignment(s1["id"], "SCRUB_NURSE"),
            make_staff_assignment(cn1["id"], "CIRCULATING_NURSE"),
        ],
        instrument_set_id=inst1["id"],
    )
    pre_emergency_settlement = get_settlement_for_case(case_a["id"])

    payload = create_emergency_insert_payload(
        scheduled_room_id=room["id"],
        planned_start_minute=0,
        planned_end_minute=60,
        staff_assignments=[
            make_staff_assignment(a2["id"], "LEAD_ANESTHESIOLOGIST"),
            make_staff_assignment(s2["id"], "SCRUB_NURSE"),
            make_staff_assignment(cn2["id"], "CIRCULATING_NURSE"),
        ],
        instrument_set_id=inst2["id"],
        patient_id="P-EM-1",
        surgery_type="emergency CABG",
        specialty_required="CARDIAC",
        implant_cost_estimate=0.00,
    )
    emergency_case = get_success_data(api_client.emergency_insert(payload, SCHED))
    return {
        "preempted_case": case_a,
        "preempted_settlement_pre": pre_emergency_settlement,
        "emergency_case": emergency_case,
        "instrument_preempted": inst1,
        "instrument_emergency": inst2,
    }


# --- Rule 4.2: cancel cascade depth 2 --------------------------------------
def setup_cancel_cascade_general():
    """Difficulty Rule 4, instance cancel_cascade_depth_two.
    GENERAL case scheduled with R/A/B/I, planned 0..60. Caller is responsible
    for triggering cancel and verifying the cascade. Expected refund=930.00."""
    room = create_operating_room(
        room_type="GENERAL_OR",
        hourly_rate=500.00,
        turnover_buffer_minutes=30,
        specialty_required="GENERAL",
    )
    anesth = create_anesthesiologist(hourly_rate=200.00)
    scrub = create_scrub_nurse(hourly_rate=80.00)
    instrument = create_instrument_set(specialty="GENERAL", sterilize=True)
    case = create_surgical_case(
        specialty_required="GENERAL",
        implant_cost_estimate=0.00,
    )
    case = approve_case(case["id"])
    case = schedule_case(
        case["id"],
        room_id=room["id"],
        planned_start_minute=0,
        planned_end_minute=60,
        staff_assignments=[
            make_staff_assignment(anesth["id"], "LEAD_ANESTHESIOLOGIST"),
            make_staff_assignment(scrub["id"], "SCRUB_NURSE"),
        ],
        instrument_set_id=instrument["id"],
    )
    return {
        "room": room,
        "anesth": anesth,
        "scrub": scrub,
        "instrument": instrument,
        "case": case,
    }


# --- Rule 5.1: priority conflict — state vs business_safety ----------------
def setup_state_vs_safety_qual_conflict():
    """Difficulty Rule 5, instance state_vs_business_safety_qualification.
    Case is still REQUESTED (not approved) AND staff has wrong qualifications.
    /schedule should fail with ERR_CASE_NOT_APPROVED (state priority wins)."""
    room = create_operating_room(
        room_type="GENERAL_OR",
        hourly_rate=500.00,
        turnover_buffer_minutes=30,
        specialty_required="GENERAL",
    )
    mismatch_staff = create_anesthesiologist(qualifications=["CARDIAC"], hourly_rate=200.00)
    instrument = create_instrument_set(specialty="GENERAL", sterilize=True)
    case = create_surgical_case(
        specialty_required="GENERAL",
        pre_op_assessment_attached=True,
        informed_consent_verified=True,
    )
    # do NOT approve — case stays in REQUESTED
    return {
        "room": room,
        "staff": mismatch_staff,
        "instrument": instrument,
        "case": case,
    }


# --- Rule 5.2: priority conflict — business_safety vs business_temporal ----
def setup_safety_vs_temporal_conflict():
    """Difficulty Rule 5, instance business_safety_qualification_vs_business_temporal_room.

    Step 1: schedule a CARDIAC case C0 with valid CARDIAC staff to occupy
    CARDIAC_OR R during [0, 150) (planned 0..120 + 30 buffer).

    Step 2: approve C1 (CARDIAC) but try to schedule it with mismatched
    staff (qualifications=[GENERAL]) in the same room over [0, 60) — both
    a qualification mismatch (priority 9) and a room time conflict
    (priority 14) apply. Expected error_id is ERR_QUALIFICATION_MISMATCH."""
    room = create_operating_room(
        room_type="CARDIAC_OR",
        hourly_rate=1000.00,
        turnover_buffer_minutes=30,
        specialty_required="CARDIAC",
    )
    good_staff = create_anesthesiologist(qualifications=["CARDIAC"], hourly_rate=200.00)
    mismatch_staff = create_anesthesiologist(qualifications=["GENERAL"], hourly_rate=200.00)
    inst1 = create_instrument_set(specialty="CARDIAC", sterilize=True)
    inst2 = create_instrument_set(specialty="CARDIAC", sterilize=True)

    c0 = create_surgical_case(specialty_required="CARDIAC")
    c0 = approve_case(c0["id"])
    c0 = schedule_case(
        c0["id"],
        room_id=room["id"],
        planned_start_minute=0,
        planned_end_minute=120,
        staff_assignments=[make_staff_assignment(good_staff["id"], "LEAD_ANESTHESIOLOGIST")],
        instrument_set_id=inst1["id"],
    )

    c1 = create_surgical_case(specialty_required="CARDIAC")
    c1 = approve_case(c1["id"])
    return {
        "room": room,
        "mismatch_staff": mismatch_staff,
        "instrument_for_c1": inst2,
        "case_c1_approved": c1,
    }


# --- Rule 6.1: 72-hour sterilization expiration boundary ------------------
def setup_sterilization_at_boundary():
    """Difficulty Rule 6, instance sterilization_expiration_72h_boundary_on_get_instrument.
    Returns a sterilized GENERAL set whose last_sterilized_at_minute=0 and the
    test driver should advance the clock + GET to test boundaries."""
    instrument = create_instrument_set(specialty="GENERAL", sterilize=True)
    return {"instrument": instrument}


# --- Rule 6.2: 720-minute working hours boundary --------------------------
def setup_working_hours_boundary_environment():
    """Difficulty Rule 6, instance staff_working_hours_720_boundary_on_schedule.
    Three rooms, one anesthesiologist, three sterilized GENERAL instrument sets,
    three approved GENERAL cases. The first 600-minute schedule is performed
    inside the helper; tests then drive the last two schedules to test the
    720 / 721 boundary."""
    r1 = create_operating_room(specialty_required="GENERAL", hourly_rate=500.00, turnover_buffer_minutes=30)
    r2 = create_operating_room(specialty_required="GENERAL", hourly_rate=500.00, turnover_buffer_minutes=30)
    r3 = create_operating_room(specialty_required="GENERAL", hourly_rate=500.00, turnover_buffer_minutes=30)
    anesth = create_anesthesiologist(hourly_rate=200.00)
    inst1 = create_instrument_set(specialty="GENERAL", sterilize=True)
    inst2 = create_instrument_set(specialty="GENERAL", sterilize=True)
    inst3 = create_instrument_set(specialty="GENERAL", sterilize=True)

    c1 = approve_case(create_surgical_case(specialty_required="GENERAL")["id"])
    c2 = approve_case(create_surgical_case(specialty_required="GENERAL")["id"])
    c3 = approve_case(create_surgical_case(specialty_required="GENERAL")["id"])

    # Schedule c1 0..600 (A's window-total = 600 ≤ 720)
    c1 = schedule_case(
        c1["id"],
        room_id=r1["id"],
        planned_start_minute=0,
        planned_end_minute=600,
        staff_assignments=[make_staff_assignment(anesth["id"], "LEAD_ANESTHESIOLOGIST")],
        instrument_set_id=inst1["id"],
    )
    return {
        "rooms": (r1, r2, r3),
        "anesth": anesth,
        "instruments": (inst1, inst2, inst3),
        "case_c1_scheduled": c1,
        "case_c2_approved": c2,
        "case_c3_approved": c3,
    }


# --- Rule 7.1: schedule depends on instrument sterilization ---------------
def setup_unsterilized_instrument_for_schedule():
    """Difficulty Rule 7, instance case_schedule_depends_on_instrument_sterilization.
    Approved GENERAL case + SOILED (never sterilized) GENERAL instrument set."""
    room = create_operating_room(specialty_required="GENERAL", hourly_rate=500.00)
    anesth = create_anesthesiologist(hourly_rate=200.00)
    instrument = create_instrument_set(specialty="GENERAL", sterilize=False)  # SOILED
    case = approve_case(create_surgical_case(specialty_required="GENERAL")["id"])
    return {"room": room, "anesth": anesth, "instrument": instrument, "case": case}


# --- Rule 7.2: start depends on assignment confirmation -------------------
def setup_scheduled_case_unconfirmed_for_start():
    """Difficulty Rule 7, instance case_start_depends_on_assignment_confirmation.
    Case is in SCHEDULED with assignment still in RESERVED (no /confirm called)."""
    bundle = setup_scheduled_general_case()
    return bundle


# --- Rule 8.1: room turnover-buffer closed-gap boundary ------------------
def setup_room_buffer_boundary():
    """Difficulty Rule 8, instance room_turnover_buffer_closed_gap_semantics.
    Schedule C1 in R [0..120] (with buffer 30 → R occupied [0,150)). Provide
    two additional approved cases (C2_pass, C2_fail) and additional staff /
    sterilized instruments so caller can drive the boundary tests."""
    room = create_operating_room(
        room_type="GENERAL_OR",
        hourly_rate=500.00,
        turnover_buffer_minutes=30,
        specialty_required="GENERAL",
    )
    a1 = create_anesthesiologist(hourly_rate=200.00)
    a2 = create_anesthesiologist(hourly_rate=200.00)
    inst1 = create_instrument_set(specialty="GENERAL", sterilize=True)
    inst2 = create_instrument_set(specialty="GENERAL", sterilize=True)
    inst3 = create_instrument_set(specialty="GENERAL", sterilize=True)

    c1 = approve_case(create_surgical_case(specialty_required="GENERAL")["id"])
    c1 = schedule_case(
        c1["id"],
        room_id=room["id"],
        planned_start_minute=0,
        planned_end_minute=120,
        staff_assignments=[make_staff_assignment(a1["id"], "LEAD_ANESTHESIOLOGIST")],
        instrument_set_id=inst1["id"],
    )
    c2_pass = approve_case(create_surgical_case(specialty_required="GENERAL")["id"])
    c2_fail = approve_case(create_surgical_case(specialty_required="GENERAL")["id"])
    return {
        "room": room,
        "anesth_for_c2_pass": a2,
        "anesth_for_c2_fail": a2,
        "instrument_for_c2_pass": inst2,
        "instrument_for_c2_fail": inst3,
        "case_c1_scheduled": c1,
        "case_c2_pass_approved": c2_pass,
        "case_c2_fail_approved": c2_fail,
    }


# --- Rule 8.2: staff half-open overlap (no buffer) ------------------------
def setup_staff_overlap_boundary():
    """Difficulty Rule 8, instance staff_open_half_overlap_no_buffer.
    C1 booked planned [0..60) with staff A; provide two more rooms / instruments
    plus C2_adj_pass and C2_overlap_fail approved cases."""
    r1 = create_operating_room(specialty_required="GENERAL", hourly_rate=500.00, turnover_buffer_minutes=30)
    r2 = create_operating_room(specialty_required="GENERAL", hourly_rate=500.00, turnover_buffer_minutes=30)
    r3 = create_operating_room(specialty_required="GENERAL", hourly_rate=500.00, turnover_buffer_minutes=30)
    anesth = create_anesthesiologist(hourly_rate=200.00)
    inst1 = create_instrument_set(specialty="GENERAL", sterilize=True)
    inst2 = create_instrument_set(specialty="GENERAL", sterilize=True)
    inst3 = create_instrument_set(specialty="GENERAL", sterilize=True)

    c1 = approve_case(create_surgical_case(specialty_required="GENERAL")["id"])
    c1 = schedule_case(
        c1["id"],
        room_id=r1["id"],
        planned_start_minute=0,
        planned_end_minute=60,
        staff_assignments=[make_staff_assignment(anesth["id"], "LEAD_ANESTHESIOLOGIST")],
        instrument_set_id=inst1["id"],
    )
    c2_adj_pass = approve_case(create_surgical_case(specialty_required="GENERAL")["id"])
    c2_overlap_fail = approve_case(create_surgical_case(specialty_required="GENERAL")["id"])
    return {
        "rooms": (r1, r2, r3),
        "anesth": anesth,
        "instruments": (inst1, inst2, inst3),
        "case_c1_scheduled": c1,
        "case_c2_adj_pass_approved": c2_adj_pass,
        "case_c2_overlap_fail_approved": c2_overlap_fail,
    }


# --- Rule 9.1: settlement billing register conserved on cancel -----------
def setup_billing_register_invariant():
    """Difficulty Rule 9, instance settlement_billing_register_conserved_on_cancel.
    GENERAL case scheduled with R/A/B/I planned 0..60. Returns scheduled case
    + Settlement so test can verify pre/post cancel snapshots.
    Expected: pre.estimated=930, post.refund=930."""
    return setup_cancel_cascade_general()


# --- Rule 9.2: staff planned workload conserved on release --------------
def setup_workload_conservation_invariant():
    """Difficulty Rule 9, instance staff_planned_workload_minutes_conserved_on_release.
    Single anesth, scheduled GENERAL case 0..60. Test should snapshot
    GET /staff/A pre-schedule, post-schedule, and post-cancel."""
    room = create_operating_room(specialty_required="GENERAL", hourly_rate=500.00)
    anesth = create_anesthesiologist(hourly_rate=200.00)
    instrument = create_instrument_set(specialty="GENERAL", sterilize=True)
    case = approve_case(create_surgical_case(specialty_required="GENERAL")["id"])
    return {"room": room, "anesth": anesth, "instrument": instrument, "case": case}
