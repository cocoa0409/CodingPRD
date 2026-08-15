"""In-memory data store for the Industrial Hygiene Monitoring API.

Storage is plain Python dicts keyed by id. The store starts empty on every
boot; no seeding, no preloading, no on-disk persistence.
"""

# ---------------------------------------------------------------------------
# Logical clock (PRD section 2.5)
# ---------------------------------------------------------------------------
# Startup default: exactly 2026-08-01T00:00:00Z. The server never falls back
# to wall-clock time; only POST /ih/_clock/set_current_utc moves it.
current_utc_iso = "2026-08-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Entity tables (all keyed by entity id)
# ---------------------------------------------------------------------------
sites = {}
employees = {}
exposure_limits = {}
segs = {}
seg_memberships = {}
sampling_plans = {}
pumps = {}
pump_calibrations = {}
field_samples = {}
lab_batches = {}
lab_results = {}
assessments = {}
controls = {}
notifications = {}
medical_clearances = {}
fit_tests = {}

# Monotonic insertion sequence used as a stable tie-breaker when several rows
# share the same logical created_at timestamp.
_seq_counter = [0]


def next_seq():
    _seq_counter[0] += 1
    return _seq_counter[0]
