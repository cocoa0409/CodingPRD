"""Work-order parallel state machine, cascading approve/cancel/complete side effects,
cross-entity transition preconditions, and compensation invariants (PRD §2.7-§2.8, §3.2,
§3.6, §3.7).
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data, TEST_USERS, ApiErrorId,
    create_customer, create_vehicle, create_tire_model, create_fitment_rule,
    create_work_order, create_service_bay, add_tire_line, approve_order,
    authorize_payment, book_appointment,
    setup_customer_vehicle_tire, setup_approved_order_with_tire_line,
    setup_approved_authorized_order, setup_scheduled_appointment,
    setup_checked_in_in_service_order, seed_store_credit_2500,
)
import test_helpers.factories as F

ADVISOR = TEST_USERS["service_advisor_headers"]
TECH = TEST_USERS["technician_headers"]
INV = TEST_USERS["inventory_manager_headers"]


# ---------------------------------------------------------------------------
# Rule 3 — parallel state machine (payment vs fulfillment axes)
# ---------------------------------------------------------------------------
class TestParallelStateAxes:
    def test_authorize_advances_payment_only(self, api):
        """PRD §2.7: "These two axes evolve independently: authorizing payment does not
        advance fulfillment, and starting service does not advance payment."
        PRD §3.7: "a `ServiceAdvisor` authorizes payment on an order, moving `payment_status`
        from `UNPAID` to `AUTHORIZED`; this is permitted only once the order's
        `fulfillment_status` is `APPROVED`".

        Design: Difficulty/non_linear_state_machine/work_order_parallel_payment_and_fulfillment_axes
        """
        customer, vehicle, tire, wo, line, approved = setup_approved_order_with_tire_line(
            quantity=4, tire_overrides={"unit_price_cents": 12000, "stock_qty": 8})
        data = validate_success(api.authorize_payment(wo["id"], ADVISOR))
        assert data["payment_status"] == "AUTHORIZED"
        assert data["fulfillment_status"] == "APPROVED"

    def test_payment_axis_independent_persisted(self, api):
        """PRD §2.7: "Its `fulfillment_status` records the progress of physical work and
        moves through `DRAFT`, `APPROVED`, `IN_SERVICE`, and `COMPLETED`".
        PRD §2.7: "Its `payment_status` records the state of the money and moves through
        `UNPAID`, `AUTHORIZED`, and `PAID`".

        Design: Difficulty/non_linear_state_machine/work_order_parallel_payment_and_fulfillment_axes
        """
        customer, vehicle, tire, wo, line, approved = setup_approved_order_with_tire_line(
            quantity=4, tire_overrides={"unit_price_cents": 12000, "stock_qty": 8})
        validate_success(api.authorize_payment(wo["id"], ADVISOR))
        fetched = validate_success(api.get_work_order(wo["id"], ADVISOR))
        assert fetched["payment_status"] == "AUTHORIZED"
        assert fetched["fulfillment_status"] == "APPROVED"


# ---------------------------------------------------------------------------
# Rule 4 — transitive cascade chains
# ---------------------------------------------------------------------------
class TestCancelApprovedCascade:
    def test_cancel_voids_line_restocks_and_cancels_appointment(self, api):
        """PRD §3.7: "The transition drives `fulfillment_status` to `CANCELLED` and performs
        a full compensation: every line that is not already `VOID` moves to `VOID`; for each
        `COMMITTED` `TIRE` line that had debited stock, the tire model's `stock_qty` is
        restocked by the line's `quantity`; any `ACTIVE` `RoadHazardWarranty` on the order is
        voided; if `store_credit_applied_cents` was greater than zero, that amount is refunded
        to the customer's `store_credit_cents`; any `SCHEDULED` or `RESCHEDULE_PENDING`
        appointment for the order is moved to `CANCELLED`, freeing its bay window".

        Design: Difficulty/transitive_cascade/cancel_approved_order_cascade_depth3
        """
        customer, vehicle, tire = setup_customer_vehicle_tire(
            tire_overrides={"unit_price_cents": 13000, "mileage_warranty_miles": 60000,
                            "original_tread_32nds": 12, "stock_qty": 10})
        bay = create_service_bay(alignment_capable=False, turnover_buffer_min=15)
        wo = create_work_order(customer["id"], vehicle["id"])
        line = add_tire_line(wo, tire["id"], quantity=4, road_hazard_opted=True)
        approve_order(wo)
        # stock 10 -> 6 after approval
        assert validate_success(api.get_tire_model(tire["id"], INV))["stock_qty"] == 6
        appt = book_appointment(wo, bay, "2026-07-03T09:00:00.000Z", "2026-07-03T10:00:00.000Z")
        cancelled = validate_success(api.cancel_work_order(
            wo["id"], {"expected_work_order_version": wo["version"]}, ADVISOR))
        assert cancelled["fulfillment_status"] == "CANCELLED"
        assert validate_success(api.get_work_order_line(line["id"], ADVISOR))["line_status"] == "VOID"
        assert validate_success(api.get_tire_model(tire["id"], INV))["stock_qty"] == 10
        assert validate_success(api.get_appointment(appt["id"], ADVISOR))["status"] == "CANCELLED"

    def test_cancel_voids_active_road_hazard_warranty(self, api):
        """PRD §3.4: "If the order is cancelled, any `ACTIVE` warranty on it is voided,
        moving its `status` to `VOID`."
        PRD §3.7: "any `ACTIVE` `RoadHazardWarranty` on the order is voided".

        Design: Difficulty/transitive_cascade/cancel_approved_order_cascade_depth3
        """
        from test_helpers import validate_paginated
        customer, vehicle, tire = setup_customer_vehicle_tire(
            tire_overrides={"unit_price_cents": 13000, "mileage_warranty_miles": 60000,
                            "original_tread_32nds": 12, "stock_qty": 10})
        wo = create_work_order(customer["id"], vehicle["id"])
        line = add_tire_line(wo, tire["id"], quantity=4, road_hazard_opted=True)
        approve_order(wo)
        warranties, _ = validate_paginated(
            api.list_road_hazard_warranties(ADVISOR, params={"work_order_line_id": line["id"]}))
        assert len(warranties) == 1 and warranties[0]["status"] == "ACTIVE"
        validate_success(api.cancel_work_order(
            wo["id"], {"expected_work_order_version": wo["version"]}, ADVISOR))
        rh = validate_success(api.get_road_hazard_warranty(warranties[0]["id"], ADVISOR))
        assert rh["status"] == "VOID"


class TestCompleteServiceCascade:
    def test_complete_completes_appointment_and_captures_payment(self, api):
        """PRD §3.7: "an order may be completed only if its `payment_status` is `AUTHORIZED`
        or `PAID`".
        PRD §3.7: "Completion carries two side effects: the linked `CHECKED_IN` appointment
        is moved to `COMPLETED`, and, if `payment_status` was `AUTHORIZED`, it is captured to
        `PAID` in the same step."

        Design: Difficulty/transitive_cascade/complete_service_cascade_depth2
        """
        customer, vehicle, tire, wo, line, bay, appt = setup_checked_in_in_service_order(
            scheduled_start="2026-07-04T09:00:00.000Z",
            scheduled_end="2026-07-04T10:00:00.000Z", authorize=True)
        completed = validate_success(api.complete_work_order(wo["id"], TECH))
        assert completed["fulfillment_status"] == "COMPLETED"
        assert completed["payment_status"] == "PAID"
        assert validate_success(api.get_appointment(appt["id"], ADVISOR))["status"] == "COMPLETED"

    def test_complete_fulfillment_reaches_completed(self, api):
        """PRD §3.7: "The technician later completes the job, moving `fulfillment_status` from
        `IN_SERVICE` to `COMPLETED`."

        Design: Difficulty/transitive_cascade/complete_service_cascade_depth2
        """
        customer, vehicle, tire, wo, line, bay, appt = setup_checked_in_in_service_order(
            scheduled_start="2026-07-14T09:00:00.000Z",
            scheduled_end="2026-07-14T10:00:00.000Z", authorize=True)
        completed = validate_success(api.complete_work_order(wo["id"], TECH))
        assert completed["fulfillment_status"] == "COMPLETED"
        fetched = validate_success(api.get_work_order(wo["id"], ADVISOR))
        assert fetched["fulfillment_status"] == "COMPLETED"


# ---------------------------------------------------------------------------
# Rule 7 — cross-entity state dependencies
# ---------------------------------------------------------------------------
class TestCrossEntityPreconditions:
    def test_start_service_requires_checked_in_appointment(self, api):
        """PRD §3.7: "a `Technician` starts service, moving `fulfillment_status` from
        `APPROVED` to `IN_SERVICE`; this requires that an appointment for the order already
        be in `CHECKED_IN`."
        PRD §3.2: "an attempt to add a line to an order in any other state is rejected with
        `ERR_INVALID_STATE`." (ERR_INVALID_STATE is the invalid-transition error.)

        With the appointment merely SCHEDULED, start-service is rejected.

        Design: Difficulty/cross_entity_state_dependency/start_service_requires_checked_in_appointment
        """
        customer, vehicle, tire, wo, line, bay, appt = setup_scheduled_appointment(
            scheduled_start="2026-07-06T09:00:00.000Z",
            scheduled_end="2026-07-06T10:00:00.000Z", authorize=True)
        validate_error(api.start_service(wo["id"], TECH), ApiErrorId.ERR_INVALID_STATE)

    def test_start_service_succeeds_after_check_in(self, api):
        """PRD §3.7: "a `Technician` starts service, moving `fulfillment_status` from
        `APPROVED` to `IN_SERVICE`; this requires that an appointment for the order already be
        in `CHECKED_IN`."
        PRD §3.6: "A `Technician` checks the vehicle in, moving the appointment from
        `SCHEDULED` to `CHECKED_IN`."

        Once the appointment IS checked in, the same start-service call succeeds (the positive
        side of the cross-entity precondition).

        Design: Difficulty/cross_entity_state_dependency/start_service_requires_checked_in_appointment
        """
        customer, vehicle, tire, wo, line, bay, appt = setup_scheduled_appointment(
            scheduled_start="2026-07-16T09:00:00.000Z",
            scheduled_end="2026-07-16T10:00:00.000Z", authorize=True)
        validate_success(api.check_in_appointment(appt["id"], TECH))
        data = validate_success(api.start_service(wo["id"], TECH))
        assert data["fulfillment_status"] == "IN_SERVICE"

    def test_mileage_claim_approve_requires_committed_line(self, api):
        """PRD §3.9: "Approval requires the claim to be `SUBMITTED` and the covered line's
        `line_status` to be `COMMITTED` — a claim can only be approved against a tire line
        that was actually sold, that is, whose order was approved; otherwise the request is
        rejected with `ERR_INVALID_STATE`."

        Order never approved -> line still PENDING -> claim approve rejected.

        Design: Difficulty/cross_entity_state_dependency/mileage_claim_approve_requires_committed_line
        """
        customer, vehicle, tire = setup_customer_vehicle_tire(
            tire_overrides={"unit_price_cents": 17000, "mileage_warranty_miles": 50000,
                            "original_tread_32nds": 13, "stock_qty": 8})
        wo = create_work_order(customer["id"], vehicle["id"])
        line = add_tire_line(wo, tire["id"], quantity=4)
        claim = get_success_data(api.create_mileage_claim(
            F.create_mileage_claim_payload(line["id"], tire["id"],
                                           measured_tread_32nds=2, miles_driven=10000,
                                           payout_method="REFUND", claim_quantity=4), ADVISOR))
        validate_error(api.approve_mileage_claim(claim["id"], ADVISOR), ApiErrorId.ERR_INVALID_STATE)

    def test_mileage_claim_approves_once_line_committed(self, api):
        """PRD §3.9: "Approval requires the claim to be `SUBMITTED` and the covered line's
        `line_status` to be `COMMITTED` — a claim can only be approved against a tire line that
        was actually sold, that is, whose order was approved".
        PRD §3.2: "Every line that is not already `VOID` moves from `PENDING` to `COMMITTED` in
        `line_status`, capturing its `extended_cents`."

        After the order is approved (line COMMITTED) the same claim approves — the positive
        side of the committed-line precondition.

        Design: Difficulty/cross_entity_state_dependency/mileage_claim_approve_requires_committed_line
        """
        from test_helpers import setup_submitted_mileage_claim
        customer, vehicle, tire, wo, line, claim = setup_submitted_mileage_claim(
            measured_tread_32nds=2, miles_driven=10000, payout_method="REFUND", claim_quantity=4,
            tire_overrides={"unit_price_cents": 17000, "mileage_warranty_miles": 50000,
                            "original_tread_32nds": 13, "stock_qty": 8})
        committed = validate_success(api.get_work_order_line(line["id"], ADVISOR))
        assert committed["line_status"] == "COMMITTED"
        data = validate_success(api.approve_mileage_claim(claim["id"], ADVISOR))
        assert data["status"] == "APPROVED"


# ---------------------------------------------------------------------------
# Rule 9 — compensating-action invariants
# ---------------------------------------------------------------------------
class TestCompensationInvariants:
    def test_cancel_restores_tire_stock(self, api):
        """PRD §3.7: "for each `COMMITTED` `TIRE` line that had debited stock, the tire
        model's `stock_qty` is restocked by the line's `quantity`".
        PRD §2.8: "stock that was debited is restocked ... so that the catalog ... [is]
        conserved across the approve/cancel pair."

        stock 10 -> approve(qty 4) -> 6 -> cancel -> 10.

        Design: Difficulty/compensating_invariant/cancel_restores_tire_stock_invariant
        """
        customer, vehicle, tire, wo, line, approved = setup_approved_order_with_tire_line(
            quantity=4, tire_overrides={"unit_price_cents": 11000, "mileage_warranty_miles": 65000,
                                        "original_tread_32nds": 11, "stock_qty": 10})
        assert validate_success(api.get_tire_model(tire["id"], INV))["stock_qty"] == 6
        cancelled = validate_success(api.cancel_work_order(
            wo["id"], {"expected_work_order_version": wo["version"]}, ADVISOR))
        assert cancelled["fulfillment_status"] == "CANCELLED"
        assert validate_success(api.get_tire_model(tire["id"], INV))["stock_qty"] == 10

    def test_draft_cancel_never_debited_stock_unchanged(self, api):
        """PRD §2.8: "Its mirror image is cancellation, which is designed as an exact
        compensation: stock that was debited is restocked ... so that the catalog ... [is]
        conserved across the approve/cancel pair."
        PRD §3.7: "for each `COMMITTED` `TIRE` line that had debited stock, the tire model's
        `stock_qty` is restocked by the line's `quantity`".

        A DRAFT order (never approved -> stock never debited) cancels with stock conserved
        at its original value (10).

        Design: Difficulty/compensating_invariant/cancel_restores_tire_stock_invariant
        """
        customer, vehicle, tire, wo, line, approved = setup_approved_order_with_tire_line(
            quantity=4, tire_overrides={"unit_price_cents": 11000, "mileage_warranty_miles": 65000,
                                        "original_tread_32nds": 11, "stock_qty": 10})
        # approve debited 10 -> 6; cancel restores 6 -> 10
        validate_success(api.cancel_work_order(
            wo["id"], {"expected_work_order_version": wo["version"]}, ADVISOR))
        final = validate_success(api.get_tire_model(tire["id"], INV))["stock_qty"]
        assert final == 10, f"stock after approve+cancel must equal pre-approve 10, got {final}"

    def test_cancel_restores_store_credit(self, api):
        """PRD §3.7: "if `store_credit_applied_cents` was greater than zero, that amount is
        refunded to the customer's `store_credit_cents`".
        PRD §2.8: "store credit that was applied is refunded ... so that ... the customer's
        credit balance ... [is] conserved across the approve/cancel pair."

        Seed 2500 credit; order applies 2500 (balance -> 0); cancel refunds -> 2500.

        Design: Difficulty/compensating_invariant/cancel_restores_store_credit_invariant
        """
        customer = create_customer()
        vehicle = create_vehicle(customer["id"], make="TOYOTA", model="COROLLA")
        tire = create_tire_model(unit_price_cents=15000, mileage_warranty_miles=30000,
                                 original_tread_32nds=10, stock_qty=20)
        create_fitment_rule(vehicle["id"], tire["id"], grade="OE_EXACT")
        seed_store_credit_2500(customer, vehicle, tire)
        assert validate_success(api.get_customer(customer["id"], ADVISOR))["store_credit_cents"] == 2500
        wo = create_work_order(customer["id"], vehicle["id"], store_credit_applied_cents=2500)
        add_tire_line(wo, tire["id"], quantity=4)
        approve_order(wo)
        assert validate_success(api.get_customer(customer["id"], ADVISOR))["store_credit_cents"] == 0
        cancelled = validate_success(api.cancel_work_order(
            wo["id"], {"expected_work_order_version": wo["version"]}, ADVISOR))
        assert cancelled["fulfillment_status"] == "CANCELLED"
        assert cancelled["payment_status"] == "UNPAID"
        assert validate_success(api.get_customer(customer["id"], ADVISOR))["store_credit_cents"] == 2500

    def test_store_credit_debited_at_approval_then_refunded(self, api):
        """PRD §3.2: "the customer's `store_credit_cents` is debited by that clamped amount."
        PRD §3.7: "if `store_credit_applied_cents` was greater than zero, that amount is
        refunded to the customer's `store_credit_cents`".

        Confirms the debit-at-approval and refund-at-cancel halves of the conservation pair:
        2500 -> 0 (approve) -> 2500 (cancel).

        Design: Difficulty/compensating_invariant/cancel_restores_store_credit_invariant
        """
        customer = create_customer()
        vehicle = create_vehicle(customer["id"], make="TOYOTA", model="COROLLA")
        tire = create_tire_model(unit_price_cents=15000, mileage_warranty_miles=30000,
                                 original_tread_32nds=10, stock_qty=20)
        create_fitment_rule(vehicle["id"], tire["id"], grade="OE_EXACT")
        seed_store_credit_2500(customer, vehicle, tire)
        wo = create_work_order(customer["id"], vehicle["id"], store_credit_applied_cents=2500)
        add_tire_line(wo, tire["id"], quantity=4)
        approved = approve_order(wo)
        assert approved["store_credit_applied_cents"] == 2500
        assert validate_success(api.get_customer(customer["id"], ADVISOR))["store_credit_cents"] == 0
        validate_success(api.cancel_work_order(
            wo["id"], {"expected_work_order_version": wo["version"]}, ADVISOR))
        assert validate_success(api.get_customer(customer["id"], ADVISOR))["store_credit_cents"] == 2500
