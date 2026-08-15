"""Payload factories — one per entity, input fields only (PRD §3)."""

DEFAULTS = {
    "BUSINESS_NAME": "Test Co",
    "TIER": "POSITIVE_PAY",
    "DEFAULT_DECISION": "PAY",
    "DISPLAY_NAME": "Test User",
    "ACCOUNT_NUMBER": "800001",
    "FILE_REFERENCE": "F-1",
    "CHECK_NUMBER": "1",
    "AMOUNT_CENTS": 100,
    "PAYEE_NAME": "P",
    "ISSUE_DATE": "2026-08-01",
    "CHANNEL": "TELLER",
    "TRAINER_ID": "tr-1",
    "SESSION_START": "2026-08-01T09:00:00Z",
    "SESSION_END": "2026-08-01T10:00:00Z",
    "ORIGINATOR_COMPANY_ID": "ORG1",
    "SEC_CODE": "CCD",
    "RULE_START": "2026-08-01",
    "CLAIM_REASON": "FORGED_SIGNATURE",
}


def create_enrollment_payload(**overrides) -> dict:
    defaults = {
        "business_name": DEFAULTS["BUSINESS_NAME"],
        "tier": DEFAULTS["TIER"],
        "default_decision": DEFAULTS["DEFAULT_DECISION"],
    }
    defaults.update(overrides)
    return defaults


def create_enrollment_user_payload(enrollment_id, **overrides) -> dict:
    defaults = {
        "enrollment_id": enrollment_id,
        "display_name": DEFAULTS["DISPLAY_NAME"],
        "user_role": "ADMIN",
    }
    defaults.update(overrides)
    return defaults


def create_account_payload(enrollment_id, **overrides) -> dict:
    defaults = {
        "enrollment_id": enrollment_id,
        "account_number": DEFAULTS["ACCOUNT_NUMBER"],
    }
    defaults.update(overrides)
    return defaults


def make_check_row(check_number=DEFAULTS["CHECK_NUMBER"],
                   amount_cents=DEFAULTS["AMOUNT_CENTS"],
                   payee_name=DEFAULTS["PAYEE_NAME"],
                   issue_date=DEFAULTS["ISSUE_DATE"]) -> dict:
    return {
        "check_number": str(check_number),
        "amount_cents": amount_cents,
        "payee_name": payee_name,
        "issue_date": issue_date,
    }


def create_issue_file_payload(enrollment_id, account_id, file_reference,
                              rows) -> dict:
    return {
        "enrollment_id": enrollment_id,
        "account_id": account_id,
        "file_reference": file_reference,
        "rows": rows,
    }


def create_presented_item_payload(account_id, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "check_number": DEFAULTS["CHECK_NUMBER"],
        "amount_cents": DEFAULTS["AMOUNT_CENTS"],
        "payee_name_raw": DEFAULTS["PAYEE_NAME"],
        "channel": DEFAULTS["CHANNEL"],
    }
    defaults.update(overrides)
    return defaults


def create_ach_rule_payload(account_id, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "rule_type": "BLOCK",
        "originator_company_id": DEFAULTS["ORIGINATOR_COMPANY_ID"],
        "sec_code": DEFAULTS["SEC_CODE"],
        "effective_start_date": DEFAULTS["RULE_START"],
    }
    defaults.update(overrides)
    return defaults


def create_liability_case_payload(presented_item_id, **overrides) -> dict:
    defaults = {
        "presented_item_id": presented_item_id,
        "claim_reason": DEFAULTS["CLAIM_REASON"],
    }
    defaults.update(overrides)
    return defaults


def create_training_session_payload(enrollment_id, **overrides) -> dict:
    defaults = {
        "enrollment_id": enrollment_id,
        "trainer_id": DEFAULTS["TRAINER_ID"],
        "scheduled_start": DEFAULTS["SESSION_START"],
        "scheduled_end": DEFAULTS["SESSION_END"],
    }
    defaults.update(overrides)
    return defaults
