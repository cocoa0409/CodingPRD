"""The split-billing accumulator: virtual unit read vs actual package replenishment,
the dispense->accumulator->purchase-order cascade, the package boundary, multi-package
floor division, reverse/reinstate conservation, and OCC on manual replenish.

Design sources: Difficulty/dual_variant_calc/accumulator_virtual_unit_read_vs_actual_package_replenish,
Difficulty/transitive_cascade/dispense_to_accumulator_to_purchase_order_depth3,
Difficulty/boundary_precision_check/accumulator_package_threshold_29_vs_30_on_dispense,
Difficulty/compensating_invariant/reverse_reinstate_conserves_accumulator_accrued_units,
plus Corner/calculations + Corner/cross_cutting accumulator instances.
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    create_dispense_payload, replenish_payload,
    create_and_approve_covered_entity, create_drug_with_published_ceiling,
    create_prescriber, create_patient, create_accumulator,
    setup_dispensable_scenario, record_dispense,
    assert_accumulator,
)

CO = TEST_USERS["compliance_officer_headers"]
HRSA = TEST_USERS["hrsa_auditor_headers"]
PHARM = TEST_USERS["pharmacy_operator_headers"]


def _scenario_with_accumulator(package_size_units=30, amp=4000, ura=1500):
    scenario = setup_dispensable_scenario(
        package_size_units=package_size_units, amp=amp, ura=ura, with_accumulator=True)
    return scenario


# ---------------------------------------------------------------------------
# Dual-variant: virtual unit read vs actual package replenishment
# ---------------------------------------------------------------------------
def test_accumulator_virtual_read_below_boundary(api):
    """PRD §3.6: "Reading an accumulator reports `accrued_units` as a running unit balance
    — a read-only projection that does not crystallise any package and creates no purchase
    order."

    Design: Difficulty/dual_variant_calc/accumulator_virtual_unit_read_vs_actual_package_replenish
    """
    scenario = _scenario_with_accumulator()
    acc_id = scenario["accumulator"]["id"]
    record_dispense(scenario, quantity_units=10)
    record_dispense(scenario, quantity_units=10)
    acc = validate_success(api.get_accumulator(acc_id, PHARM), 200)
    assert acc["accrued_units"] == 20
    assert acc["replenished_packages_total"] == 0


def test_accumulator_actual_replenish_crystallises_on_boundary(api):
    """PRD §3.6: "When `accrued_units` is greater than or equal to `package_size_units` —
    the boundary is inclusive, so reaching exactly the package size triggers a sweep — the
    system crystallises whole packages".

    Design: Difficulty/dual_variant_calc/accumulator_virtual_unit_read_vs_actual_package_replenish
    """
    scenario = _scenario_with_accumulator()
    acc_id = scenario["accumulator"]["id"]
    record_dispense(scenario, quantity_units=10)
    record_dispense(scenario, quantity_units=10)
    record_dispense(scenario, quantity_units=10)  # third 10 -> 30 == package_size
    acc = validate_success(api.get_accumulator(acc_id, PHARM), 200)
    assert acc["accrued_units"] == 0
    assert acc["replenished_packages_total"] == 1


# ---------------------------------------------------------------------------
# Depth-3 cascade: dispense -> accumulator sweep -> B340B purchase order
# ---------------------------------------------------------------------------
def test_dispense_crossing_boundary_crystallises_one_package(api):
    """PRD §3.6: "the number of packages is the integer floor of `accrued_units` divided
    by `package_size_units`, computed by integer floor division; `accrued_units` is then
    reduced by the number of packages multiplied by `package_size_units`".

    Design: Difficulty/transitive_cascade/dispense_to_accumulator_to_purchase_order_depth3
    """
    scenario = _scenario_with_accumulator()
    acc_id = scenario["accumulator"]["id"]
    record_dispense(scenario, quantity_units=30)
    acc = validate_success(api.get_accumulator(acc_id, PHARM), 200)
    assert acc["accrued_units"] == 0
    assert acc["replenished_packages_total"] == 1


def test_replenishment_emits_b340b_purchase_order(api):
    """PRD §3.6: "As a side effect, the sweep creates a purchase order on the `B340B`
    channel for the crystallised packages, with its `accumulator_id` pointing back at this
    accumulator and its `unit_price_paid_cents` set to the effective ceiling price per
    unit."

    Design: Difficulty/transitive_cascade/dispense_to_accumulator_to_purchase_order_depth3
    """
    scenario = _scenario_with_accumulator()
    acc_id = scenario["accumulator"]["id"]
    record_dispense(scenario, quantity_units=30)
    data, meta = _list_pos_for_accumulator(api, acc_id)
    assert len(data) == 1, f"expected exactly one B340B PO, got {len(data)}"
    po = data[0]
    assert po["channel"] == "B340B"
    assert po["packages_ordered"] == 1
    assert po["accumulator_id"] == acc_id


def _list_pos_for_accumulator(api, acc_id):
    from test_helpers import validate_paginated
    resp = api.list_purchase_orders(PHARM, params={"accumulator_id": acc_id})
    return validate_paginated(resp)


# ---------------------------------------------------------------------------
# Boundary precision 29 (no sweep) vs 30 (sweep)
# ---------------------------------------------------------------------------
def test_accumulator_below_threshold_29_no_sweep(api):
    """PRD §3.6: "When `accrued_units` is greater than or equal to `package_size_units` —
    the boundary is inclusive, so reaching exactly the package size triggers a sweep — the
    system crystallises whole packages".

    Design: Difficulty/boundary_precision_check/accumulator_package_threshold_29_vs_30_on_dispense
    """
    scenario = _scenario_with_accumulator()
    acc_id = scenario["accumulator"]["id"]
    record_dispense(scenario, quantity_units=29)
    acc = validate_success(api.get_accumulator(acc_id, PHARM), 200)
    assert acc["accrued_units"] == 29
    assert acc["replenished_packages_total"] == 0


def test_accumulator_at_threshold_30_triggers_sweep(api):
    """PRD §3.6: "the boundary is inclusive, so reaching exactly the package size triggers
    a sweep — the system crystallises whole packages".

    Design: Difficulty/boundary_precision_check/accumulator_package_threshold_29_vs_30_on_dispense
    """
    scenario = _scenario_with_accumulator()
    acc_id = scenario["accumulator"]["id"]
    record_dispense(scenario, quantity_units=30)
    acc = validate_success(api.get_accumulator(acc_id, PHARM), 200)
    assert acc["accrued_units"] == 0
    assert acc["replenished_packages_total"] == 1


def test_multi_package_single_dispense_floor_division(api):
    """PRD §3.6: "the number of packages is the integer floor of `accrued_units` divided
    by `package_size_units`, computed by integer floor division; `accrued_units` is then
    reduced by the number of packages multiplied by `package_size_units`, leaving a
    remainder that always sits between 0 and one less than `package_size_units` inclusive".

    Design: Corner/calculations/multi_package_single_dispense_floor_division
    """
    scenario = _scenario_with_accumulator()
    acc_id = scenario["accumulator"]["id"]
    record_dispense(scenario, quantity_units=70)  # floor(70/30) = 2, remainder 10
    acc = validate_success(api.get_accumulator(acc_id, PHARM), 200)
    assert acc["replenished_packages_total"] == 2
    assert acc["accrued_units"] == 10


# ---------------------------------------------------------------------------
# Compensating invariant: reverse/reinstate conserves accrued_units
# ---------------------------------------------------------------------------
def test_reverse_debits_accumulator(api):
    """PRD §3.7: "As compensation, if the dispense was `CLASSIFIED_340B`, the accumulator
    for its pair is debited: `accrued_units` is reduced by the dispense's `quantity_units`".

    Design: Difficulty/compensating_invariant/reverse_reinstate_conserves_accumulator_accrued_units
    """
    scenario = _scenario_with_accumulator()
    acc_id = scenario["accumulator"]["id"]
    record_dispense(scenario, quantity_units=17)
    disp7 = record_dispense(scenario, quantity_units=7)  # accrued 24
    validate_success(api.reverse_dispense(disp7["id"], PHARM), 200)
    acc = validate_success(api.get_accumulator(acc_id, PHARM), 200)
    assert acc["accrued_units"] == 17


def test_reverse_then_reinstate_conserves_accrued_units(api):
    """PRD §3.7: "Reinstatement re-credits a `CLASSIFIED_340B` dispense's `quantity_units`
    back into the accumulator's `accrued_units` and re-runs the replenishment sweep — so the
    conserved quantity nets to zero across a reverse-then-reinstate pair."

    Design: Difficulty/compensating_invariant/reverse_reinstate_conserves_accumulator_accrued_units
    """
    scenario = _scenario_with_accumulator()
    acc_id = scenario["accumulator"]["id"]
    record_dispense(scenario, quantity_units=17)
    disp7 = record_dispense(scenario, quantity_units=7)  # accrued 24
    validate_success(api.reverse_dispense(disp7["id"], PHARM), 200)
    mid = validate_success(api.get_accumulator(acc_id, PHARM), 200)
    assert mid["accrued_units"] == 17
    validate_success(api.reinstate_dispense(disp7["id"], PHARM), 200)
    end = validate_success(api.get_accumulator(acc_id, PHARM), 200)
    assert end["accrued_units"] == 24  # no drift


# ---------------------------------------------------------------------------
# OCC on manual replenish
# ---------------------------------------------------------------------------
def test_manual_replenish_with_stale_version_rejected(api):
    """PRD §2.7: "If a 340B dispense — or an automatic replenishment that dispense
    triggered — has already advanced the accumulator's `accrued_units` and bumped its
    `version` since the client last read it, the client's view of the package count is
    stale, and the replenishment is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_accumulator_replenish_conflict
    """
    scenario = _scenario_with_accumulator()
    acc_id = scenario["accumulator"]["id"]
    stale = validate_success(api.get_accumulator(acc_id, PHARM), 200)
    stale_version = stale["version"]
    # A 30-unit 340B dispense auto-replenishes and bumps the accumulator version.
    record_dispense(scenario, quantity_units=30)
    resp = api.replenish_accumulator(acc_id, replenish_payload(stale_version), PHARM)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, expected_status=412)
