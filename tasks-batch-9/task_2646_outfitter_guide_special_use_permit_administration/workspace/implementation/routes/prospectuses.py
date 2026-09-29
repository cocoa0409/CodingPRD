"""Competitive solicitations: issue, respond, close, award, cancel (PRD 3.3)."""
from decimal import Decimal

from flask import Blueprint

import calc
import envelope
import security
import serialize
import shapes
import store
from errors import ApiError
from routes.common import match, qstr
from security import ADMIN, ANY_ROLE, OFFICER, REPRESENTATIVE, SPECIALIST

bp = Blueprint("prospectuses", __name__)

DEFAULT_MIN_QUALIFYING_SCORE = Decimal("60.0")
OPEN_OR_EVALUATING = ("OPEN", "EVALUATING")


def responses_of(prospectus_id):
    return [
        a
        for a in store.all_of("applications")
        if a["prospectus_id"] == prospectus_id and a["status"] == "PROSPECTUS_RESPONDED"
    ]


def recount(prospectus):
    prospectus["responsive_application_count"] = len(responses_of(prospectus["id"]))


@bp.post("/osup/prospectuses")
def issue_prospectus():
    security.authenticate((SPECIALIST, ADMIN))
    data = shapes.body()
    # priority 3: existence, in the order the endpoint declares the two ids
    area = None
    raw_area = data.get("use_area_id")
    if isinstance(raw_area, str) and raw_area.strip():
        area = store.get_or_404("use_areas", raw_area, "ERR_USE_AREA_NOT_FOUND")
    assessment = None
    raw_assessment = data.get("needs_assessment_id")
    if isinstance(raw_assessment, str) and raw_assessment.strip():
        assessment = store.get_or_404(
            "needs_assessments", raw_assessment, "ERR_NEEDS_ASSESSMENT_NOT_FOUND"
        )
    # priority 5: shape
    use_area_id = shapes.req_id(data, "use_area_id")
    needs_assessment_id = shapes.req_id(data, "needs_assessment_id")
    offered = shapes.req_int(data, "offered_service_days", minimum=1, maximum=3650)
    deadline = shapes.req_date(data, "submission_deadline_date")
    min_score = shapes.opt_dec(
        data,
        "min_qualifying_score",
        minimum=Decimal("0"),
        maximum=Decimal("100"),
        default=DEFAULT_MIN_QUALIFYING_SCORE,
    )
    if area is None:
        area = store.get_or_404("use_areas", use_area_id, "ERR_USE_AREA_NOT_FOUND")
    if assessment is None:
        assessment = store.get_or_404(
            "needs_assessments", needs_assessment_id, "ERR_NEEDS_ASSESSMENT_NOT_FOUND"
        )
    # priority 9: the cited assessment must be published and must find a public need
    if assessment["status"] != "PUBLISHED":
        raise ApiError(
            "ERR_NEEDS_ASSESSMENT_NOT_PUBLISHED", "the cited assessment is not PUBLISHED"
        )
    if assessment["public_need_finding"] != "NEED_EXISTS":
        raise ApiError("ERR_NO_PUBLIC_NEED", "the governing assessment finds no public need")

    prospectus = store.insert(
        "prospectuses",
        {
            "use_area_id": use_area_id,
            "needs_assessment_id": needs_assessment_id,
            "offered_service_days": offered,
            "submission_deadline_date": deadline,
            "min_qualifying_score": calc.rh(min_score, 2),
            "responsive_application_count": 0,
            "awarded_application_id": None,
            "cancellation_reason_code": None,
            "status": "OPEN",
        },
    )
    return envelope.ok(serialize.prospectus(prospectus), 201)


@bp.get("/osup/prospectuses/<prospectus_id>")
def read_prospectus(prospectus_id):
    security.authenticate(ANY_ROLE, mutating=False)
    prospectus = store.get_or_404("prospectuses", prospectus_id, "ERR_PROSPECTUS_NOT_FOUND")
    return envelope.ok(serialize.prospectus(prospectus))


@bp.get("/osup/prospectuses")
def list_prospectuses():
    security.authenticate(ANY_ROLE, mutating=False)
    filters = {
        "use_area_id": qstr("use_area_id"),
        "needs_assessment_id": qstr("needs_assessment_id"),
        "status": qstr("status"),
    }
    rows = [p for p in store.all_of("prospectuses") if match(p, **filters)]
    return envelope.paginate(store.sort_created(rows), serialize.prospectus)


@bp.post("/osup/prospectuses/<prospectus_id>/responses")
def file_response(prospectus_id):
    caller = security.authenticate((REPRESENTATIVE,))
    prospectus = store.get_or_404("prospectuses", prospectus_id, "ERR_PROSPECTUS_NOT_FOUND")
    data = shapes.body()
    app = None
    raw_app = data.get("application_id")
    if isinstance(raw_app, str) and raw_app.strip():
        app = store.get_or_404("applications", raw_app, "ERR_APPLICATION_NOT_FOUND")
    if app is not None:
        security.require_owner(caller, app["outfitter_id"])
    application_id = shapes.req_id(data, "application_id")
    if app is None:
        app = store.get_or_404("applications", application_id, "ERR_APPLICATION_NOT_FOUND")
        security.require_owner(caller, app["outfitter_id"])
    # priority 7: the application first, then the solicitation
    if app["status"] != "PROSPECTUS_QUEUED":
        raise ApiError(
            "ERR_INVALID_APPLICATION_STATE", "only a PROSPECTUS_QUEUED application may respond"
        )
    if prospectus["status"] != "OPEN":
        raise ApiError("ERR_PROSPECTUS_NOT_OPEN", "the solicitation is not OPEN")
    if prospectus["use_area_id"] != app["use_area_id"]:
        raise ApiError(
            "ERR_INVALID_REQUEST", "the solicitation covers a different use area"
        )
    # priority 10: the deadline boundary is inclusive
    if store.today() > store.as_date(prospectus["submission_deadline_date"]):
        raise ApiError("ERR_SUBMISSION_DEADLINE_PASSED", "the submission window has closed")
    # priority 12: the request must fit inside what is offered
    if app["requested_service_days"] > prospectus["offered_service_days"]:
        raise ApiError(
            "ERR_INSUFFICIENT_SERVICE_DAYS",
            "requested_service_days exceeds offered_service_days",
        )

    app["status"] = "PROSPECTUS_RESPONDED"
    app["prospectus_id"] = prospectus["id"]
    store.touch(app)
    recount(prospectus)
    store.touch(prospectus)
    return envelope.ok(serialize.application(app))


@bp.post("/osup/prospectuses/<prospectus_id>/close-submissions")
def close_submissions(prospectus_id):
    security.authenticate((SPECIALIST,))
    prospectus = store.get_or_404("prospectuses", prospectus_id, "ERR_PROSPECTUS_NOT_FOUND")
    if prospectus["status"] != "OPEN":
        raise ApiError("ERR_PROSPECTUS_NOT_OPEN", "the solicitation is not OPEN")
    for app in store.sort_created(responses_of(prospectus["id"])):
        app["preliminary_evaluation_score"] = calc.prospectus_score(
            app, prospectus, "PRELIMINARY"
        )
        store.touch(app)
    prospectus["status"] = "EVALUATING"
    recount(prospectus)
    store.touch(prospectus)
    return envelope.ok(serialize.prospectus(prospectus))


@bp.post("/osup/prospectuses/<prospectus_id>/award")
def award_prospectus(prospectus_id):
    security.authenticate((OFFICER, ADMIN))
    prospectus = store.get_or_404("prospectuses", prospectus_id, "ERR_PROSPECTUS_NOT_FOUND")
    data = shapes.body()
    expected = shapes.req_int(data, "expected_use_area_version", minimum=0)
    area = store.get("use_areas", prospectus["use_area_id"])
    # priority 6: optimistic concurrency on the governing area
    if area is None or expected != area["version"]:
        raise ApiError("ERR_STALE_USE_AREA_VERSION", "expected_use_area_version is stale")
    # priority 7
    if prospectus["status"] != "EVALUATING":
        raise ApiError("ERR_PROSPECTUS_NOT_OPEN", "the solicitation is not EVALUATING")

    responses = store.sort_created(responses_of(prospectus["id"]))
    for app in responses:
        app["final_evaluation_score"] = calc.prospectus_score(app, prospectus, "FINAL")
        store.touch(app)
    bar = prospectus["min_qualifying_score"]
    pool = [a for a in responses if a["final_evaluation_score"] >= bar]
    if not pool:
        # nothing is written -- the request-scoped snapshot is rolled back
        raise ApiError(
            "ERR_NO_RESPONSIVE_APPLICATIONS", "no response reached min_qualifying_score"
        )
    pool = sorted(
        pool,
        key=lambda a: (-a["final_evaluation_score"], a["_created_dt"], a["_seq"]),
    )
    winner = pool[0]
    winner["status"] = "AWARDED"
    store.touch(winner)
    released_years = set()
    for app in responses:
        if app["id"] == winner["id"]:
            continue
        app["status"] = "DENIED"
        app["denial_reason_code"] = "NOT_SELECTED"
        store.touch(app)
        released_years.add(app["season_year"])
    prospectus["awarded_application_id"] = winner["id"]
    prospectus["status"] = "AWARDED"
    store.touch(prospectus)
    calc.recompute_area(area)
    for year in sorted(released_years):
        calc.recompute_governing_assessment(area["id"], year)
    return envelope.ok(serialize.prospectus(prospectus))


@bp.post("/osup/prospectuses/<prospectus_id>/cancel")
def cancel_prospectus(prospectus_id):
    security.authenticate((OFFICER, ADMIN))
    prospectus = store.get_or_404("prospectuses", prospectus_id, "ERR_PROSPECTUS_NOT_FOUND")
    data = shapes.body()
    reason = shapes.req_str(data, "cancellation_reason_code")
    if prospectus["status"] not in OPEN_OR_EVALUATING:
        raise ApiError("ERR_PROSPECTUS_NOT_OPEN", "the solicitation is already terminal")
    for app in store.sort_created(responses_of(prospectus["id"])):
        app["status"] = "PROSPECTUS_QUEUED"
        app["prospectus_id"] = None
        app["preliminary_evaluation_score"] = None
        app["final_evaluation_score"] = None
        store.touch(app)
    prospectus["cancellation_reason_code"] = reason
    prospectus["status"] = "CANCELLED"
    prospectus["responsive_application_count"] = 0
    store.touch(prospectus)
    return envelope.ok(serialize.prospectus(prospectus))
