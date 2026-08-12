"""Cleaning job drafting and scheduling gates (PRD §3.4)."""
import pytest

from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    create_product_payload, create_cleaning_job_payload,
    create_service_window_payload,
    new_ctx, create_job, schedule_job, activate_window_and_take_oos,
    set_clock, fresh_tank_version,
    assert_cleaning_job,
)

ADMIN = TEST_USERS["admin_headers"]
OPERATOR = TEST_USERS["operator_headers"]


class TestJobDraft:
    def test_job_initial_state_is_draft(self, api):
        """PRD §4: "POST /ops/cleaning-jobs | Create a cleaning job in `DRAFT`; computes changeover class, provisional sludge estimate, flush volume"
        PRD §3.4: "Scheduling is the first gated transition."

        Design: Corner/state_machines/job_initial_state_is_draft
        """
        ctx = new_ctx()
        job = create_job(ctx, heel_volume_liters_sounding=100,
                         base_service_fee_cents=1000)
        assert_cleaning_job(job)
        assert job["status"] == "DRAFT"
        assert job.get("window_id") is None

    def test_forbidden_changeover_creates_with_null_flush_then_schedule_rejected(self, api):
        """PRD §3.4: "otherwise, if the two product families form a crude-into-jet or jet-into-crude pair in either direction, the class is `FORBIDDEN`"
        PRD §3.4: "A job classified `FORBIDDEN` carries no flush volume — the field stays null — and, as scheduling will enforce, can never leave the draft stage."
        PRD §3.4: "Next, a `FORBIDDEN` changeover class is rejected with `ERR_INCOMPATIBLE_CHANGEOVER` (HTTP 422)."

        Design: Corner/validations/schedule_forbidden_changeover_rejected
        """
        ctx = new_ctx()
        crude = validate_success(api.create_product(create_product_payload(
            code="CRD01", family="CRUDE", viscosity_class="HIGH",
            compatibility_group="CRUDE", flash_point_c=20), ADMIN), 201)
        jet = validate_success(api.create_product(create_product_payload(
            code="JETA", family="JET", viscosity_class="LOW",
            compatibility_group="JET", flash_point_c=38), ADMIN), 201)
        job = validate_success(api.create_cleaning_job(
            create_cleaning_job_payload(
                ctx["terminal"]["id"], ctx["tank"]["id"],
                ctx["contractor"]["id"], crude["id"], jet["id"],
                heel_volume_liters_sounding=3000, base_service_fee_cents=900000),
            OPERATOR), 201)
        assert job["changeover_class"] == "FORBIDDEN"
        assert job["flush_volume_liters"] is None

        window = validate_success(api.create_service_window(
            create_service_window_payload(
                ctx["tank"]["id"], fresh_tank_version(ctx["tank"]["id"])),
            OPERATOR), 201)
        res = api.schedule_job(job["id"], {"window_id": window["id"]}, OPERATOR)
        validate_error(res, ApiErrorId.ERR_INCOMPATIBLE_CHANGEOVER)
        after = validate_success(api.get_cleaning_job(job["id"], OPERATOR), 200)
        assert after["status"] == "DRAFT"

    def test_schedule_twice_returns_invalid_state(self, api):
        """PRD §3.4: "The job must be in `DRAFT` — anything else is an invalid transition"

        Design: Corner/state_machines/schedule_twice_returns_invalid_state
        """
        ctx = new_ctx()
        create_job(ctx, heel_volume_liters_sounding=100,
                   base_service_fee_cents=1000)
        schedule_job(ctx)
        job = ctx["job"]
        assert job["status"] == "SCHEDULED"
        res = api.schedule_job(job["id"], {"window_id": ctx["window"]["id"]},
                               OPERATOR)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        after = validate_success(api.get_cleaning_job(job["id"], OPERATOR), 200)
        assert after["status"] == "SCHEDULED"

    def test_job_create_on_out_of_service_tank_rejected(self, api):
        """PRD §3.4: "Creation refuses a tank that is not `IN_SERVICE` with `ERR_TANK_NOT_IN_SERVICE` (HTTP 409)"

        Design: Corner/validations/job_create_on_oos_tank_rejected
        """
        ctx = new_ctx()
        create_job(ctx, heel_volume_liters_sounding=100,
                   base_service_fee_cents=1000)
        schedule_job(ctx)
        activate_window_and_take_oos(ctx)
        # Tank is now OUT_OF_SERVICE; a second job on it is refused.
        res = api.create_cleaning_job(
            create_cleaning_job_payload(
                ctx["terminal"]["id"], ctx["tank"]["id"],
                ctx["contractor"]["id"], ctx["gas"]["id"], ctx["dist"]["id"],
                heel_volume_liters_sounding=50, base_service_fee_cents=500),
            OPERATOR)
        validate_error(res, ApiErrorId.ERR_TANK_NOT_IN_SERVICE)


class TestJobCancellation:
    def test_cancelled_job_is_terminal_and_rejects_further_transitions(self, api):
        """PRD §3.8: "Cancelling a job is defined from `DRAFT`, `SCHEDULED`, `TANK_OOS`, `HEEL_REMOVED`, `SLUDGE_REMOVED`, `GAS_FREE_PENDING`, `GAS_FREE_CERTIFIED`, and `PAUSED`; from any other status the request is an invalid transition."
        PRD §3.8: "From `DRAFT` there is nothing to unwind."

        Design: Corner/state_machines/cancelled_job_terminal_lockdown
        """
        ctx = new_ctx()
        job = create_job(ctx, heel_volume_liters_sounding=100,
                         base_service_fee_cents=1000)
        cancelled = validate_success(api.cancel_job(job["id"], OPERATOR), 200)
        assert cancelled["status"] == "CANCELLED"

        res1 = api.cancel_job(job["id"], OPERATOR)
        validate_error(res1, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        res2 = api.take_out_of_service(job["id"], OPERATOR)
        validate_error(res2, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

        tank = validate_success(api.get_tank(ctx["tank"]["id"], OPERATOR), 200)
        assert tank["status"] == "IN_SERVICE"
