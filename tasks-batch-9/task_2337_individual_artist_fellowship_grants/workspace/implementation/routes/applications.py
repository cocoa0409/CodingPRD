"""Application and WorkSample endpoints."""

from flask import Blueprint

import constants as C
import db
import middleware as mw
import response
import validation as v
from errors import ApiError
from routes import support as sup
from services import calc, cascade, derive

bp = Blueprint("applications", __name__)

PO = (mw.PROGRAM_OFFICER,)
ARTIST_ONLY = (mw.ARTIST,)
ARTIST_OR_PO = (mw.ARTIST, mw.PROGRAM_OFFICER)
ALL = sup.ALL_ROLES


def _counted_samples(application):
    return [
        s
        for s in db.rows(
            "work_samples", lambda r, a=application["id"]: r["application_id"] == a
        )
        if s["status"] in C.COUNTED_SAMPLE_STATUSES
    ]


def _own(application, user_id, role):
    if role == mw.ARTIST and application["artist_id"] != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")


# ========================================================== applications


@bp.post("/grants/applications")
def create_application():
    user_id, role = mw.authorize(ARTIST_OR_PO, entity_backed=True)
    data = v.body()
    cycle_id = v.req_id(data, "cycle_id")
    discipline_id = v.req_id(data, "discipline_category_id")
    artist_id = v.req_id(data, "artist_id")
    statement = v.req_str(data, "artist_statement")
    narrative = v.req_str(data, "career_narrative")

    # P45 body foreign keys, in the order §1.5 declares them.
    sup.resolve_fk("cycles", cycle_id)
    discipline = sup.resolve_fk("disciplines", discipline_id)
    if discipline["cycle_id"] != cycle_id:
        raise ApiError(
            "ERR_DISCIPLINE_CATEGORY_NOT_FOUND",
            "That discipline category does not belong to the named cycle.",
        )
    sup.resolve_fk("artists", artist_id)

    if role == mw.ARTIST and artist_id != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")

    application = db.insert(
        "applications",
        {
            "cycle_id": cycle_id,
            "discipline_category_id": discipline_id,
            "artist_id": artist_id,
            "assigned_panel_id": None,
            "artist_statement": statement,
            "career_narrative": narrative,
            "sealed_alias": None,
            "status": "DRAFT",
            "anonymity_status": "SEALED",
            "submitted_at": None,
            "notified_at": None,
            "eligibility_determined_by": None,
            "ineligibility_reason_code": None,
            "residency_months_at_deadline": None,
            "blackout_gap_years": None,
            "applicant_legal_name": None,
            "applicant_region": None,
            "work_sample_count": 0,
            "valid_review_count": 0,
            "provisional_composite_score": None,
            "final_composite_score": None,
            "score_spread": None,
            "review_round_number": 0,
        },
    )
    return response.obj(sup.application_view(role)(application), 201)


@bp.get("/grants/applications/<application_id>")
def read_application(application_id):
    _, role = mw.authorize(ALL)
    application = sup.resolve("applications", application_id)
    return response.obj(sup.application_view(role)(application))


@bp.get("/grants/applications")
def list_applications():
    _, role = mw.authorize(ALL)
    rows = db.rows("applications")
    rows = sup.eq(rows, "cycle_id", v.query_str("cycle_id"))
    rows = sup.eq(rows, "discipline_category_id", v.query_str("discipline_category_id"))
    rows = sup.eq(rows, "artist_id", v.query_str("artist_id"))
    rows = sup.eq(rows, "assigned_panel_id", v.query_str("assigned_panel_id"))
    rows = sup.eq(rows, "status", v.query_str("status"))
    rows = sup.eq(rows, "anonymity_status", v.query_str("anonymity_status"))
    return sup.listed(rows, sup.application_view(role))


@bp.post("/grants/applications/<application_id>/submit")
def submit_application(application_id):
    user_id, role = mw.authorize(ARTIST_ONLY, entity_backed=True)
    application = sup.resolve("applications", application_id)
    _own(application, user_id, role)

    if application["status"] != "DRAFT":
        raise ApiError("ERR_APPLICATION_STATE_INVALID")

    cycle = derive.cycle_of(application)
    discipline = derive.discipline_of(application)
    artist = db.get("artists", application["artist_id"])

    if cycle["status"] != "OPEN":
        raise ApiError("ERR_CYCLE_STATE_INVALID")
    if artist["standing"] != "GOOD_STANDING":
        raise ApiError("ERR_ARTIST_NOT_IN_GOOD_STANDING")

    moment = db.now()
    if moment < db.dt_of(cycle, "application_open_at"):
        raise ApiError("ERR_APPLICATION_WINDOW_NOT_OPEN")
    if moment > db.dt_of(cycle, "application_deadline_at"):
        raise ApiError("ERR_APPLICATION_DEADLINE_PASSED")

    for other in derive.applications_of_cycle(cycle["id"]):
        if other["id"] == application["id"] or other["artist_id"] != artist["id"]:
            continue
        if other["status"] not in ("DRAFT", "WITHDRAWN"):
            raise ApiError("ERR_DUPLICATE_APPLICATION")

    samples = _counted_samples(application)
    allowed = list(discipline["allowed_media"])
    duration = sum(
        int(s["duration_seconds"] or 0) for s in samples if s["medium"] in C.TIMED_MEDIA
    )
    if (
        len(samples) < int(discipline["required_work_sample_count"])
        or any(s["medium"] not in allowed for s in samples)
        or duration > int(discipline["max_total_duration_seconds"])
    ):
        raise ApiError("ERR_WORK_SAMPLE_REQUIREMENTS_NOT_MET")

    counter = int(discipline["submitted_sequence_counter"]) + 1
    derive.set_fields(discipline, submitted_sequence_counter=counter)
    alias = "%s-%s-%04d" % (
        discipline["alias_prefix"],
        cycle["fiscal_year"],
        counter,
    )
    months = calc.residency_months(
        db.date_of(artist, "residency_start_date"),
        db.dt_of(cycle, "application_deadline_at"),
    )
    last_year = artist["last_award_fiscal_year"]
    gap = None if last_year is None else int(cycle["fiscal_year"]) - int(last_year)

    derive.set_fields(
        application,
        status="SUBMITTED",
        submitted_at=db.iso3(moment),
        sealed_alias=alias,
        residency_months_at_deadline=months,
        blackout_gap_years=gap,
        applicant_legal_name=artist["legal_name"],
        applicant_region=artist["region"],
    )
    derive.refresh_cycle(cycle)
    return response.obj(sup.application_view(role)(application))


def _failing_criteria(application, cycle, artist):
    """The set of ineligibility reason codes that actually fail."""
    failures = set()
    months = application["residency_months_at_deadline"]
    if months is None or int(months) < int(cycle["residency_min_months"]):
        failures.add("RESIDENCY_DURATION")
    gap = application["blackout_gap_years"]
    if gap is not None and int(gap) < int(cycle["award_blackout_years"]):
        failures.add("PRIOR_AWARD_BLACKOUT")
    if artist["is_enrolled_student"]:
        failures.add("ENROLLED_STUDENT")
    return failures


@bp.post("/grants/applications/<application_id>/eligibility")
def eligibility(application_id):
    user_id, role = mw.authorize(PO)
    data = v.body()
    determination = v.req_enum(data, "determination", C.ELIGIBILITY_DETERMINATIONS)
    reason = v.opt_enum(data, "ineligibility_reason_code", C.INELIGIBILITY_REASONS)
    if determination == "INELIGIBLE" and reason is None:
        v.bad("ineligibility_reason_code is required for an INELIGIBLE determination.")

    application = sup.resolve("applications", application_id)
    if application["status"] != "SUBMITTED":
        raise ApiError("ERR_APPLICATION_STATE_INVALID")

    cycle = derive.cycle_of(application)
    artist = db.get("artists", application["artist_id"])
    if cycle["status"] not in ("CLOSED", "PANEL_REVIEW"):
        raise ApiError("ERR_CYCLE_STATE_INVALID")

    failures = _failing_criteria(application, cycle, artist)
    if determination == "ELIGIBLE":
        if failures:
            raise ApiError("ERR_ELIGIBILITY_CRITERIA_NOT_MET")
        derive.set_fields(
            application, status="ELIGIBLE", eligibility_determined_by=user_id
        )
    else:
        if reason not in failures:
            raise ApiError("ERR_INELIGIBILITY_REASON_UNSUPPORTED")
        derive.set_fields(
            application,
            status="INELIGIBLE",
            ineligibility_reason_code=reason,
            eligibility_determined_by=user_id,
            notified_at=db.iso3(db.now()),
        )

    derive.refresh_discipline_by_id(application["discipline_category_id"])
    derive.refresh_cycle(cycle)
    return response.obj(sup.application_view(role)(application))


@bp.post("/grants/applications/<application_id>/withdraw")
def withdraw_application(application_id):
    user_id, role = mw.authorize(ARTIST_ONLY, entity_backed=True)
    application = sup.resolve("applications", application_id)
    _own(application, user_id, role)

    status = application["status"]
    if status not in ("DRAFT", "SUBMITTED", "ELIGIBLE"):
        raise ApiError("ERR_APPLICATION_STATE_INVALID")

    cycle = derive.cycle_of(application)
    if status == "SUBMITTED" and cycle["status"] not in ("OPEN", "CLOSED"):
        raise ApiError("ERR_CYCLE_STATE_INVALID")
    if status == "ELIGIBLE" and application["assigned_panel_id"] is not None:
        raise ApiError(
            "ERR_APPLICATION_STATE_INVALID",
            "An application attached to a panel can no longer be withdrawn.",
        )

    derive.set_fields(application, status="WITHDRAWN")
    cascade.reject_open_samples(application)
    derive.refresh_discipline_by_id(application["discipline_category_id"])
    derive.refresh_cycle(cycle)
    return response.obj(sup.application_view(role)(application))


# =========================================================== work samples


@bp.post("/grants/work-samples")
def create_work_sample():
    user_id, role = mw.authorize(ARTIST_OR_PO, entity_backed=True)
    data = v.body()
    application_id = v.req_id(data, "application_id")
    medium = v.req_enum(data, "medium", C.MEDIA)
    ordinal = v.req_int(data, "ordinal", minimum=1)
    page_count = v.opt_int(data, "page_count", None, minimum=0)
    duration = v.opt_int(data, "duration_seconds", 0, minimum=0)
    identifying = v.opt_bool(data, "contains_identifying_metadata", False)

    application = sup.resolve_fk("applications", application_id)
    _own(application, user_id, role)

    if application["status"] != "DRAFT":
        raise ApiError("ERR_APPLICATION_STATE_INVALID")

    siblings = db.rows(
        "work_samples", lambda r: r["application_id"] == application_id
    )
    for sibling in siblings:
        if int(sibling["ordinal"]) == ordinal:
            v.bad("ordinal %d is already used on this application." % ordinal)

    sample = db.insert(
        "work_samples",
        {
            "application_id": application_id,
            "medium": medium,
            "ordinal": ordinal,
            "page_count": page_count,
            "duration_seconds": duration,
            "contains_identifying_metadata": identifying,
            "status": "PENDING_SCREEN",
            "screened_by": None,
        },
    )
    derive.refresh_work_sample_count(application)
    return response.obj(db.public(sample), 201)


@bp.get("/grants/work-samples/<work_sample_id>")
def read_work_sample(work_sample_id):
    mw.authorize(ALL)
    return response.obj(db.public(sup.resolve("work_samples", work_sample_id)))


@bp.get("/grants/work-samples")
def list_work_samples():
    mw.authorize(ALL)
    rows = db.rows("work_samples")
    rows.sort(key=lambda r: (int(r["ordinal"]), r["_seq"]))
    rows = sup.eq(rows, "application_id", v.query_str("application_id"))
    rows = sup.eq(rows, "status", v.query_str("status"))
    rows = sup.eq(rows, "medium", v.query_str("medium"))
    return sup.listed(rows)


@bp.post("/grants/work-samples/<work_sample_id>/screen")
def screen_work_sample(work_sample_id):
    user_id, _ = mw.authorize(PO)
    data = v.body()
    disposition = v.req_enum(data, "disposition", C.WORK_SAMPLE_DISPOSITIONS)
    sample = sup.resolve("work_samples", work_sample_id)

    if sample["status"] != "PENDING_SCREEN":
        raise ApiError("ERR_WORK_SAMPLE_STATE_INVALID")

    application = db.get("applications", sample["application_id"])
    if application["status"] == "WITHDRAWN":
        raise ApiError("ERR_APPLICATION_STATE_INVALID")

    new_status = {
        "CLEARED": "CLEARED",
        "FLAGGED_IDENTIFYING": "FLAGGED",
        "REJECTED": "REJECTED",
    }[disposition]
    derive.set_fields(sample, status=new_status, screened_by=user_id)
    derive.refresh_work_sample_count(application)

    if disposition == "FLAGGED_IDENTIFYING":
        cascade.breach_application(application)
    else:
        derive.refresh_cycle_by_id(application["cycle_id"])
    return response.obj(db.public(sample))


@bp.post("/grants/work-samples/<work_sample_id>/redact")
def redact_work_sample(work_sample_id):
    mw.authorize(PO)
    sample = sup.resolve("work_samples", work_sample_id)
    if sample["status"] != "FLAGGED":
        raise ApiError("ERR_WORK_SAMPLE_STATE_INVALID")
    derive.set_fields(sample, status="REDACTED", contains_identifying_metadata=False)
    application = db.get("applications", sample["application_id"])
    derive.refresh_work_sample_count(application)
    cascade.clear_breach_if_resolved(application)
    return response.obj(db.public(sample))
