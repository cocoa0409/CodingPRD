"""Dispatch confirmation gates, permit/inspection scheduling, cross-entity state
dependencies, validation-priority conflicts, and the empty-estimate boundary.

These cover the confirm-time business gates (skill, license, route overlap), the
inspector daily aggregate capacity, the job->estimate and job->permit completion
preconditions, and the two priority-conflict instances where the higher-priority
check wins.
"""
import pytest

from test_helpers import (
    get_success_data, validate_success, validate_error, ApiErrorId,
    create_flat_rate_item, create_customer, create_technician,
    create_service_job, create_inspector, propose_assignment,
    setup_on_site_job, setup_authorized_job,
    setup_permit_job_issued, setup_permit_job_in_progress_scheduled,
    create_estimate_on_job, add_flat_rate_line, present_estimate,
    drive_job_to_on_site, start_work,
    get_job_permit, issue_permit, schedule_inspection,
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


class TestTechnicianRouteOverlap:
    def test_buffered_overlap_double_books_technician(self, api):
        """PRD §3.2: "no other assignment of this technician that is in `CONFIRMED`,
        `EN_ROUTE`, or `ON_SITE` status may overlap the requested
        `[window_start, window_end)` interval after that interval is expanded by the
        travel buffer on each side; an overlap is rejected with `ERR_TECH_DOUBLE_BOOKED`.
        The travel buffer between back-to-back jobs is a fixed thirty minutes".

        Design: Difficulty/resource_temporal_overlap/technician_assignment_buffered_pairwise_overlap
        """
        customer = create_customer(credit_limit_cents=1000000)
        technician = create_technician(skill_level=3)
        # First assignment 10:00-12:00 CONFIRMED.
        job_a = create_service_job(customer["id"], category="LEAK")
        asg_a = propose_assignment(job_a["id"], technician["id"], job_a["version"],
                                   "2026-06-15T10:00:00.000Z",
                                   "2026-06-15T12:00:00.000Z",
                                   "2026-06-15T10:15:00.000Z")
        validate_success(api.confirm_assignment(asg_a["id"], DISP))
        # Second assignment 12:25-14:00 — only 25 min after the first ends, inside the
        # 30-minute buffer, so it collides even though raw intervals do not overlap.
        job_b = create_service_job(customer["id"], category="DRAIN")
        asg_b = propose_assignment(job_b["id"], technician["id"], job_b["version"],
                                   "2026-06-15T12:25:00.000Z",
                                   "2026-06-15T14:00:00.000Z",
                                   "2026-06-15T12:30:00.000Z")
        resp = api.confirm_assignment(asg_b["id"], DISP)
        validate_error(resp, ApiErrorId.ERR_TECH_DOUBLE_BOOKED.value)
        reread = get_success_data(api.get_dispatch_assignment(asg_b["id"], DISP))
        assert reread["status"] == "PROPOSED", \
            "the rejected assignment stays PROPOSED"


class TestInspectorDailyCapacity:
    def test_inspector_daily_aggregate_capacity_full(self, api):
        """PRD §3.5: "the inspector must currently hold fewer than its
        `max_daily_inspections` visits in `PENDING` result on that `scheduled_date`,
        or the request is rejected with `ERR_INSPECTOR_CAPACITY_FULL`. This daily
        capacity is an aggregate count across all permits, evaluated per the requested
        date."

        Design: Difficulty/resource_temporal_overlap/inspector_daily_aggregate_capacity_full
        """
        inspector = create_inspector(jurisdiction="CITY02", max_daily_inspections=1)
        # First permit job: issue + schedule one PENDING inspection on 2026-06-20.
        s1 = setup_permit_job_issued(
            jurisdiction="CITY02",
            window_start="2026-06-15T10:00:00.000Z",
            window_end="2026-06-15T12:00:00.000Z",
            eta="2026-06-15T10:15:00.000Z",
            clock="2026-06-15T08:00:00.000Z")
        schedule_inspection(s1["permit"]["id"], inspector["id"], "2026-06-20")

        # Second permit job (same jurisdiction), issued and ready to schedule.
        s2 = setup_permit_job_issued(
            jurisdiction="CITY02",
            window_start="2026-06-15T13:00:00.000Z",
            window_end="2026-06-15T15:00:00.000Z",
            eta="2026-06-15T13:15:00.000Z")
        resp = api.schedule_inspection(
            s2["permit"]["id"],
            {"inspector_id": inspector["id"], "scheduled_date": "2026-06-20"}, OM)
        validate_error(resp, ApiErrorId.ERR_INSPECTOR_CAPACITY_FULL.value)
        reread = get_success_data(api.get_permit(s2["permit"]["id"], OM))
        assert reread["status"] == "ISSUED", \
            "the second permit stays ISSUED when capacity is full"


class TestCrossEntityStateDependency:
    def test_start_work_blocked_until_estimate_approved(self, api):
        """PRD §3.5: "Starting is permitted only when the job is `AUTHORIZED` and its
        `authorized_estimate_id` is not null and points at an estimate that is in
        `APPROVED` status — a cross-entity dependency where the job genuinely requires
        its estimate to be approved before work may begin."

        Design: Difficulty/cross_entity_state_dependency/start_work_blocked_until_estimate_approved_job_estimate
        """
        fr = create_flat_rate_item(code="CE-1", category="LEAK",
                                   base_price_cents=20000, skill_required=1)
        scenario = setup_on_site_job(
            customer_overrides={"credit_limit_cents": 100000},
            technician_overrides={"skill_level": 2},
            job_overrides={"category": "LEAK"},
            window_start=NORMAL_START, window_end=NORMAL_END, eta=NORMAL_ETA)
        tech_id = scenario["technician"]["id"]
        job = scenario["job"]
        tech_h = make_technician_headers(tech_id)
        # Build and PRESENT the estimate but do NOT approve: job stays ON_SITE.
        estimate = create_estimate_on_job(job["id"], job["version"], tech_id)
        add_flat_rate_line(estimate["id"], fr["id"], tech_id, 1)
        present_estimate(estimate["id"], tech_id)

        resp = api.start_work(job["id"], tech_h)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
        reread = get_success_data(api.get_service_job(job["id"], tech_h))
        assert reread["status"] == "ON_SITE", \
            "start-work on an unapproved (ON_SITE) job leaves it ON_SITE"

    def test_complete_blocked_until_permit_passed(self, api):
        """PRD §3.5: "if any permit exists for the job, that permit's status must be
        `PASSED` (a cross-entity dependency where the job requires its permit to have
        passed inspection)".

        Design: Difficulty/cross_entity_state_dependency/complete_blocked_until_permit_passed_job_permit
        """
        inspector = create_inspector(jurisdiction="CITY01", max_daily_inspections=4)
        scenario = setup_permit_job_in_progress_scheduled(
            jurisdiction="CITY01", inspector_id=inspector["id"],
            scheduled_date="2026-06-16",
            window_start=NORMAL_START, window_end=NORMAL_END, eta=NORMAL_ETA,
            clock="2026-06-15T12:00:00.000Z")
        # Permit is INSPECTION_SCHEDULED (not PASSED) and the job is IN_PROGRESS.
        tech_id = scenario["technician"]["id"]
        tech_h = make_technician_headers(tech_id)
        resp = api.complete_job(scenario["job"]["id"], {"consumed_parts": []}, tech_h)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
        reread = get_success_data(api.get_service_job(scenario["job"]["id"], tech_h))
        assert reread["status"] == "IN_PROGRESS", \
            "completion blocked by an un-passed permit leaves the job IN_PROGRESS"


class TestValidationPriorityConflicts:
    def test_approve_state_check_beats_credit_check(self, api):
        """PRD §2.6: "State validity comes fifth: a target resource not in a legal
        state for the requested transition yields `ERR_INVALID_STATE`. ... Only after
        all of these pass does the system evaluate the domain-specific business rules
        — skill, licensing, route overlap, inspector capacity, estimate non-emptiness,
        stock sufficiency, warranty, and credit".
        PRD §3.4: "Approval is permitted only when the estimate is in `PRESENTED`
        status and the job is `ON_SITE`."

        Design: Difficulty/priority_pair_validation_conflict/approve_state_beats_credit_fiscal
        """
        fr = create_flat_rate_item(code="PC-1", category="LEAK",
                                   base_price_cents=40000, skill_required=1)
        scenario = setup_on_site_job(
            customer_overrides={"credit_limit_cents": 1000},  # far below 40000
            technician_overrides={"skill_level": 2},
            job_overrides={"category": "LEAK"},
            window_start=NORMAL_START, window_end=NORMAL_END, eta=NORMAL_ETA)
        tech_id = scenario["technician"]["id"]
        cust_id = scenario["customer"]["id"]
        job = scenario["job"]
        estimate = create_estimate_on_job(job["id"], job["version"], tech_id)
        add_flat_rate_line(estimate["id"], fr["id"], tech_id, 1)
        present_estimate(estimate["id"], tech_id)
        # Customer declines -> estimate DECLINED. Both the state check (not PRESENTED)
        # and the credit check (1000 < total) would fail; state must win.
        cust_h = make_customer_headers(cust_id)
        validate_success(api.decline_estimate(estimate["id"], cust_h))

        resp = api.approve_estimate(estimate["id"], cust_h)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
        body = resp.json()
        assert body["data"]["error_id"] != ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED.value, \
            "state error must pre-empt the credit error"

    def test_confirm_skill_check_beats_double_booked_check(self, api):
        """PRD §2.6: "structural and state checks always precede business checks, and
        within the business tier the specific rule that fires is determined by the
        operation in question."
        PRD §3.2: "the technician's `skill_level` must be greater than or equal to the
        maximum `skill_required` across the flat-rate work the job intends; if the
        technician's skill falls below that ceiling, the request is rejected with
        `ERR_SKILL_INSUFFICIENT`."

        Design: Difficulty/priority_pair_validation_conflict/confirm_skill_safety_beats_double_booked_temporal
        """
        customer = create_customer(credit_limit_cents=1000000)
        technician = create_technician(skill_level=1)
        fr_hi = create_flat_rate_item(code="SK-HI", category="REPIPE",
                                      base_price_cents=50000, skill_required=3)
        # Job A: confirmed 11:00-13:00 to occupy the technician's route.
        job_a = create_service_job(customer["id"], category="DRAIN")
        asg_a = propose_assignment(job_a["id"], technician["id"], job_a["version"],
                                   "2026-05-25T11:00:00.000Z",
                                   "2026-05-25T13:00:00.000Z",
                                   "2026-05-25T11:15:00.000Z")
        validate_success(api.confirm_assignment(asg_a["id"], DISP))
        # Job B: overlapping window 12:00-14:00 AND a skill-3 line the skill-1 tech
        # cannot do. Skill (priority 7) must win over double-booked (priority 9).
        job_b = create_service_job(customer["id"], category="REPIPE")
        asg_b_resp = api.create_dispatch_assignment(
            {"job_id": job_b["id"], "technician_id": technician["id"],
             "window_start": "2026-05-25T12:00:00.000Z",
             "window_end": "2026-05-25T14:00:00.000Z",
             "eta": "2026-05-25T12:15:00.000Z",
             "expected_job_version": job_b["version"]}, DISP)
        asg_b = get_success_data(asg_b_resp)
        job_b_v1 = get_success_data(api.get_service_job(job_b["id"], DISP))["version"]
        tech_h = make_technician_headers(technician["id"])
        estimate = create_estimate_on_job(job_b["id"], job_b_v1, technician["id"])
        add_flat_rate_line(estimate["id"], fr_hi["id"], technician["id"], 1)

        resp = api.confirm_assignment(asg_b["id"], DISP)
        validate_error(resp, ApiErrorId.ERR_SKILL_INSUFFICIENT.value)
        body = resp.json()
        assert body["data"]["error_id"] != ApiErrorId.ERR_TECH_DOUBLE_BOOKED.value, \
            "skill (safety) error must pre-empt the temporal double-booked error"


class TestEmptyEstimateBoundary:
    def test_present_empty_estimate_rejected(self, api):
        """PRD §3.3: "an estimate with no lines at all cannot be presented and is
        rejected with `ERR_EMPTY_ESTIMATE`."

        Design: Difficulty/boundary_precision_check/present_empty_estimate_zero_lines_rejected
        """
        scenario = setup_on_site_job(
            customer_overrides={"credit_limit_cents": 100000},
            technician_overrides={"skill_level": 2},
            job_overrides={"category": "DRAIN"},
            window_start=NORMAL_START, window_end=NORMAL_END, eta=NORMAL_ETA)
        tech_id = scenario["technician"]["id"]
        job = scenario["job"]
        tech_h = make_technician_headers(tech_id)
        estimate = create_estimate_on_job(job["id"], job["version"], tech_id)
        # No lines added.
        resp = api.present_estimate(estimate["id"], tech_h)
        validate_error(resp, ApiErrorId.ERR_EMPTY_ESTIMATE.value)
        reread = get_success_data(api.get_estimate(estimate["id"], OM))
        assert reread["status"] == "DRAFT", "a rejected present leaves the estimate DRAFT"


class TestConfirmationGatesCorners:
    def test_confirm_off_duty_technician_rejected(self, api):
        """PRD §3.2: "the assigned technician's availability `status` must be
        `AVAILABLE` or `ON_CALL` — a technician that is `OFF_DUTY` cannot be confirmed
        onto the job."
        PRD §2.6: "State validity comes fifth: a target resource not in a legal state
        for the requested transition yields `ERR_INVALID_STATE`."

        Design: Corner/validations/confirm_unavailable_technician_returns_invalid_state
        """
        customer = create_customer(credit_limit_cents=100000)
        technician = create_technician(skill_level=3)
        job = create_service_job(customer["id"], category="LEAK")
        asg = propose_assignment(job["id"], technician["id"], job["version"],
                                 NORMAL_START, NORMAL_END, NORMAL_ETA)
        validate_success(api.set_technician_status(
            technician["id"], {"status": "OFF_DUTY"}, DISP))
        resp = api.confirm_assignment(asg["id"], DISP)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
        reread = get_success_data(api.get_dispatch_assignment(asg["id"], DISP))
        assert reread["status"] == "PROPOSED"

    def test_confirm_unlicensed_technician_for_permit_job_rejected(self, api):
        """PRD §3.2: "if the job requires a permit, the technician's
        `licensed_for_permits` must be true, or the request is rejected with
        `ERR_LICENSE_REQUIRED`."

        Design: Corner/validations/confirm_unlicensed_technician_for_permit_job_returns_license_required
        """
        fr = create_flat_rate_item(code="UL-PMT", category="WATER_HEATER",
                                   base_price_cents=40000, skill_required=2,
                                   requires_permit=True)
        customer = create_customer(credit_limit_cents=1000000)
        technician = create_technician(skill_level=5, licensed_for_permits=False)
        job = create_service_job(customer["id"], category="WATER_HEATER")
        asg = propose_assignment(job["id"], technician["id"], job["version"],
                                 NORMAL_START, NORMAL_END, NORMAL_ETA)
        job_v1 = get_success_data(api.get_service_job(job["id"], DISP))["version"]
        tech_id = technician["id"]
        estimate = create_estimate_on_job(job["id"], job_v1, tech_id)
        add_flat_rate_line(estimate["id"], fr["id"], tech_id, 1)
        # A DRAFT estimate carries the requires_permit line: the job requires a permit.
        resp = api.confirm_assignment(asg["id"], DISP)
        validate_error(resp, ApiErrorId.ERR_LICENSE_REQUIRED.value)
        reread = get_success_data(api.get_dispatch_assignment(asg["id"], DISP))
        assert reread["status"] == "PROPOSED"

    def test_schedule_inspection_jurisdiction_mismatch_rejected(self, api):
        """PRD §3.5: "the chosen inspector's `jurisdiction` must equal the permit's
        `jurisdiction`, or the request is rejected with `ERR_LICENSE_REQUIRED`".

        Design: Corner/validations/schedule_inspection_jurisdiction_mismatch_returns_license_required
        """
        wrong_inspector = create_inspector(jurisdiction="CITY99",
                                           max_daily_inspections=4)
        scenario = setup_permit_job_issued(
            jurisdiction="CITY04",
            window_start=NORMAL_START, window_end=NORMAL_END, eta=NORMAL_ETA,
            clock="2026-06-15T08:00:00.000Z")
        resp = api.schedule_inspection(
            scenario["permit"]["id"],
            {"inspector_id": wrong_inspector["id"], "scheduled_date": "2026-06-16"}, OM)
        validate_error(resp, ApiErrorId.ERR_LICENSE_REQUIRED.value)
        reread = get_success_data(api.get_permit(scenario["permit"]["id"], OM))
        assert reread["status"] == "ISSUED", "the permit stays ISSUED on a rejected schedule"

    def test_complete_with_insufficient_stock_rejected(self, api):
        """PRD §3.5: "for every consumed part, the acting technician's truck-stock
        `quantity` for that part must be greater than or equal to the units claimed
        consumed. A claim to consume more than the truck holds is rejected with
        `ERR_INSUFFICIENT_STOCK`."

        Design: Corner/validations/complete_with_insufficient_stock_returns_error
        """
        from test_helpers import create_part, create_truck_stock
        part = create_part(sku="STK-1", name="Elbow", list_price_cents=200)
        fr = create_flat_rate_item(code="STK-FR", category="REPIPE",
                                   base_price_cents=20000, skill_required=1)
        customer = create_customer(credit_limit_cents=1000000)
        technician = create_technician(skill_level=2)
        ts = create_truck_stock(technician["id"], part["id"], quantity=3, reorder_point=1)
        job = create_service_job(customer["id"], category="REPIPE")
        _asg, job_on_site = drive_job_to_on_site(
            job, technician["id"], NORMAL_START, NORMAL_END, NORMAL_ETA)
        estimate = create_estimate_on_job(job["id"], job_on_site["version"], technician["id"])
        add_flat_rate_line(estimate["id"], fr["id"], technician["id"], 1)
        from test_helpers import add_part_line, approve_estimate
        add_part_line(estimate["id"], part["id"], technician["id"], 5)
        present_estimate(estimate["id"], technician["id"])
        approve_estimate(estimate["id"], customer["id"])
        start_work(job["id"], technician["id"])

        tech_h = make_technician_headers(technician["id"])
        resp = api.complete_job(
            job["id"], {"consumed_parts": [{"part_id": part["id"], "units": 5}]}, tech_h)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_STOCK.value)
        reread_ts = get_success_data(api.get_truck_stock(ts["id"], OM))
        assert reread_ts["quantity"] == 3, "no decrement occurs on a rejected completion"
        reread_job = get_success_data(api.get_service_job(job["id"], DISP))
        assert reread_job["status"] == "IN_PROGRESS"


class TestDispatchEndpointCorners:
    def test_window_end_before_start_rejected(self, api):
        """PRD §3.2: "The `window_end` must be strictly after the `window_start`; a
        window whose end is at or before its start is rejected with `ERR_VALIDATION`."

        Design: Corner/endpoints/window_end_before_start_returns_validation
        """
        customer = create_customer(credit_limit_cents=100000)
        technician = create_technician(skill_level=3)
        job = create_service_job(customer["id"], category="LEAK")
        resp = api.create_dispatch_assignment(
            {"job_id": job["id"], "technician_id": technician["id"],
             "window_start": "2026-06-15T12:00:00.000Z",
             "window_end": "2026-06-15T11:00:00.000Z",
             "eta": "2026-06-15T11:30:00.000Z",
             "expected_job_version": job["version"]}, DISP)
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)

    def test_part_line_without_part_id_rejected(self, api):
        """PRD §3.3: "A line whose type and reference do not agree — a `FLAT_RATE`
        line missing its flat-rate item, or a `PART` line missing its part — is
        rejected with `ERR_INVALID_REQUEST`."

        Design: Corner/endpoints/estimate_line_part_without_part_id_returns_invalid_request
        """
        scenario = setup_on_site_job(
            customer_overrides={"credit_limit_cents": 100000},
            technician_overrides={"skill_level": 3},
            job_overrides={"category": "LEAK"},
            window_start=NORMAL_START, window_end=NORMAL_END, eta=NORMAL_ETA)
        tech_id = scenario["technician"]["id"]
        job = scenario["job"]
        tech_h = make_technician_headers(tech_id)
        estimate = create_estimate_on_job(job["id"], job["version"], tech_id)
        resp = api.add_estimate_line(
            estimate["id"], {"line_type": "PART", "quantity": 1}, tech_h)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_technician_truck_stock_reverse_reachability(self, api):
        """PRD §4 (routing): "GET `/plumbing/technicians/{id}/truck-stock` List a
        technician's truck-stock rows".
        PRD §3.1: "A `TruckStock` row names a `technician_id` (the truck the stock
        lives on) and a `part_id` (the stocked part)".

        Design: Corner/endpoints/truck_stock_reverse_reachability_by_technician
        """
        from test_helpers import create_part, create_truck_stock
        part1 = create_part(sku="RR-1", name="Pipe A", list_price_cents=100)
        part2 = create_part(sku="RR-2", name="Pipe B", list_price_cents=200)
        technician = create_technician(skill_level=2)
        create_truck_stock(technician["id"], part1["id"], quantity=5)
        create_truck_stock(technician["id"], part2["id"], quantity=7)
        resp = api.list_technician_truck_stock(technician["id"], DISP)
        data, meta = self._paginated(resp)
        assert meta.get("total_count") == 2, \
            f"the technician has two stocked parts, got total_count {meta.get('total_count')}"

    @staticmethod
    def _paginated(response):
        body = response.json()
        return body.get("data", []), body.get("meta", {})
