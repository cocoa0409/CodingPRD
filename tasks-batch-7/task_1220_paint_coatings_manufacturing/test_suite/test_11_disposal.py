"""Disposal: hazmat classification, manifest gating, quantity reconciliation,
pricing with the recovery cap, and cancellation restore."""

import test_helpers as fx
from test_helpers import (
    ApiErrorId,
    PLANT_MANAGER,
    REGULATORY_CLERK,
    validate_error,
    validate_success,
)


def _setup_obsolete_gallon_can(api):
    """An F1 batch closed to FILLED with one GALLON can, aged to OBSOLETE by
    the daily sweep at its expiry date. Returns (b1, g1)."""
    fx.set_clock("2026-05-01T00:00:00Z")
    _tb1, _c1, f1, m1 = fx.setup_plant()
    b1 = fx.plan_batch(f1["id"], m1["id"], planned_gallons=1)
    fx.start_batch(b1["id"])
    fx.dispersion_pass(b1["id"], 18)
    fx.submit_qc(b1["id"], 1)
    cm1 = fx.enter_measurement(b1["id"], 0.42)
    fx.approve_match(cm1["id"])
    fx.set_clock("2026-06-10T10:00:00Z")
    g1 = fx.fill_container(b1["id"], "GALLON", 4600)
    fx.complete_filling(b1["id"], 0)
    fx.set_clock("2028-06-10T00:00:00Z")
    fx.run_daily_sweep()
    assert fx.read_container(g1["id"])["status"] == "OBSOLETE"
    return b1, g1


def test_disposal_cost_hazmat_with_recovery_cap_math(api):
    """PRD §3.9: "The rate is 250 cents per kilogram for a hazardous load and
    90 cents per kilogram otherwise; `gross_cost_cents` is the rate times
    `expected_destroyed_kg`, rounded half up to whole cents, plus a flat
    manifest fee of 45000 cents. `recovery_credit_cents` returns 300 cents
    for each `FIVE_GALLON` metal pail among the referenced containers, capped
    at 20 percent of the gross cost rounded half up to whole cents — the
    credit is the lesser of the two. `net_cost_cents` is the gross minus the
    recovery."
    PRD §3.9: "The `hazmat_class` is `HAZARDOUS` when any referenced
    container's batch has a `voc_actual_gpl` strictly above 250 grams per
    liter or when any colorant in that batch's formula carries `is_hazmat`;
    otherwise it is `NON_HAZARDOUS`."

    Design: Corner/calculations/disposal_cost_hazmat_with_recovery_cap_math
    """
    fx.set_clock("2026-05-01T00:00:00Z")
    tb1 = fx.create_tb1()
    tb2 = fx.create_tb2()
    c1 = fx.create_c1()
    c2 = fx.create_c2()
    f1 = fx.create_f1(tb1["id"], c1["id"])
    fx.activate_formula(f1["id"])
    f2 = fx.create_f2(tb2["id"], c2["id"])
    fx.activate_formula(f2["id"])
    m1 = fx.create_mill()

    # Hazmat custom batch: two FIVE_GALLON pails.
    b2 = fx.plan_batch(f2["id"], m1["id"], planned_gallons=50)
    fx.start_batch(b2["id"])
    fx.dispersion_pass(b2["id"], 15)
    fx.submit_qc(b2["id"], 50)
    cm2 = fx.enter_measurement(b2["id"], 0.3)
    fx.approve_match(cm2["id"])
    fx.set_clock("2026-06-10T10:00:00Z")
    p1 = fx.fill_container(b2["id"], "FIVE_GALLON", 23000)
    p2 = fx.fill_container(b2["id"], "FIVE_GALLON", 23000)
    fx.complete_filling(b2["id"], 39.55)

    # Non-hazmat stock batch: one GALLON can (separate mill window).
    b1 = fx.plan_batch(f1["id"], m1["id"], planned_gallons=1,
                       window=("2026-06-11T08:00:00Z", "2026-06-11T10:00:00Z"))
    fx.start_batch(b1["id"])
    fx.dispersion_pass(b1["id"], 18)
    fx.submit_qc(b1["id"], 1)
    cm1 = fx.enter_measurement(b1["id"], 0.42)
    fx.approve_match(cm1["id"])
    g1 = fx.fill_container(b1["id"], "GALLON", 4600)
    fx.complete_filling(b1["id"], 0)

    # Age everything to OBSOLETE and open one disposal request over all
    # three containers.
    fx.set_clock("2028-06-10T00:00:00Z")
    fx.run_daily_sweep()
    for can in (p1, p2, g1):
        assert fx.read_container(can["id"])["status"] == "OBSOLETE"

    dr1 = fx.create_disposal_request(
        reason="OBSOLETE_STOCK", container_ids=[p1["id"], p2["id"], g1["id"]]
    )
    assert dr1["hazmat_class"] == "HAZARDOUS", (
        "the custom batch's formula uses the is_hazmat colorant"
    )
    assert dr1["expected_destroyed_kg"] == 50.6

    validate_success(
        api.manifest_disposal_request(dr1["id"], {"manifest_no": "MAN-2028-0001"},
                                      REGULATORY_CLERK)
    )
    completed = validate_success(
        api.complete_disposal_request(dr1["id"], {"actual_destroyed_kg": 50.6},
                                      PLANT_MANAGER)
    )
    assert completed["status"] == "DISPOSED"
    # gross = round_half_up(250 * 50.6) + 45000 = 12650 + 45000.
    assert completed["gross_cost_cents"] == 57650
    # 2 pails * 300 = 600; the 20% cap (11530) is not binding.
    assert completed["recovery_credit_cents"] == 600
    assert completed["net_cost_cents"] == 57050
    fx.assert_disposal_cost_invariants(completed)
    for can in (p1, p2, g1):
        assert fx.read_container(can["id"])["status"] == "DISPOSED"


def test_disposal_quantity_mismatch_returns_error(api):
    """PRD §3.9: "Completion carries the scale-verified `actual_destroyed_kg`
    and enforces the quantity gate: when nothing was expected, exactly
    nothing must be certified destroyed; otherwise the absolute deviation
    between actual and expected, divided by the expected mass and expressed
    as a percentage, must not exceed 2 — a larger gap is
    `ERR_DISPOSAL_QUANTITY_MISMATCH`."
    PRD §3.9: "Completion, a `PlantManager` certification, is allowed from
    `MANIFESTED` for any load, and directly from `REQUESTED` only for a
    `NON_HAZARDOUS` load"

    Design: Corner/calculations/disposal_quantity_mismatch_returns_error
    """
    _b1, g1 = _setup_obsolete_gallon_can(api)
    dr1 = fx.create_disposal_request(reason="OBSOLETE_STOCK",
                                     container_ids=[g1["id"]])
    assert dr1["hazmat_class"] == "NON_HAZARDOUS"
    assert dr1["expected_destroyed_kg"] == 4.6
    assert dr1["status"] == "REQUESTED"

    # |6.0 - 4.6| / 4.6 = 30.4% off — far past the 2% gate.
    mismatch = api.complete_disposal_request(
        dr1["id"], {"actual_destroyed_kg": 6.0}, PLANT_MANAGER
    )
    validate_error(mismatch, ApiErrorId.ERR_DISPOSAL_QUANTITY_MISMATCH.value, 422)
    assert fx.read_disposal_request(dr1["id"])["status"] == "REQUESTED"

    # NON_HAZARDOUS shortcut: complete straight from REQUESTED, no manifest.
    completed = validate_success(
        api.complete_disposal_request(dr1["id"], {"actual_destroyed_kg": 4.6},
                                      PLANT_MANAGER)
    )
    assert completed["status"] == "DISPOSED"
    # gross = round_half_up(90 * 4.6) + 45000 = 414 + 45000; no pails.
    assert completed["gross_cost_cents"] == 45414
    assert completed["recovery_credit_cents"] == 0
    assert completed["net_cost_cents"] == 45414
    assert fx.read_container(g1["id"])["status"] == "DISPOSED"


def test_hazmat_complete_without_manifest_returns_invalid_state(api):
    """PRD §3.9: "Completion, a `PlantManager` certification, is allowed from
    `MANIFESTED` for any load, and directly from `REQUESTED` only for a
    `NON_HAZARDOUS` load; a hazardous request that tries to skip its manifest
    is rejected with `ERR_INVALID_STATE`."

    Design: Corner/calculations/hazmat_complete_without_manifest_returns_invalid_state
    """
    fx.set_clock("2026-05-01T00:00:00Z")
    tb2 = fx.create_tb2()
    c2 = fx.create_c2()
    f2 = fx.create_f2(tb2["id"], c2["id"])
    fx.activate_formula(f2["id"])
    m1 = fx.create_mill()
    b2 = fx.plan_batch(f2["id"], m1["id"], planned_gallons=50)
    fx.start_batch(b2["id"])
    fx.dispersion_pass(b2["id"], 15)
    fx.submit_qc(b2["id"], 50)
    cm2 = fx.enter_measurement(b2["id"], 0.3)
    fx.approve_match(cm2["id"])
    fx.set_clock("2026-06-10T10:00:00Z")
    p1 = fx.fill_container(b2["id"], "FIVE_GALLON", 23000)
    fx.complete_filling(b2["id"], 44.77)
    fx.set_clock("2028-06-10T00:00:00Z")
    fx.run_daily_sweep()
    assert fx.read_container(p1["id"])["status"] == "OBSOLETE"

    dr1 = fx.create_disposal_request(reason="OBSOLETE_STOCK",
                                     container_ids=[p1["id"]])
    assert dr1["hazmat_class"] == "HAZARDOUS"
    assert dr1["status"] == "REQUESTED"

    shortcut = api.complete_disposal_request(
        dr1["id"], {"actual_destroyed_kg": 23.0}, PLANT_MANAGER
    )
    validate_error(shortcut, ApiErrorId.ERR_INVALID_STATE.value, 409)
    assert fx.read_disposal_request(dr1["id"])["status"] == "REQUESTED"


def test_disposal_cancel_restores_pre_disposal_status(api):
    """PRD §3.9: "A request still in `REQUESTED` can instead be cancelled by
    a `RegulatoryClerk`. Cancellation restores every referenced container to
    its `pre_disposal_status` — whether that was `OBSOLETE`, `RETURNED`, or
    `REJECTED` — clears `disposal_request_id` and `pre_disposal_status`, and
    lands the request in the terminal `CANCELLED` state."
    PRD §3.9: "Referenced containers must be in `OBSOLETE`, `RETURNED`, or
    `REJECTED` status; each moves to `DISPOSAL_PENDING`, storing its prior
    status in `pre_disposal_status` and the request's id in
    `disposal_request_id`."

    Design: Corner/state_machines/disposal_cancel_restores_pre_disposal_status
    """
    env = fx.setup_shipped_container(line_gallons=1)
    k1 = env["k1"]

    returned = validate_success(
        api.customer_return(k1["id"], fx.PRODUCTION_OPERATOR)
    )
    assert returned["status"] == "RETURNED"

    dr1 = fx.create_disposal_request(reason="RETURNED_GOODS",
                                     container_ids=[k1["id"]])
    pending = fx.read_container(k1["id"])
    assert pending["status"] == "DISPOSAL_PENDING"
    assert pending["pre_disposal_status"] == "RETURNED"
    assert pending["disposal_request_id"] == dr1["id"]

    cancelled = validate_success(
        api.cancel_disposal_request(dr1["id"], REGULATORY_CLERK)
    )
    assert cancelled["status"] == "CANCELLED"
    restored = fx.read_container(k1["id"])
    assert restored["status"] == "RETURNED"
    assert restored.get("disposal_request_id") is None
    assert restored.get("pre_disposal_status") is None
