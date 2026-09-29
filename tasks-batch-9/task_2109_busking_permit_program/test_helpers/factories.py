"""Payload factories — one per resource, input fields only."""
import itertools

_email_seq = itertools.count(1)
_zone_code_seq = itertools.count(1)
_pitch_code_seq = itertools.count(1)


def unique_email(prefix: str = "performer") -> str:
    return f"{prefix}{next(_email_seq)}@example.org"


def unique_zone_code(prefix: str = "ZN") -> str:
    return f"{prefix}{next(_zone_code_seq)}"


def unique_pitch_code(prefix: str = "PT") -> str:
    return f"{prefix}{next(_pitch_code_seq)}"


def create_zone_payload(**overrides) -> dict:
    """District registration payload. Defaults model Riverside Plaza: base 78 dB,
    weekend bonus 3, evening penalty 5 from minute 1080, quiet window 23:00-06:00."""
    defaults = {
        "name": "Riverside Plaza",
        "code": "RP",
        "base_noise_cap_db": 78,
        "evening_start_minute": 1080,
        "quiet_hours_start_minute": 1380,
        "quiet_hours_end_minute": 360,
        "weekend_noise_bonus_db": 3,
        "evening_penalty_db": 5,
        "max_concurrent_closures": 1,
    }
    defaults.update(overrides)
    return defaults


def create_pitch_payload(zone_id: str, **overrides) -> dict:
    """Designated-pitch registration payload."""
    defaults = {
        "zone_id": zone_id,
        "code": "RP-01",
        "tier": "STANDARD",
        "noise_cap_db": 82,
        "amplification_allowed": True,
    }
    defaults.update(overrides)
    return defaults


def create_performer_payload(**overrides) -> dict:
    defaults = {
        "legal_name": "Ada Vance",
        "stage_name": "Ada V",
        "email": "ada@example.org",
        "act_type": "ACOUSTIC_MUSIC",
    }
    defaults.update(overrides)
    return defaults


def create_application_payload(performer_id: str, requested_zone_id: str,
                               **overrides) -> dict:
    defaults = {
        "performer_id": performer_id,
        "requested_zone_id": requested_zone_id,
        "season_year": 2026,
        "requested_act_type": "ACOUSTIC_MUSIC",
        "amplification_requested": False,
    }
    defaults.update(overrides)
    return defaults


def decision_payload(outcome: str, decision_note: str = None) -> dict:
    payload = {"outcome": outcome}
    if decision_note is not None:
        payload["decision_note"] = decision_note
    return payload


def revision_payload(expected_application_version: int, **overrides) -> dict:
    payload = {"expected_application_version": expected_application_version}
    payload.update(overrides)
    return payload


def create_audition_payload(application_id: str, **overrides) -> dict:
    defaults = {
        "application_id": application_id,
        "scheduled_for": "2026-08-06T10:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_audition_score_payload(technical_score: int = 7,
                                  suitability_score: int = 7,
                                  safety_score: int = 7, **overrides) -> dict:
    defaults = {
        "technical_score": technical_score,
        "suitability_score": suitability_score,
        "safety_score": safety_score,
    }
    defaults.update(overrides)
    return defaults


def payment_payload(amount_cents: int) -> dict:
    return {"amount_cents": amount_cents}


def renew_payload(season_year: int) -> dict:
    return {"season_year": season_year}


def revoke_payload(reason: str = "Permit surrendered by the holder",
                   refund_mode: str = None) -> dict:
    payload = {"reason": reason}
    if refund_mode is not None:
        payload["refund_mode"] = refund_mode
    return payload


def reinstate_payload(note: str = None) -> dict:
    return {} if note is None else {"note": note}


def create_lottery_draw_payload(pitch_id: str, **overrides) -> dict:
    defaults = {
        "pitch_id": pitch_id,
        "season_year": 2026,
        "slot_start_at": "2026-08-20T12:00:00Z",
        "slot_end_at": "2026-08-20T13:30:00Z",
        "entry_deadline_at": "2026-08-15T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_lottery_entry_payload(permit_id: str) -> dict:
    return {"permit_id": permit_id}


def create_session_booking_payload(permit_id: str, pitch_id: str,
                                   start_at: str, end_at: str,
                                   expected_permit_version: int,
                                   **overrides) -> dict:
    defaults = {
        "permit_id": permit_id,
        "pitch_id": pitch_id,
        "start_at": start_at,
        "end_at": end_at,
        "expected_permit_version": expected_permit_version,
        "amplification_planned": False,
    }
    defaults.update(overrides)
    return defaults


def cancel_booking_payload(reason: str = None) -> dict:
    return {} if reason is None else {"reason": reason}


def create_noise_reading_payload(booking_id: str, taken_at: str,
                                 reading_db: int) -> dict:
    return {
        "booking_id": booking_id,
        "taken_at": taken_at,
        "reading_db": reading_db,
    }


def create_complaint_payload(permit_id: str, **overrides) -> dict:
    defaults = {
        "permit_id": permit_id,
        "category": "NOISE",
        "description": "Amplified backing track at midday",
    }
    defaults.update(overrides)
    return defaults


def triage_payload(severity: str, route: str) -> dict:
    return {"severity": severity, "route": route}


def adjudicate_payload(outcome: str, resolution_note: str = None) -> dict:
    payload = {"outcome": outcome}
    if resolution_note is not None:
        payload["resolution_note"] = resolution_note
    return payload


def create_closure_order_payload(zone_id: str, starts_at: str, ends_at: str,
                                 **overrides) -> dict:
    defaults = {
        "zone_id": zone_id,
        "reason": "SPECIAL_EVENT",
        "starts_at": starts_at,
        "ends_at": ends_at,
    }
    defaults.update(overrides)
    return defaults
