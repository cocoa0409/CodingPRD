"""Composite setup helpers for multi-step test prerequisites (Mold Remediation).

The test harness restarts the server before every test, so every fixture begins
from an empty database. Each fixture sets the logical clock first, then builds its
preconditions using only PRD-declared endpoints. Fixtures use get_success_data()
(lenient validator) so a setup misstep surfaces as a clear "setup failed" error.

Role usage follows the PRD §2.1 RBAC matrix; X-User-ID is opaque for all roles.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_worker_payload, create_project_payload, create_assessment_payload,
    create_sample_payload, create_zone_payload, create_pressure_log_payload,
    create_abatement_order_payload, create_assignment_payload, create_manifest_payload,
    create_clearance_test_payload, create_permit_payload, create_insurance_claim_payload,
)
from .constants import TEST_CLOCK, TEST_DEFAULTS
from .test_users import TEST_USERS

PM = TEST_USERS["project_manager_headers"]
AS = TEST_USERS["abatement_supervisor_headers"]
LT = TEST_USERS["lab_tech_headers"]
HY = TEST_USERS["hygienist_headers"]
CO = TEST_USERS["compliance_officer_headers"]


# ─── Clock ─────────────────────────────────────────────────────────────────
def set_clock(to_iso8601=TEST_CLOCK):
    """Advance the logical clock. Returns the clock-set response data."""
    return get_success_data(api_client.set_clock(to_iso8601, CO))


# ─── Tier 1: primitives ──────────────────────────────────────────────────────
def create_worker(cert_type="MOLD", **overrides):
    """Register a worker. Defaults to a current MOLD cert."""
    return get_success_data(
        api_client.create_worker(create_worker_payload(cert_type=cert_type, **overrides), PM)
    )


def create_project(hazard_class="MOLD", **overrides):
    """Create a project (posture ASSESSMENT)."""
    return get_success_data(
        api_client.create_project(create_project_payload(hazard_class=hazard_class, **overrides), PM)
    )


def create_assessment(project_id, assessor_worker_id, **overrides):
    return get_success_data(
        api_client.create_assessment(
            create_assessment_payload(project_id, assessor_worker_id, **overrides), LT)
    )


def create_zone(project_id, **overrides):
    """Create a SETUP zone."""
    return get_success_data(
        api_client.create_zone(create_zone_payload(project_id, **overrides), PM)
    )


def create_active_zone(project_id, required_pressure_pa=None, reading_pa=None,
                       reading_at=None):
    """Create a zone, log a compliant reading, and activate it. Returns the ACTIVE zone."""
    zkw = {}
    if required_pressure_pa is not None:
        zkw["required_pressure_pa"] = required_pressure_pa
    zone = create_zone(project_id, **zkw)
    plkw = {}
    if reading_pa is not None:
        plkw["reading_pa"] = reading_pa
    if reading_at is not None:
        plkw["reading_at"] = reading_at
    get_success_data(
        api_client.create_pressure_log(zone["id"], create_pressure_log_payload(zone["id"], **plkw), AS)
    )
    return get_success_data(api_client.activate_zone(zone["id"], PM))


def acknowledge_transport_permit(project_id):
    """Create -> submit -> acknowledge a TRANSPORT permit (PRD §3.7). Required as a
    precondition for submitting an ASBESTOS order's disposal manifest (PRD §3.6:
    "when the parent order's abatement_type is ASBESTOS, an ACKNOWLEDGED TRANSPORT
    permit must exist for the project"). Returns the ACKNOWLEDGED permit."""
    permit = get_success_data(
        api_client.create_permit(create_permit_payload(project_id, permit_type="TRANSPORT"), CO)
    )
    get_success_data(api_client.submit_permit(permit["id"], CO))
    return get_success_data(api_client.acknowledge_permit(permit["id"], CO))


# ─── Tier 2: ANALYZED sample under an assessment ─────────────────────────────
def create_analyzed_air_sample(project_id, assessment_id, raw_count, volume_liters=100,
                               collected_at=None):
    """Collect an AIR sample and upload a result. Returns the ANALYZED sample."""
    pl = {} if collected_at is None else {"collected_at": collected_at}
    sample = get_success_data(
        api_client.create_sample(
            create_sample_payload(assessment_id, project_id, "AIR",
                                  volume_liters=volume_liters, **pl), LT)
    )
    return get_success_data(
        api_client.upload_sample_result(sample["id"], {"raw_count": raw_count}, LT)
    )


# ─── Tier 3: completed-order setup (the dominant shared preamble) ─────────────
def setup_completed_order(hazard_class="MOLD", abatement_type="MOLD",
                          planned_weight_kg=50, removed_weight_kg=50,
                          manifest_weight_kg=50, lead_cert_type=None,
                          structure_sqft=None, with_sampler=False,
                          with_hygienist=False):
    """
    Build a project all the way to a COMPLETED abatement order backed by an
    ACCEPTED disposal manifest. Returns a dict with the captured ids/entities:
      pid, zid, aid, mid, lead_id  (+ sampler_id if with_sampler, hyg_id if with_hygienist)

    Sequence: clock -> workers -> project -> active zone -> order -> assignment ->
    start -> manifest -> submit -> accept -> complete.
    Defaults match the canonical MOLD setups in the design index.
    """
    set_clock()
    lead_cert_type = lead_cert_type or abatement_type
    lead = create_worker(cert_type=lead_cert_type, full_name="Lead")
    out = {"lead_id": lead["id"]}
    if with_sampler:
        sampler = create_worker(cert_type="MOLD", full_name="Sampler")
        out["sampler_id"] = sampler["id"]
    if with_hygienist:
        hyg = create_worker(cert_type="HYGIENIST", full_name="Hyg")
        out["hyg_id"] = hyg["id"]

    pkw = {} if structure_sqft is None else {"structure_sqft": structure_sqft}
    project = create_project(hazard_class=hazard_class, **pkw)
    out["pid"] = project["id"]

    zone = create_active_zone(project["id"])
    out["zid"] = zone["id"]

    order = get_success_data(
        api_client.create_abatement_order(
            create_abatement_order_payload(
                project["id"], zone["id"], lead["id"],
                abatement_type=abatement_type, planned_weight_kg=planned_weight_kg), AS)
    )
    out["aid"] = order["id"]

    get_success_data(
        api_client.create_assignment(create_assignment_payload(order["id"], lead["id"]), AS)
    )
    get_success_data(api_client.start_abatement_order(order["id"], AS))

    manifest = get_success_data(
        api_client.create_manifest(
            create_manifest_payload(order["id"], project["id"],
                                    manifest_weight_kg=manifest_weight_kg), AS)
    )
    out["mid"] = manifest["id"]
    # PRD §3.6: submitting an ASBESTOS order's manifest requires an ACKNOWLEDGED
    # TRANSPORT permit on the project. Satisfy that precondition for ASBESTOS setups.
    if abatement_type == "ASBESTOS":
        acknowledge_transport_permit(project["id"])
    get_success_data(api_client.submit_manifest(manifest["id"], AS))
    get_success_data(api_client.accept_manifest(manifest["id"], PM))
    get_success_data(
        api_client.complete_abatement_order(order["id"], {"removed_weight_kg": removed_weight_kg}, AS)
    )
    return out


def setup_draft_clearance(hazard_class="MOLD", clearance_air_count=10,
                          clearance_volume_liters=100, with_hygienist=True,
                          **order_overrides):
    """
    setup_completed_order + a DRAFT ClearanceTest referencing the order.
    Returns the setup_completed_order dict plus 'cid'. A sampler worker is always
    created (clearance tests need a sampler_worker_id).
    """
    ctx = setup_completed_order(hazard_class=hazard_class, with_sampler=True,
                                with_hygienist=with_hygienist, **order_overrides)
    clearance = get_success_data(
        api_client.create_clearance_test(
            create_clearance_test_payload(
                ctx["pid"], ctx["zid"], ctx["aid"], ctx["sampler_id"],
                clearance_air_count=clearance_air_count,
                clearance_volume_liters=clearance_volume_liters), LT)
    )
    ctx["cid"] = clearance["id"]
    return ctx


def setup_passed_clearance(hazard_class="MOLD", clearance_air_count=10,
                           clearance_volume_liters=100, **order_overrides):
    """setup_draft_clearance then analyze to PASSED (count/volume default to a PASS)."""
    ctx = setup_draft_clearance(hazard_class=hazard_class,
                                clearance_air_count=clearance_air_count,
                                clearance_volume_liters=clearance_volume_liters,
                                with_hygienist=True, **order_overrides)
    get_success_data(api_client.analyze_clearance_test(ctx["cid"], LT))
    return ctx


def get_project_version(pid, headers=HY):
    """GET the project and return its current version (for OCC expected_project_version)."""
    return get_success_data(api_client.get_project(pid, headers))["version"]


def setup_verified_project(hazard_class="MOLD", **order_overrides):
    """
    Drive a project to posture VERIFIED via a PASSED clearance signed off by an
    independent hygienist (no assessments, so open_finding_count stays 0).
    Returns the setup dict plus 'pv_after' (project version after sign-off).
    """
    ctx = setup_passed_clearance(hazard_class=hazard_class, **order_overrides)
    pv = get_project_version(ctx["pid"])
    get_success_data(
        api_client.signoff_clearance_test(
            ctx["cid"],
            {"signoff_worker_id": ctx["hyg_id"], "expected_project_version": pv}, HY)
    )
    ctx["pv_after"] = get_project_version(ctx["pid"])
    return ctx
