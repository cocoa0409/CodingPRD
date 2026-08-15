"""Lots: booking, accept, cancel, release (PRD SS3.3, SS3.6)."""
from flask import g, request

from db import STORE
from errors import ApiError
from middleware import require_roles, ROLES
from response import success_object, success_list, paginate
from serializers import ser_lot
from services import new_common, touch, base_charge_cents, spec_of
from validators import get_body, req, as_str, as_int

from . import bp


def _get_or_404(table, rid):
    rec = STORE[table].get(rid)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Resource not found: %s" % rid)
    return rec


def _latest_pass_cycle(lot_id):
    passes = [c for c in STORE["oven_cycles"].values()
              if c["lot_id"] == lot_id and c["verdict"] == "PASS"]
    if not passes:
        return None
    return max(passes, key=lambda c: c["_seq"])


def _epoch_tests(lot_id):
    """QualityTests of the lot in the current cure epoch: recorded after the
    lot's latest PASS OvenCycle (all of them when no PASS cycle exists)."""
    latest = _latest_pass_cycle(lot_id)
    after_seq = latest["_seq"] if latest is not None else 0
    return [t for t in STORE["quality_tests"].values()
            if t["lot_id"] == lot_id and t["_seq"] > after_seq]


@bp.post("/ecoat/lots")
@require_roles("LineScheduler")
def create_lot():
    body = get_body()
    customer_id = as_str(req(body, "customer_id"), "customer_id")
    spec_id = as_str(req(body, "spec_id"), "spec_id")
    part_quantity = as_int(req(body, "part_quantity"), "part_quantity")
    if part_quantity <= 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "part_quantity must be greater than zero")
    if STORE["customers"].get(customer_id) is None:
        raise ApiError("ERR_NOT_FOUND", 404, "customer_id does not exist")
    if STORE["coating_specs"].get(spec_id) is None:
        raise ApiError("ERR_NOT_FOUND", 404, "spec_id does not exist")
    lot = new_common()
    lot.update({
        "customer_id": customer_id, "spec_id": spec_id,
        "part_quantity": part_quantity,
        "scrapped_quantity": 0, "passed_quantity": 0, "rework_count": 0,
        "status": "RECEIVED",
        "base_charge_cents": 0, "purge_alloc_cents": 0,
        "rework_charge_cents": 0, "total_charge_cents": 0,
    })
    STORE["lots"][lot["id"]] = lot
    return success_object(ser_lot(lot), 201)


@bp.get("/ecoat/lots/<lid>")
@require_roles(*ROLES)
def get_lot(lid):
    return success_object(ser_lot(_get_or_404("lots", lid)))


@bp.get("/ecoat/lots")
@require_roles(*ROLES)
def list_lots():
    items = list(STORE["lots"].values())
    customer_id = request.args.get("customer_id")
    spec_id = request.args.get("spec_id")
    status = request.args.get("status")
    if customer_id is not None:
        items = [l for l in items if l["customer_id"] == customer_id]
    if spec_id is not None:
        items = [l for l in items if l["spec_id"] == spec_id]
    if status is not None:
        items = [l for l in items if l["status"] == status]
    page, meta = paginate(items, ser_lot)
    return success_list(page, meta)


@bp.post("/ecoat/lots/<lid>/accept")
@require_roles("LineScheduler")
def accept_lot(lid):
    lot = _get_or_404("lots", lid)
    if lot["status"] != "RECEIVED":
        raise ApiError("ERR_INVALID_STATE", 409, "Lot accept requires status RECEIVED")
    spec = spec_of(lot)
    if spec is None or spec["status"] != "ACTIVE":
        raise ApiError("ERR_SPEC_NOT_ACTIVE", 409,
                       "Lot accept requires an ACTIVE coating spec")
    lot["base_charge_cents"] = base_charge_cents(
        lot["part_quantity"], spec["area_dm2_per_part"])
    lot["status"] = "QUEUED"
    touch(lot)
    return success_object(ser_lot(lot))


@bp.post("/ecoat/lots/<lid>/cancel")
@require_roles("LineScheduler")
def cancel_lot(lid):
    lot = _get_or_404("lots", lid)
    if lot["status"] not in ("RECEIVED", "QUEUED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a RECEIVED or QUEUED lot can be cancelled")
    lot["status"] = "CANCELLED"
    touch(lot)
    return success_object(ser_lot(lot))


@bp.post("/ecoat/lots/<lid>/release")
@require_roles("QualityManager")
def release_lot(lid):
    lot = STORE["lots"].get(lid)
    if lot is not None:
        # Segregation of duties (guard rung 2): the releasing QualityManager's
        # X-User-ID must differ from the recorder of every QualityTest of the
        # lot in the current cure epoch.
        epoch = _epoch_tests(lid)
        if any(t["recorded_by_user_id"] == g.user_id for t in epoch):
            raise ApiError(
                "ERR_SEGREGATION_OF_DUTIES", 403,
                "The releasing QualityManager recorded quality tests on this lot "
                "in the current cure epoch")
    if lot is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Resource not found: %s" % lid)
    if lot["status"] != "QC_PENDING":
        raise ApiError("ERR_INVALID_STATE", 409, "Lot release requires status QC_PENDING")
    epoch = _epoch_tests(lid)
    has_pass_adhesion = any(t["test_type"] == "ADHESION" and t["verdict"] == "PASS"
                            for t in epoch)
    has_pass_impact = any(t["test_type"] == "IMPACT" and t["verdict"] == "PASS"
                          for t in epoch)
    if not (has_pass_adhesion and has_pass_impact):
        raise ApiError("ERR_TESTS_INCOMPLETE", 409,
                       "Release requires a PASS adhesion and a PASS impact test "
                       "recorded after the latest PASS oven cycle")
    lot["passed_quantity"] = lot["part_quantity"] - lot["scrapped_quantity"]
    lot["total_charge_cents"] = (lot["base_charge_cents"] + lot["purge_alloc_cents"]
                                 + lot["rework_charge_cents"])
    lot["status"] = "RELEASED"
    touch(lot)
    return success_object(ser_lot(lot))
