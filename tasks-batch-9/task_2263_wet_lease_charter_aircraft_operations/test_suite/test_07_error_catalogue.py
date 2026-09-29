"""Error catalogue triggerability.

Each entity family owns its own 404 identifier, authentication is decided strictly ahead
of everything else, and the two-state guards on the lessee credit-control cycle and on the
authority docket are real source-state guards rather than idempotent no-ops.
"""

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    clear_conditions_payload,
    create_lessee,
    determination_payload,
    get_success_data,
    qualify_crew_member,
    revoke_payload,
    set_clock,
    setup_approved_lease,
    setup_filed_lease,
    validate_error,
    validate_success,
)

OPS = TEST_USERS["lessor_ops_headers"]
AUTHORITY = TEST_USERS["regulatory_authority_headers"]
TECH = TEST_USERS["maintenance_controller_headers"]
BILLING = TEST_USERS["billing_admin_headers"]

CLOCK = "2026-09-01T00:00:00Z"

# A well-formed X-User-ID with the X-User-Role header omitted entirely.
NO_ROLE_HEADERS = {"X-User-ID": "ops-controller-1", "Content-Type": "application/json"}


class TestDistinctNotFoundIdentifiers:
    @pytest.mark.parametrize(
        "reader,role_headers_key,expected_error",
        [
            ("get_lessee", "lessor_ops_headers", ApiErrorId.ERR_LESSEE_NOT_FOUND),
            ("get_aircraft", "maintenance_controller_headers", ApiErrorId.ERR_AIRCRAFT_NOT_FOUND),
            ("get_lease", "lessor_ops_headers", ApiErrorId.ERR_LEASE_NOT_FOUND),
            ("get_crew_member", "lessor_ops_headers", ApiErrorId.ERR_CREW_MEMBER_NOT_FOUND),
            ("get_crew_qualification", "lessor_ops_headers", ApiErrorId.ERR_QUALIFICATION_NOT_FOUND),
            ("get_regulatory_approval", "regulatory_authority_headers", ApiErrorId.ERR_APPROVAL_NOT_FOUND),
            ("get_insurance_certificate", "insurance_underwriter_headers", ApiErrorId.ERR_CERTIFICATE_NOT_FOUND),
            ("get_flight_leg", "lessor_ops_headers", ApiErrorId.ERR_FLIGHT_LEG_NOT_FOUND),
            ("get_substitution", "lessor_ops_headers", ApiErrorId.ERR_SUBSTITUTION_NOT_FOUND),
            ("get_utilization_period", "billing_admin_headers", ApiErrorId.ERR_PERIOD_NOT_FOUND),
            ("get_settlement_invoice", "billing_admin_headers", ApiErrorId.ERR_INVOICE_NOT_FOUND),
            ("get_reliability_report", "maintenance_controller_headers", ApiErrorId.ERR_REPORT_NOT_FOUND),
            ("get_return_condition", "lessor_ops_headers", ApiErrorId.ERR_RETURN_CONDITION_NOT_FOUND),
        ],
    )
    def test_each_entity_family_reports_its_own_not_found_identifier(
        self, api, reader, role_headers_key, expected_error
    ):
        """PRD §2.8: **Existence**, resolved in this order and, where a single request carries several identifiers of one kind, left to right in the order the fields are declared in the request: a lessee identifier (`lesseeId` in the path or `lessee_id` in the body) resolving to a `Lessee`, else `ERR_LESSEE_NOT_FOUND`; then every aircraft identifier (`aircraftId`, `primary_aircraft_id`, `original_aircraft_id`, `substitute_aircraft_id`, `aircraft_id`) resolving to an `Aircraft`, else `ERR_AIRCRAFT_NOT_FOUND`; then `leaseId` or `lease_id` resolving to a `LeaseAgreement`, else `ERR_LEASE_NOT_FOUND`; then `crewMemberId`, `crew_member_id`, `captain_id` and `first_officer_id` resolving to `CrewMember` rows, else `ERR_CREW_MEMBER_NOT_FOUND`; then `qualificationId`, else `ERR_QUALIFICATION_NOT_FOUND`; then `approvalId`, else `ERR_APPROVAL_NOT_FOUND`; then `certificateId`, else `ERR_CERTIFICATE_NOT_FOUND`; then `legId` in the path and `repositioning_leg_id` in the body, else `ERR_FLIGHT_LEG_NOT_FOUND`; then `substitutionId`, else `ERR_SUBSTITUTION_NOT_FOUND`; then `periodId` in the path and `period_id` in the body, else `ERR_PERIOD_NOT_FOUND`; then `invoiceId`, else `ERR_INVOICE_NOT_FOUND`; then `reportId`, else `ERR_REPORT_NOT_FOUND`; then `returnId`, else `ERR_RETURN_CONDITION_NOT_FOUND`.
        PRD §2.8: Because most write endpoints in this system guard against half a dozen distinct failures, the order in which checks run is part of the contract: the first check that fails determines the response, and a later check never masks an earlier one.

        Design: Corner/errors/every_entity_family_has_its_own_distinct_not_found_error
        """
        set_clock(api, CLOCK)

        response = getattr(api, reader)(NON_EXISTENT_UUID, TEST_USERS[role_headers_key])

        error = validate_error(response, expected_error)
        assert error["error_id"] == expected_error.value, (
            f"an unresolvable identifier on {reader} must report the family-specific "
            f"{expected_error.value}, not a generic not-found identifier"
        )


class TestAuthenticationPrecedesEverything:
    def test_a_read_with_no_role_header_is_unauthenticated_and_never_unauthorized(self, api):
        """PRD §2.1: Every request must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the capacity in which it acts.
        PRD §2.1: If either header is absent, or if `X-User-Role` is not one of the six declared roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401).
        PRD §2.8: **Authentication** — headers present and `X-User-Role` one of the six declared roles, else `ERR_UNAUTHENTICATED`.

        Design: Corner/errors/requests_with_no_role_header_are_unauthenticated_before_anything_else_runs
        """
        scenario = setup_approved_lease(api, clock=CLOCK)
        qualify_crew_member(api, scenario["captain"]["id"], scenario["lease"]["id"])

        response = api.get_lease(scenario["lease"]["id"], NO_ROLE_HEADERS)

        error = validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED)
        assert error["error_id"] != ApiErrorId.ERR_UNAUTHORIZED.value, (
            "a request with no X-User-Role header must fail authentication, not authorisation"
        )

    def test_a_mutation_with_no_role_header_is_unauthenticated_and_leaves_no_trace(self, api):
        """PRD §2.1: If either header is absent, or if `X-User-Role` is not one of the six declared roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401).
        PRD §2.8: **Authentication** — headers present and `X-User-Role` one of the six declared roles, else `ERR_UNAUTHENTICATED`.
        PRD §2.8: Because most write endpoints in this system guard against half a dozen distinct failures, the order in which checks run is part of the contract: the first check that fails determines the response, and a later check never masks an earlier one.
        PRD §3.5: It sets the primary airframe from `AVAILABLE` to `ASSIGNED` and writes `assigned_lease_id` to the lease.

        Design: Corner/errors/requests_with_no_role_header_are_unauthenticated_before_anything_else_runs
        """
        scenario = setup_approved_lease(api, clock=CLOCK)
        qualify_crew_member(api, scenario["captain"]["id"], scenario["lease"]["id"])

        response = api.activate_lease(scenario["lease"]["id"], NO_ROLE_HEADERS)

        error = validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED)
        assert error["error_id"] != ApiErrorId.ERR_UNAUTHORIZED.value, (
            "an anonymous activate must fail authentication, not authorisation"
        )

        lease = get_success_data(api.get_lease(scenario["lease"]["id"], OPS))
        assert lease["status"] == "APPROVED", (
            f"the rejected activate must leave the lease APPROVED, got {lease['status']}"
        )
        aircraft = get_success_data(api.get_aircraft(scenario["aircraft"]["id"], TECH))
        assert aircraft["status"] == "AVAILABLE", (
            "the rejected activate must not assign the airframe, so it stays AVAILABLE, "
            f"got {aircraft['status']}"
        )
        assert aircraft["assigned_lease_id"] is None, (
            "the rejected activate must leave assigned_lease_id null"
        )


class TestLesseeCreditControlCycleGuards:
    def test_both_directions_of_the_credit_control_cycle_guard_their_source_state(self, api):
        """PRD §3.1: A `BillingAdmin` may suspend an `ACTIVE` lessee, moving `status` from `ACTIVE` to `SUSPENDED`, and may reinstate a `SUSPENDED` one, moving it back from `SUSPENDED` to `ACTIVE`.
        PRD §3.1: Suspending a lessee that is not `ACTIVE`, or reinstating one that is not `SUSPENDED`, is rejected with `ERR_LESSEE_INVALID_STATE` (HTTP 409).
        PRD §3.1: Neither leg of the cycle touches `outstanding_balance_usd_cents` or `credit_limit_usd_cents`.

        Design: Corner/errors/reinstating_an_active_lessee_and_suspending_a_suspended_one_both_return_lessee_invalid_state
        """
        set_clock(api, CLOCK)
        lessee = create_lessee(api)

        validate_error(
            api.reinstate_lessee(lessee["id"], BILLING),
            ApiErrorId.ERR_LESSEE_INVALID_STATE,
        )

        suspended = validate_success(api.suspend_lessee(lessee["id"], BILLING), 200)
        assert suspended["status"] == "SUSPENDED", (
            f"suspending an ACTIVE lessee must land SUSPENDED, got {suspended['status']}"
        )

        validate_error(
            api.suspend_lessee(lessee["id"], BILLING),
            ApiErrorId.ERR_LESSEE_INVALID_STATE,
        )
        still_suspended = get_success_data(api.get_lessee(lessee["id"], BILLING))
        assert still_suspended["status"] == "SUSPENDED", (
            "the rejected second suspend must leave the lessee SUSPENDED, got "
            f"{still_suspended['status']}"
        )

        reinstated = validate_success(api.reinstate_lessee(lessee["id"], BILLING), 200)
        assert reinstated["status"] == "ACTIVE", (
            f"reinstating a SUSPENDED lessee must land ACTIVE, got {reinstated['status']}"
        )
        assert reinstated["outstanding_balance_usd_cents"] == 0, (
            "neither leg of the credit-control cycle may touch the receivable, expected 0, "
            f"got {reinstated['outstanding_balance_usd_cents']}"
        )


class TestDecidedDocketGuards:
    def test_a_decided_docket_refuses_a_further_decision_and_condition_clearance(self, api):
        """PRD §3.2: A determination requested from a docket that is not in a declared source state — anything other than `UNDER_REVIEW` for the first three rulings, or other than `CONDITIONAL` for the denial of a conditioned docket — is rejected with `ERR_APPROVAL_INVALID_STATE`.
        PRD §3.2: The clearance is admissible only while the `determination` is `CONDITIONAL`, and only when every code still listed in `open_condition_codes` appears in the supplied array — that is, when nothing would remain open afterwards.

        Design: Corner/errors/decision_clear_conditions_and_double_revoke_on_a_settled_docket_return_approval_invalid_state
        """
        scenario = setup_filed_lease(api, determination="APPROVED", clock=CLOCK)
        approval_id = scenario["approval"]["id"]

        validate_error(
            api.record_determination(
                approval_id,
                determination_payload("CONDITIONAL", conditions=["OPS_MANUAL_SUPP_B"]),
                AUTHORITY,
            ),
            ApiErrorId.ERR_APPROVAL_INVALID_STATE,
        )
        validate_error(
            api.clear_approval_conditions(
                approval_id, clear_conditions_payload(["OPS_MANUAL_SUPP_B"]), AUTHORITY
            ),
            ApiErrorId.ERR_APPROVAL_INVALID_STATE,
        )

        docket = get_success_data(api.get_regulatory_approval(approval_id, AUTHORITY))
        assert docket["determination"] == "APPROVED", (
            f"the rejected rulings must leave the docket APPROVED, got {docket['determination']}"
        )
        assert docket["review_round"] == 1, (
            f"a rejected ruling must not advance review_round, got {docket['review_round']}"
        )
        assert docket["conditions"] == [], (
            f"the rejected CONDITIONAL ruling must write no conditions, got {docket['conditions']}"
        )
        assert docket["open_condition_codes"] == [], (
            "the rejected clearance must leave open_condition_codes empty, got "
            f"{docket['open_condition_codes']}"
        )

    def test_revocation_is_terminal_so_the_second_revoke_is_refused(self, api):
        """PRD §3.2: Revocation is the docket's terminal act.
        PRD §3.2: The authority revokes from `APPROVED` or from `CONDITIONAL` by supplying a `revocation_reason`; the docket moves to the terminal `REVOKED`, `decided_at` is set, the lease moves from `ACTIVE` to `SUSPENDED` with `suspension_reason` `REGULATORY_APPROVAL_REVOKED`, every leg on that lease still `SCHEDULED` or `DISPATCHED` is cancelled into `CANCELLED_LESSOR` with `cancel_reason` `REGULATORY`, and each such cancellation recomputes the affected crew members' rolling exposure and the covering open month's charge.
        PRD §3.2: A determination requested from a docket that is not in a declared source state — anything other than `UNDER_REVIEW` for the first three rulings, or other than `CONDITIONAL` for the denial of a conditioned docket — is rejected with `ERR_APPROVAL_INVALID_STATE`.

        Design: Corner/errors/decision_clear_conditions_and_double_revoke_on_a_settled_docket_return_approval_invalid_state
        """
        scenario = setup_filed_lease(api, determination="APPROVED", clock=CLOCK)
        approval_id = scenario["approval"]["id"]

        revoked = validate_success(
            api.revoke_regulatory_approval(
                approval_id, revoke_payload("OPERATIONAL_CONTROL_FINDING"), AUTHORITY
            ),
            200,
        )
        assert revoked["determination"] == "REVOKED", (
            f"revocation must land the docket in REVOKED, got {revoked['determination']}"
        )
        assert revoked["revocation_reason"] == "OPERATIONAL_CONTROL_FINDING", (
            "the first revocation must record its reason, got "
            f"{revoked['revocation_reason']!r}"
        )

        validate_error(
            api.revoke_regulatory_approval(
                approval_id, revoke_payload("DUPLICATE_FILING"), AUTHORITY
            ),
            ApiErrorId.ERR_APPROVAL_INVALID_STATE,
        )

        docket = get_success_data(api.get_regulatory_approval(approval_id, AUTHORITY))
        assert docket["revocation_reason"] == "OPERATIONAL_CONTROL_FINDING", (
            "the refused second revoke must not overwrite the recorded revocation_reason, got "
            f"{docket['revocation_reason']!r}"
        )
        lease = get_success_data(api.get_lease(scenario["lease"]["id"], OPS))
        assert lease["status"] == "APPROVED", (
            "a lease that never entered service is not suspended by the revocation, expected "
            f"APPROVED, got {lease['status']}"
        )
