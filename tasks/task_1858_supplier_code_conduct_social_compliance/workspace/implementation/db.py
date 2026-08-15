"""In-memory data store. Fresh on every process boot."""

# Logical clock state. ISO-8601 UTC string; default 2026-08-01T00:00:00Z.
_clock_state = {
    "current_utc": "2026-08-01T00:00:00.000Z",
}


def get_clock():
    return _clock_state["current_utc"]


def set_clock(iso_str):
    _clock_state["current_utc"] = iso_str


# Entity stores, keyed by id
code_versions = {}
suppliers = {}
acknowledgments = {}
facilities = {}
auditors = {}
audits = {}
findings = {}
caps = {}
grievances = {}
worker_interview_records = {}
recruitment_fee_reviews = {}
reimbursements = {}
mutual_recognition_claims = {}
