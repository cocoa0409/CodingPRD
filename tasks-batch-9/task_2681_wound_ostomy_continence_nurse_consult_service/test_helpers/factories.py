"""Payload factories — one per resource, carrying only client-supplied fields."""
import itertools

_SEQ = itertools.count(1)


def next_seq() -> int:
    """Monotonic counter used to keep natural keys unique within one test."""
    return next(_SEQ)


def unit_code(prefix: str = "U") -> str:
    """A unit_code honouring the uppercase/digit/hyphen 2-12 character rule."""
    return f"{prefix}{next_seq():04d}"[:12].upper()


def mrn(prefix: str = "MRN") -> str:
    """An mrn honouring the 6-16 character rule."""
    return f"{prefix}{next_seq():06d}"


def asset_tag(prefix: str = "TAG") -> str:
    """An asset_tag honouring the 3-24 character rule."""
    return f"{prefix}-{next_seq():05d}"


def sku(prefix: str = "SKU") -> str:
    """A sku honouring the 3-24 character rule."""
    return f"{prefix}-{next_seq():05d}"


def create_unit_payload(**overrides) -> dict:
    payload = {
        "unit_code": unit_code(),
        "name": "Medical Surgical Ward",
        "bed_count": 24,
        "rental_budget_cap_cents": 500000,
    }
    payload.update(overrides)
    return payload


def budget_adjustment_payload(delta_cents: int, **overrides) -> dict:
    payload = {"delta_cents": delta_cents, "reason": "Quarterly rental budget revision"}
    payload.update(overrides)
    return payload


def create_patient_payload(unit_id: str, **overrides) -> dict:
    payload = {
        "mrn": mrn(),
        "unit_id": unit_id,
        "admitted_at": "2026-08-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def discharge_patient_payload(discharged_at: str, **overrides) -> dict:
    payload = {"discharged_at": discharged_at}
    payload.update(overrides)
    return payload


def create_woc_nurse_payload(home_unit_id: str, **overrides) -> dict:
    payload = {
        "full_name": "Dana Whitfield",
        "home_unit_id": home_unit_id,
        "ce_credits": 30,
    }
    payload.update(overrides)
    return payload


def competency_signoff_payload(
    signed_off_at: str = "2026-08-01T00:00:00Z", **overrides
) -> dict:
    payload = {
        "signed_off_at": signed_off_at,
        "competency_domain": "PRESSURE_INJURY_STAGING",
    }
    payload.update(overrides)
    return payload


def certify_payload(
    cert_expires_at: str = "2028-08-01T00:00:00Z", **overrides
) -> dict:
    payload = {"cert_expires_at": cert_expires_at}
    payload.update(overrides)
    return payload


def lapse_payload(**overrides) -> dict:
    payload = {"reason": "Certification renewal window missed"}
    payload.update(overrides)
    return payload


def create_consult_request_payload(
    patient_id: str, requesting_unit_id: str, **overrides
) -> dict:
    payload = {
        "patient_id": patient_id,
        "requesting_unit_id": requesting_unit_id,
        "consult_type": "WOUND",
        "reported_stage": "STAGE_2",
        "clinical_note": "Sacral redness noted on the morning skin check.",
    }
    payload.update(overrides)
    return payload


def return_consult_payload(**overrides) -> dict:
    payload = {"reason": "Narrative lacks measurement and onset detail."}
    payload.update(overrides)
    return payload


def resubmit_consult_payload(**overrides) -> dict:
    payload = {
        "clinical_note": "Revised narrative with measurement and onset detail added.",
        "reported_stage": "STAGE_3",
    }
    payload.update(overrides)
    return payload


def assign_consult_payload(assigned_nurse_id: str, **overrides) -> dict:
    payload = {"assigned_nurse_id": assigned_nurse_id}
    payload.update(overrides)
    return payload


def escalate_consult_payload(**overrides) -> dict:
    payload = {"reason": "Response allowance elapsed without a bedside visit."}
    payload.update(overrides)
    return payload


def close_consult_payload(**overrides) -> dict:
    payload = {"closing_summary": "Wound healed; protocol discontinued at discharge."}
    payload.update(overrides)
    return payload


def cancel_consult_payload(**overrides) -> dict:
    payload = {"reason": "Patient transferred off service."}
    payload.update(overrides)
    return payload


def create_skin_assessment_payload(
    consult_request_id: str,
    patient_id: str,
    expected_patient_version: int,
    **overrides,
) -> dict:
    payload = {
        "consult_request_id": consult_request_id,
        "patient_id": patient_id,
        "anatomic_location": "SACRUM",
        "observed_stage": "STAGE_2",
        "measured_area_cm2": 12.0,
        "observed_at": "2026-08-01T00:00:00Z",
        "expected_patient_version": expected_patient_version,
    }
    payload.update(overrides)
    return payload


def validate_assessment_payload(
    confirmed_stage: str = "STAGE_2",
    present_on_admission_confirmed: bool = False,
    **overrides,
) -> dict:
    payload = {
        "confirmed_stage": confirmed_stage,
        "present_on_admission_confirmed": present_on_admission_confirmed,
    }
    payload.update(overrides)
    return payload


def dispute_assessment_payload(**overrides) -> dict:
    payload = {"dispute_reason": "Staging inconsistent with photographic record."}
    payload.update(overrides)
    return payload


def restage_assessment_payload(
    observed_stage: str = "STAGE_3", measured_area_cm2: float = 14.0, **overrides
) -> dict:
    payload = {
        "observed_stage": observed_stage,
        "measured_area_cm2": measured_area_cm2,
    }
    payload.update(overrides)
    return payload


def rca_start_payload(rca_lead_nurse_id: str, **overrides) -> dict:
    payload = {"rca_lead_nurse_id": rca_lead_nurse_id}
    payload.update(overrides)
    return payload


def rca_complete_payload(
    root_cause_category: str = "REPOSITIONING", **overrides
) -> dict:
    payload = {
        "root_cause_category": root_cause_category,
        "contributing_factors": ["Turn schedule not documented", "Understaffed night shift"],
    }
    payload.update(overrides)
    return payload


def close_case_payload(**overrides) -> dict:
    payload = {"closure_note": "Root cause addressed; corrective actions in place."}
    payload.update(overrides)
    return payload


def create_survey_round_payload(
    participating_unit_ids, round_type: str = "PREVALENCE", **overrides
) -> dict:
    payload = {
        "round_type": round_type,
        "window_start": "2026-08-01T00:00:00Z",
        "window_end": "2026-08-03T00:00:00Z",
        "participating_unit_ids": list(participating_unit_ids),
    }
    payload.update(overrides)
    return payload


def cancel_survey_round_payload(**overrides) -> dict:
    payload = {"reason": "Round stood down for staffing reasons."}
    payload.update(overrides)
    return payload


def create_survey_observation_payload(
    survey_round_id: str,
    unit_id: str,
    patient_id: str,
    observer_nurse_id: str,
    **overrides,
) -> dict:
    payload = {
        "survey_round_id": survey_round_id,
        "unit_id": unit_id,
        "patient_id": patient_id,
        "observer_nurse_id": observer_nurse_id,
        "observed_at": "2026-08-01T00:00:00Z",
        "injury_present": False,
        "classification": "NONE",
    }
    payload.update(overrides)
    return payload


def create_support_surface_payload(**overrides) -> dict:
    payload = {
        "asset_tag": asset_tag(),
        "surface_class": "LOW_AIR_LOSS",
        "daily_rate_cents": 10000,
        "vendor_name": "Northfield Medical Rentals",
    }
    payload.update(overrides)
    return payload


def retire_surface_payload(**overrides) -> dict:
    payload = {"reason": "End of vendor service life."}
    payload.update(overrides)
    return payload


def create_support_surface_order_payload(
    patient_id: str, unit_id: str, support_surface_id: str, **overrides
) -> dict:
    payload = {
        "patient_id": patient_id,
        "unit_id": unit_id,
        "support_surface_id": support_surface_id,
        "rental_start": "2026-08-01T00:00:00Z",
        "rental_end": "2026-08-04T00:00:00Z",
        "authorized_days": 3,
    }
    payload.update(overrides)
    return payload


def approve_order_payload(expected_unit_version: int, **overrides) -> dict:
    payload = {"expected_unit_version": expected_unit_version}
    payload.update(overrides)
    return payload


def deny_order_payload(**overrides) -> dict:
    payload = {"denial_reason": "Alternative surface already on the ward."}
    payload.update(overrides)
    return payload


def deliver_order_payload(delivered_at: str, **overrides) -> dict:
    payload = {"delivered_at": delivered_at}
    payload.update(overrides)
    return payload


def return_order_payload(actual_return_at: str, **overrides) -> dict:
    payload = {"actual_return_at": actual_return_at}
    payload.update(overrides)
    return payload


def create_formulary_product_payload(**overrides) -> dict:
    payload = {
        "sku": sku(),
        "name": "Silicone Foam Border Dressing",
        "category": "FOAM",
        "unit_cost_cents": 1000,
        "formulary_tier": "PREFERRED",
    }
    payload.update(overrides)
    return payload


def archive_product_payload(**overrides) -> dict:
    payload = {"reason": "Superseded by a preferred equivalent."}
    payload.update(overrides)
    return payload


def create_dressing_protocol_payload(
    consult_request_id: str, formulary_product_id: str, **overrides
) -> dict:
    payload = {
        "consult_request_id": consult_request_id,
        "formulary_product_id": formulary_product_id,
        "change_frequency_hours": 48,
        "units_per_change": 1,
    }
    payload.update(overrides)
    return payload


def create_ostomy_education_plan_payload(
    consult_request_id: str, patient_id: str, **overrides
) -> dict:
    payload = {"consult_request_id": consult_request_id, "patient_id": patient_id}
    payload.update(overrides)
    return payload


def education_session_payload(teach_back_score: int, **overrides) -> dict:
    payload = {"teach_back_score": teach_back_score}
    payload.update(overrides)
    return payload


def transition_supplies_payload(followup_appointment_at: str, **overrides) -> dict:
    payload = {"followup_appointment_at": followup_appointment_at}
    payload.update(overrides)
    return payload


def set_clock_payload(to_iso8601: str, **overrides) -> dict:
    payload = {"to_iso8601": to_iso8601}
    payload.update(overrides)
    return payload
