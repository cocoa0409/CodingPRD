"""In-memory data store. Starts empty on every boot."""

# Each entity gets its own dict keyed by id (UUID string).
households = {}
members = {}
pledge_campaigns = {}
pledges = {}
donations = {}
year_end_statements = {}
events = {}
facilities = {}
facility_bookings = {}
volunteer_assignments = {}
small_groups = {}
group_memberships = {}
child_checkins = {}

# Logical clock — default at startup, before any /_clock/set_current_utc call.
DEFAULT_CLOCK_ISO = "2026-03-01T00:00:00.000Z"
_clock_iso = DEFAULT_CLOCK_ISO


def get_clock_iso():
    return _clock_iso


def set_clock_iso(v):
    global _clock_iso
    _clock_iso = v


def reset():
    """Reset the store to empty (used only for defensive purposes; boot already empty)."""
    global _clock_iso
    households.clear()
    members.clear()
    pledge_campaigns.clear()
    pledges.clear()
    donations.clear()
    year_end_statements.clear()
    events.clear()
    facilities.clear()
    facility_bookings.clear()
    volunteer_assignments.clear()
    small_groups.clear()
    group_memberships.clear()
    child_checkins.clear()
    _clock_iso = DEFAULT_CLOCK_ISO
