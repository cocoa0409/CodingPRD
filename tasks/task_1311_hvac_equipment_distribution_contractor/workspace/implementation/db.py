"""In-memory data store. Starts completely empty on every boot — no seeding."""

# Entity stores: dicts keyed by id (insertion-ordered for stable created_at ties).
contractors = {}
equipment_models = {}
ahri_ratings = {}
prebuy_programs = {}
orders = {}
order_lines = {}
allocation_pools = {}
warranty_registrations = {}
parts_claims = {}
refrigerant_cylinders = {}
refrigerant_events = {}
rebate_submissions = {}
training_courses = {}
training_credits = {}
coop_claims = {}

# Heel-shortfall violation records: list of {"contractor_id": ..., "recorded_at": datetime}
heel_violations = []
