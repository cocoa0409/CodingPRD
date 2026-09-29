"""The renewal calendar projection (PRD 3.9)."""
from datetime import date

import clock
from store import db, ordered
from services import permits, volume

DEFAULT_HORIZON_DAYS = 90
CALENDAR_STATUSES_SHOWN = ("OVERDUE", "FILED", "DUE")


def _month_start(year, month):
    return date(year, month, 1)


def report_window(rule, today):
    """The most recent COMPLETE reporting period the state's cadence implies."""
    if rule["reporting_frequency"] == "MONTHLY":
        this_month = _month_start(today.year, today.month)
        if today.month == 1:
            previous = _month_start(today.year - 1, 12)
        else:
            previous = _month_start(today.year, today.month - 1)
        return previous, this_month, date(today.year, today.month, 15)
    return (date(today.year - 1, 1, 1), date(today.year, 1, 1),
            date(today.year, 1, 31))


def report_filed(winery_id, state_code, period_type, start_raw, end_raw):
    for row in db.remittances.values():
        if row["winery_id"] != winery_id or row["state_code"] != state_code:
            continue
        if row["period_type"] != period_type:
            continue
        if row["status"] not in ("FILED", "REMITTED"):
            continue
        if clock.parse_date(row["period_start"]) != clock.parse_date(start_raw):
            continue
        if clock.parse_date(row["period_end"]) != clock.parse_date(end_raw):
            continue
        return True
    return False


def build(winery_id, horizon_days):
    today = clock.today()
    horizon_edge = clock.plus_days(today, horizon_days)
    # a permit observed past its expiration_date is driven ACTIVE -> EXPIRED first
    permits.observe_expiry_for(winery_id)

    expiring = []
    states_seen = []
    for permit in ordered(list(db.state_permits.values())):
        if permit["winery_id"] != winery_id:
            continue
        if permit["status"] not in permits.NON_REVOKED:
            continue
        rule = volume.state_rule_for(permit["state_code"])
        lead = rule["renewal_lead_days"] if rule is not None else 60
        expires = clock.parse_date(permit["expiration_date"])
        if expires is None:
            continue
        due = clock.plus_days(expires, -lead)
        if due < today and permit["status"] != "RENEWAL_FILED":
            status = "OVERDUE"
        elif permit["status"] == "RENEWAL_FILED":
            status = "FILED"
        elif due <= horizon_edge:
            status = "DUE"
        else:
            status = "SCHEDULED"
        if status not in CALENDAR_STATUSES_SHOWN:
            continue
        expiring.append({
            "permit_id": permit["id"],
            "state_code": permit["state_code"],
            "permit_number": permit["permit_number"],
            "permit_type": permit["permit_type"],
            "status": permit["status"],
            "expiration_date": permit["expiration_date"],
            "renewal_due_date": clock.date_iso(due),
            "renewal_lead_days": lead,
            "calendar_status": status,
            "_due": due,
        })
        if rule is not None and permit["state_code"] not in states_seen:
            states_seen.append(permit["state_code"])

    expiring.sort(key=lambda e: (e["_due"], e["state_code"]))
    reports = []
    for state_code in states_seen:
        rule = volume.state_rule_for(state_code)
        if rule is None:
            continue
        start, end, due_date = report_window(rule, today)
        start_raw = clock.date_iso(start)
        end_raw = clock.date_iso(end)
        reports.append({
            "state_code": state_code,
            "period_type": rule["reporting_frequency"],
            "report_period": {"period_start": start_raw, "period_end": end_raw},
            "period_start": start_raw,
            "period_end": end_raw,
            "report_due_date": clock.date_iso(due_date),
            "report_filed": report_filed(winery_id, state_code,
                                         rule["reporting_frequency"], start_raw, end_raw),
            "_due": due_date,
        })
    reports.sort(key=lambda r: (r["_due"], r["state_code"]))
    for entry in expiring:
        entry.pop("_due", None)
    for entry in reports:
        entry.pop("_due", None)
    return {
        "winery_id": winery_id,
        "as_of": clock.now_iso(),
        "horizon_days": horizon_days,
        "permits_expiring": expiring,
        "reports_due": reports,
    }
