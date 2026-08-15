"""Payload factories — one per creatable entity, input fields only."""
from .constants import JUSTIFICATION_20, RELEASE_REASON_10, STANDARD_WINDOW_START


def create_program_payload(name="Program", fiscal_year_end_month=12,
                           fiscal_year_end_day=31, **overrides) -> dict:
    defaults = {
        "name": name,
        "fiscal_year_end_month": fiscal_year_end_month,
        "fiscal_year_end_day": fiscal_year_end_day,
    }
    defaults.update(overrides)
    return defaults


def create_record_class_payload(program_id, code="GEN", name="General",
                                monthly_storage_cost_cents_per_gb=10, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "code": code,
        "name": name,
        "monthly_storage_cost_cents_per_gb": monthly_storage_cost_cents_per_gb,
    }
    defaults.update(overrides)
    return defaults


def create_jurisdiction_payload(program_id, code="US-FED", name="Federal", **overrides) -> dict:
    defaults = {"program_id": program_id, "code": code, "name": name}
    defaults.update(overrides)
    return defaults


def create_custodian_payload(program_id, email="c@x.com", full_name="Cust",
                             department="Legal", **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "email": email,
        "full_name": full_name,
        "department": department,
    }
    defaults.update(overrides)
    return defaults


def create_retention_rule_payload(program_id, record_class_id, jurisdiction_id,
                                  rule_code="R-1M", retention_months=1,
                                  trigger_basis="EVENT_DATE",
                                  effective_from=STANDARD_WINDOW_START,
                                  effective_to=None, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "record_class_id": record_class_id,
        "jurisdiction_id": jurisdiction_id,
        "rule_code": rule_code,
        "retention_months": retention_months,
        "trigger_basis": trigger_basis,
        "effective_from": effective_from,
    }
    if effective_to is not None:
        defaults["effective_to"] = effective_to
    defaults.update(overrides)
    return defaults


def supersede_rule_payload(rule_code, retention_months, expected_retention_rule_version,
                           trigger_basis="EVENT_DATE",
                           effective_from=STANDARD_WINDOW_START,
                           effective_to=None, **overrides) -> dict:
    defaults = {
        "rule_code": rule_code,
        "retention_months": retention_months,
        "trigger_basis": trigger_basis,
        "effective_from": effective_from,
        "expected_retention_rule_version": expected_retention_rule_version,
    }
    if effective_to is not None:
        defaults["effective_to"] = effective_to
    defaults.update(overrides)
    return defaults


def resolve_conflict_payload(strategy="APPLY_LONGEST", **overrides) -> dict:
    defaults = {"strategy": strategy}
    defaults.update(overrides)
    return defaults


def create_record_payload(program_id, record_class_id, jurisdiction_id, title="R",
                          source_system="ERP", event_date="2026-06-01T00:00:00Z",
                          size_gb=1, auto_delete_enabled=None,
                          owner_custodian_id=None, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "record_class_id": record_class_id,
        "jurisdiction_id": jurisdiction_id,
        "title": title,
        "source_system": source_system,
        "event_date": event_date,
        "size_gb": size_gb,
    }
    if auto_delete_enabled is not None:
        defaults["auto_delete_enabled"] = auto_delete_enabled
    if owner_custodian_id is not None:
        defaults["owner_custodian_id"] = owner_custodian_id
    defaults.update(overrides)
    return defaults


def create_legal_hold_payload(program_id, matter_ref, custodian_ids, record_ids,
                              title="Hold", reason="Case", **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "matter_ref": matter_ref,
        "title": title,
        "reason": reason,
        "custodian_ids": custodian_ids,
        "record_ids": record_ids,
    }
    defaults.update(overrides)
    return defaults


def release_hold_payload(release_reason=RELEASE_REASON_10,
                         expected_legal_hold_version=1, **overrides) -> dict:
    defaults = {
        "release_reason": release_reason,
        "expected_legal_hold_version": expected_legal_hold_version,
    }
    defaults.update(overrides)
    return defaults


def create_disposition_request_payload(program_id, record_ids, method="SECURE_ERASE",
                                       justification=JUSTIFICATION_20, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "record_ids": record_ids,
        "method": method,
        "justification": justification,
    }
    defaults.update(overrides)
    return defaults


def reject_request_payload(rejection_reason="Need counsel review first", **overrides) -> dict:
    defaults = {"rejection_reason": rejection_reason}
    defaults.update(overrides)
    return defaults


def create_freeze_window_payload(program_id, start_at, end_at,
                                 reason="Audit season", **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "start_at": start_at,
        "end_at": end_at,
        "reason": reason,
    }
    defaults.update(overrides)
    return defaults


def create_hold_audit_payload(program_id, **overrides) -> dict:
    defaults = {"program_id": program_id}
    defaults.update(overrides)
    return defaults
