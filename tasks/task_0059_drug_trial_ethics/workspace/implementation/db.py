from __future__ import annotations

"""In-memory data store keyed by id.

Each entity stored as a dict. The DB exposes the per-resource collections plus
helpers for id generation and a process-wide lock used to serialize mutating
operations (sufficient for in-memory test workloads).
"""

import uuid
from threading import RLock


lock = RLock()


# Primary tables, keyed by id
applications: dict[str, dict] = {}
submissions: dict[str, dict] = {}
committee_members: dict[str, dict] = {}
conflict_declarations: dict[str, dict] = {}
meetings: dict[str, dict] = {}
agenda_items: dict[str, dict] = {}
attendance_confirmations: dict[str, dict] = {}
votes: dict[str, dict] = {}
resolutions: dict[str, dict] = {}
rectifications: dict[str, dict] = {}
annual_reports: dict[str, dict] = {}
audit_logs: dict[str, dict] = {}


def new_id() -> str:
    return str(uuid.uuid4())


def reset_all() -> None:
    with lock:
        for d in (applications, submissions, committee_members, conflict_declarations,
                  meetings, agenda_items, attendance_confirmations, votes, resolutions,
                  rectifications, annual_reports, audit_logs):
            d.clear()
