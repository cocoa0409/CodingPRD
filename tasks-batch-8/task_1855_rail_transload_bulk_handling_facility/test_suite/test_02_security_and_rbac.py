"""Authentication, the validation priority ladder, RBAC denials/allows, and
CustomerRep ownership scoping."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    UNAUTHENTICATED_HEADERS,
    ApiErrorId,
    allocation_adjustment_payload,
    create_customer_payload,
    create_incident_payload,
    create_invoice_payload,
    create_product_payload,
    create_railcar_payload,
    create_spot_order_payload,
    get_success_data,
    make_customer_rep_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    ADMIN,
    BILLING,
    OPERATOR,
    SAFETY,
    YARD,
    arrive_car,
    create_customer,
    create_equipment,
    create_facility,
    create_lot,
    create_product,
    create_railcar,
    create_spot_order_for_car,
    create_track,
    schedule_spot_order,
    set_clock,
)


def _base_setup():
    """Facility + customer + product + lot + track + one REGISTERED car."""
    fac = create_facility(name="FT-V1")
    cust = create_customer(name="C1", allocated_car_spots=5)
    prod = create_product(name="Salt")
    lot = create_lot(cust["id"], prod["id"])
    trk = create_track(name="T1", spot_capacity=1)
    car = create_railcar(cust["id"], prod["id"], lot["id"], car_number="97101")
    return fac, cust, prod, lot, trk, car


class TestValidationLadder:
    def test_auth_and_priority_ordering_rejected(self, api):
        """PRD §2.9: "Every endpoint evaluates its checks in a fixed priority
        order, and when several checks fail the earliest one wins:"
        PRD §2.9: "1. Authentication — headers present and role declared
        (`ERR_UNAUTHENTICATED`)." "2. Endpoint authorization — role listed for
        the endpoint (`ERR_FORBIDDEN_ROLE`)." "3. Existence — path ids resolve
        left-to-right, then body foreign-key ids (`railcar_id`, `lot_id`,
        `customer_id`, `product_id`, `equipment_id`, `track_id`) resolve
        (`ERR_NOT_FOUND`, 404)." "4. Envelope and shape — required fields
        present, types valid, enum members valid, numeric ranges valid
        (strictly positive where required), and `window_end` strictly after
        `window_start` (`ERR_INVALID_REQUEST`, 400)."
        PRD §2.1: "A request missing either header, or whose `X-User-Role`
        does not name one of the declared roles, is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/auth_and_priority_ordering_rejected
        """
        _fac, cust, _prod, _lot, trk, car = _base_setup()

        # 1: missing auth headers beats everything else
        validate_error(
            api.create_customer(
                create_customer_payload(name="X", allocated_car_spots=1),
                UNAUTHENTICATED_HEADERS,
            ),
            ApiErrorId.ERR_UNAUTHENTICATED,
        )

        # 2 beats 3: CustomerRep on an admin-only endpoint whose path id does
        # not exist -> ERR_FORBIDDEN_ROLE, not ERR_NOT_FOUND
        rep = make_customer_rep_headers(cust["id"])
        validate_error(
            api.create_allocation_adjustment(
                NON_EXISTENT_UUID,
                allocation_adjustment_payload(
                    expected_customer_version=cust["version"],
                    new_allocated_car_spots=9,
                ),
                rep,
            ),
            ApiErrorId.ERR_FORBIDDEN_ROLE,
        )

        # 3 beats 5: a real role on a non-existent spot order -> ERR_NOT_FOUND
        validate_error(
            api.schedule_spot_order(NON_EXISTENT_UUID, YARD),
            ApiErrorId.ERR_NOT_FOUND,
        )

        # 4 beats 5: REGISTERED car (wrong state for anything) + reversed
        # window (bad shape) -> ERR_INVALID_REQUEST
        validate_error(
            api.create_spot_order(
                car["id"],
                create_spot_order_payload(
                    expected_railcar_version=car["version"],
                    track_id=trk["id"],
                    spot_number=1,
                    window_start="2026-08-03T05:00:00Z",
                    window_end="2026-08-03T01:00:00Z",
                ),
                YARD,
            ),
            ApiErrorId.ERR_INVALID_REQUEST,
        )

    def test_validation_satisfaction_passes(self, api):
        """PRD §3.4: "The new order then takes its own reservation —
        `Track.reserved_spots` increases by one — starts in `REQUESTED`, and
        bumps `Railcar.version`."
        PRD §4: "Creation of a new resource returns HTTP 201; state
        transitions, modifications, and reads return HTTP 200."

        Design: Corner/validations/validation_satisfaction_passes
        """
        _fac, _cust, _prod, _lot, trk, car = _base_setup()
        car = arrive_car(car["id"])

        order = validate_success(
            api.create_spot_order(
                car["id"],
                create_spot_order_payload(
                    expected_railcar_version=car["version"],
                    track_id=trk["id"],
                    spot_number=1,
                    window_start="2026-08-04T01:00:00Z",
                    window_end="2026-08-04T03:00:00Z",
                ),
                YARD,
            ),
            201,
        )
        assert order["status"] == "REQUESTED"
        assert order["id"], "server assigns an id"
        assert order["track_id"] == trk["id"]


class TestRbac:
    def test_rbac_role_denials_rejected(self, api):
        """PRD §2.1: "If the role is declared but not listed among the roles
        authorized for the endpoint, the request is rejected with
        `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §4: "| POST | /transload/railcars | Register inbound railcar
        (advance consist) | YardMaster |" — the FacilityAdmin is not listed:
        the peer role model grants no admin override. Likewise
        "| POST | /transload/customers/{customerId}/allocation-adjustments |
        OCC track-space allocation adjustment | FacilityAdmin |" and
        "| POST | /transload/tracks/{trackId}/engage-derail | Derail
        protection DISENGAGED → ENGAGED | SafetyOfficer |" and
        "| POST | /transload/invoices | Create DRAFT invoice for a customer
        and period | BillingClerk, FacilityAdmin |".

        Design: Corner/rbac/rbac_role_denials_rejected
        """
        _fac, cust, prod, lot, trk, _car = _base_setup()
        rep = make_customer_rep_headers(cust["id"])

        denials = [
            # CustomerRep creating a product (FacilityAdmin-only endpoint)
            api.create_product(create_product_payload(name="X"), rep),
            # TransferOperator registering a railcar (YardMaster-only)
            api.create_railcar(
                create_railcar_payload(
                    customer_id=cust["id"], product_id=prod["id"],
                    lot_id=lot["id"], car_number="97302",
                    quantity_loaded_tons=10.0,
                ),
                OPERATOR,
            ),
            # YardMaster creating an invoice (BillingClerk/FacilityAdmin)
            api.create_invoice(
                create_invoice_payload(customer_id=cust["id"]), YARD
            ),
            # BillingClerk engaging a derail (SafetyOfficer-only)
            api.engage_derail(trk["id"], BILLING),
            # SafetyOfficer creating a customer (FacilityAdmin-only)
            api.create_customer(
                create_customer_payload(name="Y", allocated_car_spots=1), SAFETY
            ),
            # FacilityAdmin registering a railcar — peer role model, no
            # admin override (YardMaster-only per §4)
            api.create_railcar(
                create_railcar_payload(
                    customer_id=cust["id"], product_id=prod["id"],
                    lot_id=lot["id"], car_number="97303",
                    quantity_loaded_tons=10.0,
                ),
                ADMIN,
            ),
            # YardMaster posting an allocation adjustment (FacilityAdmin-only)
            api.create_allocation_adjustment(
                cust["id"],
                allocation_adjustment_payload(
                    expected_customer_version=cust["version"],
                    new_allocated_car_spots=9,
                ),
                YARD,
            ),
        ]
        for resp in denials:
            validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

        # No side effects leaked through the denials.
        track = get_success_data(api.get_track(trk["id"], YARD))
        assert track["derail_protection"] == "DISENGAGED"
        customer = get_success_data(api.get_customer(cust["id"], ADMIN))
        assert customer["allocated_car_spots"] == 5
        _data, meta = validate_paginated(api.list_railcars(YARD))
        assert meta["total_count"] == 1, "denied railcar creates added nothing"

    def test_rbac_positive_sweep(self, api):
        """PRD §4: "| POST | /transload/railcars/{railcarId}/arrive |
        REGISTERED → ARRIVED; stamps arrival, loads lot | YardMaster |" and
        "| POST | /transload/equipment/{equipmentId}/start-cleaning |
        Equipment AVAILABLE → CLEANING | TransferOperator |" and
        "| POST | /transload/railcars/{railcarId}/place-hold | hold_status
        NONE → SAFETY_HOLD | SafetyOfficer |" and
        "| POST | /transload/invoices | Create DRAFT invoice for a customer
        and period | BillingClerk, FacilityAdmin |" and
        "| GET | /transload/customers/{customerId} | Get customer |
        FacilityAdmin, YardMaster, SafetyOfficer, TransferOperator,
        BillingClerk, CustomerRep |".

        Design: Corner/rbac/rbac_positive_sweep
        """
        fac = create_facility(name="FT-R2")
        cust = create_customer(name="C1", allocated_car_spots=5)
        prod = create_product(name="Salt")
        lot = create_lot(cust["id"], prod["id"])
        eq = create_equipment(name="PUMP-1", equipment_type="PUMP")
        car = create_railcar(cust["id"], prod["id"], lot["id"], car_number="97311")

        arrived = validate_success(api.arrive_railcar(car["id"], YARD))
        assert arrived["placement_status"] == "ARRIVED"

        cleaning = validate_success(api.start_equipment_cleaning(eq["id"], OPERATOR))
        assert cleaning["status"] == "CLEANING"

        held = validate_success(api.place_hold(car["id"], "check", SAFETY))
        assert held["hold_status"] == "SAFETY_HOLD"

        inv = validate_success(
            api.create_invoice(create_invoice_payload(customer_id=cust["id"]), BILLING),
            201,
        )
        assert inv["status"] == "DRAFT"

        rep = make_customer_rep_headers(cust["id"])
        own = validate_success(api.get_customer(cust["id"], rep))
        assert own["id"] == cust["id"]


class TestCustomerRepOwnership:
    def test_customer_rep_cross_customer_rejected(self, api):
        """PRD §2.1: "When `X-User-Role` is `CustomerRep`, `X-User-ID` is the
        `id` of the acting `Customer`; ownership checks on any resource that
        references a `Customer` compare the resource's customer foreign key to
        `X-User-ID`, and a mismatch is rejected with `ERR_RESOURCE_NOT_OWNED`
        (HTTP 403). The ownership rule applies to listing and reading railcars,
        spot orders, transfer orders, weight tickets, charges, and invoices
        (including the single-entity reads of those resources), and to creating
        or cancelling spot orders and paying or disputing invoices — a
        `CustomerRep` may only touch resources of their own customer record."

        Design: Corner/rbac/customer_rep_cross_customer_rejected
        """
        set_clock("2026-08-03T00:00:00Z")
        create_facility(name="FT-R3")
        cust_a = create_customer(name="A", allocated_car_spots=5)
        cust_b = create_customer(name="B", allocated_car_spots=5)
        prod = create_product(name="Salt")
        lot_a = create_lot(cust_a["id"], prod["id"])
        lot_b = create_lot(cust_b["id"], prod["id"])
        trk = create_track(name="T1", spot_capacity=2)
        car_a = create_railcar(cust_a["id"], prod["id"], lot_a["id"], car_number="97321")
        car_b = create_railcar(cust_b["id"], prod["id"], lot_b["id"], car_number="97322")
        car_a = arrive_car(car_a["id"])
        car_b = arrive_car(car_b["id"])
        so_b = create_spot_order_for_car(
            car_b["id"], trk["id"], 1,
            "2026-08-03T01:00:00Z", "2026-08-03T03:00:00Z",
        )
        schedule_spot_order(so_b["id"])
        inv_b = get_success_data(
            api.create_invoice(
                create_invoice_payload(customer_id=cust_b["id"]), BILLING
            )
        )
        get_success_data(api.issue_invoice(inv_b["id"], BILLING))
        car_b_now = get_success_data(api.get_railcar(car_b["id"], YARD))

        rep_a = make_customer_rep_headers(cust_a["id"])
        rep_b = make_customer_rep_headers(cust_b["id"])

        # A's rep reading B's car -> 403; reading own car -> 200
        validate_error(api.get_railcar(car_b["id"], rep_a),
                       ApiErrorId.ERR_RESOURCE_NOT_OWNED)
        own_car = validate_success(api.get_railcar(car_a["id"], rep_a))
        assert own_car["id"] == car_a["id"]

        # A's rep paying B's invoice -> 403; B's rep paying it -> PAID
        validate_error(api.pay_invoice(inv_b["id"], rep_a),
                       ApiErrorId.ERR_RESOURCE_NOT_OWNED)
        paid = validate_success(api.pay_invoice(inv_b["id"], rep_b))
        assert paid["status"] == "PAID"

        # A's rep creating a spot order for B's car -> 403 (ownership is
        # checked before the OCC version guard, PRD §2.9 items 6 and 16)
        validate_error(
            api.create_spot_order(
                car_b["id"],
                create_spot_order_payload(
                    expected_railcar_version=car_b_now["version"],
                    track_id=trk["id"],
                    spot_number=2,
                    window_start="2026-08-03T06:00:00Z",
                    window_end="2026-08-03T08:00:00Z",
                ),
                rep_a,
            ),
            ApiErrorId.ERR_RESOURCE_NOT_OWNED,
        )

        # A's rep listing invoices scoped to B -> 403
        validate_error(
            api.list_invoices(rep_a, params={"customer_id": cust_b["id"]}),
            ApiErrorId.ERR_RESOURCE_NOT_OWNED,
        )
