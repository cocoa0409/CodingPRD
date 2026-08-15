"""In-memory data store.

Plain dicts keyed by id. The store starts empty on every boot; nothing is
seeded at startup. A fresh process (per-test-server isolation) therefore
carries zero state from any prior run.
"""

owners = {}
dormancy_rules = {}
properties = {}
contact_events = {}
letters = {}
reports = {}
line_items = {}
securities_details = {}
liquidation_orders = {}
remittances = {}
claims = {}
penalty_assessments = {}
audit_cases = {}
document_records = {}
