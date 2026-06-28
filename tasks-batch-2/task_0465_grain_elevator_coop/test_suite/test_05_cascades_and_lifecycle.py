"""Settlement and shipment cascades: depth-3 depletion->receipt cancel, ticket bubble-up,
load-out draws, and the shipment-load state dependency on the storage position.

Queue A (Difficulty) — transitive_cascade (depth3), cross_entity_state_dependency
                       (shipment load requires position not depleted).
Queue B (Corner) — state_machines (ticket SETTLED_IN bubble-up),
                   endpoints (load draws bushels).
"""
from test_helpers import validate_success, validate_error, ApiErrorId, TEST_USERS
import test_helpers.fixtures as fx

MERCH = TEST_USERS["merchandiser_headers"]
OFFICER = TEST_USERS["settlement_officer_headers"]
SHIPPER = TEST_USERS["shipping_clerk_headers"]


def _full_draw_settlement_setup():
    """WAREHOUSE_RECEIPT 1000-bu CORN position with an ISSUED receipt, CASH net 4.70
    contract, and a DRAFT 1000-bu settlement. Returns (position, receipt, settlement)."""
    fx.reset_clock_default()
    commodity = fx.create_commodity()
    member = fx.create_member(name="Fay Farm")
    fx.create_price_board(commodity["id"])
    _, _, _graded, position = fx.create_graded_position(
        commodity_id=commodity["id"], member_id=member["id"],
        deposit_account_type="WAREHOUSE_RECEIPT", member_name="Fay Farm",
    )
    receipt = fx.issue_warehouse_receipt(position["id"])
    contract = fx.create_priced_cash_contract(member["id"], commodity["id"], contracted_bushels=1000)
    settlement = fx.create_draft_settlement(contract["id"], position["id"], priced_bushels=1000)
    return position, receipt, settlement


def test_settlement_post_depletes_position(api):
    """PRD §3.5: "the position's `bushels_available` is reduced by the priced bushels, and
    if that reaches 0 the position is carried to `DEPLETED`".

    Design: Difficulty/transitive_cascade/settlement_post_depletes_position_cancels_receipt_depth3
    """
    position, _receipt, settlement = _full_draw_settlement_setup()
    posted = fx.post_settlement(settlement["id"], position["id"])
    assert posted["status"] == "SETTLED"
    pos_after = validate_success(api.get_storage_position(position["id"], OFFICER))
    assert pos_after["bushels_available"] == 0
    assert pos_after["status"] == "DEPLETED"


def test_settlement_post_depletion_cascades_receipt_cancellation(api):
    """PRD §3.5: "if that reaches 0 the position is carried to `DEPLETED` (which in turn
    cancels any issued warehouse receipt on that position)". PRD §3.3: "cancellation
    happens automatically when the documented position is fully loaded out or otherwise
    depleted".

    Design: Difficulty/transitive_cascade/settlement_post_depletes_position_cancels_receipt_depth3
    """
    position, receipt, settlement = _full_draw_settlement_setup()
    fx.post_settlement(settlement["id"], position["id"])
    receipt_after = validate_success(api.get_warehouse_receipt(receipt["id"], MERCH))
    assert receipt_after["status"] == "CANCELLED", (
        "receipt must cascade to CANCELLED when its position is depleted"
    )


def _two_shipments_first_depletes_setup():
    """WAREHOUSE_RECEIPT 1000-bu CORN position; first shipment of all 1000 loaded (position
    DEPLETED); a second 0-bu shipment SCHEDULED on a non-overlapping window. Returns
    (position, second_shipment).

    Per PRD §3.7 the load checks are ordered: SCHEDULED state, then bushels <=
    bushels_available (ERR_INSUFFICIENT_BUSHELS), then position STORED/CHARGE_FROZEN
    (ERR_INVALID_STATE). A DEPLETED position necessarily has 0 bushels_available, so
    any positive load quantity would trip the earlier ERR_INSUFFICIENT_BUSHELS gate;
    the second shipment requests 0 bushels (0 <= 0 passes the bushels gate) to isolate
    and exercise the DEPLETED-position ERR_INVALID_STATE rule this test targets."""
    fx.reset_clock_default()
    commodity = fx.create_commodity()
    member = fx.create_member(name="Lou Farm")
    bay = fx.create_loadout_bay(name="BAY-1")
    _, _, _graded, position = fx.create_graded_position(
        commodity_id=commodity["id"], member_id=member["id"],
        deposit_account_type="WAREHOUSE_RECEIPT", member_name="Lou Farm",
    )
    sh1 = fx.schedule_shipment(
        commodity["id"], position["id"], bay["id"], bushels=1000,
        bay_window_start="2026-02-01T08:00:00Z", bay_window_end="2026-02-01T10:00:00Z",
    )
    fx.load_shipment(sh1["id"])
    sh2 = fx.schedule_shipment(
        commodity["id"], position["id"], bay["id"], bushels=0,
        bay_window_start="2026-02-01T12:00:00Z", bay_window_end="2026-02-01T13:00:00Z",
    )
    return position, sh2


def test_shipment_load_against_depleted_position_returns_invalid_state(api):
    """PRD §3.7: "the position must be in `STORED` or `CHARGE_FROZEN` status — a
    `DEPLETED` or `VOIDED` position cannot be loaded from and yields `ERR_INVALID_STATE`."

    Design: Difficulty/cross_entity_state_dependency/shipment_load_requires_position_not_depleted_state
    """
    _position, sh2 = _two_shipments_first_depletes_setup()
    resp = api.load_shipment(sh2["id"], SHIPPER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_shipment_load_rejected_leaves_position_and_shipment_unchanged(api):
    """PRD §3.7: "a `DEPLETED` ... position cannot be loaded from and yields
    `ERR_INVALID_STATE`." PRD §3.5: "if that reaches 0 the position is carried to
    `DEPLETED`".

    Design: Difficulty/cross_entity_state_dependency/shipment_load_requires_position_not_depleted_state
    """
    position, sh2 = _two_shipments_first_depletes_setup()
    api.load_shipment(sh2["id"], SHIPPER)
    pos_after = validate_success(api.get_storage_position(position["id"], OFFICER))
    sh2_after = validate_success(api.get_shipment(sh2["id"], SHIPPER))
    assert pos_after["status"] == "DEPLETED"
    assert sh2_after["status"] == "SCHEDULED"


def test_first_settlement_bubbles_ticket_to_settled_in(api):
    """PRD §3.5: "if the position's owning scale ticket is still `GRADED`, it is advanced
    to `SETTLED_IN` (marking the grain accepted into the priced ledger)".

    Design: Corner/state_machines/scale_ticket_settled_in_bubbles_up_on_first_settlement
    """
    fx.reset_clock_default()
    commodity = fx.create_commodity()
    member = fx.create_member(name="BB Farm")
    fx.create_price_board(commodity["id"])
    _, _, graded, position = fx.create_graded_position(
        commodity_id=commodity["id"], member_id=member["id"], member_name="BB Farm",
    )
    contract = fx.create_priced_cash_contract(member["id"], commodity["id"], contracted_bushels=1000)
    settlement = fx.create_draft_settlement(contract["id"], position["id"], priced_bushels=600)
    fx.post_settlement(settlement["id"], position["id"])

    ticket_after = validate_success(api.get_scale_ticket(graded["id"], OFFICER))
    pos_after = validate_success(api.get_storage_position(position["id"], OFFICER))
    assert ticket_after["status"] == "SETTLED_IN"
    assert pos_after["bushels_available"] == 400.0
    assert pos_after["status"] == "STORED"


def test_bushels_conserved_grade_equals_available_plus_drawn(api):
    """PRD §3.5: "the position's `bushels_available` is reduced by the priced bushels".
    PRD §3.5: "the contract's `priced_bushels` is increased by the priced bushels".

    Design: Difficulty/compensating_invariant/bushels_conserved_grade_in_equals_drawn_plus_available
    """
    fx.reset_clock_default()
    commodity = fx.create_commodity()
    member = fx.create_member(name="Ona Farm")
    fx.create_price_board(commodity["id"])
    _, _, _graded, position = fx.create_graded_position(
        commodity_id=commodity["id"], member_id=member["id"], member_name="Ona Farm",
    )
    contract = fx.create_priced_cash_contract(member["id"], commodity["id"], contracted_bushels=1000)
    settlement = fx.create_draft_settlement(contract["id"], position["id"], priced_bushels=600)
    fx.post_settlement(settlement["id"], position["id"])

    pos_after = validate_success(api.get_storage_position(position["id"], OFFICER))
    contract_after = validate_success(api.get_contract(contract["id"], MERCH))
    assert pos_after["bushels"] == 1000.0, "deposited bushels must be unchanged by settlement"
    assert pos_after["bushels_available"] == 400.0
    assert contract_after["priced_bushels"] == 600
    # 1000 deposited == 400 available + 600 drawn — no bushel created or lost
    assert pos_after["bushels"] == pos_after["bushels_available"] + contract_after["priced_bushels"]


def test_bushels_invariant_deposited_unchanged_after_partial_settlement(api):
    """PRD §3.2: the graded position's `bushels` and `bushels_available` "are both set to
    the computed net dry bushels". PRD §3.5: "the position's `bushels_available` is reduced
    by the priced bushels".

    Design: Difficulty/compensating_invariant/bushels_conserved_grade_in_equals_drawn_plus_available
    """
    fx.reset_clock_default()
    commodity = fx.create_commodity()
    member = fx.create_member(name="Ona2 Farm")
    fx.create_price_board(commodity["id"])
    _, _, _graded, position = fx.create_graded_position(
        commodity_id=commodity["id"], member_id=member["id"], member_name="Ona2 Farm",
    )
    assert position["bushels"] == 1000.0
    assert position["bushels_available"] == 1000.0
    contract = fx.create_priced_cash_contract(member["id"], commodity["id"], contracted_bushels=1000)
    settlement = fx.create_draft_settlement(contract["id"], position["id"], priced_bushels=600)
    fx.post_settlement(settlement["id"], position["id"])
    pos_after = validate_success(api.get_storage_position(position["id"], OFFICER))
    assert pos_after["bushels"] == 1000.0, "deposited bushels must never change on draw-down"


def test_load_shipment_draws_bushels_from_position(api):
    """PRD §3.7: "On load, the position's `bushels_available` is reduced by the shipment's
    bushels". PRD §3.7: "Loading a scheduled shipment moves it from `SCHEDULED` to
    `LOADED`".

    Design: Corner/endpoints/load_shipment_draws_bushels_side_effect
    """
    fx.reset_clock_default()
    commodity = fx.create_commodity()
    member = fx.create_member(name="LL Farm")
    bay = fx.create_loadout_bay(name="BAY-4")
    _, _, _graded, position = fx.create_graded_position(
        commodity_id=commodity["id"], member_id=member["id"],
        deposit_account_type="WAREHOUSE_RECEIPT", member_name="LL Farm",
    )
    shipment = fx.schedule_shipment(
        commodity["id"], position["id"], bay["id"], bushels=400,
        bay_window_start="2026-02-01T08:00:00Z", bay_window_end="2026-02-01T10:00:00Z",
    )
    loaded = fx.load_shipment(shipment["id"])
    assert loaded["status"] == "LOADED"
    pos_after = validate_success(api.get_storage_position(position["id"], OFFICER))
    assert pos_after["bushels_available"] == 600.0
    assert pos_after["status"] == "STORED"
