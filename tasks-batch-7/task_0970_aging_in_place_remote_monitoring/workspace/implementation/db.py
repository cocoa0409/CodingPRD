"""In-memory data store. Starts empty on every boot; the logical clock starts
exactly at 2026-05-01T00:00:00Z and never falls back to wall-clock time."""
from datetime import datetime, timezone

seniors = {}
plans = {}
subscriptions = {}
kits = {}
devices = {}
events = {}
installers = {}
appointments = {}
caregivers = {}
contacts = {}
alerts = {}
notifications = {}
medication_schedules = {}
doses = {}
checkins = {}
reports = {}

clock = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)

_seq = [0]
_kit_seq = [0]


def next_seq():
    _seq[0] += 1
    return _seq[0]


def next_kit_seq():
    _kit_seq[0] += 1
    return _kit_seq[0]
