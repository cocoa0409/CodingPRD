"""DeviceLot and DeviceUsage endpoints."""
from flask import Blueprint, request

from db import STORE, logical_now
from errors import (
    ApiError,
    ERR_CASE_INVALID_STATE,
    ERR_CASE_NOT_FOUND,
    ERR_DEVICE_EXPIRED,
    ERR_INSUFFICIENT_DEVICE_STOCK,
    ERR_INVALID_REQUEST,
    ERR_LOT_NOT_FOUND,
    ERR_STALE_LOT_VERSION,
    ERR_USAGE_INVALID_STATE,
    ERR_USAGE_NOT_FOUND,
)
from helpers import (
    DEVICE_TYPES,
    OWNERSHIPS,
    get_payload,
    is_int_valued,
    new_id,
    paginate,
    req_dt,
    req_enum,
    req_int,
    req_str,
)
from middleware import ALL_ROLES, require_roles
from response import success
from services import (
    lot_out,
    new_entity,
    recompute_lot,
    touch,
    usage_out,
)

bp = Blueprint("devices", __name__)


def _get_lot_or_404(lot_id):
    lot = STORE["lots"].get(lot_id)
    if lot is None:
        raise ApiError(ERR_LOT_NOT_FOUND, "No DeviceLot with the given id", 404)
    return lot


def _get_usage_or_404(usage_id):
    usage = STORE["usages"].get(usage_id)
    if usage is None:
        raise ApiError(ERR_USAGE_NOT_FOUND, "No DeviceUsage with the given id", 404)
    return usage


# ---------------------------------------------------------------------------
# DeviceLot
# ---------------------------------------------------------------------------

@bp.route("/cath-lab/device-lots", methods=["POST"])
@require_roles("CathLabTechnologist")
def create_lot():
    data = get_payload()
    device_type = req_enum(data, "device_type", DEVICE_TYPES)
    manufacturer = req_str(data, "manufacturer")
    model_number = req_str(data, "model_number")
    lot_number = req_str(data, "lot_number")
    ownership = req_enum(data, "ownership", OWNERSHIPS)
    quantity_on_hand = req_int(data, "quantity_on_hand", ge=0)
    reorder_threshold = req_int(data, "reorder_threshold", ge=0)
    expiration_date = req_dt(data, "expiration_date")
    lot = new_entity()
    lot["id"] = new_id()
    lot.update(
        {
            "device_type": device_type,
            "manufacturer": manufacturer,
            "model_number": model_number,
            "lot_number": lot_number,
            "ownership": ownership,
            "quantity_on_hand": quantity_on_hand,
            "allocated_units": 0,
            "available_units": quantity_on_hand,
            "reorder_threshold": reorder_threshold,
            "expiration_date": expiration_date,
            "status": "ACTIVE",
        }
    )
    STORE["lots"][lot["id"]] = lot
    recompute_lot(lot, bump_version=False)
    return success(lot_out(lot), 201)


@bp.route("/cath-lab/device-lots", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_lots():
    device_type = request.args.get("device_type")
    status = request.args.get("status")
    ownership = request.args.get("ownership")
    items = []
    for lot in STORE["lots"].values():
        if device_type is not None and lot["device_type"] != device_type:
            continue
        if status is not None and lot["status"] != status:
            continue
        if ownership is not None and lot["ownership"] != ownership:
            continue
        items.append(lot)
    items.sort(key=lambda l: l["_seq"])
    page, pg = paginate(items)
    return success([lot_out(l) for l in page], 200, is_list=True, pagination=pg)


@bp.route("/cath-lab/device-lots/<lot_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_lot(lot_id):
    return success(lot_out(_get_lot_or_404(lot_id)), 200)


@bp.route("/cath-lab/device-lots/<lot_id>/restock", methods=["POST"])
@require_roles("CathLabTechnologist")
def restock_lot(lot_id):
    lot = _get_lot_or_404(lot_id)
    data = get_payload()
    quantity = req_int(data, "quantity", ge=1)
    expected_lot_version = data.get("expected_lot_version")
    if not is_int_valued(expected_lot_version):
        raise ApiError(
            ERR_INVALID_REQUEST,
            "expected_lot_version is required and must be a whole number",
            400,
        )
    # Priority 10: OCC on the lot version.
    if int(expected_lot_version) != lot["version"]:
        raise ApiError(
            ERR_STALE_LOT_VERSION,
            "expected_lot_version does not match the lot's current version",
            412,
        )
    lot["quantity_on_hand"] += quantity
    recompute_lot(lot)  # bumps version and refreshes updated_at
    return success(lot_out(lot), 200)


@bp.route("/cath-lab/device-lots/<lot_id>/usages", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_lot_usages(lot_id):
    _get_lot_or_404(lot_id)
    items = [u for u in STORE["usages"].values() if u["lot_id"] == lot_id]
    items.sort(key=lambda u: u["_seq"])
    page, pg = paginate(items)
    return success([usage_out(u) for u in page], 200, is_list=True, pagination=pg)


# ---------------------------------------------------------------------------
# DeviceUsage
# ---------------------------------------------------------------------------

@bp.route("/cath-lab/cases/<case_id>/device-usages", methods=["POST"])
@require_roles("CathLabTechnologist")
def create_usage(case_id):
    case = STORE["cases"].get(case_id)
    if case is None:
        raise ApiError(ERR_CASE_NOT_FOUND, "No CathCase with the given id", 404)
    data = get_payload()
    # Priority 3: body FK existence.
    lot_ref = data.get("lot_id")
    lot = None
    if isinstance(lot_ref, str):
        lot = STORE["lots"].get(lot_ref)
        if lot is None:
            raise ApiError(ERR_LOT_NOT_FOUND, "No DeviceLot with the given lot_id", 404)
    # Priority 4: shape.
    lot_id = req_str(data, "lot_id")
    quantity = req_int(data, "quantity", ge=1)
    # Priority 5: case state gate.
    if case["status"] not in ("SCHEDULED", "IN_PROGRESS"):
        raise ApiError(
            ERR_CASE_INVALID_STATE,
            "Device units may only be reserved for a SCHEDULED or IN_PROGRESS case",
            409,
        )
    # Priority 7: expiry — the current logical date must not fall strictly
    # after the lot's expiration date (the expiration date itself is allowed).
    if logical_now().date() > lot["expiration_date"].date():
        raise ApiError(ERR_DEVICE_EXPIRED, "Device lot is expired", 422)
    # Priority 9: stock (a request equal to available_units is allowed).
    if lot["available_units"] < quantity:
        raise ApiError(
            ERR_INSUFFICIENT_DEVICE_STOCK,
            "available_units is below the requested quantity",
            409,
        )
    usage = new_entity()
    usage["id"] = new_id()
    usage.update(
        {
            "case_id": case_id,
            "lot_id": lot_id,
            "quantity": quantity,
            "status": "RESERVED",
        }
    )
    STORE["usages"][usage["id"]] = usage
    recompute_lot(lot)  # allocated_units += quantity; status recomputed
    return success(usage_out(usage), 201)


@bp.route("/cath-lab/cases/<case_id>/device-usages", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_case_usages(case_id):
    case = STORE["cases"].get(case_id)
    if case is None:
        raise ApiError(ERR_CASE_NOT_FOUND, "No CathCase with the given id", 404)
    items = [u for u in STORE["usages"].values() if u["case_id"] == case_id]
    items.sort(key=lambda u: u["_seq"])
    page, pg = paginate(items)
    return success([usage_out(u) for u in page], 200, is_list=True, pagination=pg)


@bp.route("/cath-lab/device-usages/<usage_id>/implant", methods=["POST"])
@require_roles("CathLabTechnologist")
def implant_usage(usage_id):
    usage = _get_usage_or_404(usage_id)
    case = STORE["cases"].get(usage["case_id"])
    if case is None or case["status"] != "IN_PROGRESS":
        raise ApiError(
            ERR_CASE_INVALID_STATE,
            "Implantation requires the parent case to be IN_PROGRESS",
            409,
        )
    if usage["status"] != "RESERVED":
        raise ApiError(
            ERR_USAGE_INVALID_STATE,
            "Only a RESERVED usage can be implanted",
            409,
        )
    usage["status"] = "IMPLANTED"
    touch(usage)
    lot = STORE["lots"][usage["lot_id"]]
    lot["quantity_on_hand"] -= usage["quantity"]
    recompute_lot(lot)  # allocated_units -= quantity; status recomputed
    return success(usage_out(usage), 200)


@bp.route("/cath-lab/device-usages/<usage_id>/release", methods=["POST"])
@require_roles("CathLabTechnologist")
def release_usage(usage_id):
    usage = _get_usage_or_404(usage_id)
    if usage["status"] != "RESERVED":
        raise ApiError(
            ERR_USAGE_INVALID_STATE,
            "Only a RESERVED usage can be released",
            409,
        )
    usage["status"] = "RELEASED"
    touch(usage)
    recompute_lot(STORE["lots"][usage["lot_id"]])
    return success(usage_out(usage), 200)
