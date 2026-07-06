"""Common-field helpers used by every mutable entity.

Per PRD §2.4, most entities carry id + created_at + updated_at + version.
WalletEntry and SubstitutionRule are append-only and carry only id + created_at.
"""
from util import gen_id, iso_now
import db


def new_common():
    """New common fields for a mutable entity."""
    t = iso_now(db.now())
    return {
        "id": gen_id(),
        "created_at": t,
        "updated_at": t,
        "version": 1,
    }


def new_common_appendonly():
    """New common fields for an append-only entity (WalletEntry / SubstitutionRule)."""
    return {
        "id": gen_id(),
        "created_at": iso_now(db.now()),
    }


def touch(entity):
    """Bump updated_at and version by one."""
    entity["updated_at"] = iso_now(db.now())
    entity["version"] = entity.get("version", 0) + 1
