"""In-memory data store. Module-level dicts; populated fresh on every boot."""

# entity stores keyed by id
seasons = {}
sugarbushes = {}
leases = {}
tap_lines = {}
vacuum_readings = {}          # id -> reading; also kept per-line order via list index
weather_windows = {}
crew_members = {}
sap_runs = {}
batches = {}
batch_intakes = {}
syrup_lots = {}
flavor_evaluations = {}
packaging_runs = {}
cert_audits = {}

# logical clock: ISO8601 string with 'Z'. Default per PRD §2.4.
LOGICAL_CLOCK_DEFAULT = "2026-05-01T00:00:00Z"
clock_iso = LOGICAL_CLOCK_DEFAULT
