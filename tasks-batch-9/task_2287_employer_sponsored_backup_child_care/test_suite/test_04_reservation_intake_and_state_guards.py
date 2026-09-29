"""Derived intake fields, initial states, invalid transitions and the auth bands."""

import pytest
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    assert_reservation,
    benefit_plan_payload,
    cancel,
    create_dependent,
    create_employer,
    create_invoice,
    create_provider,
    create_reservation,
    employer_payload,
    file_incident,
    make_provider_manager_headers,
    read_reservation,
    reservation_payload,
    setup_enrolled_employee,
    unauthenticated_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

NETWORK_ADMIN = TEST_USERS["network_admin"]
BENEFITS_ADMIN = TEST_USERS["benefits_admin"]
CARE_COORDINATOR = TEST_USERS["care_coordinator"]


class TestDerivedIntakeFields:
    def test_intake_derives_date_seats_and_deadline_from_the_window(self, api):
        """None of care_date, dependent_count, required_seats or the deadline are supplied.

        PRD 3.4: "From the window and the dependent list, intake derives `care_date`
        (the UTC calendar date of `care_start_utc`), `dependent_count` (the length
        of `dependent_ids`, frozen from this point on)".

        Design: Corner/entities/corner_reservation_computed_fields_derive_from_inputs
        """
        world = setup_enrolled_employee(
            api,
            dependent_count=2,
            plan_overrides={
                "cancellation_window_hours": 24,
                "eligible_dependent_types": ["CHILD"],
                "max_dependents_per_reservation": 3,
            },
        )
        payload = reservation_payload(
            world["employee"]["id"],
            world["dependent_ids"],
            "2026-08-14T09:00:00Z",
            "2026-08-14T15:00:00Z",
            requested_care_mode="CENTER_BASED",
        )
        assert "care_date" not in payload
        assert "required_seats" not in payload

        reservation = validate_success(
            api.create_reservation(payload, CARE_COORDINATOR), expected_status=201
        )
        assert_reservation(reservation)

        assert reservation["care_date"] == "2026-08-14"
        assert reservation["dependent_count"] == 2
        assert reservation["required_seats"] == 2
        assert reservation["dependent_type_mix"] == "CHILD_ONLY"
        assert reservation["cancellation_deadline_utc"].startswith("2026-08-13T09:00:00")
        assert reservation["plan_version_pinned"] == world["plan"]["version"]
        assert reservation["matched_provider_id"] is None
        assert reservation["matched_capacity_block_id"] is None
        assert reservation["confirmation_code"] is None
        assert reservation["excluded_provider_ids"] == []
        assert reservation["overage_tier_multiplier"] == pytest.approx(1, abs=0.01)

    def test_in_home_request_takes_one_seat_regardless_of_dependent_count(self, api):
        """The requested mode alone decides required_seats before any match.

        PRD 3.4: "`required_seats` (the dependent count when the care will be
        delivered centre-based, and 1 when it will be delivered in-home; before a
        provider has been matched the requested mode decides".

        Design: Corner/entities/corner_reservation_computed_fields_derive_from_inputs
        """
        world = setup_enrolled_employee(api, dependent_count=3)

        in_home = create_reservation(
            api,
            world["employee"]["id"],
            world["dependent_ids"],
            "2026-08-14T09:00:00Z",
            "2026-08-14T15:00:00Z",
            requested_care_mode="IN_HOME",
        )
        either = create_reservation(
            api,
            world["employee"]["id"],
            world["dependent_ids"],
            "2026-08-15T09:00:00Z",
            "2026-08-15T15:00:00Z",
            requested_care_mode="EITHER",
        )
        center = create_reservation(
            api,
            world["employee"]["id"],
            world["dependent_ids"],
            "2026-08-16T09:00:00Z",
            "2026-08-16T15:00:00Z",
            requested_care_mode="CENTER_BASED",
        )

        assert in_home["dependent_count"] == 3
        assert in_home["required_seats"] == 1
        assert either["required_seats"] == 1
        assert center["required_seats"] == 3

    def test_unknown_reservation_id_is_a_404_not_an_empty_success(self, api):
        """A well-formed but unknown identifier names the reservation entity.

        PRD 2.8 band 3: "Each failure returns the not-found code of the entity that
        failed to resolve."

        Design: Corner/entities/corner_reservation_not_found_returns_404
        """
        response = api.get_reservation(NON_EXISTENT_UUID, CARE_COORDINATOR)
        body = validate_error(response, ApiErrorId.ERR_RESERVATION_NOT_FOUND.value)

        assert response.status_code == 404
        assert response.json()["response_type"] == "error"
        assert isinstance(body["message"], str) and body["message"]


class TestDeclaredInitialStates:
    def test_every_freshly_created_row_lands_on_its_declared_initial_state(self, api):
        """Plan DRAFT, provider PENDING, credential VALID, invoice DRAFT, incident OPEN.

        PRD 2.9: "`billing_status` tracks money movement and takes one of
        `NOT_BILLABLE`, `ACCRUED`, `INVOICED`, or `PAID`, starting at
        `NOT_BILLABLE`, with `PAID` as its only terminal state."

        Design: Corner/state_machines/corner_every_entity_starts_in_its_declared_initial_state
        """
        employer = create_employer(api)

        plan = validate_success(
            api.create_benefit_plan(
                benefit_plan_payload(employer["id"], employer["version"]), BENEFITS_ADMIN
            ),
            expected_status=201,
        )
        assert plan["status"] == "DRAFT"

        provider = create_provider(api)
        assert provider["network_status"] == "PENDING"

        credential = validate_success(
            api.create_credential(
                provider["id"],
                {
                    "credential_type": "LICENSE",
                    "issued_on": "2026-01-02",
                    "expires_on": "2027-06-30",
                    "verified_by": "u_na_1",
                },
                NETWORK_ADMIN,
            ),
            expected_status=201,
        )
        assert credential["status"] == "VALID"
        assert credential["revoked_reason_code"] is None

        invoice = create_invoice(api, employer["id"], "2026-07-01", "2026-07-31")
        assert invoice["invoice_status"] == "DRAFT"

        incident = file_incident(api, provider["id"], "MINOR")
        assert incident["incident_status"] == "OPEN"
        assert incident["qa_action"] is None or incident["qa_action"] == "NONE"

        world = setup_enrolled_employee(api)
        reservation = create_reservation(
            api,
            world["employee"]["id"],
            world["dependent_ids"],
            "2026-08-20T09:00:00Z",
            "2026-08-20T15:00:00Z",
        )
        assert reservation["fulfillment_status"] == "INTAKE"
        assert reservation["billing_status"] == "NOT_BILLABLE"

    def test_service_transitions_are_refused_while_the_reservation_sits_in_intake(self, api):
        """check-in, complete and no-show all belong to later edges.

        PRD 2.9: "Attempting a transition the current `fulfillment_status` does not
        permit — confirming from `INTAKE`, checking in from `OFFERED`, completing
        from `CONFIRMED`, rejecting an offer from `MATCHING` — yields
        `ERR_RESERVATION_STATE_INVALID`".

        Design: Corner/state_machines/corner_check_in_from_intake_returns_state_invalid
        """
        world = setup_enrolled_employee(api)
        reservation = create_reservation(
            api,
            world["employee"]["id"],
            world["dependent_ids"],
            "2026-08-20T09:00:00Z",
            "2026-08-20T15:00:00Z",
        )
        reservation_id = reservation["id"]

        validate_error(
            api.check_in_reservation(reservation_id, CARE_COORDINATOR),
            ApiErrorId.ERR_RESERVATION_STATE_INVALID.value,
        )
        validate_error(
            api.complete_reservation(
                reservation_id,
                {
                    "actual_start_utc": "2026-08-20T09:00:00Z",
                    "actual_end_utc": "2026-08-20T15:00:00Z",
                },
                CARE_COORDINATOR,
            ),
            ApiErrorId.ERR_RESERVATION_STATE_INVALID.value,
        )
        validate_error(
            api.no_show_reservation(reservation_id, {}, CARE_COORDINATOR),
            ApiErrorId.ERR_RESERVATION_STATE_INVALID.value,
        )

        after = read_reservation(api, reservation_id)
        assert after["fulfillment_status"] == "INTAKE"
        assert after["billing_status"] == "NOT_BILLABLE"
        assert after["version"] == reservation["version"]
        assert after["actual_start_utc"] is None
        assert after["penalty_cents"] == 0

    def test_cancelling_twice_reports_terminal_and_preserves_the_first_cancel(self, api):
        """The second cancel is refused, not absorbed.

        PRD 2.9: "while any transition attempt on a reservation already in
        `COMPLETED`, `CANCELLED` or `NO_SHOW` yields `ERR_RESERVATION_TERMINAL`."

        Design: Corner/state_machines/corner_second_cancel_on_cancelled_reservation_returns_terminal
        """
        world = setup_enrolled_employee(api)
        reservation = create_reservation(
            api,
            world["employee"]["id"],
            world["dependent_ids"],
            "2026-08-22T09:00:00Z",
            "2026-08-22T15:00:00Z",
        )

        cancelled = cancel(api, reservation["id"], cancel_reason_code="SCHOOL_REOPENED")
        assert cancelled["fulfillment_status"] == "CANCELLED"
        assert cancelled["cancel_reason_code"] == "SCHOOL_REOPENED"
        assert cancelled["penalty_cents"] == 0
        assert cancelled["billing_status"] == "NOT_BILLABLE"

        validate_error(
            api.cancel_reservation(
                reservation["id"], {"cancel_reason_code": "CHANGED_MIND"}, CARE_COORDINATOR
            ),
            ApiErrorId.ERR_RESERVATION_TERMINAL.value,
        )

        after = read_reservation(api, reservation["id"])
        assert after["cancel_reason_code"] == "SCHOOL_REOPENED"
        assert after["version"] == cancelled["version"]


class TestWindowShapeAndTemporalBands:
    def test_three_bad_windows_separate_by_band_order(self, api):
        """Zero-length pre-empts both temporal rules; the temporal pair then splits.

        PRD 3.4: "The window must be well-formed (end strictly after start), must
        fall entirely on one UTC calendar date (otherwise
        `ERR_CARE_WINDOW_SPANS_DAYS`, which also covers a window longer than 14
        hours), and must begin strictly after the logical clock (otherwise
        `ERR_CARE_WINDOW_IN_PAST`)."

        Design: Corner/validations/corner_care_window_in_past_or_spanning_midnight_rejected
        """
        world = setup_enrolled_employee(api)
        employee_id = world["employee"]["id"]
        dependent_ids = world["dependent_ids"]

        # care_end equal to care_start is band 1 and pre-empts both temporal checks.
        validate_error(
            api.create_reservation(
                reservation_payload(
                    employee_id, dependent_ids, "2026-07-30T09:00:00Z", "2026-07-30T09:00:00Z"
                ),
                CARE_COORDINATOR,
            ),
            ApiErrorId.ERR_INVALID_WINDOW.value,
        )

        # care_start exactly at the clock is not strictly after it.
        validate_error(
            api.create_reservation(
                reservation_payload(
                    employee_id, dependent_ids, "2026-08-01T00:00:00Z", "2026-08-01T06:00:00Z"
                ),
                CARE_COORDINATOR,
            ),
            ApiErrorId.ERR_CARE_WINDOW_IN_PAST.value,
        )
        validate_error(
            api.create_reservation(
                reservation_payload(
                    employee_id, dependent_ids, "2026-07-25T09:00:00Z", "2026-07-25T15:00:00Z"
                ),
                CARE_COORDINATOR,
            ),
            ApiErrorId.ERR_CARE_WINDOW_IN_PAST.value,
        )

        # A future window straddling midnight is two calendar dates.
        validate_error(
            api.create_reservation(
                reservation_payload(
                    employee_id, dependent_ids, "2026-08-20T23:00:00Z", "2026-08-21T01:00:00Z"
                ),
                CARE_COORDINATOR,
            ),
            ApiErrorId.ERR_CARE_WINDOW_SPANS_DAYS.value,
        )

        accepted = validate_success(
            api.create_reservation(
                reservation_payload(
                    employee_id, dependent_ids, "2026-08-20T09:00:00Z", "2026-08-20T15:00:00Z"
                ),
                CARE_COORDINATOR,
            ),
            expected_status=201,
        )
        assert accepted["care_date"] == "2026-08-20"

        _, meta = validate_paginated(api.list_employee_reservations(employee_id, CARE_COORDINATOR))
        assert meta["total_count"] == 1


class TestAuthenticationAndAuthorisationBands:
    def test_a_request_with_no_user_id_header_never_leaks_a_later_band(self, api):
        """Band 2 runs ahead of existence, and never leaks a later band.

        PRD 2.8 band 2: "`X-User-ID` must be present and resolve to a known role
        identity (`ERR_UNAUTHENTICATED`); then the caller's role must be authorised
        for the endpoint (`ERR_UNAUTHORIZED`)".

        Design: Corner/rbac/corner_missing_x_user_id_returns_unauthenticated
        """
        anonymous = unauthenticated_headers()

        # Band 1 (request shape) precedes band 2, so the payload is deliberately
        # well-formed: the only thing wrong with this call is the missing header.
        validate_error(
            api.create_employer(employer_payload(industry_code="MIXED"), anonymous),
            ApiErrorId.ERR_UNAUTHENTICATED.value,
        )
        validate_error(
            api.get_employer(NON_EXISTENT_UUID, anonymous),
            ApiErrorId.ERR_UNAUTHENTICATED.value,
        )

        _, meta = validate_paginated(api.list_employers(NETWORK_ADMIN))
        assert meta["total_count"] == 0

    def test_no_role_dominates_another_so_each_peer_operation_is_refused(self, api):
        """Five roles, five exclusive operations, five ERR_UNAUTHORIZED refusals.

        PRD 2.1: "The system recognises exactly five roles, and none of them is a
        superset of another."

        Design: Corner/rbac/corner_peer_role_exclusive_operations_are_mutually_denied
        """
        world = setup_enrolled_employee(api, user_id="u_ee_pr1")
        employer_id = world["employer"]["id"]
        reservation = create_reservation(
            api,
            world["employee"]["id"],
            world["dependent_ids"],
            "2026-08-20T09:00:00Z",
            "2026-08-20T15:00:00Z",
            market_code="MKT-PDX",
        )
        invoice = create_invoice(api, employer_id, "2026-07-01", "2026-07-31")
        # same_day_available is declared with a false default (PRD 3.3), so it is
        # set explicitly here for the refused PATCH below to have something to undo.
        provider = create_provider(
            api,
            owner_user_id="u_pm_z",
            market_code="MKT-PDX",
            provider_name="Peer Role Center",
            same_day_available=True,
        )

        # Plan drafting is exclusive to benefits_admin.
        validate_error(
            api.create_benefit_plan(
                benefit_plan_payload(employer_id, world["employer"]["version"], plan_code="PRF-X"),
                NETWORK_ADMIN,
            ),
            ApiErrorId.ERR_UNAUTHORIZED.value,
        )
        # Matching is exclusive to care_coordinator.
        validate_error(
            api.match_reservation(reservation["id"], BENEFITS_ADMIN),
            ApiErrorId.ERR_UNAUTHORIZED.value,
        )
        # Issuing an invoice is exclusive to network_admin.
        validate_error(
            api.issue_invoice(invoice["id"], CARE_COORDINATOR),
            ApiErrorId.ERR_UNAUTHORIZED.value,
        )
        # The maintenance sweep is exclusive to network_admin.
        validate_error(
            api.run_daily_maintenance(world["employee_headers"]),
            ApiErrorId.ERR_UNAUTHORIZED.value,
        )
        # PATCH provider is not in provider_manager's role set at all, so the
        # role check fires ahead of the ownership scope check.
        validate_error(
            api.patch_provider(
                provider["id"], {"same_day_available": False}, make_provider_manager_headers("u_pm_z")
            ),
            ApiErrorId.ERR_UNAUTHORIZED.value,
        )

        unchanged = validate_success(api.get_provider(provider["id"], NETWORK_ADMIN))
        assert unchanged["same_day_available"] is True
        assert unchanged["version"] == 1

        # The denials above were authorisation failures, not silent no-ops.
        matched = validate_success(api.match_reservation(reservation["id"], CARE_COORDINATOR))
        assert matched["fulfillment_status"] == "UNFULFILLED"


class TestPathIdentifierNotFoundBattery:
    def test_seven_endpoints_return_seven_entity_specific_not_found_codes(self, api):
        """The path identifier resolves against the endpoint's own entity.

        PRD 2.8 band 3: "Path identifiers resolve first, strictly left to right, so
        the outermost identifier in a nested path is the one whose absence is
        reported".

        Design: Corner/errors/corner_path_id_battery_returns_entity_specific_not_found
        """
        cases = [
            (api.get_employer(NON_EXISTENT_UUID, BENEFITS_ADMIN), ApiErrorId.ERR_EMPLOYER_NOT_FOUND),
            (
                api.get_benefit_plan(NON_EXISTENT_UUID, BENEFITS_ADMIN),
                ApiErrorId.ERR_BENEFITPLAN_NOT_FOUND,
            ),
            (api.get_employee(NON_EXISTENT_UUID, BENEFITS_ADMIN), ApiErrorId.ERR_EMPLOYEE_NOT_FOUND),
            (api.get_provider(NON_EXISTENT_UUID, NETWORK_ADMIN), ApiErrorId.ERR_PROVIDER_NOT_FOUND),
            (
                api.get_credential(NON_EXISTENT_UUID, NETWORK_ADMIN),
                ApiErrorId.ERR_CREDENTIAL_NOT_FOUND,
            ),
            (
                api.get_match_offer(NON_EXISTENT_UUID, CARE_COORDINATOR),
                ApiErrorId.ERR_MATCHOFFER_NOT_FOUND,
            ),
            (
                api.get_invoice(NON_EXISTENT_UUID, NETWORK_ADMIN),
                ApiErrorId.ERR_EMPLOYERINVOICE_NOT_FOUND,
            ),
            (
                api.get_incident_report(NON_EXISTENT_UUID, NETWORK_ADMIN),
                ApiErrorId.ERR_INCIDENTREPORT_NOT_FOUND,
            ),
        ]
        observed = []
        for response, expected in cases:
            body = validate_error(response, expected.value)
            assert response.status_code == 404
            observed.append(body["error_id"])

        assert len(set(observed)) == len(observed)

        # Nested paths report the outermost identifier, not the leaf entity.
        validate_error(
            api.list_dependents(NON_EXISTENT_UUID, BENEFITS_ADMIN),
            ApiErrorId.ERR_EMPLOYEE_NOT_FOUND.value,
        )
        validate_error(
            api.list_credentials(NON_EXISTENT_UUID, NETWORK_ADMIN),
            ApiErrorId.ERR_PROVIDER_NOT_FOUND.value,
        )
        validate_error(
            api.list_employer_benefit_plans(NON_EXISTENT_UUID, BENEFITS_ADMIN),
            ApiErrorId.ERR_EMPLOYER_NOT_FOUND.value,
        )

        # A dependent under a resolvable employee still 404s on its own id.
        world = setup_enrolled_employee(api, dependent_count=1)
        create_dependent(api, world["employee"]["id"])
        validate_error(
            api.get_dependent(NON_EXISTENT_UUID, BENEFITS_ADMIN),
            ApiErrorId.ERR_DEPENDENT_NOT_FOUND.value,
        )
