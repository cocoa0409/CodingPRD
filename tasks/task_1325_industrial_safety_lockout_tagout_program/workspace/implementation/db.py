"""In-memory data store. The store starts empty on every boot; no seeding.

Every entity any caller needs is constructed through the declared API surface.
"""

import itertools

DB = {
    "machines": {},
    "modifications": {},
    "employees": {},
    "energy_surveys": {},
    "lockout_procedures": {},
    "training_records": {},
    "lockout_sessions": {},
    "employee_locks": {},
    "procedure_audits": {},
    "incident_reports": {},
    "contractor_permits": {},
    "minor_servicing_exceptions": {},
}

_seq = itertools.count(1)


def next_seq():
    """Monotonic insertion sequence for stable created_at tie-breaking."""
    return next(_seq)
