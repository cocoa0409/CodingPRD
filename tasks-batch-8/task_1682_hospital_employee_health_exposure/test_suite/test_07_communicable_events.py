"""Communicable-disease events and contact tracing."""
from test_helpers import (
    ApiErrorId,
    advance_event,
    assert_exposure_contact,
    assert_instant,
    create_event,
    enroll_contact,
    enroll_contact_payload,
    get_contact,
    get_employee,
    get_event,
    list_restrictions,
    make_staff_employee_headers,
    register_employee,
    set_clock,
    setup_tracing_event_with_contact,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestEventWindowConstants:
    def test_pertussis_constants_applied(self, api, safety_headers):
        """PRD §3.7: "The `infectious_start` is the `onset_date` shifted
        earlier by the disease's incubation offset — two days for `COVID`, one
        day for `INFLUENZA`, seven days for `PERTUSSIS`, one day for
        `NOROVIRUS`, and four days for `MEASLES`. The `monitoring_window_days`
        is the disease's monitoring span — fourteen days for `COVID`, seven for
        `INFLUENZA`, twenty-one for `PERTUSSIS`, three for `NOROVIRUS`, and
        twenty-one for `MEASLES`." and "Enrollment computes `monitoring_start`
        equal to the `contact_date` and `monitoring_end` equal to the
        `contact_date` plus the event's `monitoring_window_days`."

        Design: Corner/calculations/event_window_constants_applied
        """
        ix = register_employee("E-CL4X", full_name="Pert Idx", department="PED")
        ec = register_employee("E-CL4C", full_name="Pert Ctc", job_category="TECH",
                               department="PED")

        event = create_event(ix["id"], disease="PERTUSSIS",
                             onset_date="2026-08-10T00:00:00Z")
        assert_instant(event["infectious_start"], "2026-08-03T00:00:00")
        assert event["monitoring_window_days"] == 21

        advance_event(event["id"], "TRACING")
        set_clock("2026-08-10T00:00:00Z")
        contact = enroll_contact(event["id"], ec["id"],
                                 contact_date="2026-08-06T00:00:00Z")
        assert_exposure_contact(contact)
        assert_instant(contact["monitoring_start"], "2026-08-06T00:00:00")
        assert_instant(contact["monitoring_end"], "2026-08-27T00:00:00")


class TestContactMonitoringBoundary:
    def test_contact_stays_monitoring_at_exact_end(self, api, safety_headers):
        """PRD §3.7: "A contact clears only passively and strictly: when the
        clock is strictly later than `monitoring_end` and
        `symptom_onset_reported` remains false, the contact automatically
        becomes `CLEARED`; at the exact instant of `monitoring_end` the contact
        remains `MONITORING`."

        Design: Difficulty/boundary_precision_check/contact_monitoring_strict_end_boundary
        """
        _ix, _ec, _event, contact = setup_tracing_event_with_contact(
            "E-BP2X", "E-BP2C", disease="COVID",
            onset_date="2026-08-01T00:00:00Z", contact_date="2026-08-02T00:00:00Z",
        )
        # COVID monitoring span is 14 days: end == contact_date + 14 days.
        assert_instant(contact["monitoring_end"], "2026-08-16T00:00:00")

        set_clock("2026-08-16T00:00:00Z")
        at_end = get_contact(contact["id"])
        assert at_end["status"] == "MONITORING", (
            "strict > not yet met at now == monitoring_end"
        )

    def test_contact_clears_after_monitoring_end(self, api, safety_headers):
        """PRD §3.7: "when the clock is strictly later than `monitoring_end`
        and `symptom_onset_reported` remains false, the contact automatically
        becomes `CLEARED`"

        Design: Difficulty/boundary_precision_check/contact_monitoring_strict_end_boundary
        """
        _ix, _ec, _event, contact = setup_tracing_event_with_contact(
            "E-BP2D", "E-BP2E", disease="COVID",
            onset_date="2026-08-01T00:00:00Z", contact_date="2026-08-02T00:00:00Z",
        )
        set_clock("2026-08-17T00:00:00Z")  # monitoring_end + 1 day
        after = get_contact(contact["id"])
        assert after["status"] == "CLEARED"
        assert after["symptom_onset_reported"] is False


class TestContactConversion:
    def test_convert_without_symptoms_rejected(self, api, nurse_headers):
        """PRD §3.7: "A nurse may then convert a `MONITORING` contact to
        `CONVERTED_TO_CASE`, but only when symptoms have been reported
        (`ERR_NO_SYMPTOMS_REPORTED`)."

        Design: Corner/state_machines/contact_convert_without_symptoms_rejected
        """
        _ix, _ec, event, contact = setup_tracing_event_with_contact(
            "E-SM13X", "E-SM13C",
        )
        resp = api.transition_exposure_contact(
            contact["id"], {"to_state": "CONVERTED_TO_CASE"}, nurse_headers
        )
        validate_error(resp, ApiErrorId.ERR_NO_SYMPTOMS_REPORTED)

        assert get_contact(contact["id"])["status"] == "MONITORING"
        assert get_event(event["id"])["status"] == "TRACING"

    def test_symptom_then_convert_escalates_event(self, api, nurse_headers,
                                                  physician_headers):
        """PRD §3.7: "Conversion escalates the parent event from `MONITORING`
        to `ESCALATED` automatically, and auto-creates a `FULL_EXCLUSION` work
        restriction for the contact employee starting at the current logical
        time, open-ended, with `origin` `CONTACT_CONVERSION` — incrementing
        that employee's `open_restriction_count` and recomputing posture."

        Design: Corner/state_machines/contact_symptom_then_convert_escalates_event
        """
        _ix, ec, event, contact = setup_tracing_event_with_contact(
            "E-SM17X", "E-SM17C", advance_to_monitoring=True,
        )

        # The exposed employee reports their own symptoms (self-scope).
        reported = validate_success(api.report_symptom(
            contact["id"], {"symptom_onset_date": "2026-08-04T00:00:00Z"},
            make_staff_employee_headers(ec["id"]),
        ))
        assert reported["symptom_onset_reported"] is True

        converted = validate_success(api.transition_exposure_contact(
            contact["id"], {"to_state": "CONVERTED_TO_CASE"}, nurse_headers
        ))
        assert converted["status"] == "CONVERTED_TO_CASE"

        assert get_event(event["id"])["status"] == "ESCALATED"

        restrictions = list_restrictions(ec["id"], status="ACTIVE")
        assert len(restrictions) == 1
        wr = restrictions[0]
        assert wr["restriction_type"] == "FULL_EXCLUSION"
        assert wr["origin"] == "CONTACT_CONVERSION"
        assert wr["end_date"] is None
        assert_instant(wr["start_date"], "2026-08-05T00:00:00")

        emp_after = get_employee(ec["id"])
        assert emp_after["open_restriction_count"] == 1
        assert emp_after["compliance_posture"] == "WORK_EXCLUDED"


class TestEventCloseGate:
    def test_close_blocked_while_contact_monitoring(self, api, safety_headers):
        """PRD §3.7: "The event closes only from `MONITORING`, and only when
        every enrolled contact has reached `CLEARED`, `CONVERTED_TO_CASE`, or
        `LOST_TO_FOLLOWUP`; closing with any contact still `MONITORING` is
        rejected with `ERR_EVENT_CLOSE_BLOCKED`."

        Design: Corner/state_machines/event_close_blocked_while_contacts_monitoring
        """
        _ix, _ec, event, contact = setup_tracing_event_with_contact(
            "E-SM12X", "E-SM12C", advance_to_monitoring=True,
        )
        assert get_contact(contact["id"])["status"] == "MONITORING"

        resp = api.advance_communicable_event(
            event["id"], {"to_state": "CLOSED"}, safety_headers
        )
        validate_error(resp, ApiErrorId.ERR_EVENT_CLOSE_BLOCKED)
        assert get_event(event["id"])["status"] == "MONITORING"


class TestContactDateRange:
    def test_contact_date_before_infectious_start_rejected(self, api,
                                                           safety_headers):
        """PRD §3.7: "the `contact_date` must fall between the event's
        `infectious_start` and the current logical time, inclusive of both
        (`ERR_CONTACT_DATE_OUT_OF_RANGE`)."

        Design: Corner/validations/contact_date_before_infectious_window_rejected
        """
        ix = register_employee("E-V9X", full_name="Evt Idx")
        ec = register_employee("E-V9C", full_name="Early Contact",
                               job_category="TECH")
        # COVID onset 2026-08-01 -> infectious_start 2026-07-30.
        event = create_event(ix["id"], disease="COVID",
                             onset_date="2026-08-01T00:00:00Z")
        advance_event(event["id"], "TRACING")
        set_clock("2026-08-05T00:00:00Z")

        resp = api.enroll_contact(
            event["id"],
            enroll_contact_payload(contact_employee_id=ec["id"],
                                   contact_date="2026-07-01T00:00:00Z"),
            safety_headers,
        )
        validate_error(resp, ApiErrorId.ERR_CONTACT_DATE_OUT_OF_RANGE)

        data, meta = validate_paginated(
            api.list_exposure_contacts(safety_headers,
                                       params={"event_id": event["id"]})
        )
        assert meta["total_count"] == 0 and data == []
