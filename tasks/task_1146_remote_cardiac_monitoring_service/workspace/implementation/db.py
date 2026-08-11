"""In-memory store. Starts empty on every boot -- no seeding."""
import uuid

from clock import now

patients = {}
physicians = {}
technicians = {}
devices = {}
orders = {}
enrollments = {}
episodes = {}
suspension_intervals = {}
transmissions = {}
alerts = {}
attempts = {}
reports = {}
billing_periods = {}
shipments = {}
compliance_events = {}


def new_id():
    return str(uuid.uuid4())


def base_record():
    t = now()
    return {"id": new_id(), "created_at": t, "updated_at": t, "version": 1}


def touch(rec):
    rec["updated_at"] = now()
    rec["version"] += 1
