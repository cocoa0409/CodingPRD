"""Payload factories — one per write endpoint, input fields only."""

from .constants import TEST_DEFAULTS


def rights_holder_payload(**overrides) -> dict:
    payload = {
        "legal_name": "Northbeam Records",
        "holder_type": "LABEL",
        "home_territory_code": "GB",
    }
    payload.update(overrides)
    return payload


def work_payload(**overrides) -> dict:
    payload = {
        "work_type": "RECORDING",
        "identifier": TEST_DEFAULTS["RECORDING_A_ISRC"],
        "title": TEST_DEFAULTS["RECORDING_A_TITLE"],
        "artist_credit": TEST_DEFAULTS["RECORDING_A_ARTIST"],
    }
    payload.update(overrides)
    return payload


def composition_payload(**overrides) -> dict:
    payload = {
        "work_type": "COMPOSITION",
        "identifier": TEST_DEFAULTS["COMPOSITION_A_ISWC"],
        "title": TEST_DEFAULTS["COMPOSITION_A_TITLE"],
    }
    payload.update(overrides)
    return payload


def period_payload(**overrides) -> dict:
    payload = {
        "label": TEST_DEFAULTS["PERIOD_LABEL"],
        "usage_start": TEST_DEFAULTS["PERIOD_USAGE_START"],
        "usage_end": TEST_DEFAULTS["PERIOD_USAGE_END"],
    }
    payload.update(overrides)
    return payload


def usage_batch_payload(period_id, **overrides) -> dict:
    payload = {
        "period_id": period_id,
        "source_label": TEST_DEFAULTS["SOURCE_LABEL"],
    }
    payload.update(overrides)
    return payload


def usage_line_payload(**overrides) -> dict:
    payload = {
        "reported_title": TEST_DEFAULTS["RECORDING_A_TITLE"],
        "territory_code": "GB",
        "subscription_tier": "INDIVIDUAL",
        "play_count": 300000,
    }
    payload.update(overrides)
    return payload


def rights_registration_payload(work_id, claimant_id, expected_work_version, **overrides) -> dict:
    payload = {
        "work_id": work_id,
        "claimant_id": claimant_id,
        "right_type": "MASTER",
        "routing": "DIRECT",
        "share_bps": 10000,
        "territory_set": ["WORLD"],
        "effective_from": TEST_DEFAULTS["REGISTRATION_EFFECTIVE_FROM"],
        "effective_to": TEST_DEFAULTS["REGISTRATION_EFFECTIVE_TO"],
        "expected_work_version": expected_work_version,
    }
    payload.update(overrides)
    return payload


def pool_payload(period_id, **overrides) -> dict:
    payload = {
        "period_id": period_id,
        "territory_code": "GB",
        "subscription_tier": "INDIVIDUAL",
        "subscriber_count": TEST_DEFAULTS["CANONICAL_SUBSCRIBER_COUNT"],
        "gross_revenue_cents": TEST_DEFAULTS["CANONICAL_GROSS_REVENUE_CENTS"],
    }
    payload.update(overrides)
    return payload


def statement_payload(rights_holder_id, period_id, expected_period_version, **overrides) -> dict:
    payload = {
        "rights_holder_id": rights_holder_id,
        "period_id": period_id,
        "expected_period_version": expected_period_version,
    }
    payload.update(overrides)
    return payload


def audit_engagement_payload(rights_holder_id, statement_id, **overrides) -> dict:
    payload = {
        "rights_holder_id": rights_holder_id,
        "statement_id": statement_id,
        "requested_scope_start": TEST_DEFAULTS["PERIOD_USAGE_START"],
        "requested_scope_end": TEST_DEFAULTS["PERIOD_USAGE_END"],
    }
    payload.update(overrides)
    return payload


def rate_schedule_payload(**overrides) -> dict:
    payload = {
        "proceeding_ref": TEST_DEFAULTS["SCHEDULE_PROCEEDING_REF"],
        "territory_code": "GB",
        "subscription_tier": "INDIVIDUAL",
        "revenue_share_bps": 7000,
        "per_subscriber_minimum_cents": 500,
        "mechanical_share_bps": 4000,
        "performance_share_bps": 6000,
        "statutory_floor_per_play_millicents": 100,
        "effective_from": TEST_DEFAULTS["SCHEDULE_EFFECTIVE_FROM"],
        "effective_to": TEST_DEFAULTS["SCHEDULE_EFFECTIVE_TO"],
    }
    payload.update(overrides)
    return payload


def rejection_payload(**overrides) -> dict:
    payload = {"rejection_reason": "Chain of title not established"}
    payload.update(overrides)
    return payload


def dispute_payload(disputing_holder_id, **overrides) -> dict:
    payload = {"disputing_holder_id": disputing_holder_id}
    payload.update(overrides)
    return payload


def data_production_payload(statement_line_ids, **overrides) -> dict:
    payload = {"statement_line_ids": list(statement_line_ids)}
    payload.update(overrides)
    return payload


def findings_payload(asserted_underpayment_cents, **overrides) -> dict:
    payload = {"asserted_underpayment_cents": asserted_underpayment_cents}
    payload.update(overrides)
    return payload


def settlement_payload(resolution, **overrides) -> dict:
    payload = {"resolution": resolution}
    payload.update(overrides)
    return payload
