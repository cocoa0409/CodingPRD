"""In-memory data store. The store starts empty on every boot; no seeding."""
import uuid

DB = {
    "donor_sites": {},
    "agencies": {},
    "drivers": {},
    "windows": {},
    "coolers": {},
    "reservations": {},
    "offers": {},
    "runs": {},
    "temp_logs": {},
    "strikes": {},
    "receipts": {},
    "rate_cards": {},
}

# Server-wide mutable state: the logical clock (never falls back to wall
# clock), a monotonic creation sequence (created_at tie-break), and the
# monotonic rate-card version counter.
STATE = {
    "clock": "2026-08-01T00:00:00Z",
    "seq": 0,
    "next_card_version": 1,
}


def new_id():
    return str(uuid.uuid4())


def next_seq():
    STATE["seq"] += 1
    return STATE["seq"]
