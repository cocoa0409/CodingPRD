"""CDRReview: list, schedule, complete; emits the cessation cascade."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional

from app import clock, store
from app.calculations import (
    CDR_SCHEDULE_LOOKBACK_DAYS,
    MIE_DIARY_MONTHS,
    MIP_DIARY_MONTHS,
    MINE_DIARY_MONTHS,
)
from app.errors import (
    bad_request,
    cdr_not_due,
    invalid_state,
    resource_not_found,
)
from app.util import add_months, new_uuid, parse_iso_date


def list_cdr_reviews(status: Optional[str], due_before: Optional[str]) -> list[dict]:
    rows = list(store.cdr_reviews.values())
    if status is not None:
        if status not in ("PENDING", "SCHEDULED", "COMPLETED"):
            raise bad_request("status must be PENDING|SCHEDULED|COMPLETED")
        rows = [r for r in rows if r["status"] == status]
    if due_before is not None:
        ddate = parse_iso_date(due_before, "due_before")
        rows = [r for r in rows if _to_date(r["review_due_date"]) <= ddate]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    return rows


def _to_date(value) -> date:
    if isinstance(value, datetime):
        return value.date()
    return value


def _fetch(review_id: str) -> dict:
    r = store.cdr_reviews.get(review_id)
    if not r:
        raise resource_not_found(f"CDRReview {review_id} not found")
    return r


def schedule_review(review_id: str) -> dict:
    with store.lock():
        r = _fetch(review_id)
        if r["status"] != "PENDING":
            raise invalid_state(f"CDRReview in status {r['status']} cannot be scheduled")
        now = clock.now()
        review_due = r["review_due_date"]
        if isinstance(review_due, date) and not isinstance(review_due, datetime):
            # Build a midnight UTC datetime for the comparison.
            from datetime import timezone
            review_due_dt = datetime(review_due.year, review_due.month, review_due.day, tzinfo=timezone.utc)
        else:
            review_due_dt = review_due
        # Allowed if now >= review_due - 60 days
        threshold = review_due_dt - timedelta(days=CDR_SCHEDULE_LOOKBACK_DAYS)
        if now < threshold:
            raise cdr_not_due("CDR cannot be scheduled before review_due_date - 60 days")
        r["status"] = "SCHEDULED"
        r["scheduled_at"] = now
        r["updated_at"] = now
        r["version"] += 1
    return r


def complete_review(review_id: str, body: dict) -> dict:
    if "medical_improvement_found" not in body or body["medical_improvement_found"] is None:
        raise bad_request("medical_improvement_found is required")
    if "working_at_sga" not in body or body["working_at_sga"] is None:
        raise bad_request("working_at_sga is required")
    mi = body["medical_improvement_found"]
    sga = body["working_at_sga"]
    if not isinstance(mi, bool):
        raise bad_request("medical_improvement_found must be a boolean")
    if not isinstance(sga, bool):
        raise bad_request("working_at_sga must be a boolean")

    with store.lock():
        r = _fetch(review_id)
        if r["status"] != "SCHEDULED":
            raise invalid_state(f"CDRReview in status {r['status']} cannot be completed")

        now = clock.now()
        outcome = "CEASE" if (mi or sga) else "CONTINUE"
        r["medical_improvement_found"] = mi
        r["working_at_sga"] = sga
        r["outcome"] = outcome
        r["completed_at"] = now
        r["status"] = "COMPLETED"
        r["updated_at"] = now
        r["version"] += 1

        if outcome == "CEASE":
            # Cascade into Application APPROVED -> CLOSED_DENIED.
            from app.services.applications import cdr_cease_application
            cdr_cease_application(r["application_id"])
        else:
            # Auto-create next CDRReview.
            app = store.applications.get(r["application_id"])
            if app is not None:
                diary = app.get("cdr_diary")
                months = {
                    "MIE": MIE_DIARY_MONTHS,
                    "MIP": MIP_DIARY_MONTHS,
                    "MINE": MINE_DIARY_MONTHS,
                }.get(diary, MIP_DIARY_MONTHS)
                if isinstance(now, datetime):
                    base = now.date()
                else:
                    base = now
                next_due = add_months(base, months)
                next_id = new_uuid()
                store.cdr_reviews[next_id] = {
                    "id": next_id,
                    "application_id": r["application_id"],
                    "review_due_date": next_due,
                    "scheduled_at": None,
                    "completed_at": None,
                    "outcome": None,
                    "medical_improvement_found": None,
                    "working_at_sga": None,
                    "status": "PENDING",
                    "created_at": now,
                    "updated_at": now,
                    "version": 1,
                }
                # Also update the parent application's next_cdr_due_date.
                app["next_cdr_due_date"] = next_due
                app["updated_at"] = now
                app["version"] += 1
    return r
