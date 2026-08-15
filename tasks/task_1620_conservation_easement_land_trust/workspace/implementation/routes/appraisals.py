"""Appraisal endpoints."""
from flask import Blueprint, g, request

import db
import utils
from errors import ApiError
from middleware import ANY_ROLE, body, paginate, require_roles
from response import ok
from services import domain

bp = Blueprint("appraisals", __name__)


def get_appraisal_or_404(appraisal_id):
    r = db.appraisals.get(appraisal_id)
    if r is None:
        raise ApiError("ERR_APPRAISAL_NOT_FOUND", "Appraisal id does not exist.", 404)
    return r


@bp.route("/stewardship/appraisals", methods=["POST"])
@require_roles("StewardshipCoordinator")
def create_appraisal():
    b = body()
    easement_id = b.get("easement_id")
    if easement_id is not None and easement_id not in db.easements:
        raise ApiError("ERR_EASEMENT_NOT_FOUND", "Easement id does not exist.", 404)
    e = db.easements.get(easement_id)
    if e is not None and e["status"] != "RECORDED":
        raise ApiError("ERR_EASEMENT_NOT_RECORDED", "Child operational create requires a RECORDED easement.", 409)
    appraiser = b.get("appraiser_user_id")
    effective_on = utils.parse_date(b.get("effective_on"))
    gift_on = utils.parse_date(b.get("gift_on"))
    flag = b.get("contiguous_enhancement_applies")
    if (
        e is None
        or not isinstance(appraiser, str)
        or effective_on is None
        or gift_on is None
        or not isinstance(flag, bool)
    ):
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "easement_id, appraiser_user_id, effective_on, gift_on and contiguous_enhancement_applies are required.",
            400,
        )
    # 365-day engagement buffer per (appraiser, easement); exactly 365 days is allowed.
    for a in db.appraisals.values():
        if (
            a["appraiser_user_id"] == appraiser
            and a["easement_id"] == easement_id
            and a["status"] in ("ENGAGED", "DELIVERED")
            and abs((effective_on - a["effective_on"]).days) < 365
        ):
            raise ApiError(
                "ERR_APPRAISAL_ENGAGEMENT_OVERLAP",
                "The appraiser already holds an engagement on this easement within 365 days.",
                409,
            )
    now = utils.now_iso()
    r = {
        "id": utils.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "easement_id": easement_id,
        "appraiser_user_id": appraiser,
        "effective_on": effective_on,
        "gift_on": gift_on,
        "contiguous_enhancement_applies": flag,
        "before_value_cents": None,
        "after_value_cents": None,
        "enhancement_value_cents": None,
        "deductible_value_cents": None,
        "status": "ENGAGED",
    }
    db.appraisals[r["id"]] = r
    return ok(domain.appraisal_json(r), 201)


@bp.route("/stewardship/appraisals", methods=["GET"])
@require_roles(*ANY_ROLE)
def list_appraisals():
    filters = {}
    for key in ("easement_id", "appraiser_user_id", "status"):
        v = request.args.get(key)
        if v is not None:
            filters[key] = v
    return paginate(list(db.appraisals.values()), domain.appraisal_json, filters)


@bp.route("/stewardship/appraisals/<appraisalId>", methods=["GET"])
@require_roles(*ANY_ROLE)
def get_appraisal(appraisalId):
    return ok(domain.appraisal_json(get_appraisal_or_404(appraisalId)))


@bp.route("/stewardship/appraisals/<appraisalId>/deliver", methods=["POST"])
@require_roles("Appraiser")
def deliver_appraisal(appraisalId):
    r = get_appraisal_or_404(appraisalId)
    if r["status"] != "ENGAGED":
        raise ApiError("ERR_INVALID_APPRAISAL_STATE", "Deliver requires ENGAGED.", 409)
    if g.user_id != r["appraiser_user_id"]:
        raise ApiError("ERR_NOT_ENGAGED_APPRAISER", "Only the engaged appraiser may deliver.", 403)
    b = body()
    before = b.get("before_value_cents")
    after = b.get("after_value_cents")
    enhancement = b.get("enhancement_value_cents", 0)
    if (
        not utils.is_int(before)
        or before <= 0
        or not utils.is_int(after)
        or after < 0
        or not utils.is_int(enhancement)
        or enhancement < 0
    ):
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "before_value_cents must be > 0; after_value_cents and enhancement_value_cents must be >= 0.",
            400,
        )
    r["before_value_cents"] = before
    r["after_value_cents"] = after
    r["enhancement_value_cents"] = enhancement
    r["status"] = "DELIVERED"
    domain.bump(r)
    return ok(domain.appraisal_json(r))


@bp.route("/stewardship/appraisals/<appraisalId>/certify", methods=["POST"])
@require_roles("StewardshipCoordinator")
def certify_appraisal(appraisalId):
    r = get_appraisal_or_404(appraisalId)
    if r["status"] != "DELIVERED":
        raise ApiError("ERR_INVALID_APPRAISAL_STATE", "Certify requires DELIVERED.", 409)
    # Domain (priority 9): positive deduction under the selected variant.
    if r["contiguous_enhancement_applies"]:
        deductible = max(
            0,
            r["before_value_cents"] - r["after_value_cents"] - r["enhancement_value_cents"],
        )
        positive = (r["before_value_cents"] - r["after_value_cents"] - r["enhancement_value_cents"]) > 0
    else:
        deductible = r["before_value_cents"] - r["after_value_cents"]
        positive = deductible > 0
    if not positive:
        raise ApiError("ERR_NON_POSITIVE_DEDUCTION", "Computed deductible_value_cents must be > 0.", 422)
    # Temporal (priority 10): substantiation window, both boundaries inclusive.
    if r["effective_on"] < utils.add_days(r["gift_on"], -60) or utils.today() > utils.add_days(
        r["gift_on"], 240
    ):
        raise ApiError("ERR_SUBSTANTIATION_WINDOW_EXPIRED", "Outside the substantiation window.", 422)
    # Referential (priority 11): appraiser independence from the baseline preparer.
    baseline = next(
        (x for x in db.baseline_reports.values() if x["easement_id"] == r["easement_id"]), None
    )
    if baseline is not None and r["appraiser_user_id"] == baseline["prepared_by_user_id"]:
        raise ApiError(
            "ERR_APPRAISER_CONFLICT",
            "The appraiser may not have prepared the easement's baseline report.",
            422,
        )
    r["deductible_value_cents"] = deductible
    r["status"] = "CERTIFIED"
    domain.bump(r)
    return ok(domain.appraisal_json(r))


@bp.route("/stewardship/appraisals/<appraisalId>/withdraw", methods=["POST"])
@require_roles("StewardshipCoordinator")
def withdraw_appraisal(appraisalId):
    r = get_appraisal_or_404(appraisalId)
    if r["status"] not in ("ENGAGED", "DELIVERED"):
        raise ApiError("ERR_INVALID_APPRAISAL_STATE", "Withdraw requires ENGAGED or DELIVERED.", 409)
    r["status"] = "WITHDRAWN"
    domain.bump(r)
    return ok(domain.appraisal_json(r))
