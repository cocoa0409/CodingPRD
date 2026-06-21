"""Payload factories — one per creatable resource, input fields only.

Each factory returns a dict of the request-body fields the PRD declares as input
for the corresponding create endpoint; pass **overrides to control any value.
"""

DEFAULTS = {
    "MOTHER_NAME": "Pat Doe",
    "MOTHER_DOB": "1992-05-01",
    "DUE_DATE": "2026-03-12",
    "FACILITY": "Mercy",
    "CARRIER": "EmpCo",
    "SUBSCRIBER": "Pat Doe",
    "COVERAGE_DATE": "2026-01-01",
    "BIRTH_DATETIME": "2026-03-05T10:00:00Z",
    "BED_LABEL": "NICU-1",
}


def create_insurance_policy_payload(**overrides) -> dict:
    payload = {
        "carrier_name": DEFAULTS["CARRIER"],
        "subscriber_name": DEFAULTS["SUBSCRIBER"],
        "plan_type": "EMPLOYER_GROUP",
        "coverage_effective_date": DEFAULTS["COVERAGE_DATE"],
        "dependent_slots_max": 3,
    }
    payload.update(overrides)
    return payload


def create_registration_payload(payer_policy_id, **overrides) -> dict:
    payload = {
        "mother_full_name": DEFAULTS["MOTHER_NAME"],
        "mother_dob": DEFAULTS["MOTHER_DOB"],
        "due_date": DEFAULTS["DUE_DATE"],
        "payer_policy_id": payer_policy_id,
        "planned_delivery_facility": DEFAULTS["FACILITY"],
    }
    payload.update(overrides)
    return payload


def record_birth_payload(**overrides) -> dict:
    """A healthy singleton: clear of NICU criteria (ga 39, apgar 9, weight 3200)."""
    payload = {
        "birth_datetime": DEFAULTS["BIRTH_DATETIME"],
        "birth_sequence": 1,
        "weight_grams": 3200,
        "gestational_age_weeks": 39,
        "apgar_5min": 9,
    }
    payload.update(overrides)
    return payload


def create_lactation_consult_payload(newborn_id, consult_datetime, **overrides) -> dict:
    payload = {"newborn_id": newborn_id, "consult_datetime": consult_datetime}
    payload.update(overrides)
    return payload


def create_nicu_bed_payload(**overrides) -> dict:
    payload = {"bed_label": DEFAULTS["BED_LABEL"], "acuity_level": "LEVEL_3"}
    payload.update(overrides)
    return payload


def nicu_escalate_payload(expected_newborn_version, **overrides) -> dict:
    payload = {
        "required_level": "LEVEL_3",
        "admitted_at": "2026-03-05T11:00:00Z",
        "expected_newborn_version": expected_newborn_version,
    }
    payload.update(overrides)
    return payload


def assign_stay_payload(nicu_stay_id, **overrides) -> dict:
    payload = {"nicu_stay_id": nicu_stay_id}
    payload.update(overrides)
    return payload


def create_discharge_bag_payload(newborn_id, line_items=None, **overrides) -> dict:
    if line_items is None:
        line_items = [{"sku": "FORM-A", "category": "FORMULA", "qty": 2, "unit_value_cents": 1299}]
    payload = {"newborn_id": newborn_id, "line_items": line_items}
    payload.update(overrides)
    return payload


def complete_consult_payload(latch_score, **overrides) -> dict:
    payload = {"latch_score": latch_score}
    payload.update(overrides)
    return payload


def issue_bag_payload(**overrides) -> dict:
    payload = {}
    payload.update(overrides)
    return payload


def record_attempt_payload(scheduled_at=None, **overrides) -> dict:
    payload = {}
    if scheduled_at is not None:
        payload["scheduled_at"] = scheduled_at
    payload.update(overrides)
    return payload


def create_dependent_enrollment_payload(newborn_id, policy_id, requested_at, **overrides) -> dict:
    payload = {"newborn_id": newborn_id, "policy_id": policy_id, "requested_at": requested_at}
    payload.update(overrides)
    return payload


def approve_enrollment_payload(expected_policy_version, **overrides) -> dict:
    payload = {"expected_policy_version": expected_policy_version}
    payload.update(overrides)
    return payload


def create_government_filing_payload(newborn_id, filing_type, **overrides) -> dict:
    payload = {"newborn_id": newborn_id, "filing_type": filing_type}
    payload.update(overrides)
    return payload


def acknowledge_filing_payload(outcome, reference_number=None, **overrides) -> dict:
    payload = {"outcome": outcome}
    if reference_number is not None:
        payload["reference_number"] = reference_number
    payload.update(overrides)
    return payload
