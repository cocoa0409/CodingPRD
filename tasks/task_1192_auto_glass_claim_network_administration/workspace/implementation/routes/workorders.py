"""Work order lifecycle and calibration events."""

from datetime import timedelta

from flask import Blueprint, request

from db import store, base_fields, touch, sorted_created, parse_dt, now_dt, now_iso
from errors import (
    ApiError,
    ERR_WORK_ORDER_NOT_FOUND,
    ERR_CLAIM_NOT_FOUND,
    ERR_CALIBRATION_EVENT_NOT_FOUND,
    ERR_WORK_ORDER_NOT_OFFERED,
    ERR_WORK_ORDER_NOT_SCHEDULABLE,
    ERR_WORK_ORDER_NOT_SCHEDULED,
    ERR_WORK_ORDER_NOT_CANCELLABLE,
    ERR_RESOURCE_OWNERSHIP_MISMATCH,
    ERR_SHOP_SUSPENDED,
    ERR_STALE_WORK_ORDER_VERSION,
    ERR_INVALID_REQUEST,
    ERR_ADAS_CERTIFICATION_REQUIRED,
    ERR_SERVICE_MODE_CAPABILITY_MISMATCH,
    ERR_CALIBRATION_NOT_VERIFIED,
    ERR_COMPLETION_BEFORE_SCHEDULED_START,
    ERR_CALIBRATION_NOT_SCHEDULED,
    ERR_INSUFFICIENT_PERMISSIONS,
)
from middleware import (
    get_context,
    body_json,
    req_enum,
    req_str,
    opt_str,
    pagination_params,
    paginate,
    ALL_ROLES,
    ROLE_SHOP_OPERATOR,
    ROLE_CLAIM_ADJUSTER,
    ROLE_NETWORK_AUDITOR,
)
from response import success_object, success_list
from serialize import work_order_view, calibration_view
from services.capacity import check_bay_capacity, check_mobile_buffer, check_calibration_slot
from services.claims import bubble_up_claim
from services.fraud import apply_signal, RAPID_COMPLETION_POINTS

bp = Blueprint("workorders", __name__)

RAPID_COMPLETION_MINUTES = 45
SERVICE_MODES = {"MOBILE", "IN_SHOP"}
CALIBRATION_TYPES = {"STATIC", "DYNAMIC"}
CALIBRATION_OUTCOMES = {"VERIFIED", "FAILED", "WAIVED"}


def _get_wo(wid):
    wo = store.work_orders.get(wid)
    if wo is None:
        raise ApiError(ERR_WORK_ORDER_NOT_FOUND, 404, "Work order does not exist")
    return wo


def _check_wo_ownership(wo, uid):
    if wo["shop_id"] != uid:
        raise ApiError(
            ERR_RESOURCE_OWNERSHIP_MISMATCH,
            403,
            "ShopOperator may act only on work orders whose shop_id matches their identity",
        )


@bp.route("/work-orders/<wid>", methods=["GET"])
def get_work_order(wid):
    get_context(ALL_ROLES)
    return success_object(work_order_view(_get_wo(wid)))


@bp.route("/work-orders/<wid>/accept", methods=["POST"])
def accept_work_order(wid):
    uid, _role = get_context([ROLE_SHOP_OPERATOR])
    wo = _get_wo(wid)
    _check_wo_ownership(wo, uid)
    if wo["status"] != "OFFERED":
        raise ApiError(ERR_WORK_ORDER_NOT_OFFERED, 409, "accept requires WorkOrder OFFERED")
    shop = store.shops.get(wo["shop_id"])
    if shop is not None and shop["network_status"] != "ACTIVE":
        raise ApiError(ERR_SHOP_SUSPENDED, 409, "Shop network_status is SUSPENDED")
    wo["status"] = "ACCEPTED"
    touch(wo)
    return success_object(work_order_view(wo))


@bp.route("/work-orders/<wid>/decline", methods=["POST"])
def decline_work_order(wid):
    uid, _role = get_context([ROLE_SHOP_OPERATOR])
    wo = _get_wo(wid)
    _check_wo_ownership(wo, uid)
    if wo["status"] != "OFFERED":
        raise ApiError(ERR_WORK_ORDER_NOT_OFFERED, 409, "decline requires WorkOrder OFFERED")
    body_json(required=False)
    wo["status"] = "DECLINED"
    touch(wo)
    bubble_up_claim(wo["claim_id"])
    return success_object(work_order_view(wo))


@bp.route("/work-orders/<wid>/schedule", methods=["POST"])
def schedule_work_order(wid):
    uid, _role = get_context([ROLE_SHOP_OPERATOR])
    wo = _get_wo(wid)
    _check_wo_ownership(wo, uid)
    if wo["status"] not in ("ACCEPTED", "SCHEDULED", "NO_SHOW"):
        raise ApiError(
            ERR_WORK_ORDER_NOT_SCHEDULABLE,
            409,
            "schedule requires WorkOrder in {ACCEPTED, SCHEDULED, NO_SHOW}",
        )
    data = body_json(required=True)
    expected = data.get("expected_work_order_version")
    if expected is None or isinstance(expected, bool) or not isinstance(expected, int):
        raise ApiError(
            ERR_INVALID_REQUEST,
            400,
            "expected_work_order_version is required and must be an integer",
        )
    if expected != wo["version"]:
        raise ApiError(
            ERR_STALE_WORK_ORDER_VERSION,
            412,
            "expected_work_order_version does not match the work order's current version",
        )
    service_mode = req_enum(data, "service_mode", SERVICE_MODES)
    start_raw = req_str(data, "scheduled_start")
    end_raw = req_str(data, "scheduled_end")
    try:
        start = parse_dt(start_raw)
        end = parse_dt(end_raw)
    except ValueError:
        raise ApiError(ERR_INVALID_REQUEST, 400, "scheduled_start/scheduled_end must be ISO 8601 datetimes")
    if end <= start:
        raise ApiError(ERR_INVALID_REQUEST, 400, "scheduled_end must be strictly later than scheduled_start")

    claim = store.claims.get(wo["claim_id"])
    shop = store.shops.get(wo["shop_id"])
    if claim is not None and claim["requires_adas_calibration"] and shop is not None and not shop["adas_certified"]:
        raise ApiError(
            ERR_ADAS_CERTIFICATION_REQUIRED,
            422,
            "Claim requires ADAS calibration but the shop is not adas_certified",
        )
    if service_mode == "MOBILE" and shop is not None and not shop["mobile_capable"]:
        raise ApiError(
            ERR_SERVICE_MODE_CAPABILITY_MISMATCH,
            422,
            "service_mode MOBILE requires a mobile_capable shop",
        )
    if service_mode == "IN_SHOP":
        check_bay_capacity(shop, wo, start, end)
    else:
        check_mobile_buffer(shop, wo, start, end)

    wo["service_mode"] = service_mode
    wo["scheduled_start"] = start_raw
    wo["scheduled_end"] = end_raw
    wo["status"] = "SCHEDULED"
    touch(wo)
    return success_object(work_order_view(wo))


@bp.route("/work-orders/<wid>/mark-no-show", methods=["POST"])
def mark_no_show(wid):
    uid, _role = get_context([ROLE_SHOP_OPERATOR])
    wo = _get_wo(wid)
    _check_wo_ownership(wo, uid)
    if wo["status"] != "SCHEDULED":
        raise ApiError(ERR_WORK_ORDER_NOT_SCHEDULED, 409, "mark-no-show requires WorkOrder SCHEDULED")
    wo["status"] = "NO_SHOW"
    touch(wo)
    claim = store.claims.get(wo["claim_id"])
    if claim is not None:
        policyholder = store.policyholders.get(claim["policyholder_id"])
        if policyholder is not None:
            policyholder["no_show_count"] += 1
            touch(policyholder)
    return success_object(work_order_view(wo))


@bp.route("/work-orders/<wid>/complete", methods=["POST"])
def complete_work_order(wid):
    uid, _role = get_context([ROLE_SHOP_OPERATOR])
    wo = _get_wo(wid)
    _check_wo_ownership(wo, uid)
    if wo["status"] != "SCHEDULED":
        raise ApiError(ERR_WORK_ORDER_NOT_SCHEDULED, 409, "complete requires WorkOrder SCHEDULED")
    claim = store.claims.get(wo["claim_id"])
    if claim is not None and claim["requires_adas_calibration"]:
        verified = any(
            ev["work_order_id"] == wid and ev["status"] in ("VERIFIED", "WAIVED")
            for ev in store.calibrations.values()
        )
        if not verified:
            raise ApiError(
                ERR_CALIBRATION_NOT_VERIFIED,
                422,
                "Completing an ADAS work order requires a VERIFIED or WAIVED calibration event",
            )
    now = now_dt()
    scheduled_start = parse_dt(wo["scheduled_start"])
    if now < scheduled_start:
        raise ApiError(
            ERR_COMPLETION_BEFORE_SCHEDULED_START,
            422,
            "Logical clock has not reached scheduled_start",
        )
    wo["completed_at"] = now_iso()
    wo["_completed_dt"] = now
    wo["status"] = "COMPLETED"
    touch(wo)
    if claim is not None and claim["status"] == "WORK_AUTHORIZED":
        claim["status"] = "WORK_COMPLETED"
        touch(claim)
    if claim is not None:
        elapsed = now - scheduled_start
        if elapsed < timedelta(minutes=RAPID_COMPLETION_MINUTES) and claim["part_category"] == "WINDSHIELD":
            policyholder = store.policyholders.get(claim["policyholder_id"])
            if policyholder is not None:
                apply_signal(policyholder, claim["id"], "RAPID_COMPLETION", RAPID_COMPLETION_POINTS)
    if wo.get("warranty_claim_id"):
        wc = store.warranty_claims.get(wo["warranty_claim_id"])
        if wc is not None and wc["status"] == "APPROVED_REWORK":
            wc["status"] = "REWORK_COMPLETED"
            touch(wc)
    return success_object(work_order_view(wo))


@bp.route("/work-orders/<wid>/cancel", methods=["POST"])
def cancel_work_order(wid):
    get_context([ROLE_CLAIM_ADJUSTER])
    wo = _get_wo(wid)
    if wo["status"] not in ("OFFERED", "ACCEPTED", "SCHEDULED"):
        raise ApiError(
            ERR_WORK_ORDER_NOT_CANCELLABLE,
            409,
            "cancel requires WorkOrder in {OFFERED, ACCEPTED, SCHEDULED}",
        )
    body_json(required=False)
    wo["status"] = "CANCELLED"
    touch(wo)
    bubble_up_claim(wo["claim_id"])
    return success_object(work_order_view(wo))


# ---------------------------------------------------------- CalibrationEvent

@bp.route("/work-orders/<wid>/calibration-events", methods=["POST"])
def create_calibration_event(wid):
    uid, _role = get_context([ROLE_SHOP_OPERATOR])
    wo = _get_wo(wid)
    _check_wo_ownership(wo, uid)
    if wo["status"] not in ("ACCEPTED", "SCHEDULED"):
        raise ApiError(
            ERR_WORK_ORDER_NOT_SCHEDULABLE,
            409,
            "calibration-events require WorkOrder in {ACCEPTED, SCHEDULED}",
        )
    data = body_json(required=True)
    calibration_type = req_enum(data, "calibration_type", CALIBRATION_TYPES)
    start_raw = req_str(data, "scheduled_start")
    end_raw = req_str(data, "scheduled_end")
    try:
        start = parse_dt(start_raw)
        end = parse_dt(end_raw)
    except ValueError:
        raise ApiError(ERR_INVALID_REQUEST, 400, "scheduled_start/scheduled_end must be ISO 8601 datetimes")
    if end <= start:
        raise ApiError(ERR_INVALID_REQUEST, 400, "scheduled_end must be strictly later than scheduled_start")
    check_calibration_slot(wo["shop_id"], start, end)
    ev = base_fields()
    ev.update(
        {
            "work_order_id": wid,
            "calibration_type": calibration_type,
            "scheduled_start": start_raw,
            "scheduled_end": end_raw,
            "report_reference": None,
            "status": "SCHEDULED",
        }
    )
    store.calibrations[ev["id"]] = ev
    return success_object(calibration_view(ev), status=201)


@bp.route("/work-orders/<wid>/calibration-events", methods=["GET"])
def list_calibration_events(wid):
    get_context(ALL_ROLES)
    _get_wo(wid)
    limit, offset = pagination_params()
    items = sorted_created([e for e in store.calibrations.values() if e["work_order_id"] == wid])
    page, total = paginate(items, limit, offset)
    return success_list([calibration_view(e) for e in page], limit, offset, total)


@bp.route("/calibration-events/<eid>/verify", methods=["POST"])
def verify_calibration_event(eid):
    uid, role = get_context([ROLE_SHOP_OPERATOR, ROLE_NETWORK_AUDITOR])
    data = body_json(required=True)
    outcome = data.get("outcome")
    if outcome == "WAIVED" and role != ROLE_NETWORK_AUDITOR:
        raise ApiError(
            ERR_INSUFFICIENT_PERMISSIONS,
            403,
            "outcome=WAIVED requires role NetworkAuditor",
        )
    ev = store.calibrations.get(eid)
    if ev is None:
        raise ApiError(ERR_CALIBRATION_EVENT_NOT_FOUND, 404, "Calibration event does not exist")
    wo = store.work_orders.get(ev["work_order_id"])
    if role == ROLE_SHOP_OPERATOR:
        if wo is None or wo["shop_id"] != uid:
            raise ApiError(
                ERR_RESOURCE_OWNERSHIP_MISMATCH,
                403,
                "ShopOperator may act only on work orders whose shop_id matches their identity",
            )
    if ev["status"] != "SCHEDULED":
        raise ApiError(ERR_CALIBRATION_NOT_SCHEDULED, 409, "verify requires CalibrationEvent SCHEDULED")
    if not isinstance(outcome, str) or outcome not in CALIBRATION_OUTCOMES:
        raise ApiError(ERR_INVALID_REQUEST, 400, "outcome must be one of VERIFIED, FAILED, WAIVED")
    report_reference = opt_str(data, "report_reference", None)
    ev["status"] = outcome
    if report_reference is not None:
        ev["report_reference"] = report_reference
    touch(ev)
    return success_object(calibration_view(ev))
