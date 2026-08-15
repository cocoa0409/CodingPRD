"""In-memory data store. Fresh on every boot — never seeded."""

# Entity collections, keyed by id.
rights_assets = {}
broadcasters = {}
packages = {}
bids = {}
deals = {}
payment_milestones = {}
production_obligations = {}
broadcast_events = {}
audience_measurements = {}
sublicense_requests = {}
blackout_windows = {}
renewal_offers = {}
rights_conflicts = {}
