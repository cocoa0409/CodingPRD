"""Orchard contracts, harvest intake, and settlement (shortfall penalty)."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    NON_EXISTENT_UUID, TEST_USERS, api_client,
    create_contract_payload, create_harvest_lot_payload,
    create_active_contract, create_variety, create_harvest_lot,
    create_complete_press_batch, assert_contract, assert_harvest_lot,
    assert_lot_weight_invariant, assert_settlement_penalty_cents,
)

OM = TEST_USERS["orchard_manager_headers"]
CL = TEST_USERS["cellar_lead_headers"]
CO = TEST_USERS["compliance_officer_headers"]


# ─── Corner: entities ───────────────────────────────────────────────────────

def test_contract_creation_default_shortfall_penalty_applied(api):
    """PRD section 3.1: "an optional `shortfall_penalty_cents_per_lb` defaults
    to 0 when omitted. A new contract starts in `DRAFT` status with its
    `received_weight_lbs` tally at 0."

    Design: Corner/entities/contract_creation_default_shortfall_penalty_applied
    """
    payload = create_contract_payload(grower_name="DefTest", committed_weight_lbs=5000)
    assert "shortfall_penalty_cents_per_lb" not in payload
    created = validate_success(api.create_contract(payload, OM), 201)
    assert_contract(created)
    assert created["shortfall_penalty_cents_per_lb"] == 0


def test_contract_get_by_id_returns_persisted(api):
    """PRD section 2.2: "Unless otherwise noted, operations that create or modify
    a resource will return the created or updated resource object in the data field."
    PRD section 2.4: "The `version` is a system-managed integer that increments
    by one on every mutation — state transitions, computed-field recomputations,
    and cascade-driven updates all count as mutations."

    Design: Corner/entities/contract_get_by_id_returns_persisted
    """
    created = validate_success(api.create_contract(
        create_contract_payload(grower_name="GetMe", region_code="VT",
                                season_year=2026, committed_weight_lbs=3000,
                                price_per_lb_cents=85), OM), 201)
    fetched = validate_success(api.get_contract(created["id"], OM), 200)
    assert_contract(fetched)
    assert fetched["id"] == created["id"]
    assert fetched["grower_name"] == "GetMe"
    assert fetched["season_year"] == 2026
    # initial version value is server-chosen; the GET must echo what create returned
    assert fetched["version"] == created["version"]
    assert fetched["created_at"] == created["created_at"]


def test_contract_get_not_found_returns_404(api):
    """PRD section 2.7: "the server confirms each identifier in sequence and
    rejects the request with `ERR_NOT_FOUND` at the first identifier, such as
    `{varietyId}`, `{tankId}`, or a bare `{id}`, that does not resolve to an
    existing resource."

    Design: Corner/entities/contract_get_not_found_returns_404
    """
    res = api.get_contract(NON_EXISTENT_UUID, OM)
    validate_error(res, "ERR_NOT_FOUND")


def test_contract_list_pagination_envelope(api):
    """PRD section 2.3: "The `limit` parameter caps the number of items returned:
    it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset`
    parameter specifies how many items to skip and defaults to 0."
    PRD section 2.3: "The `meta` object of a list response carries the pagination
    fields `limit`, `offset`, `total_count`, and `has_more`."
    PRD section 2.3: "Unless otherwise specified, every list endpoint returns
    resources sorted by `created_at` in ascending order."

    Design: Corner/entities/contract_list_pagination_envelope
    """
    ids = []
    for name in ("A", "B", "C"):
        c = validate_success(api.create_contract(
            create_contract_payload(grower_name=name), OM), 201)
        ids.append(c["id"])

    data, meta = validate_paginated(api.list_contracts(OM, params={"limit": 2, "offset": 0}))
    assert len(data) == 2
    assert meta["limit"] == 2
    assert meta["offset"] == 0
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert [c["id"] for c in data] == ids[:2], "list must be created_at ascending"

    data2, meta2 = validate_paginated(api.list_contracts(OM, params={"limit": 2, "offset": 2}))
    assert len(data2) == 1
    assert meta2["has_more"] is False
    assert data2[0]["id"] == ids[2]


def test_create_returns_full_entity_immediately(api):
    """PRD section 3.1: "A new contract starts in `DRAFT` status with its
    `received_weight_lbs` tally at 0."
    PRD section 2.2: "Unless otherwise noted, operations that create or modify
    a resource will return the created or updated resource object in the data field."

    Design: Corner/consistency_model/create_returns_full_entity_immediately
    """
    created = validate_success(api.create_contract(
        create_contract_payload(grower_name="IC", committed_weight_lbs=1000), OM), 201)
    assert_contract(created)
    assert created["received_weight_lbs"] == 0
    assert created["status"] == "DRAFT"
    assert isinstance(created["version"], int)


# ─── Corner: state machines ─────────────────────────────────────────────────

def test_contract_settle_from_draft_rejected(api):
    """PRD section 3.1: "Once the season winds down, the `OrchardManager` settles
    an `ACTIVE` contract."
    PRD section 2.9: "suitability of the target resource's state for the requested
    action (else `ERR_INVALID_STATE`)".

    Design: Corner/state_machines/contract_settle_from_draft_rejected
    """
    contract = validate_success(api.create_contract(
        create_contract_payload(grower_name="Drafty", committed_weight_lbs=1000), OM), 201)
    assert contract["status"] == "DRAFT"
    res = api.settle_contract(contract["id"], OM)
    validate_error(res, "ERR_INVALID_STATE")


def test_contract_terminal_settled_no_further_transition(api):
    """PRD section 3.1: "A `DRAFT` contract that was opened in error can be voided,
    moving it to `VOIDED`, but only while no harvest lots are linked to it;
    `SETTLED` and `VOIDED` are terminal."
    PRD section 2.9: "suitability of the target resource's state for the requested
    action (else `ERR_INVALID_STATE`)".

    Design: Corner/state_machines/contract_terminal_settled_no_further_transition
    """
    contract = create_active_contract(grower_name="Term", committed_weight_lbs=100)
    settled = validate_success(api.settle_contract(contract["id"], OM), 200)
    assert settled["status"] == "SETTLED"

    res = api.void_contract(contract["id"], OM)
    validate_error(res, "ERR_INVALID_STATE")


def test_harvest_lot_initial_state_received(api):
    """PRD section 3.1: "A new lot starts in `RECEIVED` status, and its weight is
    added to the parent contract's `received_weight_lbs`."

    Design: Corner/state_machines/harvest_lot_initial_state_received
    """
    variety = create_variety(code="VI")
    contract = create_active_contract(grower_name="I", committed_weight_lbs=100)
    lot = validate_success(api.create_harvest_lot(
        contract["id"],
        create_harvest_lot_payload(variety["id"], weight_lbs=100), OM), 201)
    assert_harvest_lot(lot)
    assert lot["status"] == "RECEIVED"

    contract_after = validate_success(api.get_contract(contract["id"], OM), 200)
    assert contract_after["received_weight_lbs"] == 100


def test_harvest_lot_computed_unpressed_weight(api):
    """PRD section 3.1: "each lot additionally tracks its `pressed_weight_lbs`
    (starting at 0) and a derived `unpressed_weight_lbs`, which is always the
    lot's `weight_lbs` minus its `pressed_weight_lbs`."

    Design: Corner/entities/harvest_lot_computed_unpressed_weight
    """
    variety = create_variety(code="VX")
    contract = create_active_contract(grower_name="CX", committed_weight_lbs=1000)
    created = validate_success(api.create_harvest_lot(
        contract["id"],
        create_harvest_lot_payload(variety["id"], weight_lbs=1000), OM), 201)
    lot = validate_success(api.get_harvest_lot(created["id"], OM), 200)
    assert lot["weight_lbs"] == 1000
    assert lot["pressed_weight_lbs"] == 0
    assert lot["unpressed_weight_lbs"] == 1000
    assert_lot_weight_invariant(lot)


# ─── Difficulty: dual_variant_calc / contract_shortfall_provisional_vs_final ─

def _setup_shortfall_scenario(pressed_lbs, spoiled_lbs, committed=10000, rate=50):
    """Active contract + one fully PRESSED lot + one SPOILED lot."""
    variety = create_variety(code=f"V-{pressed_lbs}-{spoiled_lbs}")
    contract = create_active_contract(
        grower_name="Riverbend", region_code="VT",
        committed_weight_lbs=committed, shortfall_penalty_cents_per_lb=rate)
    lot_pressed = create_harvest_lot(contract["id"], variety["id"], weight_lbs=pressed_lbs)
    lot_spoiled = create_harvest_lot(contract["id"], variety["id"], weight_lbs=spoiled_lbs)
    press_batch = create_complete_press_batch(
        lot_pressed["id"], pressed_lbs, pressed_lbs // 2)
    assert press_batch["status"] == "COMPLETE", "Setup failed: press batch not COMPLETE"
    spoiled = validate_success(api_client.spoil_harvest_lot(lot_spoiled["id"], CL), 200)
    assert spoiled["status"] == "SPOILED", "Setup failed: lot not SPOILED"
    return contract, lot_pressed, lot_spoiled


def test_shortfall_final_settle_excludes_spoiled_lot(api):
    """PRD section 3.1: "The received figure sums `weight_lbs` across the
    contract's lots in `PRESSED` or `PARTIALLY_PRESSED` state — `SPOILED` lots
    are excluded."
    PRD section 3.1: "Otherwise, the excess over the free allowance is charged
    tier by tier: the portion of the excess that fits inside the twenty-percent
    tier is charged at `shortfall_penalty_cents_per_lb` per pound, and any
    remaining pounds beyond that tier are charged at double that rate, with the
    total expressed in integer cents."
    PRD section 3.1: "Settling moves the contract to `SETTLED` and emits a
    `CONTRACT_SETTLED` event that includes the penalty."

    committed=10000, one PRESSED lot of 5000, one SPOILED lot of 4000:
    received=5000, shortfall=5000, free=1000, tier1=2000 -> 2000*50 + 2000*100
    = 300000 cents.

    Design: Difficulty/dual_variant_calc/contract_shortfall_provisional_vs_final
    """
    contract, lot_pressed, lot_spoiled = _setup_shortfall_scenario(5000, 4000)

    settled = validate_success(api.settle_contract(contract["id"], OM), 200)
    assert settled["status"] == "SETTLED"
    assert settled["received_weight_lbs"] == 5000, "SPOILED lot must be excluded"
    assert_settlement_penalty_cents(settled, 300000)

    events, _ = validate_paginated(api.list_compliance_events(
        CO, params={"entity_id": contract["id"], "action": "CONTRACT_SETTLED"}))
    assert len(events) >= 1, "settlement must emit a CONTRACT_SETTLED compliance event"


def test_shortfall_live_tally_matches_locked_figure_at_settle(api):
    """PRD section 3.1: "Spoiled fruit does not count toward the grower's
    commitment: the lot's `weight_lbs` is subtracted from the contract's
    `received_weight_lbs`, and a `LOT_SPOILED` compliance event is emitted."
    PRD section 3.1: "A provisional variant of this calculation can be quoted at
    any time before settlement for preview, using the contract's current
    `received_weight_lbs`; the final variant is computed at the moment of
    settlement from the locked received figure, persists to the settlement
    record, and cannot be moved by any subsequent lot transition."

    The live tally moves 5000 -> 9000 (second receive) -> 5000 (spoil) before
    settle; the settle then locks received=5000 and the 300000-cent penalty.

    Design: Difficulty/dual_variant_calc/contract_shortfall_provisional_vs_final
    """
    variety = create_variety(code="V-LIVE")
    contract = create_active_contract(
        grower_name="LiveTally", region_code="VT",
        committed_weight_lbs=10000, shortfall_penalty_cents_per_lb=50)
    lot_a = create_harvest_lot(contract["id"], variety["id"], weight_lbs=5000)
    lot_b = create_harvest_lot(contract["id"], variety["id"], weight_lbs=4000)

    mid = validate_success(api.get_contract(contract["id"], OM), 200)
    assert mid["received_weight_lbs"] == 9000

    press_batch = create_complete_press_batch(lot_a["id"], 5000, 2500)
    assert press_batch["status"] == "COMPLETE", "Setup failed: press batch not COMPLETE"
    after_press = validate_success(api.get_contract(contract["id"], OM), 200)
    assert after_press["received_weight_lbs"] == 9000, \
        "already-counted fruit still counts after pressing"

    validate_success(api.spoil_harvest_lot(lot_b["id"], CL), 200)
    after_spoil = validate_success(api.get_contract(contract["id"], OM), 200)
    assert after_spoil["received_weight_lbs"] == 5000, "spoiled fruit must be subtracted"

    settled = validate_success(api.settle_contract(contract["id"], OM), 200)
    assert settled["status"] == "SETTLED"
    assert settled["received_weight_lbs"] == 5000, "settle locks the live figure"
    assert_settlement_penalty_cents(settled, 300000)


# ─── Difficulty: combinatorial_formula / contract_shortfall_tiered ──────────

def test_shortfall_tier2_double_rate_applies(api):
    """PRD section 3.1: "The first slice of any shortfall is free: the free
    allowance is `committed_weight_lbs` times ten percent, rounded down to a
    whole pound. The next tier spans `committed_weight_lbs` times twenty
    percent, also rounded down."
    PRD section 3.1: "Otherwise, the excess over the free allowance is charged
    tier by tier: the portion of the excess that fits inside the twenty-percent
    tier is charged at `shortfall_penalty_cents_per_lb` per pound, and any
    remaining pounds beyond that tier are charged at double that rate, with the
    total expressed in integer cents."

    committed=10000, received=5000 (one fully PRESSED lot), rate=50:
    shortfall=5000; free=1000; remaining=4000; tier1 min(4000,2000)=2000 at 50;
    tier2 2000 at 100 -> 100000 + 200000 = 300000 cents.

    Design: Difficulty/combinatorial_formula/contract_shortfall_tiered_three_input_nonlinear
    """
    variety = create_variety(code="V-T2")
    contract = create_active_contract(
        grower_name="Stony Field", committed_weight_lbs=10000,
        shortfall_penalty_cents_per_lb=50)
    lot = create_harvest_lot(contract["id"], variety["id"], weight_lbs=5000)
    press_batch = create_complete_press_batch(lot["id"], 5000, 2500)
    assert press_batch["status"] == "COMPLETE", "Setup failed: press batch not COMPLETE"

    settled = validate_success(api.settle_contract(contract["id"], OM), 200)
    assert settled["status"] == "SETTLED"
    assert settled["received_weight_lbs"] == 5000
    assert_settlement_penalty_cents(settled, 300000)


def test_shortfall_within_tier1_single_rate(api):
    """PRD section 3.1: "If the shortfall does not exceed the free allowance,
    the penalty is zero cents. Otherwise, the excess over the free allowance is
    charged tier by tier: the portion of the excess that fits inside the
    twenty-percent tier is charged at `shortfall_penalty_cents_per_lb` per
    pound, and any remaining pounds beyond that tier are charged at double that
    rate, with the total expressed in integer cents."

    committed=10000, received=7500, rate=50: shortfall=2500; free=1000;
    remaining=1500 which fits inside the 2000-lb tier-1 -> 1500 * 50 = 75000
    cents, and nothing spills into the double-rate tier.

    Design: Difficulty/combinatorial_formula/contract_shortfall_tiered_three_input_nonlinear
    """
    variety = create_variety(code="V-T1")
    contract = create_active_contract(
        grower_name="TierOne", committed_weight_lbs=10000,
        shortfall_penalty_cents_per_lb=50)
    lot = create_harvest_lot(contract["id"], variety["id"], weight_lbs=7500)
    press_batch = create_complete_press_batch(lot["id"], 7500, 3750)
    assert press_batch["status"] == "COMPLETE", "Setup failed: press batch not COMPLETE"

    settled = validate_success(api.settle_contract(contract["id"], OM), 200)
    assert settled["status"] == "SETTLED"
    assert settled["received_weight_lbs"] == 7500
    assert_settlement_penalty_cents(settled, 75000)
