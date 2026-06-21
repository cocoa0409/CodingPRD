"""Field returns (RMA): open-gating, warranty-credit computation, and triage forks.

Covers the queue-A difficulty instances on the RMA->Unit shipped-gating dependency
and the dual-variant warranty-credit calculation, plus queue-B corner instances on
the workmanship full-factor credit and the no-fault-found repair block.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
)
import test_helpers.fixtures as fx
import test_helpers.factories as f

PE = TEST_USERS["process_engineer_headers"]
PP = TEST_USERS["production_planner_headers"]
QE = TEST_USERS["quality_engineer_headers"]


# ---------------------------------------------------------------------------
# RMA open gating on SHIPPED disposition (queue A cross_entity_state_dependency)
# ---------------------------------------------------------------------------

def test_open_rma_for_unshipped_unit_rejected(api):
    """PRD §3.10: "a return may be opened only for a unit whose `disposition` is
    `SHIPPED`, otherwise it is rejected with `ERR_UNIT_NOT_SHIPPED` (HTTP 422)."

    Design: Difficulty/cross_entity_state_dependency/rma_open_requires_unit_shipped
    """
    # A PASS unit that has NOT been shipped (disposition still IN_PROCESS).
    _part, _bom, _prog, wo, units = fx.setup_at_test_work_order(planned_qty=1,
                                                               received_qty=10,
                                                               unit_cost_cents=20,
                                                               standard_cost_cents=20)
    fx.record_result(units[0]["id"], "PASS")
    fetched_unit = validate_success(api.get_unit(units[0]["id"], PP))
    assert fetched_unit["disposition"] == "IN_PROCESS", fetched_unit
    validate_error(api.create_rma(f.create_rma_payload(units[0]["id"]), QE),
                   ApiErrorId.ERR_UNIT_NOT_SHIPPED.value)


def test_open_rma_for_shipped_unit_succeeds(api):
    """PRD §3.10: "A field return is opened by a `QualityEngineer` for a board that has
    actually shipped. ... a return may be opened only for a unit whose `disposition` is
    `SHIPPED`".
    PRD §3.10: "A new return starts `RECEIVED` with `warranty_credit_cents` zero."

    Companion to the unshipped rejection: a genuinely SHIPPED unit accepts the RMA,
    pinning that the gate keys on the SHIPPED disposition.

    Design: Difficulty/cross_entity_state_dependency/rma_open_requires_unit_shipped
    """
    _part, _bom, _wo, units = fx.setup_shipped_unit(planned_qty=2, received_qty=100,
                                                    unit_cost_cents=50, qty_per_assembly=1)
    shipped = validate_success(api.get_unit(units[0]["id"], PP))
    assert shipped["disposition"] == "SHIPPED", shipped
    rma = validate_success(api.create_rma(f.create_rma_payload(units[0]["id"]), QE),
                           expected_status=201)
    assert rma["status"] == "RECEIVED", rma
    assert rma["warranty_credit_cents"] == 0, rma


# ---------------------------------------------------------------------------
# Warranty-credit dual-variant calculation (queue A dual_variant_calc)
# ---------------------------------------------------------------------------

def test_component_credit_sixty_percent(api):
    """PRD §3.10: "That per-unit build cost is the parent work order's
    `material_cost_cents` divided by its `built_qty`, using integer floor division."
    PRD §3.10: "a `COMPONENT` failure credits 0.60 of it ... The base credit is the
    build cost multiplied by the class factor, rounded half-up to whole cents."

    material_cost 200 / built 2 = unit_build 100; COMPONENT factor 0.60 -> credit 60
    (the unit was never reworked, so no penalty applies).

    Design: Difficulty/dual_variant_calc/rma_warranty_credit_vs_rework_surcharge_cost
    """
    _part, _wo, _unit, rma = fx.setup_rma_for_shipped_unit(
        failure_class="COMPONENT", planned_qty=2, received_qty=100,
        unit_cost_cents=50, qty_per_assembly=2)
    assert rma["status"] == "TRIAGED", rma
    assert rma["warranty_credit_cents"] == 60, rma


def test_component_credit_computed_at_triage(api):
    """PRD §3.10: "A new return starts `RECEIVED` with `warranty_credit_cents` zero."
    PRD §3.10: "A `QualityEngineer` triages a `RECEIVED` return by assigning a
    `failure_class` ... which both moves the return from `RECEIVED` to `TRIAGED` and
    computes its `warranty_credit_cents`."

    The COMPONENT credit (unit_build 100 * 0.60 = 60) materializes only at triage: the
    untriaged return carries zero, and triage both transitions the RMA and computes the
    credit — independently of the rework-surcharge variant.

    Design: Difficulty/dual_variant_calc/rma_warranty_credit_vs_rework_surcharge_cost
    """
    _part, _wo, _unit, rma = fx.setup_rma_for_shipped_unit(
        failure_class=None, planned_qty=2, received_qty=100,
        unit_cost_cents=50, qty_per_assembly=2)
    assert rma["status"] == "RECEIVED", rma
    assert rma["warranty_credit_cents"] == 0, rma
    triaged = validate_success(api.triage_rma(rma["id"], f.triage_rma_payload("COMPONENT"), QE))
    assert triaged["status"] == "TRIAGED", triaged
    assert triaged["warranty_credit_cents"] == 60, triaged


def test_workmanship_credit_full_factor(api):
    """PRD §3.10: "a `WORKMANSHIP` failure credits the full build cost (factor 1.00)
    ... The base credit is the build cost multiplied by the class factor, rounded
    half-up to whole cents."

    material_cost 200 / built 2 = unit_build 100; WORKMANSHIP factor 1.00 -> credit 100.

    Design: Corner/calculations/warranty_credit_workmanship_full_factor
    """
    _part, _wo, _unit, rma = fx.setup_rma_for_shipped_unit(
        failure_class="WORKMANSHIP", planned_qty=2, received_qty=100,
        unit_cost_cents=50, qty_per_assembly=2)
    assert rma["warranty_credit_cents"] == 100, rma


# ---------------------------------------------------------------------------
# Triage fork: no-fault-found cannot be repaired
#
# DELETED test_repair_no_fault_found_rejected — STEP 1b unique-derivability
# (error-precedence collapse). PRD §3.10 gates repair on the *business rule*
# "only when the `failure_class` is not `NO_FAULT_FOUND`", but the RMA is in
# `TRIAGED`, which IS a valid state for the repair transition (TRIAGED ->
# REPAIRED). Under PRD §2.7 the state check passes (valid state) and the
# failure_class block is a business rule with no specific error code, so §2.7
# maps it to ERR_VALIDATION, not ERR_INVALID_STATE. PRD does not uniquely
# determine the asserted ERR_INVALID_STATE; a faithful reader produces
# ERR_VALIDATION. Rule that drove the test: rma_repair_no_fault_found_blocked.
# ---------------------------------------------------------------------------
