"""Path resolution and the phase gate."""

import store
from errors import fail

_NOT_FOUND = {
    "elections": "ERR_ELECTION_NOT_FOUND",
    "contests": "ERR_CONTEST_NOT_FOUND",
    "candidates": "ERR_CANDIDATE_NOT_FOUND",
    "precincts": "ERR_PRECINCT_NOT_FOUND",
    "ballot_styles": "ERR_BALLOT_STYLE_NOT_FOUND",
    "print_vendors": "ERR_PRINT_VENDOR_NOT_FOUND",
    "print_jobs": "ERR_PRINT_JOB_NOT_FOUND",
    "ballot_lots": "ERR_BALLOT_LOT_NOT_FOUND",
    "tabulator_units": "ERR_TABULATOR_NOT_FOUND",
    "test_decks": "ERR_TEST_DECK_NOT_FOUND",
    "la_sessions": "ERR_LA_SESSION_NOT_FOUND",
}


def find(collection, row_id):
    row = store.get(collection, row_id)
    if row is None:
        fail(_NOT_FOUND[collection])
    return row


def election_of_contest(contest):
    return store.get("elections", contest["election_id"])


def contest_of_candidate(candidate):
    return store.get("contests", candidate["contest_id"])


def require_phase(election, allowed):
    if election["status"] not in allowed:
        fail("ERR_ELECTION_PHASE_INVALID",
             "Election phase %s does not permit this operation." % election["status"])


def state_error(error_id, status):
    fail(error_id, "State %s does not permit this operation." % status)
