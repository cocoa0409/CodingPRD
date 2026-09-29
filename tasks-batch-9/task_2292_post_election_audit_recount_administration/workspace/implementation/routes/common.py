"""Shared route helpers."""

from db import db, serialize, sorted_rows
from errors import fail
from response import list_response, object_response
from validate import filter_value, pagination

NOT_FOUND_ERRORS = {
    "elections": "ERR_ELECTION_NOT_FOUND",
    "contests": "ERR_CONTEST_NOT_FOUND",
    "ballot_batches": "ERR_BALLOT_BATCH_NOT_FOUND",
    "custody_events": "ERR_CUSTODY_EVENT_NOT_FOUND",
    "audits": "ERR_AUDIT_NOT_FOUND",
    "audit_rounds": "ERR_AUDIT_ROUND_NOT_FOUND",
    "audit_batches": "ERR_AUDIT_BATCH_NOT_FOUND",
    "tally_teams": "ERR_TALLY_TEAM_NOT_FOUND",
    "manual_tallies": "ERR_MANUAL_TALLY_NOT_FOUND",
    "discrepancies": "ERR_DISCREPANCY_NOT_FOUND",
    "ballot_interpretations": "ERR_BALLOT_INTERPRETATION_NOT_FOUND",
    "recounts": "ERR_RECOUNT_NOT_FOUND",
    "corrective_actions": "ERR_CORRECTIVE_ACTION_NOT_FOUND",
    "observer_credentials": "ERR_OBSERVER_CREDENTIAL_NOT_FOUND",
}


def lookup(collection, row_id, error_id=None):
    row = getattr(db, collection).get(row_id)
    if row is None:
        fail(error_id or NOT_FOUND_ERRORS[collection])
    return row


def single(row, status=200):
    return object_response(serialize(row), status)


def paged(rows, limit, offset, sort_keys=("created_at",)):
    ordered = sorted_rows(rows, sort_keys)
    total = len(ordered)
    window = ordered[offset: offset + limit]
    return list_response([serialize(r) for r in window], limit, offset, total)


def collect_filters(spec):
    """spec: {query_param: (row_field, choices|None)}"""
    active = {}
    for param, config in spec.items():
        field, choices = config
        value = filter_value(param, choices)
        if value is not None:
            active[field] = value
    return active


def _matches(row_value, wanted):
    if isinstance(row_value, bool):
        return str(row_value).lower() == wanted.lower()
    if row_value is None:
        return wanted == "null"
    return str(row_value) == wanted


def apply_filters(rows, active):
    out = []
    for row in rows:
        keep = True
        for field, value in active.items():
            if not _matches(row.get(field), value):
                keep = False
                break
        if keep:
            out.append(row)
    return out


def list_endpoint(collection, spec, sort_keys=("created_at",), base=None):
    limit, offset = pagination()
    active = collect_filters(spec)
    rows = base if base is not None else list(getattr(db, collection).values())
    rows = apply_filters(rows, active)
    return paged(rows, limit, offset, sort_keys)
