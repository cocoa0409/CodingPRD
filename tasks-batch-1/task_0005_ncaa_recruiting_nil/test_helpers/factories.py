"""Payload factories — one per entity, source: input fields only (PRD §3)."""
from typing import Optional


# ─── Program (PRD §3.1) ─────────────────────────────────


def create_program_payload(
    sport_code: str = "FOOTBALL",
    school_name: str = "Test University",
    scholarship_slot_cap: int = 85,
    **overrides,
) -> dict:
    defaults = {
        "sport_code": sport_code,
        "school_name": school_name,
        "scholarship_slot_cap": scholarship_slot_cap,
    }
    defaults.update(overrides)
    return defaults


# ─── Period (PRD §3.1) ──────────────────────────────────


def create_period_payload(
    period_type: str = "CONTACT",
    starts_at: str = "2026-06-01T00:00:00Z",
    ends_at: str = "2026-06-30T00:00:00Z",
    **overrides,
) -> dict:
    defaults = {
        "period_type": period_type,
        "starts_at": starts_at,
        "ends_at": ends_at,
    }
    defaults.update(overrides)
    return defaults


# ─── StudentAthlete (PRD §3.2) ──────────────────────────


def create_student_athlete_payload(
    full_name: str = "Test Athlete",
    sport_code: str = "FOOTBALL",
    gpa: float = 3.500,
    amateurism_flag: Optional[bool] = True,
    **overrides,
) -> dict:
    defaults = {
        "full_name": full_name,
        "sport_code": sport_code,
        "gpa": gpa,
    }
    if amateurism_flag is not None:
        defaults["amateurism_flag"] = amateurism_flag
    defaults.update(overrides)
    return defaults


# ─── EligibilityCertification (PRD §3.2) ────────────────


def create_eligibility_certification_payload(
    student_athlete_id: str,
    **overrides,
) -> dict:
    defaults = {"student_athlete_id": student_athlete_id}
    defaults.update(overrides)
    return defaults


def deny_certification_payload(
    denial_reason: str = "GPA_BELOW_MIN",
    **overrides,
) -> dict:
    defaults = {"denial_reason": denial_reason}
    defaults.update(overrides)
    return defaults


# ─── RecruitingContact (PRD §3.3) ───────────────────────


def create_recruiting_contact_payload(
    program_id: str,
    student_athlete_id: str,
    coach_user_id: str,
    contact_at: str,
    channel: str = "IN_PERSON",
    **overrides,
) -> dict:
    defaults = {
        "program_id": program_id,
        "student_athlete_id": student_athlete_id,
        "coach_user_id": coach_user_id,
        "contact_at": contact_at,
        "channel": channel,
    }
    defaults.update(overrides)
    return defaults


# ─── ScholarshipOffer (PRD §3.4) ────────────────────────


def create_scholarship_offer_payload(
    program_id: str,
    student_athlete_id: str,
    annual_value_cents: int = 5_000_000,
    **overrides,
) -> dict:
    defaults = {
        "program_id": program_id,
        "student_athlete_id": student_athlete_id,
        "annual_value_cents": annual_value_cents,
    }
    defaults.update(overrides)
    return defaults


def send_scholarship_offer_payload(
    expected_program_version: int,
    **overrides,
) -> dict:
    defaults = {"expected_program_version": expected_program_version}
    defaults.update(overrides)
    return defaults


# ─── NILDeal (PRD §3.5) ─────────────────────────────────


def create_nil_deal_payload(
    student_athlete_id: str,
    brand_name: str = "Test Brand",
    gross_value_cents: int = 100_000,
    agent_fee_pct: Optional[float] = 0.0,
    **overrides,
) -> dict:
    defaults = {
        "student_athlete_id": student_athlete_id,
        "brand_name": brand_name,
        "gross_value_cents": gross_value_cents,
    }
    if agent_fee_pct is not None:
        defaults["agent_fee_pct"] = agent_fee_pct
    defaults.update(overrides)
    return defaults


def reject_nil_deal_payload(
    rejection_reason: str = "BRAND_PROHIBITED",
    **overrides,
) -> dict:
    defaults = {"rejection_reason": rejection_reason}
    defaults.update(overrides)
    return defaults


# ─── TransferPortalEntry (PRD §3.6) ─────────────────────


def create_transfer_portal_entry_payload(
    student_athlete_id: str,
    source_program_id: str,
    **overrides,
) -> dict:
    defaults = {
        "student_athlete_id": student_athlete_id,
        "source_program_id": source_program_id,
    }
    defaults.update(overrides)
    return defaults


def match_transfer_portal_entry_payload(
    matched_program_id: str,
    expected_transferportalentry_version: int,
    **overrides,
) -> dict:
    defaults = {
        "matched_program_id": matched_program_id,
        "expected_transferportalentry_version":
            expected_transferportalentry_version,
    }
    defaults.update(overrides)
    return defaults


# ─── BoosterIncident (PRD §3.7) ─────────────────────────


def create_booster_incident_payload(
    program_id: str,
    booster_name: str = "Test Booster",
    student_athlete_id: str = None,
    alleged_value_cents: int = 100_000,
    **overrides,
) -> dict:
    defaults = {
        "program_id": program_id,
        "booster_name": booster_name,
        "student_athlete_id": student_athlete_id,
        "alleged_value_cents": alleged_value_cents,
    }
    defaults.update(overrides)
    return defaults


def sustain_booster_incident_payload(
    expected_boosterincident_version: int,
    **overrides,
) -> dict:
    defaults = {
        "expected_boosterincident_version": expected_boosterincident_version,
    }
    defaults.update(overrides)
    return defaults


# ─── Test-driving (PRD §2.8) ────────────────────────────


def set_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
