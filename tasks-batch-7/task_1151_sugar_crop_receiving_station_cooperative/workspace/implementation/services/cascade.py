"""Recompute helpers for derived aggregates (PRD §2.8) and shared cascades."""
from decimal import Decimal

import db
from services.calc import D, q4


def recompute_station(station_id):
    s = db.stations.get(station_id)
    if not s:
        return
    booked = Decimal("0")
    for b in db.bookings.values():
        if b["station_id"] == station_id and b["status"] == "CONFIRMED":
            booked += D(b["estimated_tons"])
    received = Decimal("0")
    for t in db.tickets.values():
        if t["station_id"] == station_id and t["status"] in ("ACCEPTED", "CREDITED"):
            received += D(t["adjusted_net_tons_final"] or 0)
    stored_lbs_total = Decimal("0")
    for p in db.piles.values():
        if p["station_id"] == station_id:
            stored_lbs_total += D(p["stored_lbs"] or 0)
    s["booked_tons"] = booked
    s["received_tons"] = q4(received)
    s["stored_tons"] = q4(stored_lbs_total / Decimal("2000"))


def recompute_pile_stored(pile_id):
    p = db.piles.get(pile_id)
    if not p:
        return
    total = Decimal("0")
    for a in db.pile_allocations.values():
        if a["pile_id"] == pile_id and a["status"] == "ACTIVE":
            total += D(a["remaining_lbs"])
    p["stored_lbs"] = total


def recompute_member_ledger(member_id):
    m = db.members.get(member_id)
    if not m:
        return
    total = 0
    for e in db.ledger_entries.values():
        if e["member_id"] == member_id:
            total += int(e["amount_cents"])
    m["net_ledger_cents"] = total


def recompute_member_loss(member_id):
    m = db.members.get(member_id)
    if not m:
        return
    # deterioration_loss_lbs = sum of loss allocated to this member across ALLOCATED loss events.
    # We track per-event contributions implicitly via allocation reductions; recompute from
    # allocation history is not directly possible, so this value is maintained incrementally
    # by loss-event allocate. This function exists for symmetry/future use.
    return m


def get_campaign_pool(campaign_id):
    for p in db.pools.values():
        if p["campaign_id"] == campaign_id:
            return p
    return None
