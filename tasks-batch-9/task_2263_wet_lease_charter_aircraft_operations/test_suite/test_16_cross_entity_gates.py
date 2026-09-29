"""Gates that read a different aggregate's state than the one being transitioned.

Activation reads the authority docket, dispatch reads the airframe posture, and invoice
approval reads the lessee-reviewed reliability report.
"""

from datetime import datetime, timezone

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    close_month,
    dispatch_payload,
    file_reliability_report,
    fly_leg,
    get_success_data,
    issue_insurance_certificate,
    make_billing_admin_headers,
    prepare_invoice,
    qualify_crew_member,
    record_maintenance_event,
    review_report_payload,
    revoke_approval,
    schedule_leg,
    setup_active_lease,
    setup_approved_lease,
    setup_filed_lease,
    validate_error,
    validate_success,
)

OPS = TEST_USERS["lessor_ops_headers"]
AUTHORITY = TEST_USERS["regulatory_authority_headers"]
TECH = TEST_USERS["maintenance_controller_headers"]
BILLING = TEST_USERS["billing_admin_headers"]

PREPARER = make_billing_admin_headers("billing-clerk-01")
APPROVER = make_billing_admin_headers("billing-supervisor-02")


def _instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant so two spellings of one instant compare equal."""
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _prepared_invoice_over_rejected_report(api):
    """Closed 2026-09 month whose only reliability report was rejected by the lessee."""
    scenario = setup_active_lease(api)
    fly_leg(api, scenario, "2026-09-10T06:00:00Z", "2026-09-10T07:40:00Z")
    period = close_month(api, scenario["period"]["id"])
    rejected = file_reliability_report(
        api,
        scenario,
        period_month="2026-09",
        decision="REJECT",
        review_note="Delay coding disputed.",
    )
    period = get_success_data(api.get_utilization_period(period["id"], BILLING))
    invoice = prepare_invoice(
        api, period, due_on="2026-10-15", variant="FINAL", headers=PREPARER
    )
    return scenario, rejected, invoice


class TestActivationReadsTheDocket:
    def test_activation_admitted_on_a_conditional_determination_with_open_conditions(
        self, api
    ):
        """PRD §3.5: The lease must own a `RegulatoryApproval` whose `determination` is `APPROVED` or `CONDITIONAL` and whose `expires_on` is either null or not earlier than the current logical date; otherwise `ERR_REGULATORY_APPROVAL_MISSING` (HTTP 409).
        PRD §3.2: A `CONDITIONAL` ruling requires a non-empty `conditions` array and copies it into `open_condition_codes`.
        PRD §3.2: Both `APPROVED` and `CONDITIONAL` advance the lease from `PENDING_REGULATORY_APPROVAL` to `APPROVED` — the same lease outcome, the difference being that a conditional lease carries open conditions to clear before its term ends.
        PRD §3.5: It sets the primary airframe from `AVAILABLE` to `ASSIGNED` and writes `assigned_lease_id` to the lease.

        Design: Difficulty/cross_entity_state_dependency/activation_requires_live_regulatory_determination_on_the_docket
        """
        scenario = setup_filed_lease(
            api,
            determination="CONDITIONAL",
            determination_overrides={"conditions": ["OPS_MANUAL_AMENDMENT"]},
        )
        lease_id = scenario["lease"]["id"]
        issue_insurance_certificate(api, lease_id)
        qualify_crew_member(api, scenario["captain"]["id"], lease_id)

        activated = validate_success(api.activate_lease(lease_id, OPS))
        assert activated["status"] == "ACTIVE", (
            "a lease whose docket is CONDITIONAL must still activate, expected ACTIVE, "
            f"got {activated['status']}"
        )

        docket = get_success_data(
            api.get_regulatory_approval(scenario["approval"]["id"], AUTHORITY)
        )
        assert docket["determination"] == "CONDITIONAL", (
            "activation must not alter the docket, expected determination CONDITIONAL, "
            f"got {docket['determination']}"
        )
        assert docket["open_condition_codes"] == ["OPS_MANUAL_AMENDMENT"], (
            "the conditional ruling's condition codes must remain open, expected "
            f"['OPS_MANUAL_AMENDMENT'], got {docket['open_condition_codes']}"
        )

        aircraft = get_success_data(api.get_aircraft(scenario["aircraft"]["id"], TECH))
        assert aircraft["status"] == "ASSIGNED", (
            f"activation must assign the airframe, got status {aircraft['status']}"
        )
        assert aircraft["assigned_lease_id"] == lease_id, (
            "activation must write assigned_lease_id to the activating lease, got "
            f"{aircraft['assigned_lease_id']}"
        )

    def test_activation_refused_when_the_docket_was_revoked_after_approval(self, api):
        """PRD §3.5: The lease must own a `RegulatoryApproval` whose `determination` is `APPROVED` or `CONDITIONAL` and whose `expires_on` is either null or not earlier than the current logical date; otherwise `ERR_REGULATORY_APPROVAL_MISSING` (HTTP 409).
        PRD §3.2: The authority revokes from `APPROVED` or from `CONDITIONAL` by supplying a `revocation_reason`; the docket moves to the terminal `REVOKED`, `decided_at` is set, the lease moves from `ACTIVE` to `SUSPENDED` with `suspension_reason` `REGULATORY_APPROVAL_REVOKED`, every leg on that lease still `SCHEDULED` or `DISPATCHED` is cancelled into `CANCELLED_LESSOR` with `cancel_reason` `REGULATORY`, and each such cancellation recomputes the affected crew members' rolling exposure and the covering open month's charge.
        PRD §3.5: A first activation moves the lease from `APPROVED` to `ACTIVE` and does three things besides.

        Design: Difficulty/cross_entity_state_dependency/activation_requires_live_regulatory_determination_on_the_docket
        """
        scenario = setup_approved_lease(api)
        lease_id = scenario["lease"]["id"]
        qualify_crew_member(api, scenario["captain"]["id"], lease_id)
        revoke_approval(
            api, scenario["approval"]["id"], "OPERATIONAL_CONTROL_FINDING"
        )

        response = api.activate_lease(lease_id, OPS)
        validate_error(response, ApiErrorId.ERR_REGULATORY_APPROVAL_MISSING)

        lease = get_success_data(api.get_lease(lease_id, OPS))
        assert lease["status"] == "APPROVED", (
            "a refused activation must leave the lease where it was, expected APPROVED, "
            f"got {lease['status']}"
        )

        docket = get_success_data(
            api.get_regulatory_approval(scenario["approval"]["id"], AUTHORITY)
        )
        assert docket["determination"] == "REVOKED", (
            f"the revoked docket must stay REVOKED, got {docket['determination']}"
        )

        aircraft = get_success_data(api.get_aircraft(scenario["aircraft"]["id"], TECH))
        assert aircraft["status"] == "AVAILABLE", (
            "the airframe must not be assigned by a refused activation, expected "
            f"AVAILABLE, got {aircraft['status']}"
        )
        assert aircraft["assigned_lease_id"] is None, (
            "a refused activation must leave assigned_lease_id null, got "
            f"{aircraft['assigned_lease_id']}"
        )


class TestDispatchReadsTheAirframePosture:
    def test_dispatch_refused_while_the_airframe_sits_in_scheduled_maintenance(self, api):
        """PRD §3.1: A `GROUND_SCHEDULED` event is accepted from `AVAILABLE` or `ASSIGNED` and sets `status` to `IN_MAINTENANCE`; it cancels nothing, so scheduled legs survive but dispatch off that airframe is subsequently refused with `ERR_AIRCRAFT_UNAVAILABLE`.
        PRD §3.6: It re-runs the gates at the dispatch instant rather than trusting the ones passed at scheduling: the lease must be `ACTIVE`; the airframe named by the leg must be `ASSIGNED`, else `ERR_AIRCRAFT_UNAVAILABLE`; a certificate on the lease must be `ACTIVE` with `additional_insured_lessee` true and a closed coverage interval containing `actual_out`, else `ERR_INSURANCE_COVERAGE_MISSING`; both pilots' qualifications for the lease must be `QUALIFIED`; both must hold the airframe's `type_designator`; and both projected exposures must remain within limits.

        Design: Difficulty/cross_entity_state_dependency/dispatch_requires_airframe_returned_to_service
        """
        scenario = setup_active_lease(api)
        leg = schedule_leg(
            api, scenario, "2026-09-18T06:00:00Z", "2026-09-18T09:00:00Z"
        )
        grounded = record_maintenance_event(
            api, scenario["aircraft"]["id"], "GROUND_SCHEDULED", note="C-check slot"
        )
        assert grounded["status"] == "IN_MAINTENANCE", (
            "GROUND_SCHEDULED must move the airframe to IN_MAINTENANCE, got "
            f"{grounded['status']}"
        )

        before = get_success_data(api.get_flight_leg(leg["id"], OPS))
        assert before["status"] == "SCHEDULED", (
            "GROUND_SCHEDULED cancels nothing, so the leg must remain SCHEDULED, got "
            f"{before['status']}"
        )

        response = api.dispatch_flight_leg(
            leg["id"], dispatch_payload("2026-09-18T06:00:00Z"), OPS
        )
        validate_error(response, ApiErrorId.ERR_AIRCRAFT_UNAVAILABLE)

        after = get_success_data(api.get_flight_leg(leg["id"], OPS))
        assert after["status"] == "SCHEDULED", (
            f"a refused dispatch must leave the leg SCHEDULED, got {after['status']}"
        )
        assert after["actual_out"] is None, (
            f"a refused dispatch must not record actual_out, got {after['actual_out']}"
        )

    def test_dispatch_admitted_once_the_airframe_is_returned_to_service(self, api):
        """PRD §3.1: A `RETURN_TO_SERVICE` event is accepted from `IN_MAINTENANCE` or `AOG`; it resets `hours_since_last_check` and `cycles_since_last_check` to 0, and lands the airframe in `ASSIGNED` when `assigned_lease_id` is non-null or `AVAILABLE` when it is null.
        PRD §3.6: Releasing a leg for departure is admissible only from `SCHEDULED`, advances `status` from `SCHEDULED` to `DISPATCHED`, and records the supplied `actual_out` off-blocks instant.
        PRD §2.10: Advancing the operational dimension never touches the financial dimension — dispatching and completing a leg both leave `billing_state` exactly as it was — and advancing the financial dimension never touches `status`.

        Design: Difficulty/cross_entity_state_dependency/dispatch_requires_airframe_returned_to_service
        """
        scenario = setup_active_lease(api)
        leg = schedule_leg(
            api, scenario, "2026-09-18T06:00:00Z", "2026-09-18T09:00:00Z"
        )
        record_maintenance_event(
            api, scenario["aircraft"]["id"], "GROUND_SCHEDULED", note="C-check slot"
        )
        released = record_maintenance_event(
            api,
            scenario["aircraft"]["id"],
            "RETURN_TO_SERVICE",
            note="Released to service",
        )
        assert released["status"] == "ASSIGNED", (
            "a return to service on a leased airframe must land in ASSIGNED, got "
            f"{released['status']}"
        )
        assert float(released["hours_since_last_check"]) == pytest.approx(
            0.00, abs=0.01
        ), (
            "return to service must reset hours_since_last_check to 0.00, got "
            f"{released['hours_since_last_check']}"
        )
        assert released["cycles_since_last_check"] == 0, (
            "return to service must reset cycles_since_last_check to 0, got "
            f"{released['cycles_since_last_check']}"
        )

        dispatched = validate_success(
            api.dispatch_flight_leg(
                leg["id"], dispatch_payload("2026-09-18T06:00:00Z"), OPS
            )
        )
        assert dispatched["status"] == "DISPATCHED", (
            "the identical dispatch must now succeed, expected DISPATCHED, got "
            f"{dispatched['status']}"
        )
        assert _instant(dispatched["actual_out"]) == _instant(
            "2026-09-18T06:00:00Z"
        ), (
            "dispatch must record the supplied off-blocks instant, expected "
            f"2026-09-18T06:00:00Z, got {dispatched['actual_out']}"
        )
        assert dispatched["billing_state"] == "UNBILLED", (
            "dispatch must leave the financial dimension untouched, expected UNBILLED, "
            f"got {dispatched['billing_state']}"
        )


class TestInvoiceApprovalReadsTheReliabilityReport:
    def test_approval_refused_while_the_month_s_only_report_is_rejected(self, api):
        """PRD §3.9: An `ACCEPTED` reliability report must exist for the invoice's lease and the period's `period_month`, else `ERR_RELIABILITY_REPORT_NOT_ACCEPTED` (HTTP 409).
        PRD §3.9: Approval moves the invoice from `PREPARED` to `APPROVED` and writes `approved_by_user_id` with the approver's identifier.

        Design: Difficulty/cross_entity_state_dependency/invoice_approval_requires_accepted_reliability_report
        """
        _, _, invoice = _prepared_invoice_over_rejected_report(api)

        response = api.approve_settlement_invoice(invoice["id"], APPROVER)
        validate_error(response, ApiErrorId.ERR_RELIABILITY_REPORT_NOT_ACCEPTED)

        fetched = get_success_data(api.get_settlement_invoice(invoice["id"], BILLING))
        assert fetched["status"] == "PREPARED", (
            "a refused approval must leave the invoice PREPARED, got "
            f"{fetched['status']}"
        )
        assert fetched["approved_by_user_id"] is None, (
            "a refused approval must not write approved_by_user_id, got "
            f"{fetched['approved_by_user_id']}"
        )

    def test_approval_admitted_once_a_resubmitted_report_is_accepted(self, api):
        """PRD §3.8: Acceptance moves the report from `SUBMITTED` to the terminal `ACCEPTED`, which both unblocks invoice approval for the same lease and month and feeds `technical_dispatch_reliability_pct` into the penalty on the next close.
        PRD §3.8: Rejection moves it from `SUBMITTED` to the terminal `REJECTED`, records the note, and frees the lease-airframe-month combination so a fresh report may be filed.
        PRD §3.8: `tdr_departure_basis_pct` is 100 multiplied by `revenue_departures` less `technical_delay_events`, divided by `revenue_departures`; when `revenue_departures` is 0 the figure is 100.00.
        PRD §3.9: Approval moves the invoice from `PREPARED` to `APPROVED` and writes `approved_by_user_id` with the approver's identifier.

        Design: Difficulty/cross_entity_state_dependency/invoice_approval_requires_accepted_reliability_report
        """
        scenario, rejected, invoice = _prepared_invoice_over_rejected_report(api)

        resubmitted = file_reliability_report(
            api, scenario, period_month="2026-09", decision=None
        )
        assert float(resubmitted["tdr_departure_basis_pct"]) == pytest.approx(
            100.00, abs=0.01
        ), (
            "one dispatched revenue leg with no technical delay must report a departure "
            f"basis of 100.00, got {resubmitted['tdr_departure_basis_pct']}"
        )

        accepted = get_success_data(
            api.review_reliability_report(
                resubmitted["id"],
                review_report_payload("ACCEPT", review_note="Recoded and agreed."),
                scenario["lessee_headers"],
            )
        )
        assert accepted["status"] == "ACCEPTED", (
            f"the lessee's ACCEPT must land the report ACCEPTED, got {accepted['status']}"
        )

        stale = get_success_data(api.get_reliability_report(rejected["id"], TECH))
        assert stale["status"] == "REJECTED", (
            "REJECTED is terminal, so the first report must be untouched, got "
            f"{stale['status']}"
        )

        approved = validate_success(
            api.approve_settlement_invoice(invoice["id"], APPROVER)
        )
        assert approved["status"] == "APPROVED", (
            "the identical approval must now succeed, expected APPROVED, got "
            f"{approved['status']}"
        )
        assert approved["approved_by_user_id"] == "billing-supervisor-02", (
            "approval must record the approver's identifier, expected "
            f"billing-supervisor-02, got {approved['approved_by_user_id']}"
        )
        assert approved["prepared_by_user_id"] == "billing-clerk-01", (
            "approval must not overwrite the preparer's identifier, expected "
            f"billing-clerk-01, got {approved['prepared_by_user_id']}"
        )
