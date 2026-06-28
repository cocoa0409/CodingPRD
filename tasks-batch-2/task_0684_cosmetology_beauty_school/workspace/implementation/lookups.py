"""Existence resolution helpers (PRD 2.6).

Path-referenced resources -> ERR_NOT_FOUND (priority 3), validated left-to-right.
Body foreign keys -> ERR_FK_NOT_FOUND (priority 4).
"""
import db
import errors


def path(store, ident):
    """Resolve a path-referenced resource or raise ERR_NOT_FOUND."""
    row = store.get(ident)
    if row is None:
        raise errors.not_found()
    return row


def fk(store, ident):
    """Resolve a body foreign key or raise ERR_FK_NOT_FOUND."""
    row = store.get(ident)
    if row is None:
        raise errors.fk_not_found()
    return row
