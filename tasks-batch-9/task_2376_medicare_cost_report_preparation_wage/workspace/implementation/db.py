"""In-memory store. Nothing is ever persisted to disk and nothing is seeded."""

import itertools
import uuid
from datetime import datetime, timezone

TABLES = (
    "providers",
    "cost_reports",
    "cost_centers",
    "trial_balance_lines",
    "workpaper_entries",
    "stepdown_runs",
    "wage_index_submissions",
    "occ_mix_responses",
    "residents",
    "rotation_assignments",
    "ucc_data_sets",
    "settlements",
    "audit_adjustments",
    "appeal_cases",
    "interim_rate_requests",
)

DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def utcnow():
    return datetime.now(timezone.utc)


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


class Store:
    def __init__(self):
        for table in TABLES:
            setattr(self, table, {})
        self.clock = DEFAULT_CLOCK
        self._counter = itertools.count(1)

    def next_seq(self):
        return next(self._counter)

    def now(self):
        """The logical clock instant."""
        return self.clock


db = Store()


# ---------------------------------------------------------------- row helpers
def new_row(**fields):
    stamp = iso(utcnow())
    row = {
        "id": str(uuid.uuid4()),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "_seq": db.next_seq(),
    }
    row.update(fields)
    return row


def touch(row):
    row["updated_at"] = iso(utcnow())
    row["version"] = row["version"] + 1


def apply_changes(row, changes):
    """Write only the values that actually differ; bump the row when any did."""
    changed = False
    for key, value in changes.items():
        if key not in row or row[key] != value:
            row[key] = value
            changed = True
    if changed:
        touch(row)
    return changed


def ordered(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


# ---------------------------------------------------------------- traversals
def centers_of(report_id):
    return ordered([c for c in db.cost_centers.values() if c["cost_report_id"] == report_id])


def tb_lines_of(report_id):
    return ordered(
        [t for t in db.trial_balance_lines.values() if t["cost_report_id"] == report_id])


def entries_of(report_id):
    return ordered(
        [w for w in db.workpaper_entries.values() if w["cost_report_id"] == report_id])


def runs_of(report_id):
    return ordered([r for r in db.stepdown_runs.values() if r["cost_report_id"] == report_id])


def submissions_of(report_id):
    return ordered(
        [s for s in db.wage_index_submissions.values() if s["cost_report_id"] == report_id])


def occ_of(submission_id):
    return ordered(
        [o for o in db.occ_mix_responses.values()
         if o["wage_index_submission_id"] == submission_id])


def ucc_of(report_id):
    return ordered([u for u in db.ucc_data_sets.values() if u["cost_report_id"] == report_id])


def settlements_of(report_id):
    return ordered([s for s in db.settlements.values() if s["cost_report_id"] == report_id])


def adjustments_of(settlement_id):
    return ordered(
        [a for a in db.audit_adjustments.values() if a["settlement_id"] == settlement_id])


def residents_of(provider_id):
    return ordered([r for r in db.residents.values() if r["provider_id"] == provider_id])


def rotations_of_resident(resident_id):
    return ordered(
        [r for r in db.rotation_assignments.values() if r["resident_id"] == resident_id])


def reports_of(provider_id):
    return ordered([r for r in db.cost_reports.values() if r["provider_id"] == provider_id])


def interim_requests_of(provider_id):
    return ordered(
        [r for r in db.interim_rate_requests.values() if r["provider_id"] == provider_id])


def completed_run(report_id):
    for run in runs_of(report_id):
        if run["status"] == "COMPLETED":
            return run
    return None
