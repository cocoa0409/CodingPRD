"""Entity creation, computed fields, defaults, and reference/validation errors
(PRD §2.5, §3.1, §3.3, §3.6).

Corner queue (B) instances (section: entities):
  - create_operator_returns_201_with_defaults
  - create_aircraft_computes_weight_class
  - create_service_visit_computes_nights
  - get_operator_not_found
  - create_fuel_order_missing_required_field
  - create_fuel_order_zero_gallons_rejected
  - fuel_order_defaults_tankering_false
  - create_aircraft_unknown_operator_not_found
"""
from test_helpers import (
    api_client as api,
    validate_success,
    validate_error,
    get_success_data,
    assert_operator,
    setup_operator_aircraft_contract,
    create_operator_payload,
    create_aircraft_payload,
    create_service_visit_payload,
    create_fuel_order_payload,
    NON_EXISTENT_UUID,
    TEST_USERS,
)

OPS = TEST_USERS["ops_dispatcher_headers"]
FUEL = TEST_USERS["fuel_tech_headers"]
BILLING = TEST_USERS["billing_clerk_headers"]


def test_create_operator_returns_201_with_defaults():
    """PRD §3.1: "A newly registered operator starts with `account_status` of `ACTIVE`,
    a `jeta_month_cumulative_gallons` of 0, and an `open_invoice_balance_cents` of 0."
    PRD §2.4: "The `version` field is an integer that begins at creation and increments
    by one on every mutation"

    POST /operators returns 201 with ACTIVE status, zeroed computed fields, and version 1.

    Design: Corner/entities/create_operator_returns_201_with_defaults
    """
    res = api.create_operator(create_operator_payload(), BILLING)
    operator = validate_success(res, 201)
    assert_operator(operator)
    assert operator["account_status"] == "ACTIVE"
    assert operator["jeta_month_cumulative_gallons"] == 0
    assert operator["open_invoice_balance_cents"] == 0
    assert operator["version"] == 1


def test_create_aircraft_computes_weight_class_mid():
    """PRD §3.1: "From the weight, the system derives the aircraft's `weight_class`: an
    aircraft is `LIGHT` when its `mtow_lb` is below 12,500 pounds, `MID` when its
    `mtow_lb` is at least 12,500 but below 41,000 pounds, and `HEAVY` at 41,000 pounds
    and above."

    An aircraft with mtow_lb 30000 derives weight_class MID.

    Design: Corner/entities/create_aircraft_computes_weight_class
    """
    operator = get_success_data(api.create_operator(create_operator_payload(), BILLING))
    res = api.create_aircraft(
        create_aircraft_payload(operator["id"], tail_number="N100AA", fuel_type="JET_A", mtow_lb=30000),
        OPS)
    aircraft = validate_success(res, 201)
    assert aircraft["weight_class"] == "MID"


def test_create_service_visit_computes_nights_three():
    """PRD §3.3: "From the two timestamps the system computes the visit's `nights` as the
    span from arrival to departure divided into 24-hour blocks and rounded up to the next
    whole block, with a floor of 1 night"
    PRD §3.3: "A new visit starts in `SCHEDULED` status with `services_outstanding` of 0"

    A visit spanning 2026-06-14T08:00Z → 2026-06-17T08:00Z (exactly 3 × 24h) computes
    nights 3, status SCHEDULED, services_outstanding 0.

    Design: Corner/entities/create_service_visit_computes_nights
    """
    operator, aircraft, _contract = setup_operator_aircraft_contract()
    res = api.create_service_visit(
        create_service_visit_payload(operator["id"], aircraft["id"],
                                     arrival_utc="2026-06-14T08:00:00.000Z",
                                     departure_utc="2026-06-17T08:00:00.000Z"), OPS)
    visit = validate_success(res, 201)
    assert visit["nights"] == 3
    assert visit["status"] == "SCHEDULED"
    assert visit["services_outstanding"] == 0


def test_get_operator_not_found():
    """PRD §2.5: "the first reference that does not resolve to an existing resource causes
    the whole request to be rejected with `ERR_NOT_FOUND` (HTTP 404) before any business
    rule is evaluated."

    GET /operators/{random uuid} returns ERR_NOT_FOUND (404).

    Design: Corner/entities/get_operator_not_found
    """
    res = api.get_operator(NON_EXISTENT_UUID, BILLING)
    validate_error(res, "ERR_NOT_FOUND")


def test_create_fuel_order_missing_required_field():
    """PRD §2.5: "A required input field that is entirely absent or structurally malformed
    is rejected earlier still, with `ERR_MISSING_FIELD` (HTTP 400)."
    PRD §3.6: "naming the `fuel_contract_id` whose pricing will apply, the `product`
    ordered, and the `ordered_gallons` (at least 1)"

    POST /fuel-orders omitting ordered_gallons returns ERR_MISSING_FIELD (400).

    Design: Corner/entities/create_fuel_order_missing_required_field
    """
    operator, aircraft, contract = setup_operator_aircraft_contract()
    visit = get_success_data(api.create_service_visit(
        create_service_visit_payload(operator["id"], aircraft["id"]), OPS))
    payload = create_fuel_order_payload(visit["id"], aircraft["id"], contract["id"])
    del payload["ordered_gallons"]
    del payload["tankering"]
    res = api.create_fuel_order(payload, FUEL)
    validate_error(res, "ERR_MISSING_FIELD")


def test_create_fuel_order_zero_gallons_rejected():
    """PRD §2.5: "A field that is present and well-formed but violates a declared value
    constraint — for instance an `ordered_gallons` below 1, or an `mtow_lb` below 1 — is
    rejected with `ERR_VALIDATION` (HTTP 422)."

    ordered_gallons=0 violates the >=1 constraint → ERR_VALIDATION (422).

    Design: Corner/entities/create_fuel_order_zero_gallons_rejected
    """
    operator, aircraft, contract = setup_operator_aircraft_contract()
    visit = get_success_data(api.create_service_visit(
        create_service_visit_payload(operator["id"], aircraft["id"]), OPS))
    res = api.create_fuel_order(
        create_fuel_order_payload(visit["id"], aircraft["id"], contract["id"], ordered_gallons=0),
        FUEL)
    validate_error(res, "ERR_VALIDATION")


def test_fuel_order_defaults_tankering_false():
    """PRD §3.6: "an optional `tankering` flag defaults to false."

    Omitting tankering defaults it to false on the created order.

    Design: Corner/entities/fuel_order_defaults_tankering_false
    """
    operator, aircraft, contract = setup_operator_aircraft_contract()
    visit = get_success_data(api.create_service_visit(
        create_service_visit_payload(operator["id"], aircraft["id"]), OPS))
    payload = create_fuel_order_payload(visit["id"], aircraft["id"], contract["id"], ordered_gallons=6000)
    del payload["tankering"]
    order = validate_success(api.create_fuel_order(payload, FUEL), 201)
    assert order["tankering"] is False


def test_create_aircraft_unknown_operator_not_found():
    """PRD §2.5: "Whenever a request names a resource, whether by an identifier embedded
    in the path or by a foreign key supplied in the body, that reference is resolved left
    to right in the order it appears, and the first reference that does not resolve to an
    existing resource causes the whole request to be rejected with `ERR_NOT_FOUND`
    (HTTP 404) before any business rule is evaluated."

    POST /aircraft with a non-existent operator_id FK returns ERR_NOT_FOUND (404).

    Design: Corner/entities/create_aircraft_unknown_operator_not_found
    """
    res = api.create_aircraft(
        create_aircraft_payload(NON_EXISTENT_UUID, tail_number="N1", fuel_type="JET_A", mtow_lb=9000),
        OPS)
    validate_error(res, "ERR_NOT_FOUND")
