"""Shared route helpers: existence lookups, OCC, filtering."""

from db import db, by_created_at
from errors import fail
from validators import present, v_int

# body FK field name -> (collection accessor, 404 error id)  (PRD 2.6)
FK_ERRORS = {
    "conference_id": ("conferences", "ERR_CONFERENCE_NOT_FOUND"),
    "category_id": ("categories", "ERR_CATEGORY_NOT_FOUND"),
    "submitting_author_id": ("authors", "ERR_AUTHOR_NOT_FOUND"),
    "author_id": ("authors", "ERR_AUTHOR_NOT_FOUND"),
    "requested_by_author_id": ("authors", "ERR_AUTHOR_NOT_FOUND"),
    "presenter_author_id": ("authors", "ERR_AUTHOR_NOT_FOUND"),
    "substitute_presenter_author_id": ("authors", "ERR_AUTHOR_NOT_FOUND"),
    "abstract_id": ("abstracts", "ERR_ABSTRACT_NOT_FOUND"),
    "member_id": ("members", "ERR_MEMBER_NOT_FOUND"),
    "reviewer_member_id": ("members", "ERR_MEMBER_NOT_FOUND"),
    "arbiter_member_id": ("members", "ERR_MEMBER_NOT_FOUND"),
    "chair_member_id": ("members", "ERR_MEMBER_NOT_FOUND"),
    "target_session_id": ("sessions", "ERR_SESSION_NOT_FOUND"),
    "session_id": ("sessions", "ERR_SESSION_NOT_FOUND"),
    "session_slot_id": ("slots", "ERR_SLOT_NOT_FOUND"),
    "accreditation_id": ("accreditations", "ERR_ACCREDITATION_NOT_FOUND"),
}


def lookup(collection_name, row_id, error_id):
    row = getattr(db, collection_name).get(row_id)
    if row is None:
        fail(error_id)
    return row


def resolve_fk(body, name, required=False):
    """Band 5: resolve a body foreign key, 404 on a dangling reference."""
    collection_name, error_id = FK_ERRORS[name]
    if not present(body, name):
        if required:
            return None
        return None
    value = body[name]
    if not isinstance(value, str):
        # Malformed types are left to the band-7 schema check.
        return None
    row = getattr(db, collection_name).get(value)
    if row is None:
        fail(error_id)
    return row


def check_occ(body, field, stored_version, error_id):
    """Band 8: non-optional OCC token compared against the stored version."""
    expected = v_int(body, field, required=True)
    if expected != stored_version:
        fail(error_id)
    return expected


def filtered(rows, filters):
    """Apply conjunctive equality filters; None filter values are ignored."""
    out = []
    for row in rows:
        keep = True
        for field, wanted in filters.items():
            if wanted is None:
                continue
            if row.get(field) != wanted:
                keep = False
                break
        if keep:
            out.append(row)
    return by_created_at(out)
