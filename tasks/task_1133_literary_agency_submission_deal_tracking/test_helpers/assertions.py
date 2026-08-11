"""Entity assertions and domain invariant checkers.

Each assert_* checks the uniform system fields of PRD section 2.5 (id as a
bare UUID, ISO 8601 created_at/updated_at, integer version) plus the
entity's declared fields and status enumeration. Nullable system/computed
fields are only type-checked when non-null.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AdvanceInstallmentStatus,
    AgencyPosture,
    AgentStatus,
    AuthorStatus,
    ClientAgreementStatus,
    DealStatus,
    EditorStatus,
    Genre,
    ManuscriptStatus,
    Milestone,
    OfferStatus,
    QueryLetterStatus,
    RoyaltyBasis,
    RoyaltyStatementStatus,
    SubmissionRoundStatus,
    SubmissionStatus,
    ValuationMode,
)


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_opt_int(data: dict, field: str):
    assert field in data, f"missing field {field}"
    assert data[field] is None or isinstance(data[field], int), f"{field} must be int or null"


def _assert_opt_str(data: dict, field: str):
    assert field in data, f"missing field {field}"
    assert data[field] is None or isinstance(data[field], str), f"{field} must be str or null"


def assert_agency(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["commission_pct"], (int, float))
    assert isinstance(data["slush_capacity"], int)
    assert isinstance(data["period_index"], int)
    _assert_opt_int(data, "books_closed_through_period_index")
    assert data["posture"] in {p.value for p in AgencyPosture}


def assert_agent(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("agency_id", "")), "agency_id must be a UUID"
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert data["status"] in {s.value for s in AgentStatus}
    assert isinstance(data["open_query_count"], int)


def assert_author(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("agency_id", "")), "agency_id must be a UUID"
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert data["status"] in {s.value for s in AuthorStatus}


def assert_editor(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("agency_id", "")), "agency_id must be a UUID"
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert isinstance(data["imprint"], str) and data["imprint"]
    assert isinstance(data["email"], str) and data["email"]
    assert data["status"] in {s.value for s in EditorStatus}


def assert_query_letter(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("agency_id", "")), "agency_id must be a UUID"
    assert is_valid_uuid(data.get("author_id", "")), "author_id must be a UUID"
    _assert_opt_str(data, "assigned_agent_id")
    assert data["genre"] in {g.value for g in Genre}
    assert isinstance(data["word_count"], int) and data["word_count"] > 0
    _assert_opt_int(data, "triage_score")
    _assert_opt_int(data, "requested_period_index")
    assert data["status"] in {s.value for s in QueryLetterStatus}


def assert_manuscript(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("agency_id", "")), "agency_id must be a UUID"
    assert is_valid_uuid(data.get("query_letter_id", "")), "query_letter_id must be a UUID"
    assert is_valid_uuid(data.get("author_id", "")), "author_id must be a UUID"
    _assert_opt_str(data, "reader_agent_id")
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["revision_round"], int)
    _assert_opt_int(data, "eval_score")
    assert data["status"] in {s.value for s in ManuscriptStatus}


def assert_client_agreement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("agency_id", "")), "agency_id must be a UUID"
    assert is_valid_uuid(data.get("author_id", "")), "author_id must be a UUID"
    assert is_valid_uuid(data.get("manuscript_id", "")), "manuscript_id must be a UUID"
    assert is_valid_uuid(data.get("agent_id", "")), "agent_id must be a UUID"
    assert data.get("commission_pct_override") is None or isinstance(
        data["commission_pct_override"], (int, float)
    )
    assert isinstance(data["exclusive"], bool)
    assert data["status"] in {s.value for s in ClientAgreementStatus}
    _assert_opt_int(data, "signed_period_index")


def assert_submission_round(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("agency_id", "")), "agency_id must be a UUID"
    assert is_valid_uuid(data.get("manuscript_id", "")), "manuscript_id must be a UUID"
    assert is_valid_uuid(data.get("agent_id", "")), "agent_id must be a UUID"
    assert isinstance(data["round_index"], int) and data["round_index"] >= 1
    assert isinstance(data["max_editors"], int) and data["max_editors"] >= 1
    assert isinstance(data["auction_mode"], bool)
    assert data["valuation_mode"] in {m.value for m in ValuationMode}
    assert data["status"] in {s.value for s in SubmissionRoundStatus}


def assert_submission(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("agency_id", "")), "agency_id must be a UUID"
    assert is_valid_uuid(data.get("submission_round_id", "")), "submission_round_id must be a UUID"
    assert is_valid_uuid(data.get("editor_id", "")), "editor_id must be a UUID"
    _assert_opt_int(data, "sent_period_index")
    _assert_opt_int(data, "response_period_index")
    assert data["status"] in {s.value for s in SubmissionStatus}


def assert_offer(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("agency_id", "")), "agency_id must be a UUID"
    assert is_valid_uuid(data.get("submission_id", "")), "submission_id must be a UUID"
    assert isinstance(data["advance_cents"], int) and data["advance_cents"] >= 0
    for f in ("royalty_pct_hardcover", "royalty_pct_trade", "royalty_pct_ebook"):
        assert isinstance(data[f], (int, float)), f"{f} must be a number"
    assert data["royalty_basis"] in {b.value for b in RoyaltyBasis}
    for f in ("includes_film_rights", "includes_foreign_rights", "includes_audio_rights"):
        assert isinstance(data[f], bool), f"{f} must be a boolean"
    _assert_opt_int(data, "auction_rank")
    assert data["status"] in {s.value for s in OfferStatus}


def assert_deal(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("agency_id", "")), "agency_id must be a UUID"
    assert is_valid_uuid(data.get("offer_id", "")), "offer_id must be a UUID"
    assert is_valid_uuid(data.get("submission_id", "")), "submission_id must be a UUID"
    assert is_valid_uuid(data.get("client_agreement_id", "")), "client_agreement_id must be a UUID"
    assert isinstance(data["advance_cents"], int) and data["advance_cents"] >= 0
    assert data["royalty_basis"] in {b.value for b in RoyaltyBasis}
    for f in ("retains_film_rights", "retains_foreign_rights", "retains_audio_rights"):
        assert isinstance(data[f], bool), f"{f} must be a boolean"
    assert isinstance(data["advance_earned_out_cents"], int) and data["advance_earned_out_cents"] >= 0
    _assert_opt_int(data, "executed_period_index")
    assert data["status"] in {s.value for s in DealStatus}


def assert_deal_invariants(data: dict):
    """Domain invariants that must hold for any deal."""
    assert_deal(data)
    assert data["advance_earned_out_cents"] <= data["advance_cents"], (
        "advance_earned_out_cents must never exceed advance_cents"
    )


def assert_royalty_statement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("agency_id", "")), "agency_id must be a UUID"
    assert is_valid_uuid(data.get("deal_id", "")), "deal_id must be a UUID"
    assert isinstance(data["period_index"], int)
    for f in ("units_hardcover", "units_trade", "units_ebook"):
        assert isinstance(data[f], int) and data[f] >= 0, f"{f} must be a non-negative int"
    for f in ("net_receipts_hardcover_cents", "net_receipts_trade_cents",
              "net_receipts_ebook_cents", "publisher_reported_royalty_cents"):
        assert isinstance(data[f], int) and data[f] >= 0, f"{f} must be a non-negative int"
    for f in ("gross_royalty_cents", "agency_commission_cents", "author_net_cents", "variance_cents"):
        _assert_opt_int(data, f)
    assert data["status"] in {s.value for s in RoyaltyStatementStatus}


def assert_advance_installment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("agency_id", "")), "agency_id must be a UUID"
    assert is_valid_uuid(data.get("deal_id", "")), "deal_id must be a UUID"
    assert data["milestone"] in {m.value for m in Milestone}
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0
    assert isinstance(data["due_period_index"], int)
    _assert_opt_int(data, "paid_period_index")
    _assert_opt_int(data, "agency_commission_cents")
    assert data["status"] in {s.value for s in AdvanceInstallmentStatus}
