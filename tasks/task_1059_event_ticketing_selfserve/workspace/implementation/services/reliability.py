"""organizer_reliability_score (PRD §3.9)."""
from decimal import Decimal

import db
from services import constants as C
from services.money import round_half_up


def _event_score(event):
    gross = event["gross_cents"]
    refunds = event["refunds_cents"]
    issued = event["issued_count"]
    checked_in = event["checked_in_count"]

    refund_rate = Decimal(0) if gross == 0 else Decimal(refunds) / Decimal(gross)
    checkin_rate = Decimal(0) if issued == 0 else Decimal(checked_in) / Decimal(issued)
    cancel_flag = Decimal(1) if event["status"] == "CANCELLED" else Decimal(0)

    return Decimal(100) * (
        C.RELIABILITY_WEIGHT_REFUND * (Decimal(1) - refund_rate)
        + C.RELIABILITY_WEIGHT_CHECKIN * checkin_rate
        + C.RELIABILITY_WEIGHT_CANCEL * (Decimal(1) - cancel_flag)
    )


def qualifying_events(organizer_id):
    return [
        e
        for e in db.store.events.values()
        if e["organizer_id"] == organizer_id and e["status"] in ("COMPLETED", "CANCELLED")
    ]


def score(organizer_id, variant="LIFETIME"):
    events = qualifying_events(organizer_id)
    if variant == "TRAILING":
        events = sorted(
            events,
            key=lambda e: (e["ends_at"], e["created_at"], e["_seq"]),
            reverse=True,
        )[: C.RELIABILITY_TRAILING_EVENTS]

    if not events:
        return C.RELIABILITY_DEFAULT_SCORE, 0

    total = sum((_event_score(e) for e in events), Decimal(0))
    mean = total / Decimal(len(events))
    value = int(round_half_up(mean, 0))
    value = max(0, min(100, value))
    return value, len(events)
