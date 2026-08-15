"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "WRITER_LEGAL_NAME": "Test Writer",
    "IPI_NUMBER": "00000000101",
    "PRO_AFFILIATION": "ASCAP",
    "WORK_TITLE": "Test Song",
    "GRANT_DATE": "1990-06-15T00:00:00Z",
    "SOCIETY_NAME": "ASCAP",
    "SOCIETY_CODE": "ASCAP",
    "SOCIETY_TYPE": "PRO",
    "TERRITORY_CODE": "US",
    "PUBLISHER_NAME": "OurPub",
    "SUB_PUBLISHER_NAME": "DE Sub",
    "SUB_HOME_TERRITORY": "DE",
    "LICENSEE_NAME": "StreamCo",
    "LICENSEE_TYPE": "STREAMING",
    "PERIOD_START": "2026-01-01T00:00:00Z",
    "PERIOD_END": "2026-03-31T23:59:59Z",
    "AGREEMENT_REF": "ADV-1",
    "PERIOD_LABEL": "2026Q2",
    "STATUTE_BASIS": "SEC_203",
}


def create_writer_payload(**overrides) -> dict:
    defaults = {
        "legal_name": DEFAULTS["WRITER_LEGAL_NAME"],
        "ipi_number": DEFAULTS["IPI_NUMBER"],
        "pro_affiliation": DEFAULTS["PRO_AFFILIATION"],
    }
    defaults.update(overrides)
    return defaults


def create_work_payload(**overrides) -> dict:
    defaults = {
        "title": DEFAULTS["WORK_TITLE"],
        "grant_date": DEFAULTS["GRANT_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_society_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["SOCIETY_NAME"],
        "code": DEFAULTS["SOCIETY_CODE"],
        "society_type": DEFAULTS["SOCIETY_TYPE"],
        "territory_code": DEFAULTS["TERRITORY_CODE"],
    }
    defaults.update(overrides)
    return defaults


def create_society_registration_payload(work_id, society_id, **overrides) -> dict:
    defaults = {"work_id": work_id, "society_id": society_id}
    defaults.update(overrides)
    return defaults


def writer_split_line(writer_id, share_bp) -> dict:
    return {"participant_type": "WRITER", "writer_id": writer_id,
            "share_bp": share_bp}


def publisher_split_line(publisher_name=None, share_bp=10000) -> dict:
    return {"participant_type": "PUBLISHER",
            "publisher_name": publisher_name or DEFAULTS["PUBLISHER_NAME"],
            "share_bp": share_bp}


def create_split_set_payload(work_id, expected_work_version, lines,
                             **overrides) -> dict:
    defaults = {
        "work_id": work_id,
        "expected_work_version": expected_work_version,
        "lines": lines,
    }
    defaults.update(overrides)
    return defaults


def create_sub_publisher_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["SUB_PUBLISHER_NAME"],
        "home_territory_code": DEFAULTS["SUB_HOME_TERRITORY"],
    }
    defaults.update(overrides)
    return defaults


def create_sub_publishing_agreement_payload(sub_publisher_id, **overrides) -> dict:
    defaults = {
        "sub_publisher_id": sub_publisher_id,
        "territory_codes": ["DE"],
        "income_types": ["PERFORMANCE"],
        "retention_bp": 2000,
        "effective_from": "2026-01-01T00:00:00Z",
        "effective_to": "2027-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_licensee_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["LICENSEE_NAME"],
        "licensee_type": DEFAULTS["LICENSEE_TYPE"],
    }
    defaults.update(overrides)
    return defaults


def statement_line_payload(line_number, reported_title, gross_cents,
                           reported_iswc=None, reported_work_code=None) -> dict:
    line = {
        "line_number": line_number,
        "reported_title": reported_title,
        "gross_cents": gross_cents,
    }
    if reported_iswc is not None:
        line["reported_iswc"] = reported_iswc
    if reported_work_code is not None:
        line["reported_work_code"] = reported_work_code
    return line


def create_royalty_statement_payload(source_type, source_id, income_type,
                                     territory_code, period_start, period_end,
                                     gross_amount_cents, **overrides) -> dict:
    defaults = {
        "source_type": source_type,
        "source_id": source_id,
        "income_type": income_type,
        "territory_code": territory_code,
        "period_start": period_start,
        "period_end": period_end,
        "gross_amount_cents": gross_amount_cents,
    }
    defaults.update(overrides)
    return defaults


def create_advance_payload(writer_id, expected_writer_version, amount_cents,
                           **overrides) -> dict:
    defaults = {
        "writer_id": writer_id,
        "expected_writer_version": expected_writer_version,
        "agreement_ref": DEFAULTS["AGREEMENT_REF"],
        "amount_cents": amount_cents,
    }
    defaults.update(overrides)
    return defaults


def create_distribution_run_payload(**overrides) -> dict:
    defaults = {"period_label": DEFAULTS["PERIOD_LABEL"]}
    defaults.update(overrides)
    return defaults


def create_licensee_audit_payload(licensee_id, **overrides) -> dict:
    defaults = {
        "licensee_id": licensee_id,
        "period_start": "2025-01-01T00:00:00Z",
        "period_end": "2025-12-31T23:59:59Z",
        "valuation_method": "ACTUAL_SHORTFALL",
    }
    defaults.update(overrides)
    return defaults


def issue_findings_payload(actual_shortfall_cents, sampled_base_cents=None,
                           reported_base_cents=None) -> dict:
    payload = {"actual_shortfall_cents": actual_shortfall_cents}
    if sampled_base_cents is not None:
        payload["sampled_base_cents"] = sampled_base_cents
    if reported_base_cents is not None:
        payload["reported_base_cents"] = reported_base_cents
    return payload


def create_termination_claim_payload(work_id, statute_basis,
                                     intended_effective_date,
                                     **overrides) -> dict:
    defaults = {
        "work_id": work_id,
        "statute_basis": statute_basis,
        "intended_effective_date": intended_effective_date,
    }
    defaults.update(overrides)
    return defaults
