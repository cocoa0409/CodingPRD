"""List-read plumbing: conjunctive filters then the pagination window.

Filter values are never enum-validated (PRD 2.3): an unrecognised value simply
matches nothing. Every list is ordered created_at ascending unless a specific
endpoint says otherwise, and none does.
"""

from flask import jsonify, request

from common import envelope_array, envelope_object
from validate import parse_pagination


def apply_filters(rows, mapping):
    """`mapping` maps a query parameter name onto the row field it restricts."""
    args = request.args
    out = rows
    for param, field in mapping.items():
        if param not in args:
            continue
        wanted = args.get(param)
        out = [row for row in out if _matches(row.get(field), wanted)]
    return out


def _matches(value, wanted):
    if value is None:
        return False
    return str(value) == wanted


def list_response(rows, serializer, mapping=None):
    if mapping:
        rows = apply_filters(rows, mapping)
    limit, offset = parse_pagination(request.args)
    total = len(rows)
    window = rows[offset:offset + limit]
    body = envelope_array([serializer(row) for row in window], limit, offset, total)
    return jsonify(body), 200


def object_response(data, status=200):
    return jsonify(envelope_object(data)), status
