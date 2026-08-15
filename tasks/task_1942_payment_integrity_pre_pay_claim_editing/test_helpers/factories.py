"""Payload factories — one per creatable resource, input fields only."""


def create_provider_payload(**overrides) -> dict:
    defaults = {
        "npi": "NPI-0001",
        "name": "Test Provider",
    }
    defaults.update(overrides)
    return defaults


def patch_provider_payload(status="TERMINATED") -> dict:
    return {"status": status}


def create_edit_rule_payload(**overrides) -> dict:
    defaults = {
        "edit_code": "EDIT-01",
        "category": "CODING",
        "source": "INTERNAL",
    }
    defaults.update(overrides)
    return defaults


def create_edit_version_payload(**overrides) -> dict:
    defaults = {
        "severity": "DENY",
        "applies_to_claim_types": ["PROFESSIONAL"],
        "logic_expression": "deny line",
        "effective_from": "2026-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def approve_version_payload(expected_edit_rule_version, **overrides) -> dict:
    defaults = {"expected_edit_rule_version": expected_edit_rule_version}
    defaults.update(overrides)
    return defaults


def create_vendor_edit_payload(**overrides) -> dict:
    defaults = {
        "vendor_name": "EditCorp",
        "vendor_edit_key": "EC-100",
    }
    defaults.update(overrides)
    return defaults


def map_vendor_edit_payload(edit_rule_id, comparison_status="DUPLICATE") -> dict:
    return {"edit_rule_id": edit_rule_id, "comparison_status": comparison_status}


def create_claim_payload(provider_id, **overrides) -> dict:
    defaults = {
        "claim_number": "C1",
        "provider_id": provider_id,
        "member_id": "M-1",
        "claim_type": "PROFESSIONAL",
        "total_billed_cents": 30000,
        "service_from": "2026-07-10T00:00:00Z",
        "service_to": "2026-07-10T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_claim_line_payload(line_number=1, procedure_code="99213",
                              billed_cents=30000, **overrides) -> dict:
    defaults = {
        "line_number": line_number,
        "procedure_code": procedure_code,
        "billed_cents": billed_cents,
    }
    defaults.update(overrides)
    return defaults


def assign_task_payload(reviewer_user_id, **overrides) -> dict:
    defaults = {"reviewer_user_id": reviewer_user_id}
    defaults.update(overrides)
    return defaults


def decide_task_payload(outcome, **overrides) -> dict:
    defaults = {"outcome": outcome}
    defaults.update(overrides)
    return defaults


def create_dispute_payload(edit_hit_id, expected_claim_version,
                           reason="contest denial") -> dict:
    return {
        "edit_hit_id": edit_hit_id,
        "reason": reason,
        "expected_claim_version": expected_claim_version,
    }


def decide_dispute_payload(outcome, **overrides) -> dict:
    defaults = {"outcome": outcome}
    defaults.update(overrides)
    return defaults


def complete_ibr_payload(findings_cents=0) -> dict:
    return {"findings_cents": findings_cents}


def record_findings_payload(**overrides) -> dict:
    return dict(overrides)


def decide_inpatient_payload(outcome, **overrides) -> dict:
    defaults = {"outcome": outcome}
    defaults.update(overrides)
    return defaults


def create_savings_period_payload(period_key="2026-08") -> dict:
    return {"period_key": period_key}
