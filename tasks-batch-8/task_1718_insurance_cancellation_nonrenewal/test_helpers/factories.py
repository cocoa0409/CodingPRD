"""Payload factories — one per entity, input fields only (PRD §3 / §4)."""

DEFAULTS = {
    "STATE_CODE": "ZZ",
    "PERMISSIBLE_GROUNDS": ["NONPAYMENT"],
    "NONPAYMENT_NOTICE_DAYS": 10,
    "OTHER_GROUNDS_NOTICE_DAYS": 30,
    "MORTGAGEE_NOTICE_DAYS": 45,
    "NONRENEWAL_NOTICE_DAYS": 60,
    "SHORT_RATE_PENALTY_PCT": 0.0,
    "REINSTATEMENT_WINDOW_DAYS": 45,
    "MAX_REINSTATEMENTS": 2,
    "NONRENEWAL_CONTENT_CODES": ["SPECIFIC_REASON"],
    "FULL_NAME": "Test Insured",
    "MAILING_ADDRESS": "1 Test St",
    "EMAIL": "insured@example.com",
    "TERM_START": "2026-01-01",
    "TERM_END": "2027-01-01",
    "TOTAL_PREMIUM_CENTS": 10000,
    "GROUND_CODE": "NONPAYMENT",
    "INTEREST_TYPE": "MORTGAGEE",
    "INSTITUTION_NAME": "Test Bank",
    "REASON_CODE": "UNDERWRITING_GUIDELINES",
    "REASON_TEXT": "Underwriting guideline change",
    "TRACKING_CODE": "TRACK-1",
    "GROUNDS_TEXT": "Appeal grounds",
}


def create_state_profile_payload(**overrides) -> dict:
    defaults = {
        "state_code": DEFAULTS["STATE_CODE"],
        "permissible_grounds": list(DEFAULTS["PERMISSIBLE_GROUNDS"]),
        "nonpayment_notice_days": DEFAULTS["NONPAYMENT_NOTICE_DAYS"],
        "other_grounds_notice_days": DEFAULTS["OTHER_GROUNDS_NOTICE_DAYS"],
        "mortgagee_notice_days": DEFAULTS["MORTGAGEE_NOTICE_DAYS"],
        "nonrenewal_notice_days": DEFAULTS["NONRENEWAL_NOTICE_DAYS"],
        "short_rate_penalty_pct": DEFAULTS["SHORT_RATE_PENALTY_PCT"],
        "reinstatement_window_days": DEFAULTS["REINSTATEMENT_WINDOW_DAYS"],
        "max_reinstatements": DEFAULTS["MAX_REINSTATEMENTS"],
        "nonrenewal_content_codes": list(DEFAULTS["NONRENEWAL_CONTENT_CODES"]),
    }
    defaults.update(overrides)
    return defaults


def create_policyholder_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["FULL_NAME"],
        "mailing_address": DEFAULTS["MAILING_ADDRESS"],
        "email": DEFAULTS["EMAIL"],
    }
    defaults.update(overrides)
    return defaults


def create_policy_payload(policyholder_id, state_profile_id, policy_number, **overrides) -> dict:
    defaults = {
        "policyholder_id": policyholder_id,
        "state_profile_id": state_profile_id,
        "policy_number": policy_number,
        "term_start_date": DEFAULTS["TERM_START"],
        "term_end_date": DEFAULTS["TERM_END"],
        "total_premium_cents": DEFAULTS["TOTAL_PREMIUM_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_interest_payload(**overrides) -> dict:
    defaults = {
        "interest_type": DEFAULTS["INTEREST_TYPE"],
        "institution_name": DEFAULTS["INSTITUTION_NAME"],
        "mailing_address": DEFAULTS["MAILING_ADDRESS"],
    }
    defaults.update(overrides)
    return defaults


def create_cancellation_case_payload(policy_id, expected_policy_version, **overrides) -> dict:
    defaults = {
        "policy_id": policy_id,
        "ground_code": DEFAULTS["GROUND_CODE"],
        "expected_policy_version": expected_policy_version,
    }
    defaults.update(overrides)
    return defaults


def approve_cancellation_payload(scheduled_effective_date) -> dict:
    return {"scheduled_effective_date": scheduled_effective_date}


def rescind_payload(reason="Rescinded per compliance review") -> dict:
    return {"reason": reason}


def notice_entry(recipient_kind, mailed_on_date, tracking_code, insured_interest_id=None) -> dict:
    entry = {
        "recipient_kind": recipient_kind,
        "mailed_on_date": mailed_on_date,
        "tracking_code": tracking_code,
    }
    if insured_interest_id is not None:
        entry["insured_interest_id"] = insured_interest_id
    return entry


def dispatch_payload(notices) -> dict:
    return {"notices": notices}


def create_nonrenewal_case_payload(policy_id, **overrides) -> dict:
    defaults = {
        "policy_id": policy_id,
        "reason_code": DEFAULTS["REASON_CODE"],
        "reason_text": DEFAULTS["REASON_TEXT"],
        "content_codes_present": list(DEFAULTS["NONRENEWAL_CONTENT_CODES"]),
    }
    defaults.update(overrides)
    return defaults


def create_reinstatement_payload(policy_id, cancellation_case_id, expected_policy_version) -> dict:
    return {
        "policy_id": policy_id,
        "cancellation_case_id": cancellation_case_id,
        "expected_policy_version": expected_policy_version,
    }


def create_appeal_payload(cancellation_case_id, filed_by="POLICYHOLDER", **overrides) -> dict:
    defaults = {
        "cancellation_case_id": cancellation_case_id,
        "filed_by": filed_by,
        "grounds_text": DEFAULTS["GROUNDS_TEXT"],
    }
    defaults.update(overrides)
    return defaults


def decide_payload(decision) -> dict:
    return {"decision": decision}


def clock_payload(to_iso8601) -> dict:
    return {"to_iso8601": to_iso8601}
