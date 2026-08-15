"""In-memory data store. Starts empty on every boot — no seeding."""

# Entity tables: dict keyed by id
program_cycles = {}
applications = {}
volunteers = {}
training_enrollments = {}
credit_entries = {}
recertification_records = {}
shifts = {}
shift_signups = {}
inquiries = {}
diagnosis_referrals = {}
specialists = {}
community_projects = {}
rotation_assignments = {}

# Logical clock state (ISO 8601 string, defaults to 2026-08-01T00:00:00Z)
clock_state = {"current_utc": "2026-08-01T00:00:00Z"}
