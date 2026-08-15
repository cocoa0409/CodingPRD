"""In-memory data store. All state lives in module-level dicts.

The store starts empty on every boot — no seeding of any kind. Every entity
is constructed via the declared API surface.
"""

# Each dict maps entity id -> entity dict (plain JSON-serializable records).
union_agreements = {}
productions = {}
performers = {}
engagements = {}
timecards = {}
penalty_assessments = {}
residual_obligations = {}
pay_batches = {}
pay_lines = {}
garnishment_orders = {}
remittance_reports = {}
grievance_cases = {}

# Pending garnishment allocations recorded at batch close, applied to
# GarnishmentOrder.total_withheld_cents at disburse. Keyed by order id.
pending_garnishment_allocations = {}
