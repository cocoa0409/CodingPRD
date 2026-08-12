"""Rate-card selection (PRD 3.3) -- chronological, by SERVICE date."""

from core.errors import ApiError
from core.store import db
from core.timeutil import parse_iso_date


def select_rate_card(service_date_iso, required=True):
    """Rank ACTIVE and SUPERSEDED cards effective on or before the service date.

    Ranked by ``effective_from`` descending, ties broken by ``created_at``
    descending; the first is selected.  A card whose ``effective_from`` equals
    the service date exactly IS eligible.  DRAFT cards are never candidates.
    """
    target = parse_iso_date(service_date_iso) if isinstance(service_date_iso, str) else service_date_iso
    if target is None:
        if required:
            raise ApiError("ERR_NO_EFFECTIVE_RATE_CARD")
        return None
    candidates = []
    for card in db.rate_cards.values():
        if card["status"] not in ("ACTIVE", "SUPERSEDED"):
            continue
        effective = parse_iso_date(card["effective_from"])
        if effective is None or effective > target:
            continue
        candidates.append((effective, card["created_at"], card["_seq"], card))
    if not candidates:
        if required:
            raise ApiError("ERR_NO_EFFECTIVE_RATE_CARD")
        return None
    candidates.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    return candidates[0][3]
