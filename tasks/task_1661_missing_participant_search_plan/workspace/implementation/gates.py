"""Shared front gates for the two disposition endpoints (POST /pbgc-transfers
and POST /forfeitures), evaluated in the PRD section 2.9 order.

Note on ordering: PRD section 2.9 puts the distribution_status from-state
gate (priority 6) ahead of structural checks (priority 9). For forfeitures,
the pinned corner case duplicate_open_records_return_already_open_errors
requires a second forfeiture on an already-FORFEITED participant to report
ERR_FORFEITURE_ALREADY_RECORDED, so the forfeiture route runs its
singularity check before the distribution-state gate; the transfer route
(whose creation never changes distribution_status) keeps the strict
section 2.9 order."""

import db
from errors import (
    ApiError,
    ERR_CASE_INVALID_STATE,
    ERR_ELECTION_INVALID_STATE,
    ERR_FIDUCIARY_DOC_MISSING,
    ERR_PARTICIPANT_NOT_MISSING,
    ERR_SEARCH_PROTOCOL_INCOMPLETE,
    ERR_SEGREGATION_OF_DUTIES_VIOLATION,
)

DISPOSITION_CASE_STATUSES = {"DISTRIBUTION_IN_PROGRESS", "FINAL_RECONCILIATION"}


def case_and_missing_gates(participant):
    """Priority 6: case-status and locate-status gates. Returns (case,
    search_case)."""
    case = db.get("cases", participant["termination_case_id"])
    if case["status"] not in DISPOSITION_CASE_STATUSES:
        raise ApiError(
            ERR_CASE_INVALID_STATE, 409,
            "dispositions require case status DISTRIBUTION_IN_PROGRESS or "
            "FINAL_RECONCILIATION",
        )
    if participant["locate_status"] != "MISSING":
        raise ApiError(
            ERR_PARTICIPANT_NOT_MISSING, 409,
            "dispositions require a MISSING participant",
        )
    search_case = (
        db.get("search_cases", participant["active_search_case_id"])
        if participant["active_search_case_id"]
        else None
    )
    return case, search_case


def distribution_gate(participant):
    """Priority 6: distribution_status must be PENDING_ELECTION."""
    if participant["distribution_status"] != "PENDING_ELECTION":
        raise ApiError(
            ERR_ELECTION_INVALID_STATE, 409,
            "dispositions require distribution_status PENDING_ELECTION",
        )


def sod_and_doc_gates(search_case, user_id):
    """Priority 7 (segregation of duties) then priority 8 (fiduciary
    documentation)."""
    if (
        search_case is not None
        and search_case["exhausted_by_user_id"] is not None
        and search_case["exhausted_by_user_id"] == user_id
    ):
        raise ApiError(
            ERR_SEGREGATION_OF_DUTIES_VIOLATION, 403,
            "the operator who exhausted the search may not approve the "
            "disposition",
        )
    if search_case is None or not any(
        e["entry_type"] == "SEARCH_PROTOCOL_SUMMARY"
        and e["related_entity_id"] == search_case["id"]
        for e in db.all_of("logs")
    ):
        raise ApiError(
            ERR_FIDUCIARY_DOC_MISSING, 422,
            "a SEARCH_PROTOCOL_SUMMARY fiduciary log entry referencing the "
            "search case is required",
        )


def require_exhausted(search_case):
    """Priority 11: the participant's active search case must be EXHAUSTED."""
    if search_case is None or search_case["status"] != "EXHAUSTED":
        raise ApiError(
            ERR_SEARCH_PROTOCOL_INCOMPLETE, 409,
            "the search protocol must be exhausted first",
        )
