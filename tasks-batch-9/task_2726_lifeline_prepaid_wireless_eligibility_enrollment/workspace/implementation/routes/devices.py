"""Handset inventory, issuance under the reissue freeze, and returns."""
from flask import Blueprint

import db
import response
import validation as v
from errors import ApiError
from routes.common import (DEVICE_STATUSES, MODEL_TIERS, PROGRAM_ADMINISTRATOR,
                           PROVIDER_AGENT, RETURN_CONDITIONS, ROLES_ALL,
                           authenticate, get_device, get_enrollment, get_provider,
                           require_provider_owner)
from services import calc, derive

bp = Blueprint("devices", __name__)


@bp.post("/lifeline/providers/<provider_id>/devices")
def stock_device(provider_id):
    caller = authenticate((PROVIDER_AGENT, PROGRAM_ADMINISTRATOR))
    provider = get_provider(provider_id)

    body = v.get_body()
    imei = v.string_field(body, "imei", pattern=r"^\d{15}$", min_len=15, max_len=15)
    model_tier = v.enum_field(body, "model_tier", MODEL_TIERS)
    unit_cost_cents = v.int_field(body, "unit_cost_cents", minimum=0)

    require_provider_owner(caller, provider_id)

    if provider["status"] != "ACTIVE":
        raise ApiError("ERR_PROVIDER_NOT_ACTIVE",
                       "A suspended carrier cannot take delivery of stock")

    for existing in db.db.devices.values():
        if existing["imei"] == imei:
            raise ApiError("ERR_INVALID_REQUEST", "imei must be unique")

    row = db.base_row()
    row.update({
        "provider_id": provider_id,
        "imei": imei,
        "model_tier": model_tier,
        "unit_cost_cents": unit_cost_cents,
        "status": "IN_STOCK",
        "issued_enrollment_id": None,
        "issued_at": None,
        "returned_at": None,
        "return_condition": None,
    })
    db.db.devices[row["id"]] = row
    db.touch(provider)
    return response.ok(derive.device_json(row), 201)


@bp.get("/lifeline/devices/<device_id>")
def read_device(device_id):
    authenticate(ROLES_ALL)
    device = get_device(device_id)
    return response.ok(derive.device_json(device))


@bp.get("/lifeline/devices")
def list_devices():
    authenticate(ROLES_ALL)
    provider_id = response.filter_str("provider_id")
    issued_enrollment_id = response.filter_str("issued_enrollment_id")
    status = response.filter_enum("status", DEVICE_STATUSES)
    model_tier = response.filter_enum("model_tier", MODEL_TIERS)
    rows = list(db.db.devices.values())
    if model_tier is not None:
        rows = [r for r in rows if r["model_tier"] == model_tier]
    if provider_id is not None:
        rows = [r for r in rows if r["provider_id"] == provider_id]
    if issued_enrollment_id is not None:
        rows = [r for r in rows if r["issued_enrollment_id"] == issued_enrollment_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return response.paginate(db.by_created(rows), derive.device_json)


def _most_recently_issued(enrollment_id):
    issued = [d for d in derive.devices_of_enrollment(enrollment_id)
              if d["issued_at"] is not None]
    if not issued:
        return None
    return max(issued, key=lambda d: (d["issued_at"], d["_seq"]))


def _freeze_waived(enrollment):
    device = _most_recently_issued(enrollment["id"])
    if device is None:
        return False
    if device["status"] == "RECLAIM_PENDING":
        return True
    if (device["status"] in ("RETIRED", "LOST")
            and device["return_condition"] in ("DAMAGED", "LOST")):
        return True
    return False


def _holds_outstanding_handset(subscriber_id):
    enrollment_ids = set(e["id"] for e in derive.enrollments_of_subscriber(subscriber_id))
    for device in db.db.devices.values():
        if (device["status"] in ("ISSUED", "RECLAIM_PENDING")
                and device["issued_enrollment_id"] in enrollment_ids):
            return True
    return False


@bp.post("/lifeline/enrollments/<enrollment_id>/device-issuance")
def issue_device(enrollment_id):
    caller = authenticate((PROVIDER_AGENT,))
    enrollment = get_enrollment(enrollment_id)

    body = v.get_body()
    device_id = v.string_field(body, "device_id", required=False, min_len=1,
                               default=None)
    named = get_device(device_id) if device_id is not None else None

    require_provider_owner(caller, enrollment["provider_id"])

    now = db.now()
    if enrollment["benefit_status"] != "ACTIVE":
        raise ApiError("ERR_ENROLLMENT_NOT_ACTIVE", "The benefit is not active")
    if enrollment["device_status"] != "AWAITING_DEVICE":
        raise ApiError("ERR_DEVICE_ALREADY_ISSUED",
                       "The benefit is not awaiting a handset")

    last_issued = enrollment["last_device_issued_at"]
    if last_issued is not None:
        if last_issued <= now <= calc.device_freeze_end(last_issued):
            if not _freeze_waived(enrollment):
                raise ApiError("ERR_DEVICE_FREEZE_ACTIVE",
                               "The handset reissue freeze is active")

    if _holds_outstanding_handset(enrollment["subscriber_id"]):
        raise ApiError("ERR_SINGLE_DEVICE_PER_SUBSCRIBER",
                       "The applicant already holds an outstanding handset")

    if named is not None:
        if named["provider_id"] != enrollment["provider_id"]:
            raise ApiError("ERR_NO_DEVICE_IN_STOCK",
                           "The named handset is not this carrier's stock")
        if named["status"] != "IN_STOCK":
            raise ApiError("ERR_DEVICE_ALREADY_ISSUED",
                           "The named handset is not in stock")
        device = named
    else:
        pool = [d for d in derive.devices_of_provider(enrollment["provider_id"])
                if d["status"] == "IN_STOCK"]
        if not pool:
            raise ApiError("ERR_NO_DEVICE_IN_STOCK",
                           "The carrier holds no handset in stock")
        pool.sort(key=lambda d: (calc.device_tier_rank(d["model_tier"]),
                                 d["unit_cost_cents"], d["created_at"], d["_seq"]))
        device = pool[0]

    device["status"] = "ISSUED"
    device["issued_enrollment_id"] = enrollment["id"]
    device["issued_at"] = now
    db.touch(device)

    enrollment["device_status"] = "DEVICE_ISSUED"
    enrollment["last_device_issued_at"] = now
    enrollment["device_issuance_count"] = (enrollment["device_issuance_count"] or 0) + 1
    derive.recompute_risk(enrollment)
    db.touch(enrollment)

    provider = db.db.providers.get(enrollment["provider_id"])
    if provider is not None:
        db.touch(provider)

    return response.ok(derive.device_json(device))


@bp.post("/lifeline/devices/<device_id>/return")
def return_device(device_id):
    caller = authenticate((PROVIDER_AGENT, PROGRAM_ADMINISTRATOR))
    device = get_device(device_id)

    body = v.get_body()
    condition = v.enum_field(body, "return_condition", RETURN_CONDITIONS)

    require_provider_owner(caller, device["provider_id"])

    if device["status"] not in ("ISSUED", "RECLAIM_PENDING"):
        raise ApiError("ERR_DEVICE_NOT_ISSUED",
                       "Only a handset out with a subscriber can be returned")

    device["returned_at"] = db.now()
    device["return_condition"] = condition
    if condition == "GOOD":
        device["status"] = "IN_STOCK"
    elif condition == "DAMAGED":
        device["status"] = "RETIRED"
    else:
        device["status"] = "LOST"
    db.touch(device)

    enrollment = db.db.enrollments.get(device["issued_enrollment_id"])
    if enrollment is not None:
        enrollment["device_status"] = "AWAITING_DEVICE"
        derive.recompute_risk(enrollment)
        db.touch(enrollment)

    provider = db.db.providers.get(device["provider_id"])
    if provider is not None:
        db.touch(provider)

    return response.ok(derive.device_json(device))
