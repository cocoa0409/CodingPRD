"""Form 3922 service: lookup and per-participant year list."""
from __future__ import annotations

from typing import Optional

from core.errors import err_not_found
from core.store import store
from core.utils import parse_iso


def get_form_or_404(form_id: str) -> dict:
    f = store.form_3922s.get(form_id)
    if f is None:
        raise err_not_found(f"Form3922 {form_id} not found.")
    return f


def list_forms_for_participant(
    participant_id: str, *, calendar_year: int
) -> list:
    items = []
    for f in store.form_3922s.values():
        if f["participant_id"] != participant_id:
            continue
        try:
            yr = parse_iso(f["purchase_date"]).year
        except Exception:
            continue
        if yr == calendar_year:
            items.append(f)
    items.sort(key=lambda f: f["created_at"])
    return items
