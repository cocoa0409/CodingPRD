"""Composite setup helpers.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints; the harness restarts the server (empty DB) before each test. Setup
calls use get_success_data() so a broken precondition surfaces as "Setup failed"
rather than a confusing assertion error.

Identity threading: whenever a Technician acts, the acting X-User-ID is the
acting Technician's own id via make_technician_headers(technician["id"]); this is
mandatory for the ownership-gated appointment transitions (§2.1).
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import TEST_USERS, make_technician_headers
from . import factories as F
from .constants import ROUTE_WINDOW_START, ROUTE_WINDOW_END, APPT_START, APPT_END_90

DISPATCHER = TEST_USERS["dispatcher_headers"]
BILLING = TEST_USERS["billing_clerk_headers"]

# Distinct (repair_type, part_sku) pairs for building multiple valid repairs.
REPAIR_SPECS = [
    ("CAP", "CAP-STD"),
    ("DAMPER", "DMP-TOP"),
    ("LINER", "LNR-SS6"),
    ("CAP", "CAP-SS"),
    ("DAMPER", "DMP-THR"),
    ("LINER", "LNR-AL"),
]


# --------------------------------------------------------------------------
# Clock
# --------------------------------------------------------------------------
def set_clock(iso: str):
    return get_success_data(api_client.set_clock(iso, DISPATCHER))


# --------------------------------------------------------------------------
# Single-entity builders
# --------------------------------------------------------------------------
def make_customer(**overrides):
    return get_success_data(api_client.create_customer(F.create_customer_payload(**overrides), DISPATCHER))


def make_chimney(customer_id, **overrides):
    return get_success_data(
        api_client.create_chimney(F.create_chimney_payload(customer_id=customer_id, **overrides), DISPATCHER)
    )


def make_technician(**overrides):
    return get_success_data(api_client.create_technician(F.create_technician_payload(**overrides), DISPATCHER))


def make_route_day(technician_id, **overrides):
    return get_success_data(
        api_client.create_route_day(F.create_route_day_payload(technician_id=technician_id, **overrides), DISPATCHER)
    )


def make_service_job(customer_id, chimney_id, **overrides):
    return get_success_data(
        api_client.create_service_job(
            F.create_service_job_payload(customer_id=customer_id, chimney_id=chimney_id, **overrides), DISPATCHER
        )
    )


def get_job(job_id):
    return get_success_data(api_client.get_service_job(job_id, DISPATCHER))


def get_chimney(chimney_id):
    return get_success_data(api_client.get_chimney(chimney_id, DISPATCHER))


def get_chimney_version(chimney_id):
    return get_chimney(chimney_id)["version"]


def get_route_day(route_day_id):
    return get_success_data(api_client.get_route_day(route_day_id, DISPATCHER))


def get_repair_order(ro_id):
    return get_success_data(api_client.get_repair_order(ro_id, DISPATCHER))


def get_appointment(appt_id):
    return get_success_data(api_client.get_appointment(appt_id, DISPATCHER))


def get_warranty(warranty_id):
    return get_success_data(api_client.get_warranty(warranty_id, DISPATCHER))


def get_reminder(reminder_id):
    return get_success_data(api_client.get_reminder_schedule(reminder_id, DISPATCHER))


# --------------------------------------------------------------------------
# Composite: onboarding setups
# --------------------------------------------------------------------------
def setup_customer_chimney(chimney_overrides=None):
    """Returns (customer, chimney)."""
    customer = make_customer()
    chimney = make_chimney(customer["id"], **(chimney_overrides or {}))
    return customer, chimney


def setup_job(job_overrides=None, chimney_overrides=None):
    """Active onboarding through a DRAFT ServiceJob plus a technician.

    Returns dict: customer, chimney, technician, job.
    """
    customer = make_customer()
    chimney = make_chimney(customer["id"], **(chimney_overrides or {}))
    technician = make_technician()
    job = make_service_job(customer["id"], chimney["id"], **(job_overrides or {}))
    return {"customer": customer, "chimney": chimney, "technician": technician, "job": job}


def setup_route_day(capacity_minutes=300):
    """A technician with a route day. Returns dict: technician, route_day."""
    technician = make_technician()
    route_day = make_route_day(technician["id"], capacity_minutes=capacity_minutes)
    return {"technician": technician, "route_day": route_day}


# --------------------------------------------------------------------------
# On-site evidence
# --------------------------------------------------------------------------
def record_safety_check(job_id, technician, co_ppm=3, draft_ok=True, spillage_detected=False):
    """Record a safety check; returns the SafetyCheck data (has computed outcome)."""
    payload = F.create_safety_check_payload(
        service_job_id=job_id, co_ppm=co_ppm, draft_ok=draft_ok, spillage_detected=spillage_detected
    )
    return get_success_data(api_client.safety_check_service_job(job_id, payload, make_technician_headers(technician["id"])))


def make_job_safe(job_id, technician):
    """Drive posture to SAFE via a passing safety check (co low, draft ok)."""
    record_safety_check(job_id, technician, co_ppm=3, draft_ok=True)


def record_sweep(job_id, technician, measured_creosote_class=1, glaze_present=False):
    """Log a sweep; returns the SweepLog data."""
    payload = F.create_sweep_log_payload(
        service_job_id=job_id, measured_creosote_class=measured_creosote_class, glaze_present=glaze_present
    )
    return get_success_data(api_client.sweep_service_job(job_id, payload, make_technician_headers(technician["id"])))


def record_inspect(job_id, technician, flue_assessment):
    return get_success_data(
        api_client.inspect_service_job(job_id, {"flue_assessment": flue_assessment}, make_technician_headers(technician["id"]))
    )


# --------------------------------------------------------------------------
# Appointments
# --------------------------------------------------------------------------
def book_appointment(route_day_id, service_job_id, technician_id, start_ts=APPT_START, end_ts=APPT_END_90):
    payload = F.create_appointment_payload(
        route_day_id=route_day_id, service_job_id=service_job_id, technician_id=technician_id,
        start_ts=start_ts, end_ts=end_ts,
    )
    return get_success_data(api_client.create_appointment(payload, DISPATCHER))


def drive_appointment_to_on_site(appt_id, technician):
    """DEPART then ARRIVE — advances the parent job to IN_PROGRESS."""
    th = make_technician_headers(technician["id"])
    get_success_data(api_client.transition_appointment(appt_id, {"action": "DEPART"}, th))
    get_success_data(api_client.transition_appointment(appt_id, {"action": "ARRIVE"}, th))


def setup_in_progress_job(job_overrides=None, capacity_minutes=300):
    """Job booked on a route day and driven to IN_PROGRESS (posture still PENDING).

    Returns dict: customer, chimney, technician, route_day, job, appointment.
    """
    base = setup_job(job_overrides=job_overrides)
    route_day = make_route_day(base["technician"]["id"], capacity_minutes=capacity_minutes)
    appointment = book_appointment(route_day["id"], base["job"]["id"], base["technician"]["id"])
    drive_appointment_to_on_site(appointment["id"], base["technician"])
    base["route_day"] = route_day
    base["appointment"] = appointment
    base["job"] = get_job(base["job"]["id"])
    return base


# --------------------------------------------------------------------------
# Repair orders
# --------------------------------------------------------------------------
def propose_repair(job_id, technician=None, headers=None, repair_type="CAP", part_sku="CAP-STD",
                   quoted_cost_cents=9000):
    """Propose a repair order. Provide either technician (acts as Technician) or explicit headers."""
    if headers is None:
        headers = make_technician_headers(technician["id"]) if technician else DISPATCHER
    payload = F.create_repair_order_payload(
        service_job_id=job_id, repair_type=repair_type, quoted_cost_cents=quoted_cost_cents
    )
    if part_sku is not None:
        payload["part_sku"] = part_sku
    return get_success_data(api_client.create_repair_order(payload, headers))


def approve_repair(ro_id):
    return get_success_data(api_client.transition_repair_order(ro_id, {"action": "APPROVE"}, DISPATCHER))


def start_repair(ro_id, technician):
    return get_success_data(
        api_client.transition_repair_order(ro_id, {"action": "START"}, make_technician_headers(technician["id"]))
    )


def complete_repair(ro_id, technician, final_cost_cents, labor_cents):
    return get_success_data(
        api_client.transition_repair_order(
            ro_id, {"action": "COMPLETE", "final_cost_cents": final_cost_cents, "labor_cents": labor_cents},
            make_technician_headers(technician["id"]),
        )
    )


def add_completed_repair(job_id, technician, repair_type="CAP", part_sku="CAP-STD",
                         quoted_cost_cents=12000, final_cost_cents=12000, labor_cents=8000):
    """Propose -> approve -> start -> complete a repair. Requires posture SAFE/CONDITIONS.

    Returns the COMPLETED RepairOrder data.
    """
    ro = propose_repair(job_id, technician=technician, repair_type=repair_type, part_sku=part_sku,
                        quoted_cost_cents=quoted_cost_cents)
    approve_repair(ro["id"])
    start_repair(ro["id"], technician)
    return complete_repair(ro["id"], technician, final_cost_cents, labor_cents)


# --------------------------------------------------------------------------
# Warranties
# --------------------------------------------------------------------------
def issue_warranty(job_id, repair_order_id, coverage_type="LABOR_ONLY", term_months=12):
    payload = F.create_warranty_payload(
        repair_order_id=repair_order_id, service_job_id=job_id,
        coverage_type=coverage_type, term_months=term_months,
    )
    return get_success_data(api_client.create_warranty(payload, BILLING))


# --------------------------------------------------------------------------
# Reminders
# --------------------------------------------------------------------------
def create_reminder(customer_id, chimney_id, expected_chimney_version, cadence_months=None):
    overrides = {
        "customer_id": customer_id,
        "chimney_id": chimney_id,
        "expected_chimney_version": expected_chimney_version,
    }
    if cadence_months is not None:
        overrides["cadence_months"] = cadence_months
    return get_success_data(api_client.create_reminder_schedule(F.create_reminder_schedule_payload(**overrides), DISPATCHER))


# --------------------------------------------------------------------------
# High-level lifecycle shortcuts
# --------------------------------------------------------------------------
def setup_safe_draft_job(job_overrides=None):
    """A DRAFT ServiceJob whose posture has been driven to SAFE by a passing
    safety check (no appointment needed; safety checks have no job_status
    precondition). Returns dict: customer, chimney, technician, job.
    """
    base = setup_job(job_overrides=job_overrides)
    make_job_safe(base["job"]["id"], base["technician"])
    base["job"] = get_job(base["job"]["id"])
    return base


def setup_completed_invoice_job(inspection_level=1, trip_zone="A", measured_creosote_class=1,
                                glaze_present=False, repair_finals=None, repair_authorization_cents=100000):
    """Full lifecycle through COMPLETED, returning the completed job.

    Drives: onboarding -> route day -> book appointment -> DEPART/ARRIVE
    (IN_PROGRESS) -> passing safety check (SAFE) -> sweep (final cost) ->
    for each (final, labor) in repair_finals a fully COMPLETED repair -> complete.

    Returns dict: customer, chimney, technician, route_day, job (COMPLETED),
    appointment, repairs (list of COMPLETED RepairOrder data).
    """
    repair_finals = repair_finals or []
    base = setup_in_progress_job(
        job_overrides={
            "inspection_level": inspection_level,
            "trip_zone": trip_zone,
            "repair_authorization_cents": repair_authorization_cents,
        }
    )
    tech = base["technician"]
    job_id = base["job"]["id"]
    make_job_safe(job_id, tech)
    record_sweep(job_id, tech, measured_creosote_class=measured_creosote_class, glaze_present=glaze_present)
    repairs = []
    for i, (final_cost, labor) in enumerate(repair_finals):
        rtype, sku = REPAIR_SPECS[i % len(REPAIR_SPECS)]
        repairs.append(
            add_completed_repair(job_id, tech, repair_type=rtype, part_sku=sku,
                                 quoted_cost_cents=final_cost, final_cost_cents=final_cost, labor_cents=labor)
        )
    completed = get_success_data(api_client.complete_service_job(job_id, BILLING))
    base["job"] = completed
    base["repairs"] = repairs
    return base
