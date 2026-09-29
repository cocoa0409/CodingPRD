"""Request-payload factories.

Each factory returns only the input fields the PRD lets a client supply, with valid
defaults, and accepts keyword overrides. Server-assigned and derived fields are never
included.
"""
import itertools

_counter = itertools.count(1)


def unique_suffix():
    """A short suffix that keeps natural keys unique inside one test."""
    return f"{next(_counter):04d}"


# --------------------------------------------------------------------------- #
# ProductModel (PRD §3.1)
# --------------------------------------------------------------------------- #
def product_model_payload(**overrides):
    payload = {
        "model_code": f"MDL-{unique_suffix()}",
        "product_family": "AURORA",
        "market_release_date": "2025-01-15T00:00:00Z",
        "repairability_tier": "TIER_A_SELF_SERVICE",
    }
    payload.update(overrides)
    return payload


def end_production_payload(**overrides):
    payload = {"end_of_production_date": "2024-06-30T00:00:00Z"}
    payload.update(overrides)
    return payload


def end_support_payload(**overrides):
    payload = {"support_end_date": "2026-06-30T00:00:00Z"}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------- #
# RegionalComplianceProfile (PRD §3.2)
# --------------------------------------------------------------------------- #
def compliance_profile_payload(**overrides):
    payload = {
        "region_code": f"R{unique_suffix()}",
        "min_parts_availability_years": 7,
        "min_documentation_years": 7,
        "requires_public_manual": False,
        "max_documentation_fee_cents": 2000,
        "allows_pairing_restriction": True,
        "self_service_mandate_tier": "MANDATE_FULL",
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------- #
# ComplianceObligation (PRD §3.2)
# --------------------------------------------------------------------------- #
def compliance_obligation_payload(model_id, region_code, **overrides):
    payload = {"model_id": model_id, "region_code": region_code}
    payload.update(overrides)
    return payload


def attestation_payload(**overrides):
    payload = {
        "attestation_note": "Documentation reviewed and confirmed published.",
        "documentation_verified": True,
    }
    payload.update(overrides)
    return payload


def compliance_sweep_payload(**overrides):
    payload = {}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------- #
# PartCatalogItem (PRD §3.3)
# --------------------------------------------------------------------------- #
def part_catalog_item_payload(**overrides):
    payload = {
        "sku": f"SKU-{unique_suffix()}",
        "part_class": "COMPONENT",
        "safety_class": "UNRESTRICTED",
        "list_price_cents": 1000,
        "core_return_required": False,
    }
    payload.update(overrides)
    return payload


def supersession_payload(supersedes_part_id, **overrides):
    payload = {
        "supersedes_part_id": supersedes_part_id,
        "supersession_note": "Predecessor re-pointed after catalogue rework.",
    }
    payload.update(overrides)
    return payload


def restriction_payload(**overrides):
    payload = {
        "safety_class": "SAFETY_RESTRICTED_HIGH_VOLTAGE",
        "restriction_reason": "Field incidents reported on high-voltage board.",
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------- #
# PartModelCompatibility (PRD §3.3)
# --------------------------------------------------------------------------- #
def part_compatibility_payload(part_id, model_id, **overrides):
    payload = {
        "part_id": part_id,
        "model_id": model_id,
        "effective_from": "2025-02-01T00:00:00Z",
        "self_service_eligible": True,
        "install_minutes": 60,
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------- #
# ManualRevision (PRD §3.4)
# --------------------------------------------------------------------------- #
def manual_revision_payload(model_id, expected_model_version, **overrides):
    payload = {
        "model_id": model_id,
        "doc_type": "DISASSEMBLY_GUIDE",
        "covered_part_skus": [],
        "safety_warning_count": 3,
        "expected_model_version": expected_model_version,
    }
    payload.update(overrides)
    return payload


def review_decision_payload(decision="APPROVE", **overrides):
    payload = {"decision": decision, "review_note": "Reviewed against bench procedure."}
    payload.update(overrides)
    return payload


def publish_revision_payload(**overrides):
    payload = {}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------- #
# EligibilityAssessment (PRD §3.5)
# --------------------------------------------------------------------------- #
def eligibility_assessment_payload(model_id, part_id, region_code, **overrides):
    payload = {
        "model_id": model_id,
        "part_id": part_id,
        "region_code": region_code,
        "requester_class": "SELF_REPAIR_CONSUMER",
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------- #
# PartsOrder (PRD §3.6)
# --------------------------------------------------------------------------- #
def parts_order_payload(assessment_id, region_code, **overrides):
    payload = {
        "assessment_id": assessment_id,
        "region_code": region_code,
        "buyer_class": "SELF_REPAIR_CONSUMER",
    }
    payload.update(overrides)
    return payload


def order_line_payload(part_id, expected_order_version, quantity=1, **overrides):
    payload = {
        "part_id": part_id,
        "quantity": quantity,
        "expected_order_version": expected_order_version,
    }
    payload.update(overrides)
    return payload


def acknowledgment_payload(
    warranty_impact_class_ack,
    liability_warning_version,
    acknowledged_scope="FULL_SELF_REPAIR",
    **overrides,
):
    payload = {
        "warranty_impact_class_ack": warranty_impact_class_ack,
        "liability_warning_version": liability_warning_version,
        "acknowledged_scope": acknowledged_scope,
    }
    payload.update(overrides)
    return payload


def cancellation_payload(**overrides):
    payload = {"cancellation_reason": "Buyer no longer needs the part."}
    payload.update(overrides)
    return payload


def core_return_payload(received_at, core_condition="INTACT", **overrides):
    payload = {"core_condition": core_condition, "received_at": received_at}
    payload.update(overrides)
    return payload


def authenticate_payload(pairing_token, **overrides):
    payload = {"pairing_token": pairing_token}
    payload.update(overrides)
    return payload


def calibrate_payload(measured_offset_ppm, **overrides):
    payload = {"measured_offset_ppm": measured_offset_ppm}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------- #
# RepairProvider (PRD §3.8)
# --------------------------------------------------------------------------- #
def repair_provider_payload(region_code, **overrides):
    payload = {
        "legal_name": f"Independent Repairs {unique_suffix()} Ltd",
        "region_code": region_code,
        "requested_access_tier": "TIER_1_UNRESTRICTED",
        "technician_count": 4,
    }
    payload.update(overrides)
    return payload


def begin_training_payload(training_credit_grant=8, **overrides):
    payload = {"training_credit_grant": training_credit_grant}
    payload.update(overrides)
    return payload


def authorization_decision_payload(decision="AUTHORIZE", **overrides):
    payload = {"decision": decision, "decision_reason": "Coverage and score reviewed."}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------- #
# TrainingCertification (PRD §3.8)
# --------------------------------------------------------------------------- #
def training_certification_payload(provider_id, technician_user_id, **overrides):
    payload = {
        "provider_id": provider_id,
        "technician_user_id": technician_user_id,
        "course_code": "CRS_GENERAL_REPAIR",
        "valid_from": "2026-07-01T00:00:00Z",
        "valid_until": "2027-07-01T00:00:00Z",
        "exam_score": 90,
    }
    payload.update(overrides)
    return payload


def void_certification_payload(**overrides):
    payload = {"void_reason": "Filed against the wrong technician."}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------- #
# DefectiveReturnCase (PRD §3.9)
# --------------------------------------------------------------------------- #
def defective_return_payload(order_line_id, quantity=1, **overrides):
    payload = {
        "order_line_id": order_line_id,
        "reported_failure_code": "NO_POWER",
        "quantity": quantity,
    }
    payload.update(overrides)
    return payload


def receive_defective_return_payload(**overrides):
    payload = {}
    payload.update(overrides)
    return payload


def failure_analysis_payload(root_cause_code="MANUFACTURING_DEFECT", defect_confirmed=True, **overrides):
    payload = {
        "root_cause_code": root_cause_code,
        "defect_confirmed": defect_confirmed,
        "analysis_note": "Bench analysis reproduced the reported symptom.",
    }
    payload.update(overrides)
    return payload


def credit_decision_payload(decision="ISSUE_CREDIT", **overrides):
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------- #
# Logical clock (PRD §2.4)
# --------------------------------------------------------------------------- #
def clock_payload(to_iso8601, **overrides):
    payload = {"to_iso8601": to_iso8601}
    payload.update(overrides)
    return payload
