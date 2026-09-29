"""Payload factories — one per collection, carrying input fields only."""
from .constants import TEST_DEFAULTS


def loyalty_program_payload(**overrides) -> dict:
    payload = {
        "name": TEST_DEFAULTS["PROGRAM_NAME"],
        "current_period": TEST_DEFAULTS["CURRENT_PERIOD"],
    }
    payload.update(overrides)
    return payload


def co_brand_issuer_payload(program_id: str, **overrides) -> dict:
    payload = {
        "program_id": program_id,
        "name": TEST_DEFAULTS["ISSUER_NAME"],
        "annual_mile_purchase_cap_miles": TEST_DEFAULTS["ISSUER_CAP_MILES"],
    }
    payload.update(overrides)
    return payload


def tier_schedule(*entries) -> list:
    """``entries`` is a sequence of (threshold_miles, price_per_mile_centicents)."""
    return [
        {"threshold_miles": threshold, "price_per_mile_centicents": price}
        for threshold, price in entries
    ]


def mile_sale_agreement_payload(issuer_id: str, **overrides) -> dict:
    payload = {
        "issuer_id": issuer_id,
        "term_start_date": TEST_DEFAULTS["TERM_START_DATE"],
        "term_end_date": TEST_DEFAULTS["TERM_END_DATE"],
        "committed_volume_miles": TEST_DEFAULTS["COMMITTED_VOLUME_MILES"],
        "tier_schedule": tier_schedule((0, TEST_DEFAULTS["TIER_PRICE_CENTICENTS"])),
    }
    payload.update(overrides)
    return payload


def mile_purchase_order_payload(agreement_id: str, order_miles: int,
                               expected_agreement_version: int,
                               **overrides) -> dict:
    payload = {
        "agreement_id": agreement_id,
        "order_miles": order_miles,
        "expected_agreement_version": expected_agreement_version,
    }
    payload.update(overrides)
    return payload


def member_account_payload(program_id: str, **overrides) -> dict:
    payload = {
        "program_id": program_id,
        "external_member_ref": TEST_DEFAULTS["MEMBER_REF"],
        "home_region": TEST_DEFAULTS["HOME_REGION"],
    }
    payload.update(overrides)
    return payload


def mile_transaction_payload(member_id: str, txn_type: str, activity_date: str,
                            **overrides) -> dict:
    payload = {
        "member_id": member_id,
        "txn_type": txn_type,
        "activity_date": activity_date,
    }
    payload.update(overrides)
    return payload


def promotion_campaign_payload(program_id: str, **overrides) -> dict:
    payload = {
        "program_id": program_id,
        "code": TEST_DEFAULTS["CAMPAIGN_CODE"],
        "earn_channel": "FLIGHT",
        "multiplier_bps": 20000,
        "stacking_mode": "ADDITIVE",
        "window_start": TEST_DEFAULTS["CAMPAIGN_WINDOW_START"],
        "window_end": TEST_DEFAULTS["CAMPAIGN_WINDOW_END"],
    }
    payload.update(overrides)
    return payload


def award_inventory_window_payload(program_id: str, **overrides) -> dict:
    payload = {
        "program_id": program_id,
        "route_code": TEST_DEFAULTS["ROUTE_CODE"],
        "cabin": TEST_DEFAULTS["CABIN"],
        "window_start_date": TEST_DEFAULTS["WINDOW_START_DATE"],
        "window_end_date": TEST_DEFAULTS["WINDOW_END_DATE"],
        "authorized_seats": TEST_DEFAULTS["AUTHORIZED_SEATS"],
    }
    payload.update(overrides)
    return payload


def award_booking_payload(member_id: str, window_id: str,
                          expected_window_version: int, **overrides) -> dict:
    payload = {
        "member_id": member_id,
        "window_id": window_id,
        "travel_date": TEST_DEFAULTS["TRAVEL_DATE"],
        "seats": 1,
        "fare_class": "FLEX",
        "expected_window_version": expected_window_version,
    }
    payload.update(overrides)
    return payload


def partner_airline_payload(program_id: str, **overrides) -> dict:
    payload = {
        "program_id": program_id,
        "iata_code": TEST_DEFAULTS["IATA_CODE"],
        "settlement_rate_centicents_per_mile":
            TEST_DEFAULTS["SETTLEMENT_RATE_CENTICENTS"],
    }
    payload.update(overrides)
    return payload


def program_change_notice_payload(program_id: str, change_type: str,
                                  effective_at: str,
                                  expected_program_version: int,
                                  **overrides) -> dict:
    payload = {
        "program_id": program_id,
        "change_type": change_type,
        "effective_at": effective_at,
        "expected_program_version": expected_program_version,
    }
    payload.update(overrides)
    return payload


def fraud_case_payload(member_id: str, case_type: str, **overrides) -> dict:
    payload = {
        "member_id": member_id,
        "case_type": case_type,
        "login_geo_velocity": 0,
        "redemption_velocity_24h": 0,
        "brokering_pattern_hits": 0,
        "dormancy_days": 0,
    }
    payload.update(overrides)
    return payload


def deferred_revenue_posting_payload(program_id: str, period: str,
                                     expected_program_version: int,
                                     **overrides) -> dict:
    payload = {
        "program_id": program_id,
        "period": period,
        "expected_program_version": expected_program_version,
    }
    payload.update(overrides)
    return payload
