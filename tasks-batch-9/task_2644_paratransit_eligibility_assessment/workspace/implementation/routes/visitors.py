"""PRD 3.10 — visitor eligibility for out-of-area riders."""

from datetime import timedelta

from flask import Blueprint

import lookups
import serializers
import shapes
from auth import require
from envelope import created, ok
from errors import ApiError
from store import base_record, db, plus_days, today, touch

bp = Blueprint("visitors", __name__)

VISITOR_DAYS_ALLOWED = 21
VISITOR_WINDOW_DAYS = 365
SERVICE_DATE_HORIZON_DAYS = 90


@bp.post("/applicants/<applicant_id>/visitor-eligibilities")
@require(("IntakeClerk", "AccessibilityOfficeAdmin"))
def grant_visitor_eligibility(applicant_id):
    applicant = lookups.applicant(applicant_id)
    payload = shapes.body()
    home_agency_name = shapes.req_str(payload, "home_agency_name")
    certification = shapes.req_bool(payload, "home_agency_certification_provided")
    visit_start_date = shapes.req_iso_date(payload, "visit_start_date")

    # PRD 3.10: the visitor gate first, local eligibility only then.
    if applicant["residence_zone"] != "OUT_OF_SERVICE_AREA" or certification is not True:
        raise ApiError("ERR_NOT_OUT_OF_AREA")
    issued = lookups.issued_determination_of(applicant["id"])
    if issued is not None and issued["category"] != "INELIGIBLE":
        raise ApiError("ERR_LOCAL_ELIGIBILITY_EXISTS")

    rec = base_record()
    rec.update(
        {
            "applicant_id": applicant["id"],
            "home_agency_name": home_agency_name,
            "home_agency_certification_provided": certification,
            "visit_start_date": visit_start_date,
            "service_dates": [],
            "days_used_365": 0,
            "days_remaining_365": VISITOR_DAYS_ALLOWED,
            "status": "ACTIVE",
        }
    )
    db.visitor_records[rec["id"]] = rec

    # Where the rider holds no ISSUED determination at all their status becomes
    # VISITOR; where they hold an INELIGIBLE one it is left as it stands.
    if issued is None:
        applicant["current_eligibility_status"] = "VISITOR"
        touch(applicant)
    return created(serializers.visitor_record(rec))


@bp.post("/visitor-eligibilities/<visitor_record_id>/service-days")
@require(("IntakeClerk", "AccessibilityOfficeAdmin"))
def record_service_day(visitor_record_id):
    rec = lookups.visitor_record(visitor_record_id)
    payload = shapes.body()
    service_date = shapes.req_iso_date(payload, "service_date")

    if rec["status"] != "ACTIVE":
        raise ApiError("ERR_VISITOR_RECORD_INACTIVE")
    if service_date < rec["visit_start_date"] or service_date > plus_days(
        today(), SERVICE_DATE_HORIZON_DAYS
    ):
        raise ApiError("ERR_SERVICE_DATE_OUT_OF_RANGE")

    # Step 1 — the window is fixed from the request, never from the outcome.
    window_end = service_date
    window_start = window_end - timedelta(days=VISITOR_WINDOW_DAYS - 1)

    # Step 2 — count the distinct dates already present inside that window.
    used_before = len({d for d in rec["service_dates"] if window_start <= d <= window_end})

    # Step 3 — grant only when that count is below the allowance.
    if used_before >= VISITOR_DAYS_ALLOWED:
        raise ApiError("ERR_VISITOR_DAYS_EXHAUSTED")

    # Step 4 — append, idempotently.
    if service_date not in rec["service_dates"]:
        rec["service_dates"].append(service_date)

    # Step 5 — recompute the counters over the window fixed in step 1.
    used = len({d for d in rec["service_dates"] if window_start <= d <= window_end})
    rec["days_used_365"] = used
    remaining = VISITOR_DAYS_ALLOWED - used
    rec["days_remaining_365"] = remaining if remaining > 0 else 0
    if used == VISITOR_DAYS_ALLOWED:
        rec["status"] = "EXHAUSTED"
    touch(rec)
    return ok(serializers.visitor_record(rec))
