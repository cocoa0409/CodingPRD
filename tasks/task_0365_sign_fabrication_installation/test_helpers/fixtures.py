"""Composite setup helpers for multi-step test prerequisites.

Most interesting claims in this PRD require the project to be walked deep into
its lifecycle (DESIGN -> ESTIMATING -> PERMITTING -> FABRICATION -> INSTALL ->
WARRANTY -> CLOSED), which takes 8-20 API calls. These helpers encapsulate the
common prefixes so test bodies focus on the assertion under test.

All helpers use get_success_data() (lenient) for setup calls so a broken
precondition surfaces as a clear "Setup failed" rather than a confusing
assertion mismatch. Because the runner restarts the server (empty DB) before
every test, every helper builds its preconditions from scratch.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_sign_project_payload, create_art_proof_payload, create_estimate_payload,
    create_site_survey_payload, create_permit_payload, create_crew_payload,
    create_equipment_payload, create_install_job_payload, create_change_order_payload,
    create_warranty_claim_payload, create_reorder_payload,
)
from .test_users import TEST_USERS

SM = TEST_USERS["shop_manager_headers"]
DES = TEST_USERS["designer_headers"]
CUST = TEST_USERS["customer_headers"]
SURV = TEST_USERS["surveyor_headers"]
PC = TEST_USERS["permit_clerk_headers"]


# ─── Clock control ───────────────────────────────────────────────────────────

def set_clock(iso: str):
    """Set the server's logical UTC clock (PRD §3.9)."""
    return get_success_data(api_client.set_clock({"to_iso8601": iso}, SM))


# ─── Crew / equipment registration ───────────────────────────────────────────

def register_crew(name="Test Crew", certified_aerial=True, active=True):
    return get_success_data(api_client.create_crew(
        create_crew_payload(name=name, certified_aerial=certified_aerial, active=active), SM))


def register_equipment(asset_tag="EQ-1", equipment_class="BUCKET_TRUCK",
                       max_reach_ft=40, in_service=True):
    return get_success_data(api_client.create_equipment(
        create_equipment_payload(asset_tag=asset_tag, equipment_class=equipment_class,
                                 max_reach_ft=max_reach_ft, in_service=in_service), SM))


# ─── Tier 1: project to a given phase ────────────────────────────────────────

def create_project(**proj_overrides):
    """Create a fresh DESIGN project."""
    return get_success_data(api_client.create_sign_project(
        create_sign_project_payload(**proj_overrides), SM))


def create_project_with_approved_proof(color_count=3, **proj_overrides):
    """ESTIMATING project + one APPROVED art proof. Returns (project, proof)."""
    project = create_project(**proj_overrides)
    proof = get_success_data(api_client.create_art_proof(
        project["id"], create_art_proof_payload(color_count=color_count), DES))
    api_client.submit_art_proof(project["id"], proof["id"], DES)
    proof = get_success_data(api_client.decide_art_proof(
        project["id"], proof["id"], {"decision": "APPROVE"}, CUST))
    project = get_success_data(api_client.get_sign_project(project["id"], SM))
    return project, proof


def create_sent_estimate(color_count=3, substrate="ALUMINUM",
                         valid_until_iso=None, **proj_overrides):
    """ESTIMATING project + APPROVED proof + one SENT estimate.

    Returns (project, proof, estimate)."""
    project, proof = create_project_with_approved_proof(color_count=color_count, **proj_overrides)
    payload = create_estimate_payload(proof["id"], substrate=substrate)
    if valid_until_iso is not None:
        payload["valid_until_iso"] = valid_until_iso
    estimate = get_success_data(api_client.create_estimate(project["id"], payload, SM))
    estimate = get_success_data(api_client.send_estimate(project["id"], estimate["id"], SM))
    return project, proof, estimate


def create_permitting_project(color_count=3, substrate="ALUMINUM", **proj_overrides):
    """PERMITTING project with an ACCEPTED estimate.

    Returns (project, proof, estimate)."""
    project, proof, estimate = create_sent_estimate(
        color_count=color_count, substrate=substrate, **proj_overrides)
    pv = get_success_data(api_client.get_sign_project(project["id"], SM))["version"]
    estimate = get_success_data(api_client.accept_estimate(
        project["id"], estimate["id"], {"expected_sign_project_version": pv}, CUST))
    project = get_success_data(api_client.get_sign_project(project["id"], SM))
    return project, proof, estimate


def create_passed_survey(project_id, measured_clearance_ft=30,
                         overhead_obstruction=False, ground_bearing_ok=True):
    """Create a survey and pass it. Returns the PASSED survey."""
    survey = get_success_data(api_client.create_site_survey(
        project_id, create_site_survey_payload(
            measured_clearance_ft=measured_clearance_ft,
            overhead_obstruction=overhead_obstruction,
            ground_bearing_ok=ground_bearing_ok), SURV))
    survey = get_success_data(api_client.decide_site_survey(
        project_id, survey["id"], {"result": "PASS"}, SURV))
    return survey


def create_fabrication_project(color_count=3, substrate="ALUMINUM",
                               survey_overhead_obstruction=False, **proj_overrides):
    """FABRICATION project: accepted estimate + passed survey + RELEASED work order.

    Returns (project, estimate, survey, work_order)."""
    project, proof, estimate = create_permitting_project(
        color_count=color_count, substrate=substrate, **proj_overrides)
    survey = create_passed_survey(
        project["id"], overhead_obstruction=survey_overhead_obstruction)
    wo = get_success_data(api_client.create_work_order(project["id"], SM))
    project = get_success_data(api_client.get_sign_project(project["id"], SM))
    return project, estimate, survey, wo


def create_ready_for_install_project(color_count=3, substrate="ALUMINUM",
                                     survey_overhead_obstruction=False, **proj_overrides):
    """INSTALL project: work order walked RELEASED -> IN_PRODUCTION -> QC_HOLD ->
    READY_FOR_INSTALL (qc_pass=true).

    Returns (project, estimate, survey, work_order)."""
    project, estimate, survey, wo = create_fabrication_project(
        color_count=color_count, substrate=substrate,
        survey_overhead_obstruction=survey_overhead_obstruction, **proj_overrides)
    api_client.start_work_order(project["id"], wo["id"], SM)
    api_client.qc_hold_work_order(project["id"], wo["id"], SM)
    wo = get_success_data(api_client.qc_decide_work_order(
        project["id"], wo["id"], {"qc_pass": True}, SM))
    project = get_success_data(api_client.get_sign_project(project["id"], SM))
    return project, estimate, survey, wo


def schedule_install_job(project_id, work_order_id, crew_id,
                         window_start_iso, window_end_iso, equipment_id=None):
    """Schedule an install job. Returns the SCHEDULED job (raw success data)."""
    payload = create_install_job_payload(
        work_order_id, crew_id, window_start_iso, window_end_iso)
    if equipment_id is not None:
        payload["equipment_id"] = equipment_id
    return get_success_data(api_client.create_install_job(project_id, payload, SM))


def create_installed_project(
        placement_height_ft=12, equipment_class="LADDER", equipment_reach=16,
        certified_aerial=False, window_start_iso="2026-06-01T08:00:00Z",
        window_end_iso="2026-06-01T09:00:00Z", **proj_overrides):
    """WARRANTY project: full lifecycle through an INSTALLED install job.

    Crew/equipment are sized to satisfy the derived required_equipment_class for
    the given placement_height_ft. Returns (project, work_order, crew, equipment,
    install_job)."""
    project, estimate, survey, wo = create_ready_for_install_project(
        placement_height_ft=placement_height_ft, **proj_overrides)
    crew = register_crew(name="Install Crew", certified_aerial=certified_aerial)
    equip = register_equipment(
        asset_tag="EQ-INST", equipment_class=equipment_class, max_reach_ft=equipment_reach)
    job = schedule_install_job(
        project["id"], wo["id"], crew["id"], window_start_iso, window_end_iso,
        equipment_id=equip["id"])
    api_client.dispatch_install_job(project["id"], job["id"], SM)
    job = get_success_data(api_client.complete_install_job(project["id"], job["id"], SM))
    project = get_success_data(api_client.get_sign_project(project["id"], SM))
    return project, wo, crew, equip, job


def create_closed_project(install_iso="2026-06-01T10:00:00Z", **proj_overrides):
    """CLOSED project: installed at install_iso then closed (no open claims).

    Sets the clock to install_iso before completing so the warranty clock anchors
    deterministically. Returns the CLOSED project."""
    set_clock(install_iso)
    project, wo, crew, equip, job = create_installed_project(**proj_overrides)
    project = get_success_data(api_client.close_sign_project(project["id"], SM))
    return project


def create_proposed_change_order(project_id, **co_overrides):
    """Propose a change order against a project already in the change window.

    Returns the PROPOSED change order."""
    return get_success_data(api_client.create_change_order(
        project_id, create_change_order_payload(**co_overrides), SM))


def create_approved_change_order(project_id, **co_overrides):
    """Propose then approve a change order. Returns the APPROVED change order."""
    co = create_proposed_change_order(project_id, **co_overrides)
    return get_success_data(api_client.approve_change_order(project_id, co["id"], CUST))


def get_project_version(project_id):
    """Read the project's current version (used for OCC expected_sign_project_version)."""
    return get_success_data(api_client.get_sign_project(project_id, SM))["version"]
