"""In-memory data store (PRD §2.4).

State is wiped on every process boot. NOTHING is seeded here.
Every entity carries: id (uuid, no prefix), created_at, updated_at, version.
The Label resource is the single exception: only id + created_at.
"""
import threading
import uuid

import clock

# Per-entity dicts keyed by id.
customers = {}
service_levels = {}
grading_standards = {}
submissions = {}
submission_items = {}
intake_records = {}
grade_assessments = {}
authentication_checks = {}
slabs = {}
labels = {}
population_reports = {}
insurance_policies = {}
regrade_requests = {}
shipments = {}

# Monotonic certificate-number counter (server-minted, never reused).
_cert_counter = 0

# Global write lock for atomic multi-entity mutations.
lock = threading.RLock()


def new_id():
    return str(uuid.uuid4())


def next_cert_number():
    global _cert_counter
    _cert_counter += 1
    return "CERT{:010d}".format(_cert_counter)


def stamp_create(record):
    """Attach id/created_at/updated_at/version to a new record (common fields)."""
    ts = clock.now_iso()
    record.setdefault("id", new_id())
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1
    return record


def touch(record):
    """Mark a record mutated: bump version, refresh updated_at."""
    record["updated_at"] = clock.now_iso()
    record["version"] = record.get("version", 1) + 1
    return record
