"""Request payload builders.

Every builder returns a payload whose field names are exactly the ones the PRD
declares for that operation, filled with canonical valid values, and accepts
``**overrides`` so a test can perturb a single field. ``None`` is a legal
override value: passing ``field=None`` sends an explicit null, while popping a
key from the returned dict omits it entirely.
"""

from typing import Any, Dict, List, Optional

from .constants import (
    ASSET_TAG_1,
    BASIS_PRELIMINARY,
    CONTEST_TYPE_CANDIDATE,
    DISTRICT_D12,
    ELECTION_DATE,
    ELECTION_NAME,
    FIRMWARE_VERSION,
    FORMAT_PAPER_STANDARD,
    JURISDICTION,
    LANGUAGE_EN,
    LA_NOTICE_HOURS,
    LOT_CODE_1,
    ORDER_ALPHABETICAL,
    POLLING_PLACE_1,
    PRECINCT_CODE_1,
    PRESS_WINDOW_END,
    PRESS_WINDOW_START,
    ROTATION_NONE,
    SEAL_1,
    SESSION_END,
    SESSION_START,
    SESSION_TYPE_PUBLIC,
    STYLE_CODE_MAIN,
    UNIT_COST_CENTS_PER_THOUSAND,
    VENDOR_ACTIVE,
    VENDOR_NAME,
)


def _merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    base.update(overrides)
    return base


# ─── Election ────────────────────────────────────────────────────────────────

def election_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "name": ELECTION_NAME,
            "jurisdiction": JURISDICTION,
            "election_date": ELECTION_DATE,
            "rotation_policy": ROTATION_NONE,
            "candidate_order_method": ORDER_ALPHABETICAL,
            "la_notice_hours": LA_NOTICE_HOURS,
        },
        overrides,
    )


def reconcile_payload(basis: str, expected_election_version: int,
                      **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {"basis": basis, "expected_election_version": expected_election_version},
        overrides,
    )


def accountability_params(basis: Optional[str] = BASIS_PRELIMINARY) -> Dict[str, Any]:
    return {} if basis is None else {"basis": basis}


# ─── Contests and candidates ─────────────────────────────────────────────────

def contest_payload(title: str = "County Sheriff", **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "title": title,
            "contest_type": CONTEST_TYPE_CANDIDATE,
            "district_code": DISTRICT_D12,
            "seats_open": 1,
            "rotation_required": False,
        },
        overrides,
    )


def candidate_payload(full_name: str = "Ana Alvarez", ballot_name: str = "Alvarez",
                      filing_received_at: str = "2026-06-01T09:00:00Z",
                      party_code: str = "IND", **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "full_name": full_name,
            "ballot_name": ballot_name,
            "filing_received_at": filing_received_at,
            "party_code": party_code,
        },
        overrides,
    )


def withdraw_payload(reason: str = "Court order vacated the contest",
                     **overrides: Any) -> Dict[str, Any]:
    return _merge({"withdrawn_reason": reason}, overrides)


def disqualify_payload(reason: str = "Residency requirement not met",
                       **overrides: Any) -> Dict[str, Any]:
    return _merge({"disqualified_reason": reason}, overrides)


# ─── Precincts and styles ────────────────────────────────────────────────────

def precinct_payload(precinct_code: str = PRECINCT_CODE_1,
                     district_codes: Optional[List[str]] = None,
                     registered_voter_count: int = 100,
                     polling_place: str = POLLING_PLACE_1,
                     **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "precinct_code": precinct_code,
            "district_codes": list(district_codes) if district_codes else [DISTRICT_D12],
            "registered_voter_count": registered_voter_count,
            "polling_place": polling_place,
        },
        overrides,
    )


def ballot_style_payload(style_code: str = STYLE_CODE_MAIN,
                         district_codes: Optional[List[str]] = None,
                         language_set: Optional[List[str]] = None,
                         required_formats: Optional[List[str]] = None,
                         **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "style_code": style_code,
            "district_codes": list(district_codes) if district_codes else [DISTRICT_D12],
            "language_set": list(language_set) if language_set else [LANGUAGE_EN],
            "required_formats": (list(required_formats) if required_formats
                                 else [FORMAT_PAPER_STANDARD]),
        },
        overrides,
    )


def language_certification_payload(translated_languages: Optional[List[str]] = None,
                                   certified_formats: Optional[List[str]] = None,
                                   **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "translated_languages": (list(translated_languages)
                                     if translated_languages else [LANGUAGE_EN]),
            "certified_formats": (list(certified_formats)
                                  if certified_formats else [FORMAT_PAPER_STANDARD]),
        },
        overrides,
    )


def proof_decision_payload(decision: str = "APPROVE",
                           decision_note: str = "Artwork accepted",
                           **overrides: Any) -> Dict[str, Any]:
    return _merge({"decision": decision, "decision_note": decision_note}, overrides)


def assign_style_payload(style_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"style_id": style_id}, overrides)


def layout_params(basis: Optional[str] = None) -> Dict[str, Any]:
    return {} if basis is None else {"basis": basis}


# ─── Print vendors, print jobs, lots ─────────────────────────────────────────

def print_vendor_payload(name: str = VENDOR_NAME, press_line_count: int = 2,
                         certified_secure: bool = True,
                         status: str = VENDOR_ACTIVE, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "name": name,
            "press_line_count": press_line_count,
            "certified_secure": certified_secure,
            "status": status,
        },
        overrides,
    )


def print_job_payload(vendor_id: str, style_id: str, expected_ballot_style_version: int,
                      quantity_ordered: int = 12500,
                      unit_cost_cents_per_thousand: int = UNIT_COST_CENTS_PER_THOUSAND,
                      press_window_start: str = PRESS_WINDOW_START,
                      press_window_end: str = PRESS_WINDOW_END,
                      **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "vendor_id": vendor_id,
            "style_id": style_id,
            "quantity_ordered": quantity_ordered,
            "unit_cost_cents_per_thousand": unit_cost_cents_per_thousand,
            "press_window_start": press_window_start,
            "press_window_end": press_window_end,
            "expected_ballot_style_version": expected_ballot_style_version,
        },
        overrides,
    )


def inspect_payload(sample_size: int = 500, defect_count: int = 6,
                    **overrides: Any) -> Dict[str, Any]:
    return _merge({"sample_size": sample_size, "defect_count": defect_count}, overrides)


def manifest_line(lot_code: str = LOT_CODE_1, quantity_shipped: int = 12500,
                  seal_number: str = SEAL_1, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "lot_code": lot_code,
            "quantity_shipped": quantity_shipped,
            "seal_number": seal_number,
        },
        overrides,
    )


def deliver_payload(lots: Optional[List[Dict[str, Any]]] = None,
                    **overrides: Any) -> Dict[str, Any]:
    return _merge({"lots": list(lots) if lots is not None else [manifest_line()]}, overrides)


def receive_payload(seal_number: str = SEAL_1, quantity_received: int = 12500,
                    **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {"seal_number": seal_number, "quantity_received": quantity_received},
        overrides,
    )


def issue_payload(precinct_id: str, issue_quantity: int = 3000,
                  **overrides: Any) -> Dict[str, Any]:
    return _merge({"precinct_id": precinct_id, "issue_quantity": issue_quantity}, overrides)


def recall_payload(reason: str = "Precinct consolidated", **overrides: Any) -> Dict[str, Any]:
    return _merge({"recall_reason": reason}, overrides)


def return_counts_payload(voted_quantity: int = 2900, spoiled_quantity: int = 30,
                          returned_unused_quantity: int = 70,
                          **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "voted_quantity": voted_quantity,
            "spoiled_quantity": spoiled_quantity,
            "returned_unused_quantity": returned_unused_quantity,
        },
        overrides,
    )


# ─── Tabulators and seals ────────────────────────────────────────────────────

def tabulator_payload(asset_tag: str = ASSET_TAG_1,
                      firmware_version: str = FIRMWARE_VERSION,
                      **overrides: Any) -> Dict[str, Any]:
    return _merge({"asset_tag": asset_tag, "firmware_version": firmware_version}, overrides)


def program_payload(style_id: str, firmware_version: str = FIRMWARE_VERSION,
                    **overrides: Any) -> Dict[str, Any]:
    return _merge({"style_id": style_id, "firmware_version": firmware_version}, overrides)


def deploy_unit_payload(precinct_id: str, seal_number: str,
                        **overrides: Any) -> Dict[str, Any]:
    return _merge({"precinct_id": precinct_id, "seal_number": seal_number}, overrides)


def break_seal_payload(reason: str = "Paper jam service call",
                       **overrides: Any) -> Dict[str, Any]:
    return _merge({"reason": reason}, overrides)


def seal_retention_payload(seal_number: str, retention_days: int = 22,
                           **overrides: Any) -> Dict[str, Any]:
    return _merge({"seal_number": seal_number, "retention_days": retention_days}, overrides)


# ─── Test decks and logic-and-accuracy sessions ──────────────────────────────

def expected_mark(contest_id: str, candidate_id: Optional[str],
                  mark_count: int = 1, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {"contest_id": contest_id, "candidate_id": candidate_id, "mark_count": mark_count},
        overrides,
    )


def test_deck_payload(expected_marks: List[Dict[str, Any]], deck_code: str = "DECK-A",
                      ballot_count: int = 2, blank_count: int = 1,
                      overvote_count: int = 0, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "deck_code": deck_code,
            "ballot_count": ballot_count,
            "blank_count": blank_count,
            "overvote_count": overvote_count,
            "expected_marks": list(expected_marks),
        },
        overrides,
    )


def la_session_payload(tabulator_id: str, deck_id: str,
                       scheduled_start: str = SESSION_START,
                       scheduled_end: str = SESSION_END,
                       public_notice_posted_at: str = "2026-08-01T00:00:00Z",
                       session_type: str = SESSION_TYPE_PUBLIC,
                       **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "tabulator_id": tabulator_id,
            "deck_id": deck_id,
            "session_type": session_type,
            "scheduled_start": scheduled_start,
            "scheduled_end": scheduled_end,
            "public_notice_posted_at": public_notice_posted_at,
        },
        overrides,
    )


def observer_payload(observer_name: str = "Iris Nolan", **overrides: Any) -> Dict[str, Any]:
    return _merge({"observer_name": observer_name}, overrides)


def reported_mark(contest_id: str, candidate_id: Optional[str],
                  mark_count: int = 1, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {"contest_id": contest_id, "candidate_id": candidate_id, "mark_count": mark_count},
        overrides,
    )


def record_results_payload(reported_marks: List[Dict[str, Any]],
                           reported_blank_count: int = 1,
                           reported_overvote_count: int = 0,
                           **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "reported_marks": list(reported_marks),
            "reported_blank_count": reported_blank_count,
            "reported_overvote_count": reported_overvote_count,
        },
        overrides,
    )
