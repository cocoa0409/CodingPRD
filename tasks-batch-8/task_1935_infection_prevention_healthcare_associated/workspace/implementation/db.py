"""In-memory data store. Starts EMPTY on every boot — no seeding whatsoever."""

# Entity stores, keyed by id.
facilities = {}
units = {}
patients = {}
employees = {}
device_episodes = {}
surgical_procedures = {}
infection_cases = {}
device_day_counts = {}
monthly_summaries = {}
outbreak_investigations = {}
isolation_orders = {}
isolation_compliance_audits = {}
hand_hygiene_observations = {}
employee_exposures = {}
corrective_action_plans = {}
