"""In-memory data store. Dicts keyed by id; starts completely empty on boot.

No seeding, no persistence — the per-test-server harness restarts the process
before every test, so each boot is a fully fresh state.
"""

# Primary stores, keyed by id
card_accounts = {}
card_transactions = {}
dispute_cases = {}
provisional_credits = {}
chargebacks = {}
representments = {}
notifications = {}
loss_recoveries = {}

# Creation-order sequence per store (stable sort key equal to created_at order
# even when the logical clock is not moved between creations)
_sequence = 0


def next_sequence():
    global _sequence
    _sequence += 1
    return _sequence
