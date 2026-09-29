"""Request-payload factories.

Each factory returns a fully valid payload for one write endpoint and accepts
keyword overrides, so a test can bend exactly one field and leave every other
field valid.
"""

from typing import Any, Dict

# --- Canonical literals reused across the suite -----------------------------
IMPORTER_LEGAL_NAME = "Northbrook Foods Import LLC"
IMPORTER_DNB = "123456789"
IMPORTER_UFI = "UFI-NB-0001"

SECOND_IMPORTER_LEGAL_NAME = "Southbay Provisions Inc"
SECOND_IMPORTER_DNB = "987654321"
SECOND_IMPORTER_UFI = "UFI-SB-0002"

SMALL_IMPORTER_LEGAL_NAME = "Harborline Small Importer LLC"
SMALL_IMPORTER_DNB = "555000111"
SMALL_IMPORTER_UFI = "UFI-HL-0003"

QI_A_NAME = "Ada Ruiz"
QI_A_EMAIL = "ada@northbrook.example"
QI_A_SUMMARY = "PCQI and FSVP training plus eight years of supplier audit experience"
QI_A_TRAINING = "2025-06-01T00:00:00Z"

QI_B_NAME = "Ben Osei"
QI_B_EMAIL = "ben@northbrook.example"
QI_B_SUMMARY = "Preventive controls qualified individual with laboratory oversight background"
QI_B_TRAINING = "2025-07-01T00:00:00Z"

SUPPLIER_NAME = "Rio Verde SA"
SUPPLIER_COUNTRY = "PE"
SUPPLIER_FRN = "FRN-PE-77001"

FOOD_NAME = "Frozen mango chunks"
FOOD_CODE = "20-MAN-01"


def _merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(base)
    payload.update(overrides)
    return {k: v for k, v in payload.items() if v is not _OMIT}


class _Omit:
    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "<omit>"


_OMIT = _Omit()
OMIT = _OMIT
"""Sentinel: pass ``field=OMIT`` to drop a key from the payload entirely."""


# --- Importer ---------------------------------------------------------------
def importer_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "legal_name": IMPORTER_LEGAL_NAME,
            "dnb_number": IMPORTER_DNB,
            "unique_facility_identifier": IMPORTER_UFI,
        },
        overrides,
    )


def second_importer_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "legal_name": SECOND_IMPORTER_LEGAL_NAME,
            "dnb_number": SECOND_IMPORTER_DNB,
            "unique_facility_identifier": SECOND_IMPORTER_UFI,
        },
        overrides,
    )


def small_importer_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "legal_name": SMALL_IMPORTER_LEGAL_NAME,
            "dnb_number": SMALL_IMPORTER_DNB,
            "unique_facility_identifier": SMALL_IMPORTER_UFI,
            "small_importer_flag": True,
        },
        overrides,
    )


# --- QualifiedIndividual ----------------------------------------------------
def qualified_individual_payload(importer_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "importer_id": importer_id,
            "full_name": QI_A_NAME,
            "email": QI_A_EMAIL,
            "qualification_summary": QI_A_SUMMARY,
            "training_completed_at": QI_A_TRAINING,
        },
        overrides,
    )


def second_qualified_individual_payload(importer_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "importer_id": importer_id,
            "full_name": QI_B_NAME,
            "email": QI_B_EMAIL,
            "qualification_summary": QI_B_SUMMARY,
            "training_completed_at": QI_B_TRAINING,
        },
        overrides,
    )


def designation_payload(action: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"action": action}, overrides)


# --- ForeignSupplier --------------------------------------------------------
def foreign_supplier_payload(importer_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "importer_id": importer_id,
            "name": SUPPLIER_NAME,
            "country_code": SUPPLIER_COUNTRY,
            "facility_registration_number": SUPPLIER_FRN,
            "regulatory_compliance_status": "NO_ADVERSE_FINDINGS",
        },
        overrides,
    )


def evaluation_payload(decision: str = "APPROVE", **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "decision": decision,
            "performance_basis_note": (
                "No adverse FDA findings and two acceptable prior audits on file"
            ),
        },
        overrides,
    )


def compliance_status_payload(status: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "regulatory_compliance_status": status,
            "source_reference": "FDA compliance record reviewed on 2026-08-28",
        },
        overrides,
    )


# --- Food -------------------------------------------------------------------
def food_payload(importer_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "importer_id": importer_id,
            "food_name": FOOD_NAME,
            "fda_product_code": FOOD_CODE,
            "is_raw_agricultural_commodity": False,
            "intended_consumer_group": "GENERAL",
            "ready_to_eat": True,
        },
        overrides,
    )


def plain_food_payload(importer_id: str, **overrides: Any) -> Dict[str, Any]:
    """GENERAL, non-RAC, not ready-to-eat: every optional multiplier is 1.00."""
    return _merge(
        {
            "importer_id": importer_id,
            "food_name": "Dried yellow peas",
            "fda_product_code": "23-PEA-04",
            "is_raw_agricultural_commodity": False,
            "intended_consumer_group": "GENERAL",
            "ready_to_eat": False,
        },
        overrides,
    )


def juice_food_payload(importer_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "importer_id": importer_id,
            "food_name": "Pasteurized orange juice",
            "fda_product_code": "24-JUI-11",
            "is_raw_agricultural_commodity": False,
            "intended_consumer_group": "GENERAL",
            "process_control_category": "JUICE_HACCP",
            "ready_to_eat": True,
        },
        overrides,
    )


def infant_food_payload(importer_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "importer_id": importer_id,
            "food_name": "Infant rice cereal",
            "fda_product_code": "40-INF-06",
            "is_raw_agricultural_commodity": False,
            "intended_consumer_group": "INFANT",
            "ready_to_eat": True,
        },
        overrides,
    )


# --- SupplierFoodPair -------------------------------------------------------
def pair_payload(
    importer_id: str, supplier_id: str, food_id: str, designated_qi_id: str, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "importer_id": importer_id,
            "supplier_id": supplier_id,
            "food_id": food_id,
            "designated_qi_id": designated_qi_id,
        },
        overrides,
    )


def verification_approval_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "approval_note": (
                "Verification activities and their frequency justification are adequate"
            )
        },
        overrides,
    )


def reassessment_payload(trigger_reason: str = "NEW_HAZARD_INFORMATION", **overrides: Any):
    return _merge({"trigger_reason": trigger_reason}, overrides)


def exemption_claim_payload(exemption_type: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "action": "CLAIM",
            "exemption_type": exemption_type,
            "basis_note": (
                "Importer holds written assurance that this regulatory control applies"
            ),
        },
        overrides,
    )


def exemption_determination_payload(action: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "action": action,
            "determination_note": (
                "Exemption reviewed against the product code and process category"
            ),
        },
        overrides,
    )


# --- HazardAnalysis / Hazard -----------------------------------------------
def hazard_analysis_payload(pair_id: str, expected_pair_version: int, **overrides: Any):
    return _merge(
        {
            "pair_id": pair_id,
            "expected_pair_version": expected_pair_version,
            "methodology_note": "Codex hazard identification for this food and supplier",
        },
        overrides,
    )


def hazard_payload(
    hazard_type: str = "BIOLOGICAL",
    severity: int = 4,
    probability: int = 3,
    control_owner: str = "FOREIGN_SUPPLIER",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "hazard_type": hazard_type,
            "hazard_name": "Listeria monocytogenes",
            "severity": severity,
            "probability": probability,
            "control_owner": control_owner,
        },
        overrides,
    )


def hazard_analysis_approval_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "approval_note": (
                "Hazard analysis complete for this supplier and food combination"
            )
        },
        overrides,
    )


# --- VerificationActivity ---------------------------------------------------
def activity_payload(
    pair_id: str,
    assigned_qi_id: str,
    activity_type: str = "ONSITE_AUDIT",
    frequency_per_year: int = 1,
    window_start: str = "2026-09-10T00:00:00Z",
    window_end: str = "2026-09-20T00:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "pair_id": pair_id,
            "activity_type": activity_type,
            "frequency_per_year": frequency_per_year,
            "justification_text": (
                "Annual onsite audit of the foreign supplier for pathogen control"
            ),
            "window_start": window_start,
            "window_end": window_end,
            "assigned_qi_id": assigned_qi_id,
        },
        overrides,
    )


def activity_review_payload(decision: str = "APPROVE", **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "decision": decision,
            "reviewer_note": "Activity scope and frequency reviewed by a second individual",
        },
        overrides,
    )


# --- VerificationRecord -----------------------------------------------------
def record_payload(
    activity_id: str,
    outcome: str = "PASS",
    performed_start: str = "2026-09-12T00:00:00Z",
    performed_end: str = "2026-09-14T00:00:00Z",
    findings_count: int = 0,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "activity_id": activity_id,
            "outcome": outcome,
            "performed_start": performed_start,
            "performed_end": performed_end,
            "findings_count": findings_count,
            "document_reference": "AUD-2026-0912-RV",
        },
        overrides,
    )


def attestation_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {"attestation_note": "Verification document reviewed and admitted"}, overrides
    )


def rescission_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {"reason": "Laboratory withdrew the certificate for this verification record"},
        overrides,
    )


# --- CorrectiveAction -------------------------------------------------------
def corrective_action_decision_payload(
    decision: str, expected_supplier_version: int, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "decision": decision,
            "rationale": (
                "Supplier failed onsite verification and cannot show adequate hazard control"
            ),
            "expected_supplier_version": expected_supplier_version,
        },
        overrides,
    )


def corrective_action_closure_payload(action: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "action": action,
            "closure_note": "Corrective action closed by the compliance office of record",
        },
        overrides,
    )


# --- EntrySubmission --------------------------------------------------------
def entry_submission_payload(
    pair_id: str,
    dnb_number_submitted: str = IMPORTER_DNB,
    ufi_submitted: str = IMPORTER_UFI,
    entry_number: str = "ENT2026001",
    entry_line_number: int = 1,
    arrival_date: str = "2026-09-25T00:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "pair_id": pair_id,
            "entry_number": entry_number,
            "entry_line_number": entry_line_number,
            "dnb_number_submitted": dnb_number_submitted,
            "ufi_submitted": ufi_submitted,
            "arrival_date": arrival_date,
        },
        overrides,
    )
