"""ReplacementCampaign and CampaignEnrollment endpoints."""
from datetime import timedelta

from flask import Blueprint, request

from db import db, stamp_new, touch, now_dt
from errors import (
    ApiError, ERR_NOT_FOUND, ERR_REFERENCED_ENTITY_NOT_FOUND, ERR_INVALID_REQUEST,
    ERR_INVALID_STATE_TRANSITION, ERR_CAMPAIGN_QUOTA_EXCEEDED,
    ERR_METER_NOT_ELIGIBLE_FOR_CAMPAIGN, ERR_METER_ALREADY_ENROLLED,
    ERR_EVIDENCE_PRESERVATION_HOLD,
)
from middleware import require_roles, ALL_ROLES, body, req_str, req_int
from response import success, list_response, created_sorted
from serializers import ser_campaign, ser_enrollment, campaign_counts
from services.cascades import evidence_hold_active
from util import fmt_date

bp = Blueprint("campaigns", __name__)


def get_campaign(cid):
    c = db.campaigns.get(cid)
    if not c:
        raise ApiError(ERR_NOT_FOUND, "ReplacementCampaign not found", 404)
    return c


@bp.route("/replacement-campaigns", methods=["POST"])
def create():
    require_roles("MeterOpsAdmin")
    data = body()
    name = req_str(data, "campaign_name")
    quota = req_int(data, "quota", minimum=1)
    rec = {"campaign_name": name, "quota": quota, "campaign_status": "DRAFT"}
    stamp_new(rec)
    db.campaigns[rec["id"]] = rec
    return success(ser_campaign(rec), code=201)


@bp.route("/replacement-campaigns", methods=["GET"])
def list_all():
    require_roles(*ALL_ROLES)
    items = list(db.campaigns.values())
    val = request.args.get("campaign_status")
    if val is not None:
        items = [c for c in items if c["campaign_status"] == val]
    return list_response([ser_campaign(c) for c in created_sorted(items)])


@bp.route("/replacement-campaigns/<cid>", methods=["GET"])
def get_one(cid):
    require_roles(*ALL_ROLES)
    return success(ser_campaign(get_campaign(cid)), code=200)


@bp.route("/replacement-campaigns/<cid>/open", methods=["POST"])
def open_campaign(cid):
    require_roles("MeterOpsAdmin")
    c = get_campaign(cid)
    if c["campaign_status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, "Campaign is not DRAFT", 409)
    c["campaign_status"] = "OPEN"
    touch(c)
    return success(ser_campaign(c), code=200)


@bp.route("/replacement-campaigns/<cid>/enroll", methods=["POST"])
def enroll(cid):
    require_roles("MeterOpsAdmin")
    data = body()
    meter_ids = data.get("meter_ids")
    if (
        not isinstance(meter_ids, list)
        or len(meter_ids) == 0
        or any(not isinstance(v, str) for v in meter_ids)
    ):
        raise ApiError(
            ERR_INVALID_REQUEST, "meter_ids must be a non-empty array of strings", 400
        )
    c = get_campaign(cid)
    for mid in meter_ids:
        if mid not in db.meters:
            raise ApiError(ERR_REFERENCED_ENTITY_NOT_FOUND, f"Meter {mid} not found", 404)
    if c["campaign_status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, "Campaign is not OPEN", 409)
    # evidence-preservation hold (priority 14) precedes the campaign checks
    for mid in meter_ids:
        if evidence_hold_active(db.meters[mid]):
            raise ApiError(
                ERR_EVIDENCE_PRESERVATION_HOLD,
                "Meter is under an evidence-preservation hold",
                409,
            )
    # pinned intra-group order: batch quota (atomic) -> eligibility -> already enrolled
    enrolled_count, _replaced, _withdrawn = campaign_counts(cid)
    if len(meter_ids) > c["quota"] - enrolled_count:
        raise ApiError(
            ERR_CAMPAIGN_QUOTA_EXCEEDED,
            "Enrollment batch exceeds the campaign's remaining quota",
            409,
        )
    for mid in meter_ids:
        if db.meters[mid]["endpoint_comms_status"] != "FAILED":
            raise ApiError(
                ERR_METER_NOT_ELIGIBLE_FOR_CAMPAIGN,
                "Meter's endpoint_comms_status is not FAILED",
                409,
            )
    seen = set()
    for mid in meter_ids:
        already = mid in seen or any(
            e["meter_id"] == mid
            and e["enrollment_status"] in ("ENROLLED", "WORK_ORDER_CREATED")
            and (lambda oc: oc is not None and oc["campaign_status"] == "OPEN")(
                db.campaigns.get(e["campaign_id"])
            )
            for e in db.enrollments.values()
        )
        if already:
            raise ApiError(
                ERR_METER_ALREADY_ENROLLED,
                "Meter is already enrolled in an OPEN campaign",
                409,
            )
        seen.add(mid)
    # all gates passed: create enrollments atomically, each immediately spawning
    # its ENDPOINT_SWAP work order (ENROLLED -> WORK_ORDER_CREATED)
    enrollment_date = now_dt().date()
    scheduled = fmt_date(enrollment_date + timedelta(days=7))
    created = []
    for mid in meter_ids:
        meter = db.meters[mid]
        enr = {
            "campaign_id": cid,
            "meter_id": mid,
            "enrollment_status": "ENROLLED",
            "work_order_id": None,
        }
        stamp_new(enr)
        db.enrollments[enr["id"]] = enr
        wo = {
            "work_order_type": "ENDPOINT_SWAP",
            "service_account_id": meter["installed_service_account_id"],
            "meter_id": mid,
            "route_stop_id": None,
            "investigation_id": None,
            "campaign_enrollment_id": enr["id"],
            "scheduled_date": scheduled,
            "work_shift": "FULL",
            "notes": None,
            "technician_id": None,
            "work_order_status": "OPEN",
            "new_meter_id": None,
            "old_final_read_value": None,
            "new_initial_read_value": None,
            "reread_value": None,
            "reread_at": None,
            "evidence_note": None,
            "completed_at": None,
        }
        stamp_new(wo)
        db.work_orders[wo["id"]] = wo
        enr["enrollment_status"] = "WORK_ORDER_CREATED"
        enr["work_order_id"] = wo["id"]
        touch(enr)
        created.append(enr)
    return success([ser_enrollment(e) for e in created], response_type="array", code=201)


@bp.route("/replacement-campaigns/<cid>/close", methods=["POST"])
def close_campaign(cid):
    require_roles("MeterOpsAdmin")
    c = get_campaign(cid)
    if c["campaign_status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, "Campaign is not OPEN", 409)
    c["campaign_status"] = "CLOSED"
    touch(c)
    for e in db.enrollments.values():
        if e["campaign_id"] != cid:
            continue
        if e["enrollment_status"] in ("ENROLLED", "WORK_ORDER_CREATED"):
            e["enrollment_status"] = "WITHDRAWN"
            touch(e)
            if e["work_order_id"]:
                wo = db.work_orders.get(e["work_order_id"])
                if wo and wo["work_order_status"] in ("OPEN", "DISPATCHED", "REWORK"):
                    wo["work_order_status"] = "CANCELLED"
                    touch(wo)
    return success(ser_campaign(c), code=200)


@bp.route("/campaign-enrollments", methods=["GET"])
def list_enrollments():
    require_roles(*ALL_ROLES)
    items = list(db.enrollments.values())
    for param in ("campaign_id", "meter_id", "enrollment_status", "work_order_id"):
        val = request.args.get(param)
        if val is not None:
            items = [e for e in items if e[param] == val]
    return list_response([ser_enrollment(e) for e in created_sorted(items)])


@bp.route("/campaign-enrollments/<eid>", methods=["GET"])
def get_enrollment(eid):
    require_roles(*ALL_ROLES)
    e = db.enrollments.get(eid)
    if not e:
        raise ApiError(ERR_NOT_FOUND, "CampaignEnrollment not found", 404)
    return success(ser_enrollment(e), code=200)
