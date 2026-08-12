"""Shared list-endpoint plumbing (PRD 2.3)."""

import envelope
import lookup
from dispatch import page_params, query_filter
from store import ordered


def respond(rows, serializer, presorted=None):
    limit, offset = page_params()
    rows = presorted if presorted is not None else ordered(rows)
    page, total = envelope.paginate(rows, limit, offset)
    return envelope.list_response([serializer(r) for r in page], limit, offset, total)


def apply_filters(rows, spec):
    """spec: iterable of (query_param_name, row_field_name)."""
    for param, field in spec:
        value = query_filter(param)
        if value is None:
            continue
        rows = [r for r in rows if r.get(field) == value]
    return rows


def scope_to_client(context, rows, owner_of):
    """A ClientContact reads its own portfolio: estate-wide lists narrow to the
    acting client rather than raising, since those paths address no single
    resource for the cross-client rung to test."""
    if not context.is_client_contact:
        return rows
    return [r for r in rows if owner_of(r) == context.user_id]


def registration_owner(registration):
    return lookup.client_id_of_registration(registration)
