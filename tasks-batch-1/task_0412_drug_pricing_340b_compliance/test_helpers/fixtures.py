"""Composite setup helpers for the 340B Drug Pricing & Compliance API.

Each test runs against a freshly restarted, empty server, so every fixture builds
all of its preconditions from scratch using only PRD-declared endpoints. Setup calls
use get_success_data() (lenient) so a broken precondition surfaces as a clear
"Setup failed" rather than a confusing downstream assertion.

All three roles are opaque operator identifiers (PRD §2.1), so fixtures use the
shared role-header constants directly.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import TEST_USERS
from . import factories as F

CO = TEST_USERS["compliance_officer_headers"]
HRSA = TEST_USERS["hrsa_auditor_headers"]
PHARM = TEST_USERS["pharmacy_operator_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-entity creators (each returns the created resource dict)
# ---------------------------------------------------------------------------
def create_covered_entity(**overrides) -> dict:
    """Register a covered entity (starts PENDING)."""
    payload = F.create_covered_entity_payload(**overrides)
    return get_success_data(api_client.create_covered_entity(payload, CO))


def create_and_approve_covered_entity(**overrides) -> dict:
    """Register + approve a covered entity -> ACTIVE. Returns the active entity."""
    ce = create_covered_entity(**overrides)
    return get_success_data(api_client.approve_covered_entity(ce["id"], HRSA))


def create_drug_product(**overrides) -> dict:
    payload = F.create_drug_product_payload(**overrides)
    return get_success_data(api_client.create_drug_product(payload, CO))


def add_ceiling_price(drug_product_id, **overrides) -> dict:
    payload = F.create_ceiling_price_payload(**overrides)
    return get_success_data(api_client.create_ceiling_price(drug_product_id, payload, CO))


def create_drug_with_published_ceiling(amp=4000, ura=1500, quarter="2026Q2",
                                       wac_price_per_unit_cents=6000,
                                       package_size_units=30, **dp_overrides) -> dict:
    """Drug product + one published ceiling for the quarter. Returns the drug product
    dict (re-fetched so its version reflects the ceiling addition)."""
    dp = create_drug_product(package_size_units=package_size_units,
                             wac_price_per_unit_cents=wac_price_per_unit_cents,
                             **dp_overrides)
    add_ceiling_price(dp["id"], quarter=quarter, amp_per_unit_cents=amp,
                      ura_per_unit_cents=ura, is_published=True)
    return get_success_data(api_client.get_drug_product(dp["id"], HRSA))


def create_prescriber(ce_id, relationship_type="EMPLOYED", **overrides) -> dict:
    payload = F.create_prescriber_payload(relationship_type=relationship_type, **overrides)
    return get_success_data(api_client.create_prescriber(ce_id, payload, CO))


def create_patient(ce_id, **overrides) -> dict:
    payload = F.create_patient_payload(**overrides)
    return get_success_data(api_client.create_patient(ce_id, payload, CO))


def create_accumulator(ce_id, drug_product_id) -> dict:
    payload = F.create_accumulator_payload(drug_product_id)
    return get_success_data(api_client.create_accumulator(ce_id, payload, CO))


# ---------------------------------------------------------------------------
# Tier 2: the canonical dispensable scenario
# ---------------------------------------------------------------------------
def setup_dispensable_scenario(amp=4000, ura=1500, wac_price_per_unit_cents=6000,
                               package_size_units=30, quarter="2026Q2",
                               medicaid_billing_mode="CARVE_OUT",
                               entity_type="FQHC",
                               prescriber_relationship="EMPLOYED",
                               patient_overrides=None,
                               with_accumulator=False):
    """Active CE + published-ceiling drug + prescriber + patient (and optionally an
    accumulator). Returns a dict with keys:
    ce, drug, prescriber, patient, accumulator (None unless requested), quarter.

    This is the most common preamble: it puts the system in a state where a
    PharmacyOperator can record a dispense that classifies 340B for an all-eligible
    patient.
    """
    ce = create_and_approve_covered_entity(entity_type=entity_type,
                                           medicaid_billing_mode=medicaid_billing_mode)
    drug = create_drug_with_published_ceiling(
        amp=amp, ura=ura, quarter=quarter,
        wac_price_per_unit_cents=wac_price_per_unit_cents,
        package_size_units=package_size_units,
    )
    prescriber = create_prescriber(ce["id"], relationship_type=prescriber_relationship)
    patient = create_patient(ce["id"], **(patient_overrides or {}))
    accumulator = create_accumulator(ce["id"], drug["id"]) if with_accumulator else None
    return {
        "ce": ce, "drug": drug, "prescriber": prescriber,
        "patient": patient, "accumulator": accumulator, "quarter": quarter,
    }


def record_dispense(scenario, quantity_units=4, headers=None, **overrides) -> dict:
    """Record a dispense against a setup_dispensable_scenario(). Returns the dispense."""
    headers = headers or PHARM
    payload = F.create_dispense_payload(
        scenario["ce"]["id"], scenario["patient"]["id"], scenario["prescriber"]["id"],
        scenario["drug"]["id"], quantity_units=quantity_units,
        quarter=scenario["quarter"], **overrides,
    )
    return get_success_data(api_client.create_dispense(payload, headers))


def setup_classified_340b_dispense(quantity_units=4, with_accumulator=True, **scenario_kwargs):
    """Full chain to a single CLASSIFIED_340B dispense. Returns (scenario, dispense)."""
    scenario = setup_dispensable_scenario(with_accumulator=with_accumulator, **scenario_kwargs)
    dispense = record_dispense(scenario, quantity_units=quantity_units)
    return scenario, dispense


# ---------------------------------------------------------------------------
# Tier 3: audit-finding lifecycle shortcuts
# ---------------------------------------------------------------------------
def create_open_hrsa_finding(scenario, dispense, finding_type="DIVERSION", assessed_units=4) -> dict:
    """Raise an OPEN HRSA_AUDIT finding against a dispense."""
    payload = F.create_audit_finding_payload(
        scenario["ce"]["id"], dispense["id"],
        finding_type=finding_type, assessed_units=assessed_units,
    )
    return get_success_data(api_client.create_audit_finding(payload, HRSA))


def create_under_review_hrsa_finding(scenario, dispense, finding_type="DIVERSION",
                                     assessed_units=4) -> dict:
    """OPEN HRSA finding advanced to UNDER_REVIEW via start-review."""
    finding = create_open_hrsa_finding(scenario, dispense, finding_type, assessed_units)
    return get_success_data(api_client.start_review_audit_finding(finding["id"], HRSA))


# ---------------------------------------------------------------------------
# Tier 4: ceiling-reconciliation -> repayment obligation shortcuts
# ---------------------------------------------------------------------------
def setup_b340b_purchase_order(ce, drug, packages_ordered=2, unit_price_paid_cents=2700,
                               quarter="2026Q2") -> dict:
    payload = F.create_purchase_order_payload(
        ce["id"], drug["id"], channel="B340B",
        packages_ordered=packages_ordered, quarter=quarter,
        unit_price_paid_cents=unit_price_paid_cents,
    )
    return get_success_data(api_client.create_purchase_order(payload, PHARM))


def setup_ceiling_reconciliation_obligation(packages_ordered=2, unit_price_paid_cents=2700,
                                            amp=4000, ura=1500, package_size_units=30,
                                            quarter="2026Q2"):
    """Active CE + published-ceiling drug + one overcharging B340B PO, then reconcile
    to create a CEILING_RECONCILIATION RepaymentObligation. Returns
    (ce, drug, obligation). The default (2 packages * 30 units * (2700-2500)) = 12000.
    """
    ce = create_and_approve_covered_entity()
    drug = create_drug_with_published_ceiling(
        amp=amp, ura=ura, quarter=quarter, package_size_units=package_size_units,
    )
    setup_b340b_purchase_order(ce, drug, packages_ordered=packages_ordered,
                               unit_price_paid_cents=unit_price_paid_cents, quarter=quarter)
    dp = get_success_data(api_client.get_drug_product(drug["id"], HRSA))
    obligation = get_success_data(api_client.reconcile_drug_product(
        drug["id"], F.reconcile_payload(quarter, dp["version"]), HRSA,
    ))
    return ce, drug, obligation


def setup_diversion_repayment_obligation(wac_price_per_unit_cents=4000, amp=4000, ura=1500,
                                         assessed_units=5, quantity_units=5):
    """Active CE + 340B dispense + OPEN HRSA DIVERSION finding + AUDIT_FINDING repayment
    obligation. Returns (scenario, dispense, finding, obligation)."""
    scenario, dispense = setup_classified_340b_dispense(
        quantity_units=quantity_units, with_accumulator=False,
        wac_price_per_unit_cents=wac_price_per_unit_cents, amp=amp, ura=ura,
    )
    finding = create_open_hrsa_finding(scenario, dispense, finding_type="DIVERSION",
                                       assessed_units=assessed_units)
    obligation = get_success_data(api_client.create_finding_repayment(finding["id"], HRSA))
    return scenario, dispense, finding, obligation


# ---------------------------------------------------------------------------
# Tier 5: contract-pharmacy setups
# ---------------------------------------------------------------------------
def setup_ce_with_contract_pharmacy(npi="1234567890", effective_start="2026-01-01",
                                    effective_end="2026-07-01"):
    """Active CE + one ACTIVE contract-pharmacy arrangement. Returns (ce, arrangement)."""
    ce = create_and_approve_covered_entity()
    payload = F.create_contract_pharmacy_payload(
        ship_to_bill_to_npi=npi, effective_start=effective_start, effective_end=effective_end,
    )
    cp = get_success_data(api_client.create_contract_pharmacy(ce["id"], payload, CO))
    return ce, cp
