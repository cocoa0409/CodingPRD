"""In-memory data store.

All state lives in module-level dicts keyed by resource id. A fresh process
(start.sh re-invocation) starts with every collection empty — no seeding,
no disk persistence of any kind.
"""

# One dict per entity type; insertion order preserved for created_at ordering.
hospitals = {}
practitioners = {}
patient_cases = {}
antimicrobials = {}
allergy_assessments = {}
culture_reports = {}
susceptibility_results = {}
antibiotic_orders = {}
approval_requests = {}
audit_interventions = {}
conversion_opportunities = {}
antibiograms = {}
antibiogram_rows = {}
empiric_guidelines = {}
dot_snapshots = {}
regulatory_reports = {}

# Per-order administration event timestamps (list of aware datetimes).
# Internal only — never serialized directly.
administration_events = {}  # order_id -> [datetime, ...]
