"""Payload factories — one per entity, input fields only (PRD §3)."""

DEFAULTS = {
    "AGENCY_NAME": "Stellar Talent",
    "COMMISSION_RATE_BPS": 1000,
    "CD_NAME": "Dana Cast",
    "STUDIO": "BigPic",
    "TALENT_NAME": "Tess Lead",
    "UNION_STATUS": "SAG",
    "SCALE_RATE_CENTS": 100000,
    "HEADSHOT_URL": "http://x/h.jpg",
    "HEIGHT_CM": 170,
    "SKILLS": ["act"],
    "CALL_TITLE": "Lead Spot",
    "MEDIA_TYPE": "STREAMING",
    "USAGE_TERM_MONTHS": 12,
    "DAY_RATE_CENTS": 200000,
}


def create_agency_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["AGENCY_NAME"],
        "commission_rate_bps": DEFAULTS["COMMISSION_RATE_BPS"],
    }
    payload.update(overrides)
    return payload


def create_casting_director_payload(**overrides) -> dict:
    payload = {"display_name": DEFAULTS["CD_NAME"], "studio": DEFAULTS["STUDIO"]}
    payload.update(overrides)
    return payload


def create_talent_payload(agency_id, **overrides) -> dict:
    payload = {
        "agency_id": agency_id,
        "full_name": DEFAULTS["TALENT_NAME"],
        "union_status": DEFAULTS["UNION_STATUS"],
        "scale_rate_cents": DEFAULTS["SCALE_RATE_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_comp_card_payload(talent_id, **overrides) -> dict:
    payload = {
        "talent_id": talent_id,
        "headshot_url": DEFAULTS["HEADSHOT_URL"],
        "height_cm": DEFAULTS["HEIGHT_CM"],
        "skills": list(DEFAULTS["SKILLS"]),
    }
    payload.update(overrides)
    return payload


def create_casting_call_payload(casting_director_id, **overrides) -> dict:
    payload = {
        "casting_director_id": casting_director_id,
        "title": DEFAULTS["CALL_TITLE"],
        "media_type": DEFAULTS["MEDIA_TYPE"],
        "usage_term_months": DEFAULTS["USAGE_TERM_MONTHS"],
        "shoot_start_date": "2026-03-15T00:00:00Z",
        "shoot_end_date": "2026-03-19T00:00:00Z",
        "offered_day_rate_cents": DEFAULTS["DAY_RATE_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_submission_payload(casting_call_id, talent_id, comp_card_id, **overrides) -> dict:
    payload = {
        "casting_call_id": casting_call_id,
        "talent_id": talent_id,
        "comp_card_id": comp_card_id,
    }
    payload.update(overrides)
    return payload


def create_audition_slot_payload(submission_id, casting_director_id, **overrides) -> dict:
    payload = {
        "submission_id": submission_id,
        "casting_director_id": casting_director_id,
        "slot_kind": "AUDITION",
        "start_at": "2026-04-10T10:00:00Z",
        "end_at": "2026-04-10T10:30:00Z",
    }
    payload.update(overrides)
    return payload


def create_availability_hold_payload(talent_id, **overrides) -> dict:
    payload = {
        "talent_id": talent_id,
        "start_date": "2026-03-15T00:00:00Z",
        "end_date": "2026-03-19T00:00:00Z",
        "hold_kind": "CONFIRMED_BOOKING",
    }
    payload.update(overrides)
    return payload


def create_deal_memo_payload(casting_call_id, talent_id, submission_id, **overrides) -> dict:
    payload = {
        "casting_call_id": casting_call_id,
        "talent_id": talent_id,
        "submission_id": submission_id,
    }
    payload.update(overrides)
    return payload


def offer_payload(offer_day_rate_cents=200000, offer_usage_term_months=12, **overrides) -> dict:
    payload = {
        "offer_day_rate_cents": offer_day_rate_cents,
        "offer_usage_term_months": offer_usage_term_months,
    }
    payload.update(overrides)
    return payload


def counter_payload(counter_day_rate_cents=210000, counter_usage_term_months=12, **overrides) -> dict:
    payload = {
        "counter_day_rate_cents": counter_day_rate_cents,
        "counter_usage_term_months": counter_usage_term_months,
    }
    payload.update(overrides)
    return payload


def create_booking_payload(deal_memo_id, talent_id, casting_call_id,
                           availability_hold_id, expected_talent_version, **overrides) -> dict:
    payload = {
        "deal_memo_id": deal_memo_id,
        "talent_id": talent_id,
        "casting_call_id": casting_call_id,
        "availability_hold_id": availability_hold_id,
        "start_date": "2026-03-15T00:00:00Z",
        "end_date": "2026-03-19T00:00:00Z",
        "expected_talent_version": expected_talent_version,
    }
    payload.update(overrides)
    return payload


def confirm_payload(expected_talent_version, **overrides) -> dict:
    payload = {"expected_talent_version": expected_talent_version}
    payload.update(overrides)
    return payload


def create_payment_payload(booking_id, talent_id, gross_amount_cents, **overrides) -> dict:
    payload = {
        "booking_id": booking_id,
        "talent_id": talent_id,
        "gross_amount_cents": gross_amount_cents,
    }
    payload.update(overrides)
    return payload


def create_residual_schedule_payload(payment_id, booking_id, period_index, **overrides) -> dict:
    payload = {
        "payment_id": payment_id,
        "booking_id": booking_id,
        "period_index": period_index,
    }
    payload.update(overrides)
    return payload
