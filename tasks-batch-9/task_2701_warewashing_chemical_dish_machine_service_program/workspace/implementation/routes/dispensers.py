"""Dispensers plus the flat reads of the two immutable evidence tables."""

from flask import Blueprint

import db
import middleware
import response
from errors import ApiError
from middleware import (
    ROLE_ACCOUNT_MANAGER, ROLE_PLATFORM_ADMIN, ROLE_QUALITY_AUDITOR,
    ROLE_SERVICE_TECHNICIAN,
)
from routes import common
from services import calc, derive

bp = Blueprint("dispensers", __name__)

DISPENSER_STATUSES = ("ACTIVE", "LOCKED_OUT", "REMOVED")


@bp.route("/dispensers", methods=["POST"])
def create_dispenser():
    middleware.require_roles(ROLE_SERVICE_TECHNICIAN)
    body = middleware.body_object()
    placement_id = middleware.f_str(body, "placement_id", required=True)
    product_id = middleware.f_str(body, "product_id", required=True)
    dose = middleware.f_num(
        body, "calibrated_dose_ml_per_rack", required=True, gt=0
    )

    placement = middleware.must_reference(
        "machine_placements", placement_id, "placement_id"
    )
    middleware.must_reference("chemical_products", product_id, "product_id")

    if placement["placement_status"] != "INSTALLED":
        raise ApiError(
            "ERR_PLACEMENT_NOT_INSTALLED",
            "The placement is %s, not INSTALLED"
            % placement["placement_status"],
        )

    agreement = db.get("service_agreements", placement["agreement_id"])
    covered = agreement["covered_product_ids"] if agreement else []
    if product_id not in covered:
        raise ApiError(
            "ERR_PRODUCT_NOT_ON_AGREEMENT",
            "The product is not covered by the placement's agreement",
        )

    for existing in derive.dispensers_of_placement(placement_id):
        if (existing["product_id"] == product_id
                and existing["dispenser_status"] in ("ACTIVE", "LOCKED_OUT")):
            raise ApiError(
                "ERR_DUPLICATE_DISPENSER_PRODUCT",
                "The placement already meters this product",
            )

    row = db.insert("dispensers", {
        "placement_id": placement_id,
        "product_id": product_id,
        "calibrated_dose_ml_per_rack": dose,
        "dispenser_status": "ACTIVE",
        "dose_effective_at": db.now(),
        "prior_dose_ml_per_rack": None,
        "last_calibrated_at": None,
        "last_drift_pct": None,
        "lockout_reason": None,
        "_initial_dose": dose,
    })
    row["dose_effective_at"] = row["created_at"]
    return response.created(response.serialize(row))


@bp.route("/dispensers/<dispenser_id>", methods=["GET"])
def read_dispenser(dispenser_id):
    middleware.require_roles(
        ROLE_SERVICE_TECHNICIAN, ROLE_ACCOUNT_MANAGER, ROLE_QUALITY_AUDITOR
    )
    row = middleware.must_exist("dispensers", dispenser_id, "Dispenser")
    return response.ok(response.serialize(row))


@bp.route("/dispensers", methods=["GET"])
def list_dispensers():
    middleware.require_roles(
        ROLE_SERVICE_TECHNICIAN, ROLE_QUALITY_AUDITOR, ROLE_ACCOUNT_MANAGER
    )
    limit, offset = middleware.pagination()
    rows = common.apply_filters(db.rows("dispensers"), (
        ("placement_id", "placement_id"),
        ("product_id", "product_id"),
        ("dispenser_status", "dispenser_status"),
        ("status", "dispenser_status"),
    ))
    return common.listing(rows, limit, offset)


# --------------------------------------------------------------------------
# calibration records (read only; the write lives under the visit)
# --------------------------------------------------------------------------

@bp.route("/calibration-records/<record_id>", methods=["GET"])
def read_record(record_id):
    middleware.require_roles(
        ROLE_SERVICE_TECHNICIAN, ROLE_QUALITY_AUDITOR, ROLE_ACCOUNT_MANAGER
    )
    row = middleware.must_exist(
        "calibration_records", record_id, "CalibrationRecord"
    )
    return response.ok(response.serialize(row))


@bp.route("/calibration-records", methods=["GET"])
def list_records():
    middleware.require_roles(
        ROLE_SERVICE_TECHNICIAN, ROLE_QUALITY_AUDITOR, ROLE_ACCOUNT_MANAGER
    )
    limit, offset = middleware.pagination()
    rows = common.apply_filters(db.rows("calibration_records"), (
        ("visit_id", "visit_id"),
        ("dispenser_id", "dispenser_id"),
        ("applied", "applied"),
        ("calibration_verdict", "calibration_verdict"),
        ("verdict", "calibration_verdict"),
        ("efficacy_result", "efficacy_result"),
    ))
    return common.listing(rows, limit, offset)


# --------------------------------------------------------------------------
# telemetry readings (read only)
# --------------------------------------------------------------------------

@bp.route("/telemetry-readings/<reading_id>", methods=["GET"])
def read_reading(reading_id):
    middleware.require_roles(
        ROLE_PLATFORM_ADMIN, ROLE_SERVICE_TECHNICIAN, ROLE_QUALITY_AUDITOR
    )
    row = middleware.must_exist(
        "telemetry_readings", reading_id, "TelemetryReading"
    )
    return response.ok(response.serialize(row))


@bp.route("/telemetry-readings", methods=["GET"])
def list_readings():
    middleware.require_roles(
        ROLE_PLATFORM_ADMIN, ROLE_SERVICE_TECHNICIAN, ROLE_QUALITY_AUDITOR
    )
    limit, offset = middleware.pagination()
    rows = common.apply_filters(db.rows("telemetry_readings"), (
        ("placement_id", "placement_id"),
        ("source", "source"),
    ))
    rows = sorted(rows, key=lambda r: (r["reading_at"], r["created_at"], r["_seq"]))
    return common.listing(rows, limit, offset)


# --------------------------------------------------------------------------
# telemetry alerts
# --------------------------------------------------------------------------

@bp.route("/telemetry-alerts/<alert_id>", methods=["GET"])
def read_alert(alert_id):
    middleware.require_roles(
        ROLE_SERVICE_TECHNICIAN, ROLE_QUALITY_AUDITOR, ROLE_ACCOUNT_MANAGER
    )
    row = middleware.must_exist("telemetry_alerts", alert_id, "TelemetryAlert")
    return response.ok(response.serialize(row))


@bp.route("/telemetry-alerts", methods=["GET"])
def list_alerts():
    middleware.require_roles(
        ROLE_SERVICE_TECHNICIAN, ROLE_QUALITY_AUDITOR, ROLE_ACCOUNT_MANAGER
    )
    limit, offset = middleware.pagination()
    rows = common.apply_filters(db.rows("telemetry_alerts"), (
        ("placement_id", "placement_id"),
        ("triggering_reading_id", "triggering_reading_id"),
        ("alert_type", "alert_type"),
        ("severity", "severity"),
        ("status", "status"),
    ))
    return common.listing(rows, limit, offset)


@bp.route("/telemetry-alerts/<alert_id>/acknowledge", methods=["POST"])
def acknowledge_alert(alert_id):
    user_id, _role = middleware.require_roles(ROLE_SERVICE_TECHNICIAN)
    middleware.body_object()
    alert = middleware.must_exist(
        "telemetry_alerts", alert_id, "TelemetryAlert"
    )
    if alert["status"] != "OPEN":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "The alert is %s, not OPEN" % alert["status"],
        )
    alert["status"] = "ACKNOWLEDGED"
    alert["acknowledged_by_user_id"] = user_id
    db.mark(alert)
    return response.ok(response.serialize(alert))
