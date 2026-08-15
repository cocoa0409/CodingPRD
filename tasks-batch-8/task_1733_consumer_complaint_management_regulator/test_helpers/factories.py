"""Payload factories — one per creatable entity, input fields only (PRD §3)."""

DEFAULTS = {
    "PRODUCT_DISPLAY_NAME": "Test Product",
    "CHANNEL_DISPLAY_NAME": "Test Channel",
    "COMPLAINANT_REF": "CUST-1000",
    "NARRATIVE": "Consumer reports an issue with the account.",
    "PROCESS_STEP": "ACCOUNT_MAINTENANCE",
    "TEMPLATE_BODY": "We have reviewed your complaint.",
    "RESPONSE_TEXT": "We have reviewed your complaint and taken action.",
    "REFERRAL_RESPONSE_TEXT": "Response filed with the regulator.",
    "ESCALATION_REASON": "Requires executive attention.",
}


def create_product_payload(**overrides) -> dict:
    defaults = {
        "product_code": "P-1",
        "display_name": DEFAULTS["PRODUCT_DISPLAY_NAME"],
    }
    defaults.update(overrides)
    return defaults


def create_channel_payload(**overrides) -> dict:
    defaults = {
        "channel_code": "WEB",
        "display_name": DEFAULTS["CHANNEL_DISPLAY_NAME"],
    }
    defaults.update(overrides)
    return defaults


def create_taxonomy_category_payload(**overrides) -> dict:
    defaults = {"category_code": "C.1"}
    defaults.update(overrides)
    return defaults


def create_response_template_payload(**overrides) -> dict:
    defaults = {
        "template_key": "TPL-1",
        "channel_code": "WEB",
        "category_code": "C.1",
        "body": DEFAULTS["TEMPLATE_BODY"],
    }
    defaults.update(overrides)
    return defaults


def create_complaint_payload(**overrides) -> dict:
    defaults = {
        "complainant_ref": DEFAULTS["COMPLAINANT_REF"],
        "channel_code": "WEB",
        "product_code": "P-1",
        "category_code": "C.1",
        "narrative": DEFAULTS["NARRATIVE"],
    }
    defaults.update(overrides)
    return defaults


def create_rca_payload(**overrides) -> dict:
    defaults = {
        "verdict": "SUBSTANTIATED",
        "linked_product_code": "P-1",
        "process_step": DEFAULTS["PROCESS_STEP"],
    }
    defaults.update(overrides)
    return defaults


def create_remediation_decision_payload(**overrides) -> dict:
    defaults = {
        "decision_type": "RESTITUTION",
        "line_items": [{"label": "fee", "amount_cents": 1000}],
        "expected_complaint_version": 1,
    }
    defaults.update(overrides)
    return defaults


def create_quality_review_payload(**overrides) -> dict:
    defaults = {
        "window_start_at": "2026-08-01T00:00:00Z",
        "window_end_at": "2026-08-15T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_escalation_payload(**overrides) -> dict:
    defaults = {
        "escalation_tier": "EXECUTIVE",
        "reason": DEFAULTS["ESCALATION_REASON"],
    }
    defaults.update(overrides)
    return defaults


def create_trend_snapshot_payload(**overrides) -> dict:
    defaults = {
        "period_start_at": "2026-08-01T00:00:00Z",
        "period_end_at": "2026-08-31T23:59:59Z",
    }
    defaults.update(overrides)
    return defaults
