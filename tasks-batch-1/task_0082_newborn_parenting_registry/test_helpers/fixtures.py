"""Composite setup helpers.

Every test runs against a freshly restarted, empty server, so each fixture builds
its preconditions from scratch using only PRD-declared endpoints. Fixtures use the
lenient get_success_data() validator internally so setup failures surface as clear
"Setup failed" errors rather than confusing assertion failures.

All roles are opaque (PRD §2.1): ownership is never decided by matching X-User-ID
against an entity id, so the shared role-header constants are always correct.
"""
from datetime import datetime, timedelta, timezone

from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import TEST_USERS
from . import factories as f


def _birth_plus(birth_datetime: str, hours: int = 0) -> str:
    """birth_datetime advanced by `hours`, formatted as the server's ISO 8601 ms-UTC."""
    base = datetime.fromisoformat(birth_datetime.replace("Z", "+00:00")).astimezone(timezone.utc)
    out = base + timedelta(hours=hours)
    return out.strftime("%Y-%m-%dT%H:%M:%S.") + f"{out.microsecond // 1000:03d}Z"

# Role header shortcuts.
SUPER = TEST_USERS["registry_supervisor_headers"]
CLERK = TEST_USERS["intake_clerk_headers"]
NURSE = TEST_USERS["attending_nurse_headers"]
NEO = TEST_USERS["neonatologist_headers"]
BENEFITS = TEST_USERS["benefits_coordinator_headers"]
VITAL = TEST_USERS["vital_records_officer_headers"]


# --- Clock ---

# Track the clock the test last asked for, so composite setup helpers that must
# temporarily move the clock (e.g. to satisfy the admit window) can restore the
# test's intended clock afterward. The admit window (PRD §3.1) is the only setup
# step gated on the clock; birth recording, enrollment, and SEP checks all read
# stored timestamps, not the clock.
_last_clock = None


def set_clock(instant: str):
    """Set the test-driving clock (PRD §2.9)."""
    global _last_clock
    _last_clock = instant
    return get_success_data(api_client.set_clock(instant, SUPER))


# --- Tier 1/2: base scaffolding (policy + registration through ADMITTED) ---

def create_policy(plan_type="EMPLOYER_GROUP", dependent_slots_max=3, carrier_name="EmpCo"):
    """Create an InsurancePolicy. Returns the policy dict."""
    payload = f.create_insurance_policy_payload(
        plan_type=plan_type, dependent_slots_max=dependent_slots_max, carrier_name=carrier_name)
    return get_success_data(api_client.create_insurance_policy(payload, BENEFITS))


def create_bed(acuity_level="LEVEL_3", bed_label="NICU-1"):
    """Register a NICU bed. Returns the bed dict."""
    payload = f.create_nicu_bed_payload(acuity_level=acuity_level, bed_label=bed_label)
    return get_success_data(api_client.create_nicu_bed(payload, NEO))


def create_admitted_registration(policy_id=None, due_date="2026-03-12", **reg_overrides):
    """Create a policy (if none supplied) + registration, then submit + admit.

    Returns (registration, policy_id). The admit step is the only setup action the
    PRD gates on the clock (PRD §3.1: the clock date must fall within
    [due_date-21d, due_date+21d] inclusive). To keep this helper self-contained the
    admit is performed with the clock pinned to due_date noon (always inside the
    window), then the test's own clock is restored so the caller's scenario-specific
    instant survives the setup. Birth recording reads birth_datetime, not the clock,
    so the temporary clock move is invisible to every other step.
    """
    if policy_id is None:
        policy_id = create_policy()["id"]
    reg = get_success_data(api_client.create_registration(
        f.create_registration_payload(policy_id, due_date=due_date, **reg_overrides), CLERK))
    rid = reg["id"]
    get_success_data(api_client.submit_registration(rid, CLERK))

    saved_clock = _last_clock
    set_clock(f"{due_date}T12:00:00.000Z")  # within [due-21d, due+21d]
    reg = get_success_data(api_client.admit_registration(rid, CLERK))
    if saved_clock is not None:
        set_clock(saved_clock)  # restore the test's intended clock
    return reg, policy_id


def record_birth(reg_id, **overrides):
    """Record a birth under an ADMITTED/BIRTH_RECORDED registration. Returns the newborn."""
    return get_success_data(api_client.record_birth(reg_id, f.record_birth_payload(**overrides), NURSE))


def setup_admitted_with_newborn(policy_plan="EMPLOYER_GROUP", policy_slots=3,
                                due_date="2026-03-12", **birth_overrides):
    """Active pipeline: policy + ADMITTED registration + one BORN newborn.

    Returns (newborn, reg_id, policy_id). Caller controls the birth via **birth_overrides
    (e.g. weight_grams, gestational_age_weeks, apgar_5min, legal_name, birth_datetime).
    """
    policy = create_policy(plan_type=policy_plan, dependent_slots_max=policy_slots)
    reg, policy_id = create_admitted_registration(policy_id=policy["id"], due_date=due_date)
    newborn = record_birth(reg["id"], **birth_overrides)
    return newborn, reg["id"], policy_id


def get_newborn_version(newborn_id, headers=NEO):
    """Read a newborn's current version (used to feed the OCC guard)."""
    return get_success_data(api_client.get_newborn(newborn_id, headers))["version"]


def get_policy_version(policy_id):
    """Read a policy's current version (used to feed the OCC guard on approve)."""
    return get_success_data(api_client.get_insurance_policy(policy_id, BENEFITS))["version"]


# --- Tier 3: NICU escalation / bed lifecycle ---

def escalate(newborn_id, required_level="LEVEL_3", admitted_at="2026-03-05T11:00:00Z",
             expected_version=None):
    """Escalate a newborn to the NICU (OCC-guarded). Reads the current version first
    when expected_version is not supplied. Returns the created NicuStay."""
    if expected_version is None:
        expected_version = get_newborn_version(newborn_id)
    payload = f.nicu_escalate_payload(
        expected_version, required_level=required_level, admitted_at=admitted_at)
    return get_success_data(api_client.nicu_escalate(newborn_id, payload, NEO))


def setup_escalated_active(required_level="LEVEL_3", bed_acuity="LEVEL_3",
                           admitted_at="2026-03-05T09:00:00Z", weight_grams=1500,
                           gestational_age_weeks=31, apgar_5min=9):
    """One bed + one newborn meeting NICU criteria, escalated onto the bed (ACTIVE).

    Returns (newborn, stay, bed). Used by step-down conservation/cascade tests.
    """
    bed = create_bed(acuity_level=bed_acuity)
    newborn, reg_id, _ = setup_admitted_with_newborn(
        weight_grams=weight_grams, gestational_age_weeks=gestational_age_weeks,
        apgar_5min=apgar_5min, birth_datetime="2026-03-05T08:30:00Z")
    stay = escalate(newborn["id"], required_level=required_level, admitted_at=admitted_at)
    bed = get_success_data(api_client.get_nicu_bed(bed["id"], NEO))
    return newborn, stay, bed


# --- Tier 4/5: full clinical happy-path to DISCHARGE_READY and to DISCHARGED ---

def setup_discharge_ready(weight_grams=3200, gestational_age_weeks=39, apgar_5min=9,
                          legal_name="Baby Doe", with_feeding=True, with_birth_cert=True,
                          with_issued_bag=True, bag_line_items=None,
                          birth_datetime="2026-03-05T10:00:00Z", due_date="2026-03-12"):
    """Walk a healthy newborn to DISCHARGE_READY.

    Builds: policy + ADMITTED registration + BORN newborn -> room-in -> (optional
    feeding-adequate consult) -> (optional issued non-medication bag) -> (optional
    SUBMITTED birth-cert filing) -> mark-discharge-ready.

    Returns a dict with keys: newborn_id, reg_id, policy_id, bag_id, bc_filing_id,
    consult_id (any may be None when its flag is False).

    Pins a build clock at birth_datetime + 2h so the birth-certificate filing is
    submitted before its +5-day deadline (PRD §3.7) — an on-time SUBMITTED filing
    is what the discharge prerequisite (PRD §3.8) requires. Callers that need a
    later instant for the action under test re-pin the clock themselves.
    """
    set_clock(_birth_plus(birth_datetime, hours=2))
    newborn, reg_id, policy_id = setup_admitted_with_newborn(
        due_date=due_date, weight_grams=weight_grams,
        gestational_age_weeks=gestational_age_weeks, apgar_5min=apgar_5min,
        legal_name=legal_name, birth_datetime=birth_datetime)
    nb_id = newborn["id"]
    get_success_data(api_client.room_in(nb_id, NURSE))

    consult_id = None
    if with_feeding:
        consult = get_success_data(api_client.create_lactation_consult(
            f.create_lactation_consult_payload(nb_id, "2026-03-05T11:00:00Z"), NURSE))
        consult_id = consult["id"]
        get_success_data(api_client.complete_lactation_consult(
            consult_id, f.complete_consult_payload(8), NURSE))

    bag_id = None
    if with_issued_bag:
        if bag_line_items is None:
            bag_line_items = [{"sku": "FORM-A", "category": "FORMULA",
                               "qty": 2, "unit_value_cents": 1299}]
        bag = get_success_data(api_client.create_discharge_bag(
            f.create_discharge_bag_payload(nb_id, line_items=bag_line_items), NURSE))
        bag_id = bag["id"]
        get_success_data(api_client.assemble_discharge_bag(bag_id, NURSE))
        get_success_data(api_client.issue_discharge_bag(bag_id, NURSE))

    bc_filing_id = None
    if with_birth_cert:
        bc = get_success_data(api_client.create_government_filing(
            f.create_government_filing_payload(nb_id, "BIRTH_CERTIFICATE"), VITAL))
        bc_filing_id = bc["id"]
        get_success_data(api_client.submit_filing(bc_filing_id, VITAL))

    get_success_data(api_client.mark_discharge_ready(nb_id, NURSE))
    return {
        "newborn_id": nb_id, "reg_id": reg_id, "policy_id": policy_id,
        "bag_id": bag_id, "bc_filing_id": bc_filing_id, "consult_id": consult_id,
    }


def setup_discharged(discharge_clock="2026-03-10T08:00:00Z", **ready_overrides):
    """Full happy path through DISCHARGED. Advances the clock to discharge_clock
    immediately before the discharge call so the spawned follow-up due_at values are
    anchored to that instant. Returns the same dict as setup_discharge_ready."""
    ctx = setup_discharge_ready(**ready_overrides)
    set_clock(discharge_clock)
    get_success_data(api_client.discharge(ctx["newborn_id"], NURSE))
    return ctx


def get_followup_task(newborn_id, task_type):
    """Fetch a specific follow-up task for a newborn by its task_type filter. Returns
    the task dict (or None when absent)."""
    data, _ = _list_followups(newborn_id, task_type)
    return data[0] if data else None


def _list_followups(newborn_id, task_type=None):
    from prd_bench_local_runner.testing import validate_paginated
    params = {"newborn_id": newborn_id}
    if task_type is not None:
        params["task_type"] = task_type
    resp = api_client.list_follow_up_tasks(NURSE, params=params)
    return validate_paginated(resp)


# --- Dependent-enrollment helpers ---

def create_enrollment(newborn_id, policy_id, requested_at):
    """Create a PENDING dependent enrollment. Returns the enrollment dict."""
    return get_success_data(api_client.create_dependent_enrollment(
        f.create_dependent_enrollment_payload(newborn_id, policy_id, requested_at), BENEFITS))


def approve_enrollment(enrollment_id, policy_id, expected_version=None):
    """Approve an enrollment under the policy's current version (read if not supplied)."""
    if expected_version is None:
        expected_version = get_policy_version(policy_id)
    return get_success_data(api_client.approve_enrollment(
        enrollment_id, f.approve_enrollment_payload(expected_version), BENEFITS))


# --- Government-filing helpers ---

def create_birth_cert(newborn_id):
    """Create a PENDING BIRTH_CERTIFICATE filing. Returns the filing dict."""
    return get_success_data(api_client.create_government_filing(
        f.create_government_filing_payload(newborn_id, "BIRTH_CERTIFICATE"), VITAL))


def create_ssn_filing(newborn_id):
    """Create a PENDING SSN_APPLICATION filing. Returns the filing dict."""
    return get_success_data(api_client.create_government_filing(
        f.create_government_filing_payload(newborn_id, "SSN_APPLICATION"), VITAL))
