"""Easement endpoints plus the amendment draft (PRD 3.8, 3.9)."""

from flask import Blueprint, request

from db import base_row, db, touch
from errors import ApiError
from middleware import authenticate
from response import created, listing, ok, pagination
from services import cascade, lookup, serialize
from validation import Payload, raw_body

bp = Blueprint("easements", __name__)

READ_ROLES = ("ProgramAdmin", "AcquisitionOfficer", "StewardshipMonitor", "Landowner")
CHILD_READ_ROLES = ("ProgramAdmin", "StewardshipMonitor", "Landowner")
EASEMENT_STATUSES = ("RECORDED", "AMENDED", "TERMINATED")
STEWARDSHIP_STATUSES = ("MONITORING_CURRENT", "MONITORING_DUE", "MONITORING_DELINQUENT")
COMPLIANCE_STATUSES = (
    "COMPLIANT",
    "VIOLATION_OPEN",
    "VIOLATION_CURED",
    "VIOLATION_ESCALATED",
)
VISIT_STATUSES = ("SCHEDULED", "COMPLETED", "CANCELLED")
VIOLATION_STATUSES = ("OPEN", "CURE_PLAN_ACCEPTED", "CURED", "ESCALATED")
VIOLATION_TYPES = (
    "IMPERVIOUS_EXCEEDANCE",
    "UNAUTHORIZED_SUBDIVISION",
    "PROHIBITED_USE",
    "EXCESS_DWELLING",
)
AMENDMENT_STATUSES = (
    "DRAFT",
    "UNDER_REVIEW",
    "SUSPENDED",
    "APPROVED",
    "REJECTED",
    "RESCINDED",
)
AMENDMENT_TYPES = (
    "IMPERVIOUS_INCREASE",
    "BOUNDARY_ADJUSTMENT",
    "RESIDENTIAL_RIGHT_RELOCATION",
)


def _enum_filter(name, values):
    raw = request.args.get(name)
    if raw is None:
        return None
    if raw not in values:
        raise ApiError("ERR_INVALID_REQUEST", "%s filter is not valid" % name)
    return raw


@bp.get("/easements/<easement_id>")
def read_easement(easement_id):
    authenticate(READ_ROLES)
    return ok(serialize.easement(lookup.get_easement(easement_id)))


@bp.get("/easements")
def list_easements():
    authenticate(READ_ROLES)
    limit, offset = pagination(request.args)
    status = _enum_filter("status", EASEMENT_STATUSES)
    compliance = _enum_filter("compliance_status", COMPLIANCE_STATUSES)
    stewardship = _enum_filter("stewardship_status", STEWARDSHIP_STATUSES)
    rows = list(db.easements.values())
    parcel_id = request.args.get("parcel_id")
    if parcel_id is not None:
        rows = [r for r in rows if r["parcel_id"] == parcel_id]
    application_id = request.args.get("application_id")
    if application_id is not None:
        rows = [r for r in rows if r["application_id"] == application_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if compliance is not None:
        rows = [r for r in rows if r["compliance_status"] == compliance]
    if stewardship is not None:
        rows = [r for r in rows if r["stewardship_status"] == stewardship]
    rows.sort(key=lambda r: (r["recorded_on"], r["created_at"], r["_seq"]))
    return listing(rows, limit, offset, serialize.easement)


@bp.post("/easements/<easement_id>/impervious-requests")
def request_impervious(easement_id):
    authenticate(("ProgramAdmin", "StewardshipMonitor"))
    easement = lookup.get_easement(easement_id)
    payload = Payload(raw_body(), ("added_impervious_sqft", "description"))
    added = payload.integer("added_impervious_sqft", minimum=1)
    payload.string("description", min_len=1, max_len=500)

    used = int(easement["impervious_used_sqft"] or 0)
    if used + added > int(easement["impervious_allowance_sqft"]):
        raise ApiError(
            "ERR_IMPERVIOUS_ALLOWANCE_EXCEEDED",
            "the request would push impervious_used_sqft above the allowance",
        )
    easement["impervious_used_sqft"] = used + added
    touch(easement)
    return ok(serialize.easement(easement))


@bp.get("/easements/<easement_id>/monitoring-visits")
def list_easement_visits(easement_id):
    authenticate(CHILD_READ_ROLES)
    easement = lookup.get_easement(easement_id)
    limit, offset = pagination(request.args)
    status = _enum_filter("status", VISIT_STATUSES)
    rows = lookup.visits_of(easement["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=lambda r: (r["window_start"], r["created_at"], r["_seq"]))
    return listing(rows, limit, offset, serialize.monitoring_visit)


@bp.get("/easements/<easement_id>/violations")
def list_easement_violations(easement_id):
    authenticate(CHILD_READ_ROLES)
    easement = lookup.get_easement(easement_id)
    limit, offset = pagination(request.args)
    status = _enum_filter("status", VIOLATION_STATUSES)
    violation_type = _enum_filter("violation_type", VIOLATION_TYPES)
    rows = lookup.violations_of(easement["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if violation_type is not None:
        rows = [r for r in rows if r["violation_type"] == violation_type]
    rows.sort(key=lambda r: (r["opened_on"], r["created_at"], r["_seq"]))
    return listing(rows, limit, offset, serialize.violation)


@bp.get("/easements/<easement_id>/amendments")
def list_easement_amendments(easement_id):
    authenticate(CHILD_READ_ROLES)
    easement = lookup.get_easement(easement_id)
    limit, offset = pagination(request.args)
    status = _enum_filter("status", AMENDMENT_STATUSES)
    amendment_type = _enum_filter("amendment_type", AMENDMENT_TYPES)
    rows = lookup.amendments_of(easement["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if amendment_type is not None:
        rows = [r for r in rows if r["amendment_type"] == amendment_type]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return listing(rows, limit, offset, serialize.amendment)


@bp.post("/easements/<easement_id>/amendments")
def draft_amendment(easement_id):
    authenticate(("ProgramAdmin",))
    easement = lookup.get_easement(easement_id)
    payload = Payload(
        raw_body(),
        (
            "expected_easement_version",
            "amendment_type",
            "net_conservation_benefit_cents",
            "requested_impervious_sqft",
            "residential_rights_delta",
        ),
    )
    expected = payload.integer("expected_easement_version", minimum=0)
    amendment_type = payload.enum("amendment_type", AMENDMENT_TYPES)
    benefit = payload.integer("net_conservation_benefit_cents", minimum=0)
    requested_impervious = payload.integer(
        "requested_impervious_sqft", required=False, default=None, minimum=1
    )
    rights_delta = payload.integer(
        "residential_rights_delta", required=False, default=0
    )

    if amendment_type == "IMPERVIOUS_INCREASE":
        if requested_impervious is None:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "requested_impervious_sqft is required on an IMPERVIOUS_INCREASE",
            )
    elif requested_impervious is not None:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "requested_impervious_sqft is only accepted on an IMPERVIOUS_INCREASE",
        )

    if amendment_type == "RESIDENTIAL_RIGHT_RELOCATION":
        if rights_delta >= 0:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "residential_rights_delta must be strictly negative on a "
                "RESIDENTIAL_RIGHT_RELOCATION",
            )
    elif rights_delta != 0:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "residential_rights_delta must be 0 for this amendment_type",
        )

    # rung 8 -- optimistic concurrency on the parent easement.
    if expected != easement["version"]:
        raise ApiError(
            "ERR_STALE_EASEMENT_VERSION",
            "expected_easement_version does not match Easement.version",
        )

    # rung 9 -- deed dimension.
    if easement["status"] not in ("RECORDED", "AMENDED"):
        raise ApiError(
            "ERR_INVALID_EASEMENT_STATE",
            "only a RECORDED or AMENDED easement can be amended",
        )

    # rung 15 -- the type-specific business ceilings.
    if amendment_type == "IMPERVIOUS_INCREASE" and requested_impervious <= int(
        easement["impervious_allowance_sqft"]
    ):
        raise ApiError(
            "ERR_IMPERVIOUS_ALLOWANCE_EXCEEDED",
            "requested_impervious_sqft must exceed the current allowance",
        )
    if (
        amendment_type == "RESIDENTIAL_RIGHT_RELOCATION"
        and int(easement["residential_rights_retained"]) + rights_delta < 0
    ):
        raise ApiError(
            "ERR_RESIDENTIAL_RIGHTS_OVERDRAWN",
            "the delta would drive residential_rights_retained below zero",
        )

    # rung 16 -- referential scope.
    parent_app = db.applications.get(easement["application_id"])
    if parent_app is not None and parent_app["parcel_id"] != easement["parcel_id"]:
        raise ApiError(
            "ERR_EASEMENT_SCOPE_MISMATCH",
            "the easement's parcel_id does not match its application's parcel_id",
        )

    for existing in lookup.amendments_of(easement["id"]):
        if existing["status"] == "DRAFT":
            existing["status"] = "RESCINDED"
            existing["rescission_reason"] = cascade.RESCISSION_SUPERSEDED
            touch(existing)

    row = base_row()
    row.update(
        {
            "easement_id": easement["id"],
            "amendment_type": amendment_type,
            "requested_impervious_sqft": requested_impervious,
            "residential_rights_delta": rights_delta,
            "net_conservation_benefit_cents": benefit,
            "status": "DRAFT",
            "suspended_reason": None,
            "decision_reason": None,
            "rescission_reason": None,
            "applied_rights_delta": 0,
            "applied_impervious_sqft": None,
        }
    )
    db.amendments[row["id"]] = row
    touch(easement)
    return created(serialize.amendment(row))
