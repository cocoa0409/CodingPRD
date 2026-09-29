"""Liability periods, reserves and the net funded liability (PRD 3.10)."""
import clock
import db as dbm
from db import db
from services import cards as card_svc
from services.money import apply_bps

PERIOD_STATES = ("OPEN", "CLOSED", "RESTATED")
PROVISIONAL_BASIS = ("OPEN", "TRIAGED", "CONFIRMED")
FINAL_BASIS = ("CONFIRMED",)


def overlaps(period_start, period_end, ignore_id=None):
    """Half-open exclusive occupancy: candidate.start < existing.end AND
    existing.start < candidate.end. Both strict, so adjacency is legal.
    Periods in every state participate."""
    for existing in db.periods.values():
        if ignore_id is not None and existing["id"] == ignore_id:
            continue
        if period_start < existing["period_end"] and existing["period_start"] < period_end:
            return existing
    return None


def in_period_alerts(period, states=None):
    """created_at inside the half-open span [period_start, period_end)."""
    out = []
    for alert in db.alerts.values():
        if not (period["period_start"] <= alert["created_at"] < period["period_end"]):
            continue
        if states is not None and alert["state"] not in states:
            continue
        out.append(alert)
    return out


def funded_cards():
    """Cards whose activation_state is ACTIVE or DEPLETED."""
    out = []
    for card in db.cards.values():
        if card["activation_state"] in ("ACTIVE", "DEPLETED"):
            card_svc.recompute(card)
            out.append(card)
    return out


def outstanding_liability():
    return sum(c["current_balance_cents"] for c in funded_cards())


def reserve(gross_exposure_cents, rate_bps):
    """Rounded half up once over the aggregate, never per alert."""
    return apply_bps(gross_exposure_cents, rate_bps)


def write_basis(period, states, rate_bps, reserve_field):
    basis = in_period_alerts(period, states)
    gross = sum(a["exposure_cents"] for a in basis)
    period["gross_exposure_cents"] = gross
    period["reserve_basis_alert_count"] = len(basis)
    period[reserve_field] = reserve(gross, rate_bps)
    period["outstanding_liability_cents"] = outstanding_liability()
    return period


def open_period_containing_now():
    """The OPEN period whose half-open span contains the logical now."""
    now = clock.now()
    candidates = [
        p for p in db.periods.values()
        if p["state"] == "OPEN" and p["period_start"] <= now < p["period_end"]
    ]
    if not candidates:
        return None
    return dbm.by_created(candidates)[0]
