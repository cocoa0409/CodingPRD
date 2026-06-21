"""Temporal-overlap conflicts (contract-pharmacy windows, ceiling quarters), the GPO
prohibition, the duplicate-discount guard, Medicaid-claim status, pagination bounds,
list filters, RBAC denials, and authentication.

Design sources: Difficulty/resource_temporal_overlap/*, Corner/validations/*,
Corner/endpoints/*, Corner/errors/*, Corner/rbac/*.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS,
    create_covered_entity_payload, create_drug_product_payload,
    create_contract_pharmacy_payload, create_purchase_order_payload,
    create_dispense_payload, create_prescriber_payload, create_patient_payload,
    create_ceiling_price_payload,
    create_and_approve_covered_entity, create_covered_entity,
    create_drug_with_published_ceiling, create_drug_product, add_ceiling_price,
    create_prescriber, create_patient,
    setup_dispensable_scenario, record_dispense, setup_ce_with_contract_pharmacy,
    setup_ceiling_reconciliation_obligation,
    make_unknown_role_headers,
)

CO = TEST_USERS["compliance_officer_headers"]
HRSA = TEST_USERS["hrsa_auditor_headers"]
PHARM = TEST_USERS["pharmacy_operator_headers"]


# ---------------------------------------------------------------------------
# Contract-pharmacy half-open window overlap vs adjacency
# ---------------------------------------------------------------------------
def test_contract_pharmacy_overlapping_window_rejected(api):
    """PRD §3.4: "creating an arrangement is rejected with `ERR_CP_WINDOW_OVERLAP` (HTTP
    409) when the same covered entity already has an arrangement whose `arrangement_status`
    is `ACTIVE` or `SUSPENDED`, that shares the same `ship_to_bill_to_npi`, and whose
    half-open window intersects the new half-open window."

    Design: Difficulty/resource_temporal_overlap/contract_pharmacy_half_open_window_overlap_vs_adjacency
    """
    ce, _cp = setup_ce_with_contract_pharmacy(
        npi="1234567890", effective_start="2026-01-01", effective_end="2026-07-01")
    resp = api.create_contract_pharmacy(
        ce["id"],
        create_contract_pharmacy_payload(
            pharmacy_name="Overlap", ship_to_bill_to_npi="1234567890",
            effective_start="2026-06-01", effective_end="2026-12-01"), CO)
    validate_error(resp, ApiErrorId.ERR_CP_WINDOW_OVERLAP.value, expected_status=409)


def test_contract_pharmacy_adjacent_window_allowed(api):
    """PRD §3.4: "Because the intervals are half-open, adjacency does not collide: if an
    existing arrangement's `effective_end` equals the new arrangement's `effective_start`,
    the two abut without overlapping and the new arrangement is accepted."

    Design: Difficulty/resource_temporal_overlap/contract_pharmacy_half_open_window_overlap_vs_adjacency
    """
    ce, _cp = setup_ce_with_contract_pharmacy(
        npi="1234567890", effective_start="2026-01-01", effective_end="2026-07-01")
    adj = validate_success(
        api.create_contract_pharmacy(
            ce["id"],
            create_contract_pharmacy_payload(
                pharmacy_name="Adjacent", ship_to_bill_to_npi="1234567890",
                effective_start="2026-07-01", effective_end="2026-12-01"), CO), 201)
    assert adj["arrangement_status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# Ceiling-quarter degenerate-point collision (published only)
# ---------------------------------------------------------------------------
def test_second_published_ceiling_same_quarter_rejected(api):
    """PRD §3.3: "a second record with `is_published` of `true` for a `(drug_product_id,
    quarter)` pair that already has a published record is rejected with
    `ERR_CEILING_QUARTER_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/ceiling_quarter_degenerate_point_collision_published_only
    """
    drug = create_drug_product(drug_name="SigmaQtr", wac_price_per_unit_cents=5000)
    add_ceiling_price(drug["id"], quarter="2026Q2", amp_per_unit_cents=4000,
                      ura_per_unit_cents=1500, is_published=True)
    resp = api.create_ceiling_price(
        drug["id"], create_ceiling_price_payload(
            amp_per_unit_cents=4100, ura_per_unit_cents=1500, is_published=True), CO)
    validate_error(resp, ApiErrorId.ERR_CEILING_QUARTER_OVERLAP.value, expected_status=409)


def test_provisional_ceiling_same_quarter_allowed(api):
    """PRD §3.3: "Provisional records (with `is_published` of `false`) never collide on
    quarter, and may coexist with a published record for the same quarter."

    Design: Difficulty/resource_temporal_overlap/ceiling_quarter_degenerate_point_collision_published_only
    """
    drug = create_drug_product(drug_name="SigmaQtr2", wac_price_per_unit_cents=5000)
    add_ceiling_price(drug["id"], quarter="2026Q2", amp_per_unit_cents=4000,
                      ura_per_unit_cents=1500, is_published=True)
    prov = validate_success(
        api.create_ceiling_price(
            drug["id"], create_ceiling_price_payload(
                amp_per_unit_cents=4200, ura_per_unit_cents=1500, is_published=False), CO), 201)
    assert prov["is_published"] is False


# ---------------------------------------------------------------------------
# GPO prohibition
# ---------------------------------------------------------------------------
def test_gpo_purchase_order_at_prohibited_ce_rejected(api):
    """PRD §3.10: "A `GPO`-channel purchase order is rejected with `ERR_GPO_PROHIBITED`
    (HTTP 409) when the covered entity's `gpo_prohibited` is `true` and the drug product's
    `is_covered_outpatient_drug` is `true`".

    Design: Corner/validations/gpo_prohibited_purchase_order_rejected
    """
    ce = create_and_approve_covered_entity(entity_type="DSH", medicaid_billing_mode="CARVE_OUT")
    drug = create_drug_product(drug_name="GPO Drug", is_covered_outpatient_drug=True)
    resp = api.create_purchase_order(
        create_purchase_order_payload(
            ce["id"], drug["id"], channel="GPO", packages_ordered=1, unit_price_paid_cents=6000), PHARM)
    validate_error(resp, ApiErrorId.ERR_GPO_PROHIBITED.value, expected_status=409)


def test_gpo_purchase_order_at_non_prohibited_ce_allowed(api):
    """PRD §3.10: "Orders on the `WAC` or `B340B` channel, or `GPO` orders for non-covered
    drugs or at non-prohibited entities, are unaffected."

    Design: Corner/validations/gpo_purchase_allowed_for_non_prohibited_ce
    """
    ce = create_and_approve_covered_entity(entity_type="FQHC", medicaid_billing_mode="CARVE_OUT")
    drug = create_drug_product(drug_name="GPO OK Drug", is_covered_outpatient_drug=True)
    po = validate_success(
        api.create_purchase_order(
            create_purchase_order_payload(
                ce["id"], drug["id"], channel="GPO", packages_ordered=1, unit_price_paid_cents=6000), PHARM), 201)
    assert po["channel"] == "GPO"


# ---------------------------------------------------------------------------
# Duplicate-discount guard + Medicaid claim status
# ---------------------------------------------------------------------------
def test_duplicate_discount_medicaid_claim_on_340b_carve_out_rejected(api):
    """PRD §3.11: "a Medicaid claim may not be created against a `CLASSIFIED_340B` dispense
    when the covered entity's `medicaid_billing_mode` is `CARVE_OUT` ... Such an attempt is
    rejected with `ERR_DUPLICATE_DISCOUNT` (HTTP 409)."

    Design: Corner/validations/duplicate_discount_medicaid_claim_on_340b_carve_out_rejected
    """
    scenario = setup_dispensable_scenario(medicaid_billing_mode="CARVE_OUT")
    disp = record_dispense(scenario, quantity_units=4)  # CLASSIFIED_340B
    resp = api.create_medicaid_claim(disp["id"], {"medicaid_state_code": "CA"}, CO)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_DISCOUNT.value, expected_status=409)


def test_medicaid_claim_clean_on_wac_dispense(api):
    """PRD §3.11: "The system sets `claim_status` to `DUPLICATE_RISK` when the underlying
    dispense is `CLASSIFIED_340B` for a carve-in entity that has not listed on the Medicaid
    Exclusion File (because a rebate would then duplicate the 340B discount), and to `CLEAN`
    otherwise".

    Design: Corner/endpoints/medicaid_claim_clean_on_wac_dispense
    """
    scenario = setup_dispensable_scenario(
        medicaid_billing_mode="CARVE_OUT", patient_overrides={"medicaid_ffs_enrolled": True})
    disp = record_dispense(scenario, quantity_units=4)  # CLASSIFIED_WAC (carve-out medicaid)
    assert disp["classification_status"] == "CLASSIFIED_WAC"
    claim = validate_success(
        api.create_medicaid_claim(disp["id"], {"medicaid_state_code": "CA"}, CO), 201)
    assert claim["claim_status"] == "CLEAN"


# ---------------------------------------------------------------------------
# Pagination and invalid input
# ---------------------------------------------------------------------------
def test_pagination_limit_zero_rejected(api):
    """PRD §2.3: "A `limit` below 1, a `limit` above 100, or a negative `offset` is rejected
    with `ERR_VALIDATION_PAGINATION` (HTTP 422)."

    Design: Corner/validations/pagination_limit_out_of_bounds_rejected
    """
    resp = api.list_covered_entities(HRSA, params={"limit": 0})
    validate_error(resp, ApiErrorId.ERR_VALIDATION_PAGINATION.value, expected_status=422)


def test_dispense_quantity_units_zero_rejected(api):
    """PRD §3.5: "a `quantity_units` (integer of at least 1)".
    PRD §2.6: "then request-shape validity — required fields present, correct types, enum
    members drawn from their declared sets, and integer fields meeting their lower bounds
    (`ERR_INVALID_REQUEST`, HTTP 422)."

    Design: Corner/errors/invalid_quantity_units_zero_rejected
    """
    scenario = setup_dispensable_scenario()
    resp = api.create_dispense(create_dispense_payload(
        scenario["ce"]["id"], scenario["patient"]["id"], scenario["prescriber"]["id"],
        scenario["drug"]["id"], quantity_units=0, quarter="2026Q2"), PHARM)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=422)


def test_list_dispenses_filtered_by_patient_id(api):
    """PRD §2.5: "dispenses, audit findings, repayment obligations, and purchase orders are
    all listable globally with a `covered_entity_id` (and other foreign-key) filter."

    Design: Corner/endpoints/list_dispenses_filtered_by_patient_id
    """
    scenario = setup_dispensable_scenario()
    disp = record_dispense(scenario, quantity_units=4)
    resp = api.list_dispenses(HRSA, params={"patient_id": scenario["patient"]["id"]})
    data, _meta = validate_paginated(resp)
    ids = [d["id"] for d in data]
    assert disp["id"] in ids
    assert all(d["patient_id"] == scenario["patient"]["id"] for d in data)


# ---------------------------------------------------------------------------
# RBAC denials and authentication
# ---------------------------------------------------------------------------
def test_pharmacy_operator_cannot_approve_ce(api):
    """PRD §2.1: "A request whose role is recognised but is not permitted to invoke the
    targeted endpoint per the authorization table in §4 is rejected with `ERR_FORBIDDEN_ROLE`
    (HTTP 403)."

    Design: Corner/rbac/pharmacy_operator_cannot_approve_ce
    """
    ce = create_covered_entity()  # PENDING
    resp = api.approve_covered_entity(ce["id"], PHARM)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value, expected_status=403)


def test_compliance_officer_cannot_dispense(api):
    """PRD §2.1: "A request whose role is recognised but is not permitted to invoke the
    targeted endpoint per the authorization table in §4 is rejected with `ERR_FORBIDDEN_ROLE`
    (HTTP 403)."

    Design: Corner/rbac/compliance_officer_cannot_dispense
    """
    scenario = setup_dispensable_scenario()
    resp = api.create_dispense(create_dispense_payload(
        scenario["ce"]["id"], scenario["patient"]["id"], scenario["prescriber"]["id"],
        scenario["drug"]["id"], quantity_units=4, quarter="2026Q2"), CO)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value, expected_status=403)


def test_hrsa_auditor_cannot_remit_repayment(api):
    """PRD §2.1: "A request whose role is recognised but is not permitted to invoke the
    targeted endpoint per the authorization table in §4 is rejected with `ERR_FORBIDDEN_ROLE`
    (HTTP 403)."

    Design: Corner/rbac/hrsa_auditor_cannot_remit_repayment
    """
    _ce, _drug, obligation = setup_ceiling_reconciliation_obligation(
        packages_ordered=2, unit_price_paid_cents=2700)
    resp = api.remit_repayment(obligation["id"], {"amount_cents": 1000}, HRSA)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value, expected_status=403)


def test_unknown_role_rejected_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or carrying an `X-User-Role` that is not
    one of those three, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/unauthenticated_missing_headers_rejected
    """
    resp = api.list_covered_entities(make_unknown_role_headers("ghost-1"))
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, expected_status=401)
