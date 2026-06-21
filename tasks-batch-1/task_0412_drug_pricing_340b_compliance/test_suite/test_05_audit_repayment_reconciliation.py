"""Ceiling-price reconciliation, repayment-obligation assessment, remittance / waiver
cascades into compliance posture, the OCC reconcile guard, and segregation of duties.

Design sources: Difficulty/combinatorial_formula/overcharge_reconciliation_per_po_floor_then_sum_mode_b,
Difficulty/transitive_cascade/remit_settles_obligation_clears_ce_posture_depth2,
Difficulty/compensating_invariant/remit_then_waive_conserves_repayment_money_balance,
plus Corner/calculations + Corner/validations + Corner/cross_cutting + Corner/errors instances.
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    reconcile_payload, remit_payload, create_purchase_order_payload,
    create_and_approve_covered_entity, create_drug_with_published_ceiling,
    setup_b340b_purchase_order, setup_ceiling_reconciliation_obligation,
    setup_diversion_repayment_obligation,
    setup_dispensable_scenario, record_dispense,
    make_compliance_officer_headers,
    create_self_disclosure_payload,
)

CO = TEST_USERS["compliance_officer_headers"]
HRSA = TEST_USERS["hrsa_auditor_headers"]
PHARM = TEST_USERS["pharmacy_operator_headers"]


# ---------------------------------------------------------------------------
# Overcharge reconciliation: per-PO floor then sum (combinatorial mode b)
# ---------------------------------------------------------------------------
def test_overcharge_reconciliation_per_po_floored_total(api):
    """PRD §3.10: "The flooring order is pinned: each order is floored at zero before
    summation, so an order bought below the ceiling never offsets an order bought above it —
    the total is a sum-of-floored values, not a floor-of-sum."

    Design: Difficulty/combinatorial_formula/overcharge_reconciliation_per_po_floor_then_sum_mode_b
    """
    ce = create_and_approve_covered_entity()
    drug = create_drug_with_published_ceiling(amp=4000, ura=1500, package_size_units=30)  # ceiling 2500
    setup_b340b_purchase_order(ce, drug, packages_ordered=2, unit_price_paid_cents=2700)  # over: (200)*60=12000
    setup_b340b_purchase_order(ce, drug, packages_ordered=1, unit_price_paid_cents=2400)  # under: floored to 0
    dp = validate_success(api.get_drug_product(drug["id"], HRSA), 200)
    obl = validate_success(
        api.reconcile_drug_product(drug["id"], reconcile_payload("2026Q2", dp["version"]), HRSA), 201)
    assert obl["assessed_cents"] == 12000
    assert obl["source_kind"] == "CEILING_RECONCILIATION"


def test_overcharge_reconciliation_not_net_floor_of_sum(api):
    """PRD §3.10: "an order bought below the ceiling never offsets an order bought above it
    — the total is a sum-of-floored values, not a floor-of-sum."

    Design: Difficulty/combinatorial_formula/overcharge_reconciliation_per_po_floor_then_sum_mode_b
    """
    ce = create_and_approve_covered_entity()
    drug = create_drug_with_published_ceiling(amp=4000, ura=1500, package_size_units=30)
    setup_b340b_purchase_order(ce, drug, packages_ordered=2, unit_price_paid_cents=2700)
    setup_b340b_purchase_order(ce, drug, packages_ordered=1, unit_price_paid_cents=2400)
    dp = validate_success(api.get_drug_product(drug["id"], HRSA), 200)
    obl = validate_success(
        api.reconcile_drug_product(drug["id"], reconcile_payload("2026Q2", dp["version"]), HRSA), 201)
    # Net floor-of-sum would have been 9000 (12000 over minus 3000 under); per-PO floor pins 12000.
    assert obl["assessed_cents"] != 9000


# ---------------------------------------------------------------------------
# Diversion clawback assessment (corner)
# ---------------------------------------------------------------------------
def test_diversion_repayment_clawback_amount(api):
    """PRD §3.9: "the per-unit benefit is the drug product's `wac_price_per_unit_cents`
    minus the effective published ceiling price per unit for the dispense's
    `(drug_product_id, quarter)`, floored at zero ... `assessed_cents` is that per-unit
    benefit multiplied by the finding's `assessed_units`."

    Design: Corner/calculations/repayment_diversion_assessment_clawback_amount
    """
    _scenario, _disp, _finding, obligation = setup_diversion_repayment_obligation(
        wac_price_per_unit_cents=4000, amp=4000, ura=1500, assessed_units=5, quantity_units=5)
    # max(0, 4000 - 2500) * 5 = 7500
    assert obligation["assessed_cents"] == 7500
    assert obligation["source_kind"] == "AUDIT_FINDING"


# ---------------------------------------------------------------------------
# Depth-2 cascade: full remit settles obligation -> CE posture flips GOOD
# ---------------------------------------------------------------------------
def test_full_remit_settles_obligation(api):
    """PRD §3.9: "when the remitted amount exactly equals the remaining balance, the
    obligation moves to `SETTLED` with `remaining_balance_cents` driven to 0."

    Design: Difficulty/transitive_cascade/remit_settles_obligation_clears_ce_posture_depth2
    """
    ce, _drug, obligation = setup_ceiling_reconciliation_obligation(
        packages_ordered=2, unit_price_paid_cents=2700)  # assessed 12000
    settled = validate_success(
        api.remit_repayment(obligation["id"], remit_payload(12000), CO), 200)
    assert settled["status"] == "SETTLED"
    assert settled["remaining_balance_cents"] == 0


def test_settlement_flips_ce_posture_to_good(api):
    """PRD §3.9: "Every remit and waive recomputes the owing entity's `open_repayment_cents`
    and `compliance_posture`; a settlement or waiver of the last outstanding obligation, with
    no findings still open, may flip the posture from `FLAGGED` back to `GOOD`."

    Design: Difficulty/transitive_cascade/remit_settles_obligation_clears_ce_posture_depth2
    """
    ce, _drug, obligation = setup_ceiling_reconciliation_obligation(
        packages_ordered=2, unit_price_paid_cents=2700)  # assessed 12000
    validate_success(api.remit_repayment(obligation["id"], remit_payload(12000), CO), 200)
    ce_after = validate_success(api.get_covered_entity(ce["id"], CO), 200)
    assert ce_after["open_repayment_cents"] == 0
    assert ce_after["compliance_posture"] == "GOOD"


# ---------------------------------------------------------------------------
# Money conservation: partial remit then waive
# ---------------------------------------------------------------------------
def test_partial_remit_updates_balance_and_open_cents(api):
    """PRD §3.9: "When the remitted amount is strictly less than the remaining balance, the
    obligation moves to (or stays in) `PARTIALLY_PAID`".

    Design: Difficulty/compensating_invariant/remit_then_waive_conserves_repayment_money_balance
    """
    ce, _drug, obligation = setup_ceiling_reconciliation_obligation(
        packages_ordered=2, unit_price_paid_cents=2700)  # assessed 12000
    partial = validate_success(
        api.remit_repayment(obligation["id"], remit_payload(5000), CO), 200)
    assert partial["status"] == "PARTIALLY_PAID"
    assert partial["remaining_balance_cents"] == 7000
    ce_after = validate_success(api.get_covered_entity(ce["id"], CO), 200)
    assert ce_after["open_repayment_cents"] == 7000


def test_waive_owed_obligation_zeroes_balance(api):
    """PRD §3.9: "an `HrsaAuditor` may waive an `OWED` obligation, moving it to the terminal
    `WAIVED` state with `remaining_balance_cents` set to 0." Money balance conserved to zero:
    waiving the only outstanding obligation drives the entity's open_repayment_cents to 0.

    Design: Difficulty/compensating_invariant/remit_then_waive_conserves_repayment_money_balance
    """
    ce, _drug, obligation = setup_ceiling_reconciliation_obligation(
        packages_ordered=2, unit_price_paid_cents=2700)  # assessed 12000, status OWED
    waived = validate_success(api.waive_repayment(obligation["id"], HRSA), 200)
    assert waived["status"] == "WAIVED"
    assert waived["remaining_balance_cents"] == 0
    ce_after = validate_success(api.get_covered_entity(ce["id"], CO), 200)
    assert ce_after["open_repayment_cents"] == 0


# ---------------------------------------------------------------------------
# OCC reconcile success (corner)
# ---------------------------------------------------------------------------
def test_reconcile_with_current_version_succeeds(api):
    """PRD §3.10: "When the total overcharge is greater than zero, the reconcile creates a
    repayment obligation with `source_kind` of `CEILING_RECONCILIATION` whose
    `assessed_cents` equals that total".

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_drug_product_reconcile_succeeds
    """
    ce = create_and_approve_covered_entity()
    drug = create_drug_with_published_ceiling(amp=4000, ura=1500, package_size_units=30)  # ceiling 2500
    setup_b340b_purchase_order(ce, drug, packages_ordered=1, unit_price_paid_cents=2600)  # over 100/unit * 30
    dp = validate_success(api.get_drug_product(drug["id"], HRSA), 200)
    obl = validate_success(
        api.reconcile_drug_product(drug["id"], reconcile_payload("2026Q2", dp["version"]), HRSA), 201)
    assert obl["assessed_cents"] == 3000


def test_reconcile_provisional_only_quarter_rejected(api):
    """PRD §3.10: "it requires that a published ceiling-price record exist for the
    `(drug_product_id, quarter)` pair — a provisional-only quarter cannot be reconciled and
    is rejected with `ERR_NO_PUBLISHED_CEILING` (HTTP 409)."

    Design: Corner/validations/reconcile_provisional_only_quarter_rejected
    """
    ce = create_and_approve_covered_entity()
    from test_helpers import create_drug_product, add_ceiling_price
    drug = create_drug_product(drug_name="ProvRecon Drug")
    add_ceiling_price(drug["id"], quarter="2026Q2", amp_per_unit_cents=4000,
                      ura_per_unit_cents=1500, is_published=False)
    setup_b340b_purchase_order(ce, drug, packages_ordered=1, unit_price_paid_cents=2700)
    dp = validate_success(api.get_drug_product(drug["id"], HRSA), 200)
    resp = api.reconcile_drug_product(drug["id"], reconcile_payload("2026Q2", dp["version"]), HRSA)
    validate_error(resp, ApiErrorId.ERR_NO_PUBLISHED_CEILING.value, expected_status=409)


def test_remit_exceeds_remaining_balance_rejected(api):
    """PRD §3.9: "The amount must be greater than 0 and at most `remaining_balance_cents`;
    an amount of 0 or below, or an amount exceeding the remaining balance, is rejected with
    `ERR_REMIT_EXCEEDS_BALANCE` (HTTP 422)."

    Design: Corner/validations/remit_exceeds_remaining_balance_rejected
    """
    _ce, _drug, obligation = setup_ceiling_reconciliation_obligation(
        packages_ordered=2, unit_price_paid_cents=2700)  # assessed 12000
    resp = api.remit_repayment(obligation["id"], remit_payload(12001), CO)
    validate_error(resp, ApiErrorId.ERR_REMIT_EXCEEDS_BALANCE.value, expected_status=422)


def test_assessed_units_exceed_dispense_quantity_rejected(api):
    """PRD §3.8: "In both cases `assessed_units` may not exceed the referenced dispense's
    `quantity_units`; an excess is rejected with `ERR_ASSESSED_UNITS_EXCEED` (HTTP 422)."

    Design: Corner/validations/assessed_units_exceed_dispense_quantity_rejected
    """
    scenario = setup_dispensable_scenario()
    disp = record_dispense(scenario, quantity_units=4)
    resp = api.create_self_disclosure(
        scenario["ce"]["id"],
        create_self_disclosure_payload(disp["id"], finding_type="DIVERSION", assessed_units=5), CO)
    validate_error(resp, ApiErrorId.ERR_ASSESSED_UNITS_EXCEED.value, expected_status=422)


# ---------------------------------------------------------------------------
# Segregation of duties on self-disclosure dispute
# ---------------------------------------------------------------------------
def test_self_discloser_cannot_dispute_own_finding(api):
    """PRD §3.8: "on a self-disclosed finding this is subject to segregation of duties —
    the disputing officer's `X-User-ID` must differ from the `X-User-ID` that created the
    disclosure, and a self-disputer is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/rbac/segregation_of_duties_self_discloser_cannot_dispute
    """
    discloser = make_compliance_officer_headers("co-discloser")
    # Build the scenario as the discloser so they own the disclosure.
    from test_helpers import (
        create_covered_entity_payload, create_drug_product_payload,
        create_ceiling_price_payload, create_prescriber_payload, create_patient_payload,
        create_dispense_payload,
    )
    ce = validate_success(
        api.create_covered_entity(
            create_covered_entity_payload(legal_name="SoD CE", entity_type="FQHC",
                                          medicaid_billing_mode="CARVE_OUT"), discloser), 201)
    validate_success(api.approve_covered_entity(ce["id"], HRSA), 200)
    drug = validate_success(
        api.create_drug_product(create_drug_product_payload(drug_name="SoD Drug"), discloser), 201)
    validate_success(
        api.create_ceiling_price(drug["id"], create_ceiling_price_payload(
            amp_per_unit_cents=4000, ura_per_unit_cents=1500, is_published=True), discloser), 201)
    presc = validate_success(
        api.create_prescriber(ce["id"], create_prescriber_payload(relationship_type="EMPLOYED"), discloser), 201)
    pat = validate_success(
        api.create_patient(ce["id"], create_patient_payload(medicaid_ffs_enrolled=False), discloser), 201)
    disp = validate_success(
        api.create_dispense(create_dispense_payload(
            ce["id"], pat["id"], presc["id"], drug["id"], quantity_units=4, quarter="2026Q2"), PHARM), 201)
    finding = validate_success(
        api.create_self_disclosure(
            ce["id"], create_self_disclosure_payload(disp["id"], finding_type="DIVERSION", assessed_units=4),
            discloser), 201)
    validate_success(api.start_review_audit_finding(finding["id"], HRSA), 200)
    resp = api.dispute_audit_finding(finding["id"], discloser)
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, expected_status=403)
