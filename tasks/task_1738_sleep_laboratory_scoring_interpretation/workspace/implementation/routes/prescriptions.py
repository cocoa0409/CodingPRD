"""Therapy prescriptions (PRD 3.7)."""
from decimal import Decimal

from flask import Blueprint

from db import db
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_STALE_VERSION,
    ERR_REPORT_INVALID_STATE,
    ERR_THERAPY_NOT_INDICATED,
    ERR_RX_DEVICE_FIELDS_INVALID,
    ERR_NOT_REPORT_AUTHOR,
    ERR_RX_INVALID_STATE,
)
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response, public, query_filters
from services.calculations import DME_TERMINAL
from services.core import new_record, touch
from util import CLOCK, to_decimal
from validate import get_body, req_str, req_enum, req_int, opt_bool, require_path_resource, require_body_ref

bp = Blueprint("prescriptions", __name__)

DEVICE_TYPES = {"CPAP", "APAP", "BIPAP"}
MASK_TYPES = {"NASAL", "FULL_FACE", "NASAL_PILLOWS"}


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _on_half_step(v) -> bool:
    d = to_decimal(v)
    return (d * 2) == (d * 2).to_integral_value()


def _validate_device_fields(body, device_type):
    """Device-specific pressure field sets (ERR_RX_DEVICE_FIELDS_INVALID)."""
    def invalid(msg):
        raise_error(ERR_RX_DEVICE_FIELDS_INVALID, msg)

    if device_type == "CPAP":
        v = body.get("cpap_pressure_cm")
        if v is None or not _is_num(v):
            invalid("CPAP requires cpap_pressure_cm")
        d = to_decimal(v)
        if d < Decimal("4.0") or d > Decimal("20.0") or not _on_half_step(v):
            invalid("cpap_pressure_cm must be within 4.0..20.0 in 0.5 steps")
    elif device_type == "APAP":
        lo = body.get("apap_min_cm")
        hi = body.get("apap_max_cm")
        if lo is None or hi is None or not _is_num(lo) or not _is_num(hi):
            invalid("APAP requires apap_min_cm and apap_max_cm")
        dlo, dhi = to_decimal(lo), to_decimal(hi)
        if (dlo < Decimal("4.0") or dhi > Decimal("20.0") or not dlo < dhi
                or not _on_half_step(lo) or not _on_half_step(hi)):
            invalid("APAP requires 4.0 <= apap_min_cm < apap_max_cm <= 20.0 in 0.5 steps")
    else:  # BIPAP
        epap = body.get("bipap_epap_cm")
        ipap = body.get("bipap_ipap_cm")
        if epap is None or ipap is None or not _is_num(epap) or not _is_num(ipap):
            invalid("BIPAP requires bipap_epap_cm and bipap_ipap_cm")
        depap, dipap = to_decimal(epap), to_decimal(ipap)
        if (depap < Decimal("4.0") or dipap > Decimal("25.0") or not depap < dipap
                or not _on_half_step(epap) or not _on_half_step(ipap)):
            invalid("BIPAP requires 4.0 <= bipap_epap_cm < bipap_ipap_cm <= 25.0 in 0.5 steps")


def _cancel_dispatched_dme_for(rx_id):
    for dme in db["dme_orders"].values():
        if dme["prescription_id"] == rx_id and dme["status"] == "DISPATCHED":
            dme["status"] = "CANCELLED"
            touch(dme)


def _supersede_active_rx(report_id):
    for existing in db["therapy_prescriptions"].values():
        if (existing["report_id"] == report_id
                and existing["status"] in ("DRAFT", "ORDERED")):
            existing["status"] = "SUPERSEDED"
            touch(existing)
            _cancel_dispatched_dme_for(existing["id"])


@bp.post("/therapy-prescriptions")
def create_prescription():
    authorized(["InterpretingPhysician"])
    body = get_body()
    # Priority 3: body FK existence.
    report = require_body_ref("interpretation_reports", body.get("report_id"))
    # Priority 4: shape, including the device-specific field sets.
    report_id = req_str(body, "report_id")
    device_type = req_enum(body, "device_type", DEVICE_TYPES)
    mask_type = req_enum(body, "mask_type", MASK_TYPES)
    humidification = opt_bool(body, "humidification", True)
    expected_version = req_int(body, "expected_interpretation_report_version")
    _validate_device_fields(body, device_type)
    # Priority 6: optimistic concurrency on the report.
    if expected_version != report["version"]:
        raise_error(ERR_STALE_VERSION,
                    "expected_interpretation_report_version does not match the report's current version")
    # Priority 7: report must be SIGNED or FINALIZED.
    if report["status"] not in ("SIGNED", "FINALIZED"):
        raise_error(ERR_REPORT_INVALID_STATE,
                    f"prescription creation requires SIGNED or FINALIZED, found {report['status']}")
    # Priority 9: NORMAL severity does not support PAP therapy.
    if report["severity"] == "NORMAL":
        raise_error(ERR_THERAPY_NOT_INDICATED,
                    "severity NORMAL does not support PAP prescription")
    _supersede_active_rx(report_id)
    rec = new_record("therapy_prescriptions", {
        "report_id": report_id,
        "study_id": report["study_id"],
        "device_type": device_type,
        "cpap_pressure_cm": body.get("cpap_pressure_cm") if device_type == "CPAP" else None,
        "apap_min_cm": body.get("apap_min_cm") if device_type == "APAP" else None,
        "apap_max_cm": body.get("apap_max_cm") if device_type == "APAP" else None,
        "bipap_ipap_cm": body.get("bipap_ipap_cm") if device_type == "BIPAP" else None,
        "bipap_epap_cm": body.get("bipap_epap_cm") if device_type == "BIPAP" else None,
        "mask_type": mask_type,
        "humidification": humidification,
        "ordered_at": None,
        "status": "DRAFT",
    })
    touch(report)
    return success_object(public(rec), status=201)


@bp.get("/therapy-prescriptions")
def list_prescriptions():
    return list_response("therapy_prescriptions", query_filters("report_id", "study_id"))


@bp.get("/therapy-prescriptions/<therapyPrescriptionId>")
def get_prescription(therapyPrescriptionId):
    return get_one("therapy_prescriptions", therapyPrescriptionId)


def _check_rx_author(caller, rx):
    report = db["interpretation_reports"].get(rx["report_id"])
    author = report["physician_id"] if report is not None else None
    if caller.user_id != author:
        raise_error(ERR_NOT_REPORT_AUTHOR, "X-User-ID must equal the author report's physician_id")
    return report


@bp.post("/therapy-prescriptions/<therapyPrescriptionId>/order")
def order_prescription(therapyPrescriptionId):
    caller = authorized(["InterpretingPhysician"])
    rx = require_path_resource("therapy_prescriptions", therapyPrescriptionId)
    _check_rx_author(caller, rx)
    if rx["status"] != "DRAFT":
        raise_error(ERR_RX_INVALID_STATE, f"order requires DRAFT, found {rx['status']}")
    rx["status"] = "ORDERED"
    rx["ordered_at"] = CLOCK.now_iso()
    touch(rx)
    return success_object(public(rx))


@bp.post("/therapy-prescriptions/<therapyPrescriptionId>/cancel")
def cancel_prescription(therapyPrescriptionId):
    caller = authorized(["InterpretingPhysician"])
    rx = require_path_resource("therapy_prescriptions", therapyPrescriptionId)
    _check_rx_author(caller, rx)
    if rx["status"] not in ("DRAFT", "ORDERED"):
        raise_error(ERR_RX_INVALID_STATE,
                    f"cancel requires DRAFT or ORDERED, found {rx['status']}")
    rx["status"] = "CANCELLED"
    touch(rx)
    _cancel_dispatched_dme_for(rx["id"])
    return success_object(public(rx))
