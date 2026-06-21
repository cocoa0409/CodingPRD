"""State-machine behavior on Estimate, ServiceJob, DispatchAssignment, and Permit.

Covers the cyclic shapes (job reopen, estimate revise/re-present, permit reapply),
invalid-transition lockdowns, the initial DRAFT estimate state, and the conditional
assignment-cancel cascade.
"""
import pytest

from test_helpers import (
    get_success_data, validate_success, validate_error, ApiErrorId,
    create_flat_rate_item, create_customer, create_technician,
    create_service_job, create_inspector,
    setup_on_site_job, setup_authorized_job, setup_completed_job,
    setup_reopened_job, setup_completed_permit_job,
    create_estimate_on_job, add_flat_rate_line, present_estimate,
    approve_estimate, start_work, complete_job, file_callback, accept_callback,
    drive_job_to_on_site,
    get_job_permit, issue_permit, schedule_inspection, record_inspection,
    api_client, TEST_USERS, make_technician_headers, make_customer_headers,
)

OM = TEST_USERS["office_manager_headers"]
DISP = TEST_USERS["dispatcher_headers"]

NORMAL_START = "2026-06-16T10:00:00.000Z"
NORMAL_END = "2026-06-16T12:00:00.000Z"
NORMAL_ETA = "2026-06-16T10:15:00.000Z"


def _list(response):
    body = response.json()
    return body.get("data", []), body.get("meta", {})


class TestServiceJobReopenCycle:
    def test_completed_job_reopens_and_recompletes(self, api):
        """PRD §3.8: "Acceptance is a compensating reversal of the completed job. It
        moves the callback `OPEN → ACCEPTED` and the original job `COMPLETED → REOPENED`."
        PRD §3.8: "The technician **starts work** once more, moving the job
        `REOPENED → IN_PROGRESS`".
        PRD §3.8: "The job can then be **completed** again, cycling
        `IN_PROGRESS → COMPLETED`".

        Design: Difficulty/non_linear_state_machine/service_job_reopen_cycle_completed_to_reopened_to_completed
        """
        fr = create_flat_rate_item(code="RO-1", category="DRAIN",
                                   base_price_cents=20000, skill_required=1)
        scenario = setup_reopened_job(
            flat_rate_lines=[{"item": fr, "quantity": 1}],
            consumed_parts=[],
            customer_overrides={"credit_limit_cents": 100000},
            technician_overrides={"skill_level": 3},
            job_overrides={"category": "DRAIN"},
            window_start=NORMAL_START, window_end=NORMAL_END, eta=NORMAL_ETA,
            clock="2026-03-01T09:00:00.000Z")

        job = scenario["job"]
        tech_id = scenario["technician"]["id"]
        assert job["status"] == "REOPENED", \
            f"after accepted callback the job must be REOPENED, got {job['status']}"

        in_progress = start_work(job["id"], tech_id)
        assert in_progress["status"] == "IN_PROGRESS", \
            f"start-work on REOPENED job -> IN_PROGRESS, got {in_progress['status']}"

        recompleted = complete_job(job["id"], tech_id, [])
        assert recompleted["status"] == "COMPLETED", \
            f"re-completion returns the same row to COMPLETED, got {recompleted['status']}"


class TestEstimateRevisionCycle:
    def test_estimate_presented_revised_presented_recomputes(self, api):
        """PRD §3.3: "A technician may **revise** it, moving it `PRESENTED → REVISED`,
        which reopens it for line edits and is permitted only from `PRESENTED`; the
        revised estimate can later be presented again, looping `REVISED → PRESENTED`
        and re-running the provisional pricing each time."

        Design: Difficulty/non_linear_state_machine/estimate_revision_cycle_presented_to_revised_to_presented
        """
        fr_a = create_flat_rate_item(code="EV-A", category="LEAK",
                                     base_price_cents=12000, skill_required=1)
        fr_b = create_flat_rate_item(code="EV-B", category="LEAK",
                                     base_price_cents=8000, skill_required=1)
        scenario = setup_on_site_job(
            customer_overrides={"credit_limit_cents": 100000},
            technician_overrides={"skill_level": 2},
            job_overrides={"category": "LEAK"},
            window_start=NORMAL_START, window_end=NORMAL_END, eta=NORMAL_ETA)
        tech_id = scenario["technician"]["id"]
        job = scenario["job"]
        tech_h = make_technician_headers(tech_id)

        estimate = create_estimate_on_job(job["id"], job["version"], tech_id)
        add_flat_rate_line(estimate["id"], fr_a["id"], tech_id, 1)
        presented = present_estimate(estimate["id"], tech_id)
        assert presented["status"] == "PRESENTED", \
            f"first present -> PRESENTED, got {presented['status']}"

        revised = get_success_data(api.revise_estimate(estimate["id"], tech_h))
        assert revised["status"] == "REVISED", \
            f"revise -> REVISED, got {revised['status']}"

        add_flat_rate_line(estimate["id"], fr_b["id"], tech_id, 1)
        re_presented = present_estimate(estimate["id"], tech_id)
        assert re_presented["status"] == "PRESENTED", \
            f"re-present -> PRESENTED, got {re_presented['status']}"
        assert re_presented["labor_subtotal_cents"] == 20000, \
            f"recompute must include both lines (12000+8000), got {re_presented['labor_subtotal_cents']}"


class TestInvalidTransitions:
    def test_reconfirm_confirmed_assignment_rejected(self, api):
        """PRD §3.2: "Confirmation is permitted only when the assignment is in
        `PROPOSED` status; otherwise the request is rejected with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/confirm_already_confirmed_assignment_returns_invalid_state
        """
        scenario = setup_on_site_job(
            customer_overrides={"credit_limit_cents": 100000},
            technician_overrides={"skill_level": 3},
            job_overrides={"category": "LEAK"},
            window_start=NORMAL_START, window_end=NORMAL_END, eta=NORMAL_ETA)
        # The assignment is already CONFIRMED (and beyond) by the time the job is ON_SITE.
        asg_id = scenario["assignment"]["id"]
        resp = api.confirm_assignment(asg_id, DISP)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_cancel_already_cancelled_job_rejected(self, api):
        """PRD §3.7: "A `Dispatcher` (or an `OfficeManager`) may **cancel** a job at
        any pre-completion stage ... moving it to `CANCELLED`, a terminal state."
        PRD §2.6: "State validity comes fifth: a target resource not in a legal state
        for the requested transition yields `ERR_INVALID_STATE`."

        Design: Corner/state_machines/cancel_already_cancelled_job_terminal_lockdown
        """
        customer = create_customer(credit_limit_cents=100000)
        job = create_service_job(customer["id"], category="LEAK")
        validate_success(api.cancel_job(job["id"], DISP))

        resp = api.cancel_job(job["id"], DISP)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
        reread = get_success_data(api.get_service_job(job["id"], DISP))
        assert reread["status"] == "CANCELLED", "job stays CANCELLED after a rejected re-cancel"

    def test_new_estimate_starts_in_draft(self, api):
        """PRD §3.3: "Creating an estimate against a job produces an `Estimate` in
        `DRAFT` status linked to the job by `job_id`".
        PRD §3.3: "a family of computed money fields all defaulting to 0:
        `labor_subtotal_cents`, `parts_subtotal_cents`, `discount_cents`,
        `trip_fee_cents`, `emergency_surcharge_cents`, and `estimate_total_cents`."

        Design: Corner/state_machines/initial_state_of_new_estimate_is_draft
        """
        scenario = setup_on_site_job(
            customer_overrides={"credit_limit_cents": 100000},
            technician_overrides={"skill_level": 3},
            job_overrides={"category": "LEAK"},
            window_start=NORMAL_START, window_end=NORMAL_END, eta=NORMAL_ETA)
        job = scenario["job"]
        tech_id = scenario["technician"]["id"]
        estimate = create_estimate_on_job(job["id"], job["version"], tech_id)
        assert estimate["status"] == "DRAFT", \
            f"new estimate must be DRAFT, got {estimate['status']}"
        assert estimate["estimate_total_cents"] == 0, \
            f"new estimate total defaults 0, got {estimate['estimate_total_cents']}"


class TestPermitReapplyCycle:
    def test_reissue_failed_permit_increments_reapply_count(self, api):
        """PRD §3.5: "A failed permit can be reissued: issuing a failed permit moves
        it `FAILED → ISSUED` and increments its `reapply_count` by one, so the permit
        can cycle back through scheduling and inspection."

        Design: Corner/state_machines/permit_reapply_cycle_failed_to_issued_increments_count
        """
        inspector = create_inspector(jurisdiction="CITY03", max_daily_inspections=4)
        fr = create_flat_rate_item(code="RC-PMT", category="WATER_HEATER",
                                   base_price_cents=40000, skill_required=2,
                                   requires_permit=True)
        scenario = setup_authorized_job(
            flat_rate_lines=[{"item": fr, "quantity": 1}],
            customer_overrides={"service_address": "CITY03",
                                "credit_limit_cents": 1000000},
            technician_overrides={"skill_level": 3, "licensed_for_permits": True},
            job_overrides={"category": "WATER_HEATER"},
            window_start=NORMAL_START, window_end=NORMAL_END, eta=NORMAL_ETA)

        permit = get_job_permit(scenario["job"]["id"])
        permit = issue_permit(permit["id"])
        visit = schedule_inspection(permit["id"], inspector["id"], "2026-06-16")
        record_inspection(visit["id"], "FAILED")

        reissued = validate_success(api.issue_permit(permit["id"], OM))
        assert reissued["status"] == "ISSUED", \
            f"FAILED permit reissues to ISSUED, got {reissued['status']}"
        assert reissued["reapply_count"] == 1, \
            f"reapply_count increments to 1, got {reissued['reapply_count']}"


class TestCancelCascade:
    def test_cancel_job_cascades_confirmed_assignment_to_cancelled(self, api):
        """PRD §3.7: "Any dispatch assignment of the job that is not already terminal
        is set to `CANCELLED` — a conditional cascade that leaves already-terminal
        (`CLOSED` or `CANCELLED`) assignments untouched."

        Design: Corner/state_machines/cancel_job_cascades_assignment_cancel_conditional
        """
        customer = create_customer(credit_limit_cents=100000)
        technician = create_technician(skill_level=3)
        job = create_service_job(customer["id"], category="LEAK")
        asg, _job_on = self._dispatch_and_confirm(api, job, technician["id"])

        validate_success(api.cancel_job(job["id"], DISP))
        reread_job = get_success_data(api.get_service_job(job["id"], DISP))
        assert reread_job["status"] == "CANCELLED"
        reread_asg = get_success_data(api.get_dispatch_assignment(asg["id"], DISP))
        assert reread_asg["status"] == "CANCELLED", \
            f"the CONFIRMED assignment must cascade to CANCELLED, got {reread_asg['status']}"

    @staticmethod
    def _dispatch_and_confirm(api, job, technician_id):
        from test_helpers import propose_assignment
        asg = propose_assignment(job["id"], technician_id, job["version"],
                                 NORMAL_START, NORMAL_END, NORMAL_ETA)
        get_success_data(api.confirm_assignment(asg["id"], DISP))
        return asg, None
