"""In-memory data store.

The store starts empty on every boot — no seeding is performed here or
anywhere else in the implementation. Tests construct all preconditions via
the declared API surface.
"""

import uuid


def new_id() -> str:
    return str(uuid.uuid4())


# --- entity stores keyed by id ---
campuses: dict = {}
volunteers: dict = {}
background_checks: dict = {}
training_modules: dict = {}
training_records: dict = {}
opportunities: dict = {}
placements: dict = {}
hour_entries: dict = {}
check_ins: dict = {}
incident_reports: dict = {}
recognition_awards: dict = {}
