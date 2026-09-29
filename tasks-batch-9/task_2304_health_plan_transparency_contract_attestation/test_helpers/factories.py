"""Request payload factories.

Each factory returns a complete, valid payload for one write endpoint and
accepts ``**overrides`` so a test can perturb exactly the field under study.
Default values are drawn from the worked illustrations in the PRD so that the
arithmetic expectations in tests line up with documented figures.
"""

from __future__ import annotations

from typing import Any

from .types import (
    AMENDMENT_TYPE_DATA_RIGHTS,
    ATTESTATION_TYPE_GAG_CLAUSE_CEE,
    DEFICIENCY_GAG_CLAUSE,
    FILE_TYPE_IN_NETWORK_RATES,
    SECTION_D2_SPENDING,
    VENDOR_TYPE_TPA,
)

JsonDict = dict[str, Any]

# ---------------------------------------------------------------------------
# Canonical plan-year shape
# ---------------------------------------------------------------------------

DEFAULT_SPONSOR_NAME = "Meridian Manufacturing Benefit Plan"
DEFAULT_PLAN_YEAR_LABEL = "PY2027"
DEFAULT_PLAN_YEAR_START = "2027-01-01"
DEFAULT_PLAN_YEAR_END = "2027-12-31"
DEFAULT_COVERED_LIVES = 6000
DEFAULT_ATTESTATION_DEADLINE = "2028-01-31"
DEFAULT_RXDC_DEADLINE = "2028-06-01"


def plan_year_payload(**overrides: Any) -> JsonDict:
    """Payload for creating a plan year."""
    payload: JsonDict = {
        "sponsor_name": DEFAULT_SPONSOR_NAME,
        "plan_year_label": DEFAULT_PLAN_YEAR_LABEL,
        "start_date": DEFAULT_PLAN_YEAR_START,
        "end_date": DEFAULT_PLAN_YEAR_END,
        "covered_lives": DEFAULT_COVERED_LIVES,
        "attestation_deadline_date": DEFAULT_ATTESTATION_DEADLINE,
        "rxdc_deadline_date": DEFAULT_RXDC_DEADLINE,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Vendors
# ---------------------------------------------------------------------------

TPA_LEGAL_NAME = "Cascade Health Administrators"
TPA_CONTACT_EMAIL = "ops@cascade.example"
PBM_LEGAL_NAME = "Alpine Script Benefit Managers"
PBM_CONTACT_EMAIL = "data@alpinescript.example"
BROKER_LEGAL_NAME = "Harborline Insurance Brokers"
BROKER_CONTACT_EMAIL = "service@harborline.example"
CONSULTANT_LEGAL_NAME = "Pinehurst Benefits Consulting"
CONSULTANT_CONTACT_EMAIL = "advisory@pinehurst.example"
NETWORK_VENDOR_LEGAL_NAME = "Ridgeview Network Analytics"
NETWORK_VENDOR_CONTACT_EMAIL = "feeds@ridgeview.example"


def vendor_payload(**overrides: Any) -> JsonDict:
    """Payload for registering a service provider."""
    payload: JsonDict = {
        "legal_name": TPA_LEGAL_NAME,
        "vendor_type": VENDOR_TYPE_TPA,
        "contact_email": TPA_CONTACT_EMAIL,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Contracts
# ---------------------------------------------------------------------------

DEFAULT_TERM_START = "2027-01-01"
DEFAULT_TERM_END = "2028-01-01"
DEFAULT_ANNUAL_FEE_CENTS = 48_000_000


def contract_payload(
    plan_year_id: str, vendor_id: str, **overrides: Any
) -> JsonDict:
    """Payload for creating a service provider contract."""
    payload: JsonDict = {
        "plan_year_id": plan_year_id,
        "vendor_id": vendor_id,
        "contract_type": VENDOR_TYPE_TPA,
        "term_start": DEFAULT_TERM_START,
        "term_end": DEFAULT_TERM_END,
        "annual_fee_cents": DEFAULT_ANNUAL_FEE_CENTS,
    }
    payload.update(overrides)
    return payload


def gag_review_payload(**overrides: Any) -> JsonDict:
    """Payload for opening a gag-clause review on a contract."""
    payload: JsonDict = {
        "clause_inventory_count": 40,
        "prohibited_clause_count": 2,
        "review_note": "Initial clause inventory completed by compliance.",
    }
    payload.update(overrides)
    return payload


def request_remediation_payload(**overrides: Any) -> JsonDict:
    """Payload for requesting gag-clause remediation from the vendor."""
    payload: JsonDict = {
        "remediation_request_note": "Strike the cost-and-quality disclosure bar.",
    }
    payload.update(overrides)
    return payload


def submit_remediation_payload(**overrides: Any) -> JsonDict:
    """Payload for a vendor's gag-clause remediation submission."""
    payload: JsonDict = {
        "prohibited_clause_count": 1,
        "remediation_note": "One clause struck; one remains under legal review.",
    }
    payload.update(overrides)
    return payload


def clear_gag_payload(**overrides: Any) -> JsonDict:
    """Payload for clearing a contract's gag review."""
    payload: JsonDict = {
        "clearance_note": "No prohibited clauses remain in the executed rider.",
    }
    payload.update(overrides)
    return payload


def escalate_gag_payload(**overrides: Any) -> JsonDict:
    """Payload for escalating a contract's gag review."""
    payload: JsonDict = {
        "escalation_note": "Vendor refuses to strike the disclosure prohibition.",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Amendments
# ---------------------------------------------------------------------------

DEFAULT_AMENDMENT_EXPIRES_AT = "2027-12-31T23:59:59Z"


def amendment_payload(
    contract_id: str, expected_contract_version: int, **overrides: Any
) -> JsonDict:
    """Payload for proposing a contract amendment."""
    payload: JsonDict = {
        "contract_id": contract_id,
        "amendment_type": AMENDMENT_TYPE_DATA_RIGHTS,
        "proposed_terms_summary": "Grant the sponsor full claims data rights.",
        "data_rights_granted": True,
        "expires_at": DEFAULT_AMENDMENT_EXPIRES_AT,
        "expected_contract_version": expected_contract_version,
    }
    payload.update(overrides)
    return payload


def counter_amendment_payload(**overrides: Any) -> JsonDict:
    """Payload for a vendor's counter to a proposed amendment."""
    payload: JsonDict = {
        "counter_terms_summary": "Data rights limited to aggregated extracts.",
    }
    payload.update(overrides)
    return payload


def revise_proposal_payload(**overrides: Any) -> JsonDict:
    """Payload for the sponsor's revision of a countered amendment."""
    payload: JsonDict = {
        "proposed_terms_summary": "Full claim-line detail with monthly refresh.",
        "data_rights_granted": True,
    }
    payload.update(overrides)
    return payload


def execute_amendment_payload(**overrides: Any) -> JsonDict:
    """Payload for executing an amendment."""
    payload: JsonDict = {
        "executed_terms_note": "Rider countersigned by both parties.",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Compensation disclosures
# ---------------------------------------------------------------------------


def compensation_disclosure_payload(contract_id: str, **overrides: Any) -> JsonDict:
    """Payload for recording receipt of a compensation disclosure.

    Defaults follow the PRD's worked broker illustration: 1,000,000 cents
    direct, 400,000 cents indirect, a 1,000,000-cent benchmark, a scope score
    of 5 and a completeness score of 4.
    """
    payload: JsonDict = {
        "contract_id": contract_id,
        "direct_comp_cents": 1_000_000,
        "indirect_comp_cents": 400_000,
        "benchmark_median_cents": 1_000_000,
        "services_scope_score": 5,
        "disclosure_completeness_score": 4,
    }
    payload.update(overrides)
    return payload


def assess_disclosure_payload(**overrides: Any) -> JsonDict:
    """Payload for assessing a compensation disclosure."""
    payload: JsonDict = {
        "assessment_note": "Benchmarked against three comparable engagements.",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Machine-readable files
# ---------------------------------------------------------------------------

DEFAULT_MRF_URL = "https://transparency.meridian.example/in-network-rates.json"
DEFAULT_SCHEMA_VERSION = "v2.0.0"


def mrf_payload(plan_year_id: str, **overrides: Any) -> JsonDict:
    """Payload for staging a machine-readable file."""
    payload: JsonDict = {
        "plan_year_id": plan_year_id,
        "file_type": FILE_TYPE_IN_NETWORK_RATES,
        "posting_month": "2027-06",
        "public_url": DEFAULT_MRF_URL,
        "row_count": 128_000,
        "schema_version": DEFAULT_SCHEMA_VERSION,
    }
    payload.update(overrides)
    return payload


def validate_mrf_payload(**overrides: Any) -> JsonDict:
    """Payload for validating a staged machine-readable file."""
    payload: JsonDict = {"validation_error_count": 0}
    payload.update(overrides)
    return payload


def revise_mrf_payload(**overrides: Any) -> JsonDict:
    """Payload for revising a rejected machine-readable file."""
    payload: JsonDict = {
        "public_url": "https://transparency.meridian.example/in-network-rates-v2.json",
        "row_count": 131_500,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Refresh cycles
# ---------------------------------------------------------------------------


def refresh_cycle_payload(plan_year_id: str, **overrides: Any) -> JsonDict:
    """Payload for opening a monthly refresh cycle."""
    payload: JsonDict = {
        "plan_year_id": plan_year_id,
        "period_month": "2027-06",
        "period_start": "2027-06-01",
        "period_end": "2027-06-30",
    }
    payload.update(overrides)
    return payload


def certify_cycle_payload(**overrides: Any) -> JsonDict:
    """Payload for certifying a refresh cycle."""
    payload: JsonDict = {
        "certification_note": "Both required postings verified as public.",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Price comparison tools
# ---------------------------------------------------------------------------


def price_comparison_tool_payload(plan_year_id: str, **overrides: Any) -> JsonDict:
    """Payload for registering a price comparison tool."""
    payload: JsonDict = {
        "plan_year_id": plan_year_id,
        "tool_name": "Meridian Cost Lookup",
        "covered_items_count": 640,
    }
    payload.update(overrides)
    return payload


def outage_window_payload(**overrides: Any) -> JsonDict:
    """Payload for appending one half-open outage window."""
    payload: JsonDict = {
        "window_start": "2027-06-10T00:00:00Z",
        "window_end": "2027-06-10T03:00:00Z",
        "cause": "Upstream pricing feed unavailable",
    }
    payload.update(overrides)
    return payload


def evaluation_payload(**overrides: Any) -> JsonDict:
    """Payload for triggering a tool uptime evaluation."""
    payload: JsonDict = {"evaluation_month": "2027-06"}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Prescription-drug data
# ---------------------------------------------------------------------------


def rx_submission_payload(plan_year_id: str, **overrides: Any) -> JsonDict:
    """Payload for opening a prescription-drug data submission."""
    payload: JsonDict = {
        "plan_year_id": plan_year_id,
        "reference_year": 2027,
    }
    payload.update(overrides)
    return payload


def vendor_data_package_payload(
    rx_submission_id: str, vendor_id: str, **overrides: Any
) -> JsonDict:
    """Payload for requesting one vendor data section."""
    payload: JsonDict = {
        "rx_submission_id": rx_submission_id,
        "vendor_id": vendor_id,
        "data_section": SECTION_D2_SPENDING,
        "expected_record_count": 1200,
    }
    payload.update(overrides)
    return payload


def deliver_package_payload(**overrides: Any) -> JsonDict:
    """Payload for a vendor's package delivery.

    Defaults follow the first package of the PRD's reconciliation illustration:
    6,000,000 cents plan-paid, 1,000,000 cents member-paid, 1,500,000 cents of
    rebates.
    """
    payload: JsonDict = {
        "record_count": 1200,
        "plan_paid_cents": 6_000_000,
        "member_paid_cents": 1_000_000,
        "rebate_cents": 1_500_000,
    }
    payload.update(overrides)
    return payload


def reject_package_payload(**overrides: Any) -> JsonDict:
    """Payload for rejecting a vendor data package."""
    payload: JsonDict = {
        "rejection_reason": "Plan-paid totals disagree with the claims extract.",
    }
    payload.update(overrides)
    return payload


def resubmit_package_payload(**overrides: Any) -> JsonDict:
    """Payload for a vendor's corrected resubmission."""
    payload: JsonDict = {
        "record_count": 850,
        "plan_paid_cents": 6_000_000,
        "member_paid_cents": 1_000_000,
        "rebate_cents": 1_500_000,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Attestations
# ---------------------------------------------------------------------------


def attestation_payload(
    plan_year_id: str, expected_plan_year_version: int, **overrides: Any
) -> JsonDict:
    """Payload for creating an attestation draft."""
    payload: JsonDict = {
        "plan_year_id": plan_year_id,
        "attestation_type": ATTESTATION_TYPE_GAG_CLAUSE_CEE,
        "contract_terms_doc_count": 3,
        "expected_plan_year_version": expected_plan_year_version,
    }
    payload.update(overrides)
    return payload


def submit_attestation_payload(**overrides: Any) -> JsonDict:
    """Payload for submitting an attestation."""
    payload: JsonDict = {
        "signature_statement": (
            "I attest that no service provider contract of this plan year "
            "contains a prohibited gag clause."
        ),
    }
    payload.update(overrides)
    return payload


def accept_attestation_payload(**overrides: Any) -> JsonDict:
    """Payload for an auditor's acceptance."""
    payload: JsonDict = {
        "acceptance_note": "Evidence pack reconciles to the contract roster.",
    }
    payload.update(overrides)
    return payload


def reject_attestation_payload(**overrides: Any) -> JsonDict:
    """Payload for an auditor's rejection."""
    payload: JsonDict = {
        "rejection_reason": "Contract-terms evidence omits the pharmacy rider.",
    }
    payload.update(overrides)
    return payload


def revise_attestation_payload(**overrides: Any) -> JsonDict:
    """Payload for revising a rejected attestation."""
    payload: JsonDict = {"contract_terms_doc_count": 4}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Ledger and remediation
# ---------------------------------------------------------------------------


def reverse_entry_payload(**overrides: Any) -> JsonDict:
    """Payload for an auditor's reversal of an accrual."""
    payload: JsonDict = {
        "reason": "Accrual posted against the wrong contract on review.",
    }
    payload.update(overrides)
    return payload


def remediation_plan_payload(plan_year_id: str, **overrides: Any) -> JsonDict:
    """Payload for opening a remediation plan."""
    payload: JsonDict = {
        "plan_year_id": plan_year_id,
        "target_deficiency_type": DEFICIENCY_GAG_CLAUSE,
        "milestone_count": 2,
        "plan_summary": "Renegotiate the disclosure clause and re-review.",
    }
    payload.update(overrides)
    return payload


def milestone_completion_payload(**overrides: Any) -> JsonDict:
    """Payload for recording one completed milestone."""
    payload: JsonDict = {"milestone_label": "Disclosure clause struck by rider"}
    payload.update(overrides)
    return payload


def complete_remediation_payload(**overrides: Any) -> JsonDict:
    """Payload for completing a remediation plan."""
    payload: JsonDict = {
        "completion_note": "All corrective steps evidenced and filed.",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# The logical clock
# ---------------------------------------------------------------------------


def clock_payload(current_utc: str, **overrides: Any) -> JsonDict:
    """Payload for setting the service's logical clock."""
    payload: JsonDict = {"current_utc": current_utc}
    payload.update(overrides)
    return payload
