"""Clock-driven system sweeps (PRD 2.6, 3.4, 3.7)."""
from db import db
from services.core import touch
from util import parse_datetime


def discovery_overdue_sweep(now):
    """ISSUED with response_due_at strictly before the new clock -> OVERDUE;
    RESPOND_REQUIRED with extended_due_at strictly before -> OVERDUE.
    Equal-to-due is NOT overdue. Each flip increments the case counter."""
    rows = sorted(
        db["data_requests"].values(),
        key=lambda r: (r["created_at"], r["_seq"]),
    )
    for dr in rows:
        flipped = False
        if dr["status"] == "ISSUED" and parse_datetime(dr["response_due_at"]) < now:
            flipped = True
        elif (
            dr["status"] == "RESPOND_REQUIRED"
            and dr.get("extended_due_at") is not None
            and parse_datetime(dr["extended_due_at"]) < now
        ):
            flipped = True
        if flipped:
            dr["status"] = "OVERDUE"
            touch(dr)
            case = db["rate_cases"].get(dr["rate_case_id"])
            if case is not None:
                case["overdue_data_request_count"] += 1
                touch(case)


def tariff_supersede_sweep(now):
    """Per class, the current EFFECTIVE tariff is the one with the latest
    effective_start <= new clock; every other EFFECTIVE tariff of the class
    with a strictly earlier effective_start -> SUPERSEDED. Window expiry alone
    never supersedes."""
    by_class = {}
    for t in db["tariff_rates"].values():
        if t["status"] == "EFFECTIVE":
            by_class.setdefault(t["customer_class_id"], []).append(t)
    for _cid, tariffs in by_class.items():
        eligible = [t for t in tariffs if parse_datetime(t["effective_start"]) <= now]
        if not eligible:
            continue
        latest_start = max(parse_datetime(t["effective_start"]) for t in eligible)
        for t in tariffs:
            if parse_datetime(t["effective_start"]) < latest_start:
                t["status"] = "SUPERSEDED"
                touch(t)


def run_sweeps(now):
    discovery_overdue_sweep(now)
    tariff_supersede_sweep(now)
