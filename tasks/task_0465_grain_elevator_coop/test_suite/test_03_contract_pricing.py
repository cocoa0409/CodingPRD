"""Contract pricing: BASIS vs HTA divergence, pinned fixing-time evaluation order,
and fix-price / cancel validations.

Queue A (Difficulty) — dual_variant_calc (basis vs hta), combinatorial_formula (mode_c).
Queue B (Corner) — validations (no current price, leg already fixed, has settlements).
"""
import pytest

from test_helpers import validate_success, validate_error, ApiErrorId, TEST_USERS
import test_helpers.fixtures as fx

MERCH = TEST_USERS["merchandiser_headers"]


def _setup_basis_and_hta(api):
    """CORN; board A (4.50/-0.30) current; BASIS(basis_leg -0.30) + HTA(futures_leg 4.50);
    then board B (4.80/-0.10) current; fix BASIS. Returns (basis_id, hta_id)."""
    commodity = fx.create_commodity()
    member = fx.create_member(name="Beth Farm")
    fx.create_price_board(commodity["id"], futures_price=4.50, cash_basis=-0.30)
    basis = fx.create_contract(member["id"], commodity["id"], "BASIS", contracted_bushels=500, basis_leg=-0.30)
    hta = fx.create_contract(member["id"], commodity["id"], "HTA", contracted_bushels=500, futures_leg=4.50)
    fx.create_price_board(commodity["id"], futures_price=4.80, cash_basis=-0.10)
    return basis["id"], hta["id"]


def test_basis_contract_late_futures_leg_taken_at_fixing(api):
    """PRD §3.4: "For a `BASIS` contract, fixing sets the `futures_leg` from the board's
    futures price (the basis leg was locked at create); the member was exposed to futures
    moves, and the late leg is the futures leg taken from the board at fixing." PRD §3.4:
    "the `net_price` is then computed as the futures leg plus the basis leg, carried to 4
    decimal places".

    Design: Difficulty/dual_variant_calc/contract_net_price_basis_vs_hta_diverge_on_same_board_history
    """
    basis_id, _hta_id = _setup_basis_and_hta(api)
    priced = validate_success(api.fix_price(basis_id, MERCH))
    assert priced["status"] == "PRICED"
    assert priced["futures_leg"] == pytest.approx(4.80, abs=1e-4)
    assert priced["basis_leg"] == pytest.approx(-0.30, abs=1e-4)
    assert priced["net_price"] == pytest.approx(4.5000, abs=1e-4)


def test_hta_contract_late_basis_leg_diverges_from_basis(api):
    """PRD §3.4: "For an `HTA` contract, fixing sets the `basis_leg` from the board's cash
    basis (the futures leg was locked at create); the member was exposed to basis moves,
    and the late leg is the basis leg taken from the board at fixing." PRD §3.4: "Because
    a basis contract takes its late leg from futures while an HTA contract takes its late
    leg from basis, the very same board history applied to a `BASIS` contract and to an
    `HTA` contract produces different net prices."

    Design: Difficulty/dual_variant_calc/contract_net_price_basis_vs_hta_diverge_on_same_board_history
    """
    basis_id, hta_id = _setup_basis_and_hta(api)
    basis_priced = validate_success(api.fix_price(basis_id, MERCH))
    hta_priced = validate_success(api.fix_price(hta_id, MERCH))
    assert hta_priced["futures_leg"] == pytest.approx(4.50, abs=1e-4)
    assert hta_priced["basis_leg"] == pytest.approx(-0.10, abs=1e-4)
    assert hta_priced["net_price"] == pytest.approx(4.4000, abs=1e-4)
    # same board history -> different net price by exactly 0.10
    assert basis_priced["net_price"] - hta_priced["net_price"] == pytest.approx(0.1000, abs=1e-4)


def test_basis_late_leg_read_from_current_board_at_fixing_not_create(api):
    """PRD §3.4: "Fix-price reads the missing leg(s) from the current price board for the
    contract's commodity". PRD §3.1: "posting a new board for a commodity makes it the
    current board and supersedes whatever board was current before."

    Design: Difficulty/combinatorial_formula/contract_net_price_evaluation_order_pinned_mode_c
    """
    commodity = fx.create_commodity()
    member = fx.create_member(name="Dale Farm")
    fx.create_price_board(commodity["id"], futures_price=4.50, cash_basis=-0.30)  # board A
    contract = fx.create_contract(
        member["id"], commodity["id"], "BASIS", contracted_bushels=500, basis_leg=-0.30
    )
    fx.create_price_board(commodity["id"], futures_price=4.80, cash_basis=-0.10)  # board B current
    priced = validate_success(api.fix_price(contract["id"], MERCH))
    assert priced["futures_leg"] == pytest.approx(4.80, abs=1e-4), (
        "late futures_leg must be read from current board B at fixing, not board A at create"
    )


def test_basis_pinned_evaluation_order_yields_net_and_priced_status(api):
    """PRD §3.4: "the `net_price` is then computed as the futures leg plus the basis leg,
    carried to 4 decimal places, and the contract becomes `PRICED`."

    Design: Difficulty/combinatorial_formula/contract_net_price_evaluation_order_pinned_mode_c
    """
    commodity = fx.create_commodity()
    member = fx.create_member(name="Dale2 Farm")
    fx.create_price_board(commodity["id"], futures_price=4.50, cash_basis=-0.30)
    contract = fx.create_contract(
        member["id"], commodity["id"], "BASIS", contracted_bushels=500, basis_leg=-0.30
    )
    fx.create_price_board(commodity["id"], futures_price=4.80, cash_basis=-0.10)
    priced = validate_success(api.fix_price(contract["id"], MERCH))
    assert priced["basis_leg"] == pytest.approx(-0.30, abs=1e-4)
    assert priced["net_price"] == pytest.approx(4.5000, abs=1e-4)
    assert priced["status"] == "PRICED"


def test_fix_price_no_current_board_returns_no_current_price(api):
    """PRD §3.4: "Fix-price reads the missing leg(s) from the current price board for the
    contract's commodity, so a current board must exist or the action is rejected with
    `ERR_NO_CURRENT_PRICE`."

    Design: Corner/validations/fix_price_no_current_board_returns_no_current_price
    """
    commodity = fx.create_commodity()
    member = fx.create_member(name="HH Farm")
    contract = fx.create_open_cash_contract(member["id"], commodity["id"], contracted_bushels=1000)
    resp = api.fix_price(contract["id"], MERCH)
    validate_error(resp, ApiErrorId.ERR_NO_CURRENT_PRICE.value)
    after = validate_success(api.get_contract(contract["id"], MERCH))
    assert after["status"] == "OPEN"


def test_fix_price_forward_both_legs_fixed_returns_leg_already_fixed(api):
    """PRD §3.4: "Only the open leg for the contract's type may be fixed, and a leg already
    set cannot be fixed again — a double-fix is rejected with `ERR_LEG_ALREADY_FIXED`."
    PRD §3.4: "A `FORWARD` contract requires both legs at create".

    Design: Corner/validations/fix_price_basis_leg_already_fixed_returns_leg_already_fixed
    """
    commodity = fx.create_commodity()
    fx.create_price_board(commodity["id"])
    member = fx.create_member(name="II Farm")
    contract = fx.create_contract(
        member["id"], commodity["id"], "FORWARD", contracted_bushels=1000,
        futures_leg=4.55, basis_leg=-0.20,
    )
    resp = api.fix_price(contract["id"], MERCH)
    validate_error(resp, ApiErrorId.ERR_LEG_ALREADY_FIXED.value)


def test_cancel_contract_with_settled_bushels_returns_has_settlements(api):
    """PRD §3.4: "Cancellation requires that the contract's `priced_bushels` be exactly 0
    — that no settled settlement has been applied. If applied settlement bushels exist,
    the cancel is refused with `ERR_CONTRACT_HAS_SETTLEMENTS`."

    Design: Corner/validations/cancel_contract_with_settled_bushels_returns_has_settlements
    """
    commodity = fx.create_commodity()
    fx.create_price_board(commodity["id"])
    member = fx.create_member(name="JJ Farm")
    _, _, _graded, position = fx.create_graded_position(
        commodity_id=commodity["id"], member_id=member["id"]
    )
    contract = fx.create_priced_cash_contract(member["id"], commodity["id"], contracted_bushels=1000)
    settlement = fx.create_draft_settlement(contract["id"], position["id"], priced_bushels=600)
    fx.post_settlement(settlement["id"], position["id"])

    before = validate_success(api.get_contract(contract["id"], MERCH))
    assert before["status"] == "PRICED" and before["priced_bushels"] == 600
    resp = api.cancel_contract(contract["id"], MERCH)
    validate_error(resp, ApiErrorId.ERR_CONTRACT_HAS_SETTLEMENTS.value)
