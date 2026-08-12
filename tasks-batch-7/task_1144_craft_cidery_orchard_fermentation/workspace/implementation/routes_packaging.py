"""Packaging runs."""

from decimal import Decimal

from flask import Blueprint, g, request

import db
from errors import (
    ApiError,
    ERR_ABV_OUT_OF_TOLERANCE,
    ERR_BATCH_NOT_READY,
    ERR_INSUFFICIENT_VOLUME,
    ERR_LABEL_EXPIRED,
    ERR_LABEL_NOT_APPROVED,
    ERR_LICENSE_CAP_EXCEEDED,
    ERR_LICENSE_NOT_ACTIVE,
    ERR_PERMIT_EXPIRED,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_STALE_VERSION,
    invalid_state,
    not_found,
    validation,
)
from middleware import require_roles
from response import paginate, success_object
from services import (
    PACKAGE_FORMATS,
    UNIT_LITERS,
    _d,
    compute_abv,
    emit_event,
    expired,
    ser_packaging_run,
)

bp = Blueprint("packaging", __name__, url_prefix="/cidery")

RUN_READ = ("PackagingOperator", "ComplianceOfficer", "SalesRep", "PlatformAdmin")


def body():
    return request.get_json(silent=True) or {}


def _get_run(run_id):
    rec = db.store["packaging_runs"].get(run_id)
    if rec is None:
        raise not_found("packaging run")
    return rec


@bp.post("/packaging-runs")
@require_roles("PackagingOperator")
def create_packaging_run():
    b = body()
    # reference resolution first
    product = db.store["products"].get(b.get("product_id"))
    if product is None:
        raise not_found("product")
    batch = db.store["fermentation_batches"].get(b.get("fermentation_batch_id"))
    if batch is None:
        raise not_found("fermentation batch")
    label = db.store["label_approvals"].get(b.get("label_approval_id"))
    if label is None:
        raise not_found("label approval")
    license_ = db.store["licenses"].get(b.get("license_id"))
    if license_ is None:
        raise not_found("license")
    fmt = b.get("package_format")
    if fmt not in PACKAGE_FORMATS:
        raise validation(f"package_format must be one of {sorted(PACKAGE_FORMATS)}")
    volume = b.get("volume_liters")
    if not isinstance(volume, int) or volume <= 0:
        raise validation("volume_liters must be a positive integer")
    # licensing and labeling gates, in order
    if license_["status"] != "ACTIVE":
        raise ApiError(
            ERR_LICENSE_NOT_ACTIVE, "referenced license is not ACTIVE", 409
        )
    if label["status"] != "APPROVED":
        raise ApiError(
            ERR_LABEL_NOT_APPROVED, "label approval is not APPROVED", 409
        )
    if label["market"] != "FEDERAL_TTB" and expired(label):
        raise ApiError(ERR_LABEL_EXPIRED, "label approval is expired", 409)
    if expired(license_):
        raise ApiError(ERR_PERMIT_EXPIRED, "license permit is expired", 409)
    # batch checks
    if batch["status"] != "READY":
        raise ApiError(
            ERR_BATCH_NOT_READY, "fermentation batch is not READY", 409
        )
    if batch["volume_liters"] < volume:
        raise ApiError(
            ERR_INSUFFICIENT_VOLUME,
            "fermentation batch has insufficient volume_liters",
            409,
        )
    # annual volume cap: only a projection strictly greater than the cap fails
    cap = license_["annual_volume_cap_liters"] or 0
    if cap != 0 and license_["volume_used_liters"] + volume > cap:
        raise ApiError(
            ERR_LICENSE_CAP_EXCEEDED,
            "packaging would exceed the license annual volume cap",
            409,
        )
    unit = UNIT_LITERS[fmt]
    units = int(_d(volume) // unit)
    leftover = _d(volume) - _d(units) * unit
    rec = {
        "product_id": product["id"],
        "fermentation_batch_id": batch["id"],
        "package_format": fmt,
        "units_produced": units,
        "volume_liters": volume,
        "label_approval_id": label["id"],
        "license_id": license_["id"],
        "packaged_at": None,
        "status": "SCHEDULED",
        "_created_by_user_id": g.user_id,
    }
    db.stamp_new(rec)
    db.store["packaging_runs"][rec["id"]] = rec
    if leftover > Decimal("0.1"):
        emit_event(
            "PackagingRun", rec["id"], "PACKAGING_LEFTOVER",
            {},
            {
                "volume_liters": volume,
                "units_produced": units,
                "package_format": fmt,
                "leftover_liters": float(leftover),
            },
        )
    return success_object(ser_packaging_run(rec), 201)


@bp.get("/packaging-runs/<id>")
@require_roles(*RUN_READ)
def get_packaging_run(id):
    return success_object(ser_packaging_run(_get_run(id)))


@bp.get("/packaging-runs")
@require_roles(*RUN_READ)
def list_packaging_runs():
    items = list(db.store["packaging_runs"].values())
    for param in (
        "status", "product_id", "fermentation_batch_id",
        "label_approval_id", "license_id",
    ):
        val = request.args.get(param)
        if val is not None:
            items = [r for r in items if r.get(param) == val]
    return paginate(items, ser_packaging_run)


@bp.post("/packaging-runs/<id>/complete")
@require_roles("PackagingOperator")
def complete_packaging_run(id):
    run = _get_run(id)
    if run["status"] != "SCHEDULED":
        raise invalid_state("packaging run is not SCHEDULED")
    # segregation of duties: completer must differ from scheduler
    if g.user_id == run.get("_created_by_user_id"):
        raise ApiError(
            ERR_SEGREGATION_OF_DUTIES,
            "same X-User-ID cannot both create and complete a packaging run",
            403,
        )
    batch = db.store["fermentation_batches"].get(run["fermentation_batch_id"])
    product = db.store["products"].get(run["product_id"])
    license_ = db.store["licenses"].get(run["license_id"])
    # final ABV consistency check (equality to the tolerance passes)
    final_abv = compute_abv(
        batch["original_gravity_brix"], batch["current_gravity_brix"]
    )
    batch["abv_pct"] = final_abv
    tolerance = product["abv_tolerance_pct"]
    if abs(_d(final_abv) - _d(product["target_abv_pct"])) > _d(tolerance):
        raise ApiError(
            ERR_ABV_OUT_OF_TOLERANCE,
            "batch abv deviates from product target beyond tolerance",
            409,
        )
    # OCC guard runs last
    b = body()
    expected = b.get("expected_batch_version")
    if expected is not None and expected != batch["version"]:
        raise ApiError(
            ERR_STALE_VERSION,
            "expected_batch_version does not match current batch version",
            412,
        )
    run["status"] = "COMPLETED"
    run["packaged_at"] = db.now()
    db.bump(run)
    batch["volume_liters"] -= run["volume_liters"]
    db.bump(batch)
    if license_ is not None:
        # PRD 3.4: the tally "accumulates the packaged volume attributed to the
        # license during the calendar year" — it is scoped to the calendar year
        # of the draw, so a new year starts the tally from zero.
        now_year = db.now().year
        if license_.get("_volume_year") != now_year:
            license_["volume_used_liters"] = 0
            license_["_volume_year"] = now_year
        license_["volume_used_liters"] += run["volume_liters"]
        db.bump(license_)
    if batch["volume_liters"] == 0 and batch["status"] == "READY":
        batch["status"] = "PACKAGED"
        tank = db.store["tanks"].get(batch["tank_id"])
        if tank is not None:
            tank["status"] = "EMPTY"
            tank["current_batch_id"] = None
            db.bump(tank)
    return success_object(ser_packaging_run(run))


@bp.post("/packaging-runs/<id>/cancel")
@require_roles("PackagingOperator")
def cancel_packaging_run(id):
    run = _get_run(id)
    if run["status"] != "SCHEDULED":
        raise invalid_state("packaging run is not SCHEDULED")
    run["status"] = "CANCELLED"
    db.bump(run)
    return success_object(ser_packaging_run(run))
