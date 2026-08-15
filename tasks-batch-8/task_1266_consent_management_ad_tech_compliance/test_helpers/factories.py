"""Payload factories — one per entity, input fields only (per PRD endpoint inputs)."""

DEFAULTS = {
    "PROPERTY_NAME": "Test Property",
    "SALE_SHARE_DESIGNATION": "SELLS_AND_SHARES",
    "JURISDICTION_CODE": "US-CA",
    "BANNER_REGIME": "OPT_OUT_ALLOWED",
    "MIN_CONSENT_AGE": 16,
    "RETENTION_DAYS": 30,
    "GPC_HONORED": True,
    "EFFECTIVE_FROM": "2026-01-01T00:00:00Z",
    "EFFECTIVE_TO": "2027-01-01T00:00:00Z",
    "CATEGORIES_SHOWN": ["ANALYTICS", "ADVERTISING"],
    "CONFIG_LABEL": "v1",
    "VENDOR_LEGAL_NAME": "VendorCo",
    "DECLARED_PURPOSES": ["ADVERTISING"],
    "TRACKER_SIGNATURES": ["tracker-1.com"],
    "PURPOSE_CATEGORY": "ANALYTICS",
    "EXTERNAL_REF": "visitor@example.com",
    "ADULT_BIRTHDATE": "1990-01-01T00:00:00Z",
    "SCAN_START": "2026-06-01T10:00:00Z",
    "SCAN_DURATION_MINUTES": 30,
    "REGULATOR_REF": "REG-1",
    "DEADLINE_DAYS": 30,
}


def create_property_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["PROPERTY_NAME"],
        "sale_share_designation": DEFAULTS["SALE_SHARE_DESIGNATION"],
    }
    defaults.update(overrides)
    return defaults


def create_jurisdiction_policy_payload(property_id, **overrides) -> dict:
    defaults = {
        "property_id": property_id,
        "jurisdiction_code": DEFAULTS["JURISDICTION_CODE"],
        "banner_regime": DEFAULTS["BANNER_REGIME"],
        "min_consent_age": DEFAULTS["MIN_CONSENT_AGE"],
        "retention_days": DEFAULTS["RETENTION_DAYS"],
        "gpc_honored": DEFAULTS["GPC_HONORED"],
        "effective_from": DEFAULTS["EFFECTIVE_FROM"],
        "effective_to": DEFAULTS["EFFECTIVE_TO"],
    }
    defaults.update(overrides)
    return defaults


def create_banner_config_payload(property_id, **overrides) -> dict:
    defaults = {
        "property_id": property_id,
        "jurisdiction_code": DEFAULTS["JURISDICTION_CODE"],
        "categories_shown": list(DEFAULTS["CATEGORIES_SHOWN"]),
        "config_label": DEFAULTS["CONFIG_LABEL"],
    }
    defaults.update(overrides)
    return defaults


def publish_banner_config_payload(expected_property_version, **overrides) -> dict:
    defaults = {"expected_property_version": expected_property_version}
    defaults.update(overrides)
    return defaults


def create_vendor_payload(property_id, **overrides) -> dict:
    defaults = {
        "property_id": property_id,
        "legal_name": DEFAULTS["VENDOR_LEGAL_NAME"],
        "declared_purposes": list(DEFAULTS["DECLARED_PURPOSES"]),
        "tracker_signatures": list(DEFAULTS["TRACKER_SIGNATURES"]),
    }
    defaults.update(overrides)
    return defaults


def create_tag_rule_payload(vendor_id, banner_config_id, **overrides) -> dict:
    defaults = {
        "vendor_id": vendor_id,
        "banner_config_id": banner_config_id,
        "purpose_category": DEFAULTS["PURPOSE_CATEGORY"],
    }
    defaults.update(overrides)
    return defaults


def create_visitor_payload(property_id, **overrides) -> dict:
    defaults = {
        "property_id": property_id,
        "external_ref": DEFAULTS["EXTERNAL_REF"],
        "jurisdiction_code": DEFAULTS["JURISDICTION_CODE"],
    }
    defaults.update(overrides)
    return defaults


def age_attestation_payload(birthdate=None, **overrides) -> dict:
    defaults = {"attested_birthdate": birthdate or DEFAULTS["ADULT_BIRTHDATE"]}
    defaults.update(overrides)
    return defaults


def gpc_signal_payload(signal="ON") -> dict:
    return {"signal": signal}


def create_consent_record_payload(purpose_category="ANALYTICS", **overrides) -> dict:
    defaults = {"purpose_category": purpose_category}
    defaults.update(overrides)
    return defaults


def create_do_not_sell_request_payload(**overrides) -> dict:
    return dict(overrides)


def create_tag_audit_scan_payload(property_id, **overrides) -> dict:
    defaults = {
        "property_id": property_id,
        "scheduled_start": DEFAULTS["SCAN_START"],
        "duration_minutes": DEFAULTS["SCAN_DURATION_MINUTES"],
    }
    defaults.update(overrides)
    return defaults


def run_scan_payload(observed_trackers=None) -> dict:
    return {"observed_trackers": observed_trackers if observed_trackers is not None else []}


def observed_tracker(tracker_signature, purpose_category="ADVERTISING") -> dict:
    return {"tracker_signature": tracker_signature, "purpose_category": purpose_category}


def create_regulatory_sweep_payload(property_id, **overrides) -> dict:
    defaults = {
        "property_id": property_id,
        "regulator_ref": DEFAULTS["REGULATOR_REF"],
        "jurisdiction_code": DEFAULTS["JURISDICTION_CODE"],
        "deadline_days": DEFAULTS["DEADLINE_DAYS"],
    }
    defaults.update(overrides)
    return defaults
