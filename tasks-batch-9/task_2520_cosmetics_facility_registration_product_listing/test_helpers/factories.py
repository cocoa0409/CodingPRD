"""Payload builders. Every factory returns a valid payload that keyword
arguments can override, so a test can express exactly the one field it is
interested in.
"""

from typing import Any, Dict, List, Optional

from . import constants as K


def facility_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {
        "facility_name": "Harbour Lane Cosmetics Works",
        "owner_operator_name": "Harbour Lane Holdings LLC",
        "facility_type": "MANUFACTURER",
        "country_code": "US",
        "state_or_province": "NJ",
    }
    payload.update(overrides)
    return payload


def registration_decision_payload(decision: str = "APPROVE", **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    payload.update(overrides)
    return payload


def renewal_payload(renewal_kind: str = K.RENEWAL_KIND_STANDARD, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"renewal_kind": renewal_kind}
    payload.update(overrides)
    return payload


def ownership_change_payload(expected_facility_version: int,
                            change_effective_date: str = K.DEFAULT_CLOCK_DATE,
                            **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "new_owner_operator_name": "Seaboard Personal Care Inc",
        "change_effective_date": change_effective_date,
        "expected_facility_version": expected_facility_version,
    }
    payload.update(overrides)
    return payload


def ownership_decision_payload(decision: str = "ACCEPT", **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    payload.update(overrides)
    return payload


def responsible_person_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "legal_name": "Meridian Label Services LLC",
        "us_address_line": "1200 Beacon Street, Suite 410, Boston MA 02215",
        "contact_phone": "+1-617-555-0142",
        "contact_email": "intake@meridianlabel.example",
    }
    payload.update(overrides)
    return payload


def listing_payload(facility_id: str, responsible_person_id: str,
                    **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "facility_id": facility_id,
        "responsible_person_id": responsible_person_id,
        "product_name": "Tidewater Daily Blush",
        "category_code": "07A",
        "product_form": K.PRODUCT_FORM_LEAVE_ON,
        "label_contact_type": K.LABEL_CONTACT_DOMESTIC_ADDRESS,
        "label_contact_value": "1200 Beacon Street, Suite 410, Boston MA 02215",
    }
    payload.update(overrides)
    return payload


def professional_listing_payload(facility_id: str, responsible_person_id: str,
                                 **overrides: Any) -> Dict[str, Any]:
    """A professional-use-only listing under a professional-use-permitted code."""
    payload = listing_payload(
        facility_id,
        responsible_person_id,
        product_name="Atelier Professional Skin Peel",
        category_code="11E",
        professional_use_only=True,
        professional_use_statement_present=True,
    )
    payload.update(overrides)
    return payload


def ingredient_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "inci_name": "GLYCERIN",
        "function_code": "OTHER",
        "concentration_pct": 2.5000,
    }
    payload.update(overrides)
    return payload


def allergen_ingredient_payload(inci_name: str = "LINALOOL",
                                concentration_pct: float = 0.0010,
                                label_disclosed: bool = False,
                                **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "inci_name": inci_name,
        "function_code": "FRAGRANCE",
        "concentration_pct": concentration_pct,
        "is_fragrance_allergen": True,
        "label_disclosed": label_disclosed,
    }
    payload.update(overrides)
    return payload


def data_gap_ingredient_payload(**overrides: Any) -> Dict[str, Any]:
    payload = ingredient_payload(
        inci_name="PHENOXYETHANOL",
        function_code="PRESERVATIVE",
        concentration_pct=0.8000,
        is_data_gap_flag=True,
    )
    payload.update(overrides)
    return payload


def substantiation_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "assessor_name": "Dr. Ingrid Halvorsen",
        "assessment_basis": K.ASSESSMENT_BASIS_PRODUCT_SPECIFIC,
    }
    payload.update(overrides)
    return payload


def review_item_payload(evidence_type: str = K.EVIDENCE_CLINICAL,
                        reviewer_credential: str = K.CREDENTIAL_BOARD_CERTIFIED,
                        **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "evidence_type": evidence_type,
        "reviewer_credential": reviewer_credential,
        "citation": "Halvorsen I. et al., Journal of Cosmetic Safety 2025;18:220-234",
    }
    payload.update(overrides)
    return payload


def review_decision_payload(review_mode: str = K.REVIEW_MODE_SCREENING,
                            **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"review_mode": review_mode}
    payload.update(overrides)
    return payload


def listing_decision_payload(decision: str = "LIST", **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    payload.update(overrides)
    return payload


def transfer_payload(responsible_person_id: str, expected_listing_version: int,
                     **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "responsible_person_id": responsible_person_id,
        "expected_listing_version": expected_listing_version,
    }
    payload.update(overrides)
    return payload


def adverse_event_payload(received_at: str = K.DEFAULT_CLOCK_UTC,
                          seriousness: str = K.SERIOUSNESS_SERIOUS,
                          **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "event_description": "Consumer reported contact dermatitis after two applications.",
        "received_at": received_at,
        "seriousness": seriousness,
    }
    payload.update(overrides)
    return payload


def report_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "report_narrative": "Batch investigation completed; consumer contacted and advised.",
    }
    payload.update(overrides)
    return payload


def reclassify_payload(seriousness: str = K.SERIOUSNESS_SERIOUS,
                       **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"seriousness": seriousness}
    payload.update(overrides)
    return payload


def inspection_payload(window_start: str, window_end: str,
                       inspection_type: str = K.INSPECTION_TYPE_GMP_ROUTINE,
                       **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "inspection_type": inspection_type,
        "window_start": window_start,
        "window_end": window_end,
    }
    payload.update(overrides)
    return payload


def observation(category: str, severity: str) -> Dict[str, str]:
    return {"category": category, "severity": severity}


def observations_payload(observations: Optional[List[Dict[str, str]]] = None,
                         **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"observations": observations if observations is not None else []}
    payload.update(overrides)
    return payload


def repeated_observations(category: str, severity: str, count: int) -> List[Dict[str, str]]:
    return [observation(category, severity) for _ in range(count)]


def inspection_response_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "response_summary": "Corrective actions scheduled for all cited categories.",
    }
    payload.update(overrides)
    return payload


def recall_action_payload(initiation_basis: str = K.INITIATION_BASIS_VOLUNTARY,
                          hazard_class: str = "CLASS_II",
                          **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "initiation_basis": initiation_basis,
        "hazard_class": hazard_class,
    }
    payload.update(overrides)
    return payload


def recall_plan_payload(distribution_depth: str = K.DEPTH_RETAIL,
                        **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "corrective_summary": "Retail-level retrieval with consignee notification letters.",
        "distribution_depth": distribution_depth,
    }
    payload.update(overrides)
    return payload


def plan_decision_payload(decision: str = "ACCEPT", **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    payload.update(overrides)
    return payload


def withdrawal_payload(expected_recall_action_version: int,
                       scope_depth: str = K.DEPTH_RETAIL,
                       **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "scope_depth": scope_depth,
        "expected_recall_action_version": expected_recall_action_version,
    }
    payload.update(overrides)
    return payload


def distribution_record_payload(lot_code: str = "LOT-A",
                                ship_date: str = "2026-08-10",
                                delivery_date: str = "2026-08-15",
                                units_shipped: int = 600,
                                **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "lot_code": lot_code,
        "consignee_name": "Northline Beauty Distributors",
        "consignee_class": K.DEPTH_WHOLESALE,
        "ship_date": ship_date,
        "delivery_date": delivery_date,
        "units_shipped": units_shipped,
    }
    payload.update(overrides)
    return payload


def records_production_payload(distribution_record_ids: List[str],
                               **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"distribution_record_ids": distribution_record_ids}
    payload.update(overrides)
    return payload


def recovery_entry_payload(distribution_record_id: str, units: int,
                           entry_kind: str = K.ENTRY_KIND_VERIFIED_RETURN,
                           **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "entry_kind": entry_kind,
        "distribution_record_id": distribution_record_id,
        "units": units,
    }
    payload.update(overrides)
    return payload


def reversal_entry_payload(distribution_record_id: str, units: int,
                           reversal_target_bucket: str = K.BUCKET_VERIFIED_RETURNED,
                           **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "entry_kind": K.ENTRY_KIND_CORRECTION_REVERSAL,
        "distribution_record_id": distribution_record_id,
        "units": units,
        "reversal_target_bucket": reversal_target_bucket,
    }
    payload.update(overrides)
    return payload


def effectiveness_check_payload(basis: str = K.BASIS_VERIFIED, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"basis": basis}
    payload.update(overrides)
    return payload
