"""Install-job scheduling guards, crew travel-buffer overlap, and the warranty fork
(seal-repair vs replacement) plus the warranty window."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    create_install_job_payload, create_warranty_claim_payload,
    setup_scheduled_fab, setup_complete_fab, setup_install_done, setup_warranty_submitted,
    new_crew,
)


# --------------------------------------------------------------------------
# Difficulty/cross_entity_state_dependency — install blocked by incomplete fab
# --------------------------------------------------------------------------
def test_install_create_blocked_by_scheduled_fab(api, installer_headers):
    """PRD §3.6: "The referenced fabrication order must be `COMPLETE`, or the create is rejected
    with `ERR_FAB_NOT_COMPLETE` (409)."

    Design: Difficulty/cross_entity_state_dependency/install_create_blocked_by_incomplete_fab
    """
    ctx = setup_scheduled_fab()
    crew = new_crew()
    payload = create_install_job_payload(
        project_id=ctx["p_id"], fabrication_order_id=ctx["f_id"], crew_id=crew["id"], install_date="2026-06-15")
    resp = api.create_install_job(payload, installer_headers)
    validate_error(resp, ApiErrorId.ERR_FAB_NOT_COMPLETE)


def test_install_create_blocked_by_cutting_fab(api, installer_headers, fabricator_headers):
    """PRD §3.6: "The referenced fabrication order must be `COMPLETE`, or the create is rejected
    with `ERR_FAB_NOT_COMPLETE` (409)."

    A fabrication order advanced only to CUTTING is still not COMPLETE.

    Design: Difficulty/cross_entity_state_dependency/install_create_blocked_by_incomplete_fab
    """
    ctx = setup_scheduled_fab()
    api.start_cut(ctx["f_id"], fabricator_headers)
    crew = new_crew()
    payload = create_install_job_payload(
        project_id=ctx["p_id"], fabrication_order_id=ctx["f_id"], crew_id=crew["id"], install_date="2026-06-15")
    resp = api.create_install_job(payload, installer_headers)
    validate_error(resp, ApiErrorId.ERR_FAB_NOT_COMPLETE)


# --------------------------------------------------------------------------
# Difficulty/resource_temporal_overlap — crew travel-buffer semantics
# --------------------------------------------------------------------------
def test_crew_within_one_day_rejected(api, installer_headers):
    """PRD §3.6: "two install jobs on the same crew must have install dates more than one day
    apart, so a create whose `install_date` falls within one day of another job on the same
    crew — that is, the absolute difference in days is one or less — is rejected with
    `ERR_CREW_UNAVAILABLE` (409)."

    2026-06-16 is one day from the existing 2026-06-15 job on the same crew.

    Design: Difficulty/resource_temporal_overlap/crew_buffered_overlap_rejected
    """
    ctx = setup_complete_fab()
    crew = new_crew()
    validate_success(api.create_install_job(
        create_install_job_payload(
            project_id=ctx["p_id"], fabrication_order_id=ctx["f_id"], crew_id=crew["id"], install_date="2026-06-15"),
        installer_headers), expected_status=201)
    payload = create_install_job_payload(
        project_id=ctx["p_id"], fabrication_order_id=ctx["f_id"], crew_id=crew["id"], install_date="2026-06-16")
    resp = api.create_install_job(payload, installer_headers)
    validate_error(resp, ApiErrorId.ERR_CREW_UNAVAILABLE)


def test_crew_more_than_one_day_apart_allowed(api, installer_headers):
    """PRD §3.6: "two install jobs on the same crew must have install dates more than one day
    apart, so a create whose `install_date` falls within one day of another job on the same
    crew — that is, the absolute difference in days is one or less — is rejected with
    `ERR_CREW_UNAVAILABLE` (409)."

    2026-06-17 is two days from the existing 2026-06-15 job, so the create is accepted.

    Design: Difficulty/resource_temporal_overlap/crew_buffered_overlap_rejected
    """
    ctx = setup_complete_fab()
    crew = new_crew()
    validate_success(api.create_install_job(
        create_install_job_payload(
            project_id=ctx["p_id"], fabrication_order_id=ctx["f_id"], crew_id=crew["id"], install_date="2026-06-15"),
        installer_headers), expected_status=201)
    payload = create_install_job_payload(
        project_id=ctx["p_id"], fabrication_order_id=ctx["f_id"], crew_id=crew["id"], install_date="2026-06-17")
    data = validate_success(api.create_install_job(payload, installer_headers), expected_status=201)
    assert data["status"] == "SCHEDULED"


# --------------------------------------------------------------------------
# Corner/state_machines — seal-repair branch (no reopen)
# --------------------------------------------------------------------------
def test_warranty_seal_repair_branch_no_reopen(api, installer_headers, salesrep_headers):
    """PRD §3.8: "A `resolution` of `SEAL_REPAIR` moves the claim to `RESOLVED`, records
    `resolution` as `SEAL_REPAIR`, and has no financial or install side effects — it is a
    simple seal touch-up."

    Design: Corner/state_machines/warranty_seal_repair_branch_no_reopen
    """
    ctx = setup_warranty_submitted(claim_type="SEAL")
    resolved = validate_success(api.resolve_warranty_claim(ctx["wc_id"], {"resolution": "SEAL_REPAIR"}, installer_headers))
    assert resolved["status"] == "RESOLVED"
    assert resolved["resolution"] == "SEAL_REPAIR"
    proj = validate_success(api.get_project(ctx["p_id"], salesrep_headers))
    assert proj["status"] == "INSTALLED"


# --------------------------------------------------------------------------
# Difficulty/non_linear_state_machine — replacement branch reopens production
# --------------------------------------------------------------------------
def test_warranty_replacement_resolves_claim(api, installer_headers):
    """PRD §3.8: "A `resolution` of `REPLACEMENT` also moves the claim to `RESOLVED` and records
    `resolution` as `REPLACEMENT`, but it reopens production by returning the project to
    `IN_PRODUCTION` so the piece can be refabricated."

    Design: Difficulty/non_linear_state_machine/warranty_fork_seal_vs_replacement_branch
    """
    ctx = setup_warranty_submitted(claim_type="CRACK")
    resolved = validate_success(api.resolve_warranty_claim(ctx["wc_id"], {"resolution": "REPLACEMENT"}, installer_headers))
    assert resolved["status"] == "RESOLVED"
    assert resolved["resolution"] == "REPLACEMENT"


def test_warranty_replacement_reopens_production(api, installer_headers, salesrep_headers):
    """PRD §3.8: "A `resolution` of `REPLACEMENT` also moves the claim to `RESOLVED` and records
    `resolution` as `REPLACEMENT`, but it reopens production by returning the project to
    `IN_PRODUCTION` so the piece can be refabricated."

    Unlike the SEAL_REPAIR branch, REPLACEMENT drives the project back to IN_PRODUCTION.

    Design: Difficulty/non_linear_state_machine/warranty_fork_seal_vs_replacement_branch
    """
    ctx = setup_warranty_submitted(claim_type="CRACK")
    api.resolve_warranty_claim(ctx["wc_id"], {"resolution": "REPLACEMENT"}, installer_headers)
    proj = validate_success(api.get_project(ctx["p_id"], salesrep_headers))
    assert proj["status"] == "IN_PRODUCTION"


# --------------------------------------------------------------------------
# Corner/validations — warranty filed after the window
# --------------------------------------------------------------------------
def test_warranty_after_window_returns_warranty_expired(api, installer_headers):
    """PRD §3.8: "the claim is accepted only while the current logical-clock time is at or
    before the job's `completed_at` plus 365 days; a claim filed after that point is rejected
    with `ERR_WARRANTY_EXPIRED` (422)."

    completed_at is at the default clock 2026-05-01; advancing to 2027-06-01 (past the
    2027-05-01 window) expires the warranty.

    Design: Corner/validations/warranty_after_window_returns_warranty_expired
    """
    ctx = setup_install_done()
    api.set_clock({"to_iso8601": "2027-06-01T00:00:00Z"}, TEST_USERS["shopmanager_headers"])
    resp = api.create_warranty_claim(
        ctx["ij_id"], create_warranty_claim_payload(claim_type="CHIP", description="late claim"), installer_headers)
    validate_error(resp, ApiErrorId.ERR_WARRANTY_EXPIRED)
