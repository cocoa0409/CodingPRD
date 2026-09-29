"""Who may act, on whose behalf, and what a refusal looks like.

Authentication runs before authorization, authorization before carrier scope,
and the two segregation-of-duties comparisons run late because they read a value
off the target record rather than off the request's credentials.
"""

from test_helpers import (
    ANALYST_HEADERS,
    ANALYST_USER_ID,
    CAPACITY_PLANNER_HEADERS,
    CAPACITY_PLANNER_USER_ID,
    DUAL_HAT_USER_ID,
    SHIFT_LEAD_HEADERS,
    SHIFT_LEAD_USER_ID,
    UNDECLARED_ROLE,
    UNKNOWN_TICKET_UUID,
    VENDOR_MANAGER_HEADERS,
    VENDOR_MANAGER_USER_ID,
    ApiErrorId,
    advance_clock,
    assert_carrier_ledger,
    assert_circuit_posture,
    assert_credit_arithmetic,
    assert_instant,
    assert_page,
    assert_upgrade_cost,
    assert_utilization_pct,
    build_nlc_single_gold,
    build_pft_capacity_circuit,
    build_pft_single_leg,
    carrier_ticket_payload,
    carrier_update_payload,
    claim_submit_payload,
    create_carrier,
    create_manual_upgrade_order,
    find_auto_drafted_claim,
    make_carrier_liaison_headers,
    make_headers_with_undeclared_role,
    make_headers_without_user_id,
    make_vendor_manager_headers,
    open_carrier_ticket,
    propose_window,
    read_carrier,
    read_circuit,
    read_claim,
    read_ticket,
    read_window,
    record_reading,
    restore_and_confirm,
    stamped,
    submit_upgrade_order,
    validate_error,
    validate_paginated,
    validate_success,
    walk_incident_to_mitigated,
    window_review_payload,
)


class TestRoleAuthorization:
    """The authorized-role list is per operation, and a refusal changes nothing."""

    def test_an_analyst_may_not_review_the_window_it_filed(self, api):
        """Filing planned work is not the same authority as approving it.

        PRD 2.1: "A `NocShiftLead` carries shift authority: incident escalation and resolution, carrier tier escalation, restoration confirmation, maintenance-window review and execution, failover-test scheduling and result attestation."
        PRD 2.7: "The acting role appears in the operation's authorized-role list, else `ERR_UNAUTHORIZED` (403)."
        PRD 3.7: "Approving moves the window `PROPOSED → APPROVED`, stamps `approved_by_user_id` and persists the supplied `risk_acknowledged`; rejecting moves it `PROPOSED → REJECTED`, which is terminal, has no effect on any schedule, and still records the reviewer of record in `approved_by_user_id`."

        Design: Corner/rbac/corner_noc_analyst_cannot_review_a_maintenance_window
        """
        state = build_pft_single_leg(
            api,
            "2026-09-02T00:00:00Z",
            circuit_identifier="PFT-CKT-9004",
            site_z_code="IND01",
            with_segment=False,
        )
        window = propose_window(
            api,
            state["circuit_id"],
            "2026-09-02T02:00:00Z",
            "2026-09-02T03:00:00Z",
            suppresses_monitoring=True,
        )

        validate_error(
            api.review_maintenance_window(
                window["id"],
                window_review_payload("APPROVED", risk_acknowledged=True),
                ANALYST_HEADERS,
            ),
            ApiErrorId.ERR_UNAUTHORIZED,
        )

        refused = read_window(api, window["id"])
        assert refused["state"] == "PROPOSED", (
            f"the unauthorized review changed nothing, got {refused['state']}"
        )
        assert refused["approved_by_user_id"] is None, "no reviewer was recorded"

        approved = validate_success(
            api.review_maintenance_window(
                window["id"],
                window_review_payload("APPROVED", risk_acknowledged=True),
                SHIFT_LEAD_HEADERS,
            )
        )["data"]
        assert approved["state"] == "APPROVED", (
            f"the shift lead carries the authority, got {approved['state']}"
        )
        assert approved["approved_by_user_id"] == SHIFT_LEAD_USER_ID, (
            "the approving lead is the reviewer of record"
        )

    def test_a_vendor_manager_may_not_open_a_carrier_ticket(self, api):
        """The commercial desk cannot raise the operational case its claims rest on.

        PRD 2.1: "A `NocAnalyst` is the front-line operator: they ingest alarms, clear them, record circuit test evidence, triage incidents and open carrier trouble tickets."
        PRD 2.1: "A `VendorManager` owns the commercial relationship: filing, submitting, settling and withdrawing credit claims, running vendor performance reviews and replacement decisions, and approving upgrade orders."
        PRD 3.5: "A new ticket is created in `OPEN` with `tier_level` 1, and both `tier_entered_at` and `opened_at` set to the current clock instant."

        Design: Corner/rbac/corner_vendor_manager_cannot_open_a_carrier_ticket
        """
        state = build_pft_single_leg(
            api, "2026-09-02T00:00:00Z", alarm_raised_at="2026-09-02T00:00:00Z"
        )
        advance_clock(api, "2026-09-02T00:10:00Z")
        body = carrier_ticket_payload(
            state["incident_id"], state["circuit_id"], carrier_reference="PFT-TT-15"
        )

        validate_error(
            api.create_carrier_ticket(body, VENDOR_MANAGER_HEADERS),
            ApiErrorId.ERR_UNAUTHORIZED,
        )

        ticket = validate_success(
            api.create_carrier_ticket(body, ANALYST_HEADERS), 201
        )["data"]
        assert ticket["state"] == "OPEN", (
            f"the analyst's identical body opens the ticket, got {ticket['state']}"
        )
        assert ticket["carrier_reference"] == "PFT-TT-15", (
            "the refused attempt consumed nothing, not even the reference"
        )
        assert_instant(
            ticket["opened_at"], stamped("2026-09-02", "00:10"), "opened_at"
        )
        assert ticket["opened_by_user_id"] == ANALYST_USER_ID, (
            "the analyst who succeeded is the opener of record"
        )

        readable = validate_success(
            api.get_carrier_ticket(ticket["id"], VENDOR_MANAGER_HEADERS)
        )["data"]
        assert readable["id"] == ticket["id"], (
            "the manager who may not write the ticket may still read it"
        )


class TestCarrierScope:
    """A liaison acts as its carrier, so another carrier's rows are out of reach."""

    def _pft_ticket_and_a_second_carrier(self, api) -> dict:
        state = build_pft_single_leg(
            api, "2026-09-02T00:00:00Z", alarm_raised_at="2026-09-02T00:00:00Z"
        )
        other = create_carrier(api, name="Eastward Telecom", carrier_code="EWT")
        advance_clock(api, "2026-09-02T00:10:00Z")
        ticket = open_carrier_ticket(
            api, state["incident_id"], state["circuit_id"], "PFT-TT-16"
        )
        state["ticket_id"] = ticket["id"]
        state["other_liaison_headers"] = make_carrier_liaison_headers(other["id"])
        return state

    def test_another_carriers_liaison_cannot_read_the_ticket(self, api):
        """Scope, not authorization, is what refuses the neighbouring carrier.

        PRD 2.1: "`CarrierLiaison` is different: when `X-User-Role` is `CarrierLiaison`, `X-User-ID` is the `id` of the acting carrier, and every ownership check compares a resource's carrier reference to that value."
        PRD 2.1: "Read access granted to a `CarrierLiaison` is scoped the same way — a liaison sees its own carrier, its own carrier's circuits, tickets, test evidence, claims and windows."
        PRD 2.1: "Any mismatch is rejected with `ERR_CARRIER_SCOPE_VIOLATION` (HTTP 403)."

        Design: Corner/rbac/corner_carrier_liaison_cannot_read_another_carriers_ticket
        """
        state = self._pft_ticket_and_a_second_carrier(api)

        validate_error(
            api.get_carrier_ticket(
                state["ticket_id"], state["other_liaison_headers"]
            ),
            ApiErrorId.ERR_CARRIER_SCOPE_VIOLATION,
        )

        owned = validate_success(
            api.get_carrier_ticket(state["ticket_id"], state["liaison_headers"])
        )["data"]
        assert owned["carrier_reference"] == "PFT-TT-16", (
            "the owning carrier's liaison reads its own ticket"
        )
        assert owned["carrier_id"] == state["carrier_id"], (
            "the ticket belongs to the carrier whose liaison could read it"
        )

    def test_the_same_scope_refuses_the_carrier_side_write(self, api):
        """The no-fault update would otherwise be admissible, and scope still refuses it.

        PRD 2.7: "For a `CarrierLiaison`, `X-User-ID` must equal the `carrier_id` of the targeted carrier ticket, credit claim or maintenance window — and, when a window is being created with `origin` `CARRIER_NOTIFIED`, the `carrier_id` of the circuit named by `circuit_id` — else `ERR_CARRIER_SCOPE_VIOLATION` (403)."
        PRD 2.7: "This guards exactly four operations: posting a carrier ticket update, answering a credit claim, creating a maintenance window with carrier origin, and reviewing a maintenance window."

        Design: Corner/rbac/corner_carrier_liaison_cannot_read_another_carriers_ticket
        """
        state = self._pft_ticket_and_a_second_carrier(api)

        validate_error(
            api.carrier_update_ticket(
                state["ticket_id"],
                carrier_update_payload("NO_FAULT_FOUND"),
                state["other_liaison_headers"],
            ),
            ApiErrorId.ERR_CARRIER_SCOPE_VIOLATION,
        )

        unchanged = read_ticket(api, state["ticket_id"])
        assert unchanged["state"] == "OPEN", (
            f"the out-of-scope update moved nothing, got {unchanged['state']}"
        )
        assert unchanged["fail_test_count"] == 0, (
            "no evidence was invented by the refused write"
        )


class TestSegregationOfDuties:
    """Two decisions may not be taken by the person who created what is decided."""

    def test_the_confirming_operator_may_not_submit_the_claim(self, api):
        """dual-1 attested the restoration, so dual-1 cannot file the money claim.

        PRD 2.11: "The operator who confirmed a restoration may not submit the credit claim that arises from it: on submission, `X-User-ID` is compared against the ticket's `restoration_confirmed_by_user_id`, and equality is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
        PRD 3.6: "The acting `X-User-ID` must differ from the ticket's `restoration_confirmed_by_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES`."
        PRD 3.6: "Success stamps `submitted_by_user_id` and `submitted_at` and advances the claim's `version` and the carrier's `version` by 1 each."

        Design: Corner/rbac/corner_confirming_user_cannot_also_submit_the_claim
        """
        state = build_nlc_single_gold(
            api,
            "2026-09-02T00:00:00Z",
            ticket_reference="NLC-TT-90002",
            ticket_opened_at="2026-09-02T00:30:00Z",
        )
        restore_and_confirm(
            api,
            state["ticket_id"],
            state["carrier_id"],
            state["alarm_id"],
            "2026-09-02T06:00:00Z",
            "2026-09-02T06:30:00Z",
            confirmer_user_id=DUAL_HAT_USER_ID,
        )
        walk_incident_to_mitigated(api, state["incident_id"])

        claim = find_auto_drafted_claim(api, state["ticket_id"])
        assert claim is not None, "the breached restoration drafted a claim"

        validate_error(
            api.submit_sla_credit_claim(
                claim["id"],
                claim_submit_payload(
                    attestation_note="same person who signed off the restoration"
                ),
                make_vendor_manager_headers(DUAL_HAT_USER_ID),
            ),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
        )

        refused = read_claim(api, claim["id"])
        assert refused["state"] == "DRAFT", (
            f"the refused submission left the claim a draft, got {refused['state']}"
        )
        assert refused["submitted_at"] is None, "nothing was filed"
        assert refused["submitted_by_user_id"] is None, "no filer was recorded"

        submitted = validate_success(
            api.submit_sla_credit_claim(
                claim["id"],
                claim_submit_payload(
                    attestation_note="filed by the commercial desk"
                ),
                VENDOR_MANAGER_HEADERS,
            )
        )["data"]
        assert submitted["state"] == "SUBMITTED", (
            f"a different operator may file it, got {submitted['state']}"
        )
        assert submitted["submitted_by_user_id"] == VENDOR_MANAGER_USER_ID, (
            "the filing manager is stamped on the claim"
        )
        assert_credit_arithmetic(
            submitted, basis="CARRIER_CLOCK", credit_amount_cents=92000
        )
        assert_carrier_ledger(
            read_carrier(api, state["carrier_id"]),
            exposure_cents=92000,
            watchlist_state="ACTIVE",
        )

    def test_the_order_creator_may_not_approve_it(self, api):
        """cp-1 raised the order, so cp-1 cannot approve it even wearing the right role.

        PRD 2.11: "The operator who created an upgrade order may not approve it: on approval, `X-User-ID` is compared against the order's `created_by_user_id`, and equality is refused with the same identifier and status."
        PRD 3.8: "Approval stamps `approved_by_user_id`."

        Design: Corner/rbac/corner_upgrade_order_creator_cannot_approve_own_order
        """
        state = build_pft_capacity_circuit(api, "2026-09-02T00:00:00Z")
        order = create_manual_upgrade_order(
            api,
            state["circuit_id"],
            200,
            state["circuit_version"],
            user_id=CAPACITY_PLANNER_USER_ID,
        )
        submit_upgrade_order(api, order["id"], user_id=CAPACITY_PLANNER_USER_ID)

        validate_error(
            api.approve_upgrade_order(
                order["id"], {}, make_vendor_manager_headers(CAPACITY_PLANNER_USER_ID)
            ),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
        )

        rows, meta = validate_paginated(
            api.list_circuit_upgrade_orders(
                state["circuit_id"], CAPACITY_PLANNER_HEADERS
            )
        )
        assert_page(meta, total_count=1)
        refused = rows[0]
        assert refused["state"] == "SUBMITTED", (
            f"the refused approval left the order submitted, got {refused['state']}"
        )
        assert refused["approved_by_user_id"] is None, "no approver was recorded"
        assert refused["created_by_user_id"] == CAPACITY_PLANNER_USER_ID, (
            "the creator is the planner the check compared against"
        )

        approved = validate_success(
            api.approve_upgrade_order(order["id"], {}, VENDOR_MANAGER_HEADERS)
        )["data"]
        assert approved["state"] == "APPROVED", (
            f"a different manager may approve it, got {approved['state']}"
        )
        assert approved["approved_by_user_id"] == VENDOR_MANAGER_USER_ID, (
            "the approving manager is stamped"
        )
        assert_upgrade_cost(
            approved,
            delta_mbps=100,
            subtotal_cents=340000,
            expedite_fee_cents=0,
            total_cost_cents=340000,
        )


class TestSharedReadSurface:
    """Shared reads really are shared across the operational and planning roles."""

    def test_the_planner_and_the_analyst_both_reach_the_capacity_reads(self, api):
        """The planner reads circuits and carriers; the analyst reads the samples.

        PRD 2.1: "If both headers are well formed but the named role is not permitted to invoke the requested operation — the authorization matrix is the Authorized Role(s) column of the endpoint table in Section 4 — the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD 2.1: "A `CapacityPlanner` owns utilization: ingesting samples and driving upgrade orders from draft through completion."
        PRD 3.8: "Readings may be listed per circuit and narrowed by `direction` and `threshold_state`."

        Design: Corner/rbac/corner_capacity_planner_shares_the_read_surface
        """
        state = build_pft_capacity_circuit(api, "2026-09-02T00:00:00Z")
        record_reading(
            api, state["circuit_id"], "2026-09-02T00:05:00Z", 70.00, direction="EGRESS"
        )

        circuit = validate_success(
            api.get_circuit(state["circuit_id"], CAPACITY_PLANNER_HEADERS)
        )["data"]
        carrier = validate_success(
            api.get_carrier(state["carrier_id"], CAPACITY_PLANNER_HEADERS)
        )["data"]
        assert circuit["id"] == state["circuit_id"], (
            "the planner reads the circuit it samples"
        )
        assert carrier["id"] == state["carrier_id"], (
            "the planner reads the carrier that owns it"
        )

        rows, meta = validate_paginated(
            api.list_capacity_readings(
                state["circuit_id"], ANALYST_HEADERS, {"direction": "EGRESS"}
            )
        )
        assert_page(meta, total_count=1)
        assert_utilization_pct(rows[0]["utilization_pct"], 70.00)
        assert rows[0]["threshold_state"] == "NORMAL", (
            f"70.00 is below the bound, got {rows[0]['threshold_state']}"
        )
        assert_circuit_posture(
            read_circuit(api, state["circuit_id"]),
            capacity_state="NORMAL",
            consecutive_high_readings=0,
        )


class TestRefusalEnvelopes:
    """A refusal is an envelope contract, not a partial resource."""

    def test_an_unknown_ticket_id_answers_a_bare_not_found_envelope(self, api):
        """The 404 body carries an error identifier and a message, and no ticket fields.

        PRD 2.7: "A missing carrier, circuit, device, application path, path segment, alarm, incident, carrier ticket, credit claim, maintenance window, failover test, upgrade order or vendor review yields `ERR_CARRIER_NOT_FOUND`, `ERR_CIRCUIT_NOT_FOUND`, `ERR_DEVICE_NOT_FOUND`, `ERR_PATH_NOT_FOUND`, `ERR_SEGMENT_NOT_FOUND`, `ERR_ALARM_NOT_FOUND`, `ERR_INCIDENT_NOT_FOUND`, `ERR_TICKET_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_WINDOW_NOT_FOUND`, `ERR_TEST_NOT_FOUND`, `ERR_ORDER_NOT_FOUND` or `ERR_REVIEW_NOT_FOUND` respectively, all HTTP 404."
        PRD 2.2: "The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`."
        PRD 2.2: "The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`."

        Design: Corner/errors/corner_unknown_ticket_id_returns_not_found_with_error_envelope
        """
        advance_clock(api, "2026-09-02T00:00:00Z")
        create_carrier(api)

        response = api.get_carrier_ticket(UNKNOWN_TICKET_UUID, ANALYST_HEADERS)
        error_data = validate_error(response, ApiErrorId.ERR_TICKET_NOT_FOUND, 404)

        body = response.json()
        assert body["response_type"] == "error", (
            f"a refusal is an error envelope, got {body['response_type']!r}"
        )
        assert body["meta"]["api_request_id"].startswith("req_"), (
            f"the request identifier is malformed: {body['meta']['api_request_id']!r}"
        )
        for field in ("state", "carrier_reference", "tier_level", "opened_at"):
            assert field not in error_data, (
                f"the error body must carry no ticket fields, but held {field}"
            )

    def test_a_request_without_a_user_id_is_unauthenticated(self, api):
        """A missing identity, and an undeclared role, are both 401 rather than 403.

        PRD 2.1: "If either header is absent, or if `X-User-Role` is not one of the six roles defined below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
        PRD 2.7: "Checks are evaluated strictly in the ascending sequence below; the first failure short-circuits the request and no later check runs."
        PRD 2.7: "Both headers present and `X-User-Role` one of the six declared roles, else `ERR_UNAUTHENTICATED` (401)."

        Design: Corner/errors/corner_missing_x_user_id_header_is_unauthenticated
        """
        advance_clock(api, "2026-09-02T00:00:00Z")
        carrier = create_carrier(api)

        validate_error(
            api.get_carrier(carrier["id"], make_headers_without_user_id("NocAnalyst")),
            ApiErrorId.ERR_UNAUTHENTICATED,
            401,
        )

        allowed = validate_success(api.get_carrier(carrier["id"], ANALYST_HEADERS))[
            "data"
        ]
        assert allowed["id"] == carrier["id"], (
            "the same read succeeds once both headers are present"
        )

        undeclared = validate_error(
            api.get_carrier(carrier["id"], make_headers_with_undeclared_role()),
            ApiErrorId.ERR_UNAUTHENTICATED,
            401,
        )
        assert undeclared["error_id"] == ApiErrorId.ERR_UNAUTHENTICATED, (
            f"an undeclared role is unauthenticated rather than unauthorized; "
            f"{UNDECLARED_ROLE} produced {undeclared['error_id']}"
        )
