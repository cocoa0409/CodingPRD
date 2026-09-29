"""Payload factories — one per resource, carrying only client-supplied fields.

The canonical HLA triple below is shared by every composite setup helper:

  * ``RECIPIENT_HLA``          — the recipient's allele-level typing
  * ``DONOR_HLA_REGISTRY``     — registry-level typing with locus C antigen-level
                                (the donor therefore declares ambiguous_loci ["C"])
  * ``REPORTED_HLA_ALLELE``    — the allele-level typing the registry reports back

Against ``RECIPIENT_HLA`` this donor scores 94.75 preliminary / 98.25 confirmed
and grades 9/10, i.e. it clears the nine-of-ten admission floor.
"""
import copy
import itertools

RECIPIENT_HLA = {
    "A": ["01:01", "02:01"],
    "B": ["07:02", "08:01"],
    "C": ["07:02", "07:04"],
    "DRB1": ["15:01", "03:01"],
    "DQB1": ["06:02", "02:01"],
}

DONOR_HLA_REGISTRY = {
    "A": ["01:01", "02:01"],
    "B": ["07:02", "08:01"],
    "C": ["07", "07"],
    "DRB1": ["15:01", "03:01"],
    "DQB1": ["06:02", "05:01"],
}

REPORTED_HLA_ALLELE = {
    "A": ["01:01", "02:01"],
    "B": ["07:02", "08:01"],
    "C": ["07:02", "07:04"],
    "DRB1": ["15:01", "03:01"],
    "DQB1": ["06:02", "05:01"],
}

# An allele-level donor typing identical to the recipient at every locus: a
# ten-of-ten donor with no ambiguity at all.
DONOR_HLA_FULL_ALLELE = copy.deepcopy(RECIPIENT_HLA)

# A reported typing whose locus A carries an antigen-level string.
REPORTED_HLA_ANTIGEN_LEVEL = {
    "A": ["01", "02:01"],
    "B": ["07:02", "08:01"],
    "C": ["07:02", "07:04"],
    "DRB1": ["15:01", "03:01"],
    "DQB1": ["06:02", "05:01"],
}

_seq = itertools.count(1)


def unique_suffix() -> str:
    """Monotonic suffix for codes that must be unique within one test."""
    return f"{next(_seq):04d}"


def hla(**overrides) -> dict:
    """A deep copy of the recipient typing with per-locus overrides."""
    typing = copy.deepcopy(RECIPIENT_HLA)
    typing.update(overrides)
    return typing


def create_registry_payload(**overrides) -> dict:
    defaults = {
        "code": f"NMDP-{unique_suffix()}",
        "name": "National Marrow Donor Program",
        "country_code": "US",
        "currency_code": "USD",
        "fx_rate_to_usd": 1.0000,
        "is_domestic": True,
        "cooperation_tier": 1,
        "ct_response_deadline_hours": 168,
    }
    defaults.update(overrides)
    return defaults


def create_international_registry_payload(**overrides) -> dict:
    defaults = {
        "code": f"DKMS-{unique_suffix()}",
        "name": "DKMS Germany",
        "country_code": "DE",
        "currency_code": "EUR",
        "fx_rate_to_usd": 1.0850,
        "is_domestic": False,
        "cooperation_tier": 2,
        "ct_response_deadline_hours": 168,
    }
    defaults.update(overrides)
    return defaults


def create_collection_center_payload(**overrides) -> dict:
    defaults = {
        "name": "Metro Apheresis Center",
        "country_code": "US",
        "concurrent_collection_capacity": 1,
    }
    defaults.update(overrides)
    return defaults


def create_patient_payload(**overrides) -> dict:
    defaults = {
        "mrn": f"MRN-{unique_suffix()}",
        "transplant_center_code": "TC-01",
        "country_code": "US",
        "diagnosis_code": "AML",
        "urgency_tier": "HIGH",
        "weight_kg": 70.0,
        "cmv_status": "POSITIVE",
        "hla_typing": copy.deepcopy(RECIPIENT_HLA),
        "case_budget_cents": 5_000_000,
    }
    defaults.update(overrides)
    return defaults


def create_donor_payload(registry_id, **overrides) -> dict:
    defaults = {
        "registry_id": registry_id,
        "donor_code": f"D-{unique_suffix()}",
        "age_years": 27,
        "sex": "F",
        "weight_kg": 68.0,
        "cmv_status": "POSITIVE",
        "hla_typing_registry": copy.deepcopy(DONOR_HLA_REGISTRY),
        "consented_methods": ["PBSC", "MARROW"],
        "ambiguous_loci": ["C"],
        "prior_donation_count": 0,
    }
    defaults.update(overrides)
    return defaults


def create_search_request_payload(patient_id, **overrides) -> dict:
    defaults = {
        "patient_id": patient_id,
        "search_scope": "DOMESTIC_ONLY",
    }
    defaults.update(overrides)
    return defaults


def create_typing_request_payload(**overrides) -> dict:
    defaults = {"priority_flag": False}
    defaults.update(overrides)
    return defaults


def typing_response_payload(**overrides) -> dict:
    defaults = {
        "reported_hla_typing": copy.deepcopy(REPORTED_HLA_ALLELE),
        "donor_available_flag": True,
    }
    defaults.update(overrides)
    return defaults


def screening_payload(**overrides) -> dict:
    defaults = {"outcome": "PASS", "deferral_type": "NONE"}
    defaults.update(overrides)
    return defaults


def clearance_result_payload(**overrides) -> dict:
    defaults = {"result": "PASS"}
    defaults.update(overrides)
    return defaults


def collection_method_payload(**overrides) -> dict:
    defaults = {"method": "PBSC", "rationale": "Apheresis selected with the donor"}
    defaults.update(overrides)
    return defaults


def create_booking_payload(workup_case_id, collection_center_id, start_at,
                           expected_workup_case_version, **overrides) -> dict:
    defaults = {
        "workup_case_id": workup_case_id,
        "collection_center_id": collection_center_id,
        "start_at": start_at,
        "expected_workup_case_version": expected_workup_case_version,
    }
    defaults.update(overrides)
    return defaults


def cancel_booking_payload(**overrides) -> dict:
    defaults = {"reason": "Donor requested a different date"}
    defaults.update(overrides)
    return defaults


def create_shipment_payload(**overrides) -> dict:
    defaults = {
        "collected_cd34_e6_per_kg": 5.20,
        "collected_volume_ml": 320.0,
        "courier_reference": f"CR-{unique_suffix()}",
    }
    defaults.update(overrides)
    return defaults


def shipment_event_payload(event_type, **overrides) -> dict:
    defaults = {"event_type": event_type}
    defaults.update(overrides)
    return defaults


def create_unavailability_window_payload(date_from, date_to, reason="PERSONAL",
                                         **overrides) -> dict:
    defaults = {"date_from": date_from, "date_to": date_to, "reason": reason}
    defaults.update(overrides)
    return defaults


def create_follow_up_payload(event_type="DAY_7_CONTACT", severity_grade=0,
                             **overrides) -> dict:
    defaults = {"event_type": event_type, "severity_grade": severity_grade}
    defaults.update(overrides)
    return defaults


def conditioning_payload(action, expected_patient_version, **overrides) -> dict:
    defaults = {"action": action, "expected_patient_version": expected_patient_version}
    defaults.update(overrides)
    return defaults
