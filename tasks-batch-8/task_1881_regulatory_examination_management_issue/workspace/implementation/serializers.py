"""Entity -> public JSON serializers. Datetimes render with 3 fractional
digits; first_day_letter_due_date renders date-granularity (PRD §2.6)."""
from util import fmt_dt

FULL_TS = {"created_at", "updated_at"}


def _ser(rec, dt_fields=(), date_fields=()):
    out = {}
    dts = set(dt_fields) | FULL_TS
    for k, v in rec.items():
        if k.startswith("_"):
            continue
        if v is None:
            out[k] = None
        elif k in date_fields:
            out[k] = v.strftime("%Y-%m-%d")
        elif k in dts:
            out[k] = fmt_dt(v)
        else:
            out[k] = v
    return out


def ser_agency(r):
    return _ser(r)


def ser_officer(r):
    return _ser(r)


def ser_reviewer(r):
    return _ser(r)


def ser_exam(r):
    return _ser(
        r,
        dt_fields={"scheduled_start_date", "scheduled_end_date"},
        date_fields={"first_day_letter_due_date"},
    )


def ser_item(r):
    return _ser(r, dt_fields={"due_date", "submitted_at"})


def ser_submission(r):
    return _ser(r)


def ser_meeting(r):
    return _ser(r, dt_fields={"meeting_date"})


def ser_finding(r):
    return _ser(r)


def ser_issue(r):
    return _ser(r, dt_fields={"due_date", "closed_at"})


def ser_plan(r):
    return _ser(r, dt_fields={"submitted_at", "approved_at"})


def ser_milestone(r):
    return _ser(r, dt_fields={"due_date", "completed_at"})


def ser_evidence(r):
    return _ser(r)


def ser_closure(r):
    return _ser(r)


def ser_report(r):
    return _ser(r, dt_fields={"reporting_period_start", "reporting_period_end"})


def ser_commitment(r):
    # CommitmentLogEntry is append-only: id + created_at, no updated_at/version.
    return _ser(r, dt_fields={"committed_at", "due_date", "fulfilled_at"})
