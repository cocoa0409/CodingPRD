"""Buyer commitments: activation OCC, cancellation, FEFO shipping, settlement."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_active_commitment_with_line,
    create_buyer,
    create_buyer_commitment_payload,
    create_commitment_line_payload,
    create_variety,
    get_success_data,
    pack_flush_lot,
    record_flush_on_cycle,
    setup_fruiting_cycle,
    setup_fruiting_cycle_with_graded_flush,
    validate_error,
    validate_paginated,
    validate_success,
)

FARM = TEST_USERS["farm_manager_headers"]
SALES = TEST_USERS["sales_manager_headers"]
ANY = TEST_USERS["any_headers"]


def test_commitment_activate_empty_rejected(api):
    """PRD §3.6: "The commitment must be `DRAFT` (otherwise
    `ERR_COMMITMENT_NOT_DRAFT`) and must have at least one line (otherwise
    `ERR_COMMITMENT_EMPTY`)."

    Design: Corner/state_machines/commitment_activate_empty_rejected
    """
    buyer = create_buyer()
    commitment = get_success_data(api.create_buyer_commitment(
        create_buyer_commitment_payload(buyer_id=buyer["id"]), SALES,
    ))
    resp = api.activate_commitment(
        commitment["id"],
        {"expected_commitment_version": commitment["version"]},
        SALES,
    )
    validate_error(resp, ApiErrorId.ERR_COMMITMENT_EMPTY)
    after = get_success_data(api.get_buyer_commitment(commitment["id"], ANY))
    assert after["status"] == "DRAFT"


def test_commitment_activate_empty_stays_draft(api):
    """PRD §3.6: "must have at least one line (otherwise
    `ERR_COMMITMENT_EMPTY`)."

    Design: Corner/state_machines/commitment_activate_empty_rejected
    """
    buyer = create_buyer()
    commitment = get_success_data(api.create_buyer_commitment(
        create_buyer_commitment_payload(buyer_id=buyer["id"]), SALES,
    ))
    resp = api.activate_commitment(
        commitment["id"],
        {"expected_commitment_version": commitment["version"]},
        SALES,
    )
    validate_error(resp, ApiErrorId.ERR_COMMITMENT_EMPTY)
    assert get_success_data(api.get_buyer_commitment(commitment["id"], ANY))["status"] == "DRAFT"


def test_commitment_cancel_draft_rejected(api):
    """PRD §3.6: "Cancelling a commitment is allowed only while nothing has
    moved against it. The commitment must be `ACTIVE` (otherwise
    `ERR_COMMITMENT_NOT_ACTIVE`)."

    Design: Corner/errors/commitment_cancel_draft_rejected
    """
    buyer = create_buyer()
    commitment = get_success_data(api.create_buyer_commitment(
        create_buyer_commitment_payload(buyer_id=buyer["id"]), SALES,
    ))
    resp = api.cancel_commitment(commitment["id"], SALES)
    validate_error(resp, ApiErrorId.ERR_COMMITMENT_NOT_ACTIVE)


def test_commitment_cancel_with_deliveries_rejected(api):
    """PRD §3.6: "The commitment must be `ACTIVE` (otherwise
    `ERR_COMMITMENT_NOT_ACTIVE`), every line's `delivered_kg` must be 0
    (otherwise `ERR_COMMITMENT_HAS_DELIVERIES`)."

    Design: Corner/state_machines/commitment_cancel_with_deliveries_rejected
    """
    variety, _batch, _room, rc, flush = setup_fruiting_cycle_with_graded_flush()
    lot = pack_flush_lot(flush, grade="A", units=30, kg_per_unit=1.0)
    buyer, commitment, line = create_active_commitment_with_line(variety, committed_kg=500.0)
    get_success_data(api.allocate_commitment_line(line["id"], {"target_kg": 30.0}, SALES))
    get_success_data(api.ship_packaged_lot(lot["id"], SALES))

    line_mid = get_success_data(api.get_commitment_line(line["id"], ANY))
    assert line_mid["delivered_kg"] == 30.0

    resp = api.cancel_commitment(commitment["id"], SALES)
    validate_error(resp, ApiErrorId.ERR_COMMITMENT_HAS_DELIVERIES)
    commitment_after = get_success_data(api.get_buyer_commitment(commitment["id"], ANY))
    line_after = get_success_data(api.get_commitment_line(line["id"], ANY))
    assert commitment_after["status"] == "ACTIVE"
    assert line_after["status"] == "ACTIVE"


def test_commitment_shortfall_tiered_penalty(api):
    """PRD §3.6: "Otherwise the line settles `SHORTFALL` and pays a tiered
    penalty on the shortfall: when the shortfall ratio — `shortfall_kg`
    divided by `committed_kg` — is at most 0.15, the rate is 120 cents per
    shortfall kilogram; when it is above 0.15 but at most 0.40, the rate is
    200; above 0.40, the rate is 350. The `penalty_cents` is the shortfall
    kilograms times the selected rate, rounded half-up to whole cents. For
    example, a line committed to 500 kg that delivered 400 kg records a
    shortfall of 100 kg, a ratio of 0.20, the 200-cent tier, and a penalty of
    20000 cents."
    PRD §3.6: "Settling a line adds its `penalty_cents` to the buyer's
    `lifetime_shortfall_penalty_cents` ... When every line of a commitment
    has reached `SETTLED` or `CANCELLED`, the commitment itself bubbles up
    from `ACTIVE` to `CLOSED`."

    Design: Difficulty/combinatorial_formula/commitment_shortfall_tiered_penalty
    """
    variety, _batch, _room, rc = setup_fruiting_cycle()
    flush = record_flush_on_cycle(rc, total_kg=1000.0)
    from test_helpers import grade_flush as _grade
    _grade(flush, grade_a_kg=600.0, grade_b_kg=300.0, cull_kg=100.0)
    lot = pack_flush_lot(flush, grade="A", units=40, kg_per_unit=10.0)

    buyer, commitment, line = create_active_commitment_with_line(variety, committed_kg=500.0)
    get_success_data(api.allocate_commitment_line(line["id"], {"target_kg": 400.0}, SALES))
    get_success_data(api.ship_packaged_lot(lot["id"], SALES))

    # Advance past week_end (2026-05-10) and sweep.
    get_success_data(api.set_clock({"to_iso8601": "2026-05-11T00:00:00Z"}, FARM))
    sweep = validate_success(api.run_daily_sweep(FARM), expected_status=200)
    assert sweep["settled_line_count"] == 1
    assert sweep["closed_commitment_count"] == 1

    line_after = get_success_data(api.get_commitment_line(line["id"], ANY))
    assert line_after["status"] == "SETTLED"
    assert line_after["settlement_outcome"] == "SHORTFALL"
    assert line_after["shortfall_kg"] == pytest.approx(100.0, abs=0.01)
    # ratio 100/500 = 0.20 -> tier 2 (rate 200 cents/kg) -> 20000 cents.
    assert line_after["penalty_cents"] == 20000

    buyer_after = get_success_data(api.get_buyer(buyer["id"], ANY))
    assert buyer_after["lifetime_shortfall_penalty_cents"] == 20000

    commitment_after = get_success_data(api.get_buyer_commitment(commitment["id"], ANY))
    assert commitment_after["status"] == "CLOSED", (
        "all lines terminal -> commitment bubbles up to CLOSED"
    )


def test_commitment_shortfall_uses_tier_two_rate(api):
    """PRD §3.6: "a line committed to 500 kg that delivered 400 kg records a
    shortfall of 100 kg, a ratio of 0.20, the 200-cent tier, and a penalty of
    20000 cents."

    Design: Difficulty/combinatorial_formula/commitment_shortfall_tiered_penalty
    """
    variety, _batch, _room, rc = setup_fruiting_cycle()
    flush = record_flush_on_cycle(rc, total_kg=1000.0)
    from test_helpers import grade_flush as _grade
    _grade(flush, grade_a_kg=600.0, grade_b_kg=300.0, cull_kg=100.0)
    lot = pack_flush_lot(flush, grade="A", units=40, kg_per_unit=10.0)
    _buyer, _commitment, line = create_active_commitment_with_line(variety, committed_kg=500.0)
    get_success_data(api.allocate_commitment_line(line["id"], {"target_kg": 400.0}, SALES))
    get_success_data(api.ship_packaged_lot(lot["id"], SALES))
    get_success_data(api.set_clock({"to_iso8601": "2026-05-11T00:00:00Z"}, FARM))
    validate_success(api.run_daily_sweep(FARM), expected_status=200)
    line_after = get_success_data(api.get_commitment_line(line["id"], ANY))
    assert line_after["settlement_outcome"] == "SHORTFALL"
    assert line_after["shortfall_kg"] == pytest.approx(100.0, abs=0.01)
    assert line_after["penalty_cents"] == 20000


def test_settlement_fulfilled_at_tolerance_boundary(api):
    """PRD §3.6: "Delivery is judged against a 5% tolerance: if
    `delivered_kg` is at least 95% of `committed_kg` — the boundary is
    inclusive, so exactly 95% counts — the line settles `FULFILLED` with
    `penalty_cents` 0. ... a line committed to 500 kg that delivered 475 kg
    meets the inclusive 95% boundary and settles `FULFILLED` with no penalty,
    though its `shortfall_kg` of 25.0 is still recorded."
    PRD §3.6: "When every line of a commitment has reached `SETTLED` or
    `CANCELLED`, the commitment itself bubbles up from `ACTIVE` to `CLOSED`."

    Design: Corner/calculations/settlement_fulfilled_at_tolerance_boundary
    """
    variety, _batch, _room, rc = setup_fruiting_cycle()
    flush = record_flush_on_cycle(rc, total_kg=1000.0)
    from test_helpers import grade_flush as _grade
    _grade(flush, grade_a_kg=600.0, grade_b_kg=300.0, cull_kg=100.0)
    lot = pack_flush_lot(flush, grade="A", units=95, kg_per_unit=5.0)

    _buyer, commitment, line = create_active_commitment_with_line(variety, committed_kg=500.0)
    get_success_data(api.allocate_commitment_line(line["id"], {"target_kg": 475.0}, SALES))
    get_success_data(api.ship_packaged_lot(lot["id"], SALES))

    get_success_data(api.set_clock({"to_iso8601": "2026-05-11T00:00:00Z"}, FARM))
    validate_success(api.run_daily_sweep(FARM), expected_status=200)

    line_after = get_success_data(api.get_commitment_line(line["id"], ANY))
    assert line_after["status"] == "SETTLED"
    assert line_after["settlement_outcome"] == "FULFILLED"
    assert line_after["shortfall_kg"] == pytest.approx(25.0, abs=0.01)
    assert line_after["penalty_cents"] == 0

    commitment_after = get_success_data(api.get_buyer_commitment(commitment["id"], ANY))
    assert commitment_after["status"] == "CLOSED"
    assert commitment_after["total_delivered_kg"] == pytest.approx(475.0, abs=0.01)


def test_occ_stale_commitment_version_returns_412(api):
    """PRD §2.6: "Activating a buyer commitment requires the request to carry
    `expected_commitment_version`, the client's last observed `version` of
    that `BuyerCommitment`. If the commitment's version has advanced since
    the client last read it, the activation is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."
    PRD §2.8: "Optimistic-concurrency stale-version rejection (priority 6,
    `ERR_STALE_VERSION`, HTTP 412) is checked before state preconditions, so
    a stale writer gets a deterministic 412 regardless of the target's
    subsequent state."

    Design: Corner/cross_cutting_layers/occ_stale_commitment_version_returns_412
    """
    variety = create_variety()
    buyer = create_buyer()
    commitment = get_success_data(api.create_buyer_commitment(
        create_buyer_commitment_payload(buyer_id=buyer["id"]), SALES,
    ))
    pre_activation_version = commitment["version"]
    get_success_data(api.add_commitment_line(
        commitment["id"],
        create_commitment_line_payload(variety_id=variety["id"]),
        SALES,
    ))
    # First activation succeeds (and bumps version to 2).
    get_success_data(api.activate_commitment(
        commitment["id"],
        {"expected_commitment_version": pre_activation_version},
        SALES,
    ))
    # Replay with the stale pre-activation version.
    replay = api.activate_commitment(
        commitment["id"],
        {"expected_commitment_version": pre_activation_version},
        SALES,
    )
    validate_error(replay, ApiErrorId.ERR_STALE_VERSION)
    after = get_success_data(api.get_buyer_commitment(commitment["id"], ANY))
    assert after["status"] == "ACTIVE", "rejected write must not change the commitment"


def test_occ_stale_commitment_version_beats_state_check(api):
    """PRD §2.8: "Optimistic-concurrency stale-version rejection (priority 6,
    `ERR_STALE_VERSION`, HTTP 412) is checked before state preconditions, so
    a stale writer gets a deterministic 412 regardless of the target's
    subsequent state."

    The replayed activation carries the pre-activation version while the
    commitment is now ACTIVE (so `ERR_COMMITMENT_NOT_DRAFT` would also apply);
    the 412 must win.

    Design: Corner/cross_cutting_layers/occ_stale_commitment_version_returns_412
    """
    variety = create_variety()
    buyer = create_buyer()
    commitment = get_success_data(api.create_buyer_commitment(
        create_buyer_commitment_payload(buyer_id=buyer["id"]), SALES,
    ))
    pre_activation_version = commitment["version"]
    get_success_data(api.add_commitment_line(
        commitment["id"],
        create_commitment_line_payload(variety_id=variety["id"]),
        SALES,
    ))
    get_success_data(api.activate_commitment(
        commitment["id"],
        {"expected_commitment_version": pre_activation_version},
        SALES,
    ))
    replay = api.activate_commitment(
        commitment["id"],
        {"expected_commitment_version": pre_activation_version},
        SALES,
    )
    body = replay.json()
    assert body["data"]["error_id"] == "ERR_STALE_VERSION"
    assert body["data"]["error_id"] != "ERR_COMMITMENT_NOT_DRAFT"


def test_commitment_create_for_suspended_buyer_rejected(api):
    """PRD §3.6: "Creation names the `buyer_id` and a purchase-order
    `reference`; the buyer must be `ACTIVE`, otherwise
    `ERR_BUYER_NOT_ACTIVE`."

    Design: Corner/validations/commitment_create_for_suspended_buyer_rejected
    """
    buyer = create_buyer()
    get_success_data(api.patch_buyer(buyer["id"], {"status": "SUSPENDED"}, SALES))
    resp = api.create_buyer_commitment(
        create_buyer_commitment_payload(buyer_id=buyer["id"]), SALES,
    )
    validate_error(resp, ApiErrorId.ERR_BUYER_NOT_ACTIVE)
