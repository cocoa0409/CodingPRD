"""Credential activation gates, subscription window rules, and the fiscal
gates — including the validation-ladder precedence between them."""
from test_helpers import (
    FINANCE,
    ApiErrorId,
    create_active_carrier,
    create_carrier,
    create_credential_for,
    create_subscription_for,
    create_vehicle_for,
    get_carrier,
    list_subscriptions_for,
    make_carrier_manager_headers,
    post_snapshot,
    set_clock,
    setup_bypass_ready,
    setup_carrier_past_due,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestChildWriteGate:
    def test_vehicle_create_requires_active_carrier(self, api):
        """PRD §3.1: "Registering vehicles, provisioning credentials,
        creating subscriptions, and opening disputes all require the carrier
        to be `ACTIVE`; against any other status the write fails with
        `ERR_CARRIER_NOT_ACTIVE` (HTTP 409)."

        Design: Corner/validations/vehicle_create_carrier_not_active_returns_409
        """
        set_clock()
        carrier = create_carrier(dot_number="100001", legal_name="Acme Hauling")
        assert carrier["status"] == "ENROLLED"
        cm = make_carrier_manager_headers(carrier["id"])
        resp = api.create_vehicle(
            {"carrier_id": carrier["id"], "vin": "VIN-0001",
             "plate_number": "P-1", "plate_state": "CA", "home_state_code": "CA",
             "gvwr_lbs": 80000},
            cm)
        validate_error(resp, ApiErrorId.ERR_CARRIER_NOT_ACTIVE)


class TestActivationGates:
    def test_activation_without_covering_subscription(self, api):
        """PRD §3.4: "then a covering subscription must exist — one whose
        status is `ACTIVE` or `PAUSED` and whose window covers today,
        otherwise `ERR_NO_ACTIVE_SUBSCRIPTION` (HTTP 402)"

        Design: Corner/validations/credential_activation_without_subscription_returns_402
        """
        set_clock()
        carrier = create_active_carrier(dot_number="200002",
                                        legal_name="No Subscription Co")
        vehicle = create_vehicle_for(carrier["id"], vin="VIN-9001")
        cred = create_credential_for(vehicle["id"], carrier["id"],
                                     device_serial="SN-9001")
        # Deliberately no subscription for the vehicle.
        cm = make_carrier_manager_headers(carrier["id"])
        resp = api.transition_credential(cred["id"], "ACTIVE", cm)
        validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_SUBSCRIPTION)
        fresh = validate_success(api.get_credential(cred["id"], FINANCE))
        assert fresh["status"] == "PROVISIONED"

    def test_activation_blocked_by_vehicle_out_of_service(self, api):
        """PRD §3.4: "then the vehicle must be `IN_SERVICE`
        (`ERR_VEHICLE_NOT_IN_SERVICE`)"

        Design: Difficulty/cross_entity_state_dependency/credential_activation_depends_on_vehicle_service
        """
        fx = setup_bypass_ready(activate=False)
        cm = fx["cm_headers"]
        validate_success(api.patch_vehicle(fx["vehicle"]["id"],
                                           {"service_status": "OUT_OF_SERVICE"},
                                           cm))
        resp = api.transition_credential(fx["credential"]["id"], "ACTIVE", cm)
        validate_error(resp, ApiErrorId.ERR_VEHICLE_NOT_IN_SERVICE)
        fresh = validate_success(api.get_credential(fx["credential"]["id"], FINANCE))
        assert fresh["status"] == "PROVISIONED"

    def test_activation_succeeds_once_vehicle_back_in_service(self, api):
        """PRD §3.4: "its manager may set it `OUT_OF_SERVICE` and back again
        at will"
        PRD §3.4: "then the vehicle must be `IN_SERVICE`
        (`ERR_VEHICLE_NOT_IN_SERVICE`)" — the gate set guards the transition,
        so once the vehicle returns to service the identical request
        succeeds.

        Design: Difficulty/cross_entity_state_dependency/credential_activation_depends_on_vehicle_service
        """
        fx = setup_bypass_ready(activate=False)
        cm = fx["cm_headers"]
        validate_success(api.patch_vehicle(fx["vehicle"]["id"],
                                           {"service_status": "OUT_OF_SERVICE"},
                                           cm))
        blocked = api.transition_credential(fx["credential"]["id"], "ACTIVE", cm)
        validate_error(blocked, ApiErrorId.ERR_VEHICLE_NOT_IN_SERVICE)

        validate_success(api.patch_vehicle(fx["vehicle"]["id"],
                                           {"service_status": "IN_SERVICE"}, cm))
        activated = validate_success(api.transition_credential(
            fx["credential"]["id"], "ACTIVE", cm))
        assert activated["status"] == "ACTIVE"


class TestValidationLadderPrecedence:
    def test_safety_gate_outranks_fiscal_gate_on_activation(self, api):
        """PRD §2.10: the business safety gates include "the credential
        posture gate (`ERR_CARRIER_NOT_BYPASS_ELIGIBLE`)" and come before rung
        "15. **Fiscal gates, in their pinned relative order.** The
        covering-subscription gate (`ERR_NO_ACTIVE_SUBSCRIPTION`) ...";
        "Rung numbering here is semantic, not decorative: when a request
        violates two rules, the error the client receives is always the one
        from the earlier rung."

        Design: Difficulty/priority_pair_validation_conflict/credential_activation_safety_vs_fiscal_rejected
        """
        set_clock()
        carrier = create_active_carrier(dot_number="100001")
        vehicle = create_vehicle_for(carrier["id"], vin="VIN-0001")
        cred = create_credential_for(vehicle["id"], carrier["id"],
                                     device_serial="SN-0001")
        # No subscription exists for the vehicle at all.
        post_snapshot(carrier["id"], iss_score=90, source="MANUAL_AUDIT")
        assert get_carrier(carrier["id"])["eligibility_status"] == "INELIGIBLE"

        cm = make_carrier_manager_headers(carrier["id"])
        resp = api.transition_credential(cred["id"], "ACTIVE", cm)
        validate_error(resp, ApiErrorId.ERR_CARRIER_NOT_BYPASS_ELIGIBLE)

    def test_safety_gate_rejection_leaves_no_side_effects(self, api):
        """PRD §3.2: "An `ACTIVE` carrier whose posture collapses keeps its
        `ACTIVE` status"
        PRD §2.10: "a request that fails an earlier rung is rejected with
        that rung's error without ever reaching later rungs."

        Design: Difficulty/priority_pair_validation_conflict/credential_activation_safety_vs_fiscal_rejected
        """
        set_clock()
        carrier = create_active_carrier(dot_number="100001")
        vehicle = create_vehicle_for(carrier["id"], vin="VIN-0001")
        cred = create_credential_for(vehicle["id"], carrier["id"],
                                     device_serial="SN-0001")
        post_snapshot(carrier["id"], iss_score=90, source="MANUAL_AUDIT")

        cm = make_carrier_manager_headers(carrier["id"])
        validate_error(api.transition_credential(cred["id"], "ACTIVE", cm),
                       ApiErrorId.ERR_CARRIER_NOT_BYPASS_ELIGIBLE)
        assert get_carrier(carrier["id"])["status"] == "ACTIVE", \
            "posture INELIGIBLE does not suspend the lifecycle"
        fresh = validate_success(api.get_credential(cred["id"], FINANCE))
        assert fresh["status"] == "PROVISIONED"

    def test_state_violation_outranks_vehicle_gate(self, api):
        """PRD §2.10: rung "5. **State-machine legality.** The target
        resource must be in a from-state that permits the requested
        transition, with terminal states locked and same-state no-ops
        rejected — otherwise `ERR_INVALID_STATE_TRANSITION`." precedes the
        business safety gates including "the vehicle in-service gate
        (`ERR_VEHICLE_NOT_IN_SERVICE`)"; "Rung numbering here is semantic,
        not decorative: when a request violates two rules, the error the
        client receives is always the one from the earlier rung."

        Design: Difficulty/priority_pair_validation_conflict/credential_transition_state_vs_safety_rejected
        """
        fx = setup_bypass_ready()  # credential already ACTIVE
        cm = fx["cm_headers"]
        validate_success(api.patch_vehicle(fx["vehicle"]["id"],
                                           {"service_status": "OUT_OF_SERVICE"},
                                           cm))
        # Double activation is a same-state no-op AND the vehicle is out of
        # service: the state-machine rung must answer.
        resp = api.transition_credential(fx["credential"]["id"], "ACTIVE", cm)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    def test_state_violation_rejection_leaves_no_side_effects(self, api):
        """PRD §2.10: "a request that fails an earlier rung is rejected with
        that rung's error without ever reaching later rungs."

        Design: Difficulty/priority_pair_validation_conflict/credential_transition_state_vs_safety_rejected
        """
        fx = setup_bypass_ready()
        cm = fx["cm_headers"]
        validate_success(api.patch_vehicle(fx["vehicle"]["id"],
                                           {"service_status": "OUT_OF_SERVICE"},
                                           cm))
        validate_error(api.transition_credential(fx["credential"]["id"], "ACTIVE",
                                                 cm),
                       ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        cred = validate_success(api.get_credential(fx["credential"]["id"], FINANCE))
        assert cred["status"] == "ACTIVE", "the rejected transition changed nothing"
        vehicle = validate_success(api.get_vehicle(fx["vehicle"]["id"], FINANCE))
        assert vehicle["service_status"] == "OUT_OF_SERVICE"

    def test_window_overlap_outranks_past_due_on_subscription_create(self, api):
        """PRD §2.10: rung "10. **Window overlaps.** Override windows first
        (`ERR_OVERRIDE_WINDOW_OVERLAP`), then subscription windows
        (`ERR_SUBSCRIPTION_WINDOW_OVERLAP`)." precedes rung "15. **Fiscal
        gates, in their pinned relative order.** ... the past-due standing
        gate (`ERR_CARRIER_PAST_DUE`)"; "Rung numbering here is semantic, not
        decorative: when a request violates two rules, the error the client
        receives is always the one from the earlier rung."

        Design: Difficulty/priority_pair_validation_conflict/subscription_create_temporal_vs_fiscal_rejected
        """
        fx = setup_carrier_past_due()  # invoice PAST_DUE at clock 2026-09-16
        cm = fx["cm_headers"]
        resp = api.create_subscription(
            {"carrier_id": fx["carrier"]["id"],
             "vehicle_id": fx["vehicle"]["id"],
             "service_start_date": "2026-10-01",
             "service_end_date": "2026-12-31"},
            cm)
        # The window overlaps the existing [2026-08-01, 2026-12-31]
        # subscription AND the carrier is past due: overlap answers first.
        validate_error(resp, ApiErrorId.ERR_SUBSCRIPTION_WINDOW_OVERLAP)

    def test_overlap_rejection_creates_no_row(self, api):
        """PRD §2.10: "a request that fails an earlier rung is rejected with
        that rung's error without ever reaching later rungs."

        Design: Difficulty/priority_pair_validation_conflict/subscription_create_temporal_vs_fiscal_rejected
        """
        fx = setup_carrier_past_due()
        cm = fx["cm_headers"]
        validate_error(api.create_subscription(
            {"carrier_id": fx["carrier"]["id"],
             "vehicle_id": fx["vehicle"]["id"],
             "service_start_date": "2026-10-01",
             "service_end_date": "2026-12-31"},
            cm), ApiErrorId.ERR_SUBSCRIPTION_WINDOW_OVERLAP)
        subs, meta = validate_paginated(api.list_subscriptions(
            FINANCE, params={"vehicle_id": fx["vehicle"]["id"]}))
        assert len(subs) == 1 and meta["total_count"] == 1, \
            "no new subscription row was created"


class TestFiscalGateAlone:
    def test_new_subscription_blocked_when_carrier_past_due(self, api):
        """PRD §3.4: "the carrier must be `ACTIVE` and free of past-due
        standing (`ERR_CARRIER_PAST_DUE`)."
        PRD §3.4: "Past-due standing blocks both new subscriptions and
        credential activation or reactivation, as the gates above describe."

        Design: Corner/validations/subscription_create_past_due_returns_402
        """
        fx = setup_carrier_past_due()
        vehicle2 = create_vehicle_for(fx["carrier"]["id"], vin="VIN-0002",
                                      plate_number="P-2")
        cm = fx["cm_headers"]
        # A clean, non-overlapping window on a different vehicle: only the
        # fiscal gate can fire.
        resp = api.create_subscription(
            {"carrier_id": fx["carrier"]["id"], "vehicle_id": vehicle2["id"],
             "service_start_date": "2026-09-16",
             "service_end_date": "2026-12-31"},
            cm)
        validate_error(resp, ApiErrorId.ERR_CARRIER_PAST_DUE)


class TestSubscriptionWindowAdjacency:
    def _carrier_with_first_window(self, api):
        set_clock()
        carrier = create_active_carrier()
        vehicle = create_vehicle_for(carrier["id"], vin="VIN-0001")
        sub1 = create_subscription_for(carrier["id"], vehicle["id"],
                                       service_start_date="2026-08-01",
                                       service_end_date="2026-09-30")
        return carrier, vehicle, sub1

    def test_adjacent_start_equals_existing_end_conflicts(self, api):
        """PRD §3.4: "Windows are closed intervals, inclusive at both ends,
        and a vehicle's non-`CLOSED` subscriptions may not overlap: a new
        window touching an existing one is rejected with
        `ERR_SUBSCRIPTION_WINDOW_OVERLAP`, and — unlike the override windows
        of §3.7 — adjacency counts as conflict here, so a start date equal to
        an existing subscription's end date is itself an overlap."

        Design: Difficulty/resource_temporal_overlap/subscription_windows_closed_interval_adjacency
        """
        carrier, vehicle, sub1 = self._carrier_with_first_window(api)
        assert sub1["status"] == "ACTIVE"
        cm = make_carrier_manager_headers(carrier["id"])
        resp = api.create_subscription(
            {"carrier_id": carrier["id"], "vehicle_id": vehicle["id"],
             "service_start_date": "2026-09-30",
             "service_end_date": "2026-12-31"},
            cm)
        validate_error(resp, ApiErrorId.ERR_SUBSCRIPTION_WINDOW_OVERLAP)
        subs = list_subscriptions_for(vehicle_id=vehicle["id"])
        assert len(subs) == 1

    def test_day_after_end_is_earliest_legal_renewal(self, api):
        """PRD §3.4: "Windows are closed intervals, inclusive at both ends"
        — so the day after the existing end date does not touch it.
        PRD §3.4: "The subscription opens as `SCHEDULED` when its start date
        lies in the future and as `ACTIVE` when the start date has already
        arrived; `payment_standing` begins at `CURRENT`."

        Design: Difficulty/resource_temporal_overlap/subscription_windows_closed_interval_adjacency
        """
        carrier, vehicle, sub1 = self._carrier_with_first_window(api)
        cm = make_carrier_manager_headers(carrier["id"])
        created = validate_success(api.create_subscription(
            {"carrier_id": carrier["id"], "vehicle_id": vehicle["id"],
             "service_start_date": "2026-10-01",
             "service_end_date": "2026-12-31"},
            cm), expected_status=201)
        assert created["status"] == "SCHEDULED", \
            "start 2026-10-01 lies in the future at logical today 2026-08-01"
        assert created["payment_standing"] == "CURRENT"
        subs = list_subscriptions_for(vehicle_id=vehicle["id"])
        assert len(subs) == 2
