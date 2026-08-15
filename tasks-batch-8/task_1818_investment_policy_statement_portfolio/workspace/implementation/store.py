"""In-memory data store. Starts completely empty on every boot —
no seeding, no preloading, no hardcoded entities."""

clients = {}
benchmarks = {}
ips_policies = {}
targets = {}          # AllocationTarget rows
portfolios = {}
securities = {}
positions = {}
events = {}           # CashFlowEvent ledger
restricted = {}       # RestrictedListEntry
proposals = {}
trades = {}
withdrawals = {}
reports = {}
amendments = {}
minutes = {}

_seq = [0]


def next_seq():
    """Monotonic insertion counter — stable tie-break for created_at ordering."""
    _seq[0] += 1
    return _seq[0]
