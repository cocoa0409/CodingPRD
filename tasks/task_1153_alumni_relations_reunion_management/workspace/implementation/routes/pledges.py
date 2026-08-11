"""GiftPledge endpoints."""

from flask import Blueprint, request

import db
from errors import (
    err_amount_too_small, err_campaign_not_active, err_campaign_not_closed,
    err_invalid_state, err_not_found, err_referential, err_unauthorized,
)
from middleware import require_roles
from response import success_list, success_object
from services.calculations import (
    matching_credit, recompute_engagement, recompute_propensity,
)
from services.common import (
    apply_pagination, json_body, logical_ts, new_entity, pagination_args,
    req_int, req_str, touch,
)
from services.serializers import PLEDGE_FIELDS, serialize
from routes.campaigns import get_campaign_or_404

bp = Blueprint("pledges", __name__)

STAFF_OR_DIRECTOR = ("AlumniRelationsStaff", "AlumniRelationsDirector")
PLEDGE_CREATE = ("AlumniRelationsStaff", "AlumniRelationsDirector", "Alumni")
PLEDGE_READ = ("AlumniRelationsStaff", "AlumniRelationsDirector", "Alumni")
CAMPAIGN_PLEDGE_READ = ("AlumniRelationsStaff", "AlumniRelationsDirector", "ReunionChair")


def get_pledge_or_404(pid):
    p = db.pledges.get(pid)
    if p is None:
        raise err_not_found("GiftPledge not found")
    return p


@bp.route("/alumni/campaigns/<cid>/pledges", methods=["POST"])
@require_roles(*PLEDGE_CREATE)
def create_pledge(cid, _role, _user_id):
    campaign = get_campaign_or_404(cid)
    body = json_body(required=["alumni_id", "amount_cents"])
    alumni_id = req_str(body["alumni_id"], "alumni_id")
    amount = req_int(body["amount_cents"], "amount_cents")
    if _role == "Alumni" and alumni_id != _user_id:
        raise err_unauthorized("Acting user must be the pledgor")

    record = db.records.get(alumni_id)
    if record is None:
        raise err_referential("AlumniRecord not found")
    if record["status"] == "DECEASED":
        raise err_referential("Alumnus is DECEASED")
    if amount < 100:
        raise err_amount_too_small()
    if campaign["status"] != "ACTIVE":
        raise err_campaign_not_active()

    pledge = new_entity({
        "campaign_id": cid,
        "alumni_id": alumni_id,
        "amount_cents": amount,
        "pledge_date": logical_ts(),
        "matched_credit_cents": 0,
        "status": "PLEDGED",
    })
    db.pledges[pledge["id"]] = pledge
    campaign["pledged_total_cents"] += amount
    touch(campaign)
    return success_object(serialize(pledge, PLEDGE_FIELDS), status=201)


@bp.route("/alumni/campaigns/<cid>/pledges", methods=["GET"])
@require_roles(*CAMPAIGN_PLEDGE_READ)
def list_campaign_pledges(cid, _role, _user_id):
    get_campaign_or_404(cid)
    limit, offset = pagination_args()
    rows = [p for p in db.pledges.values() if p["campaign_id"] == cid]
    status = request.args.get("status")
    if status:
        rows = [p for p in rows if p["status"] == status]
    page, total = apply_pagination(rows, limit, offset)
    return success_list([serialize(p, PLEDGE_FIELDS) for p in page], limit, offset, total)


@bp.route("/alumni/pledges", methods=["GET"])
@require_roles(*PLEDGE_READ)
def list_pledges(_role, _user_id):
    limit, offset = pagination_args()
    rows = list(db.pledges.values())
    alumni_id = request.args.get("alumni_id")
    if alumni_id:
        rows = [p for p in rows if p["alumni_id"] == alumni_id]
    campaign_id = request.args.get("campaign_id")
    if campaign_id:
        rows = [p for p in rows if p["campaign_id"] == campaign_id]
    status = request.args.get("status")
    if status:
        rows = [p for p in rows if p["status"] == status]
    page, total = apply_pagination(rows, limit, offset)
    return success_list([serialize(p, PLEDGE_FIELDS) for p in page], limit, offset, total)


@bp.route("/alumni/pledges/<pid>", methods=["GET"])
@require_roles(*PLEDGE_READ)
def get_pledge(pid, _role, _user_id):
    return success_object(serialize(get_pledge_or_404(pid), PLEDGE_FIELDS))


@bp.route("/alumni/pledges/<pid>/fulfill", methods=["POST"])
@require_roles(*STAFF_OR_DIRECTOR)
def fulfill(pid, _role, _user_id):
    pledge = get_pledge_or_404(pid)
    if pledge["status"] != "PLEDGED":
        raise err_invalid_state("Pledge must be PLEDGED to fulfill")
    campaign = get_campaign_or_404(pledge["campaign_id"])
    if campaign["status"] != "ACTIVE":
        raise err_campaign_not_active()
    record = db.records.get(pledge["alumni_id"])
    if record is None:
        raise err_not_found("AlumniRecord not found")
    if record["status"] == "DECEASED":
        raise err_referential("Alumnus is DECEASED")

    credit = matching_credit(pledge["amount_cents"], campaign["matching_multiplier_bps"])
    pledge["status"] = "FULFILLED"
    pledge["matched_credit_cents"] = credit
    pledge["fulfilled_at_dt"] = db.logical_now()
    touch(pledge)

    campaign["fulfilled_total_cents"] += pledge["amount_cents"]
    campaign["matched_credit_cents"] += credit
    touch(campaign)

    record["lifetime_giving_cents"] += pledge["amount_cents"]
    touch(record)
    # pinned order: engagement_score first, then propensity reads the new score
    recompute_engagement(record["id"], also_propensity=True)
    return success_object(serialize(pledge, PLEDGE_FIELDS))


@bp.route("/alumni/pledges/<pid>/lapse", methods=["POST"])
@require_roles(*STAFF_OR_DIRECTOR)
def lapse(pid, _role, _user_id):
    pledge = get_pledge_or_404(pid)
    if pledge["status"] != "PLEDGED":
        raise err_invalid_state("Pledge must be PLEDGED to lapse")
    pledge["status"] = "LAPSED"
    touch(pledge)
    campaign = db.campaigns.get(pledge["campaign_id"])
    if campaign is not None:
        campaign["pledged_total_cents"] -= pledge["amount_cents"]
        touch(campaign)
    recompute_propensity(pledge["alumni_id"])
    return success_object(serialize(pledge, PLEDGE_FIELDS))


@bp.route("/alumni/pledges/<pid>/write-off", methods=["POST"])
@require_roles("AlumniRelationsDirector")
def write_off(pid, _role, _user_id):
    pledge = get_pledge_or_404(pid)
    if pledge["status"] != "PLEDGED":
        raise err_invalid_state("Pledge must be PLEDGED to write off")
    campaign = db.campaigns.get(pledge["campaign_id"])
    if campaign is None:
        raise err_not_found("GiftCampaign not found")
    if campaign["status"] != "CLOSED":
        raise err_campaign_not_closed()
    pledge["status"] = "WRITTEN_OFF"
    touch(pledge)
    campaign["pledged_total_cents"] -= pledge["amount_cents"]
    touch(campaign)
    return success_object(serialize(pledge, PLEDGE_FIELDS))
