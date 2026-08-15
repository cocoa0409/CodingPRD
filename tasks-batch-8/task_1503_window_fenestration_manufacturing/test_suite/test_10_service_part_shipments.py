"""Service-part shipments and claim fulfillment cascades (PRD §3.7)."""
from test_helpers import (
    ApiErrorId,
    approve_repair_part,
    create_claim,
    list_claim_shipments,
    set_clock,
    setup_claim_under_review,
    setup_delivered_order,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

PM = TEST_USERS["plant_manager_headers"]
SC = TEST_USERS["shipping_coordinator_headers"]
WA = TEST_USERS["warranty_adjuster_headers"]


def test_deliver_service_part_fulfills_claim(api):
    """PRD §3.7: "A `REPAIR_PART` remedy also carries `part_sku`, `quantity`,
    and a `carrier` of `PARCEL`, `STANDARD_FREIGHT`, or `EXPEDITED`, and creates
    a **ServicePartShipment** in `PICKING` status referencing the claim via
    `warranty_claim_id`."
    PRD §3.7: "Service-part shipments walk `PICKING → SHIPPED → DELIVERED`
    under a `ShippingCoordinator` or `PlantManager`. Delivering the shipment
    cascades upward: the parent claim moves from `APPROVED` to `FULFILLED`,
    closing the loop."

    Design: Corner/endpoints/deliver_service_part_fulfills_claim
    """
    env = setup_claim_under_review(component="HARDWARE", coverage_variant="COMPONENT")
    claim_id = env["claim"]["id"]

    approved = approve_repair_part(claim_id, part_sku="CRANK-7", quantity=2, carrier="PARCEL")
    assert approved["status"] == "APPROVED"

    shipments = list_claim_shipments(claim_id)
    assert len(shipments) == 1
    shipment = shipments[0]
    assert shipment["status"] == "PICKING"
    assert shipment["part_sku"] == "CRANK-7"
    assert shipment["quantity"] == 2
    assert shipment["carrier"] == "PARCEL"
    assert shipment["shipping_charge_cents"] == 0, "full 100% coverage ships free"
    assert shipment["warranty_claim_id"] == claim_id

    shipped = validate_success(api.ship_shipment(shipment["id"], SC), 200)
    assert shipped["status"] == "SHIPPED"
    delivered = validate_success(api.deliver_shipment(shipment["id"], SC), 200)
    assert delivered["status"] == "DELIVERED"

    claim = validate_success(api.get_warranty_claim(claim_id, WA), 200)
    assert claim["status"] == "FULFILLED"


def test_deliver_before_ship_returns_invalid_state(api):
    """PRD §3.7: "Service-part shipments walk `PICKING → SHIPPED → DELIVERED`
    under a `ShippingCoordinator` or `PlantManager`."
    PRD §2.10: "Any transition attempted from a state in which it is not defined
    is rejected with `ERR_INVALID_STATE` unless a more specific state error
    applies."

    Design: Corner/endpoints/deliver_before_ship_returns_invalid_state
    """
    env = setup_claim_under_review(component="HARDWARE", coverage_variant="COMPONENT")
    approve_repair_part(env["claim"]["id"])
    shipment = list_claim_shipments(env["claim"]["id"])[0]
    assert shipment["status"] == "PICKING"

    res = api.deliver_shipment(shipment["id"], SC)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


def test_service_part_charge_conditional_on_coverage(api):
    """PRD §3.7: "The shipment's `shipping_charge_cents` is zero when the
    claim's coverage is a full 100 percent; otherwise it is the carrier's flat
    fee — 2,500 cents for `PARCEL`, 8,000 cents for `STANDARD_FREIGHT`, or
    15,000 cents for `EXPEDITED`."
    PRD §3.7: "Either way, `remedy_value_cents` is set to the line's frozen
    `line_total_cents` multiplied by `coverage_pct` and divided by one hundred,
    rounded half-up to whole cents — prorated first, rounded once."

    Design: Corner/calculations/service_part_charge_conditional_on_coverage
    """
    env = setup_delivered_order()

    # Claim A: FRAME/COMPONENT at 0 elapsed years -> coverage 100
    set_clock("2027-09-01T00:00:00Z")
    claim_a = create_claim(env["order"]["id"], env["line"]["id"],
                           component="FRAME", coverage_variant="COMPONENT",
                           failure_date="2027-09-01T00:00:00Z",
                           description="frame crack")
    get = validate_success(api.take_review_claim(claim_a["id"], WA), 200)
    assert get["status"] == "UNDER_REVIEW"
    approved_a = approve_repair_part(claim_a["id"], part_sku="FRAME-KIT-1",
                                     quantity=1, carrier="EXPEDITED")
    assert approved_a["remedy_value_cents"] == 165003
    shipment_a = list_claim_shipments(claim_a["id"])[0]
    assert shipment_a["shipping_charge_cents"] == 0

    # Claim B: IG_SEAL/WHOLE_UNIT at 8 elapsed years -> coverage 40
    set_clock("2034-09-06T00:00:00Z")
    claim_b = create_claim(env["order"]["id"], env["line"]["id"],
                           component="IG_SEAL", coverage_variant="WHOLE_UNIT",
                           failure_date="2034-09-06T00:00:00Z",
                           description="fogging")
    assert claim_b["coverage_pct"] == 40
    validate_success(api.take_review_claim(claim_b["id"], WA), 200)
    approved_b = approve_repair_part(claim_b["id"], part_sku="IG-UNIT-40X60",
                                     quantity=1, carrier="EXPEDITED")
    # round_half_up(165003 * 40 / 100) = round_half_up(66001.2) = 66001
    assert approved_b["remedy_value_cents"] == 66001
    shipment_b = list_claim_shipments(claim_b["id"])[0]
    assert shipment_b["shipping_charge_cents"] == 15000, (
        "EXPEDITED flat fee applies because coverage is below 100"
    )
