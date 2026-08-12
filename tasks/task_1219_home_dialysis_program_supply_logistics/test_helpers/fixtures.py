"""Composite setup helpers — multi-step preconditions expressed with the PRD's
public endpoints only. Each test starts against an empty database (the harness
restarts the server per test), so every fixture builds from scratch.

Setup calls use get_success_data() so a setup failure surfaces as a clear
'Setup failed' rather than a confusing assertion error.
"""
from datetime import date, timedelta

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS, DEFAULT_CATALOG
from .factories import (
    create_program_payload, create_patient_payload,
    create_training_attempt_payload, create_home_assessment_payload,
    create_work_order_payload, create_machine_payload,
    create_maintenance_event_payload, create_backup_plan_payload,
    create_supply_order_payload, create_delivery_appointment_payload,
    create_treatment_log_payload, create_chair_payload,
    create_slot_reservation_payload, create_waste_return_payload,
    create_transition_payload,
)
from .test_users import (
    make_admin_headers, make_nurse_headers, make_nephrologist_headers,
    make_coordinator_headers, make_biomed_headers, make_patient_headers,
)

NURSE_1 = "nurse-1"
NURSE_2 = "nurse-2"
MODULES = [
    "WATER_HANDLING", "MACHINE_OPERATION", "ASEPTIC_TECHNIQUE",
    "EMERGENCY_RESPONSE", "SUPPLY_STORAGE",
]


def _fail(msg, resp):
    raise AssertionError(f"Setup failed: {msg} -> {resp.status_code} {resp.text}")


# ---------------------------------------------------------------------------
# Tier 1: base entities
# ---------------------------------------------------------------------------

def create_program(**overrides) -> dict:
    """Create a DialysisProgram. Returns the program dict."""
    resp = api_client.create_program(create_program_payload(**overrides),
                                     make_admin_headers("admin-1"))
    if resp.status_code != 201:
        _fail("create_program", resp)
    return get_success_data(resp)


def set_clock(to_iso8601: str):
    """Advance the logical clock (PRD 2.5)."""
    resp = api_client.set_clock(to_iso8601, make_admin_headers("admin-1"))
    if resp.status_code != 200:
        _fail(f"set_clock {to_iso8601}", resp)
    return get_success_data(resp)


def create_patient(program_id, **overrides) -> dict:
    """Enroll a patient (TRAINING / NOT_READY). Returns the patient dict."""
    resp = api_client.create_patient(create_patient_payload(program_id, **overrides),
                                     make_nurse_headers(NURSE_1))
    if resp.status_code != 201:
        _fail("create_patient", resp)
    return get_success_data(resp)


def get_patient(patient_id) -> dict:
    resp = api_client.get_patient(patient_id, make_admin_headers("admin-1"))
    if resp.status_code != 200:
        _fail(f"get_patient {patient_id}", resp)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 2/3: readiness chain — training, assessment, machine, plan, activate
# ---------------------------------------------------------------------------

def record_and_sign_all_modules(patient_id, score_pct=90) -> list:
    """Record + cross-sign all five module attempts (SoD: trainer nurse-1,
    signer nurse-2 per PRD 2.11). Returns the attempt dicts."""
    attempts = []
    for module in MODULES:
        resp = api_client.create_training_attempt(
            create_training_attempt_payload(patient_id, module, score_pct=score_pct),
            make_nurse_headers(NURSE_1))
        if resp.status_code != 201:
            _fail(f"record attempt {module}", resp)
        att = get_success_data(resp)
        resp = api_client.sign_off_attempt(att["id"], make_nurse_headers(NURSE_2))
        if resp.status_code != 200:
            _fail(f"sign-off attempt {module}", resp)
        attempts.append(get_success_data(resp))
    return attempts


def create_accepted_assessment(patient_id, storage_area_sqft=100, **overrides) -> dict:
    """Submit + accept a PASS home assessment. Returns the ACCEPTED assessment."""
    resp = api_client.create_home_assessment(
        create_home_assessment_payload(patient_id,
                                       storage_area_sqft=storage_area_sqft,
                                       **overrides),
        make_nurse_headers(NURSE_1))
    if resp.status_code != 201:
        _fail("create_home_assessment", resp)
    asmt = get_success_data(resp)
    resp = api_client.accept_assessment(asmt["id"], make_nurse_headers(NURSE_2))
    if resp.status_code != 200:
        _fail("accept_assessment", resp)
    return get_success_data(resp)


def create_machine(program_id, **overrides) -> dict:
    resp = api_client.create_machine(create_machine_payload(program_id, **overrides),
                                     make_biomed_headers("biomed-1"))
    if resp.status_code != 201:
        _fail("create_machine", resp)
    return get_success_data(resp)


def assign_machine(machine_id, patient_id) -> dict:
    """Assign with a fresh OCC version read."""
    m = get_success_data(api_client.get_machine(machine_id,
                                                make_admin_headers("admin-1")))
    resp = api_client.assign_machine(
        machine_id,
        {"patient_id": patient_id, "expected_machine_version": m["version"]},
        make_biomed_headers("biomed-1"))
    if resp.status_code != 200:
        _fail(f"assign_machine {machine_id}", resp)
    return get_success_data(resp)


def create_active_plan(patient_id, plan_mode="IN_CENTER_CHAIR",
                       backup_machine_id=None) -> dict:
    """Create an ACTIVE backup plan with a fresh OCC patient version."""
    pat = get_patient(patient_id)
    payload = create_backup_plan_payload(
        patient_id, pat["version"], plan_mode=plan_mode)
    if backup_machine_id is not None:
        payload["backup_machine_id"] = backup_machine_id
    resp = api_client.create_backup_plan(payload, make_nurse_headers(NURSE_1))
    if resp.status_code != 201:
        _fail("create_backup_plan", resp)
    return get_success_data(resp)


def create_active_home_patient(program_id=None, *, tpw=None, upt=None,
                               storage_area_sqft=100, catalog=None,
                               score_pct=90, plan_mode="IN_CENTER_CHAIR",
                               **program_overrides) -> dict:
    """Full readiness chain: program (optional) -> patient -> 5 signed-off
    modules -> accepted PASS assessment -> assigned machine -> ACTIVE plan ->
    activate. Returns a dict of the composite context."""
    if program_id is None:
        program_kwargs = dict(program_overrides)
        if catalog is not None:
            program_kwargs["supply_catalog"] = catalog
        program = create_program(**program_kwargs)
        program_id = program["id"]
    else:
        program = get_success_data(api_client.get_program(
            program_id, make_admin_headers("admin-1")))
    patient_kwargs = {}
    if tpw is not None:
        patient_kwargs["prescription_treatments_per_week"] = tpw
    if upt is not None:
        patient_kwargs["prescription_units_per_treatment"] = upt
    patient = create_patient(program_id, **patient_kwargs)
    record_and_sign_all_modules(patient["id"], score_pct=score_pct)
    assessment = create_accepted_assessment(patient["id"],
                                            storage_area_sqft=storage_area_sqft)
    machine = create_machine(program_id)
    machine = assign_machine(machine["id"], patient["id"])
    plan = create_active_plan(patient["id"], plan_mode=plan_mode)
    resp = api_client.activate_patient(patient["id"],
                                       make_nephrologist_headers("nephro-1"))
    if resp.status_code != 200:
        _fail("activate_patient", resp)
    patient = get_success_data(resp)
    return {
        "program": program, "patient": patient, "assessment": assessment,
        "machine": machine, "plan": plan,
    }


# ---------------------------------------------------------------------------
# Tier 3: order lifecycle shortcuts
# ---------------------------------------------------------------------------

def create_draft_order(patient_id, order_month, lines) -> dict:
    """Create a DRAFT order with a fresh OCC patient version."""
    pat = get_patient(patient_id)
    resp = api_client.create_supply_order(
        create_supply_order_payload(patient_id, order_month, lines, pat["version"]),
        make_patient_headers(patient_id))
    if resp.status_code != 201:
        _fail("create_supply_order", resp)
    return get_success_data(resp)


def submit_order(order_id, patient_id) -> dict:
    resp = api_client.submit_supply_order(order_id, make_patient_headers(patient_id))
    if resp.status_code != 200:
        _fail(f"submit_order {order_id}", resp)
    return get_success_data(resp)


def review_order(order_id, decision="APPROVE", note=None) -> dict:
    payload = {"decision": decision}
    if note is not None:
        payload["note"] = note
    resp = api_client.review_supply_order(order_id, payload,
                                          make_coordinator_headers("coord-1"))
    if resp.status_code != 200:
        _fail(f"review_order {order_id}", resp)
    return get_success_data(resp)


def create_approved_order(patient_id, order_month, lines) -> dict:
    """DRAFT -> SUBMITTED -> APPROVED. Returns the order."""
    order = create_draft_order(patient_id, order_month, lines)
    order = submit_order(order["id"], patient_id)
    return review_order(order["id"], "APPROVE")


def schedule_appointment(order_id, window_start, window_end) -> dict:
    resp = api_client.create_delivery_appointment(
        create_delivery_appointment_payload(
            order_id, window_start=window_start, window_end=window_end),
        make_coordinator_headers("coord-1"))
    if resp.status_code != 201:
        _fail("create_delivery_appointment", resp)
    return get_success_data(resp)


def complete_appointment(appointment_id, delivered_units) -> dict:
    resp = api_client.complete_delivery_appointment(
        appointment_id, {"delivered_units": delivered_units},
        make_coordinator_headers("coord-1"))
    if resp.status_code != 200:
        _fail(f"complete_appointment {appointment_id}", resp)
    return get_success_data(resp)


def create_delivered_order(patient_id, order_month, lines, delivered_units,
                           window_start="2026-05-04T08:00:00Z",
                           window_end="2026-05-04T12:00:00Z") -> dict:
    """APPROVED order + one appointment completed with delivered_units."""
    order = create_approved_order(patient_id, order_month, lines)
    appt = schedule_appointment(order["id"], window_start, window_end)
    complete_appointment(appt["id"], delivered_units)
    return get_success_data(api_client.get_supply_order(
        order["id"], make_admin_headers("admin-1")))


# ---------------------------------------------------------------------------
# Tier 3: logs and reviews
# ---------------------------------------------------------------------------

def create_log(patient_id, machine_id, treatment_date, duration_minutes=240,
               consumption=None) -> dict:
    resp = api_client.create_treatment_log(
        create_treatment_log_payload(patient_id, machine_id, treatment_date,
                                     duration_minutes=duration_minutes,
                                     consumption=consumption or []),
        make_patient_headers(patient_id))
    if resp.status_code != 201:
        _fail(f"create_treatment_log {treatment_date}", resp)
    return get_success_data(resp)


def mark_reviewed(log_id) -> dict:
    resp = api_client.mark_log_reviewed(log_id, make_nurse_headers(NURSE_1))
    if resp.status_code != 200:
        _fail(f"mark_reviewed {log_id}", resp)
    return get_success_data(resp)


def list_reviews(patient_id) -> list:
    resp = api_client.list_patient_clinical_reviews(patient_id,
                                                    make_admin_headers("admin-1"))
    if resp.status_code != 200:
        _fail("list_reviews", resp)
    return get_success_data(resp)


def sign_off_review(review_id, outcome="CONTINUE") -> dict:
    resp = api_client.sign_off_review(review_id, {"outcome": outcome},
                                      make_nephrologist_headers("nephro-1"))
    if resp.status_code != 200:
        _fail(f"sign_off_review {review_id}", resp)
    return get_success_data(resp)


def create_logs_with_review(patient_id, machine_id, dates, duration_minutes=240,
                            consumption=None, mark_all_reviewed=True,
                            sign_off_outcome="CONTINUE") -> dict:
    """Create logs on the given dates (zero consumption by default), optionally
    mark each REVIEWED, then sign off the auto-created CADENCE review if one
    exists. Returns {'logs': [...], 'review': dict|None}."""
    logs = [create_log(patient_id, machine_id, d,
                       duration_minutes=duration_minutes,
                       consumption=consumption) for d in dates]
    if mark_all_reviewed:
        for log in logs:
            mark_reviewed(log["id"])
    review = None
    reviews = list_reviews(patient_id)
    if reviews:
        review = reviews[0]
        if review["status"] == "PENDING" and sign_off_outcome is not None:
            review = sign_off_review(review["id"], sign_off_outcome)
    return {"logs": logs, "review": review}


# ---------------------------------------------------------------------------
# Tier 3: chairs, slots, waste, transitions
# ---------------------------------------------------------------------------

def create_chair(program_id, **overrides) -> dict:
    resp = api_client.create_chair(create_chair_payload(program_id, **overrides),
                                   make_admin_headers("admin-1"))
    if resp.status_code != 201:
        _fail("create_chair", resp)
    return get_success_data(resp)


def create_slot(patient_id, chair_id, slot_start, slot_end) -> dict:
    resp = api_client.create_slot_reservation(
        create_slot_reservation_payload(patient_id, chair_id,
                                        slot_start=slot_start, slot_end=slot_end),
        make_patient_headers(patient_id))
    if resp.status_code != 201:
        _fail("create_slot", resp)
    return get_success_data(resp)


def report_waste_return(patient_id, record_type, activity_month, lines) -> dict:
    resp = api_client.create_waste_return_record(
        create_waste_return_payload(patient_id, record_type, activity_month, lines),
        make_patient_headers(patient_id))
    if resp.status_code != 201:
        _fail("create_waste_return_record", resp)
    return get_success_data(resp)


def verify_waste_return(record_id, approved=True) -> dict:
    resp = api_client.verify_waste_return_record(record_id, {"approved": approved},
                                                 make_coordinator_headers("coord-1"))
    if resp.status_code != 200:
        _fail(f"verify_waste_return {record_id}", resp)
    return get_success_data(resp)


def request_transition(patient_id, direction, reason_code, effective_from,
                       as_nephrologist=False, **overrides) -> dict:
    headers = (make_nephrologist_headers("nephro-1") if as_nephrologist
               else make_patient_headers(patient_id))
    resp = api_client.create_transition_record(
        create_transition_payload(patient_id, direction, reason_code,
                                  effective_from, **overrides),
        headers)
    if resp.status_code != 201:
        _fail("create_transition_record", resp)
    return get_success_data(resp)


def approve_transition(transition_id) -> dict:
    resp = api_client.approve_transition(transition_id,
                                         make_nephrologist_headers("nephro-1"))
    if resp.status_code != 200:
        _fail(f"approve_transition {transition_id}", resp)
    return get_success_data(resp)


def activate_transition(transition_id) -> dict:
    resp = api_client.activate_transition(transition_id,
                                          make_nephrologist_headers("nephro-1"))
    if resp.status_code != 200:
        _fail(f"activate_transition {transition_id}", resp)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 4/5: threshold targeting and full-lifecycle composites
# ---------------------------------------------------------------------------

def setup_active_patient_with_delivered_order(*, order_qty, delivered_qty,
                                              order_month="2026-05",
                                              sku="DIALYSATE_2L",
                                              window_date="2026-05-04",
                                              tpw=3, upt=6, storage_area_sqft=100,
                                              catalog=None,
                                              **program_overrides) -> dict:
    """ACTIVE_HOME patient plus an APPROVED order whose appointment was
    completed with delivered_qty. Returns the composite context including
    'order' and 'appointment'."""
    ctx = create_active_home_patient(tpw=tpw, upt=upt,
                                     storage_area_sqft=storage_area_sqft,
                                     catalog=catalog, **program_overrides)
    pat = ctx["patient"]["id"]
    order = create_approved_order(pat, order_month, [{"sku": sku, "quantity": order_qty}])
    appt = schedule_appointment(order["id"], f"{window_date}T08:00:00Z",
                                f"{window_date}T12:00:00Z")
    complete_appointment(appt["id"], delivered_qty)
    ctx["order"] = get_success_data(api_client.get_supply_order(
        order["id"], make_admin_headers("admin-1")))
    ctx["appointment"] = appt
    ctx["patient"] = get_patient(pat)
    return ctx


def _dates_between(start: date, count: int) -> list:
    return [(start + timedelta(days=i)).isoformat() for i in range(count)]
