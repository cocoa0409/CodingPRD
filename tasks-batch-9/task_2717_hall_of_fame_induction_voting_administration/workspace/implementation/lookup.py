"""Path / body identifier resolution (PRD 2.6) and filter application.

Each resource family reports its own not-found code, and body identifiers are
resolved in the fixed order cycle, candidate, candidacy, elector, ballot family,
induction family, exhibit family, eligibility rule, voter bloc.
"""
from flask import request

import db
import payload
import response
from errors import fail


def _get(table, row_id, error_id, label):
    if row_id is None:
        return None
    row = table.get(row_id)
    if row is None:
        fail(error_id, "%s '%s' was not found." % (label, row_id))
    return row


def cycle(row_id):
    return _get(db.cycles, row_id, "ERR_CYCLE_NOT_FOUND", "Induction cycle")


def candidate(row_id):
    return _get(db.candidates, row_id, "ERR_CANDIDATE_NOT_FOUND", "Candidate")


def candidacy(row_id):
    return _get(db.candidacies, row_id, "ERR_CANDIDACY_NOT_FOUND", "Candidacy")


def elector(row_id):
    return _get(db.electors, row_id, "ERR_ELECTOR_NOT_FOUND", "Elector")


def ballot(row_id):
    return _get(db.ballots, row_id, "ERR_BALLOT_NOT_FOUND", "Ballot")


def ballot_slot(row_id):
    return _get(db.ballot_slots, row_id, "ERR_BALLOT_NOT_FOUND", "Ballot slot")


def vote_submission(row_id):
    return _get(db.vote_submissions, row_id, "ERR_BALLOT_NOT_FOUND", "Vote submission")


def induction(row_id):
    return _get(db.inductions, row_id, "ERR_INDUCTION_NOT_FOUND", "Induction")


def travel_grant(row_id):
    return _get(db.travel_grants, row_id, "ERR_INDUCTION_NOT_FOUND", "Travel grant")


def exhibit_case(row_id):
    return _get(db.exhibit_cases, row_id, "ERR_EXHIBIT_NOT_FOUND", "Exhibit case")


def exhibit_installation(row_id):
    return _get(db.exhibit_installations, row_id, "ERR_EXHIBIT_NOT_FOUND", "Exhibit installation")


def voter_bloc(row_id):
    return _get(db.voter_blocs, row_id, "ERR_BLOC_NOT_FOUND", "Voter bloc")


def eligibility_rule(row_id):
    return _get(db.eligibility_rules, row_id, "ERR_ELIGIBILITY_RULE_NOT_FOUND", "Eligibility rule")


# ------------------------------------------------------------------- filtering


def apply_filters(rows, specs):
    """specs is a sequence of (query_parameter, field, kind) triples.  Filter
    values are matched literally; a filter naming a non-existent parent simply
    matches nothing."""
    out = rows
    for qname, field, kind in specs:
        raw = request.args.get(qname)
        if raw is None or raw == "":
            continue
        if kind == "int":
            value = payload.query_int(qname)
        elif kind == "bool":
            value = payload.query_bool(qname)
        else:
            value = raw
        out = [row for row in out if row[field] == value]
    return out


def listing(table, specs, serializer):
    response.page_params()
    rows = apply_filters(list(table.values()), specs)
    return response.paginate(db.sort_rows(rows), serializer)
