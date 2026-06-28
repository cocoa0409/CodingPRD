"""Storage charges: ESTIMATE vs ACTUAL divergence on a frozen position, warehouse-receipt
flat-fee, grace-period edge, and computed settlement reads.

Queue A (Difficulty) — dual_variant_calc (storage_charge estimate vs actual).
Queue B (Corner) — calculations (warehouse-receipt zero, within-grace zero),
                    endpoints (get settlement computed read).
"""
import pytest

from test_helpers import validate_success, get_success_data, TEST_USERS
import test_helpers.fixtures as fx

MERCH = TEST_USERS["merchandiser_headers"]
OFFICER = TEST_USERS["settlement_officer_headers"]


def _setup_frozen_position_with_priced_contract():
    """Frozen-20-days DELAYED_PRICE 1000-bu CORN position, CASH net 4.70, clock at
    2026-04-01 (60 calendar days past the 2026-01-31 grace end). Returns (contract, pos)."""
    fx.reset_clock_default()
    commodity = fx.create_commodity()
    member = fx.create_member(name="Aaron Farm")
    fx.create_price_board(commodity["id"], futures_price=4.80, cash_basis=-0.10)
    _, _, _graded, position = fx.create_graded_position(
        commodity_id=commodity["id"], member_id=member["id"], member_name="Aaron Farm",
    )
    fx.api_client.freeze_charge(position["id"], MERCH)
    fx.set_clock("2026-01-21T00:00:00Z")
    fx.api_client.unfreeze_charge(position["id"], MERCH)
    contract = fx.create_priced_cash_contract(member["id"], commodity["id"], contracted_bushels=1000)
    fx.set_clock("2026-04-01T00:00:00Z")
    return contract, position


def test_storage_charge_estimate_charges_full_span_ignoring_frozen(api):
    """PRD §3.6: "The **estimate** variant is forward-looking: it charges the full
    grace-end-to-today span and ignores frozen days entirely, as if the position were
    never paused — its chargeable days equal the chargeable calendar days." PRD §3.6: "the
    `storage_charge_dollars` are the settlement's priced bushels multiplied by the rate
    multiplied by the chargeable days, rounded to 2 decimal places."

    Design: Difficulty/dual_variant_calc/storage_charge_estimate_vs_actual_diverge_on_frozen_position
    """
    contract, position = _setup_frozen_position_with_priced_contract()
    settlement = fx.create_draft_settlement(
        contract["id"], position["id"], priced_bushels=600, storage_basis="ESTIMATE"
    )
    data = validate_success(api.get_settlement(settlement["id"], OFFICER))
    # 600 * 0.0005 * 60 days = 18.00
    assert data["storage_charge_dollars"] == pytest.approx(18.00, abs=0.01)
    assert data["gross_proceeds_dollars"] == pytest.approx(2820.00, abs=0.01)


def test_storage_charge_actual_subtracts_frozen_days_diverges_from_estimate(api):
    """PRD §3.6: "The **actual** variant is chronological: it subtracts the position's
    accumulated `frozen_days` from the chargeable calendar days (never going below zero)
    — its chargeable days equal the chargeable calendar days minus the frozen days,
    floored at zero." PRD §3.6: "For a position that was frozen for part of its storage
    span, the estimate and actual variants therefore produce different charges".

    Design: Difficulty/dual_variant_calc/storage_charge_estimate_vs_actual_diverge_on_frozen_position
    """
    contract, position = _setup_frozen_position_with_priced_contract()
    est = fx.create_draft_settlement(
        contract["id"], position["id"], priced_bushels=600, storage_basis="ESTIMATE"
    )
    act = fx.create_draft_settlement(
        contract["id"], position["id"], priced_bushels=600, storage_basis="ACTUAL"
    )
    est_data = validate_success(api.get_settlement(est["id"], OFFICER))
    act_data = validate_success(api.get_settlement(act["id"], OFFICER))
    # ACTUAL: 600 * 0.0005 * (60-20) = 12.00
    assert act_data["storage_charge_dollars"] == pytest.approx(12.00, abs=0.01)
    assert est_data["storage_charge_dollars"] - act_data["storage_charge_dollars"] == pytest.approx(6.00, abs=0.01)


def test_warehouse_receipt_position_storage_charge_is_zero(api):
    """PRD §3.6: "For a `WAREHOUSE_RECEIPT` position there is no per-day accrual at all:
    the storage charge is 0, because warehouse-receipt grain is a flat-fee program."

    Design: Corner/calculations/warehouse_receipt_storage_charge_is_zero
    """
    fx.reset_clock_default()
    commodity = fx.create_commodity()
    member = fx.create_member(name="FF Farm")
    fx.create_price_board(commodity["id"])
    _, _, _graded, position = fx.create_graded_position(
        commodity_id=commodity["id"], member_id=member["id"],
        deposit_account_type="WAREHOUSE_RECEIPT", member_name="FF Farm",
    )
    contract = fx.create_priced_cash_contract(member["id"], commodity["id"], contracted_bushels=1000)
    fx.set_clock("2026-08-01T00:00:00Z")
    settlement = fx.create_draft_settlement(
        contract["id"], position["id"], priced_bushels=600, storage_basis="ACTUAL"
    )
    posted = fx.post_settlement(settlement["id"], position["id"])
    assert posted["storage_charge_dollars"] == pytest.approx(0.00, abs=0.01)
    assert posted["net_proceeds_dollars"] == pytest.approx(2820.00, abs=0.01)


def test_storage_charge_within_grace_period_is_zero(api):
    """PRD §3.6: "grain enjoys a grace period of 30 days from its storage start before any
    storage charge accrues." PRD §3.6: "The chargeable calendar days are the whole days
    from grace-end to today, but never less than zero (grain still inside its grace window
    accrues nothing)."

    Design: Corner/calculations/storage_charge_within_grace_period_is_zero_days
    """
    fx.reset_clock_default()
    commodity = fx.create_commodity()
    member = fx.create_member(name="GG Farm")
    fx.create_price_board(commodity["id"])
    _, _, _graded, position = fx.create_graded_position(
        commodity_id=commodity["id"], member_id=member["id"], member_name="GG Farm",
    )
    contract = fx.create_priced_cash_contract(member["id"], commodity["id"], contracted_bushels=1000)
    fx.set_clock("2026-01-21T00:00:00Z")  # day 20, within 30-day grace
    settlement = fx.create_draft_settlement(
        contract["id"], position["id"], priced_bushels=600, storage_basis="ACTUAL"
    )
    posted = fx.post_settlement(settlement["id"], position["id"])
    assert posted["storage_charge_dollars"] == pytest.approx(0.00, abs=0.01)
    assert posted["net_proceeds_dollars"] == pytest.approx(2820.00, abs=0.01)


def test_storage_position_freeze_unfreeze_cycle_status(api):
    """PRD §3.3: "A `Merchandiser` may pause storage accrual on a delayed-price position by
    freezing its charge, moving the position from `STORED` to `CHARGE_FROZEN`." PRD §3.3:
    "Unfreezing the charge moves the position from `CHARGE_FROZEN` back to `STORED`".

    Design: Difficulty/non_linear_state_machine/storage_position_stored_frozen_stored_cycle
    """
    fx.reset_clock_default()
    commodity = fx.create_commodity()
    member = fx.create_member(name="Ed Farm")
    _, _, _graded, position = fx.create_graded_position(
        commodity_id=commodity["id"], member_id=member["id"], member_name="Ed Farm",
    )
    frozen = validate_success(api.freeze_charge(position["id"], MERCH))
    assert frozen["status"] == "CHARGE_FROZEN"
    fx.set_clock("2026-01-21T00:00:00Z")
    unfrozen = validate_success(api.unfreeze_charge(position["id"], MERCH))
    assert unfrozen["status"] == "STORED"


def test_storage_position_unfreeze_banks_whole_frozen_days(api):
    """PRD §3.3: "the whole days the position spent frozen are added to its cumulative
    `frozen_days` counter, and accrual resumes." PRD §2.9: "the clock value at the moment
    a ticket is graded becomes that grain's `storage_start_date`".

    Design: Difficulty/non_linear_state_machine/storage_position_stored_frozen_stored_cycle
    """
    fx.reset_clock_default()
    commodity = fx.create_commodity()
    member = fx.create_member(name="Ed2 Farm")
    _, _, _graded, position = fx.create_graded_position(
        commodity_id=commodity["id"], member_id=member["id"], member_name="Ed2 Farm",
    )
    api.freeze_charge(position["id"], MERCH)
    fx.set_clock("2026-01-21T00:00:00Z")  # 20 whole days frozen
    unfrozen = validate_success(api.unfreeze_charge(position["id"], MERCH))
    assert unfrozen["frozen_days"] == 20, f"expected 20 frozen days, got {unfrozen['frozen_days']}"


def test_get_settlement_surfaces_computed_proceeds(api):
    """PRD §3.5: "The `gross_proceeds_dollars` are the priced bushels multiplied by the
    contract's net price, to 2 decimal places." PRD §3.5: "The `net_proceeds_dollars` are
    the gross proceeds minus the storage charge, to 2 decimal places."

    Design: Corner/endpoints/get_settlement_computed_read_returns_proceeds
    """
    fx.reset_clock_default()
    commodity = fx.create_commodity()
    member = fx.create_member(name="MM Farm")
    fx.create_price_board(commodity["id"])
    _, _, _graded, position = fx.create_graded_position(
        commodity_id=commodity["id"], member_id=member["id"], member_name="MM Farm",
    )
    contract = fx.create_priced_cash_contract(member["id"], commodity["id"], contracted_bushels=1000)
    fx.set_clock("2026-02-15T00:00:00Z")  # 15 chargeable days past grace end 2026-01-31
    settlement = fx.create_draft_settlement(
        contract["id"], position["id"], priced_bushels=600, storage_basis="ACTUAL"
    )
    data = validate_success(api.get_settlement(settlement["id"], OFFICER))
    assert data["gross_proceeds_dollars"] == pytest.approx(2820.00, abs=0.01)
    # 600 * 0.0005 * 15 = 4.50
    assert data["storage_charge_dollars"] == pytest.approx(4.50, abs=0.01)
    assert data["net_proceeds_dollars"] == pytest.approx(2815.50, abs=0.01)
