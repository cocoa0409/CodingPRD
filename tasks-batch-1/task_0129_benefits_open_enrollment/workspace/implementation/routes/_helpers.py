"""Cross-route lookup helpers (PRD §2.5 existence, left-to-right).

Existence (priority 3) is checked left-to-right: path identifiers first, then
body FKs. The first identifier that does not resolve yields ERR_NOT_FOUND before
any business rule is evaluated.
"""
from __future__ import annotations

import errors as E


def get_or_404(store: dict, _id, label: str) -> dict:
    ent = store.get(_id)
    if ent is None:
        raise E.not_found(f"{label} not found")
    return ent
