"""Business validations: product mismatch, weight-class fit, de-ice field presence,
interval validity, uniqueness, contract expiry, spot out-of-service, overpayment
(PRD §3.2–§3.8).

Corner queue (B) instances (section: validations):
  - product_mismatch_on_fuel_order_create
  - weight_class_rejected_on_parking_assignment
  - deice_fields_required_on_non_deice_rejected
  - invalid_interval_on_service_visit
  - duplicate_tail_number_within_operator
  - contract_expired_blocks_dispatch
  - occupy_out_of_service_spot_rejected
  - overpayment_rejected_on_invoice_pay
"""
from test_helpers import (
    api_client as api,
    get_success_data,
    validate_error,
    setup_operator_aircraft_contract,
    setup_on_ground_visit,
    setup_departed_visit_with_invoice,
    create_requested_fuel_order,
    create_fuel_order_payload,
    create_aircraft_payload,
    create_service_visit_payload,
    create_parking_assignment_payload,
    occupy_payload,
    pay_invoice_payload,
    TEST_USERS,
)

OPS = TEST_USERS["ops_dispatcher_headers"]
FUEL = TEST_USERS["fuel_tech_headers"]
BILLING = TEST_USERS["billing_clerk_headers"]


def test_product_mismatch_on_fuel_order_create():
    """PRD §3.6: "The order's `product` must equal the aircraft's `fuel_type` and must
    equal the named contract's `product`, and that contract's `operator_id` must match
    the aircraft's `operator_id`; any of these disagreements is rejected with
    `ERR_PRODUCT_MISMATCH` (HTTP 422)."

    POST /fuel-orders with product AVGAS on a JET_A aircraft → ERR_PRODUCT_MISMATCH (422).

    Design: Corner/validations/product_mismatch_on_fuel_order_create
    """
    operator, aircraft, contract = setup_operator_aircraft_contract()
    visit = get_success_data(api.create_service_visit(
        create_service_visit_payload(operator["id"], aircraft["id"]), OPS))
    res = api.create_fuel_order(
        create_fuel_order_payload(visit["id"], aircraft["id"], contract["id"],
                                  product="AVGAS", ordered_gallons=100, tankering=False), FUEL)
    validate_error(res, "ERR_PRODUCT_MISMATCH")


def test_weight_class_rejected_on_parking_assignment():
    """PRD §3.4: "At creation the system also checks that the spot can bear the aircraft's
    weight: a `HEAVY` spot accepts any weight class, a `MID` spot accepts only `LIGHT` and
    `MID` aircraft, and a `LIGHT` spot accepts only `LIGHT` aircraft; an aircraft whose
    `weight_class` exceeds the spot's `max_weight_class` is rejected with
    `ERR_WEIGHT_CLASS_REJECTED` (HTTP 422)."

    Assigning a HEAVY aircraft (mtow 50000) to a LIGHT-only TIE_DOWN spot →
    ERR_WEIGHT_CLASS_REJECTED (422).

    Design: Corner/validations/weight_class_rejected_on_parking_assignment
    """
    operator, _aircraft, _contract = setup_operator_aircraft_contract()
    heavy = get_success_data(api.create_aircraft(
        create_aircraft_payload(operator["id"], tail_number="N747JU", fuel_type="JET_A", mtow_lb=50000),
        OPS))
    spot = get_success_data(api.create_parking_spot(
        {"label": "TD-LIGHT", "spot_type": "TIE_DOWN", "max_weight_class": "LIGHT"}, OPS))
    visit = get_success_data(api.create_service_visit(
        create_service_visit_payload(operator["id"], heavy["id"]), OPS))
    res = api.create_parking_assignment(
        create_parking_assignment_payload(visit["id"], spot["id"]), OPS)
    validate_error(res, "ERR_WEIGHT_CLASS_REJECTED")


def test_deice_fields_on_non_deice_service_rejected():
    """PRD §3.8: "A `DE_ICE` service must carry a `deice_fluid_type` of `TYPE_I` or
    `TYPE_IV`, a `deice_fluid_gallons` of at least 1, and a `deice_holdover_minutes` of at
    least 0; a `DE_ICE` request missing any required de-ice field, or any non-de-ice
    service that supplies de-ice fields, is rejected with `ERR_DEICE_FIELDS_REQUIRED`
    (HTTP 422)."

    POST /ramp-services with service_type GPU but supplying de-ice fields →
    ERR_DEICE_FIELDS_REQUIRED (422).

    Design: Corner/validations/deice_fields_required_on_non_deice_rejected
    """
    operator, aircraft, _contract = setup_operator_aircraft_contract()
    visit = get_success_data(api.create_service_visit(
        create_service_visit_payload(operator["id"], aircraft["id"]), OPS))
    res = api.create_ramp_service(
        {"service_visit_id": visit["id"], "service_type": "GPU",
         "deice_fluid_gallons": 10, "deice_fluid_type": "TYPE_I"}, OPS)
    validate_error(res, "ERR_DEICE_FIELDS_REQUIRED")


def test_invalid_interval_on_service_visit():
    """PRD §3.3: "the departure must be strictly after the arrival, and a departure that
    is equal to or before the arrival is rejected with `ERR_INVALID_INTERVAL` (HTTP 422)."

    POST /service-visits with departure_utc before arrival_utc → ERR_INVALID_INTERVAL
    (422).

    Design: Corner/validations/invalid_interval_on_service_visit
    """
    operator, aircraft, _contract = setup_operator_aircraft_contract()
    res = api.create_service_visit(
        create_service_visit_payload(operator["id"], aircraft["id"],
                                     arrival_utc="2026-06-15T08:00:00.000Z",
                                     departure_utc="2026-06-14T08:00:00.000Z"), OPS)
    validate_error(res, "ERR_INVALID_INTERVAL")


def test_duplicate_tail_number_within_operator():
    """PRD §3.1: "The tail number must be unique within that operator; registering a
    second aircraft with a tail number already used under the same `operator_id` is
    rejected with `ERR_DUPLICATE_RESOURCE` (HTTP 409)."

    Registering a second aircraft with the same tail_number under one operator →
    ERR_DUPLICATE_RESOURCE (409).

    Design: Corner/validations/duplicate_tail_number_within_operator
    """
    operator, aircraft, _contract = setup_operator_aircraft_contract()
    res = api.create_aircraft(
        create_aircraft_payload(operator["id"], tail_number="N100AA", fuel_type="AVGAS", mtow_lb=5000),
        OPS)
    validate_error(res, "ERR_DUPLICATE_RESOURCE")


def test_contract_expired_blocks_dispatch():
    """PRD §3.6: "Dispatch is permitted only while `logistics_status` is `REQUESTED`,
    only while the parent visit is `ON_GROUND` or `SERVICING`, and only while the chosen
    contract is `ACTIVE` — a dispatch against an `EXPIRED` contract is rejected with
    `ERR_CONTRACT_EXPIRED` (HTTP 422)."

    Dispatching a REQUESTED order whose contract was EXPIRED after creation →
    ERR_CONTRACT_EXPIRED; the order stays REQUESTED.

    Design: Corner/validations/contract_expired_blocks_dispatch
    """
    operator, aircraft, contract = setup_operator_aircraft_contract()
    visit = setup_on_ground_visit(operator["id"], aircraft["id"])
    order = create_requested_fuel_order(visit["id"], aircraft["id"], contract["id"],
                                        ordered_gallons=6000, tankering=False)
    get_success_data(api.expire_fuel_contract(contract["id"], BILLING))
    res = api.dispatch_fuel_order(order["id"], FUEL)
    validate_error(res, "ERR_CONTRACT_EXPIRED")
    after = get_success_data(api.get_fuel_order(order["id"], FUEL))
    assert after["logistics_status"] == "REQUESTED"


def test_occupy_out_of_service_spot_rejected():
    """PRD §3.4: "an occupy attempt against a spot whose `spot_status` is `OUT_OF_SERVICE`
    is rejected with `ERR_SPOT_OUT_OF_SERVICE` (HTTP 409)."

    Occupying a HELD assignment whose spot was toggled OUT_OF_SERVICE →
    ERR_SPOT_OUT_OF_SERVICE (409); the assignment stays HELD.

    Design: Corner/validations/occupy_out_of_service_spot_rejected
    """
    operator, aircraft, _contract = setup_operator_aircraft_contract()
    visit = setup_on_ground_visit(operator["id"], aircraft["id"])
    spot = get_success_data(api.create_parking_spot(
        {"label": "TD-OOS", "spot_type": "TIE_DOWN", "max_weight_class": "HEAVY"}, OPS))
    assignment = get_success_data(api.create_parking_assignment(
        create_parking_assignment_payload(visit["id"], spot["id"]), OPS))
    get_success_data(api.out_of_service_parking_spot(spot["id"], OPS))
    res = api.occupy_parking_assignment(assignment["id"], occupy_payload(assignment["version"]), OPS)
    validate_error(res, "ERR_SPOT_OUT_OF_SERVICE")
    after = get_success_data(api.get_parking_assignment(assignment["id"], OPS))
    assert after["status"] == "HELD"


def test_overpayment_rejected_on_invoice_pay():
    """PRD §3.7: "The `payment_cents` must be at least 1, and `paid_cents` plus the
    payment must not exceed `total_cents` — a payment that would push the paid amount
    above the total, or a non-positive payment, is rejected with `ERR_OVERPAYMENT`
    (HTTP 422)."

    Paying 200,000 cents against an ISSUED invoice whose total is 180,000 →
    ERR_OVERPAYMENT; paid_cents stays 0.

    Design: Corner/validations/overpayment_rejected_on_invoice_pay
    """
    operator, aircraft, contract, visit, order, invoice = setup_departed_visit_with_invoice(
        order_overrides={"ordered_gallons": 6000, "tankering": True},
    )
    assert invoice["total_cents"] == 180_000
    res = api.pay_invoice(invoice["id"],
                          pay_invoice_payload(200_000, invoice["version"]), BILLING)
    validate_error(res, "ERR_OVERPAYMENT")
    after = get_success_data(api.get_invoice(invoice["id"], BILLING))
    assert after["paid_cents"] == 0
