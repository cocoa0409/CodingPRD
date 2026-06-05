"""Payload factories — one per entity, input fields only.

Each factory provides PRD-valid defaults and accepts **overrides. Only fields
the client legitimately supplies (PRD §3) appear here; system/computed fields
are never sent.
"""

# Reusable sensible defaults.
DEFAULT_HLA_A = ["A1", "A2"]
DEFAULT_HLA_B = ["B7", "B8"]
DEFAULT_HLA_DR = ["DR1", "DR2"]
DEFAULT_CLOCK = "2026-06-01T00:00:00Z"


def create_transplant_center_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Center",
        "unos_center_code": "C001",
        "region_code": 5,
        "latitude": 41.8,
        "longitude": -87.6,
    }
    defaults.update(overrides)
    return defaults


def create_opo_payload(**overrides) -> dict:
    defaults = {
        "name": "Test OPO",
        "opo_code": "OPO5",
        "region_code": 5,
        "latitude": 41.8,
        "longitude": -87.6,
    }
    defaults.update(overrides)
    return defaults


def create_candidate_payload(center_id: str, **overrides) -> dict:
    defaults = {
        "center_id": center_id,
        "mrn": "MRN001",
        "organ_type": "LIVER",
        "blood_type": "O",
        "date_of_birth": "1980-01-01T00:00:00Z",
        "height_cm": 175,
        "weight_kg": 75,
        "hla_a": list(DEFAULT_HLA_A),
        "hla_b": list(DEFAULT_HLA_B),
        "hla_dr": list(DEFAULT_HLA_DR),
    }
    defaults.update(overrides)
    return defaults


def create_clinical_score_payload(**overrides) -> dict:
    """Adult-typical lab panel; overrides drive the formula branches."""
    defaults = {
        "bilirubin_mg_dl": 4.0,
        "inr": 2.0,
        "creatinine_mg_dl": 2.0,
        "sodium_mmol_l": 130,
        "albumin_g_dl": 3.0,
        "effective_at": DEFAULT_CLOCK,
    }
    defaults.update(overrides)
    return defaults


def create_donor_organ_payload(opo_id: str, **overrides) -> dict:
    defaults = {
        "opo_id": opo_id,
        "organ_type": "LIVER",
        "blood_type": "O",
        "donor_height_cm": 180,
        "donor_weight_kg": 85,
        "hla_a": list(DEFAULT_HLA_A),
        "hla_b": list(DEFAULT_HLA_B),
        "hla_dr": list(DEFAULT_HLA_DR),
        "recovered_at": DEFAULT_CLOCK,
        "max_cold_ischemia_hours": 10,
    }
    defaults.update(overrides)
    return defaults


def create_match_run_payload(donor_organ_id: str, expected_donor_organ_version: int,
                             policy_code: str = "STANDARD", **overrides) -> dict:
    defaults = {
        "donor_organ_id": donor_organ_id,
        "expected_donor_organ_version": expected_donor_organ_version,
        "policy_code": policy_code,
    }
    defaults.update(overrides)
    return defaults


def create_offer_payload(donor_organ_id: str, candidate_id: str, match_run_id: str,
                         expected_donor_organ_version: int, **overrides) -> dict:
    defaults = {
        "donor_organ_id": donor_organ_id,
        "candidate_id": candidate_id,
        "match_run_id": match_run_id,
        "expected_donor_organ_version": expected_donor_organ_version,
    }
    defaults.update(overrides)
    return defaults


def offer_next_payload(expected_donor_organ_version: int, **overrides) -> dict:
    defaults = {"expected_donor_organ_version": expected_donor_organ_version}
    defaults.update(overrides)
    return defaults


def accept_offer_payload(expected_donor_organ_version: int, **overrides) -> dict:
    defaults = {"expected_donor_organ_version": expected_donor_organ_version}
    defaults.update(overrides)
    return defaults


def decline_offer_payload(decline_reason: str = "CENTER_DECLINE", **overrides) -> dict:
    defaults = {"decline_reason": decline_reason}
    defaults.update(overrides)
    return defaults


def remove_candidate_payload(removal_reason: str = "OTHER", **overrides) -> dict:
    defaults = {"removal_reason": removal_reason}
    defaults.update(overrides)
    return defaults


def create_transplant_payload(offer_id: str, transplanted_at: str, **overrides) -> dict:
    defaults = {
        "offer_id": offer_id,
        "transplanted_at": transplanted_at,
    }
    defaults.update(overrides)
    return defaults


def create_follow_up_payload(interval_label: str = "M1",
                             scheduled_for: str = "2026-07-01T00:00:00Z",
                             **overrides) -> dict:
    defaults = {
        "interval_label": interval_label,
        "scheduled_for": scheduled_for,
    }
    defaults.update(overrides)
    return defaults


def create_unos_report_payload(report_kind: str, **overrides) -> dict:
    defaults = {"report_kind": report_kind}
    defaults.update(overrides)
    return defaults


def reject_unos_report_payload(rejection_reason: str = "incomplete documentation",
                               **overrides) -> dict:
    defaults = {"rejection_reason": rejection_reason}
    defaults.update(overrides)
    return defaults


def set_clock_payload(to_iso8601: str, **overrides) -> dict:
    defaults = {"to_iso8601": to_iso8601}
    defaults.update(overrides)
    return defaults
