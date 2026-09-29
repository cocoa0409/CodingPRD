"""Payload factories — one per entity, input fields only.

Each factory returns a fully valid payload that tests override field by field.
Field names are exactly the PRD's field names.
"""

from .constants import TEST_DEFAULTS


def create_production_payload(**overrides) -> dict:
    """A COMPETITION_HIGH_STRESS / CA production with a generous stipend pool."""
    payload = {
        "title": "Island Trials",
        "format_type": "COMPETITION_HIGH_STRESS",
        "jurisdiction_code": "CA",
        "season_number": 1,
        "episode_order": 10,
        "photography_start_utc": TEST_DEFAULTS["PHOTOGRAPHY_START_UTC"],
        "photography_end_utc": TEST_DEFAULTS["PHOTOGRAPHY_END_UTC"],
        "stipend_pool_cents": TEST_DEFAULTS["STIPEND_POOL_CENTS"],
        "welfare_budget_cents": TEST_DEFAULTS["WELFARE_BUDGET_CENTS"],
        "minor_participant_cap": 0,
    }
    payload.update(overrides)
    return payload


def create_docusoap_production_payload(**overrides) -> dict:
    """A DOCUSOAP production, which opens at duty_of_care_tier STANDARD."""
    payload = create_production_payload(
        title="Harbour Nights",
        format_type="DOCUSOAP",
        jurisdiction_code="GA",
        episode_order=9,
        stipend_pool_cents=5_000_000,
        welfare_budget_cents=2_000_000,
        minor_participant_cap=2,
    )
    payload.update(overrides)
    return payload


def create_location_payload(**overrides) -> dict:
    payload = {
        "name": "Stage A",
        "state_code": "CA",
        "capacity": 500,
        "turnaround_buffer_minutes": 60,
        "filming_permit_number": "PRM-1001",
    }
    payload.update(overrides)
    return payload


def create_casting_call_payload(production_id: str, **overrides) -> dict:
    payload = {
        "production_id": production_id,
        "channel": "REFERRAL",
        "min_age": 13,
        "max_age": 60,
        "exclusivity_window_days": 0,
    }
    payload.update(overrides)
    return payload


def create_open_call_payload(production_id: str, venue_location_id: str, **overrides) -> dict:
    payload = {
        "production_id": production_id,
        "channel": "OPEN_CALL",
        "min_age": 18,
        "max_age": 60,
        "exclusivity_window_days": 0,
        "venue_location_id": venue_location_id,
        "open_call_window_start_utc": "2026-07-25T00:00:00Z",
        "open_call_window_end_utc": "2026-08-10T00:00:00Z",
        "expected_attendance": 100,
    }
    payload.update(overrides)
    return payload


def create_applicant_payload(casting_call_id: str, **overrides) -> dict:
    payload = {
        "casting_call_id": casting_call_id,
        "legal_name": "Ada Reyes",
        "date_of_birth": TEST_DEFAULTS["ADULT_DOB"],
        "residency_state_code": "CA",
    }
    payload.update(overrides)
    return payload


def create_minor_applicant_payload(casting_call_id: str, **overrides) -> dict:
    payload = create_applicant_payload(
        casting_call_id,
        legal_name="Rae Solis",
        date_of_birth=TEST_DEFAULTS["MINOR_DOB"],
        guardian_name="Sam Solis",
    )
    payload.update(overrides)
    return payload


def create_screening_item_payload(kind: str, outcome: str = "PASS", **overrides) -> dict:
    """A screening item.

    Passing ``outcome=None`` omits both result fields so the item is opened and
    left pending.
    """
    payload = {"kind": kind}
    if outcome is not None:
        payload["outcome"] = outcome
        payload.setdefault("severity_flags", 0)
    payload.update(overrides)
    return payload


def record_outcome_payload(outcome: str = "PASS", severity_flags: int = 0, **overrides) -> dict:
    payload = {"outcome": outcome, "severity_flags": severity_flags}
    payload.update(overrides)
    return payload


def create_minor_protection_payload(**overrides) -> dict:
    payload = {
        "work_permit_number": "CA-WP-90210",
        "permit_expires_on": "2027-03-31",
        "education_hours_scheduled_weekly": 15,
        "trust_deposit_pct": 0.15,
    }
    payload.update(overrides)
    return payload


def create_agreement_payload(
    applicant_id: str, production_id: str, expected_applicant_version: int, **overrides
) -> dict:
    payload = {
        "applicant_id": applicant_id,
        "production_id": production_id,
        "exclusivity_window_days": 0,
        "confidentiality_tier": "STANDARD",
        "depiction_rights_scope": "FULL",
        "stipend_structure": "FLAT",
        "base_stipend_cents": 100_000,
        "episodes_committed": 2,
        "press_appearance_obligation_count": 0,
        "reunion_obligation": False,
        "expected_applicant_version": expected_applicant_version,
    }
    payload.update(overrides)
    return payload


def counter_offer_payload(expected_agreement_version: int, **overrides) -> dict:
    payload = {
        "requested_base_stipend_cents": 130_000,
        "requested_exclusivity_window_days": 0,
        "requested_depiction_rights_scope": "LIMITED",
        "expected_agreement_version": expected_agreement_version,
    }
    payload.update(overrides)
    return payload


def revise_payload(**overrides) -> dict:
    payload = {
        "base_stipend_cents": 115_000,
        "exclusivity_window_days": 0,
        "depiction_rights_scope": "FULL",
    }
    payload.update(overrides)
    return payload


def void_payload(void_reason: str = "BUSINESS_AFFAIRS_VOID") -> dict:
    return {"void_reason": void_reason}


def create_welfare_protocol_payload(kind: str = "DUTY_OF_CARE_OFFICER", **overrides) -> dict:
    payload = {
        "kind": kind,
        "coverage_start_utc": TEST_DEFAULTS["PHOTOGRAPHY_START_UTC"],
        "coverage_end_utc": TEST_DEFAULTS["PHOTOGRAPHY_END_UTC"],
        "cost_cents": 1_000_000,
    }
    if kind == "INSURANCE_RIDER":
        payload["carrier_certificate_number"] = "CERT-4499"
    payload.update(overrides)
    return payload


def create_shoot_block_payload(production_id: str, location_id: str, **overrides) -> dict:
    payload = {
        "production_id": production_id,
        "location_id": location_id,
        "block_kind": "STUDIO",
        "start_utc": "2026-10-05T08:00:00Z",
        "end_utc": "2026-10-05T12:00:00Z",
        "participant_agreement_ids": [],
        "expected_crowd_headcount": 0,
        "onset_minor_hours": 0,
    }
    payload.update(overrides)
    return payload


def create_release_payload(**overrides) -> dict:
    payload = {
        "subject_kind": "INCIDENTAL_CROWD",
        "head_count": 25,
        "disposition": "COLLECTED",
    }
    payload.update(overrides)
    return payload


def create_complaint_payload(**overrides) -> dict:
    payload = {
        "category": "WELFARE",
        "severity": 4,
        "narrative": "On-set duty of care fell short during the night shoot.",
    }
    payload.update(overrides)
    return payload


def route_payload(route: str) -> dict:
    return {"route": route}


def resolve_payload(resolution_note: str = "Closed after aftercare review.") -> dict:
    return {"resolution_note": resolution_note}


def withdraw_payload(reason: str = "Family withdrew consent before principal photography.") -> dict:
    return {"reason": reason}


def trust_deposit_payload(installment_count: int) -> dict:
    return {"installment_count": installment_count}
