"""Adverse-event reporting window and acknowledgement lifecycle, the
startup-default logical clock, authentication/role checks, and per-resource
404 existence semantics."""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_adverse_event,
    create_adverse_event_payload,
    create_enrollment,
    create_enrollment_payload,
    create_program,
    make_case_manager_headers,
    make_nurse_educator_headers,
    report_adverse_event,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

CM = TEST_USERS["case_manager_headers"]
PR = TEST_USERS["payer_reviewer_headers"]
MM = TEST_USERS["manufacturer_monitor_headers"]
FC = TEST_USERS["financial_counselor_headers"]
RX = TEST_USERS["pharmacy_partner_headers"]

MISSING = "11111111-1111-1111-1111-111111111111"


class TestAdverseEventLifecycle:

    def test_manufacturer_monitor_acknowledges_adverse_event(self):
        """PRD section 3.8: "The reporter's identity lands in
        `reported_by_user_id`, and the event opens in `REPORTED`. A
        `ManufacturerMonitor` acknowledges receipt, moving a `REPORTED`
        event to the terminal `ACKNOWLEDGED`; an event in any other state
        cannot be acknowledged again, and transitions on the terminal event
        are rejected with `ERR_ALREADY_TERMINAL`."

        Design: Corner/rbac/manufacturer_monitor_acknowledges_adverse_event
        """
        prog = create_program(name="ProgR5")
        enr = create_enrollment(prog["id"], patient_ref="PAT-R5")
        ae = report_adverse_event(
            enr["id"], as_headers=make_case_manager_headers("cm-1"),
            seriousness="SERIOUS", description="hospitalization")
        assert_adverse_event(ae)
        assert ae["reported_by_user_id"] == "cm-1", \
            "reporter stamped from X-User-ID at creation"
        assert ae["status"] == "REPORTED"

        resp = api_client.acknowledge_adverse_event(ae["id"], MM)
        acked = validate_success(resp, expected_status=200)
        assert acked["status"] == "ACKNOWLEDGED"

    def test_adverse_event_acknowledge_twice_returns_already_terminal(self):
        """PRD section 3.8: "A `ManufacturerMonitor` acknowledges receipt,
        moving a `REPORTED` event to the terminal `ACKNOWLEDGED`; an event
        in any other state cannot be acknowledged again, and transitions on
        the terminal event are rejected with `ERR_ALREADY_TERMINAL`."

        Design: Corner/state_machines/adverse_event_acknowledge_twice_returns_already_terminal
        """
        prog = create_program(name="ProgS4")
        enr = create_enrollment(prog["id"], patient_ref="PAT-S4")
        ae = report_adverse_event(
            enr["id"], as_headers=make_nurse_educator_headers("nurse-9"),
            seriousness="NON_SERIOUS", description="mild rash")

        first = validate_success(
            api_client.acknowledge_adverse_event(ae["id"], MM), 200)
        assert first["status"] == "ACKNOWLEDGED"

        resp = api_client.acknowledge_adverse_event(ae["id"], MM)
        validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL)


class TestReportingWindowAndClock:

    def test_adverse_event_awareness_in_future_returns_validation(self):
        """PRD section 3.8: "The awareness instant may not lie in the future
        relative to the logical clock, on penalty of `ERR_VALIDATION`, and
        the report must be filed within 24 hours of awareness
        (`AE_REPORT_WINDOW_HOURS`); a filing that arrives later is rejected
        with `ERR_AE_REPORT_WINDOW_MISSED`."
        PRD section 2.5: "At startup, before any clock operation is
        received, the logical clock reads exactly 2026-08-01T00:00:00Z, and
        it never falls back to wall-clock time."

        Design: Corner/validations/adverse_event_awareness_in_future_returns_validation
        """
        prog = create_program(name="ProgV4")
        enr = create_enrollment(prog["id"], patient_ref="PAT-V4")
        # Default clock is 2026-08-01T00:00:00Z; 2026-08-02 lies ahead of it.
        resp = api_client.create_adverse_event(
            enr["id"],
            create_adverse_event_payload(
                awareness_at="2026-08-02T00:00:00Z",
                seriousness="SERIOUS",
                description="future-dated awareness"),
            CM)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_clock_default_window_boundary_checks(self):
        """PRD section 2.5: "At startup, before any clock operation is
        received, the logical clock reads exactly 2026-08-01T00:00:00Z, and
        it never falls back to wall-clock time."
        PRD section 3.8: "The awareness instant may not lie in the future
        relative to the logical clock, on penalty of `ERR_VALIDATION`, and
        the report must be filed within 24 hours of awareness
        (`AE_REPORT_WINDOW_HOURS`); a filing that arrives later is rejected
        with `ERR_AE_REPORT_WINDOW_MISSED`."

        Design: Corner/cross_cutting_layers/clock_default_window_boundary_checks
        """
        prog = create_program(name="ProgCk")
        enr = create_enrollment(prog["id"], patient_ref="PAT-CK")

        # 2026-07-31T00:30:00Z is 23.5 hours before the default clock.
        within = api_client.create_adverse_event(
            enr["id"],
            create_adverse_event_payload(
                awareness_at="2026-07-31T00:30:00Z", description="within 24h"),
            CM)
        ae = validate_success(within, expected_status=201)
        assert_adverse_event(ae)

        # 2026-07-30T23:00:00Z is 25 hours before the default clock.
        late = api_client.create_adverse_event(
            enr["id"],
            create_adverse_event_payload(
                awareness_at="2026-07-30T23:00:00Z", description="25h late"),
            CM)
        validate_error(late, ApiErrorId.ERR_AE_REPORT_WINDOW_MISSED)


class TestAccessControl:

    def test_request_missing_auth_headers_returns_unauthenticated(self):
        """PRD section 2.1: "Every request must carry two HTTP headers:
        `X-User-ID`, identifying the acting user, and `X-User-Role`,
        declaring the user's operational capacity."
        PRD section 2.1: "A request missing either header, carrying a blank
        header value, or naming a role outside these seven is rejected with
        `ERR_UNAUTHENTICATED`."
        PRD section 2.6: "Authentication. Presence and validity of
        `X-User-ID` and `X-User-Role`; failures yield `ERR_UNAUTHENTICATED`
        (HTTP 401)."

        Design: Corner/validations/request_missing_auth_headers_returns_unauthenticated
        """
        # No X-User-Role / X-User-ID headers at all; the nonexistent
        # program id must not matter — authentication runs first.
        resp = api_client.create_enrollment(
            {"program_id": "00000000-0000-0000-0000-000000000000",
             "patient_ref": "PAT-V1", "diagnosis_code": "C50"},
            headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_payer_reviewer_cannot_create_enrollment(self):
        """PRD section 2.1: "A request whose role is not listed among the
        roles authorized for the target endpoint is rejected with
        `ERR_FORBIDDEN`; the same code applies when a `NurseEducator`
        attempts to resolve a nurse visit assigned to a different nurse."
        PRD section 4: "Enroll a patient into a drug program | CaseManager".

        Design: Corner/rbac/payer_reviewer_cannot_create_enrollment
        """
        prog = create_program(name="ProgR2")
        resp = api_client.create_enrollment(
            create_enrollment_payload(
                prog["id"], patient_ref="PAT-R2", diagnosis_code="C50"),
            PR)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        _, meta = validate_paginated(api_client.list_enrollments(CM))
        assert meta["total_count"] == 0, "a forbidden create persists nothing"


class TestExistenceSweep:

    def test_existence_404_precedes_business_checks(self):
        """PRD section 2.6: "The ordering is observable. A shipment request
        naming a missing enrollment surfaces the 404 before its body is even
        inspected; a stale-version outcome report create surfaces
        `ERR_STALE_VERSION` before its period-overlap check runs; and on
        shipment creation a cold-chain violation surfaces before the
        training or adherence gates, which in turn surface before refill
        spacing is examined."
        PRD section 2.7: "Every endpoint path that names one or more
        resource identifiers validates those identifiers in strict
        left-to-right order, and the request is rejected immediately with
        the 404 that corresponds to the first identifier that does not
        resolve."

        Design: Corner/validations/existence_404_precedes_business_checks
        """
        resp = api_client.create_shipment(
            MISSING,
            {"requested_delivery_date": "2026-08-03",
             "transit_hours": 24, "days_supply": 30},
            CM)
        validate_error(resp, ApiErrorId.ERR_ENROLLMENT_NOT_FOUND)

    def test_per_resource_not_found_sweep_returns_404s(self):
        """PRD section 2.7: "Each resource type carries its own not-found
        code: `ERR_DRUG_PROGRAM_NOT_FOUND` (including enrollment creation
        that names an unknown program), `ERR_FOUNDATION_POOL_NOT_FOUND`,
        `ERR_ENROLLMENT_NOT_FOUND`, `ERR_PRIOR_AUTHORIZATION_NOT_FOUND`,
        `ERR_COPAY_ASSISTANCE_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`,
        `ERR_NURSE_VISIT_NOT_FOUND`, `ERR_ADVERSE_EVENT_NOT_FOUND`, and
        `ERR_OUTCOME_REPORT_NOT_FOUND`."

        Design: Corner/errors/per_resource_not_found_sweep_returns_404s
        """
        resp = api_client.ship_shipment(MISSING, RX)
        validate_error(resp, ApiErrorId.ERR_SHIPMENT_NOT_FOUND)

        resp = api_client.resolve_nurse_visit(
            MISSING, {"outcome": "COMPLETED"},
            make_nurse_educator_headers("nurse-1"))
        validate_error(resp, ApiErrorId.ERR_NURSE_VISIT_NOT_FOUND)

        resp = api_client.submit_outcome_report(MISSING, CM)
        validate_error(resp, ApiErrorId.ERR_OUTCOME_REPORT_NOT_FOUND)

        resp = api_client.acknowledge_adverse_event(MISSING, MM)
        validate_error(resp, ApiErrorId.ERR_ADVERSE_EVENT_NOT_FOUND)

        resp = api_client.record_pa_decision(
            MISSING, {"outcome": "APPROVED", "rationale": "x"}, PR)
        validate_error(resp, ApiErrorId.ERR_PRIOR_AUTHORIZATION_NOT_FOUND)

        resp = api_client.release_copay_assistance(
            MISSING, TEST_USERS["financial_counselor_headers"])
        validate_error(resp, ApiErrorId.ERR_COPAY_ASSISTANCE_NOT_FOUND)

        resp = api_client.get_foundation_pool(
            MISSING, TEST_USERS["hub_admin_headers"])
        validate_error(resp, ApiErrorId.ERR_FOUNDATION_POOL_NOT_FOUND)

        resp = api_client.create_enrollment(
            create_enrollment_payload(MISSING, patient_ref="PAT-NF"), CM)
        validate_error(resp, ApiErrorId.ERR_DRUG_PROGRAM_NOT_FOUND)
