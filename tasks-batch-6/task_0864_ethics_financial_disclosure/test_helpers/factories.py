"""Payload factories — one per entity, input fields only."""


def create_jurisdiction_payload(**overrides) -> dict:
    """POST /jurisdictions. Only `name` is required; policy limits default server-side."""
    defaults = {"name": "Metro Ethics Board"}
    defaults.update(overrides)
    return defaults


def create_filer_payload(jurisdiction_id, filer_category="APPOINTED", **overrides) -> dict:
    """POST /filers. jurisdiction_id, full_name, official_title, filer_category required."""
    defaults = {
        "jurisdiction_id": jurisdiction_id,
        "full_name": "Ada Council",
        "official_title": "Councilmember",
        "filer_category": filer_category,
    }
    defaults.update(overrides)
    return defaults


def create_filing_period_payload(jurisdiction_id, **overrides) -> dict:
    """POST /filing-periods. jurisdiction_id, statement_type, coverage_start/end, due_at required."""
    defaults = {
        "jurisdiction_id": jurisdiction_id,
        "statement_type": "ANNUAL",
        "coverage_start": "2025-01-01T00:00:00Z",
        "coverage_end": "2025-12-31T00:00:00Z",
        "due_at": "2026-06-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_statement_payload(filer_id, filing_period_id, **overrides) -> dict:
    """POST /statements. filer_id, filing_period_id required."""
    defaults = {
        "filer_id": filer_id,
        "filing_period_id": filing_period_id,
    }
    defaults.update(overrides)
    return defaults


def create_gift_report_payload(filer_id, source_name="Acme Corp", gift_kind="GIFT",
                               received_at="2026-05-01T00:00:00Z", **overrides) -> dict:
    """POST /gift-reports. filer_id, source_name, gift_kind, received_at required."""
    defaults = {
        "filer_id": filer_id,
        "source_name": source_name,
        "gift_kind": gift_kind,
        "received_at": received_at,
    }
    defaults.update(overrides)
    return defaults


def create_recusal_payload(filer_id, matter_id="M1",
                           effective_start="2026-06-01T00:00:00Z",
                           effective_end="2026-06-10T00:00:00Z", **overrides) -> dict:
    """POST /recusals. filer_id, matter_id, effective_start, effective_end required."""
    defaults = {
        "filer_id": filer_id,
        "matter_id": matter_id,
        "effective_start": effective_start,
        "effective_end": effective_end,
    }
    defaults.update(overrides)
    return defaults


def create_complaint_payload(filer_id, allegation="undisclosed asset", **overrides) -> dict:
    """POST /complaints. filer_id, allegation required."""
    defaults = {
        "filer_id": filer_id,
        "allegation": allegation,
        "complainant_ref": "cx-1",
    }
    defaults.update(overrides)
    return defaults


def create_training_record_payload(filer_id, course_code="ETH-101", **overrides) -> dict:
    """POST /training-records. filer_id, course_code required."""
    defaults = {
        "filer_id": filer_id,
        "course_code": course_code,
    }
    defaults.update(overrides)
    return defaults
