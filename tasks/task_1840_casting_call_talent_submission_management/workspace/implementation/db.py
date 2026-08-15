"""In-memory data store. Starts empty on every boot; no seeding of any kind."""

# entity name -> {id: record(dict)}
STORE = {
    "productions": {},
    "roles": {},
    "breakdowns": {},
    "agents": {},
    "guardians": {},
    "talents": {},
    "submissions": {},
    "self_tapes": {},
    "sessions": {},
    "appointments": {},
    "holds": {},
    "offers": {},
    "deal_memos": {},
    "permits": {},
    "bookings": {},
    "taft_hartley_reports": {},
}

# Monotonic insertion counter used as a stable tiebreaker (created_at ties).
_seq = 0


def next_seq():
    global _seq
    _seq += 1
    return _seq
