"""Composite setup helpers.

These encapsulate the multi-step preambles that most RPM test claims require.
All setup calls use get_success_data() (lenient) so a setup break surfaces as a
clear "Setup failed" rather than an opaque assertion. Every fixture builds its
preconditions from scratch using only PRD-declared endpoints, because the harness
restarts the server (empty DB) before every test.

Identity note (§2.1): all roles are opaque; X-User-ID is never compared to an
entity id. Some fixtures accept explicit clinician/physician user-ids so callers
can construct segregation-of-duties scenarios (§2.11).
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_clinician_headers,
    make_physician_headers,
)
from .factories import (
    create_payer_payload,
    create_patient_payload,
    create_consent_payload,
    create_care_plan_payload,
    create_device_payload,
    create_vitals_payload,
    create_care_activity_payload,
    create_billing_period_payload,
    finalize_payload,
)

CC = TEST_USERS["care_coordinator_headers"]
CLIN = TEST_USERS["clinician_headers"]
PHYS = TEST_USERS["physician_headers"]
BILL = TEST_USERS["billing_specialist_headers"]
PAYER_AGENT = TEST_USERS["payer_agent_headers"]


# --------------------------------------------------------------------------
# Clock helper (§2.12)
# --------------------------------------------------------------------------
def set_clock(to_iso8601, headers=BILL):
    return get_success_data(api_client.set_clock(to_iso8601, headers))


# --------------------------------------------------------------------------
# Tier 0: primitive create helpers
# --------------------------------------------------------------------------
def create_payer(**overrides):
    return get_success_data(api_client.create_payer(create_payer_payload(**overrides), BILL))


def create_patient(payer_id, **overrides):
    return get_success_data(
        api_client.create_patient(create_patient_payload(payer_id, **overrides), CC))


def create_consent(patient_id, **overrides):
    return get_success_data(
        api_client.create_consent(patient_id, create_consent_payload(**overrides), CC))


def create_care_plan(patient_id, **overrides):
    return get_success_data(
        api_client.create_care_plan(patient_id, create_care_plan_payload(**overrides), PHYS))


def activate_care_plan(patient_id, plan_id, supersede=None):
    payload = {} if supersede is None else {"supersede": supersede}
    return get_success_data(
        api_client.activate_care_plan(patient_id, plan_id, payload, PHYS))


def create_device(patient_id, **overrides):
    return get_success_data(
        api_client.create_device(patient_id, create_device_payload(**overrides), CC))


def activate_device(patient_id, device_id):
    return get_success_data(api_client.activate_device(patient_id, device_id, CC))


def create_billing_period(patient_id, period_year=2026, period_month=6):
    return get_success_data(
        api_client.create_billing_period(
            patient_id, create_billing_period_payload(period_year, period_month), BILL))


# --------------------------------------------------------------------------
# Tier 1 / 2: Patient progression to an enrolled, monitoring state
# --------------------------------------------------------------------------
def setup_enrolled_patient(payer_overrides=None, mrn="M-ENR-1", consent_type="BOTH",
                           consent_effective_at="2026-05-01T00:00:00Z",
                           required_care_minutes=20):
    """payer -> patient -> consent -> care-plan -> activate plan -> enroll.

    Returns dict(payer, patient, plan). Patient is ENROLLED with an ACTIVE plan and
    an ACTIVE consent, but no device yet (monitoring_status INACTIVE).
    """
    payer = create_payer(**(payer_overrides or {}))
    patient = create_patient(payer["id"], mrn=mrn)
    consent = create_consent(patient["id"], consent_type=consent_type,
                             effective_at=consent_effective_at)
    plan = create_care_plan(patient["id"], required_care_minutes=required_care_minutes)
    activate_care_plan(patient["id"], plan["id"])
    patient = get_success_data(api_client.enroll_patient(patient["id"], CC))
    return {"payer": payer, "patient": patient, "consent": consent, "plan": plan}


def setup_enrolled_patient_with_active_device(payer_overrides=None, mrn="M-DEV-1",
                                              serial_number="SN-DEV-1",
                                              device_type="BP_CUFF",
                                              consent_type="BOTH",
                                              consent_effective_at="2026-05-01T00:00:00Z",
                                              required_care_minutes=20):
    """Enrolled patient + one device transitioned to ACTIVE (monitoring MONITORING).

    Returns dict(payer, patient, plan, device). The device is activated AFTER enroll,
    so the activation legitimately flips monitoring INACTIVE -> MONITORING.
    """
    ctx = setup_enrolled_patient(payer_overrides=payer_overrides, mrn=mrn,
                                 consent_type=consent_type,
                                 consent_effective_at=consent_effective_at,
                                 required_care_minutes=required_care_minutes)
    device = create_device(ctx["patient"]["id"], device_type=device_type,
                           serial_number=serial_number)
    device = activate_device(ctx["patient"]["id"], device["id"])
    ctx["device"] = device
    return ctx


# --------------------------------------------------------------------------
# Tier 4: Threshold / accumulation targeting
# --------------------------------------------------------------------------
def transmit_distinct_device_days(patient_id, device_id, n_days, year=2026, month=6,
                                  start_day=1, base_value=110, headers=CLIN):
    """Transmit `n_days` non-breaching readings on consecutive distinct calendar days,
    so the owning OPEN period accrues exactly `n_days` distinct device-days.

    base_value stays well below any BP_CUFF breach band (140) so no alert is created.
    Returns the list of created VitalsReading dicts.
    """
    readings = []
    for i in range(n_days):
        day = start_day + i
        measured_at = f"{year:04d}-{month:02d}-{day:02d}T08:00:00Z"
        value = base_value + (i % 20)  # stays < 140
        r = get_success_data(api_client.create_vitals(
            patient_id, create_vitals_payload(device_id, value, measured_at), headers))
        readings.append(r)
    return readings


def log_care_activity(patient_id, billing_period_id, minutes, performed_at,
                      clinician_user_id="clin-log", activity_type="REVIEW",
                      headers=None):
    """Log a single care activity. Headers default to a Clinician whose X-User-ID
    matches clinician_user_id (relevant only where provenance comparisons apply)."""
    if headers is None:
        headers = make_clinician_headers(clinician_user_id)
    return get_success_data(api_client.create_care_activity(
        patient_id,
        create_care_activity_payload(billing_period_id, clinician_user_id, minutes,
                                     performed_at, activity_type=activity_type),
        headers))


def finalize_period(period_id):
    """Read current version then finalize (clock must already be past month end)."""
    bp = get_success_data(api_client.get_billing_period(period_id, BILL))
    return get_success_data(
        api_client.finalize_billing_period(period_id, finalize_payload(bp["version"]), BILL))


# --------------------------------------------------------------------------
# Tier 3 / 5: Full billing lifecycle shortcuts
# --------------------------------------------------------------------------
def setup_finalized_period_with_care_minutes(minutes=20, period_year=2026, period_month=6,
                                             payer_overrides=None, mrn="M-FIN-1",
                                             serial_number="SN-FIN-1",
                                             clinician_user_id="clin-fin",
                                             activity_day=3,
                                             include_device=True):
    """Full setup through to a FINALIZED period that has accrued a 99457 line item.

    Steps: enrolled patient (+ optional active device) -> OPEN period for the month
    -> clock into the month -> log `minutes` of care on one day -> clock past month
    end -> finalize. With minutes >= 20 the finalize accrues a 99457 line item.

    Returns dict(payer, patient, plan, device?, period, finalized_period).
    """
    ctx = (setup_enrolled_patient_with_active_device(
                payer_overrides=payer_overrides, mrn=mrn, serial_number=serial_number)
           if include_device else
           setup_enrolled_patient(payer_overrides=payer_overrides, mrn=mrn))
    # Device is activated before period exists in the device branch, so no in-period
    # 99453 is accrued unless caller arranges otherwise; finalize will see only 99457.
    period = create_billing_period(ctx["patient"]["id"], period_year, period_month)
    set_clock(f"{period_year:04d}-{period_month:02d}-10T00:00:00Z")
    performed_at = f"{period_year:04d}-{period_month:02d}-{activity_day:02d}T10:00:00Z"
    log_care_activity(ctx["patient"]["id"], period["id"], minutes, performed_at,
                      clinician_user_id=clinician_user_id)
    # Advance clock past month end.
    set_clock(_next_month_first_day(period_year, period_month))
    finalized = finalize_period(period["id"])
    ctx["period"] = period
    ctx["finalized_period"] = finalized
    return ctx


def setup_finalized_eligible_period(period_year=2026, period_month=6,
                                    payer_overrides=None, mrn="M-FE-1",
                                    serial_number="SN-FE-1", device_type="BP_CUFF",
                                    consent_type="BOTH",
                                    consent_effective_at="2026-05-01T00:00:00Z",
                                    care_minutes=20, care_activity_day=3,
                                    device_day_count=0, device_day_start=4,
                                    clinician_user_id="clin-fe"):
    """Open a period, then (in-period) enroll+activate a device, log care minutes, and
    transmit `device_day_count` distinct device-days, then finalize past month end.

    Because the device is created and activated AFTER the OPEN period exists and inside
    the period's month, activation accrues an in-period CPT_99453. Tune care_minutes
    (>=20 -> 99457) and device_day_count (>=16 -> 99454) to hit each eligibility combo:
      * care_minutes=20, device_day_count<16  -> 99453 + 99457
      * care_minutes>=20, device_day_count=16 -> 99453 + 99454 + 99457
      * care_minutes<20, device_day_count=16  -> 99453 + 99454

    Returns dict(payer, patient, plan, device, period, finalized_period).
    """
    if payer_overrides is None:
        payer_overrides = {"requires_active_consent": False}
    ctx = setup_enrolled_patient(payer_overrides=payer_overrides, mrn=mrn,
                                 consent_type=consent_type,
                                 consent_effective_at=consent_effective_at)
    pid = ctx["patient"]["id"]
    period = create_billing_period(pid, period_year, period_month)
    # Move clock into the month so device activation resolves THIS open period.
    set_clock(f"{period_year:04d}-{period_month:02d}-02T00:00:00Z")
    device = create_device(pid, device_type=device_type, serial_number=serial_number)
    device = activate_device(pid, device["id"])  # accrues in-period 99453
    if care_minutes >= 1:
        performed_at = f"{period_year:04d}-{period_month:02d}-{care_activity_day:02d}T10:00:00Z"
        log_care_activity(pid, period["id"], care_minutes, performed_at,
                          clinician_user_id=clinician_user_id)
    if device_day_count > 0:
        transmit_distinct_device_days(pid, device["id"], device_day_count,
                                      year=period_year, month=period_month,
                                      start_day=device_day_start)
    set_clock(_next_month_first_day(period_year, period_month))
    finalized = finalize_period(period["id"])
    ctx.update({"device": device, "period": period, "finalized_period": finalized})
    return ctx


def setup_submitted_claim(period_id):
    return get_success_data(api_client.submit_claim(period_id, BILL))


def setup_accepted_claim_full_eligible(mrn="M-ACC-1", serial_number="SN-ACC-1"):
    """Fully-eligible FINALIZED period (99453+99454+99457 = 11616), claim submitted+accepted.

    Returns dict(... period, finalized_period, claim) with claim ACCEPTED.
    """
    ctx = setup_finalized_eligible_period(
        mrn=mrn, serial_number=serial_number, device_type="GLUCOMETER",
        care_minutes=20, device_day_count=16, device_day_start=3)
    claim = setup_submitted_claim(ctx["period"]["id"])
    claim = get_success_data(api_client.accept_claim(claim["id"], PAYER_AGENT))
    ctx["claim"] = claim
    return ctx


# --------------------------------------------------------------------------
# Alert / review-task progression
# --------------------------------------------------------------------------
def create_critical_bp_alert(patient_id, device_id, measured_at="2026-06-10T08:00:00Z",
                             systolic=200, diastolic=130):
    """Transmit a CRITICAL BP reading and return (reading, alert)."""
    reading = get_success_data(api_client.create_vitals(
        patient_id,
        create_vitals_payload(device_id, systolic, measured_at, secondary_value=diastolic),
        CLIN))
    alerts = get_success_data(api_client.list_alerts(
        CLIN, params={"vitals_reading_id": reading["id"]}))
    alert = alerts[0]
    return reading, alert


def setup_escalated_alert_with_queued_task(mrn="M-ESC-1", serial_number="SN-ESC-1",
                                           clock="2026-06-10T00:00:00Z"):
    """Enrolled patient + active BP device -> CRITICAL alert -> escalate -> URGENT task.

    Returns dict(payer, patient, plan, device, reading, alert, task).
    The alert is ESCALATED and the spawned ReviewTask is QUEUED.
    """
    ctx = setup_enrolled_patient_with_active_device(mrn=mrn, serial_number=serial_number,
                                                    consent_type="RPM")
    set_clock(clock, CC)
    reading, alert = create_critical_bp_alert(ctx["patient"]["id"], ctx["device"]["id"])
    alert = get_success_data(api_client.escalate_alert(alert["id"], CLIN))
    tasks = get_success_data(api_client.list_review_tasks(
        PHYS, params={"threshold_alert_id": alert["id"]}))
    task = tasks[0]
    ctx.update({"reading": reading, "alert": alert, "task": task})
    return ctx


def setup_in_review_task_with_logged_minutes(mrn="M-SG-1", serial_number="SN-SG-1",
                                             owner_user_id="phys-A",
                                             minute_logger_user_id="phys-B",
                                             clock="2026-06-10T00:00:00Z"):
    """Build an IN_REVIEW ReviewTask for segregation/owner sign tests.

    Sequence: enrolled patient + active BP device + OPEN period -> log a care activity
    whose clinician_user_id == minute_logger_user_id (logged by a Physician with that
    X-User-ID) -> CRITICAL alert -> escalate -> the spawned task is claimed by
    owner_user_id (so reviewer_user_id == owner_user_id, status IN_REVIEW).

    Returns dict(payer, patient, plan, device, period, alert, task).
    """
    ctx = setup_enrolled_patient_with_active_device(mrn=mrn, serial_number=serial_number,
                                                    consent_type="BOTH")
    pid = ctx["patient"]["id"]
    period = create_billing_period(pid, 2026, 6)
    set_clock(clock, BILL)
    # A Physician logs care minutes carrying minute_logger_user_id as the performer.
    log_care_activity(pid, period["id"], 15, "2026-06-10T09:00:00Z",
                      clinician_user_id=minute_logger_user_id,
                      headers=make_physician_headers(minute_logger_user_id))
    reading, alert = create_critical_bp_alert(pid, ctx["device"]["id"],
                                              measured_at="2026-06-10T08:00:00Z",
                                              systolic=195, diastolic=125)
    alert = get_success_data(api_client.escalate_alert(alert["id"], CLIN))
    task = get_success_data(api_client.list_review_tasks(
        PHYS, params={"threshold_alert_id": alert["id"]}))[0]
    task = get_success_data(
        api_client.claim_review_task(task["id"], make_physician_headers(owner_user_id)))
    ctx.update({"period": period, "alert": alert, "task": task})
    return ctx


def _next_month_first_day(year, month):
    if month == 12:
        return f"{year + 1:04d}-01-01T00:00:00Z"
    return f"{year:04d}-{month + 1:02d}-01T00:00:00Z"
