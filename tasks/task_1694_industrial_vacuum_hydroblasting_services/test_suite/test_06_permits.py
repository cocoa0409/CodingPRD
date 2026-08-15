"""Permit lifecycle, activation gates, and the daily-close expiry sweep."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_confirmed_equipment_assignment,
    create_equipment_unit,
    create_job,
    create_permit_payload,
    create_site_with_active_schedule,
    create_submit_approve_jha,
    get_success_data,
    schedule_and_mobilize,
    validate_error,
)

PM = TEST_USERS["project_manager_headers"]
FS = TEST_USERS["field_supervisor_headers"]
SM = TEST_USERS["safety_manager_headers"]
PA = TEST_USERS["platform_admin_headers"]


def _mobilized_job_with_unit(api, **job_kwargs):
    site, _ = create_site_with_active_schedule()
    unit = create_equipment_unit()
    job = create_job(site["id"], **job_kwargs)
    create_confirmed_equipment_assignment(job["id"], unit["id"])
    schedule_and_mobilize(job["id"])
    return site, job


class TestPermitActiveSuspendedCycle:
    def test_permit_active_suspend_reactivate_close_cycle(self, api):
        """PRD §3.3: "Activation — `ISSUED` → `ACTIVE`, or `SUSPENDED` → `ACTIVE`
        when restoring a suspended permit — ... From `ACTIVE`, a `SafetyManager`
        may suspend (`ACTIVE` → `SUSPENDED`) and a `FieldSupervisor` may close
        (`ACTIVE` → `CLOSED`)".

        Design: Difficulty/non_linear_state_machine/permit_active_suspended_cycle
        """
        _, job = _mobilized_job_with_unit(api, description="permit cycle")
        permit = get_success_data(
            api.create_permit(
                create_permit_payload(job["id"], permit_type="HOT_WORK", space_id="B-201"),
                FS,
            )
        )
        active1 = get_success_data(api.activate_permit(permit["id"], FS))
        assert active1["status"] == "ACTIVE"
        suspended = get_success_data(api.suspend_permit(permit["id"], SM))
        assert suspended["status"] == "SUSPENDED"
        active2 = get_success_data(api.activate_permit(permit["id"], FS))
        assert active2["status"] == "ACTIVE"
        closed = get_success_data(api.close_permit(permit["id"], FS))
        assert closed["status"] == "CLOSED"

    def test_permit_version_increments_on_each_transition(self, api):
        """PRD §2.4: "`version`: an integer that increments by one on every
        mutation of the resource."

        Design: Difficulty/non_linear_state_machine/permit_active_suspended_cycle
        """
        _, job = _mobilized_job_with_unit(api)
        permit = get_success_data(
            api.create_permit(create_permit_payload(job["id"]), FS)
        )
        assert permit["version"] == 1
        get_success_data(api.activate_permit(permit["id"], FS))
        get_success_data(api.suspend_permit(permit["id"], SM))
        get_success_data(api.activate_permit(permit["id"], FS))
        closed = get_success_data(api.close_permit(permit["id"], FS))
        assert closed["version"] == 5


class TestPermitActivationGates:
    def test_double_activation_rejected(self, api):
        """PRD §3.3: "Activation — `ISSUED` → `ACTIVE`, or `SUSPENDED` →
        `ACTIVE`".
        PRD §2.8: "State legality — the target entity is in a from-state that
        permits the requested transition ... else `ERR_INVALID_STATE`."

        Design: Corner/state_machines/permit_double_activation_rejected
        """
        _, job = _mobilized_job_with_unit(api, description="double activate")
        permit = get_success_data(
            api.create_permit(
                create_permit_payload(job["id"], permit_type="HOT_WORK"), FS
            )
        )
        get_success_data(api.activate_permit(permit["id"], FS))
        resp = api.activate_permit(permit["id"], FS)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
        after = get_success_data(api.get_permit(permit["id"], PM))
        assert after["status"] == "ACTIVE"

    def test_second_active_permit_same_space_rejected(self, api):
        """PRD §3.3: "no other permit of the same job and `space_id` may already
        be `ACTIVE` (`ERR_PERMIT_SPACE_OCCUPIED`)".

        Design: Corner/validations/second_active_permit_same_space_rejected
        """
        _, job = _mobilized_job_with_unit(api, description="space occupied")
        create_submit_approve_jha(job["id"], jha_overrides={
            "confined_space": True, "hazards": ["CONFINED_SPACE"],
        })
        p1 = get_success_data(
            api.create_permit(
                create_permit_payload(
                    job["id"], permit_type="CONFINED_SPACE", space_id="T-101"
                ),
                FS,
            )
        )
        get_success_data(api.activate_permit(p1["id"], FS))
        p2 = get_success_data(
            api.create_permit(
                create_permit_payload(
                    job["id"], permit_type="CONFINED_SPACE", space_id="T-101"
                ),
                FS,
            )
        )
        resp = api.activate_permit(p2["id"], FS)
        validate_error(resp, ApiErrorId.ERR_PERMIT_SPACE_OCCUPIED.value)
        assert resp.status_code == 409
        p2_after = get_success_data(api.get_permit(p2["id"], PM))
        assert p2_after["status"] == "ISSUED"

    def test_permit_activate_outside_validity_window_rejected(self, api):
        """PRD §3.3: "the logical clock must read within the inclusive window
        from `valid_from` to `valid_until` (`ERR_PERMIT_WINDOW_INVALID`)".

        Design: Corner/validations/permit_activate_outside_validity_window_rejected
        """
        _, job = _mobilized_job_with_unit(api, description="window invalid")
        permit = get_success_data(
            api.create_permit(
                create_permit_payload(
                    job["id"],
                    permit_type="HOT_WORK",
                    space_id="B-202",
                    valid_from="2026-09-01T00:00:00Z",
                    valid_until="2026-09-02T00:00:00Z",
                ),
                FS,
            )
        )
        resp = api.activate_permit(permit["id"], FS)
        validate_error(resp, ApiErrorId.ERR_PERMIT_WINDOW_INVALID.value)
        assert resp.status_code == 422
        after = get_success_data(api.get_permit(permit["id"], PM))
        assert after["status"] == "ISSUED"

    def test_confined_permit_without_confined_jha_rejected(self, api):
        """PRD §3.3: "for a `CONFINED_SPACE` permit, the job's latest `APPROVED`
        hazard analysis must declare `confined_space` true
        (`ERR_PERMIT_JHA_MISMATCH`)".

        Design: Corner/validations/confined_permit_without_confined_jha_rejected
        """
        _, job = _mobilized_job_with_unit(api, description="jha mismatch")
        # Approved JHA declares confined_space=False.
        create_submit_approve_jha(job["id"])
        permit = get_success_data(
            api.create_permit(
                create_permit_payload(
                    job["id"], permit_type="CONFINED_SPACE", space_id="T-102"
                ),
                FS,
            )
        )
        resp = api.activate_permit(permit["id"], FS)
        validate_error(resp, ApiErrorId.ERR_PERMIT_JHA_MISMATCH.value)
        assert resp.status_code == 422
        after = get_success_data(api.get_permit(permit["id"], PM))
        assert after["status"] == "ISSUED"


class TestDailyClose:
    def test_daily_close_expires_permits_past_validity(self, api):
        """PRD §2.5: "The checkpoint expires every permit belonging to the
        site's jobs that is still `ISSUED`, `ACTIVE` or `SUSPENDED` and whose
        `valid_until` is earlier than the current clock reading, moving each
        such permit to `EXPIRED` ... The checkpoint's response lists the
        affected identifiers as `expired_permit_ids` and
        `cancelled_assignment_ids`."

        Design: Corner/state_machines/daily_close_expires_permits_past_validity
        """
        site, job = _mobilized_job_with_unit(api, description="permit expiry")
        permit = get_success_data(
            api.create_permit(
                create_permit_payload(
                    job["id"],
                    permit_type="HOT_WORK",
                    valid_from="2026-07-31T00:00:00Z",
                    valid_until="2026-08-01T04:00:00Z",
                ),
                FS,
            )
        )
        get_success_data(api.activate_permit(permit["id"], FS))
        get_success_data(api.set_clock("2026-08-02T00:00:00Z", PA))
        result = get_success_data(api.daily_close(site["id"], PM))
        assert permit["id"] in result["expired_permit_ids"]
        after = get_success_data(api.get_permit(permit["id"], PM))
        assert after["status"] == "EXPIRED"

    def test_daily_close_cancels_stale_scheduled_assignments(self, api):
        """PRD §2.5: "it cancels every assignment of the site's jobs that is
        still `SCHEDULED` and whose `window_start` lies more than 24 hours in
        the past, moving each to `CANCELLED`."

        Design: Corner/state_machines/daily_close_cancels_stale_scheduled_assignments
        """
        from test_helpers import create_equipment_assignment_payload
        site, _ = create_site_with_active_schedule()
        unit_a = create_equipment_unit(unit_code="VAC-01")
        unit_b = create_equipment_unit(unit_code="VAC-02")
        job = create_job(site["id"], description="stale sweep")
        asg_a = get_success_data(
            api.create_assignment(
                create_equipment_assignment_payload(job["id"], unit_a["id"]), PM
            )
        )
        asg_b = get_success_data(
            api.create_assignment(
                create_equipment_assignment_payload(job["id"], unit_b["id"]), PM
            )
        )
        get_success_data(api.confirm_assignment(asg_b["id"], PM))
        get_success_data(api.set_clock("2026-08-02T07:00:00Z", PA))
        result = get_success_data(api.daily_close(site["id"], PM))
        assert asg_a["id"] in result["cancelled_assignment_ids"]
        assert asg_b["id"] not in result["cancelled_assignment_ids"]
        a_after = get_success_data(api.get_assignment(asg_a["id"], PM))
        assert a_after["status"] == "CANCELLED"
        b_after = get_success_data(api.get_assignment(asg_b["id"], PM))
        assert b_after["status"] == "CONFIRMED"
