"""Payload factories — one per entity, input fields only (PRD §3, §4)."""

DEFAULTS = {
    "GROWER_CODE": "G-1",
    "FULL_NAME": "Test Grower",
    "CONTRACT_NO": "C-1",
    "BASE_PAY_CENTS_PER_LB": 6,
    "COMMITTED_HOUSE_COUNT": 1,
    "TERM_START_DATE": "2026-01-01",
    "TERM_END_DATE": "2027-01-01",
    "HOUSE_NO": "H1",
    "CAPACITY_BIRDS": 10000,
    "FLOCK_NO": "F-1",
    "SCHEDULED_DATE": "2026-08-01",
    "HEAD_COUNT": 5000,
    "DELIVERED_DATE": "2026-08-05",
    "FEED_LBS": 10000,
    "FEED_TYPE": "STARTER",
    "TICKET_NO": "FT-1",
    "REPORT_DATE": "2026-08-10",
    "DEAD_HEAD": 0,
    "CONDEMNED_HEAD": 0,
    "CATCH_DATE": "2026-09-10",
    "WEIGHED_AT": "2026-09-10T08:00:00Z",
    "LIVE_WEIGHT_LBS": 5000,
    "AUDIT_DATE": "2026-08-10",
    "AUDIT_RESULT": "PASS",
    "QUARANTINE_DAYS": 0,
    "GROUP_CODE": "WK-1",
    "WEEK_ENDING_DATE": "2026-12-31",
    "CREW_CODE": "CREW-1",
    "MAX_CATCHES_PER_DAY": 2,
    "PRINCIPAL_CENTS": 100000,
    "RECOVERY_PCT": 15,
    "PURPOSE": "OPERATING",
    "NEW_TERM_END_DATE": "2029-01-01",
    "NEW_COMMITTED_HOUSE_COUNT": 2,
}


def create_grower_payload(**overrides) -> dict:
    defaults = {
        "grower_code": DEFAULTS["GROWER_CODE"],
        "full_name": DEFAULTS["FULL_NAME"],
    }
    defaults.update(overrides)
    return defaults


def create_contract_payload(grower_id, **overrides) -> dict:
    defaults = {
        "grower_id": grower_id,
        "contract_no": DEFAULTS["CONTRACT_NO"],
        "base_pay_cents_per_lb": DEFAULTS["BASE_PAY_CENTS_PER_LB"],
        "committed_house_count": DEFAULTS["COMMITTED_HOUSE_COUNT"],
        "term_start_date": DEFAULTS["TERM_START_DATE"],
        "term_end_date": DEFAULTS["TERM_END_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_house_payload(grower_id, **overrides) -> dict:
    defaults = {
        "grower_id": grower_id,
        "house_no": DEFAULTS["HOUSE_NO"],
        "capacity_birds": DEFAULTS["CAPACITY_BIRDS"],
    }
    defaults.update(overrides)
    return defaults


def create_flock_payload(house_id, contract_id, settlement_group_id, **overrides) -> dict:
    defaults = {
        "house_id": house_id,
        "contract_id": contract_id,
        "settlement_group_id": settlement_group_id,
        "flock_no": DEFAULTS["FLOCK_NO"],
    }
    defaults.update(overrides)
    return defaults


def create_placement_payload(**overrides) -> dict:
    defaults = {
        "scheduled_date": DEFAULTS["SCHEDULED_DATE"],
        "head_count": DEFAULTS["HEAD_COUNT"],
    }
    defaults.update(overrides)
    return defaults


def create_feed_delivery_payload(**overrides) -> dict:
    defaults = {
        "delivered_date": DEFAULTS["DELIVERED_DATE"],
        "feed_lbs": DEFAULTS["FEED_LBS"],
        "feed_type": DEFAULTS["FEED_TYPE"],
        "ticket_no": DEFAULTS["TICKET_NO"],
    }
    defaults.update(overrides)
    return defaults


def create_mortality_report_payload(**overrides) -> dict:
    defaults = {
        "report_date": DEFAULTS["REPORT_DATE"],
        "dead_head": DEFAULTS["DEAD_HEAD"],
        "condemned_head": DEFAULTS["CONDEMNED_HEAD"],
    }
    defaults.update(overrides)
    return defaults


def create_catch_schedule_payload(crew_id, **overrides) -> dict:
    defaults = {
        "crew_id": crew_id,
        "catch_date": DEFAULTS["CATCH_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_catch_crew_payload(**overrides) -> dict:
    defaults = {
        "crew_code": DEFAULTS["CREW_CODE"],
        "max_catches_per_day": DEFAULTS["MAX_CATCHES_PER_DAY"],
    }
    defaults.update(overrides)
    return defaults


def create_weight_ticket_payload(**overrides) -> dict:
    defaults = {
        "ticket_no": DEFAULTS["TICKET_NO"],
        "weighed_at": DEFAULTS["WEIGHED_AT"],
        "live_weight_lbs": DEFAULTS["LIVE_WEIGHT_LBS"],
    }
    defaults.update(overrides)
    return defaults


def create_biosecurity_audit_payload(**overrides) -> dict:
    defaults = {
        "audit_date": DEFAULTS["AUDIT_DATE"],
        "result": DEFAULTS["AUDIT_RESULT"],
        "quarantine_days": DEFAULTS["QUARANTINE_DAYS"],
    }
    defaults.update(overrides)
    return defaults


def create_settlement_group_payload(**overrides) -> dict:
    defaults = {
        "group_code": DEFAULTS["GROUP_CODE"],
        "week_ending_date": DEFAULTS["WEEK_ENDING_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_loan_payload(expected_grower_version, **overrides) -> dict:
    defaults = {
        "principal_cents": DEFAULTS["PRINCIPAL_CENTS"],
        "recovery_pct": DEFAULTS["RECOVERY_PCT"],
        "purpose": DEFAULTS["PURPOSE"],
        "expected_grower_version": expected_grower_version,
    }
    defaults.update(overrides)
    return defaults


def renew_contract_payload(**overrides) -> dict:
    defaults = {
        "new_term_end_date": DEFAULTS["NEW_TERM_END_DATE"],
        "new_committed_house_count": DEFAULTS["NEW_COMMITTED_HOUSE_COUNT"],
    }
    defaults.update(overrides)
    return defaults
