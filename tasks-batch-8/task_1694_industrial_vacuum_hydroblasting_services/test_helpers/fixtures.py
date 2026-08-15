"""Composite setup helpers.

Each helper builds a multi-entity scenario from scratch against an empty
database (the harness restarts the server before every test). Setup calls use
the lenient get_success_data() validator so failures surface as clear
"Setup step failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_containment_payload,
    create_disposal_facility_payload,
    create_downtime_payload,
    create_equipment_assignment_payload,
    create_equipment_unit_payload,
    create_incident_payload,
    create_jha_payload,
    create_job_payload,
    create_manifest_payload,
    create_operator_assignment_payload,
    create_operator_payload,
    create_permit_payload,
    create_pressure_plan_jha_payload,
    create_rate_schedule_payload,
    create_site_payload,
    create_waste_profile_payload,
)
from .test_users import TEST_USERS

AM = TEST_USERS["account_manager_headers"]
PM = TEST_USERS["project_manager_headers"]
PA = TEST_USERS["platform_admin_headers"]
FS = TEST_USERS["field_supervisor_headers"]
SM = TEST_USERS["safety_manager_headers"]
CO = TEST_USERS["compliance_officer_headers"]
EA = TEST_USERS["environmental_approver_headers"]


# ---------------------------------------------------------------------------
# Tier 1: commercial spine (site + ACTIVE rate schedule)
# ---------------------------------------------------------------------------

def create_site_with_active_schedule(schedule_overrides=None, site_overrides=None):
    """Create a site plus one rate schedule, activate it. Returns (site, schedule)."""
    site = get_success_data(api_client.create_site(create_site_payload(**(site_overrides or {})), AM))
    sched = get_success_data(
        api_client.create_rate_schedule(
            create_rate_schedule_payload(site["id"], **(schedule_overrides or {})), AM
        )
    )
    get_success_data(
        api_client.activate_rate_schedule(
            sched["id"], {"expected_site_version": site["version"]}, AM
        )
    )
    return site, sched


def create_equipment_unit(**overrides):
    return get_success_data(
        api_client.create_equipment_unit(create_equipment_unit_payload(**overrides), PA)
    )


def create_operator(**overrides):
    return get_success_data(
        api_client.create_operator(create_operator_payload(**overrides), PA)
    )


def create_job(site_id, **overrides):
    return get_success_data(api_client.create_job(create_job_payload(site_id, **overrides), PM))


def create_confirmed_equipment_assignment(job_id, unit_id, **overrides):
    """Create an equipment assignment and confirm it. Returns the assignment."""
    asg = get_success_data(
        api_client.create_assignment(
            create_equipment_assignment_payload(job_id, unit_id, **overrides), PM
        )
    )
    return get_success_data(api_client.confirm_assignment(asg["id"], PM))


def create_confirmed_operator_assignment(job_id, operator_id, **overrides):
    asg = get_success_data(
        api_client.create_assignment(
            create_operator_assignment_payload(job_id, operator_id, **overrides), PM
        )
    )
    return get_success_data(api_client.confirm_assignment(asg["id"], PM))


def schedule_and_mobilize(job_id):
    get_success_data(api_client.schedule_job(job_id, PM))
    return get_success_data(api_client.mobilize_job(job_id, PM))


# ---------------------------------------------------------------------------
# Tier 2: JHA approval flows (OCC on Job.version)
# ---------------------------------------------------------------------------

def create_submit_approve_jha(job_id, jha_overrides=None, pressure_plan=False):
    """Create -> submit -> approve a JHA. Returns the APPROVED JHA.

    Re-reads the job's version immediately before approval to satisfy OCC.
    """
    if pressure_plan:
        payload = create_pressure_plan_jha_payload(job_id, **(jha_overrides or {}))
    else:
        payload = create_jha_payload(job_id, **(jha_overrides or {}))
    jha = get_success_data(api_client.create_jha(payload, FS))
    get_success_data(api_client.submit_jha(jha["id"], FS))
    job = get_success_data(api_client.get_job(job_id, PM))
    return get_success_data(
        api_client.approve_jha(jha["id"], {"expected_job_version": job["version"]}, SM)
    )


# ---------------------------------------------------------------------------
# Tier 3: full lifecycle shortcuts
# ---------------------------------------------------------------------------

def create_job_in_progress(
    job_overrides=None,
    schedule_overrides=None,
    jha_overrides=None,
    pressure_plan=False,
    confined_space_permit=False,
    crew="equipment",
):
    """Site + ACTIVE schedule + job walked to IN_PROGRESS with approved JHA.

    crew: "equipment" (one COMBO unit), "operator" (one hydroblast-certified
    operator + one COMBO unit), or "both".
    Returns dict of the created entities.
    """
    site, sched = create_site_with_active_schedule(schedule_overrides)
    unit = create_equipment_unit(unit_type="COMBO", max_pressure_psi=10000, unit_code="COMBO-01")
    job = create_job(site["id"], **(job_overrides or {}))

    asg_eq = create_confirmed_equipment_assignment(job["id"], unit["id"])
    result = {
        "site": site, "schedule": sched, "unit": unit, "job": job, "asg_equipment": asg_eq,
    }
    if crew in ("operator", "both"):
        op = create_operator(
            full_name="Ollie Otis", employee_ref="E-100", hydroblast_certified=True
        )
        asg_op = create_confirmed_operator_assignment(job["id"], op["id"])
        result.update({"operator": op, "asg_operator": asg_op})

    schedule_and_mobilize(job["id"])
    jha = create_submit_approve_jha(
        job["id"], jha_overrides=jha_overrides, pressure_plan=pressure_plan
    )
    result["jha"] = jha

    if confined_space_permit:
        permit = get_success_data(
            api_client.create_permit(
                create_permit_payload(
                    job["id"], permit_type="CONFINED_SPACE", space_id="T-101"
                ),
                FS,
            )
        )
        get_success_data(api_client.activate_permit(permit["id"], FS))
        result["permit"] = permit

    job_after = get_success_data(api_client.start_work(job["id"], PM))
    result["job"] = job_after
    return result


def verify_containment(job_id, used=500, captured=500):
    """Log a containment record on the job and verify it. Returns the record."""
    rec = get_success_data(
        api_client.create_containment_record(
            create_containment_payload(job_id, water_used_gallons=used,
                                       water_captured_gallons=captured),
            FS,
        )
    )
    return get_success_data(api_client.verify_containment_record(rec["id"], PM))


def complete_field_work(job_id, gallons=1000, feet=0):
    return get_success_data(
        api_client.complete_field_work(
            job_id, {"gallons_removed": gallons, "feet_cleaned": feet}, PM
        )
    )


def create_job_field_complete(
    job_overrides=None,
    schedule_overrides=None,
    jha_overrides=None,
    pressure_plan=False,
    gallons=1000,
    feet=0,
    crew="equipment",
):
    """Job walked all the way to FIELD_COMPLETE. Returns scenario dict."""
    ctx = create_job_in_progress(
        job_overrides=job_overrides,
        schedule_overrides=schedule_overrides,
        jha_overrides=jha_overrides,
        pressure_plan=pressure_plan,
        crew=crew,
    )
    ctx["containment"] = verify_containment(ctx["job"]["id"])
    ctx["job"] = complete_field_work(ctx["job"]["id"], gallons=gallons, feet=feet)
    return ctx


def create_invoiced_job(**kwargs):
    """Job walked to INVOICED with a generated DRAFT invoice. Returns ctx with
    ctx["invoice"]."""
    ctx = create_job_field_complete(**kwargs)
    invoice = get_success_data(api_client.generate_invoice(ctx["job"]["id"], PM))
    ctx["invoice"] = invoice
    ctx["job"] = get_success_data(api_client.get_job(ctx["job"]["id"], PM))
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: waste chain (facility + APPROVED profile + manifest helpers)
# ---------------------------------------------------------------------------

def create_facility_and_approved_profile(site_id, profile_overrides=None,
                                          facility_overrides=None):
    """Create a disposal facility and an APPROVED waste profile on the site."""
    facility = get_success_data(
        api_client.create_disposal_facility(
            create_disposal_facility_payload(**(facility_overrides or {})), PA
        )
    )
    profile = get_success_data(
        api_client.create_waste_profile(
            create_waste_profile_payload(site_id, facility["id"], **(profile_overrides or {})),
            CO,
        )
    )
    get_success_data(api_client.submit_waste_profile(profile["id"], CO))
    profile = get_success_data(api_client.approve_waste_profile(profile["id"], EA))
    return facility, profile


def create_manifest(job_id, profile_id, gallons=1000):
    return get_success_data(
        api_client.create_manifest(
            create_manifest_payload(job_id, profile_id, estimated_gallons=gallons), PM
        )
    )


def create_issued_manifest(job_id, profile_id, gallons=1000):
    manifest = create_manifest(job_id, profile_id, gallons)
    return get_success_data(api_client.issue_manifest(manifest["id"], PM))


# ---------------------------------------------------------------------------
# Tier 5: downtime helpers (logical clock driven)
# ---------------------------------------------------------------------------

def open_and_close_downtime(job_id, close_clock_iso, cause="CUSTOMER_DELAY"):
    """Open a downtime event (at current clock), advance the clock, close it."""
    event = get_success_data(
        api_client.create_downtime_event(
            create_downtime_payload(job_id, cause=cause), FS
        )
    )
    get_success_data(api_client.set_clock(close_clock_iso, PA))
    return get_success_data(api_client.close_downtime_event(event["id"], FS))
