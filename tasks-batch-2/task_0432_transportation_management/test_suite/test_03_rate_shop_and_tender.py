"""Rate shopping, tender offers, and tender disposition.

Covers the pricing-engine selector (lowest priced cost), the pinned
floor-then-fuel order of the quoted cost, candidate-set eligibility
(empty set, suspended carrier, out-of-window), the shipment's parallel
tender/execution dimensions, the decline revert, and shared expire.
"""
from test_helpers import (
    TEST_USERS,
    validate_success, validate_error,
    assert_tender,
    ApiErrorId,
    create_carrier_payload, create_contract_rate_payload,
    create_order_payload, create_shipment_payload,
    setup_carrier_rate, setup_tendered_shipment, setup_booked_shipment,
)

CARRIER = TEST_USERS["carrier_ops_headers"]
SHIPPER = TEST_USERS["shipper_ops_headers"]


class TestRateShopLowestCost:
    """Combinatorial selector: max-floor linehaul + rounded fuel, lowest priced cost."""

    def test_lowest_cost_carrier_selected_and_priced(self, api):
        """PRD §3.4: "The server then ranks the candidates and chooses the one with
        the lowest priced cost."
        PRD §3.4: "the linehaul charge is the larger of the rate's per-mile rate
        multiplied by the shipment's distance in miles and the rate's minimum
        charge floor; the fuel charge is the linehaul multiplied by the rate's fuel
        surcharge fraction, rounded half up to a whole number of cents; and the
        priced cost is the linehaul plus the fuel."

        Design: Difficulty/combinatorial_formula/rate_shop_lowest_cost_with_ontime_tiebreak_mode_a
        """
        carrier_a = validate_success(api.create_carrier(
            create_carrier_payload(name="Acme TL", scac="ACME", mode="TL"), CARRIER), 201)
        carrier_b = validate_success(api.create_carrier(
            create_carrier_payload(name="Best TL", scac="BEST", mode="TL"), CARRIER), 201)
        rate_a = validate_success(api.create_contract_rate(create_contract_rate_payload(
            carrier_id=carrier_a["id"], base_rate_per_mile_cents=250,
            min_charge_cents=50000, fuel_surcharge_pct=0.15), CARRIER), 201)
        validate_success(api.create_contract_rate(create_contract_rate_payload(
            carrier_id=carrier_b["id"], base_rate_per_mile_cents=200,
            min_charge_cents=80000, fuel_surcharge_pct=0.20), CARRIER), 201)
        order = validate_success(api.create_order(create_order_payload(), SHIPPER), 201)
        ship = validate_success(api.create_shipment(
            create_shipment_payload(order_id=order["id"], distance_miles=300, weight_lbs=6000),
            SHIPPER), 201)
        resp = api.create_tender(ship["id"], {"tender_minute": 100}, SHIPPER)
        tender = validate_success(resp, 201)
        assert_tender(tender)
        assert tender["carrier_id"] == carrier_a["id"]
        assert tender["contract_rate_id"] == rate_a["id"]
        assert tender["offered_rate_cents"] == 86250

    def test_offered_rate_is_priced_lowest_candidate_value(self, api):
        """PRD §3.4: "The selected carrier and rate are written onto the new tender
        as its `carrier_id` and `contract_rate_id`, and the priced cost is recorded
        as the tender's `offered_rate_cents`."

        Design: Difficulty/combinatorial_formula/rate_shop_lowest_cost_with_ontime_tiebreak_mode_a
        """
        carrier_a = validate_success(api.create_carrier(
            create_carrier_payload(name="Acme TL", scac="ACME", mode="TL"), CARRIER), 201)
        carrier_b = validate_success(api.create_carrier(
            create_carrier_payload(name="Best TL", scac="BEST", mode="TL"), CARRIER), 201)
        validate_success(api.create_contract_rate(create_contract_rate_payload(
            carrier_id=carrier_a["id"], base_rate_per_mile_cents=250,
            min_charge_cents=50000, fuel_surcharge_pct=0.15), CARRIER), 201)
        validate_success(api.create_contract_rate(create_contract_rate_payload(
            carrier_id=carrier_b["id"], base_rate_per_mile_cents=200,
            min_charge_cents=80000, fuel_surcharge_pct=0.20), CARRIER), 201)
        order = validate_success(api.create_order(create_order_payload(), SHIPPER), 201)
        ship = validate_success(api.create_shipment(
            create_shipment_payload(order_id=order["id"], distance_miles=300, weight_lbs=6000),
            SHIPPER), 201)
        tender = validate_success(api.create_tender(ship["id"], {"tender_minute": 100}, SHIPPER), 201)
        assert tender["offered_rate_cents"] == 86250
        assert tender["carrier_id"] == carrier_a["id"]


class TestQuotedCostFloorBeforeFuel:
    """Order-of-operations: min-charge floor applied to linehaul BEFORE fuel."""

    def test_offered_rate_floors_linehaul_before_fuel(self, api):
        """PRD §3.5: "first the linehaul as the larger of the per-mile rate times
        the shipment distance and the minimum charge floor; then the fuel as that
        floored linehaul times the fuel surcharge fraction, rounded half up to
        whole cents"
        PRD §3.5: "The floor is applied to the linehaul before fuel is computed;
        computing fuel before flooring would diverge and is incorrect."

        Design: Difficulty/combinatorial_formula/quoted_cost_min_charge_floor_before_fuel_mode_b
        """
        carrier = validate_success(api.create_carrier(
            create_carrier_payload(name="Floor TL", scac="FLOR", mode="TL"), CARRIER), 201)
        validate_success(api.create_contract_rate(create_contract_rate_payload(
            carrier_id=carrier["id"], base_rate_per_mile_cents=100,
            min_charge_cents=25000, fuel_surcharge_pct=0.125), CARRIER), 201)
        order = validate_success(api.create_order(
            create_order_payload(customer_ref="C2", weight_lbs=8000, declared_value_cents=50000), SHIPPER), 201)
        ship = validate_success(api.create_shipment(
            create_shipment_payload(order_id=order["id"], distance_miles=100, weight_lbs=4000),
            SHIPPER), 201)
        tender = validate_success(api.create_tender(ship["id"], {"tender_minute": 100}, SHIPPER), 201)
        assert tender["offered_rate_cents"] == 28125

    def test_quoted_cost_adds_flat_accessorial_reserve_at_accept(self, api):
        """PRD §3.5: "then a flat provisional accessorial reserve of 5000 cents;
        and finally the quoted cost as the sum of linehaul, fuel, and that
        5000-cent reserve."

        Design: Difficulty/combinatorial_formula/quoted_cost_min_charge_floor_before_fuel_mode_b
        """
        carrier = validate_success(api.create_carrier(
            create_carrier_payload(name="Floor TL", scac="FLOR", mode="TL"), CARRIER), 201)
        validate_success(api.create_contract_rate(create_contract_rate_payload(
            carrier_id=carrier["id"], base_rate_per_mile_cents=100,
            min_charge_cents=25000, fuel_surcharge_pct=0.125), CARRIER), 201)
        order = validate_success(api.create_order(
            create_order_payload(customer_ref="C2", weight_lbs=8000, declared_value_cents=50000), SHIPPER), 201)
        ship = validate_success(api.create_shipment(
            create_shipment_payload(order_id=order["id"], distance_miles=100, weight_lbs=4000),
            SHIPPER), 201)
        tender = validate_success(api.create_tender(ship["id"], {"tender_minute": 100}, SHIPPER), 201)
        validate_success(api.accept_tender(tender["id"], CARRIER), 200)
        ship_after = validate_success(api.get_shipment(ship["id"], SHIPPER), 200)
        assert ship_after["quoted_cost_cents"] == 33125


class TestShipmentParallelDimensions:
    """Shipment carries tender_status and execution_status independently."""

    def test_booking_advances_tender_status_leaving_execution_pending(self, api):
        """PRD §3.5: "Acceptance moves the tender `OFFERED → ACCEPTED` and books the
        shipment, advancing its `tender_status` from `TENDERED` to `BOOKED`."
        PRD §3.3: "These two dimensions advance in parallel and are independent of
        one another up until cancellation."

        Design: Difficulty/non_linear_state_machine/shipment_parallel_tender_and_execution_dimensions
        """
        ctx = setup_tendered_shipment()
        validate_success(api.accept_tender(ctx["tender"]["id"], CARRIER), 200)
        ship = validate_success(api.get_shipment(ctx["shipment"]["id"], SHIPPER), 200)
        assert ship["tender_status"] == "BOOKED"
        assert ship["execution_status"] == "PENDING"

    def test_tendering_advances_tender_status_only(self, api):
        """PRD §3.4: "The tender is created in the `OFFERED` state, and creating it
        automatically advances the shipment's `tender_status` from `UNTENDERED` to
        `TENDERED`."

        Design: Difficulty/non_linear_state_machine/shipment_parallel_tender_and_execution_dimensions
        """
        ctx = setup_tendered_shipment()
        ship = validate_success(api.get_shipment(ctx["shipment"]["id"], SHIPPER), 200)
        assert ship["tender_status"] == "TENDERED"
        assert ship["execution_status"] == "PENDING"


class TestTenderDeclineRevert:
    """Decline branch reverts the shipment's tender_status back to UNTENDERED."""

    def test_decline_reverts_shipment_to_untendered(self, api):
        """PRD §3.5: "Declining moves the tender `OFFERED → DECLINED` and expiring
        moves it `OFFERED → EXPIRED`. Both carry the same side effect: the
        shipment's `tender_status` reverts from `TENDERED` to `UNTENDERED`, making
        it re-tenderable."

        Design: Difficulty/non_linear_state_machine/tender_branch_with_revert_offered_to_untendered
        """
        ctx = setup_tendered_shipment()
        tender = validate_success(api.decline_tender(ctx["tender"]["id"], CARRIER), 200)
        assert tender["status"] == "DECLINED"
        ship = validate_success(api.get_shipment(ctx["shipment"]["id"], SHIPPER), 200)
        assert ship["tender_status"] == "UNTENDERED"

    def test_reverted_shipment_carries_no_carrier_assignment(self, api):
        """PRD §3.5: "When a shipment is reverted this way it carries no carrier
        assignment — its `assigned_carrier_id` and `quoted_cost_cents` remain null
        until a future tender is accepted."

        Design: Difficulty/non_linear_state_machine/tender_branch_with_revert_offered_to_untendered
        """
        ctx = setup_tendered_shipment()
        validate_success(api.decline_tender(ctx["tender"]["id"], CARRIER), 200)
        ship = validate_success(api.get_shipment(ctx["shipment"]["id"], SHIPPER), 200)
        assert ship["assigned_carrier_id"] is None
        assert ship["quoted_cost_cents"] is None


def test_no_eligible_carrier_on_tender_rejected(api):
    """PRD §3.4: "If the candidate set is empty, the tender create is rejected
    with `ERR_NO_ELIGIBLE_CARRIER`."

    Design: Corner/validations/no_eligible_carrier_on_tender_rejected
    """
    setup_carrier_rate(origin_zone="Z1", dest_zone="Z2")
    order = validate_success(api.create_order(
        create_order_payload(origin_zone="Z3", dest_zone="Z4"), SHIPPER), 201)
    ship = validate_success(api.create_shipment(
        create_shipment_payload(order_id=order["id"]), SHIPPER), 201)
    resp = api.create_tender(ship["id"], {"tender_minute": 100}, SHIPPER)
    validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_CARRIER.value)


def test_suspended_carrier_excluded_from_rate_shop(api):
    """PRD §3.1: "A suspended carrier is excluded from rate-shop consideration but
    is otherwise untouched."
    PRD §3.4: "the rate's carrier is `ACTIVE`; and that carrier's mode equals the
    shipment's mode."

    Design: Corner/validations/suspended_carrier_excluded_from_rate_shop
    """
    carrier, _ = setup_carrier_rate()
    validate_success(api.suspend_carrier(carrier["id"], CARRIER), 200)
    order = validate_success(api.create_order(create_order_payload(), SHIPPER), 201)
    ship = validate_success(api.create_shipment(
        create_shipment_payload(order_id=order["id"]), SHIPPER), 201)
    resp = api.create_tender(ship["id"], {"tender_minute": 100}, SHIPPER)
    validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_CARRIER.value)


def test_rate_window_excludes_out_of_window_tender(api):
    """PRD §3.4: "the supplied `tender_minute` falls within the rate's closed
    effective window, meaning it is at least the effective start minute and at
    most the effective end minute"

    Design: Corner/validations/rate_window_excludes_out_of_window_tender
    """
    setup_carrier_rate(effective_start_minute=0, effective_end_minute=1000)
    order = validate_success(api.create_order(create_order_payload(), SHIPPER), 201)
    ship = validate_success(api.create_shipment(
        create_shipment_payload(order_id=order["id"], promised_eta_minute=5000), SHIPPER), 201)
    resp = api.create_tender(ship["id"], {"tender_minute": 2000}, SHIPPER)
    validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_CARRIER.value)


def test_accept_already_accepted_tender_returns_not_offered(api):
    """PRD §3.5: "Acceptance requires the tender to be `OFFERED` (otherwise
    `ERR_TENDER_NOT_OFFERED`)"

    Design: Corner/state_machines/accept_already_accepted_tender_returns_not_offered
    """
    ctx = setup_booked_shipment()
    resp = api.accept_tender(ctx["tender"]["id"], CARRIER)
    validate_error(resp, ApiErrorId.ERR_TENDER_NOT_OFFERED.value)


def test_immediate_visibility_quoted_cost_in_get_after_accept(api):
    """PRD §2.5: "Derived figures are reconciled immediately rather than lazily."
    PRD §3.5: "Booking writes the accepted tender's carrier onto the shipment's
    `assigned_carrier_id` and the accepted tender's rate onto the shipment's
    `contract_rate_id`, and it locks the provisional freight cost into
    `quoted_cost_cents`."

    Design: Corner/consistency_model/immediate_visibility_quoted_cost_in_accept_response
    """
    ctx = setup_booked_shipment()
    ship = validate_success(api.get_shipment(ctx["shipment"]["id"], SHIPPER), 200)
    assert ship["tender_status"] == "BOOKED"
    assert ship["quoted_cost_cents"] == 91250
    assert ship["assigned_carrier_id"] == ctx["carrier"]["id"]


def test_expire_tender_shared_by_shipperops(api):
    """PRD §3.5: "a `ShipperOps` or `CarrierOps` operator may expire one; either
    requires the tender to be `OFFERED` (otherwise `ERR_TENDER_NOT_OFFERED`)."
    PRD §3.5: "expiring moves it `OFFERED → EXPIRED`. Both carry the same side
    effect: the shipment's `tender_status` reverts from `TENDERED` to
    `UNTENDERED`, making it re-tenderable."

    Design: Corner/rbac/expire_tender_shared_by_shipperops_and_carrierops
    """
    ctx = setup_tendered_shipment()
    tender = validate_success(api.expire_tender(ctx["tender"]["id"], SHIPPER), 200)
    assert tender["status"] == "EXPIRED"
    ship = validate_success(api.get_shipment(ctx["shipment"]["id"], SHIPPER), 200)
    assert ship["tender_status"] == "UNTENDERED"


def test_list_tenders_filtered_by_shipment_id(api):
    """PRD §4 (routing): "GET | `/tms/shipments/{shipmentId}/tenders` | List
    tenders for a shipment". The tender created for the shipment is returned.
    PRD §3.4: "creating it automatically advances the shipment's `tender_status`
    from `UNTENDERED` to `TENDERED`."

    Design: Corner/endpoints/list_tenders_filtered_by_shipment_id
    """
    ctx = setup_tendered_shipment()
    resp = api.list_shipment_tenders(ctx["shipment"]["id"], SHIPPER)
    data = validate_success(resp, 200)
    assert isinstance(data, list) and len(data) == 1
    assert data[0]["id"] == ctx["tender"]["id"]
