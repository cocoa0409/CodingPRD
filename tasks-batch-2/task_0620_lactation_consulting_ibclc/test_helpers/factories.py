"""Payload factories — one per resource, input fields only.

Each factory provides sensible PRD-consistent defaults and accepts **overrides
so tests can control just the values they care about. Required fields with no
universal default (foreign keys, time windows) are explicit parameters.
"""

DEFAULTS = {
    "PRACTICE_NAME": "Bay Lactation",
    "CONSULTANT_NAME": "Ana IBCLC",
    "CLIENT_NAME": "Parent A",
    "STANDARD_RATE_CENTS": 20000,
    "INFANT_DOB": "2026-05-01T00:00:00Z",
    "HOUSEHOLD_INCOME_CENTS": 9900000,
    "LATCH_SCORE": 8,
}


def create_practice_payload(**overrides) -> dict:
    payload = {"name": DEFAULTS["PRACTICE_NAME"]}
    payload.update(overrides)
    return payload


def create_sliding_scale_tier_payload(practice_id, name, income_ceiling_cents,
                                      discount_pct, **overrides) -> dict:
    payload = {
        "practice_id": practice_id,
        "name": name,
        "income_ceiling_cents": income_ceiling_cents,
        "discount_pct": discount_pct,
    }
    payload.update(overrides)
    return payload


def create_service_package_payload(practice_id, name, included_visits,
                                   price_cents, **overrides) -> dict:
    payload = {
        "practice_id": practice_id,
        "name": name,
        "included_visits": included_visits,
        "price_cents": price_cents,
    }
    payload.update(overrides)
    return payload


def create_consultant_payload(practice_id, **overrides) -> dict:
    payload = {
        "practice_id": practice_id,
        "full_name": DEFAULTS["CONSULTANT_NAME"],
        "standard_rate_cents": DEFAULTS["STANDARD_RATE_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_client_payload(practice_id, **overrides) -> dict:
    payload = {
        "practice_id": practice_id,
        "full_name": DEFAULTS["CLIENT_NAME"],
        "infant_dob": DEFAULTS["INFANT_DOB"],
        "household_income_cents": DEFAULTS["HOUSEHOLD_INCOME_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_consult_payload(practice_id, client_id, consultant_id,
                           scheduled_start_utc, scheduled_end_utc,
                           consult_type="TELEHEALTH", pay_method="SELF_PAY",
                           **overrides) -> dict:
    payload = {
        "practice_id": practice_id,
        "client_id": client_id,
        "consultant_id": consultant_id,
        "consult_type": consult_type,
        "scheduled_start_utc": scheduled_start_utc,
        "scheduled_end_utc": scheduled_end_utc,
        "pay_method": pay_method,
    }
    payload.update(overrides)
    return payload


def create_feeding_assessment_payload(consult_id, latch_score=8,
                                      pre_feed_weight_grams=4000,
                                      post_feed_weight_grams=4040,
                                      **overrides) -> dict:
    payload = {
        "consult_id": consult_id,
        "latch_score": latch_score,
        "pre_feed_weight_grams": pre_feed_weight_grams,
        "post_feed_weight_grams": post_feed_weight_grams,
    }
    payload.update(overrides)
    return payload


def create_follow_up_plan_payload(consult_id, target_daily_transfer_grams,
                                  **overrides) -> dict:
    payload = {
        "consult_id": consult_id,
        "target_daily_transfer_grams": target_daily_transfer_grams,
    }
    payload.update(overrides)
    return payload


def create_weighted_feed_payload(follow_up_plan_id, pre_feed_weight_grams,
                                 post_feed_weight_grams, **overrides) -> dict:
    payload = {
        "follow_up_plan_id": follow_up_plan_id,
        "pre_feed_weight_grams": pre_feed_weight_grams,
        "post_feed_weight_grams": post_feed_weight_grams,
    }
    payload.update(overrides)
    return payload


def create_superbill_payload(consult_id, billed_amount_cents, allowed_amount_cents,
                             **overrides) -> dict:
    payload = {
        "consult_id": consult_id,
        "billed_amount_cents": billed_amount_cents,
        "allowed_amount_cents": allowed_amount_cents,
    }
    payload.update(overrides)
    return payload


def create_dme_qualification_payload(consult_id, pump_type, **overrides) -> dict:
    payload = {
        "consult_id": consult_id,
        "pump_type": pump_type,
    }
    payload.update(overrides)
    return payload


def create_pediatrician_referral_payload(consult_id, reason="WEIGHT_CONCERN",
                                         pediatrician_name="Dr Lee",
                                         **overrides) -> dict:
    payload = {
        "consult_id": consult_id,
        "reason": reason,
        "pediatrician_name": pediatrician_name,
    }
    payload.update(overrides)
    return payload


def set_clock_payload(practice_id, to_iso8601) -> dict:
    return {"practice_id": practice_id, "to_iso8601": to_iso8601}
