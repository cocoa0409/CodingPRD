"""In-memory data store. Starts empty on every boot — no seeding."""

store = {
    "members": {},
    "references": {},
    "pets": {},
    "windows": {},
    "requests": {},
    "claims": {},
    "assignments": {},
    "handoffs": {},
    "entries": {},
    "incidents": {},
    "disputes": {},
    "ledger": {},
}

_seq = [0]


def next_seq():
    _seq[0] += 1
    return _seq[0]
