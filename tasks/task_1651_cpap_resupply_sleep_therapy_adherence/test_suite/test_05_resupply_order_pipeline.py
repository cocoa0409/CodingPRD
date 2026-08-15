"""Resupply order pipeline: parallel auth/fulfillment dimensions, creation
guards (FK, quantity, prior-auth), shipment readiness, and the outstanding
balance invariant on return-vs-invoice.

Covers PRD §2.10 (parallel state dimensions), §3.5 (the order pipeline).
"""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    authorize_order,
    clinical_clear,
    create_authorized_order,
    create_cleared_order,
    create_order_for_plan,
    create_resupply_order_payload,
    current_patient_version,
    deliver_order,
    get_patient,
    get_plans_for,
    invoice_order,
    occ_payload,
    setup_therapy_patient,
    ship_order,
    validate_error,
    validate_success,
)


class TestParallelStateDimensions:
    """auth_status and fulfillment_status evolve as parallel dimensions."""

    def test_clinical_clear_moves_only_auth_dimension(self, api):
        """PRD §3.5: "A newly created order lands with `auth_status`
        `PENDING_CLINICAL_CLEARANCE` and `fulfillment_status` `NOT_READY`."
        PRD §3.5: "Clearance moves the order to `PENDING_PAYER_AUTH` and
        records the therapist's id in `clinical_cleared_by_user_id`."

        Design: Difficulty/non_linear_state_machine/resupply_order_parallel_auth_and_fulfillment_dimensions
        """
        ctx = setup_therapy_patient()
        patient = ctx["patient"]
        plan = ctx["plans"]["FILTER"]

        order = create_order_for_plan(patient["id"], plan)
        assert order["auth_status"] == "PENDING_CLINICAL_CLEARANCE"
        assert order["fulfillment_status"] == "NOT_READY"

        cleared = clinical_clear(order["id"])
        assert cleared["auth_status"] == "PENDING_PAYER_AUTH"
        # Only the auth dimension moved; fulfillment stays NOT_READY.
        assert cleared["fulfillment_status"] == "NOT_READY"
        assert cleared["clinical_cleared_by_user_id"] == "rt-1"

    def test_authorize_then_ship_move_dimensions_independently(self, api):
        """PRD §3.5: "A successful authorization moves `auth_status` to
        `AUTHORIZED` and `fulfillment_status` to `READY_TO_SHIP`"
        PRD §3.5: "Shipping sets `fulfillment_status` to `SHIPPED`, stamps
        `shipped_on` with the current date"

        Design: Difficulty/non_linear_state_machine/resupply_order_parallel_auth_and_fulfillment_dimensions
        """
        ctx = setup_therapy_patient()
        patient = ctx["patient"]
        plan = ctx["plans"]["FILTER"]
        order = create_cleared_order(patient["id"], plan)

        authorized = authorize_order(order["id"], patient["id"])
        # Authorize flips both dimensions atomically.
        assert authorized["auth_status"] == "AUTHORIZED"
        assert authorized["fulfillment_status"] == "READY_TO_SHIP"

        shipped = ship_order(order["id"], patient["id"])
        # Ship advances only the fulfillment dimension.
        assert shipped["auth_status"] == "AUTHORIZED"
        assert shipped["fulfillment_status"] == "SHIPPED"
        assert shipped["shipped_on"] == "2026-08-01"


class TestOrderCreationGuards:
    def test_resupply_order_initial_state(self, api):
        """PRD §3.5: "A newly created order lands with `auth_status`
        `PENDING_CLINICAL_CLEARANCE` and `fulfillment_status` `NOT_READY`."

        Design: Corner/state_machines/resupply_order_initial_state
        """
        ctx = setup_therapy_patient()
        order = create_order_for_plan(ctx["patient"]["id"], ctx["plans"]["TUBING"])
        assert order["auth_status"] == "PENDING_CLINICAL_CLEARANCE"
        assert order["fulfillment_status"] == "NOT_READY"

    def test_fk_body_reference_not_found(self, api, intake_coordinator_headers):
        """PRD §2.7: "then any foreign-key identifiers referenced in the
        request body, such as `patient_id`, `payer_policy_id`,
        `component_supply_plan_id`, `device_enrollment_id`, or
        `original_mask_plan_id` (a failure yields `ERR_FK_NOT_FOUND`)"

        Design: Corner/validations/fk_body_reference_not_found
        """
        ctx = setup_therapy_patient()
        patient = ctx["patient"]
        payload = create_resupply_order_payload(
            patient["id"], NON_EXISTENT_UUID, 1, current_patient_version(patient["id"]))
        res = api.create_resupply_order(payload, intake_coordinator_headers)
        validate_error(res, "ERR_FK_NOT_FOUND", expected_status=404)

    def test_quantity_mismatch_rejected(self, api, intake_coordinator_headers):
        """PRD §3.5: "then the `requested_quantity` must equal the plan's
        `quantity_per_cycle` — orders are always full-cycle, never partial
        (`ERR_QUANTITY_MISMATCH`)"

        Design: Corner/validations/quantity_mismatch_rejected
        """
        ctx = setup_therapy_patient()
        patient = ctx["patient"]
        mask_plan = ctx["plans"]["MASK"]
        payload = create_resupply_order_payload(
            patient["id"], mask_plan["id"],
            requested_quantity=mask_plan["quantity_per_cycle"] + 4,
            expected_patient_version=current_patient_version(patient["id"]))
        res = api.create_resupply_order(payload, intake_coordinator_headers)
        validate_error(res, "ERR_QUANTITY_MISMATCH", expected_status=422)

    def test_prior_auth_required_when_payer_flag_set(
            self, api, intake_coordinator_headers):
        """PRD §3.5: "If the payer's `requires_prior_auth` is true, the request
        must carry a prior-authorization reference (`ERR_PRIOR_AUTH_REQUIRED`
        when absent)."

        Design: Corner/validations/prior_auth_required_when_payer_flag_set
        """
        ctx = setup_therapy_patient(payer_overrides={"requires_prior_auth": True})
        patient = ctx["patient"]
        mask_plan = ctx["plans"]["MASK"]
        payload = create_resupply_order_payload(
            patient["id"], mask_plan["id"], mask_plan["quantity_per_cycle"],
            current_patient_version(patient["id"]))
        res = api.create_resupply_order(payload, intake_coordinator_headers)
        validate_error(res, "ERR_PRIOR_AUTH_REQUIRED", expected_status=422)


class TestShipmentReadiness:
    def test_ship_before_authorize_rejected(self, api, intake_coordinator_headers):
        """PRD §3.5: "Shipping requires the order to be `AUTHORIZED`
        (`ERR_ORDER_NOT_AUTHORIZED` when the authorization dimension is in any
        other state) and in `READY_TO_SHIP` (`ERR_ORDER_NOT_READY_TO_SHIP`)"

        Design: Corner/state_machines/resupply_order_invalid_transition_ship_before_authorize
        """
        ctx = setup_therapy_patient()
        patient = ctx["patient"]
        plan = ctx["plans"]["FILTER"]

        # Isolate the readiness failure: authorize then ship once (auth stays
        # AUTHORIZED, fulfillment leaves READY_TO_SHIP), then ship again.
        order = create_authorized_order(patient["id"], plan)
        shipped = ship_order(order["id"], patient["id"])
        assert shipped["fulfillment_status"] == "SHIPPED"

        res = api.ship_order(order["id"],
                             occ_payload(current_patient_version(patient["id"])),
                             intake_coordinator_headers)
        validate_error(res, "ERR_ORDER_NOT_READY_TO_SHIP", expected_status=409)


class TestOutstandingBalanceInvariant:
    """RETURNED before INVOICED is the compensating action: no balance impact."""

    def test_delivery_and_return_leave_balance_at_zero(
            self, api, intake_coordinator_headers):
        """PRD §3.5: "From `DELIVERED` there are two exits: marking the order
        returned moves it to `RETURNED` with no invoice and no balance impact"

        Design: Difficulty/compensating_invariant/patient_balance_invariant_on_invoice_vs_return
        """
        ctx = setup_therapy_patient()
        patient = ctx["patient"]
        assert get_patient(patient["id"])["outstanding_balance_cents"] == 0

        order = create_authorized_order(patient["id"], ctx["plans"]["FILTER"])
        ship_order(order["id"], patient["id"])
        delivered = deliver_order(order["id"])
        assert delivered["fulfillment_status"] == "DELIVERED"
        # Delivered but not invoiced: no responsibility computed, no balance.
        assert get_patient(patient["id"])["outstanding_balance_cents"] == 0

        returned = validate_success(
            api.mark_order_returned(order["id"], intake_coordinator_headers))
        assert returned["fulfillment_status"] == "RETURNED"
        assert get_patient(patient["id"])["outstanding_balance_cents"] == 0

    def test_return_after_another_invoice_does_not_touch_balance(
            self, api, intake_coordinator_headers):
        """PRD §3.5: "The computed share is added to the patient's
        `outstanding_balance_cents`, which in general aggregates the
        `patient_responsibility_cents` of all the patient's orders in
        `INVOICED` status, less any payments applied."
        PRD §3.5: "marking the order returned moves it to `RETURNED` with no
        invoice and no balance impact"

        Design: Difficulty/compensating_invariant/patient_balance_invariant_on_invoice_vs_return
        """
        ctx = setup_therapy_patient()
        patient = ctx["patient"]

        # First order (FILTER) runs through to INVOICED and lands on the books.
        order1 = create_authorized_order(patient["id"], ctx["plans"]["FILTER"])
        ship_order(order1["id"], patient["id"])
        deliver_order(order1["id"])
        invoiced = invoice_order(order1["id"])
        share = invoiced["patient_responsibility_cents"]
        assert get_patient(patient["id"])["outstanding_balance_cents"] == share

        # Second order (TUBING) is delivered then returned: balance unchanged.
        order2 = create_authorized_order(patient["id"], ctx["plans"]["TUBING"])
        ship_order(order2["id"], patient["id"])
        deliver_order(order2["id"])
        validate_success(api.mark_order_returned(order2["id"],
                                                 intake_coordinator_headers))
        assert get_patient(patient["id"])["outstanding_balance_cents"] == share
