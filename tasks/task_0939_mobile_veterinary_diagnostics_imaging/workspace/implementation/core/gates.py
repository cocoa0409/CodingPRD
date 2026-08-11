"""The five ordered write gates, rungs 8-12 (PRD 2.9).

Gate order is ABSOLUTE and independent of how many gates a request trips: every
handler calls these in the order G1, G2, G3, G4, G5 and the first one that fires
pre-empts every rung from 13 upwards.
"""

from core import db
from core.errors import ApiError


# --- G1 (rung 8) -----------------------------------------------------------

def g1_invoice_not_finalized(invoice):
    """Direct posting / finalization against an already FINALIZED invoice."""
    if invoice is not None and invoice["status"] == "FINALIZED":
        raise ApiError("ERR_INVOICE_FINALIZED")


def g1_no_frozen_lines(study_ids):
    """A cascade leg that would reverse or re-price lines on a FINALIZED invoice
    is refused outright — the freeze is absolute and there is no override."""
    ids = set(study_ids)
    if not ids:
        return
    for line in db.all_rows("charge_lines"):
        if line["study_id"] not in ids or line["status"] != "ACTIVE":
            continue
        invoice = db.get("invoices", line["invoice_id"])
        if invoice is not None and invoice["status"] == "FINALIZED":
            raise ApiError("ERR_INVOICE_FINALIZED")


# --- G2 (rung 9) -----------------------------------------------------------

def g2_clinic_not_on_hold(clinic):
    if clinic is not None and clinic.get("billing_hold_status") == "HOLD":
        raise ApiError("ERR_CLINIC_BILLING_HOLD")


# --- G3 (rung 10) ----------------------------------------------------------

def g3_unit_in_service(route):
    if route is None:
        return
    unit = db.get("mobile_units", route.get("mobile_unit_id"))
    if unit is not None and unit.get("service_status") != "IN_SERVICE":
        raise ApiError("ERR_UNIT_OUT_OF_SERVICE")


# --- G4 (rung 11) ----------------------------------------------------------

def g4_equipment_calibrated(equipment):
    from services.derive import calibration_status

    if equipment is None:
        return
    status = calibration_status(equipment)
    if status == "QUARANTINED":
        raise ApiError("ERR_EQUIPMENT_QUARANTINED")
    if status in ("EXPIRED", "UNCALIBRATED"):
        raise ApiError("ERR_EQUIPMENT_CALIBRATION_LAPSED")


# --- G5 (rung 12) ----------------------------------------------------------

def g5_route_not_completed(route):
    if route is not None and route.get("status") == "COMPLETED":
        raise ApiError("ERR_ROUTE_FROZEN")
