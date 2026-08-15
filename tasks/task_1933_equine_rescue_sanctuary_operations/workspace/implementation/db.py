"""In-memory data store. Empty on every boot; no seeding, no persistence."""

# Primary stores, keyed by id (uuid4 hex strings).
horses = {}
evaluations = {}
protocols = {}
health_logs = {}
rehab_plans = {}
practitioners = {}
appointments = {}
stalls = {}
stall_assignments = {}
adopters = {}
applications = {}
home_checks = {}
follow_ups = {}
care_plans = {}
sponsors = {}
sponsorships = {}
feed_lots = {}
day_closes = {}
purchase_orders = {}
volunteers = {}
shifts = {}
euthanasia_cases = {}

# Dates already closed by the feed day-close checkpoint (date objects).
closed_dates = set()

# Monotonic insertion sequence, tie-breaks list ordering when created_at ties.
_seq = [0]


def next_seq():
    _seq[0] += 1
    return _seq[0]
