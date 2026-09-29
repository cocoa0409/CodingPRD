"""Existence resolution (PRD section 2.8 rules 10 and 11)."""
from errors import ApiError
from store import db

_TABLES = {
    "distributor": ("distributors", "ERR_DISTRIBUTOR_NOT_FOUND"),
    "agreement": ("agreements", "ERR_AGREEMENT_NOT_FOUND"),
    "rate_card_entry": ("rate_card_entries", "ERR_RATE_CARD_ENTRY_NOT_FOUND"),
    "mfn": ("mfn_clauses", "ERR_MFN_CLAUSE_NOT_FOUND"),
    "report": ("subscriber_reports", "ERR_REPORT_NOT_FOUND"),
    "engagement": ("audit_engagements", "ERR_ENGAGEMENT_NOT_FOUND"),
    "finding": ("audit_findings", "ERR_FINDING_NOT_FOUND"),
    "title": ("content_titles", "ERR_TITLE_NOT_FOUND"),
    "window": ("rights_windows", "ERR_WINDOW_NOT_FOUND"),
    "blackout": ("blackout_rules", "ERR_BLACKOUT_NOT_FOUND"),
    "commitment": ("marketing_commitments", "ERR_COMMITMENT_NOT_FOUND"),
    "invoice": ("invoices", "ERR_INVOICE_NOT_FOUND"),
    "analysis": ("renewal_analyses", "ERR_ANALYSIS_NOT_FOUND"),
}


def find(kind, identifier):
    table_name, _ = _TABLES[kind]
    if not isinstance(identifier, str):
        return None
    return getattr(db, table_name).get(identifier)


def must(kind, identifier):
    record = find(kind, identifier)
    if record is None:
        raise ApiError(_TABLES[kind][1], "%s not found" % kind)
    return record


def all_of(kind):
    table_name, _ = _TABLES[kind]
    return list(getattr(db, table_name).values())


def put(kind, record):
    table_name, _ = _TABLES[kind]
    getattr(db, table_name)[record["id"]] = record
    return record
