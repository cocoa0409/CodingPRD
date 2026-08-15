"""In-memory data store. Empty at every boot — no seeding ever."""

# Entity stores: dicts keyed by id
events = {}
road_segments = {}
course_permits = {}
waves = {}
athletes = {}
registrations = {}
bike_checks = {}
aid_stations = {}
volunteer_assignments = {}
timing_records = {}
results = {}
penalties = {}
appeals = {}
safety_assessments = {}

# Logical clock state (ISO string). Startup default per PRD §2.5.
_logical_clock_iso = "2026-08-01T00:00:00Z"


def get_clock():
    return _logical_clock_iso


def set_clock(iso):
    global _logical_clock_iso
    _logical_clock_iso = iso
