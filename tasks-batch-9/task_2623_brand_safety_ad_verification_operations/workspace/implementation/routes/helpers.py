"""Shared route helpers."""

import db
import middleware
import response


def respond_list(records):
    limit, offset = middleware.pagination()
    window, total = response.paginate(list(records), limit, offset)
    return response.list_response(window, limit, offset, total)


def filtered(collection, predicates):
    """Conjunctive filtering over a collection, ordered by created_at ascending."""
    result = []
    for record in db.ordered(list(collection.values())):
        if all(predicate(record) for predicate in predicates):
            result.append(record)
    return result


def eq_filter(field, value):
    return lambda record: record.get(field) == value


def build_filters(spec):
    """spec: mapping (or pairs) of record field -> query-parameter name.  Only
    parameters actually supplied narrow the result, and they combine
    conjunctively (PRD section 2.4)."""
    pairs = spec.items() if isinstance(spec, dict) else spec
    predicates = []
    for field, param in pairs:
        raw = middleware.query(param)
        if raw is not None:
            predicates.append(eq_filter(field, raw))
    return predicates
