"""In-memory data store. Dicts keyed by id; starts completely empty on boot.

No seeding, no persistence — the per-test-server harness restarts the process
before every test, so each boot is a fully fresh state.
"""

# Primary stores, keyed by id
hospital_units = {}
staff_members = {}
holiday_observances = {}
patient_cases = {}
classification_decisions = {}
case_assignments = {}
investigations = {}
investigation_notes = {}
response_letters = {}
recovery_actions = {}
escalations = {}
reportable_events = {}
rounding_sessions = {}
interview_rooms = {}
interview_bookings = {}
follow_ups = {}
clock_suspensions = {}
trend_snapshots = {}

# Creation-order sequence (stable sort key equal to created_at order even when
# the logical clock is not moved between creations)
_sequence = 0


def next_sequence():
    global _sequence
    _sequence += 1
    return _sequence
