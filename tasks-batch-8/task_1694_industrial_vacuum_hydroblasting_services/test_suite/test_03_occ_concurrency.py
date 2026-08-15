"""Optimistic concurrency control on the two guarded writes."""
from test_helpers import (
    ApiErrorId,
    create_jha_payload,
    create_job,
    create_rate_schedule_payload,
    create_site_payload,
    create_site_with_active_schedule,
    get_success_data,
    validate_error,
)


class TestRateScheduleActivationOCC:
    def test_stale_site_version_rejected(
        self, api, account_manager_headers
    ):
        """PRD §2.7: "**Rate-schedule activation** requires the request to carry
        `expected_site_version`, the client-observed `version` of the owning
        site. If the site's current `version` has advanced beyond what the
        client last read, the activation is rejected with `ERR_STALE_VERSION`
        (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_schedule_activation_stale_then_fresh_succeeds
        """
        site = get_success_data(
            api.create_site(create_site_payload(), account_manager_headers)
        )
        stale_version = site["version"]
        sched1 = get_success_data(
            api.create_rate_schedule(
                create_rate_schedule_payload(site["id"], label="S1"), account_manager_headers
            )
        )
        # First activation advances the site version.
        get_success_data(
            api.activate_rate_schedule(
                sched1["id"], {"expected_site_version": stale_version},
                account_manager_headers,
            )
        )
        sched2 = get_success_data(
            api.create_rate_schedule(
                create_rate_schedule_payload(site["id"], label="S2"), account_manager_headers
            )
        )
        resp = api.activate_rate_schedule(
            sched2["id"], {"expected_site_version": stale_version}, account_manager_headers
        )
        assert resp.status_code == 412
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)

    def test_fresh_site_version_activation_supersedes_prior(
        self, api, account_manager_headers
    ):
        """PRD §3.1: "On success the owning site's `active_rate_schedule_id` is
        set to the newly activated schedule, whichever schedule of that site was
        previously `ACTIVE` moves to `SUPERSEDED`, and the site's `version`
        increments by one."

        Design: Corner/cross_cutting_layers/occ_schedule_activation_stale_then_fresh_succeeds
        """
        site = get_success_data(
            api.create_site(create_site_payload(), account_manager_headers)
        )
        sched1 = get_success_data(
            api.create_rate_schedule(
                create_rate_schedule_payload(site["id"], label="S1"), account_manager_headers
            )
        )
        get_success_data(
            api.activate_rate_schedule(
                sched1["id"], {"expected_site_version": site["version"]},
                account_manager_headers,
            )
        )
        sched2 = get_success_data(
            api.create_rate_schedule(
                create_rate_schedule_payload(site["id"], label="S2"), account_manager_headers
            )
        )
        site_now = get_success_data(api.get_site(site["id"], account_manager_headers))
        activated = get_success_data(
            api.activate_rate_schedule(
                sched2["id"], {"expected_site_version": site_now["version"]},
                account_manager_headers,
            )
        )
        assert activated["status"] == "ACTIVE"
        site_after = get_success_data(api.get_site(site["id"], account_manager_headers))
        assert site_after["active_rate_schedule_id"] == sched2["id"]
        sched1_after = get_success_data(
            api.get_rate_schedule(sched1["id"], account_manager_headers)
        )
        assert sched1_after["status"] == "SUPERSEDED"


class TestJhaApprovalOCC:
    def test_stale_job_version_rejected(self, api):
        """PRD §2.7: "**Hazard-analysis approval** requires the request to carry
        `expected_job_version`, the client-observed `version` of the owning job.
        A mismatch with the job's current `version` is likewise rejected with
        `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_jha_approval_stale_job_version_rejected
        """
        from test_helpers import TEST_USERS
        FS = TEST_USERS["field_supervisor_headers"]
        SM = TEST_USERS["safety_manager_headers"]
        PM = TEST_USERS["project_manager_headers"]
        site, _ = create_site_with_active_schedule()
        job = create_job(site["id"])
        stale_version = job["version"]

        jha1 = get_success_data(api.create_jha(create_jha_payload(job["id"]), FS))
        get_success_data(api.submit_jha(jha1["id"], FS))
        get_success_data(
            api.approve_jha(jha1["id"], {"expected_job_version": stale_version}, SM)
        )

        jha2 = get_success_data(
            api.create_jha(create_jha_payload(job["id"], hazards=["SLIP_TRIP", "ERGONOMIC"]), FS)
        )
        get_success_data(api.submit_jha(jha2["id"], FS))
        resp = api.approve_jha(jha2["id"], {"expected_job_version": stale_version}, SM)
        assert resp.status_code == 412
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)

        jha2_after = get_success_data(api.get_jha(jha2["id"], PM))
        assert jha2_after["status"] == "SUBMITTED"
        jha1_after = get_success_data(api.get_jha(jha1["id"], PM))
        assert jha1_after["status"] == "APPROVED"

    def test_fresh_job_version_approves(self, api):
        """PRD §3.3: "the request must carry `expected_job_version` matching the
        job's current `version`, and this stale-version check is evaluated
        before any business gate — a stale read is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_jha_approval_stale_job_version_rejected
        """
        from test_helpers import TEST_USERS, create_submit_approve_jha
        site, _ = create_site_with_active_schedule()
        job = create_job(site["id"])
        approved = create_submit_approve_jha(job["id"])
        assert approved["status"] == "APPROVED"
        assert approved["approved_by"] == "sm_1"
