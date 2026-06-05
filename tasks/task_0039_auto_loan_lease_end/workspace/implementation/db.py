import uuid

# In-memory data store. Starts empty on every boot. No seeding.
customers = {}
vehicles = {}
rate_cards = {}
loans = {}
leases = {}
payments = {}
settlements = {}

# Monotonic sequence to provide a stable creation order tiebreaker for sorting
# (created_at timestamps can collide at millisecond resolution).
_seq = 0


def next_seq():
    global _seq
    _seq += 1
    return _seq


def new_id():
    return str(uuid.uuid4())
