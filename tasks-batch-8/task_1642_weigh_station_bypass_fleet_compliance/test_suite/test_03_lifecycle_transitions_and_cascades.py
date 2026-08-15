"""Lifecycle state machines: legal transitions, terminal lockdowns, and the
termination / retirement cascades."""
from test_helpers import (
    ADMIN,
    FINANCE,
    GATEWAY,
    OFFICER,
    SPM,
    ApiErrorId,
    assert_credential,
    assert_invoice,
    create_active_carrier,
    create_carrier,
    create_config,
    create_credential_for,
    create_station,
    create_subscription_for,
    create_vehicle_for,
    get_carrier,
    list_credentials_for,
    list_events_for,
    list_overrides_for,
    list_subscriptions_for,
    make_carrier_manager_headers,
    make_compliance_officer_headers,
    post_snapshot,
    request_override,
    set_clock,
    setup_bypass_ready,
    setup_carrier_with_invoice,
    transition_carrier,
    validate_error,
    validate_success,
)


class TestCarrierLifecycle:
    def test_terminated_carrier_rejects_all_transitions(self, api):
        """PRD §3.1: "Termination is the exclusive, terminal act of a
        `PlatformAdmin`, available from `ENROLLED`, `ACTIVE`, or `SUSPENDED`"
        PRD §2.10: "The target resource must be in a from-state that permits
        the requested transition, with terminal states locked and same-state
        no-ops rejected — otherwise `ERR_INVALID_STATE_TRANSITION`."

        Design: Corner/state_machines/carrier_terminal_lockdown_returns_409
        """
        set_clock()
        carrier = create_carrier(dot_number="100001", legal_name="Acme Hauling")
        terminated = transition_carrier(carrier["id"], "TERMINATED", headers=ADMIN)
        assert terminated["status"] == "TERMINATED"
        resp = api.transition_carrier(carrier["id"], "ACTIVE", OFFICER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        assert get_carrier(carrier["id"])["status"] == "TERMINATED"

    def test_carrier_terminate_cascades_to_children(self, api):
        """PRD §3.1: "it cascades through everything the carrier owns: every
        credential not yet `DEACTIVATED` becomes `DEACTIVATED` with
        `status_reason` `CARRIER_TERMINATED`; every subscription in
        `SCHEDULED`, `ACTIVE`, or `PAUSED` closes with `closed_reason`
        `TERMINATED_CARRIER`, its `service_end_date` pulled back to today when
        it still lies in the future; and every eligibility override in
        `REQUESTED`, `APPROVED`, or `ACTIVE` is revoked."

        Design: Corner/state_machines/carrier_terminate_cascades_children
        """
        fx = setup_bypass_ready()
        override = request_override(fx["carrier"]["id"],
                                    start_date="2026-09-01",
                                    end_date="2026-10-01")
        assert override["status"] == "REQUESTED"

        terminated = transition_carrier(fx["carrier"]["id"], "TERMINATED",
                                        headers=ADMIN)
        assert terminated["status"] == "TERMINATED"

        creds = list_credentials_for(carrier_id=fx["carrier"]["id"])
        assert len(creds) == 1
        assert creds[0]["status"] == "DEACTIVATED"
        assert creds[0]["status_reason"] == "CARRIER_TERMINATED"

        subs = list_subscriptions_for(carrier_id=fx["carrier"]["id"])
        assert len(subs) == 1
        assert subs[0]["status"] == "CLOSED"
        assert subs[0]["closed_reason"] == "TERMINATED_CARRIER"

        overrides = list_overrides_for(fx["carrier"]["id"])
        assert len(overrides) == 1
        assert overrides[0]["status"] == "REVOKED"

    def test_suspend_reinstate_cycle_is_unlimited(self, api):
        """PRD §3.1: "Once active, a `ComplianceOfficer` may suspend the
        carrier (`ACTIVE` to `SUSPENDED`) and later reinstate it (`SUSPENDED`
        to `ACTIVE`), and this loop may cycle without limit."
        PRD §3.1: "Each lifecycle transition — approval, suspension,
        reinstatement, termination — increments the carrier's `version` by
        exactly one."

        Design: Difficulty/non_linear_state_machine/carrier_suspend_reinstate_cycle
        """
        set_clock()
        carrier = create_active_carrier()
        v_after_approve = carrier["version"]

        expected = ["SUSPENDED", "ACTIVE", "SUSPENDED", "ACTIVE"]
        previous_version = v_after_approve
        for target in expected:
            data = transition_carrier(carrier["id"], target)
            assert data["status"] == target
            assert data["version"] == previous_version + 1, \
                "each lifecycle transition increments the carrier's version by exactly one"
            previous_version = data["version"]
        assert previous_version == v_after_approve + 4, \
            "two full suspend/reinstate cycles completed without limit"

    def test_manual_suspension_does_not_cascade(self, api):
        """PRD §3.1: "Manual suspension does not cascade — a suspended
        carrier's credentials and subscriptions are left exactly as they
        were."
        PRD §3.2: "Posture never touches the lifecycle machine."

        Design: Difficulty/non_linear_state_machine/carrier_suspend_reinstate_cycle
        """
        fx = setup_bypass_ready()
        suspended = transition_carrier(fx["carrier"]["id"], "SUSPENDED")
        assert suspended["status"] == "SUSPENDED"
        assert suspended["eligibility_status"] == "ELIGIBLE", \
            "manual suspension does not alter the posture dimension"

        cred = api.get_credential(fx["credential"]["id"], FINANCE)
        cred_data = validate_success(cred)
        assert cred_data["status"] == "ACTIVE", "credential left exactly as it was"
        sub = api.get_subscription(fx["subscription"]["id"], FINANCE)
        sub_data = validate_success(sub)
        assert sub_data["status"] == "ACTIVE", "subscription left exactly as it was"

        reinstated = transition_carrier(fx["carrier"]["id"], "ACTIVE")
        assert reinstated["status"] == "ACTIVE"

    def test_reinstate_while_ineligible_rejected(self, api):
        """PRD §3.1: "Reinstatement carries its own gate: the posture must be
        anything other than `INELIGIBLE`, or the request fails with
        `ERR_CARRIER_STILL_INELIGIBLE` (HTTP 422)."

        Design: Corner/validations/carrier_reinstate_while_ineligible_returns_422
        """
        set_clock()
        carrier = create_active_carrier(iss_score=30)
        post_snapshot(carrier["id"], iss_score=90, safety_rating="UNSATISFACTORY")
        assert get_carrier(carrier["id"])["eligibility_status"] == "INELIGIBLE"
        suspended = transition_carrier(carrier["id"], "SUSPENDED")
        assert suspended["status"] == "SUSPENDED"

        resp = api.transition_carrier(carrier["id"], "ACTIVE", OFFICER)
        validate_error(resp, ApiErrorId.ERR_CARRIER_STILL_INELIGIBLE)
        assert get_carrier(carrier["id"])["status"] == "SUSPENDED"


class TestConfigAndStationMachines:
    def test_participating_to_pilot_rejected(self, api):
        """PRD §3.3: "What no patch may do is return a config to `PILOT`:
        from `SUSPENDED` or `PARTICIPATING` back to `PILOT` is an illegal
        transition, rejected with `ERR_INVALID_STATE_TRANSITION`."

        Design: Corner/state_machines/config_participating_to_pilot_returns_409
        """
        config = create_config(state_code="CA", promote_to_participating=True)
        assert config["participation_status"] == "PARTICIPATING"
        resp = api.patch_config(
            config["id"],
            {"participation_status": "PILOT",
             "expected_state_program_config_version": config["version"]},
            SPM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        fresh = validate_success(api.get_config(config["id"], SPM))
        assert fresh["participation_status"] == "PARTICIPATING"
        assert fresh["version"] == config["version"], "rejected patch leaves the row unchanged"

    def test_station_closed_perm_is_terminal(self, api):
        """PRD §3.3: "`CLOSED_PERM` is terminal and reachable from either
        operational state."
        PRD §2.10: "...with terminal states locked and same-state no-ops
        rejected — otherwise `ERR_INVALID_STATE_TRANSITION`."

        Design: Corner/state_machines/station_closed_perm_terminal_returns_409
        """
        config = create_config(state_code="CA")
        station = create_station(config["id"], station_code="CA-S1")
        closed = validate_success(api.patch_station(
            station["id"], {"operational_status": "CLOSED_PERM"}, SPM))
        assert closed["operational_status"] == "CLOSED_PERM"
        resp = api.patch_station(station["id"], {"operational_status": "OPERATIONAL"},
                                 SPM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)


class TestFleetMachines:
    def test_credential_deactivated_is_terminal(self, api):
        """PRD §3.4: "Deactivation is terminal and reachable from
        `PROVISIONED`, `ACTIVE`, or `SUSPENDED`, whether manual or by the
        carrier-termination and vehicle-retirement cascades."
        PRD §2.10: "...with terminal states locked and same-state no-ops
        rejected — otherwise `ERR_INVALID_STATE_TRANSITION`."

        Design: Corner/state_machines/credential_deactivated_terminal_returns_409
        """
        set_clock()
        carrier = create_active_carrier()
        veh = create_vehicle_for(carrier["id"])
        cred = create_credential_for(veh["id"], carrier["id"])
        cm = make_carrier_manager_headers(carrier["id"])
        deactivated = validate_success(api.transition_credential(
            cred["id"], "DEACTIVATED", cm))
        assert_credential(deactivated)
        assert deactivated["status"] == "DEACTIVATED"

        resp = api.transition_credential(cred["id"], "SUSPENDED", cm)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        fresh = validate_success(api.get_credential(cred["id"], FINANCE))
        assert fresh["status"] == "DEACTIVATED"

    def test_vehicle_retire_cascades_and_locks(self, api):
        """PRD §3.4: "retirement cascades: every credential of the vehicle
        not yet `DEACTIVATED` becomes `DEACTIVATED` with `status_reason`
        `VEHICLE_RETIRED`, and every subscription of the vehicle in
        `SCHEDULED`, `ACTIVE`, or `PAUSED` closes with `closed_reason`
        `VEHICLE_RETIRED`, its end date pulled back to today when still in
        the future."
        PRD §3.4: "or retire it to `RETIRED` — a terminal state reachable
        from either service state"

        Design: Corner/state_machines/vehicle_retire_cascades
        """
        fx = setup_bypass_ready()
        cm = fx["cm_headers"]
        retired = validate_success(api.patch_vehicle(
            fx["vehicle"]["id"], {"service_status": "RETIRED"}, cm))
        assert retired["service_status"] == "RETIRED"

        creds = list_credentials_for(vehicle_id=fx["vehicle"]["id"])
        assert creds[0]["status"] == "DEACTIVATED"
        assert creds[0]["status_reason"] == "VEHICLE_RETIRED"

        subs = list_subscriptions_for(vehicle_id=fx["vehicle"]["id"])
        assert subs[0]["status"] == "CLOSED"
        assert subs[0]["closed_reason"] == "VEHICLE_RETIRED"

        resp = api.patch_vehicle(fx["vehicle"]["id"],
                                 {"service_status": "IN_SERVICE"}, cm)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    def test_subscription_cancel_then_recancel_rejected(self, api):
        """PRD §3.4: "A `CarrierManager` may instead cancel at any time
        before then: the row closes with `closed_reason` `CANCELLED`, the end
        date pulls back to today if it still lies ahead"
        PRD §2.10: "The target resource must be in a from-state that permits
        the requested transition, with terminal states locked and same-state
        no-ops rejected — otherwise `ERR_INVALID_STATE_TRANSITION`."

        Design: Corner/state_machines/subscription_cancel_idempotency_returns_409
        """
        set_clock()
        carrier = create_active_carrier()
        veh = create_vehicle_for(carrier["id"])
        sub = create_subscription_for(carrier["id"], veh["id"])
        assert sub["status"] == "ACTIVE"
        cm = make_carrier_manager_headers(carrier["id"])

        cancelled = validate_success(api.cancel_subscription(sub["id"], cm))
        assert cancelled["status"] == "CLOSED"
        assert cancelled["closed_reason"] == "CANCELLED"
        assert cancelled["service_end_date"] == "2026-08-01", \
            "end date pulls back to today when it still lies ahead"

        resp = api.cancel_subscription(sub["id"], cm)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)


class TestOverrideAndInvoiceMachines:
    def test_rejected_override_rejects_further_decisions(self, api):
        """PRD §3.7: "`REJECT` simply records `decided_by` and ends the
        matter — `REJECTED` is terminal."
        PRD §2.10: "...with terminal states locked and same-state no-ops
        rejected — otherwise `ERR_INVALID_STATE_TRANSITION`."

        Design: Corner/state_machines/override_reject_then_decide_returns_409
        """
        set_clock()
        carrier = create_carrier(dot_number="100001", legal_name="Acme Hauling")
        post_snapshot(carrier["id"], iss_score=30,
                      expected_carrier_version=carrier["version"])
        override = request_override(carrier["id"], start_date="2026-09-01",
                                    end_date="2026-10-01")
        officer = make_compliance_officer_headers("officer-a")

        rejected = validate_success(api.decide_override(override["id"], "REJECT",
                                                        officer))
        assert rejected["status"] == "REJECTED"
        assert rejected["decided_by"] == "officer-a"

        resp = api.decide_override(override["id"], "APPROVE", officer)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    def test_invoice_double_payment_rejected(self, api):
        """PRD §3.8: "A successful payment moves the invoice from `ISSUED` or
        `PAST_DUE` to `PAID`, and `PAID` is terminal."
        PRD §3.8: "the invoice must still be payable, with a payment
        attempted against an already-`PAID` invoice rejected as
        `ERR_INVOICE_NOT_PAYABLE` (HTTP 409)"

        Design: Corner/state_machines/invoice_double_payment_returns_409
        """
        fx = setup_carrier_with_invoice()
        invoice = fx["invoice"]
        assert_invoice(invoice)
        assert invoice["status"] == "ISSUED"
        due = invoice["amount_due_cents"]

        paid = validate_success(api.record_payment(invoice["id"], due, FINANCE))
        assert paid["status"] == "PAID"

        resp = api.record_payment(invoice["id"], due, FINANCE)
        validate_error(resp, ApiErrorId.ERR_INVOICE_NOT_PAYABLE)


class TestEventIdempotency:
    def test_duplicate_approach_triple_rejected(self, api):
        """PRD §2.6: "The triple of `vehicle_id`, `station_id`, and
        `approach_at` identifies a bypass approach: a feed that redelivers
        the same approach is a conflict (`ERR_DUPLICATE_BYPASS_EVENT`), not a
        second event."

        Design: Corner/state_machines/event_duplicate_triple_returns_409
        """
        fx = setup_bypass_ready()
        set_clock("2026-08-05T12:00:00Z")
        payload = {"vehicle_id": fx["vehicle"]["id"],
                   "station_id": fx["station"]["id"],
                   "approach_at": "2026-08-05T10:00:00Z",
                   "measured_weight_lbs": 80000,
                   "credentials_presented": ["IFTA", "IRP", "UCR"]}
        first = validate_success(api.create_event(payload, GATEWAY),
                                 expected_status=201)
        assert first["decision"] == "BYPASS_GRANTED"

        replay = api.create_event(dict(payload), GATEWAY)
        validate_error(replay, ApiErrorId.ERR_DUPLICATE_BYPASS_EVENT)

        events = list_events_for(carrier_id=fx["carrier"]["id"])
        assert len(events) == 1, "a redelivered approach is not a second event"
        assert events[0]["id"] == first["id"]
