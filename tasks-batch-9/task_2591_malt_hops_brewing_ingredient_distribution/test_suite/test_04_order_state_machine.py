"""Sales orders: the two independent dimensions and the confirm gate ordering."""
import pytest

from test_helpers import (
    add_contract_hop_line,
    add_malt_line,
    add_spot_hop_line,
    confirm_order,
    create_brewer,
    create_contract,
    create_malt_product,
    create_order,
    create_program,
    create_released_lot,
    create_variety,
    get_brewer,
    make_brewer_headers,
    pin_clock,
    set_credit_limit,
    validate_error,
    validate_success,
)

CREDIT_HOLD = {"decision": "HOLD", "decision_note": "awaiting updated financials"}
CREDIT_APPROVE = {"decision": "APPROVE", "decision_note": "financials received"}


@pytest.fixture
def spot_hop_order():
    """One 880 lb SPOT Citra line: exactly a pallet, still under the order minimum."""
    pin_clock()
    brewer = create_brewer(name="Twin Dimension Brewing",
                           credit_limit_cents=5000000, cold_chain_certified=True,
                           legacy_trailing_lbs=0)
    variety = create_variety()
    order = create_order(brewer["id"],
                         requested_ship_date="2026-09-20T00:00:00Z",
                         purchase_order_ref="PO-3001")
    line = add_spot_hop_line(order["id"], brewer["id"], variety["id"], 880)
    return {"brewer": brewer, "variety": variety, "order": order, "line": line}


def test_a_credit_hold_moves_only_the_credit_dimension_of_a_confirmed_order(
        api, spot_hop_order, credit_manager_headers):
    """The order's fulfillment dimension stays CONFIRMED while credit goes ON_HOLD.

    PRD §3.8: "`HOLD` moves `credit_status` `PENDING_REVIEW → ON_HOLD` or
    `APPROVED → ON_HOLD`, and additionally freezes the dock: every reefer load of
    this order in `STAGED` moves to `HELD`, releasing its `pallet_count` from its
    zone's `occupied_pallets`."

    Design: Difficulty/non_linear_state_machine/sales_order_parallel_credit_and_fulfillment_dimensions
    """
    world = spot_hop_order
    confirmed = confirm_order(world["order"]["id"], world["brewer"]["id"])
    assert confirmed["fulfillment_status"] == "CONFIRMED", (
        f"confirm moves the fulfillment dimension, got {confirmed['fulfillment_status']}")
    assert confirmed["credit_status"] == "PENDING_REVIEW", (
        "a fresh order's credit dimension is untouched by confirmation, got "
        f"{confirmed['credit_status']}")
    assert confirmed["total_cents"] == 95380, (
        f"44880 + 43000 freight + 7500 surcharge = 95380, got {confirmed['total_cents']}")
    assert confirmed["freight_cents"] == 43000, (
        "the 25,000 TIER_1 minimum plus the 18,000 reefer surcharge, got "
        f"{confirmed['freight_cents']}")
    assert confirmed["pallet_break_fee_cents"] == 0, (
        f"880 lbs is exactly one pallet, got {confirmed['pallet_break_fee_cents']}")
    assert confirmed["small_order_surcharge_cents"] == 7500, (
        f"880 lbs is under the 2,000 lb minimum, got "
        f"{confirmed['small_order_surcharge_cents']}")

    held = validate_success(api.record_credit_decision(
        world["order"]["id"], CREDIT_HOLD, credit_manager_headers))
    assert held["credit_status"] == "ON_HOLD", (
        f"the credit dimension moves to ON_HOLD, got {held['credit_status']}")
    assert held["fulfillment_status"] == "CONFIRMED", (
        "the fulfillment dimension must not move with the credit decision, got "
        f"{held['fulfillment_status']}")


def test_pick_is_refused_while_the_order_credit_dimension_is_on_hold(
        api, spot_hop_order, credit_manager_headers, warehouse_operator_headers):
    """Only CONFIRMED plus APPROVED admits a pick, and the refusal moves nothing.

    PRD §3.8: "the order's own `credit_status` must be `APPROVED`, otherwise
    `ERR_ORDER_CREDIT_NOT_APPROVED`."

    Design: Difficulty/non_linear_state_machine/sales_order_parallel_credit_and_fulfillment_dimensions
    """
    world = spot_hop_order
    confirm_order(world["order"]["id"], world["brewer"]["id"])
    validate_success(api.record_credit_decision(
        world["order"]["id"], CREDIT_HOLD, credit_manager_headers))

    blocked = api.pick_order(world["order"]["id"], warehouse_operator_headers)
    validate_error(blocked, "ERR_ORDER_CREDIT_NOT_APPROVED", expected_status=402)

    order = validate_success(api.get_sales_order(world["order"]["id"],
                                                 warehouse_operator_headers))
    assert order["fulfillment_status"] == "CONFIRMED", (
        f"the refused pick must not advance fulfillment, got {order['fulfillment_status']}")
    assert order["credit_status"] == "ON_HOLD", (
        f"the refused pick must not touch credit either, got {order['credit_status']}")


def test_credit_can_cycle_back_into_approved_and_then_the_pick_succeeds(
        api, spot_hop_order, credit_manager_headers, warehouse_operator_headers):
    """ON_HOLD → APPROVED re-opens the dock without the fulfillment dimension moving.

    PRD §3.8: "`APPROVE` moves `credit_status` `PENDING_REVIEW → APPROVED` or
    `ON_HOLD → APPROVED`, and requires that the owning brewery's own
    `credit_status` is not `HOLD`"

    Design: Difficulty/non_linear_state_machine/sales_order_parallel_credit_and_fulfillment_dimensions
    """
    world = spot_hop_order
    confirm_order(world["order"]["id"], world["brewer"]["id"])
    validate_success(api.record_credit_decision(
        world["order"]["id"], CREDIT_HOLD, credit_manager_headers))
    approved = validate_success(api.record_credit_decision(
        world["order"]["id"], CREDIT_APPROVE, credit_manager_headers))
    assert approved["credit_status"] == "APPROVED", (
        f"ON_HOLD cycles back into APPROVED, got {approved['credit_status']}")
    assert approved["fulfillment_status"] == "CONFIRMED", (
        f"fulfillment still has not moved, got {approved['fulfillment_status']}")

    picked = validate_success(api.pick_order(world["order"]["id"],
                                             warehouse_operator_headers))
    assert picked["fulfillment_status"] == "PICKED", (
        f"the combined state now admits the pick, got {picked['fulfillment_status']}")
    assert picked["credit_status"] == "APPROVED", (
        f"picking leaves the credit dimension alone, got {picked['credit_status']}")

    variety = validate_success(api.get_hop_variety(world["variety"]["id"],
                                                   warehouse_operator_headers))
    assert variety["available_spot_lbs"] == 20000 - 880, (
        f"confirmation drew 880 lbs off the floor once, got "
        f"{variety['available_spot_lbs']}")


@pytest.fixture
def confirmed_order_on_a_held_brewer():
    """A CONFIRMED 168,380-cent order whose brewer is squeezed onto HOLD afterwards."""
    pin_clock()
    brewer = create_brewer(name="Squeeze Play Brewing", credit_limit_cents=200000,
                           cold_chain_certified=True, legacy_trailing_lbs=0)
    variety = create_variety()
    product = create_malt_product()
    lot = create_released_lot(product["id"], quantity_lbs=20000)
    order = create_order(brewer["id"],
                         requested_ship_date="2026-09-20T00:00:00Z",
                         purchase_order_ref="PO-7001")
    add_malt_line(order["id"], brewer["id"], lot["id"], 1000)
    add_spot_hop_line(order["id"], brewer["id"], variety["id"], 880)
    order = confirm_order(order["id"], brewer["id"])
    brewer = set_credit_limit(brewer["id"], 100000)
    return {"brewer": brewer, "variety": variety, "lot": lot, "order": order}


def test_re_confirming_a_confirmed_order_reports_the_state_error_not_the_credit_hold(
        api, confirmed_order_on_a_held_brewer):
    """Both gates would refuse, and the state band is evaluated first.

    PRD §2.8: "5. **State preconditions on the target resource** (priorities
    12–18): whether the requested transition is declared from the target's
    current status."

    Design: Difficulty/priority_pair_validation_conflict/state_precondition_outranks_fiscal_check_on_re_confirm
    """
    world = confirmed_order_on_a_held_brewer
    assert world["order"]["total_cents"] == 168380, (
        f"the setup order must total 168380, got {world['order']['total_cents']}")
    assert world["brewer"]["credit_status"] == "HOLD", (
        f"the setup brewer must be on hold, got {world['brewer']['credit_status']}")
    assert world["brewer"]["credit_utilization_pct"] == pytest.approx(168.38, abs=0.005), (
        "168380 of exposure over a 100000 limit, got "
        f"{world['brewer']['credit_utilization_pct']}")

    response = api.confirm_order(world["order"]["id"],
                                 make_brewer_headers(world["brewer"]["id"]))
    error = validate_error(response, "ERR_INVALID_ORDER_STATE",
                          expected_status=409)
    assert error["error_id"] != "ERR_BREWER_CREDIT_HOLD", (
        "the fiscal gate at the bottom of the precedence order must not win")
    assert response.status_code != 402, (
        "402 is the credit-hold status and must not replace the 409")


def test_the_refused_re_confirm_commits_no_poundage_a_second_time(
        api, confirmed_order_on_a_held_brewer, warehouse_operator_headers):
    """A rejected confirmation leaves inventory exactly as the first one left it.

    PRD §2.8: "When one request violates several rules, the response carries the
    error belonging to the **lowest** priority number, and only that error."

    Design: Difficulty/priority_pair_validation_conflict/state_precondition_outranks_fiscal_check_on_re_confirm
    """
    world = confirmed_order_on_a_held_brewer
    validate_error(api.confirm_order(world["order"]["id"],
                                     make_brewer_headers(world["brewer"]["id"])),
                   "ERR_INVALID_ORDER_STATE", expected_status=409)

    order = validate_success(api.get_sales_order(world["order"]["id"],
                                                 warehouse_operator_headers))
    assert order["fulfillment_status"] == "CONFIRMED", (
        f"the order stays where it was, got {order['fulfillment_status']}")
    assert order["total_cents"] == 168380, (
        f"the total was not recomputed, got {order['total_cents']}")

    variety = validate_success(api.get_hop_variety(world["variety"]["id"],
                                                   warehouse_operator_headers))
    assert variety["available_spot_lbs"] == 19120, (
        f"the 880 lb spot hold was drawn once, got {variety['available_spot_lbs']}")
    lot = validate_success(api.get_malt_lot(world["lot"]["id"],
                                            warehouse_operator_headers))
    assert lot["committed_lbs"] == 1000, (
        f"the malt commitment was booked once, got {lot['committed_lbs']}")

    brewer = get_brewer(world["brewer"]["id"])
    assert brewer["credit_exposure_cents"] == 168380, (
        f"exposure is unchanged by the refusal, got {brewer['credit_exposure_cents']}")


@pytest.fixture
def uncertified_brewer_over_contract():
    """An 880 lb line on a 500 lb contract, for a brewer with no cold-chain ticket."""
    pin_clock()
    brewer = create_brewer(name="Ambient Only Brewing",
                           credit_limit_cents=5000000,
                           cold_chain_certified=False, legacy_trailing_lbs=0)
    program = create_program(crop_year=2026)
    variety = create_variety()
    contract = create_contract(brewer["id"], variety["id"], program["id"],
                               contracted_lbs=500, price_per_lb_cents=285.50)
    order = create_order(brewer["id"],
                         requested_ship_date="2026-10-15T00:00:00Z",
                         purchase_order_ref="PO-8001")
    line = add_contract_hop_line(order["id"], brewer["id"], variety["id"],
                                 contract["id"], 880)
    return {"brewer": brewer, "variety": variety, "contract": contract,
            "order": order, "line": line}


def test_the_cold_chain_gate_is_reported_ahead_of_the_contract_volume_gate(
        api, uncertified_brewer_over_contract):
    """Both refusals are 422, and the safety gate is the earlier one.

    PRD §3.8: "Beyond the `DRAFT` requirement it imposes, in ascending
    precedence, a cold-chain gate, the delivery-window gate, the line-count gate,
    three volume gates and two fiscal gates."

    Design: Difficulty/priority_pair_validation_conflict/safety_certification_outranks_contract_volume_constraint
    """
    world = uncertified_brewer_over_contract
    assert world["line"]["cold_chain_required"] is True, (
        "the Citra line must require refrigeration, got "
        f"{world['line']['cold_chain_required']}")
    assert world["contract"]["remaining_lbs"] == 500, (
        f"the contract holds only 500 lbs, got {world['contract']['remaining_lbs']}")

    response = api.confirm_order(world["order"]["id"],
                                 make_brewer_headers(world["brewer"]["id"]))
    error = validate_error(response, "ERR_COLD_CHAIN_NOT_CERTIFIED",
                          expected_status=422)
    assert error["error_id"] != "ERR_CONTRACT_VOLUME_EXHAUSTED", (
        "the volume gate sits below the cold-chain gate even though both are 422")


def test_the_refused_confirm_leaves_the_order_in_draft_with_no_fees_priced(
        api, uncertified_brewer_over_contract, allocation_manager_headers):
    """Nothing is committed and no fee variant is stamped by a refused confirmation.

    PRD §3.8: "When the order's `requires_cold_chain` is true the owning
    brewery's `cold_chain_certified` must be true, otherwise
    `ERR_COLD_CHAIN_NOT_CERTIFIED`."

    Design: Difficulty/priority_pair_validation_conflict/safety_certification_outranks_contract_volume_constraint
    """
    world = uncertified_brewer_over_contract
    validate_error(api.confirm_order(world["order"]["id"],
                                     make_brewer_headers(world["brewer"]["id"])),
                   "ERR_COLD_CHAIN_NOT_CERTIFIED", expected_status=422)

    order = validate_success(api.get_sales_order(
        world["order"]["id"], make_brewer_headers(world["brewer"]["id"])))
    assert order["fulfillment_status"] == "DRAFT", (
        f"the order stays in DRAFT, got {order['fulfillment_status']}")
    assert order["requires_cold_chain"] is True, (
        f"the order still needs a reefer, got {order['requires_cold_chain']}")
    assert order["total_cents"] == 0, (
        f"no fee assessment ran, got {order['total_cents']}")
    assert order["fee_variant"] is None, (
        f"fee_variant stays null before a successful confirm, got {order['fee_variant']}")

    contract = validate_success(api.get_hop_contract(world["contract"]["id"],
                                                     allocation_manager_headers))
    assert contract["committed_lbs"] == 0 and contract["remaining_lbs"] == 500, (
        "the refused confirm committed nothing, got committed "
        f"{contract['committed_lbs']} remaining {contract['remaining_lbs']}")
