"""Appointments: scheduling window, half-open auditor-calendar overlap,
supersession, no-show rescheduling cap, and error precedence."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_appointment_payload,
    create_auditor,
    create_class_code,
    create_policy,
    find_work_order,
    get_success_data,
    get_work_order,
    make_auditor_headers,
    no_show_appointment,
    refresh_work_order,
    run_selection,
    schedule_appointment,
    setup_selected_work_order,
    validate_error,
    validate_success,
    wo_version,
)

MANAGER = TEST_USERS["audit_manager_headers"]


def _setup_three_physical_work_orders(api, prefix="WC-1600"):
    """Three same-state PHYSICAL work orders sharing one auditor."""
    cc = create_class_code()
    policies = [
        create_policy(f"{prefix}{suffix}", [cc["id"]],
                      estimated_annual_premium_cents=2000000,
                      minimum_premium_cents=100000)
        for suffix in ("A", "B", "C")
    ]
    auditor = create_auditor()
    run_selection()
    auditor_headers = make_auditor_headers(auditor["id"])
    orders = {}
    for suffix, pol in zip(("A", "B", "C"), policies):
        wo = find_work_order(pol["id"])
        get_success_data(api.assign_work_order(
            wo["id"], {"auditor_id": auditor["id"]}, MANAGER))
        get_success_data(api.create_records_request(
            wo["id"], {"request_type": "PAYROLL_SUMMARY"}, MANAGER))
        orders[suffix] = wo
    return auditor, auditor_headers, orders


def _create_appointment(api, work_order_id, start, end, auditor_headers,
                        location="INSURED_PREMISES"):
    """Create an appointment, threading the current work-order version."""
    version = get_work_order(work_order_id)["version"]
    return api.create_appointment(
        work_order_id,
        create_appointment_payload(scheduled_start=start, scheduled_end=end,
                                   location_type=location,
                                   expected_work_order_version=version),
        auditor_headers)


class TestAuditorCalendarOverlap:
    def test_auditor_calendar_back_to_back_allowed(self, api):
        """PRD: "The auditor's calendar must be free: across **all** work
        orders of any policy, the auditor's `SCHEDULED` and `CONFIRMED`
        appointments are treated as half-open intervals, and a conflict exists
        exactly when the new appointment starts before an existing one ends
        while that existing one starts before the new one ends — back-to-back
        placement (the new start equal to an existing end) does **not**
        conflict."
        PRD: "In contrast, an auditor's calendar treats appointment intervals
        as *half-open* — the start counts, the end does not — so back-to-back
        appointments never conflict."

        Design: Difficulty/resource_temporal_overlap/auditor_calendar_half_open_overlap
        """
        _aud, aud_headers, orders = _setup_three_physical_work_orders(api)

        appt_a = validate_success(_create_appointment(
            api, orders["A"]["id"], "2026-08-10T09:00:00Z",
            "2026-08-10T11:00:00Z", aud_headers), 201)

        resp = _create_appointment(api, orders["B"]["id"],
                                   "2026-08-10T11:00:00Z",
                                   "2026-08-10T12:00:00Z", aud_headers,
                                   location="VIRTUAL")
        appt_b = validate_success(resp, 201)
        assert appt_b["status"] == "SCHEDULED", (
            "A new appointment starting exactly at the existing appointment's "
            "end must not conflict (half-open intervals)")
        assert appt_b["auditor_id"] == appt_a["auditor_id"]

    def test_auditor_calendar_true_overlap_rejected(self, api):
        """PRD: "a conflict exists exactly when the new appointment starts
        before an existing one ends while that existing one starts before the
        new one ends — back-to-back placement (the new start equal to an
        existing end) does **not** conflict. Conflicts are rejected with
        `ERR_APPOINTMENT_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/auditor_calendar_half_open_overlap
        """
        _aud, aud_headers, orders = _setup_three_physical_work_orders(api)

        validate_success(_create_appointment(
            api, orders["A"]["id"], "2026-08-10T09:00:00Z",
            "2026-08-10T11:00:00Z", aud_headers), 201)

        resp = _create_appointment(api, orders["C"]["id"],
                                   "2026-08-10T10:30:00Z",
                                   "2026-08-10T12:00:00Z", aud_headers,
                                   location="VIRTUAL")
        validate_error(resp, ApiErrorId.ERR_APPOINTMENT_OVERLAP)


class TestAppointmentErrorPrecedence:
    def _setup_two_window_orders(self, api):
        """WC-1100A's appointment window runs to 2026-09-29; WC-1100B's ended
        2026-07-30. Both share one auditor; A holds 2026-08-10 09:00-11:00."""
        cc = create_class_code()
        pol_a = create_policy("WC-1100A", [cc["id"]],
                              estimated_annual_premium_cents=2000000,
                              minimum_premium_cents=100000)
        pol_b = create_policy("WC-1100B", [cc["id"]],
                              effective_date="2025-12-01T00:00:00Z",
                              expiration_date="2026-05-31T00:00:00Z",
                              estimated_annual_premium_cents=2000000,
                              minimum_premium_cents=100000)
        auditor = create_auditor()
        run_selection()
        aud_headers = make_auditor_headers(auditor["id"])
        wo_a = find_work_order(pol_a["id"])
        wo_b = find_work_order(pol_b["id"])
        for wo in (wo_a, wo_b):
            get_success_data(api.assign_work_order(
                wo["id"], {"auditor_id": auditor["id"]}, MANAGER))
            get_success_data(api.create_records_request(
                wo["id"], {"request_type": "PAYROLL_SUMMARY"}, MANAGER))
        appt_a = validate_success(_create_appointment(
            api, wo_a["id"], "2026-08-10T09:00:00Z", "2026-08-10T11:00:00Z",
            aud_headers), 201)
        return wo_b, aud_headers, appt_a

    def test_window_violation_reported_over_calendar_overlap(self, api):
        """PRD: "When several checks could reject the same request, the server
        evaluates them in a fixed order and returns the **first** matching
        failure:"
        PRD: "9. **Time windows** — appointment placement within the post-term
        window and dispute filing within its deadline; failures yield
        `ERR_APPOINTMENT_OUTSIDE_WINDOW` or `ERR_DISPUTE_WINDOW_CLOSED` (both
        409)."
        PRD: "10. **Business constraints** — the remaining domain guards, each
        with its own code: `ERR_APPOINTMENT_OVERLAP`,
        `ERR_ALLOCATION_PERIOD_OVERLAP`, `ERR_OPEN_RECORDS_REQUESTS`,
        `ERR_DRAFT_ALLOCATIONS_PENDING`, `ERR_RESCHEDULE_LIMIT_EXCEEDED`,
        `ERR_CERT_INSUFFICIENT_COVERAGE`, `ERR_CERT_WINDOW_INSUFFICIENT`,
        `ERR_AUDITOR_TERRITORY_MISMATCH`, `ERR_NO_NONCOMPLIANCE_BASIS`,
        `ERR_DUPLICATE_RECORDS_REQUEST`, `ERR_DUPLICATE_POLICY_NUMBER`, and
        `ERR_DUPLICATE_CLASS_CODE` (all 409)."

        Design: Difficulty/priority_pair_validation_conflict/appointment_temporal_vs_constraint_priority
        """
        wo_b, aud_headers, _appt_a = self._setup_two_window_orders(api)

        # Outside B's window (ended 2026-07-30) AND overlapping the auditor's
        # existing 09:00-11:00 appointment on A.
        resp = _create_appointment(api, wo_b["id"], "2026-08-10T10:00:00Z",
                                   "2026-08-10T12:00:00Z", aud_headers)
        error = validate_error(resp, ApiErrorId.ERR_APPOINTMENT_OUTSIDE_WINDOW)
        assert error["error_id"] != "ERR_APPOINTMENT_OVERLAP"

    def test_appointment_outside_window_isolated(self, api):
        """PRD: "The appointment must sit in the post-term window:
        `scheduled_start` strictly after `audit_period_end` and no later than
        sixty days after it, with `scheduled_end` strictly after
        `scheduled_start`; violations are rejected with
        `ERR_APPOINTMENT_OUTSIDE_WINDOW`."

        Design: Difficulty/priority_pair_validation_conflict/appointment_temporal_vs_constraint_priority
        """
        wo_b, aud_headers, _appt_a = self._setup_two_window_orders(api)

        # Outside B's window but not overlapping anything on the calendar.
        resp = _create_appointment(api, wo_b["id"], "2026-08-01T09:00:00Z",
                                   "2026-08-01T11:00:00Z", aud_headers)
        validate_error(resp, ApiErrorId.ERR_APPOINTMENT_OUTSIDE_WINDOW)


class TestNoShowRescheduleCycle:
    def _setup_two_no_shows(self, api):
        ctx = setup_selected_work_order(
            policy_number="WC-700", estimated_annual_premium_cents=2000000,
            minimum_premium_cents=100000)
        appt1 = schedule_appointment(ctx, "2026-08-10T09:00:00Z",
                                     "2026-08-10T11:00:00Z")
        no_show_appointment(ctx, appt1)
        appt2 = schedule_appointment(ctx, "2026-08-11T09:00:00Z",
                                     "2026-08-11T11:00:00Z",
                                     location_type="VIRTUAL")
        no_show_appointment(ctx, appt2)
        return ctx, appt1, appt2

    def test_two_no_show_cycles_keep_work_order_reschedulable(self, api):
        """PRD: "If the insured fails to appear, the appointment's auditor
        records a no-show from `SCHEDULED` or `CONFIRMED`, moving the
        appointment to `NO_SHOW`, incrementing the parent work order's
        `no_show_count` by one, and incrementing its `version`."
        PRD: "The assigned auditor schedules an appointment while the work
        order is `RECORDS_REQUESTED` (first appointment) or
        `APPOINTMENT_SCHEDULED` (rescheduling after a no-show)."

        Design: Difficulty/non_linear_state_machine/appointment_no_show_reschedule_cycle_with_cap
        """
        ctx, appt1, appt2 = self._setup_two_no_shows(api)

        wo = refresh_work_order(ctx)
        assert wo["no_show_count"] == 2
        assert wo["status"] == "APPOINTMENT_SCHEDULED", (
            "The no-show loop must not advance the work order")
        for appt in (appt1, appt2):
            current = validate_success(api.get_appointment(appt["id"], MANAGER))
            assert current["status"] == "NO_SHOW"

    def test_third_appointment_after_two_no_shows_rejected(self, api):
        """PRD: "The work order's `no_show_count` must still be below two; at
        two no-shows the insured has exhausted rescheduling and the attempt is
        rejected with `ERR_RESCHEDULE_LIMIT_EXCEEDED`."

        Design: Difficulty/non_linear_state_machine/appointment_no_show_reschedule_cycle_with_cap
        """
        ctx, _appt1, _appt2 = self._setup_two_no_shows(api)

        resp = api.create_appointment(
            ctx["work_order"]["id"],
            create_appointment_payload(
                scheduled_start="2026-08-12T09:00:00Z",
                scheduled_end="2026-08-12T11:00:00Z", location_type="VIRTUAL",
                expected_work_order_version=wo_version(ctx)),
            ctx["auditor_headers"])
        validate_error(resp, ApiErrorId.ERR_RESCHEDULE_LIMIT_EXCEEDED)


class TestAppointmentSideEffects:
    def test_appointment_supersede_cancels_previous(self, api):
        """PRD: "On success the appointment is created `SCHEDULED` with its
        `auditor_id` copied from the work order's `assigned_auditor_id` and
        linked via `audit_work_order_id`; any prior appointment of the same
        work order in `SCHEDULED` or `CONFIRMED` is automatically moved to
        `CANCELLED` (the new appointment supersedes it); the work order moves
        to `APPOINTMENT_SCHEDULED` and its `version` increments by one."

        Design: Corner/state_machines/appointment_supersede_cancels_previous
        """
        ctx = setup_selected_work_order(
            policy_number="WC-S6", estimated_annual_premium_cents=2000000,
            minimum_premium_cents=100000)
        appt1 = schedule_appointment(ctx, "2026-08-10T09:00:00Z",
                                     "2026-08-10T11:00:00Z")

        appt2 = schedule_appointment(ctx, "2026-08-12T09:00:00Z",
                                     "2026-08-12T11:00:00Z",
                                     location_type="VIRTUAL")

        old = validate_success(api.get_appointment(appt1["id"], MANAGER))
        assert old["status"] == "CANCELLED", (
            "The prior SCHEDULED appointment must be superseded")
        assert appt2["status"] == "SCHEDULED"
        assert ctx["work_order"]["status"] == "APPOINTMENT_SCHEDULED"

    def test_appointment_terminal_no_show_rejects_complete(self, api):
        """PRD: "`COMPLETED`, `NO_SHOW`, and `CANCELLED` are terminal for an
        appointment"
        PRD: "7. **State legality** — the target resource is in a from-state
        its state machine permits for the attempted transition, and terminal
        states reject everything; failure yields `ERR_INVALID_STATE_TRANSITION`
        (409)."

        Design: Corner/state_machines/appointment_terminal_no_show_rejects_complete
        """
        ctx = setup_selected_work_order(
            policy_number="WC-S4", estimated_annual_premium_cents=2000000,
            minimum_premium_cents=100000)
        appt = schedule_appointment(ctx)
        no_show_appointment(ctx, appt)

        resp = api.complete_appointment(appt["id"], ctx["auditor_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
