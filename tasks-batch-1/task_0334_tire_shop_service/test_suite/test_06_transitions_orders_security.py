"""Invalid/terminal transitions, special-order branches, line-type and ownership
validations, OCC version guards, RBAC denials, and reverse-reachable warranty reads
(PRD §3.2, §3.7, §3.8, §3.9, §2.1, §2.9).
"""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    TEST_USERS, ApiErrorId, make_customer_headers,
    create_customer, create_vehicle, create_tire_model, create_fitment_rule,
    create_work_order, create_service_bay, add_tire_line, add_service_line, approve_order,
    book_appointment,
    setup_customer_vehicle_tire, setup_approved_order_with_tire_line,
    setup_special_order, setup_checked_in_in_service_order,
)
import test_helpers.factories as F

ADVISOR = TEST_USERS["service_advisor_headers"]
TECH = TEST_USERS["technician_headers"]
INV = TEST_USERS["inventory_manager_headers"]


# ---------------------------------------------------------------------------
# Corner — state machines (invalid / terminal transitions)
# ---------------------------------------------------------------------------
class TestInvalidTransitions:
    def test_double_approve_rejected_no_double_debit(self, api):
        """PRD §3.2: "Approval requires the order to be in `DRAFT`".
        PRD §3.2: "an attempt to add a line to an order in any other state is rejected with
        `ERR_INVALID_STATE`." (ERR_INVALID_STATE is the not-in-required-state error.)
        PRD §3.2: "For each committed `TIRE` line backed by sufficient stock, the tire model's
        `stock_qty` is debited by the line's `quantity`."

        Re-approving an APPROVED order is rejected; stock stays at the single-debit value (6).

        Design: Corner/state_machines/approve_from_already_approved_returns_invalid_state
        """
        customer, vehicle, tire, wo, line, approved = setup_approved_order_with_tire_line(
            quantity=4, tire_overrides={"unit_price_cents": 14999, "mileage_warranty_miles": 60000,
                                        "original_tread_32nds": 10, "stock_qty": 10})
        validate_error(api.approve_work_order(
            wo["id"], {"expected_work_order_version": wo["version"]}, ADVISOR),
            ApiErrorId.ERR_INVALID_STATE)
        assert validate_success(api.get_tire_model(tire["id"], INV))["stock_qty"] == 6

    def test_cancel_already_cancelled_rejected(self, api):
        """PRD §2.7: "with `CANCELLED` as a terminal sink."
        PRD §3.7: "A `ServiceAdvisor` may cancel an order whose `fulfillment_status` is
        `DRAFT` or `APPROVED`". (A CANCELLED order is in neither state.)

        Design: Corner/state_machines/cancel_from_terminal_cancelled_returns_invalid_state
        """
        customer = create_customer()
        vehicle = create_vehicle(customer["id"], make="MAZDA", model="MX5",
                                 oe_tire_size="205/45R17", rim_diameter_in=17)
        wo = create_work_order(customer["id"], vehicle["id"])
        cancelled = validate_success(api.cancel_work_order(
            wo["id"], {"expected_work_order_version": wo["version"]}, ADVISOR))
        wo["version"] = cancelled["version"]
        validate_error(api.cancel_work_order(
            wo["id"], {"expected_work_order_version": wo["version"]}, ADVISOR),
            ApiErrorId.ERR_INVALID_STATE)

    def test_add_line_to_approved_order_rejected(self, api):
        """PRD §3.2: "Line items are added only while the order is still `DRAFT`; an attempt to
        add a line to an order in any other state is rejected with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/add_line_to_approved_order_rejected
        """
        customer, vehicle, tire, wo, line, approved = setup_approved_order_with_tire_line(
            quantity=4, tire_overrides={"unit_price_cents": 14999, "stock_qty": 10})
        validate_error(api.add_work_order_line(
            wo["id"], {"line_type": "ROTATION", "quantity": 1,
                       "expected_work_order_version": wo["version"]}, ADVISOR),
            ApiErrorId.ERR_INVALID_STATE)


class TestSpecialOrderBranches:
    def test_receive_restocks_tire_model(self, api):
        """PRD §3.8: "When the goods arrive, the manager receives the order, moving its
        `status` from `ORDERED` to `RECEIVED`; receiving increments the tire model's
        `stock_qty` by the `requested_quantity`".

        stock 0, requested_quantity 4 -> stock 4 after receive.

        Design: Corner/state_machines/special_order_receive_restocks_tire_model
        """
        customer, vehicle, tire, wo, line, so = setup_special_order(requested_quantity=4)
        data = validate_success(api.receive_special_order(so["id"], INV))
        assert data["status"] == "RECEIVED"
        assert validate_success(api.get_tire_model(tire["id"], INV))["stock_qty"] == 4

    def test_cancel_backorder_voids_draft_line(self, api):
        """PRD §3.8: "the manager may cancel the back-order, moving its `status` from
        `ORDERED` to `BACKORDER_CANCELLED`; the `deposit_cents` is forfeited and remains
        booked, and the linked work-order line is moved to `VOID` if its parent work order is
        still `DRAFT`."

        Design: Corner/state_machines/special_order_branch_cancel_backorder_voids_draft_line
        """
        customer, vehicle, tire, wo, line, so = setup_special_order(requested_quantity=4)
        data = validate_success(api.cancel_backorder(so["id"], INV))
        assert data["status"] == "BACKORDER_CANCELLED"
        assert validate_success(api.get_work_order_line(line["id"], ADVISOR))["line_status"] == "VOID"

    def test_mileage_claim_reject_terminal(self, api):
        """PRD §3.9: "A `ServiceAdvisor` may instead reject a `SUBMITTED` claim, moving its
        `status` to `REJECTED`."

        Design: Corner/state_machines/mileage_claim_reject_terminal
        """
        customer, vehicle, tire, wo, line, approved = setup_approved_order_with_tire_line(
            quantity=4, tire_overrides={"unit_price_cents": 7000, "mileage_warranty_miles": 50000,
                                        "original_tread_32nds": 10, "stock_qty": 8})
        claim = get_success_data(api.create_mileage_claim(
            F.create_mileage_claim_payload(line["id"], tire["id"], measured_tread_32nds=5,
                                           miles_driven=10000, payout_method="REFUND",
                                           claim_quantity=4), ADVISOR))
        data = validate_success(api.reject_mileage_claim(claim["id"], ADVISOR))
        assert data["status"] == "REJECTED"


# ---------------------------------------------------------------------------
# Corner — validations (ownership, line-type, payment gate)
# ---------------------------------------------------------------------------
class TestBodyValidations:
    def test_vehicle_not_owned_by_workorder_customer(self, api):
        """PRD §3.2: "The vehicle named by `vehicle_id` must be owned by the customer named by
        `customer_id` — that is, the vehicle's owner must be that same customer — and a
        mismatch is rejected with `ERR_VEHICLE_NOT_OWNED`."

        Design: Corner/validations/vehicle_not_owned_by_workorder_customer
        """
        cust_a = create_customer()
        cust_b = create_customer()
        veh_b = create_vehicle(cust_b["id"])
        validate_error(api.create_work_order(
            {"customer_id": cust_a["id"], "vehicle_id": veh_b["id"]}, ADVISOR),
            ApiErrorId.ERR_VEHICLE_NOT_OWNED)

    def test_tire_line_missing_tire_model_id(self, api):
        """PRD §3.2: "A `TIRE` line must name the tire it sells through `tire_model_id`, and a
        non-`TIRE` line must omit `tire_model_id` entirely; either violation — a `TIRE` line
        without the field or a non-`TIRE` line carrying it — is rejected with
        `ERR_LINE_TYPE_FIELD_MISMATCH`."

        Design: Corner/validations/tire_line_missing_tire_model_id
        """
        customer = create_customer()
        vehicle = create_vehicle(customer["id"])
        wo = create_work_order(customer["id"], vehicle["id"])
        validate_error(api.add_work_order_line(
            wo["id"], {"line_type": "TIRE", "quantity": 4,
                       "expected_work_order_version": wo["version"]}, ADVISOR),
            ApiErrorId.ERR_LINE_TYPE_FIELD_MISMATCH)

    def test_non_tire_line_with_tire_model_id_rejected(self, api):
        """PRD §3.2: "a non-`TIRE` line must omit `tire_model_id` entirely; either violation —
        a `TIRE` line without the field or a non-`TIRE` line carrying it — is rejected with
        `ERR_LINE_TYPE_FIELD_MISMATCH`."

        Design: Corner/validations/non_tire_line_with_tire_model_id_rejected
        """
        customer, vehicle, tire = setup_customer_vehicle_tire(
            tire_overrides={"unit_price_cents": 10000, "stock_qty": 4})
        wo = create_work_order(customer["id"], vehicle["id"])
        validate_error(api.add_work_order_line(
            wo["id"], {"line_type": "ROTATION", "tire_model_id": tire["id"], "quantity": 1,
                       "expected_work_order_version": wo["version"]}, ADVISOR),
            ApiErrorId.ERR_LINE_TYPE_FIELD_MISMATCH)

    def test_complete_unpaid_order_returns_payment_required(self, api):
        """PRD §3.7: "an order may be completed only if its `payment_status` is `AUTHORIZED`
        or `PAID`, and an attempt to complete an order that is still `UNPAID` is rejected with
        `ERR_PAYMENT_REQUIRED`."
        PRD §3.6: "Payment is deliberately *not* gated at check-in — an `UNPAID` order may be
        checked in and serviced — because the money gate lives at completion instead."

        Design: Corner/validations/complete_unpaid_order_returns_payment_required
        """
        customer, vehicle, tire, wo, line, bay, appt = setup_checked_in_in_service_order(
            scheduled_start="2026-08-10T09:00:00.000Z",
            scheduled_end="2026-08-10T10:00:00.000Z", authorize=False)
        validate_error(api.complete_work_order(wo["id"], TECH), ApiErrorId.ERR_PAYMENT_REQUIRED)


# ---------------------------------------------------------------------------
# Corner — errors (OCC version guards)
# ---------------------------------------------------------------------------
class TestVersionGuards:
    def test_stale_bay_version_on_appointment_create(self, api):
        """PRD §2.9: "Booking an install appointment requires `expected_service_bay_version` to
        equal the chosen bay's current `version`; because a bay's version is bumped whenever
        an appointment is booked on it ... a mismatch ... the booking is rejected with
        `ERR_STALE_BAY_VERSION`."

        Design: Corner/errors/stale_bay_version_on_appointment_create
        """
        customer, vehicle, tire = setup_customer_vehicle_tire(
            tire_overrides={"unit_price_cents": 10000, "stock_qty": 20})
        bay = create_service_bay(turnover_buffer_min=15)
        bay_v0 = bay["version"]
        wo1 = create_work_order(customer["id"], vehicle["id"])
        add_tire_line(wo1, tire["id"], quantity=4)
        approve_order(wo1)
        book_appointment(wo1, bay, "2026-08-03T09:00:00.000Z", "2026-08-03T10:00:00.000Z")  # bumps bay version
        wo2 = create_work_order(customer["id"], vehicle["id"])
        add_tire_line(wo2, tire["id"], quantity=4)
        approve_order(wo2)
        validate_error(api.create_appointment(
            F.create_appointment_payload(
                wo2["id"], bay["id"], "2026-08-03T13:00:00.000Z", "2026-08-03T14:00:00.000Z",
                bay_v0), ADVISOR),
            ApiErrorId.ERR_STALE_BAY_VERSION)


# ---------------------------------------------------------------------------
# Corner — cross-cutting (OCC increments, reverse-reachable reads)
# ---------------------------------------------------------------------------
class TestCrossCutting:
    def test_bay_version_increments_on_booking(self, api):
        """PRD §3.6: "A successful booking bumps the bay's `version` by one."

        Bay born version 1 -> after a successful booking -> version 2.

        Design: Corner/cross_cutting/bay_version_increments_on_each_booking
        """
        customer, vehicle, tire, wo, line, approved = setup_approved_order_with_tire_line(
            quantity=4, tire_overrides={"unit_price_cents": 10000, "stock_qty": 8})
        bay = create_service_bay(turnover_buffer_min=15)
        assert bay["version"] == 1
        appt = validate_success(api.create_appointment(
            F.create_appointment_payload(
                wo["id"], bay["id"], "2026-08-04T09:00:00.000Z", "2026-08-04T10:00:00.000Z",
                bay["version"]), ADVISOR), expected_status=201)
        assert validate_success(api.get_service_bay(bay["id"], INV))["version"] == 2

    def test_bay_close_stale_version_rejected(self, api):
        """PRD §3.5: "only when the supplied `expected_service_bay_version` matches the bay's
        current `version`; closing bumps that `version` by one."
        PRD §2.9: "The work-order approval, bay-close, and bay-reopen operations are likewise
        version-checked against their target; where a guarded write's supplied version does not
        match and no more specific code applies, the generic `ERR_STALE_VERSION` is returned,
        also with HTTP 412."

        A booking advanced the bay to version 2; closing with the stale pre-booking version 1
        is rejected with the generic ERR_STALE_VERSION (ERR_STALE_BAY_VERSION is specific to
        booking an install appointment, not bay-close).

        Design: Corner/cross_cutting/bay_close_stale_version_rejected
        """
        customer, vehicle, tire = setup_customer_vehicle_tire(
            tire_overrides={"unit_price_cents": 10000, "stock_qty": 8})
        bay = create_service_bay(turnover_buffer_min=15)
        bay_v0 = bay["version"]
        wo = create_work_order(customer["id"], vehicle["id"])
        add_tire_line(wo, tire["id"], quantity=4)
        approve_order(wo)
        appt = book_appointment(wo, bay, "2026-08-05T09:00:00.000Z", "2026-08-05T10:00:00.000Z")
        # cancel the order so its appointment cancels (close precondition: no active appointments)
        validate_success(api.cancel_work_order(
            wo["id"], {"expected_work_order_version": wo["version"]}, ADVISOR))
        validate_error(api.close_service_bay(bay["id"], {"expected_service_bay_version": bay_v0}, INV),
                       ApiErrorId.ERR_STALE_VERSION)

    def test_road_hazard_reverse_reachable_by_line(self, api):
        """PRD §3.4: "Warranties can be fetched and listed, filterable by `work_order_line_id`
        or `tire_model_id`."
        PRD §3.4: "The line's `premium_cents` is the greater of the rounded percentage term
        and the floor".

        unit 8000 qty 1: pct=960, floor=1200 -> premium 1200; warranty ACTIVE after approval.

        Design: Corner/cross_cutting/road_hazard_warranty_reverse_reachable_by_line
        """
        customer, vehicle, tire, wo, line, approved = setup_approved_order_with_tire_line(
            quantity=1, road_hazard_opted=True, grade="APPROVED_PLUS",
            tire_overrides={"unit_price_cents": 8000, "mileage_warranty_miles": 0,
                            "original_tread_32nds": 9, "stock_qty": 4})
        data, _ = validate_paginated(
            api.list_road_hazard_warranties(ADVISOR, params={"work_order_line_id": line["id"]}))
        assert len(data) == 1
        assert data[0]["premium_cents"] == 1200
        assert data[0]["status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# Corner — RBAC
# ---------------------------------------------------------------------------
class TestRbac:
    def test_technician_cannot_approve_work_order(self, api):
        """PRD §2.1: "When the headers are well formed but the role is not permitted to perform
        the requested operation, the request is rejected with `ERR_UNAUTHORIZED`."
        PRD §3.2: "Approval is the pivotal event, performed by a `ServiceAdvisor`". (Approve is
        a ServiceAdvisor-only operation per §4.)

        Design: Corner/rbac/technician_cannot_approve_work_order
        """
        customer, vehicle, tire = setup_customer_vehicle_tire(
            tire_overrides={"unit_price_cents": 10000, "stock_qty": 8})
        wo = create_work_order(customer["id"], vehicle["id"])
        add_tire_line(wo, tire["id"], quantity=4)
        validate_error(api.approve_work_order(
            wo["id"], {"expected_work_order_version": wo["version"]}, TECH),
            ApiErrorId.ERR_UNAUTHORIZED)

    def test_customer_cannot_create_tire_model(self, api):
        """PRD §2.1: "When the headers are well formed but the role is not permitted to perform
        the requested operation, the request is rejected with `ERR_UNAUTHORIZED`."
        PRD §3.1: "The `InventoryManager` builds and maintains the catalog." (Create tire model
        is an InventoryManager-only operation per §4.)

        Design: Corner/rbac/customer_cannot_create_tire_model
        """
        customer = create_customer()
        validate_error(api.create_tire_model(
            {"brand": "X", "model_name": "Y", "size_token": "235/45R18", "load_index": 94,
             "speed_rating": "V", "unit_price_cents": 10000, "original_tread_32nds": 10},
            make_customer_headers(customer["id"])),
            ApiErrorId.ERR_UNAUTHORIZED)

    def test_missing_auth_header_returns_unauthenticated(self, api):
        """PRD §2.1: "Every request must carry two mandatory HTTP headers: `X-User-ID`,
        identifying the acting user, and `X-User-Role`, declaring the capacity in which they
        act. If either header is missing, or `X-User-Role` is not one of the recognized roles,
        the request is rejected with `ERR_UNAUTHENTICATED`."

        Design: Corner/rbac/missing_auth_header_returns_unauthenticated
        """
        validate_error(api.create_customer(F.create_customer_payload(), {}),
                       ApiErrorId.ERR_UNAUTHENTICATED)
