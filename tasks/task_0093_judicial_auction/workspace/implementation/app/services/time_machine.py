"""Drive clock-gated automatic transitions."""
from __future__ import annotations

from ..clock import CLOCK, parse_iso
from ..errors import ApiError
from ..store import get_store


def advance_clock_to(to_iso: str) -> None:
    try:
        target = parse_iso(to_iso)
    except ValueError as exc:
        raise ApiError("ERR_VALIDATION", str(exc))
    CLOCK.set(target)
    _drive_transitions()


def _drive_transitions() -> None:
    from .auctions import close_auction_if_expired
    from .payments import sweep_overdue_payments

    store = get_store()
    # Close LIVE auctions whose effective_end_at has passed
    for auction in list(store.auctions.values()):
        close_auction_if_expired(auction)
    # Flip PENDING → OVERDUE on payments
    sweep_overdue_payments()
