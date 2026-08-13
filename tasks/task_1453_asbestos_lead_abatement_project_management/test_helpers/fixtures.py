"""Composite setup helpers.

Every helper builds preconditions from scratch using only PRD-declared
endpoints (each test runs against a freshly restarted server whose logical
clock reads exactly 2026-08-01T00:00:00Z). Setup calls use get_success_data so
failures surface as clear "Setup failed" errors. Identity threading: any
Supervisor call passes the acting Worker's id; any FacilityOperator call
passes the acting DisposalFacility's id.

The composite fixtures build the canonical lifecycle chain:
  project -> survey+sample -> submit -> result -> finalize (project ASSESSED)
  -> supervisor worker -> containment create/install/verify
  -> notification file (+acknowledge) -> supervisor coverage assignment
  -> clock advance -> start-abatement (IN_PROGRESS)
  -> complete-work (AWAITING_CLEARANCE)
  -> two PASS clearance tests (reoccupancy OPEN) -> close (CLOSED)
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_air_test_payload,
    create_assignment_payload,
    create_containment_payload,
    create_facility_payload,
    create_manifest_payload,
    create_notification_payload,
    create_project_payload,
    create_relocation_payload,
    create_relocation_unit_payload,
    create_sample_payload,
    create_sample_result_payload,
    create_survey_payload,
    create_worker_payload,
)
from .test_users import (
    TEST_USERS,
    make_facility_operator_headers,
    make_supervisor_headers,
)

ADMIN = TEST_USERS["contractor_admin_headers"]
IH = TEST_USERS["industrial_hygienist_headers"]
REG = TEST_USERS["regulator_clerk_headers"]

FUTURE_EXPIRY = "2027-01-01T00:00:00Z"
WORK_START_CLOCK = "2026-08-11T00:00:00Z"
COVERAGE_START = "2026-08-01T00:00:00Z"
COVERAGE_END = "2026-09-01T00:00:00Z"


def _fail(step, resp):
    raise AssertionError(
        f"Setup failed at {step}: HTTP {resp.status_code} {resp.text}"
    )


def _ok(step, resp, expected=None):
    data = get_success_data(resp)
    if expected is not None and isinstance(data, dict):
        status = data.get("status")
        assert status == expected, (
            f"Setup failed at {step}: expected status {expected}, got {status}"
        )
    return data


# ---------------------------------------------------------------------------
# Primitive step helpers (single endpoint each)
# ---------------------------------------------------------------------------

def set_clock(to_iso8601):
    resp = api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN)
    return _ok("set_clock", resp)


def create_project_entity(name="P-1", **overrides):
    resp = api_client.create_project(
        create_project_payload(name=name, **overrides), ADMIN)
    return _ok("create_project", resp)


def get_project(project_id):
    return _ok("get_project", api_client.get_project(project_id, ADMIN))


def create_survey_entity(project_id, **overrides):
    resp = api_client.create_survey(
        create_survey_payload(project_id, **overrides), ADMIN)
    return _ok("create_survey", resp)


def get_survey(survey_id):
    return _ok("get_survey", api_client.get_survey(survey_id, ADMIN))


def list_samples(survey_id, params=None):
    return _ok("list_samples",
               api_client.list_samples(survey_id, ADMIN, params=params))


def add_sample(survey_id, **overrides):
    resp = api_client.create_sample(
        create_sample_payload(survey_id, **overrides), ADMIN)
    return _ok("add_sample", resp)


def submit_survey(survey_id):
    return _ok("submit_survey", api_client.submit_survey(survey_id, ADMIN),
               expected="IN_LAB")


def report_sample(sample_id, lab_result="POSITIVE", asbestos_pct=40,
                  headers=None, **overrides):
    payload = create_sample_result_payload(
        lab_result=lab_result, asbestos_pct=asbestos_pct, **overrides)
    if lab_result != "POSITIVE" and "asbestos_pct" not in overrides:
        payload.pop("asbestos_pct", None)
    resp = api_client.record_sample_result(sample_id, payload,
                                           headers or IH)
    return _ok("report_sample", resp, expected="REPORTED")


def finalize_survey(survey_id):
    return _ok("finalize_survey", api_client.finalize_survey(survey_id, ADMIN),
               expected="FINALIZED")


def create_worker_entity(full_name="Worker One", certification_level="SUPERVISOR",
                         cert_expires_at=FUTURE_EXPIRY,
                         medical_clearance_expires_at=FUTURE_EXPIRY,
                         respirator_fit_expires_at=FUTURE_EXPIRY, **overrides):
    resp = api_client.create_worker(
        create_worker_payload(
            full_name=full_name, certification_level=certification_level,
            cert_expires_at=cert_expires_at,
            medical_clearance_expires_at=medical_clearance_expires_at,
            respirator_fit_expires_at=respirator_fit_expires_at, **overrides),
        ADMIN)
    return _ok("create_worker", resp)


def get_worker(worker_id):
    return _ok("get_worker", api_client.get_worker(worker_id, ADMIN))


def list_worker_assignments(worker_id):
    return _ok("list_worker_assignments",
               api_client.list_worker_assignments(worker_id, ADMIN))


def supervisor_headers(worker):
    """Identity-correct headers for a Supervisor acting as `worker`."""
    return make_supervisor_headers(worker["id"])


def create_containment_entity(project_id, supervisor_id,
                              work_area_volume_cuft=240_000,
                              containment_class="FULL"):
    resp = api_client.create_containment(
        create_containment_payload(
            project_id, work_area_volume_cuft=work_area_volume_cuft,
            containment_class=containment_class),
        make_supervisor_headers(supervisor_id))
    return _ok("create_containment", resp)


def list_project_containments(project_id):
    return _ok("list_project_containments",
               api_client.list_project_containments(project_id, ADMIN))


def install_containment(containment_id, supervisor_id):
    return _ok("install_containment",
               api_client.install_containment(
                   containment_id, make_supervisor_headers(supervisor_id)),
               expected="INSTALLED")


def verify_containment(containment_id, supervisor_id, pressure=-0.03):
    return _ok("verify_containment",
               api_client.verify_containment(
                   containment_id, {"pressure_reading_inwg": pressure},
                   make_supervisor_headers(supervisor_id)),
               expected="VERIFIED")


def revise_containment(containment_id, supervisor_id, expected_version,
                       **fields):
    payload = dict(fields)
    payload["expected_containment_version"] = expected_version
    return _ok("revise_containment",
               api_client.revise_containment(
                   containment_id, payload,
                   make_supervisor_headers(supervisor_id)))


def file_notification(project_id, notification_type="INITIAL",
                      declared_acm_sq_ft=100, expected_project_version=None):
    """File a notification; reads the project version when not supplied."""
    if expected_project_version is None:
        expected_project_version = get_project(project_id)["version"]
    resp = api_client.create_notification(
        create_notification_payload(
            project_id, expected_project_version,
            notification_type=notification_type,
            declared_acm_sq_ft=declared_acm_sq_ft),
        ADMIN)
    return _ok("file_notification", resp)


def acknowledge_notification(notification_id):
    return _ok("acknowledge_notification",
               api_client.acknowledge_notification(notification_id, REG),
               expected="ACKNOWLEDGED")


def list_project_notifications(project_id):
    return _ok("list_project_notifications",
               api_client.list_project_notifications(project_id, ADMIN))


def create_assignment_entity(project_id, worker_id,
                             role_on_site="HANDLER",
                             start_at="2026-08-11T00:00:00Z",
                             end_at="2026-08-20T00:00:00Z",
                             headers=None):
    resp = api_client.create_assignment(
        create_assignment_payload(
            project_id, worker_id, role_on_site=role_on_site,
            start_at=start_at, end_at=end_at),
        headers or ADMIN)
    return _ok("create_assignment", resp)


def cancel_assignment(assignment_id, headers=None):
    return _ok("cancel_assignment",
               api_client.cancel_assignment(assignment_id, headers or ADMIN),
               expected="CANCELLED")


def create_air_test_entity(project_id, phase, collected_at, headers):
    resp = api_client.create_air_test(
        create_air_test_payload(project_id, phase, collected_at), headers)
    return _ok("create_air_test", resp)


def list_project_air_tests(project_id, params=None):
    return _ok("list_project_air_tests",
               api_client.list_project_air_tests(project_id, ADMIN,
                                                 params=params))


def report_air_test(air_test_id, result_f_cc, headers=None):
    return _ok("report_air_test",
               api_client.record_air_test_result(
                   air_test_id, {"result_f_cc": result_f_cc}, headers or IH),
               expected="REPORTED")


def create_facility_entity(name="Fac A", epa_id="EPA-1",
                           accepted_hazards=("ASBESTOS",),
                           monthly_capacity_tons=50):
    resp = api_client.create_facility(
        create_facility_payload(
            name=name, epa_id=epa_id,
            accepted_hazards=list(accepted_hazards),
            monthly_capacity_tons=monthly_capacity_tons),
        ADMIN)
    return _ok("create_facility", resp)


def get_facility(facility_id):
    return _ok("get_facility", api_client.get_facility(facility_id, ADMIN))


def create_manifest_entity(project_id, facility_id, supervisor_id,
                           bags_count=2, gross_weight_lbs=100):
    resp = api_client.create_manifest(
        create_manifest_payload(
            project_id, facility_id, bags_count=bags_count,
            gross_weight_lbs=gross_weight_lbs),
        make_supervisor_headers(supervisor_id))
    return _ok("create_manifest", resp)


def list_project_manifests(project_id, params=None):
    return _ok("list_project_manifests",
               api_client.list_project_manifests(project_id, ADMIN,
                                                 params=params))


def seal_manifest(manifest_id, supervisor_id):
    return _ok("seal_manifest",
               api_client.seal_manifest(
                   manifest_id, make_supervisor_headers(supervisor_id)),
               expected="SEALED")


def ship_manifest(manifest_id, supervisor_id):
    return _ok("ship_manifest",
               api_client.ship_manifest(
                   manifest_id, make_supervisor_headers(supervisor_id)),
               expected="IN_TRANSIT")


def deliver_manifest(manifest_id, facility_id):
    return _ok("deliver_manifest",
               api_client.deliver_manifest(
                   manifest_id, make_facility_operator_headers(facility_id)),
               expected="DELIVERED")


def confirm_manifest(manifest_id, facility_id):
    return _ok("confirm_manifest",
               api_client.confirm_manifest(
                   manifest_id, make_facility_operator_headers(facility_id)),
               expected="CONFIRMED")


def reject_manifest(manifest_id, facility_id, reason="REJECTED_AT_FACILITY"):
    return _ok("reject_manifest",
               api_client.reject_manifest(
                   manifest_id, {"reason": reason},
                   make_facility_operator_headers(facility_id)),
               expected="REJECTED")


def void_manifest(manifest_id, headers=None):
    return _ok("void_manifest",
               api_client.void_manifest(manifest_id, headers or ADMIN),
               expected="VOIDED")


def create_unit_entity(unit_label="U1", capacity_persons=4):
    resp = api_client.create_relocation_unit(
        create_relocation_unit_payload(
            unit_label=unit_label, capacity_persons=capacity_persons),
        ADMIN)
    return _ok("create_relocation_unit", resp)


def get_unit(unit_id):
    return _ok("get_relocation_unit",
               api_client.get_relocation_unit(unit_id, ADMIN))


def create_relocation_entity(project_id, unit_id, household_name="Household H",
                             persons=3, move_out_at="2026-08-10T00:00:00Z"):
    resp = api_client.create_relocation(
        create_relocation_payload(
            project_id, unit_id, household_name=household_name,
            persons=persons, move_out_at=move_out_at),
        ADMIN)
    return _ok("create_relocation", resp)


def list_project_relocations(project_id):
    return _ok("list_project_relocations",
               api_client.list_project_relocations(project_id, ADMIN))


def return_relocation(relocation_id):
    return _ok("return_relocation",
               api_client.return_relocation(relocation_id, ADMIN),
               expected="RETURNED")


# ---------------------------------------------------------------------------
# Composite fixtures — lifecycle chains
# ---------------------------------------------------------------------------

def setup_assessed_project(name="P", hazard_class="ASBESTOS",
                           base_abatement_cost_cents=5_000_000,
                           site_address="1 Elm St", sample_qty=100,
                           friable=True):
    """Project -> survey -> one POSITIVE sample -> submit -> result ->
    finalize. Returns ctx with the project now ASSESSED."""
    project = create_project_entity(
        name=name, site_address=site_address, hazard_class=hazard_class,
        base_abatement_cost_cents=base_abatement_cost_cents)
    survey = create_survey_entity(project["id"])
    sample = add_sample(survey["id"], quantity_sq_ft=sample_qty,
                        friable=friable)
    submit_survey(survey["id"])
    report_sample(sample["id"])
    survey = finalize_survey(survey["id"])
    project = get_project(project["id"])
    assert project["status"] == "ASSESSED", "setup must reach ASSESSED"
    return {"project": project, "survey": survey, "sample": sample}


def add_supervisor(full_name="Sup One", **worker_kw):
    """Register a SUPERVISOR-level worker with far-future expiries."""
    worker_kw.setdefault("certification_level", "SUPERVISOR")
    return create_worker_entity(full_name=full_name, **worker_kw)


def setup_verified_containment(project_id, supervisor_id,
                               work_area_volume_cuft=240_000,
                               containment_class="FULL", pressure=-0.03):
    """Containment create -> install -> verify. Returns VERIFIED containment."""
    containment = create_containment_entity(
        project_id, supervisor_id,
        work_area_volume_cuft=work_area_volume_cuft,
        containment_class=containment_class)
    install_containment(containment["id"], supervisor_id)
    return verify_containment(containment["id"], supervisor_id, pressure)


def setup_acknowledged_notification(project_id, notification_type="INITIAL",
                                    declared_acm_sq_ft=100):
    """File + acknowledge a notification. Returns the ACKNOWLEDGED record."""
    notification = file_notification(
        project_id, notification_type=notification_type,
        declared_acm_sq_ft=declared_acm_sq_ft)
    return acknowledge_notification(notification["id"])


def setup_supervisor_coverage(project_id, supervisor_id,
                              start_at=COVERAGE_START, end_at=COVERAGE_END):
    """A SCHEDULED SUPERVISOR assignment whose window covers the start."""
    return create_assignment_entity(
        project_id, supervisor_id, role_on_site="SUPERVISOR",
        start_at=start_at, end_at=end_at,
        headers=make_supervisor_headers(supervisor_id))


def setup_start_ready_project(name="P-READY", notification_type="INITIAL",
                              declared_acm_sq_ft=100, **project_kw):
    """ASSESSED project + supervisor worker + VERIFIED containment +
    ACKNOWLEDGED notification + SCHEDULED supervisor coverage.

    The clock is NOT advanced and abatement is NOT started."""
    ctx = setup_assessed_project(name=name, **project_kw)
    ctx["supervisor"] = add_supervisor()
    ctx["containment"] = setup_verified_containment(
        ctx["project"]["id"], ctx["supervisor"]["id"])
    ctx["notification"] = setup_acknowledged_notification(
        ctx["project"]["id"], notification_type=notification_type,
        declared_acm_sq_ft=declared_acm_sq_ft)
    ctx["assignment"] = setup_supervisor_coverage(
        ctx["project"]["id"], ctx["supervisor"]["id"])
    return ctx


def start_project(ctx, clock=WORK_START_CLOCK):
    """Advance the logical clock and start abatement. Project -> IN_PROGRESS."""
    set_clock(clock)
    project = _ok("start_abatement",
                  api_client.start_abatement(ctx["project"]["id"], ADMIN),
                  expected="IN_PROGRESS")
    ctx["project"] = project
    return project


def setup_in_progress_project(name="P-PROG", clock=WORK_START_CLOCK,
                              **kwargs):
    """Start-ready chain + clock advance + start-abatement (IN_PROGRESS)."""
    ctx = setup_start_ready_project(name=name, **kwargs)
    start_project(ctx, clock=clock)
    return ctx


def complete_work(ctx):
    """Supervisor completes the work phase. Project -> AWAITING_CLEARANCE."""
    project = _ok("complete_work",
                  api_client.complete_work(
                      ctx["project"]["id"],
                      supervisor_headers(ctx["supervisor"])),
                  expected="AWAITING_CLEARANCE")
    ctx["project"] = project
    return project


def setup_awaiting_clearance_project(name="P-AWAIT", clock=WORK_START_CLOCK,
                                     **kwargs):
    """IN_PROGRESS chain + complete-work (AWAITING_CLEARANCE)."""
    ctx = setup_in_progress_project(name=name, clock=clock, **kwargs)
    complete_work(ctx)
    return ctx


def record_clearance_result(ctx, collected_at, result_f_cc, headers=None):
    """Hygienist collects + reports a CLEARANCE test. Returns the REPORTED
    air test."""
    test = create_air_test_entity(
        ctx["project"]["id"], "CLEARANCE", collected_at, headers or IH)
    return report_air_test(test["id"], result_f_cc, headers=headers)


def setup_open_reoccupancy_project(name="P-OPEN", clock=WORK_START_CLOCK,
                                   pass_readings=(0.008, 0.009),
                                   collected=("2026-08-12T08:00:00Z",
                                              "2026-08-12T09:00:00Z"),
                                   **kwargs):
    """AWAITING_CLEARANCE chain + two PASS clearance tests collected after the
    containment's last_verified_at, so reoccupancy_status is OPEN."""
    ctx = setup_awaiting_clearance_project(name=name, clock=clock, **kwargs)
    ctx["clearance_tests"] = [
        record_clearance_result(ctx, collected[0], pass_readings[0]),
        record_clearance_result(ctx, collected[1], pass_readings[1]),
    ]
    ctx["project"] = get_project(ctx["project"]["id"])
    assert ctx["project"]["reoccupancy_status"] == "OPEN", \
        "setup must reach reoccupancy OPEN"
    return ctx


def setup_closed_project(name="P-CLOSED", clock=WORK_START_CLOCK, **kwargs):
    """Full lifecycle through CLOSED (no manifests, no relocations)."""
    ctx = setup_open_reoccupancy_project(name=name, clock=clock, **kwargs)
    project = _ok("close_project",
                  api_client.close_project(ctx["project"]["id"], ADMIN),
                  expected="CLOSED")
    ctx["project"] = project
    return ctx


# ---------------------------------------------------------------------------
# Manifest lifecycle helpers
# ---------------------------------------------------------------------------

def setup_in_progress_with_facility(name="P-FAC", capacity_tons=50,
                                    accepted_hazards=("ASBESTOS",),
                                    **kwargs):
    """IN_PROGRESS chain + registered facility."""
    ctx = setup_in_progress_project(name=name, **kwargs)
    ctx["facility"] = create_facility_entity(
        accepted_hazards=accepted_hazards, monthly_capacity_tons=capacity_tons)
    return ctx


def create_sealed_manifest(ctx, bags_count=2, gross_weight_lbs=100):
    """Create + seal a manifest against the ctx project/facility/supervisor."""
    manifest = create_manifest_entity(
        ctx["project"]["id"], ctx["facility"]["id"], ctx["supervisor"]["id"],
        bags_count=bags_count, gross_weight_lbs=gross_weight_lbs)
    return seal_manifest(manifest["id"], ctx["supervisor"]["id"])


def create_shipped_manifest(ctx, bags_count=2, gross_weight_lbs=100):
    """Create + seal + ship a manifest (IN_TRANSIT)."""
    manifest = create_sealed_manifest(
        ctx, bags_count=bags_count, gross_weight_lbs=gross_weight_lbs)
    return ship_manifest(manifest["id"], ctx["supervisor"]["id"])


def create_confirmed_manifest(ctx, bags_count=2, gross_weight_lbs=100):
    """Create + seal + ship + deliver + confirm a manifest (CONFIRMED)."""
    manifest = create_shipped_manifest(
        ctx, bags_count=bags_count, gross_weight_lbs=gross_weight_lbs)
    deliver_manifest(manifest["id"], ctx["facility"]["id"])
    return confirm_manifest(manifest["id"], ctx["facility"]["id"])
