"""Public staffing measures, discrepancy investigations, and rating appeals."""

from flask import Blueprint

import calc
import services
from db import base_record, clock_now, clock_str, db, find, maybe, ordered, touch
from errors import ApiError
from middleware import auth, facility_scope
from response import apply_filters, created, listing, ok
from validation import body, check_enum, fk, need_int, need_str

bp = Blueprint("measures", __name__)

READ_ROLES = (
    "PlatformAdmin",
    "StaffingCoordinator",
    "FacilityAdministrator",
    "StateAuditor",
    "CmsPublisher",
    "AppealsReviewer",
)

TRIGGER_REASONS = (
    "AUDIT_SCORE_BELOW_FLOOR",
    "UNSUPPORTED_HOURS",
    "CENSUS_MISMATCH",
    "VENDOR_DATA_GAP",
    "PUBLIC_COMPLAINT",
)
GROUNDS = ("DATA_ENTRY_ERROR", "CENSUS_ERROR", "VENDOR_DATA_ERROR", "MEASURE_CALCULATION_ERROR")


# --------------------------------------------------------------------------
# staffing measures
# --------------------------------------------------------------------------

@bp.post("/staffing-measures")
def compute_measure():
    actor = auth("CmsPublisher")
    b = body()
    submission = fk(b, "submission_id", db.submissions, "ERR_SUBMISSION_NOT_FOUND")
    if submission is None:
        raise ApiError("ERR_INVALID_REQUEST", message="Body field 'submission_id' is required.")

    services.guard_submission_status(submission, ("ACCEPTED",))
    siblings = services.measures_of_submission(submission["id"])
    for measure in siblings:
        if measure["audit_status"] == "UNDER_AUDIT":
            raise ApiError("ERR_MEASURE_UNDER_AUDIT")
    if not services.counted_census(submission["id"]):
        raise ApiError("ERR_NO_CENSUS_DATA")
    for measure in siblings:
        if measure["publication_status"] in ("PROVISIONAL", "PUBLISHED"):
            raise ApiError("ERR_DUPLICATE_MEASURE")

    measure = base_record()
    measure.update(
        {
            "submission_id": submission["id"],
            "facility_id": submission["facility_id"],
            "reporting_period_id": submission["reporting_period_id"],
            "measure_variant": "AS_SUBMITTED",
            "total_nurse_hprd": None,
            "rn_hprd": None,
            "weekend_total_nurse_hprd": None,
            "total_nurse_points": 1,
            "rn_points": 1,
            "days_with_zero_rn_hours": 0,
            "staffing_rating": 1,
            "publication_status": "PROVISIONAL",
            "audit_status": "NOT_AUDITED",
            "published_at": None,
            "appeal_deadline": None,
            "has_open_appeal": False,
            "computed_by_user_id": actor.user_id,
        }
    )
    measure["_appeal_deadline_dt"] = None
    services.apply_measure_figures(measure, submission, "AS_SUBMITTED")
    db.measures[measure["id"]] = measure
    return created(measure)


@bp.get("/staffing-measures/<ident>")
def get_measure(ident):
    auth(*READ_ROLES)
    return ok(find(db.measures, ident, "ERR_MEASURE_NOT_FOUND"))


@bp.get("/staffing-measures")
def list_measures():
    auth(*READ_ROLES)
    rows = apply_filters(
        ordered(db.measures.values()),
        (
            "submission_id",
            "facility_id",
            "reporting_period_id",
            "publication_status",
            "audit_status",
            "measure_variant",
        ),
    )
    return listing(rows)


@bp.post("/staffing-measures/<ident>/publish")
def publish_measure(ident):
    auth("CmsPublisher")
    measure = find(db.measures, ident, "ERR_MEASURE_NOT_FOUND")

    for sibling in services.measures_of_submission(measure["submission_id"]):
        if sibling["audit_status"] == "UNDER_AUDIT":
            raise ApiError("ERR_MEASURE_UNDER_AUDIT")
    facility = db.facilities[measure["facility_id"]]
    if facility["posture"] == "SANCTIONED":
        raise ApiError("ERR_FACILITY_SANCTIONED")
    if measure["publication_status"] != "PROVISIONAL":
        raise ApiError("ERR_MEASURE_NOT_PUBLISHED")

    measure["publication_status"] = "PUBLISHED"
    services.set_appeal_deadline(measure)
    touch(measure)
    services.derive_facility(facility)
    return ok(measure)


# --------------------------------------------------------------------------
# discrepancy cases
# --------------------------------------------------------------------------

@bp.post("/discrepancy-cases")
def create_case():
    actor = auth("StateAuditor")
    b = body()

    facility = fk(b, "facility_id", db.facilities, "ERR_FACILITY_NOT_FOUND")
    submission = fk(b, "submission_id", db.submissions, "ERR_SUBMISSION_NOT_FOUND")
    measure = fk(b, "staffing_measure_id", db.measures, "ERR_MEASURE_NOT_FOUND")

    if facility is None:
        raise ApiError("ERR_INVALID_REQUEST", message="Body field 'facility_id' is required.")
    if submission is None:
        raise ApiError("ERR_INVALID_REQUEST", message="Body field 'submission_id' is required.")
    trigger_reason = need_str(b, "trigger_reason")
    detail = need_str(b, "detail")
    check_enum(trigger_reason, TRIGGER_REASONS, "trigger_reason")

    if submission["facility_id"] != facility["id"]:
        raise ApiError("ERR_CASE_SUBMISSION_MISMATCH")
    if measure is not None and measure["submission_id"] != submission["id"]:
        raise ApiError("ERR_CASE_SUBMISSION_MISMATCH")

    case = base_record()
    case.update(
        {
            "facility_id": facility["id"],
            "submission_id": submission["id"],
            "staffing_measure_id": measure["id"] if measure else None,
            "trigger_reason": trigger_reason,
            "detail": detail,
            "status": "OPEN",
            "auto_opened": False,
            "opened_by_user_id": actor.user_id,
            "info_request_count": 0,
            "facility_response_count": 0,
            "last_request_note": None,
            "last_response_note": None,
            "substantiated_by_user_id": None,
            "resolution_note": None,
        }
    )
    db.cases[case["id"]] = case
    services.derive_facility(facility)
    return created(case)


@bp.get("/discrepancy-cases/<ident>")
def get_case(ident):
    auth(*READ_ROLES)
    return ok(find(db.cases, ident, "ERR_CASE_NOT_FOUND"))


@bp.get("/discrepancy-cases")
def list_cases():
    auth(*READ_ROLES)
    rows = apply_filters(
        ordered(db.cases.values()),
        ("facility_id", "submission_id", "staffing_measure_id", "trigger_reason", "status"),
    )
    return listing(rows)


@bp.post("/discrepancy-cases/<ident>/request-info")
def request_info(ident):
    auth("StateAuditor")
    case = find(db.cases, ident, "ERR_CASE_NOT_FOUND")
    b = body()
    note = need_str(b, "request_note")
    if case["status"] not in ("OPEN", "UNDER_REVIEW"):
        raise ApiError("ERR_CASE_STATE_INVALID")

    case["status"] = "INFO_REQUESTED"
    case["last_request_note"] = note
    case["info_request_count"] += 1
    touch(case)
    return ok(case)


@bp.post("/discrepancy-cases/<ident>/respond")
def respond_case(ident):
    actor = auth("FacilityAdministrator")
    target = maybe(db.cases, ident)
    facility_scope(actor, target["facility_id"] if target else None)
    case = find(db.cases, ident, "ERR_CASE_NOT_FOUND")

    b = body()
    note = need_str(b, "response_note")
    if case["status"] != "INFO_REQUESTED":
        raise ApiError("ERR_CASE_STATE_INVALID")

    case["status"] = "UNDER_REVIEW"
    case["last_response_note"] = note
    case["facility_response_count"] += 1
    touch(case)

    measure = db.measures.get(case["staffing_measure_id"])
    if measure is not None and measure["audit_status"] == "NOT_AUDITED":
        measure["audit_status"] = "UNDER_AUDIT"
        touch(measure)
    return ok(case)


@bp.post("/discrepancy-cases/<ident>/substantiate")
def substantiate_case(ident):
    actor = auth("StateAuditor")
    case = find(db.cases, ident, "ERR_CASE_NOT_FOUND")
    b = body()
    note = need_str(b, "resolution_note")

    if case["status"] not in ("INFO_REQUESTED", "UNDER_REVIEW"):
        raise ApiError("ERR_CASE_STATE_INVALID")
    if case["facility_response_count"] < 1:
        raise ApiError("ERR_CASE_RESPONSE_REQUIRED")

    case["status"] = "SUBSTANTIATED"
    case["substantiated_by_user_id"] = actor.user_id
    case["resolution_note"] = note
    touch(case)

    measure = db.measures.get(case["staffing_measure_id"])
    if measure is not None and measure["audit_status"] == "UNDER_AUDIT":
        measure["audit_status"] = "AUDIT_REVISED"
        measure["measure_variant"] = "AUDIT_ADJUSTED"
        services.apply_measure_figures(
            measure, db.submissions[measure["submission_id"]], "AUDIT_ADJUSTED"
        )
        touch(measure)

    facility = db.facilities[case["facility_id"]]
    services.derive_facility(facility)
    services.sanction_cascade(facility)
    return ok(case)


@bp.post("/discrepancy-cases/<ident>/dismiss")
def dismiss_case(ident):
    auth("StateAuditor")
    case = find(db.cases, ident, "ERR_CASE_NOT_FOUND")
    b = body()
    note = need_str(b, "resolution_note")

    if case["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_CASE_STATE_INVALID")

    case["status"] = "DISMISSED"
    case["resolution_note"] = note
    touch(case)

    measure = db.measures.get(case["staffing_measure_id"])
    if measure is not None and measure["audit_status"] == "UNDER_AUDIT":
        measure["audit_status"] = "AUDIT_CONFIRMED"
        touch(measure)

    services.derive_facility(db.facilities[case["facility_id"]])
    return ok(case)


# --------------------------------------------------------------------------
# rating appeals
# --------------------------------------------------------------------------

@bp.post("/rating-appeals")
def create_appeal():
    actor = auth("FacilityAdministrator")
    b = body()

    raw_measure = b.get("staffing_measure_id")
    pre = db.measures.get(raw_measure) if isinstance(raw_measure, str) else None
    facility_scope(actor, pre["facility_id"] if pre else None)

    measure = fk(b, "staffing_measure_id", db.measures, "ERR_MEASURE_NOT_FOUND")
    case = fk(b, "discrepancy_case_id", db.cases, "ERR_CASE_NOT_FOUND")

    if measure is None:
        raise ApiError("ERR_INVALID_REQUEST", message="Body field 'staffing_measure_id' is required.")
    grounds = need_str(b, "grounds")
    narrative = need_str(b, "narrative")
    expected = need_int(b, "expected_measure_version")
    check_enum(grounds, GROUNDS, "grounds")

    if measure["publication_status"] != "PUBLISHED":
        raise ApiError("ERR_MEASURE_NOT_PUBLISHED")
    if expected != measure["version"]:
        raise ApiError("ERR_STALE_MEASURE_VERSION")
    if clock_now() > measure["_appeal_deadline_dt"]:
        raise ApiError("ERR_APPEAL_WINDOW_CLOSED")
    if case is not None and case["facility_id"] != measure["facility_id"]:
        raise ApiError("ERR_APPEAL_CASE_MISMATCH")
    for existing in db.appeals.values():
        if existing["staffing_measure_id"] == measure["id"] and existing["status"] == "SUBMITTED":
            raise ApiError("ERR_DUPLICATE_APPEAL")

    appeal = base_record()
    appeal.update(
        {
            "staffing_measure_id": measure["id"],
            "facility_id": measure["facility_id"],
            "discrepancy_case_id": case["id"] if case else None,
            "filed_by_worker_id": actor.worker_id,
            "grounds": grounds,
            "narrative": narrative,
            "status": "SUBMITTED",
            "decided_by_user_id": None,
            "decision_note": None,
            "decided_at": None,
            "surcharge_waived_cents": 0,
        }
    )
    db.appeals[appeal["id"]] = appeal

    measure["has_open_appeal"] = True
    touch(measure)
    return created(appeal)


@bp.get("/rating-appeals/<ident>")
def get_appeal(ident):
    auth(*READ_ROLES)
    return ok(find(db.appeals, ident, "ERR_APPEAL_NOT_FOUND"))


@bp.get("/rating-appeals")
def list_appeals():
    auth(*READ_ROLES)
    rows = apply_filters(
        ordered(db.appeals.values()),
        (
            "staffing_measure_id",
            "facility_id",
            "discrepancy_case_id",
            "filed_by_worker_id",
            "grounds",
            "status",
        ),
    )
    return listing(rows)


def _decide(appeal, actor, note, granted):
    appeal["status"] = "GRANTED" if granted else "DENIED"
    appeal["decided_by_user_id"] = actor.user_id
    appeal["decision_note"] = note
    appeal["decided_at"] = clock_str()


@bp.post("/rating-appeals/<ident>/grant")
def grant_appeal(ident):
    actor = auth("AppealsReviewer")
    appeal = find(db.appeals, ident, "ERR_APPEAL_NOT_FOUND")
    b = body()
    note = need_str(b, "decision_note")

    measure = db.measures[appeal["staffing_measure_id"]]
    if measure["publication_status"] != "PUBLISHED":
        raise ApiError("ERR_MEASURE_NOT_PUBLISHED")
    if appeal["status"] != "SUBMITTED":
        raise ApiError("ERR_APPEAL_STATE_INVALID")

    submission = db.submissions[measure["submission_id"]]
    outstanding = submission["amendment_surcharge_cents"] - submission["waived_surcharge_cents"]

    _decide(appeal, actor, note, True)
    appeal["surcharge_waived_cents"] = outstanding
    touch(appeal)

    measure["publication_status"] = "SUPPRESSED"
    measure["has_open_appeal"] = False
    touch(measure)

    case = db.cases.get(appeal["discrepancy_case_id"])
    if case is not None and case["status"] == "SUBSTANTIATED":
        case["status"] = "OVERTURNED"
        case["resolution_note"] = note
        touch(case)

    if outstanding != 0:
        submission["waived_surcharge_cents"] += outstanding
        touch(submission)

    services.derive_facility(db.facilities[measure["facility_id"]])
    return ok(appeal)


@bp.post("/rating-appeals/<ident>/deny")
def deny_appeal(ident):
    actor = auth("AppealsReviewer")
    appeal = find(db.appeals, ident, "ERR_APPEAL_NOT_FOUND")
    b = body()
    note = need_str(b, "decision_note")

    measure = db.measures[appeal["staffing_measure_id"]]
    if measure["publication_status"] != "PUBLISHED":
        raise ApiError("ERR_MEASURE_NOT_PUBLISHED")
    if appeal["status"] != "SUBMITTED":
        raise ApiError("ERR_APPEAL_STATE_INVALID")

    _decide(appeal, actor, note, False)
    touch(appeal)

    measure["has_open_appeal"] = False
    touch(measure)
    return ok(appeal)
