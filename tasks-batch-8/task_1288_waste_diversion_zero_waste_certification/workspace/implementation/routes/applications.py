"""CertificationApplication endpoints: drafting, review, and life after approval."""

from flask import Blueprint

from db import base_record, store, touch
from errors import (
    ApiError,
    ERR_APPLICATION_NOT_DRAFT,
    ERR_APPLICATION_NOT_IN_REVIEW,
    ERR_APPLICATION_NOT_SUBMITTED,
    ERR_CERTIFICATION_THRESHOLD_NOT_MET,
    ERR_CROSS_SITE_REFERENCE,
    ERR_PERIOD_NOT_CLOSED,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_STALE_VERSION,
    ERR_STANDING_PROBATION,
    not_found,
)
from middleware import (
    no_input,
    ALL_ROLES,
    authenticate,
    check_unknown,
    f_enum,
    f_int,
    f_str,
    get_body,
)
from response import success_list, success_object
from services.calc import CERT_THRESHOLDS, dec
from services.lifecycle import pub_application, rederive_tier
from util import APPLICATION_STATUSES, LEVELS, apply_filters, paginate, sort_items

bp = Blueprint("applications", __name__)


def _get_application(application_id):
    a = store.applications.get(application_id)
    if a is None:
        raise not_found("Certification application not found")
    return a


@bp.route("/certification_applications", methods=["POST"])
def create_application():
    authenticate(["SustainabilityManager"])
    b = get_body()
    check_unknown(b, ["site_id", "level_requested", "reporting_period_id",
                      "expected_site_version"])
    site_id = f_str(b, "site_id")
    level = f_enum(b, "level_requested", LEVELS)
    period_id = f_str(b, "reporting_period_id")
    expected = f_int(b, "expected_site_version")

    site = store.sites.get(site_id)
    if site is None:
        raise not_found("Site not found")
    period = store.periods.get(period_id)
    if period is None:
        raise not_found("Scorecard period not found")

    # OCC: the only version-guarded write in the API.
    if expected != site["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_site_version does not match the site's version")

    # FK scope: the reporting period must belong to the applicant site.
    if period["site_id"] != site_id:
        raise ApiError(ERR_CROSS_SITE_REFERENCE, 422,
                       "reporting_period_id belongs to another site")

    # Supersede any existing DRAFT of the same site and level.
    for a in store.applications.values():
        if (a["site_id"] == site_id and a["level_requested"] == level
                and a["status"] == "DRAFT"):
            a["status"] = "WITHDRAWN"
            touch(a)

    rec = base_record({
        "site_id": site_id,
        "reporting_period_id": period_id,
        "level_requested": level,
        "status": "DRAFT",
        "submitted_by": None,
        "decided_by": None,
        "decided_at": None,
    })
    store.applications[rec["id"]] = rec
    touch(site)  # drafting increments the site's version by one
    return success_object(pub_application(rec), 201)


@bp.route("/certification_applications/<application_id>", methods=["GET"])
def get_application(application_id):
    authenticate(ALL_ROLES)
    return success_object(pub_application(_get_application(application_id)))


@bp.route("/certification_applications", methods=["GET"])
def list_applications():
    authenticate(ALL_ROLES)
    items = apply_filters(store.applications.values(), [
        ("site_id", "site_id", None),
        ("reporting_period_id", "reporting_period_id", None),
        ("status", "status", APPLICATION_STATUSES),
    ])
    page, meta = paginate(sort_items(items))
    return success_list([pub_application(a) for a in page], meta)


@bp.route("/certification_applications/<application_id>/submit", methods=["POST"])
def submit_application(application_id):
    uid, _ = authenticate(["SustainabilityManager"])
    no_input(get_body())
    a = _get_application(application_id)

    if a["status"] != "DRAFT":
        raise ApiError(ERR_APPLICATION_NOT_DRAFT, 409, "Application is not DRAFT")
    site = store.sites.get(a["site_id"])
    if site is not None and site["program_standing"] == "PROBATION":
        raise ApiError(ERR_STANDING_PROBATION, 409,
                       "Site program standing is PROBATION")
    period = store.periods.get(a["reporting_period_id"])
    if period is None or period["site_id"] != a["site_id"]:
        raise ApiError(ERR_CROSS_SITE_REFERENCE, 422,
                       "reporting_period_id belongs to another site")
    if period["status"] != "CLOSED":
        raise ApiError(ERR_PERIOD_NOT_CLOSED, 409,
                       "Reporting period is not CLOSED")

    a["status"] = "SUBMITTED"
    a["submitted_by"] = uid
    touch(a)
    return success_object(pub_application(a))


@bp.route("/certification_applications/<application_id>/start_review",
          methods=["POST"])
def start_review(application_id):
    authenticate(["CertificationOfficer"])
    no_input(get_body())
    a = _get_application(application_id)
    if a["status"] != "SUBMITTED":
        raise ApiError(ERR_APPLICATION_NOT_SUBMITTED, 409,
                       "Application is not SUBMITTED")
    a["status"] = "UNDER_REVIEW"
    touch(a)
    return success_object(pub_application(a))


@bp.route("/certification_applications/<application_id>/decide", methods=["POST"])
def decide_application(application_id):
    uid, _ = authenticate(["CertificationOfficer"])
    b = get_body()
    check_unknown(b, ["outcome", "notes"])
    outcome = f_enum(b, "outcome", ["APPROVED", "REJECTED"])
    f_str(b, "notes", required=False, nullable=True)

    a = _get_application(application_id)
    if a["status"] != "UNDER_REVIEW":
        raise ApiError(ERR_APPLICATION_NOT_IN_REVIEW, 409,
                       "Application is not UNDER_REVIEW")
    # Segregation of duties: the decider must differ from the submitter.
    if uid == a.get("submitted_by"):
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, 403,
                       "The submitter may not decide the application")

    if outcome == "APPROVED":
        period = store.periods.get(a["reporting_period_id"])
        measured = period["diversion_rate_certified_pct"] if period else 0.0
        threshold = CERT_THRESHOLDS[a["level_requested"]]
        if dec(measured) < threshold:
            raise ApiError(ERR_CERTIFICATION_THRESHOLD_NOT_MET, 422,
                           "Certified diversion rate is below the requested "
                           "level threshold")

    a["status"] = outcome
    a["decided_by"] = uid
    a["decided_at"] = store.clock_str
    touch(a)

    if outcome == "APPROVED":
        # Any prior APPROVED application of the site is superseded.
        for o in store.applications.values():
            if (o["id"] != a["id"] and o["site_id"] == a["site_id"]
                    and o["status"] == "APPROVED"):
                o["status"] = "SUPERSEDED"
                touch(o)
        site = store.sites.get(a["site_id"])
        if site is not None and site["certification_tier"] != a["level_requested"]:
            site["certification_tier"] = a["level_requested"]
            touch(site)
    return success_object(pub_application(a))


@bp.route("/certification_applications/<application_id>/revise", methods=["POST"])
def revise_application(application_id):
    authenticate(["SustainabilityManager"])
    no_input(get_body())
    a = _get_application(application_id)
    if a["status"] != "REJECTED":
        raise ApiError(ERR_APPLICATION_NOT_DRAFT, 409,
                       "Application is not REJECTED")
    a["status"] = "DRAFT"
    a["submitted_by"] = None
    a["decided_by"] = None
    a["decided_at"] = None
    touch(a)
    return success_object(pub_application(a))
