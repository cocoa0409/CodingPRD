"""In-memory data store. The store starts empty on every boot — no seeding."""

# Entity tables: id -> dict
facilities = {}
products = {}
usage_records = {}
forecast_profiles = {}
technicians = {}
dispensers = {}
training_records = {}
standing_orders = {}
orders = {}
order_lines = {}
contract_bids = {}
substitution_proposals = {}
trial_programs = {}

# Logical clock (milliseconds-since-epoch-free; stored as a datetime in app.clock)
# Kept in clock.py to avoid circular imports.
