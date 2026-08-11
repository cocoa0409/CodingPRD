"""Payload factories — one per creatable entity, input fields only (PRD section 4)."""

DEFAULTS = {
    "AGENCY_NAME": "Test Agency",
    "COMMISSION_PCT": 0.15,
    "SLUSH_CAPACITY": 50,
    "AGENT_NAME": "Agent One",
    "AUTHOR_NAME": "Author One",
    "EDITOR_NAME": "Ed A",
    "IMPRINT": "Imprint A",
    "GENRE": "FICTION",
    "WORD_COUNT": 90000,
    "TITLE": "Test Manuscript",
    "MAX_EDITORS": 5,
    "ADVANCE_CENTS": 500000,
    "PCT_HARDCOVER": 0.10,
    "PCT_TRADE": 0.08,
    "PCT_EBOOK": 0.25,
    "EVAL_SCORE": 80,
}

_email_counter = {"n": 0}


def _unique_email(prefix: str) -> str:
    _email_counter["n"] += 1
    return f"{prefix}-{_email_counter['n']}@example.com"


def create_agency_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["AGENCY_NAME"],
        "commission_pct": DEFAULTS["COMMISSION_PCT"],
        "slush_capacity": DEFAULTS["SLUSH_CAPACITY"],
    }
    defaults.update(overrides)
    return defaults


def create_agent_payload(agency_id: str, **overrides) -> dict:
    defaults = {
        "agency_id": agency_id,
        "display_name": DEFAULTS["AGENT_NAME"],
        "email": _unique_email("agent"),
    }
    defaults.update(overrides)
    return defaults


def create_author_payload(agency_id: str, **overrides) -> dict:
    defaults = {
        "agency_id": agency_id,
        "display_name": DEFAULTS["AUTHOR_NAME"],
        "email": _unique_email("author"),
    }
    defaults.update(overrides)
    return defaults


def create_editor_payload(agency_id: str, **overrides) -> dict:
    defaults = {
        "agency_id": agency_id,
        "display_name": DEFAULTS["EDITOR_NAME"],
        "imprint": DEFAULTS["IMPRINT"],
        "email": _unique_email("editor"),
    }
    defaults.update(overrides)
    return defaults


def create_query_letter_payload(author_id: str, **overrides) -> dict:
    defaults = {
        "author_id": author_id,
        "genre": DEFAULTS["GENRE"],
        "word_count": DEFAULTS["WORD_COUNT"],
    }
    defaults.update(overrides)
    return defaults


def request_manuscript_payload(**overrides) -> dict:
    defaults = {"title": DEFAULTS["TITLE"]}
    defaults.update(overrides)
    return defaults


def evaluate_manuscript_payload(**overrides) -> dict:
    defaults = {"eval_score": DEFAULTS["EVAL_SCORE"]}
    defaults.update(overrides)
    return defaults


def create_client_agreement_payload(author_id: str, manuscript_id: str, agent_id: str, **overrides) -> dict:
    defaults = {
        "author_id": author_id,
        "manuscript_id": manuscript_id,
        "agent_id": agent_id,
    }
    defaults.update(overrides)
    return defaults


def create_submission_round_payload(manuscript_id: str, agent_id: str, **overrides) -> dict:
    defaults = {
        "manuscript_id": manuscript_id,
        "agent_id": agent_id,
        "max_editors": DEFAULTS["MAX_EDITORS"],
    }
    defaults.update(overrides)
    return defaults


def create_submission_payload(submission_round_id: str, editor_id: str, **overrides) -> dict:
    defaults = {
        "submission_round_id": submission_round_id,
        "editor_id": editor_id,
    }
    defaults.update(overrides)
    return defaults


def create_offer_payload(submission_id: str, **overrides) -> dict:
    defaults = {
        "submission_id": submission_id,
        "advance_cents": DEFAULTS["ADVANCE_CENTS"],
        "royalty_pct_hardcover": DEFAULTS["PCT_HARDCOVER"],
        "royalty_pct_trade": DEFAULTS["PCT_TRADE"],
        "royalty_pct_ebook": DEFAULTS["PCT_EBOOK"],
    }
    defaults.update(overrides)
    return defaults


def revise_offer_payload(**overrides) -> dict:
    defaults = {
        "advance_cents": DEFAULTS["ADVANCE_CENTS"],
        "royalty_pct_hardcover": DEFAULTS["PCT_HARDCOVER"],
        "royalty_pct_trade": DEFAULTS["PCT_TRADE"],
        "royalty_pct_ebook": DEFAULTS["PCT_EBOOK"],
    }
    defaults.update(overrides)
    return defaults


def create_royalty_statement_payload(deal_id: str, **overrides) -> dict:
    defaults = {
        "deal_id": deal_id,
        "period_index": 0,
        "units_hardcover": 0,
        "units_trade": 0,
        "units_ebook": 0,
        "net_receipts_hardcover_cents": 0,
        "net_receipts_trade_cents": 0,
        "net_receipts_ebook_cents": 0,
        "publisher_reported_royalty_cents": 0,
    }
    # Tuple shorthands unpack onto the PRD-declared per-format fields so the
    # emitted payload never carries undeclared `units`/`receipts` keys.
    units = overrides.pop("units", None)
    if units is not None:
        u_h, u_t, u_e = units
        defaults["units_hardcover"] = u_h
        defaults["units_trade"] = u_t
        defaults["units_ebook"] = u_e
    receipts = overrides.pop("receipts", None)
    if receipts is not None:
        r_h, r_t, r_e = receipts
        defaults["net_receipts_hardcover_cents"] = r_h
        defaults["net_receipts_trade_cents"] = r_t
        defaults["net_receipts_ebook_cents"] = r_e
    defaults.update(overrides)
    return defaults


def resolve_audit_payload(net_receipts_hardcover_cents: int,
                          net_receipts_trade_cents: int,
                          net_receipts_ebook_cents: int) -> dict:
    return {
        "net_receipts_hardcover_cents": net_receipts_hardcover_cents,
        "net_receipts_trade_cents": net_receipts_trade_cents,
        "net_receipts_ebook_cents": net_receipts_ebook_cents,
    }
