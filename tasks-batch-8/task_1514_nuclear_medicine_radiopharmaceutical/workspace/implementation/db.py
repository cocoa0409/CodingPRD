"""In-memory data store for the Nuclear Medicine & Radiopharmaceutical Management API.

Storage is plain Python dicts keyed by id. The store starts empty on every boot;
no seeding, no preloading, no on-disk persistence.
"""

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
# Before any call, the clock reads exactly 2026-08-01T00:00:00Z (PRD §2.4).
current_utc_iso = "2026-08-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Entity tables (all keyed by entity id)
# ---------------------------------------------------------------------------
isotope_products = {}
licenses = {}
authorized_users = {}
patients = {}
imaging_rooms = {}
isotope_deliveries = {}
dose_orders = {}
dose_vials = {}
dose_administrations = {}
procedure_appointments = {}
waste_containers = {}
radiation_surveys = {}
spill_incidents = {}
patient_release_instructions = {}
