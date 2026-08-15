"""In-memory data store. Fresh, empty state on every process boot."""

# Entity stores keyed by id
windows = {}
teachers = {}
families = {}
students = {}
links = {}
slots = {}
bookings = {}
interpreters = {}
interpreter_requests = {}
waitlist_entries = {}
attendance_records = {}
outreach_tasks = {}

# Server-held logical clock (ISO string). Never falls back to wall clock.
logical_clock = "2026-08-01T00:00:00Z"

# Global monotonic creation sequence (used for created_seq tie-breaks)
global_seq = 0


def next_seq():
    global global_seq
    global_seq += 1
    return global_seq
