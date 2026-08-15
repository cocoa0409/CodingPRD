"""Payload factories — one per entity, input fields only (PRD §3, §4)."""


def create_retention_policy_payload(**overrides) -> dict:
    defaults = {
        "policy_code": "RP-1YR",
        "duration_days": 365,
        "disposal_action": "DELETE",
    }
    defaults.update(overrides)
    return defaults


def create_data_element_payload(**overrides) -> dict:
    defaults = {
        "element_key": "email",
        "category": "BASIC_CONTACT",
        "classification": "INTERNAL",
    }
    defaults.update(overrides)
    return defaults


def create_data_system_payload(**overrides) -> dict:
    defaults = {
        "system_key": "sys-1",
        "hosting_region": "US",
        "stores_categories": ["FINANCIAL"],
    }
    defaults.update(overrides)
    return defaults


def create_notice_payload(**overrides) -> dict:
    defaults = {
        "scope": "WEBSITE",
        "title": "Privacy notice v1",
        "body": "Notice body text.",
        "effective_from": "2026-01-01T00:00:00Z",
        "effective_to": "2027-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_state_law_rule_payload(**overrides) -> dict:
    defaults = {
        "state_code": "CA",
        "law_name": "CCPA",
        "resident_records_threshold": 1,
        "revenue_share_threshold_pct": 100.0,
        "request_deadline_days": 45,
        "extension_days": 30,
    }
    defaults.update(overrides)
    return defaults


def create_vendor_payload(**overrides) -> dict:
    defaults = {
        "vendor_name": "DataPro",
        "home_region": "US",
        "processes_categories": ["FINANCIAL"],
    }
    defaults.update(overrides)
    return defaults


def create_contract_payload(**overrides) -> dict:
    defaults = {
        "provided_clauses": ["DPA", "BREACH_NOTICE_72H", "DELETION_ON_EXIT"],
        "expected_vendor_version": 1,
    }
    defaults.update(overrides)
    return defaults


def create_activity_payload(**overrides) -> dict:
    defaults = {
        "activity_name": "Newsletter",
        "business_unit": "Marketing",
        "notice_scope": "WEBSITE",
        "data_element_ids": [],
    }
    defaults.update(overrides)
    return defaults


def create_purpose_payload(**overrides) -> dict:
    defaults = {
        "purpose_type": "MARKETING",
        "legal_basis": "CONTRACT",
        "retention_policy_id": None,
    }
    defaults.update(overrides)
    return defaults


def create_consumer_payload(**overrides) -> dict:
    defaults = {
        "email": "tx@x.com",
        "full_name": "TX One",
        "state_code": "TX",
    }
    defaults.update(overrides)
    return defaults


def create_rights_request_payload(**overrides) -> dict:
    defaults = {
        "request_type": "ACCESS",
        "requested_categories": ["BASIC_CONTACT"],
    }
    defaults.update(overrides)
    return defaults


def create_transfer_payload(**overrides) -> dict:
    defaults = {
        "source_system_id": None,
        "vendor_id": None,
        "vendor_contract_id": None,
        "activity_id": None,
        "dest_region": "EU",
        "mechanism": "SCC_2021",
        "effective_from": "2026-03-01T00:00:00Z",
        "effective_to": "2026-09-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def applicability_run_payload(**overrides) -> dict:
    defaults = {
        "state_revenues": {},
        "total_revenue_cents": 1000,
    }
    defaults.update(overrides)
    return defaults


def clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
