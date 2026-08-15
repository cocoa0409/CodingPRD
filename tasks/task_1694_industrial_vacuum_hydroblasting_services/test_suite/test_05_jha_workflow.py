"""Job hazard analysis lifecycle: revision cycle, supersede, segregation."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_jha_payload,
    create_job,
    create_site_with_active_schedule,
    get_success_data,
    validate_error,
)

FS = TEST_USERS["field_supervisor_headers"]
SM = TEST_USERS["safety_manager_headers"]
PM = TEST_USERS["project_manager_headers"]


def _submit_and_approve(api, jha_id, job_id):
    get_success_data(api.submit_jha(jha_id, FS))
    job = get_success_data(api.get_job(job_id, PM))
    return get_success_data(
        api.approve_jha(jha_id, {"expected_job_version": job["version"]}, SM)
    )


class TestJhaRevisionCycleAndSupersede:
    def test_revision_cycle_reject_revise_resubmit(self, api):
        """PRD §3.3: "A rejected revision is not dead: revising it returns
        `REJECTED` → `DRAFT`, where its pressure and water plan can be corrected
        before resubmission — plans otherwise evolve only by authoring a new
        revision."

        Design: Difficulty/non_linear_state_machine/jha_revision_cycle_and_supersede
        """
        site, _ = create_site_with_active_schedule()
        job = create_job(site["id"])
        jha = get_success_data(api.create_jha(create_jha_payload(job["id"]), FS))
        assert jha["revision_number"] == 1
        get_success_data(api.submit_jha(jha["id"], FS))
        rejected = get_success_data(api.reject_jha(jha["id"], SM))
        assert rejected["status"] == "REJECTED"
        back = get_success_data(api.revise_jha(jha["id"], FS))
        assert back["status"] == "DRAFT"
        approved = _submit_and_approve(api, jha["id"], job["id"])
        assert approved["status"] == "APPROVED"

    def test_approving_newer_revision_supersedes_prior(self, api):
        """PRD §3.3: "A successful approval stamps `approved_by`, moves the
        revision to `APPROVED`, atomically supersedes any other `APPROVED`
        revision of the same job — there is at most one approved revision per
        job at any time — and increments the job's `version` by one."

        Design: Difficulty/non_linear_state_machine/jha_revision_cycle_and_supersede
        """
        site, _ = create_site_with_active_schedule()
        job = create_job(site["id"])
        jha1 = get_success_data(api.create_jha(create_jha_payload(job["id"]), FS))
        _submit_and_approve(api, jha1["id"], job["id"])

        jha2 = get_success_data(
            api.create_jha(
                create_jha_payload(job["id"], hazards=["CHEMICAL_EXPOSURE", "ERGONOMIC"]), FS
            )
        )
        assert jha2["revision_number"] == 2
        approved2 = _submit_and_approve(api, jha2["id"], job["id"])
        assert approved2["status"] == "APPROVED"

        jha1_after = get_success_data(api.get_jha(jha1["id"], PM))
        assert jha1_after["status"] == "SUPERSEDED"
        jha2_after = get_success_data(api.get_jha(jha2["id"], PM))
        assert jha2_after["status"] == "APPROVED"


class TestJhaApproveFromDraft:
    def test_approve_draft_jha_with_fresh_version_fails_state_check(self, api):
        """PRD §3.3: "the request must carry `expected_job_version` matching the
        job's current `version`, and this stale-version check is evaluated
        before any business gate — a stale read is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."
        PRD §2.8: "State legality — the target entity is in a from-state that
        permits the requested transition ... else `ERR_INVALID_STATE`."

        Design: Corner/state_machines/jha_approve_from_draft_rejected_after_occ_passes
        """
        site, _ = create_site_with_active_schedule()
        job = create_job(site["id"], description="occ-then-state")
        jha = get_success_data(api.create_jha(create_jha_payload(job["id"]), FS))
        job_now = get_success_data(api.get_job(job["id"], PM))
        resp = api.approve_jha(
            jha["id"], {"expected_job_version": job_now["version"]}, SM
        )
        # OCC passes (fresh version); the DRAFT from-state then fails.
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
        assert resp.status_code == 409


class TestSegregationOfDuties:
    def test_jha_approve_by_submitter_rejected(self, api):
        """PRD §3.3: "segregation of duties forbids the submitter from approving
        their own revision: an approver whose `X-User-ID` equals the revision's
        `submitted_by` is rejected with `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/validations/sod_jha_approve_by_submitter_rejected
        """
        from test_helpers import make_safety_manager_headers
        site, _ = create_site_with_active_schedule()
        job = create_job(site["id"], description="sod jha")
        jha = get_success_data(api.create_jha(create_jha_payload(job["id"]), FS))
        get_success_data(api.submit_jha(jha["id"], FS))
        job_now = get_success_data(api.get_job(job["id"], PM))
        # Approver carries the SAME X-User-ID ("fs_1") as the submitter.
        resp = api.approve_jha(
            jha["id"],
            {"expected_job_version": job_now["version"]},
            make_safety_manager_headers("fs_1"),
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
        assert resp.status_code == 422
        jha_after = get_success_data(api.get_jha(jha["id"], PM))
        assert jha_after["status"] == "SUBMITTED"


class TestPressurePlanRequirement:
    def test_hydroblast_jha_submit_without_pressure_plan_rejected(self, api):
        """PRD §3.3: "For `HYDROBLAST` and `COMBINED` jobs the submission must
        carry all three pressure-plan fields, or it is rejected with
        `ERR_JHA_PRESSURE_PLAN_REQUIRED`; a `VACUUM` job carries no such
        requirement."

        Design: Corner/validations/hydroblast_jha_submit_without_pressure_plan_rejected
        """
        site, _ = create_site_with_active_schedule()
        job = create_job(site["id"], job_type="HYDROBLAST", description="pressure plan")
        jha = get_success_data(
            api.create_jha(
                create_jha_payload(job["id"], hazards=["HIGH_PRESSURE_WATER"]), FS
            )
        )
        resp = api.submit_jha(jha["id"], FS)
        validate_error(resp, ApiErrorId.ERR_JHA_PRESSURE_PLAN_REQUIRED.value)
        assert resp.status_code == 422
        jha_after = get_success_data(api.get_jha(jha["id"], PM))
        assert jha_after["status"] == "DRAFT"
