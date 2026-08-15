"""Household goods: survey buffer, estimate cycle, vendor suspension, ratings, OCC."""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_employee_headers,
    make_vendor_headers,
    assert_case_ledger,
    assert_timestamp_equals_instant,
    assert_vendor,
    create_vendor,
    create_assignment,
    schedule_survey,
    submit_estimate,
    approve_estimate,
    create_assignment_in_state,
    setup_case_with_vendor,
    setup_paid_move,
    rate_assignment,
    create_travel_booking,
    confirm_booking,
    set_clock,
    get_case,
    get_case_version,
    DATES,
)

MC = TEST_USERS["coordinator_headers"]
FIN = TEST_USERS["finance_headers"]


class TestEstimateRejection:
    def test_reject_estimate_clears_survey_fields(self):
        """PRD §3.3: "A coordinator may instead reject the estimate, returning
        the assignment `ESTIMATE_SUBMITTED` → `REQUESTED` and clearing both
        `survey_at` and `estimated_cents` — the assignment must then be
        scheduled and estimated anew."

        Design: Corner/state_machines/reject_estimate_clears_survey_fields
        """
        ctx = setup_case_with_vendor({"name": "Clear Carriers"})
        case_id = ctx["case"]["id"]
        vendor_id = ctx["vendor"]["id"]
        ma = create_assignment_in_state(case_id, vendor_id, "ESTIMATE_SUBMITTED",
                                        estimated_cents=95000)
        assert ma["survey_at"] is not None and ma["estimated_cents"] == 95000

        rejected = get_success_data(api_client.reject_estimate(ma["id"], MC))
        assert rejected["status"] == "REQUESTED"
        assert rejected["survey_at"] is None
        assert rejected["estimated_cents"] is None
        assert_case_ledger(get_case(case_id), committed=0, paid=0, released=0)

    def test_move_assignment_reestimate_cycle(self):
        """PRD §3.3: "A coordinator may instead reject the estimate, returning
        the assignment `ESTIMATE_SUBMITTED` → `REQUESTED` and clearing both
        `survey_at` and `estimated_cents` — the assignment must then be
        scheduled and estimated anew."
        PRD §3.3: "Approval commits `estimated_cents` into the case's committed
        column and increments both the assignment's and the case's `version`."

        Design: Difficulty/non_linear_state_machine/move_assignment_reestimate_cycle
        """
        ctx = setup_case_with_vendor({"name": "Loop Logistics"})
        case_id = ctx["case"]["id"]
        vendor_id = ctx["vendor"]["id"]

        ma = create_assignment(case_id, vendor_id)
        schedule_survey(ma["id"], "2026-08-10T10:00:00Z")
        submit_estimate(ma["id"], vendor_id, 95000)

        rejected = get_success_data(api_client.reject_estimate(ma["id"], MC))
        assert rejected["status"] == "REQUESTED"
        assert rejected["survey_at"] is None
        assert rejected["estimated_cents"] is None

        # Second loop: schedule and estimate anew, then approve.
        schedule_survey(ma["id"], "2026-08-12T10:00:00Z")
        submit_estimate(ma["id"], vendor_id, 88000)
        approved = approve_estimate(ma["id"], case_id)
        assert approved["status"] == "ESTIMATE_APPROVED"
        assert approved["estimated_cents"] == 88000
        # Only the second estimate entered the ledger; the rejected 95000 did not.
        assert_case_ledger(get_case(case_id), committed=88000, paid=0, released=0)

    def test_reestimate_cycle_requires_fresh_survey_each_loop(self):
        """PRD §3.3: "The owning vendor — the caller whose `X-User-ID` equals
        the assignment's `vendor_id` — submits `estimated_cents`, moving the
        assignment `SURVEY_SCHEDULED` → `ESTIMATE_SUBMITTED`."
        PRD §2.10: "State validity**: the target resource is in a legal source
        state for the requested transition (`ERR_INVALID_STATE`, HTTP 409)"

        Design: Difficulty/non_linear_state_machine/move_assignment_reestimate_cycle
        """
        ctx = setup_case_with_vendor({"name": "Cycle Carriers"})
        case_id = ctx["case"]["id"]
        vendor_id = ctx["vendor"]["id"]

        ma = create_assignment_in_state(case_id, vendor_id, "ESTIMATE_SUBMITTED",
                                        estimated_cents=95000)
        get_success_data(api_client.reject_estimate(ma["id"], MC))

        # After rejection the assignment is REQUESTED: a vendor estimate is not
        # a legal transition until a fresh survey is scheduled.
        resp = api_client.submit_estimate(
            ma["id"], {"estimated_cents": 90000}, make_vendor_headers(vendor_id))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        schedule_survey(ma["id"], "2026-08-12T10:00:00Z")
        submit_estimate(ma["id"], vendor_id, 90000)
        get_success_data(api_client.reject_estimate(ma["id"], MC))
        schedule_survey(ma["id"], "2026-08-14T10:00:00Z")
        submit_estimate(ma["id"], vendor_id, 70000)
        approved = approve_estimate(ma["id"], case_id)
        assert approved["status"] == "ESTIMATE_APPROVED"
        assert approved["estimated_cents"] == 70000
        assert_case_ledger(get_case(case_id), committed=70000, paid=0, released=0)


class TestVendorSurveyBuffer:
    def test_vendor_survey_two_hour_buffer(self):
        """PRD §3.3: "the vendor must not already hold another assignment in
        `SURVEY_SCHEDULED` whose survey time falls less than two hours before or
        after the requested one — a conflict is rejected with
        `ERR_SURVEY_CONFLICT`, while surveys exactly two hours apart are
        permitted."

        Design: Difficulty/resource_temporal_overlap/vendor_survey_two_hour_buffer
        """
        ctx = setup_case_with_vendor({"name": "Buffer Bros"})
        case_id = ctx["case"]["id"]
        vendor_id = ctx["vendor"]["id"]
        create_assignment_in_state(case_id, vendor_id, "SURVEY_SCHEDULED",
                                   survey_at="2026-08-10T10:00:00Z")
        ma2 = create_assignment(case_id, vendor_id)

        # 1.5 hours after: inside the buffer.
        resp = api_client.schedule_survey(
            ma2["id"], {"survey_at": "2026-08-10T11:30:00Z"}, MC)
        validate_error(resp, ApiErrorId.ERR_SURVEY_CONFLICT)
        assert validate_success(api_client.get_move_assignment(ma2["id"], MC))["status"] == "REQUESTED"

        # Exactly two hours after: permitted. The recorded instant is the
        # requested one (fractional-digit rendering is a serializer choice).
        scheduled = get_success_data(api_client.schedule_survey(
            ma2["id"], {"survey_at": "2026-08-10T12:00:00Z"}, MC))
        assert scheduled["status"] == "SURVEY_SCHEDULED"
        assert_timestamp_equals_instant(scheduled["survey_at"], 2026, 8, 10, 12, 0)

    def test_vendor_survey_buffer_applies_before_existing_survey(self):
        """PRD §3.3: "the vendor must not already hold another assignment in
        `SURVEY_SCHEDULED` whose survey time falls less than two hours before or
        after the requested one — a conflict is rejected with
        `ERR_SURVEY_CONFLICT`, while surveys exactly two hours apart are
        permitted."

        Design: Difficulty/resource_temporal_overlap/vendor_survey_two_hour_buffer
        """
        ctx = setup_case_with_vendor({"name": "Before Bros"})
        case_id = ctx["case"]["id"]
        vendor_id = ctx["vendor"]["id"]
        create_assignment_in_state(case_id, vendor_id, "SURVEY_SCHEDULED",
                                   survey_at="2026-08-10T10:00:00Z")
        ma2 = create_assignment(case_id, vendor_id)

        # 1.5 hours before: inside the buffer.
        resp = api_client.schedule_survey(
            ma2["id"], {"survey_at": "2026-08-10T08:30:00Z"}, MC)
        validate_error(resp, ApiErrorId.ERR_SURVEY_CONFLICT)

        # Exactly two hours before: permitted. The recorded instant is the
        # requested one (fractional-digit rendering is a serializer choice).
        scheduled = get_success_data(api_client.schedule_survey(
            ma2["id"], {"survey_at": "2026-08-10T08:00:00Z"}, MC))
        assert scheduled["status"] == "SURVEY_SCHEDULED"
        assert_timestamp_equals_instant(scheduled["survey_at"], 2026, 8, 10, 8, 0)


class TestVendorSuspension:
    def test_create_assignment_with_suspended_vendor_rejected(self):
        """PRD §3.3: "Suspending a vendor flips its `status` to `SUSPENDED`,
        which blocks two things — creating new assignments for that vendor and
        scheduling new surveys — both rejected with `ERR_VENDOR_SUSPENDED`."

        Design: Corner/validations/create_assignment_with_suspended_vendor_rejected
        """
        ctx = setup_case_with_vendor({"name": "Shaky Shippers"})
        case_id = ctx["case"]["id"]
        vendor_id = ctx["vendor"]["id"]
        suspended = get_success_data(api_client.suspend_vendor(vendor_id, MC))
        assert suspended["status"] == "SUSPENDED"

        resp = api_client.create_move_assignment(
            {"case_id": case_id, "vendor_id": vendor_id}, MC)
        validate_error(resp, ApiErrorId.ERR_VENDOR_SUSPENDED)

        # Suspension also blocks scheduling a survey on an existing REQUESTED
        # assignment created before the suspension — covered here by creating
        # the assignment before suspending.
        vendor2 = create_vendor(name="Steady Shippers")
        ma = create_assignment(case_id, vendor2["id"])
        get_success_data(api_client.suspend_vendor(vendor2["id"], MC))
        resp = api_client.schedule_survey(
            ma["id"], {"survey_at": "2026-08-10T10:00:00Z"}, MC)
        validate_error(resp, ApiErrorId.ERR_VENDOR_SUSPENDED)


class TestRatings:
    def test_rate_unpaid_assignment_rejected(self):
        """PRD §3.3: "Once an assignment is `PAID`, the relocating employee may
        record a `rating` — an integer from 1 to 5 — exactly once; a rating
        outside that range is rejected with `ERR_INVALID_REQUEST`, while rating
        an assignment that is not yet paid or already rated is rejected with
        `ERR_INVALID_STATE`."
        PRD §3.3: "`avg_rating_lifetime` is that sum divided by that count,
        rounded half up to two decimal places, and is null while the vendor has
        no ratings"

        Design: Corner/state_machines/rate_unpaid_assignment_rejected
        """
        ctx = setup_case_with_vendor({"name": "Rate Runners"})
        case_id = ctx["case"]["id"]
        vendor_id = ctx["vendor"]["id"]
        emp_id = ctx["employee"]["id"]
        ma = create_assignment_in_state(case_id, vendor_id, "DELIVERED",
                                        estimated_cents=80000)

        resp = api_client.rate_assignment(
            ma["id"], {"rating": 4}, make_employee_headers(emp_id))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        vendor = validate_success(api_client.get_vendor(vendor_id, MC))
        assert_vendor(vendor)
        assert vendor["rating_count"] == 0
        assert vendor["rating_sum"] == 0
        assert vendor["avg_rating_lifetime"] is None

    def test_vendor_avg_rating_lifetime_simple_average(self):
        """PRD §3.3: "Vendor performance aggregates derive from these ratings
        and are recomputed whenever a rating lands and whenever a vendor is
        read: `rating_sum` and `rating_count` cover all of the vendor's rated
        assignments; `avg_rating_lifetime` is that sum divided by that count,
        rounded half up to two decimal places, and is null while the vendor has
        no ratings; `avg_rating_rolling_12m` applies the same quotient
        restricted to assignments whose `rated_at` falls within the twelve
        months preceding the logical clock, the window boundary inclusive"
        PRD §3.3: "the vendor's `completed_moves` grows by one"

        Design: Corner/calculations/vendor_avg_rating_lifetime_simple_average
        """
        ctx = setup_paid_move(vendor_name="Avg Movers", first_estimate=80000,
                              survey_at="2026-08-10T10:00:00Z")
        case_id = ctx["case"]["id"]
        vendor_id = ctx["vendor"]["id"]
        emp_id = ctx["employee"]["id"]
        rate_assignment(ctx["assignment"]["id"], emp_id, 5)

        ma2 = create_assignment_in_state(case_id, vendor_id, "PAID",
                                         estimated_cents=70000,
                                         survey_at="2026-08-10T14:00:00Z")
        rate_assignment(ma2["id"], emp_id, 3)

        vendor = validate_success(api_client.get_vendor(vendor_id, MC))
        assert_vendor(vendor)
        assert vendor["rating_sum"] == 8
        assert vendor["rating_count"] == 2
        assert vendor["avg_rating_lifetime"] == pytest.approx(4.00, abs=0.005)
        # Both ratings sit inside the trailing twelve-month window.
        assert vendor["avg_rating_rolling_12m"] == pytest.approx(4.00, abs=0.005)
        assert vendor["completed_moves"] == 2

    def test_vendor_score_rolling_vs_lifetime_aged_out_rating(self):
        """PRD §3.3: "`avg_rating_rolling_12m` applies the same quotient
        restricted to assignments whose `rated_at` falls within the twelve
        months preceding the logical clock, the window boundary inclusive, and
        is null when nothing was rated inside the window. Because old ratings
        age out of the rolling window, identical rating histories can yield
        different rolling averages as time advances."

        Design: Difficulty/dual_variant_calc/vendor_score_rolling_vs_lifetime
        """
        ctx = setup_paid_move(vendor_name="Midwest Movers", first_estimate=80000,
                              survey_at="2026-08-10T10:00:00Z")
        case_id = ctx["case"]["id"]
        vendor_id = ctx["vendor"]["id"]
        emp_id = ctx["employee"]["id"]
        # Rating of 5 lands at the default clock 2026-08-01.
        rate_assignment(ctx["assignment"]["id"], emp_id, 5)

        ma2 = create_assignment_in_state(case_id, vendor_id, "PAID",
                                         estimated_cents=80000,
                                         survey_at="2026-08-10T14:00:00Z")
        # Advance thirteen months; the first rating is now outside the window.
        set_clock(DATES["THIRTEEN_MONTHS_LATER"])  # 2027-09-01
        rate_assignment(ma2["id"], emp_id, 1)

        vendor = validate_success(api_client.get_vendor(vendor_id, MC))
        assert vendor["rating_count"] == 2
        assert vendor["rating_sum"] == 6
        assert vendor["avg_rating_lifetime"] == pytest.approx(3.00, abs=0.005)
        # Window is [2026-09-01, 2027-09-01]; the 2026-08-01 rating aged out.
        assert vendor["avg_rating_rolling_12m"] == pytest.approx(1.00, abs=0.005)

    def test_vendor_rolling_window_boundary_is_inclusive(self):
        """PRD §3.3: "`avg_rating_rolling_12m` applies the same quotient
        restricted to assignments whose `rated_at` falls within the twelve
        months preceding the logical clock, the window boundary inclusive, and
        is null when nothing was rated inside the window."

        Design: Difficulty/dual_variant_calc/vendor_score_rolling_vs_lifetime
        """
        ctx = setup_paid_move(vendor_name="Boundary Movers", first_estimate=80000,
                              survey_at="2026-08-10T10:00:00Z")
        case_id = ctx["case"]["id"]
        vendor_id = ctx["vendor"]["id"]
        emp_id = ctx["employee"]["id"]

        ma2 = create_assignment_in_state(case_id, vendor_id, "PAID",
                                         estimated_cents=80000,
                                         survey_at="2026-08-10T14:00:00Z")
        # Rate the first assignment at exactly 2026-09-01 — the future window
        # start when the clock later reads 2027-09-01.
        set_clock(DATES["ROLLING_WINDOW_START"])  # 2026-09-01
        rate_assignment(ctx["assignment"]["id"], emp_id, 5)
        set_clock(DATES["THIRTEEN_MONTHS_LATER"])  # 2027-09-01
        rate_assignment(ma2["id"], emp_id, 3)

        vendor = validate_success(api_client.get_vendor(vendor_id, MC))
        assert vendor["rating_count"] == 2
        # Boundary-inclusive: the 2026-09-01 rating still counts at 2027-09-01.
        assert vendor["avg_rating_rolling_12m"] == pytest.approx(4.00, abs=0.005)
        assert vendor["avg_rating_lifetime"] == pytest.approx(4.00, abs=0.005)


class TestAssignmentListing:
    def test_move_assignments_filtered_by_vendor(self):
        """PRD §3.3: "The assignment collection is listed with optional
        `case_id`, `vendor_id`, and `status` filters."

        Design: Corner/endpoints/move_assignments_filtered_by_vendor
        """
        ctx = setup_case_with_vendor({"name": "Filter One"})
        case_id = ctx["case"]["id"]
        v1 = ctx["vendor"]["id"]
        v2 = create_vendor(name="Filter Two")["id"]
        ma1 = create_assignment(case_id, v1)
        create_assignment(case_id, v2)

        resp = api_client.list_move_assignments(MC, params={"vendor_id": v1})
        data, meta = validate_paginated(resp)
        assert meta["total_count"] == 1
        assert len(data) == 1
        assert data[0]["id"] == ma1["id"]
        assert data[0]["vendor_id"] == v1


class TestEstimateApprovalOcc:
    def test_stale_case_version_on_estimate_approve_returns_412(self):
        """PRD §2.9: "If the supplied value does not match the case's current
        `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412)
        and nothing is mutated — the client was necessarily reasoning over an
        outdated view of the case's remaining headroom."
        PRD §3.3: "Estimate approval by a coordinator is a guarded write: the
        request must carry `expected_case_version` matching the case's current
        `version`, with a stale value rejected as `ERR_STALE_VERSION`"

        Design: Corner/errors/stale_case_version_on_estimate_approve_returns_412
        """
        ctx = setup_case_with_vendor({"name": "Stale Shippers"})
        case_id = ctx["case"]["id"]
        vendor_id = ctx["vendor"]["id"]
        emp_id = ctx["employee"]["id"]
        ma = create_assignment_in_state(case_id, vendor_id, "ESTIMATE_SUBMITTED",
                                        estimated_cents=80000)
        booking = create_travel_booking(case_id, emp_id, 30000)
        stale_version = get_case_version(case_id)
        # An interleaved write (the booking confirm) advances the case version
        # past the captured value.
        confirm_booking(booking["id"])

        resp = api_client.approve_estimate(
            ma["id"], {"expected_case_version": stale_version}, MC)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        ma_after = validate_success(api_client.get_move_assignment(ma["id"], MC))
        assert ma_after["status"] == "ESTIMATE_SUBMITTED"
        # Only the confirmed booking's 30000 entered the committed column.
        assert_case_ledger(get_case(case_id), committed=30000, paid=0, released=0)

    def test_fresh_occ_version_succeeds_after_interleaved_write(self):
        """PRD §2.9: "Each of these requests must carry `expected_case_version`
        in its body, holding the `version` of the parent relocation case the
        client last observed."
        PRD §3.3: "Approval commits `estimated_cents` into the case's committed
        column and increments both the assignment's and the case's `version`."
        PRD §2.4: "`version` (integer): a system-managed integer that increments
        by exactly one on every mutation of the resource"

        Design: Corner/cross_cutting_complexity_layers/fresh_occ_version_succeeds_after_interleaved_write
        """
        ctx = setup_case_with_vendor({"name": "Occ Movers"})
        case_id = ctx["case"]["id"]
        vendor_id = ctx["vendor"]["id"]
        emp_id = ctx["employee"]["id"]
        ma = create_assignment_in_state(case_id, vendor_id, "ESTIMATE_SUBMITTED",
                                        estimated_cents=80000)
        booking = create_travel_booking(case_id, emp_id, 30000)
        confirm_booking(booking["id"])

        version_pre = get_case_version(case_id)
        approved = get_success_data(api_client.approve_estimate(
            ma["id"], {"expected_case_version": version_pre}, MC))
        assert approved["status"] == "ESTIMATE_APPROVED"

        case_after = get_case(case_id)
        assert case_after["version"] == version_pre + 1
        assert_case_ledger(case_after, committed=110000, paid=0, released=0)
