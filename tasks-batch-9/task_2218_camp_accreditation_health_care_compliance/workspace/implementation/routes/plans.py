"""Written plans: filing, supersede and officer review."""

from flask import Blueprint

import clock
import db
import domain
import helpers
import response
import validators
from errors import api_error
from middleware import authenticate

bp = Blueprint("plans", __name__)


@bp.get("/accreditation/written-plans/<plan_id>")
def get_plan(plan_id):
    ident = authenticate(("CampDirector", "HealthCareStaff", "AccreditationOfficer"))
    plan = helpers.plan_or_404(plan_id)
    helpers.scope(ident, plan["camp_id"])
    return response.ok(helpers.public(plan))


@bp.get("/accreditation/written-plans")
def list_plans():
    authenticate(("CampDirector", "HealthCareStaff", "AccreditationOfficer"))
    return helpers.collection_response(db.written_plans, helpers.PLAN_FILTERS)


@bp.post("/accreditation/written-plans")
def file_plan():
    ident = authenticate(("CampDirector", "HealthCareStaff"))
    data = validators.body()
    camp_id = validators.require(data, "camp_id")
    if not isinstance(camp_id, str):
        raise api_error("ERR_INVALID_REQUEST", "Field 'camp_id' must be a string.")
    plan_type = validators.req_enum(data, "plan_type", domain.PLAN_TYPES)
    body_ref = validators.req_str(data, "body_ref", 1, 200)
    effective_date = validators.req_date(data, "effective_date")
    expires_at = validators.req_date(data, "expires_at")
    physician_reviewed = validators.opt_bool(data, "physician_reviewed", default=False)
    expected_camp_version = validators.req_int(data, "expected_camp_version", 0)

    camp = helpers.camp_or_404(camp_id)
    helpers.scope(ident, camp["id"])
    if expected_camp_version != camp["version"]:
        raise api_error(
            "ERR_STALE_CAMP_VERSION",
            "The camp has moved on since the version you pinned.",
        )
    if expires_at <= effective_date:
        raise api_error(
            "ERR_INCIDENT_OUTSIDE_REPORT_YEAR",
            "A plan's expires_at must be strictly after its effective_date.",
        )

    superseded = None
    for existing in domain.camp_plans(camp_id):
        if existing["plan_type"] == plan_type and existing["status"] != "SUPERSEDED":
            superseded = existing

    plan = db.common_fields()
    plan.update(
        {
            "camp_id": camp_id,
            "plan_type": plan_type,
            "body_ref": body_ref,
            "physician_reviewed": physician_reviewed,
            "effective_date": effective_date.isoformat(),
            "expires_at": expires_at.isoformat(),
            "status": "SUBMITTED",
            "supersedes_plan_id": superseded["id"] if superseded else None,
            "verified_at": None,
            "reviewer_user_id": None,
            "verification_note": None,
        }
    )
    db.written_plans[plan["id"]] = plan

    if superseded is not None:
        was_verified = superseded["status"] == "VERIFIED"
        superseded["status"] = "SUPERSEDED"
        db.touch(superseded)
        if was_verified:
            for evaluation in db.ordered(
                db.evaluations, lambda e: e["written_plan_id"] == superseded["id"]
            ):
                if evaluation["self_status"] == "VERIFIED":
                    evaluation["self_status"] = "REJECTED"
                    db.touch(evaluation)

    db.touch(camp)
    return response.created(helpers.public(plan))


@bp.post("/accreditation/written-plans/<plan_id>/review")
def review_plan(plan_id):
    ident = authenticate(("AccreditationOfficer",))
    data = validators.body()
    decision = validators.req_enum(data, "decision", ("VERIFY", "REJECT"))
    note = validators.opt_str(data, "verification_note", 0, 2000)

    plan = helpers.plan_or_404(plan_id)
    camp = db.camps.get(plan["camp_id"])

    if decision == "VERIFY":
        if plan["status"] not in ("SUBMITTED", "REVALIDATION_REQUIRED"):
            raise api_error(
                "ERR_INVALID_REQUEST",
                "A plan in %s may not be verified." % plan["status"],
            )
        if plan["status"] == "REVALIDATION_REQUIRED" and camp["compliance_posture"] == "FROZEN":
            raise api_error(
                "ERR_CAMP_POSTURE_FROZEN",
                "A plan may not be revalidated while the camp posture is FROZEN.",
            )
        if plan["plan_type"] == "HEALTH_CARE" and not plan["physician_reviewed"]:
            raise api_error(
                "ERR_PHYSICIAN_REVIEW_REQUIRED",
                "A health care plan requires physician review before verification.",
            )
        plan["status"] = "VERIFIED"
        plan["verified_at"] = clock.now_iso()
        plan["reviewer_user_id"] = ident.user_id
        if note is not None:
            plan["verification_note"] = note
        db.touch(plan)
    else:
        if plan["status"] != "SUBMITTED":
            raise api_error(
                "ERR_INVALID_REQUEST",
                "A plan in %s may not be rejected." % plan["status"],
            )
        plan["status"] = "REJECTED"
        plan["reviewer_user_id"] = ident.user_id
        if note is not None:
            plan["verification_note"] = note
        db.touch(plan)
        for evaluation in db.ordered(
            db.evaluations, lambda e: e["written_plan_id"] == plan["id"]
        ):
            if evaluation["self_status"] == "SUBMITTED":
                evaluation["self_status"] = "REJECTED"
                db.touch(evaluation)

    return response.ok(helpers.public(plan))
