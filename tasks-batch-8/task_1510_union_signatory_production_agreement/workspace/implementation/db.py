"""In-memory data store.

All state lives in module-level dicts keyed by id. The store starts empty on
every boot; nothing is seeded here. A single process-wide RLock guards every
mutation so concurrent requests cannot interleave multi-step cascades.
"""

import threading
from datetime import datetime, timezone

# Logical clock: startup default is exactly 2026-08-01T00:00:00Z and never
# falls back to wall-clock time.
_logical_clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

lock = threading.RLock()

companies = {}             # ProducerCompany
applications = {}          # SignatoryApplication
productions = {}           # Production
bonds = {}                 # Bond
crew_assignments = {}      # CrewAssignment
work_day_logs = {}         # WorkDayLog
grievances = {}            # Grievance
contribution_reports = {}  # ContributionReport
audits = {}                # Audit
force_majeure_events = {}  # ForceMajeureEvent


def get_clock():
    return _logical_clock


def set_clock(dt):
    global _logical_clock
    _logical_clock = dt
