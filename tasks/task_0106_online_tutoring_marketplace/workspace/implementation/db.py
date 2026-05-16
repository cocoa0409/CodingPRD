"""In-memory data store."""

import uuid
from datetime import datetime, timezone

from clock import clock, format_iso


def new_id():
    return str(uuid.uuid4())


def now_iso_virtual():
    return clock.now_iso()


class DataStore:
    def __init__(self):
        self.tutors = {}  # id -> dict
        self.students = {}  # id -> dict
        self.parents = {}  # id -> dict
        self.credentials = {}  # id -> dict
        self.subject_tags = {}  # id -> dict
        self.sessions = {}  # id -> dict
        self.disputes = {}  # id -> dict
        self.parent_child_links = {}  # id -> dict
        self.payout_batches = {}  # id -> dict

        # Email uniqueness sets per type
        self.tutor_emails = set()
        self.student_emails = set()
        self.parent_emails = set()

    def reset(self):
        self.__init__()


def init_common_fields(record):
    """Set id/created_at/updated_at/version for a new record."""
    ts = now_iso_virtual()
    record.setdefault("id", new_id())
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1
    return record


def init_link_or_batch_fields(record):
    """ParentChildLink and PayoutBatch carry only id + created_at."""
    ts = now_iso_virtual()
    record.setdefault("id", new_id())
    record["created_at"] = ts
    return record


def touch(record):
    """Bump updated_at and version on a mutation."""
    record["updated_at"] = now_iso_virtual()
    record["version"] = record.get("version", 1) + 1
    return record


# Singleton
db = DataStore()
