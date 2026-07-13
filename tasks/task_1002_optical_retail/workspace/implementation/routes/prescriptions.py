"""Prescription capture, verification and the rejection loop (PRD 3.2)."""
from flask import Blueprint, request

import calc
import schema
import store
from auth import authenticate, require_owner
from envelope import array_response, object_response, paginate
from errors import err
from serializers import dump, dump_all

bp = Blueprint("prescriptions", __name__)


def _read_measurements(b):
    """The measurement payload shared by capture and resubmit."""
    values = {
        "od_sphere": schema.number_field(b, "od_sphere"),
        "od_cylinder": schema.number_field(b, "od_cylinder"),
        "os_sphere": schema.number_field(b, "os_sphere"),
        "os_cylinder": schema.number_field(b, "os_cylinder"),
        "pd_mm": schema.number_field(b, "pd_mm"),
        "prism_diopters": schema.number_field(
            b, "prism_diopters", required=False, default=0.0, minimum=0
        ),
    }
    issued_raw, issued_dt = schema.datetime_field(b, "issued_at")
    expires_raw, expires_dt = schema.datetime_field(b, "expires_at")
    schema.strictly_after("expires_at", expires_dt, "issued_at", issued_dt)
    values["issued_at"] = issued_raw
    values["expires_at"] = expires_raw
    values["_issued_at_dt"] = issued_dt
    values["_expires_at_dt"] = expires_dt
    return values


def _check_pd(pd_mm):
    """Priority 13 -- the closed range [45.0, 80.0]."""
    pd = calc.dec(pd_mm)
    if pd < calc.PD_MIN_MM or pd > calc.PD_MAX_MM:
        raise err("ERR_PD_OUT_OF_RANGE")


@bp.post("/prescriptions")
def create_prescription():
    actor = authenticate("Customer", "StoreAssociate")
    b = schema.body()
    customer_id = schema.string_field(b, "customer_id")
    values = _read_measurements(b)

    schema.get_customer(customer_id)
    require_owner(actor, customer_id)
    _check_pd(values["pd_mm"])

    rec = store.new_record(
        customer_id=customer_id,
        status="SUBMITTED",
        verified_by=None,
        rejection_reason=None,
        resubmit_count=0,
        **values
    )
    store.prescriptions[rec["id"]] = rec
    return object_response(dump("prescription", rec), 201)


@bp.get("/prescriptions/<rx_id>")
def read_prescription(rx_id):
    actor = authenticate("Customer", "OpticianVerifier", "StoreAssociate", "PlatformAdmin")
    rec = schema.get_prescription(rx_id)
    require_owner(actor, rec["customer_id"])
    return object_response(dump("prescription", rec))


@bp.get("/customers/<customer_id>/prescriptions")
def list_customer_prescriptions(customer_id):
    actor = authenticate("Customer", "OpticianVerifier", "StoreAssociate", "PlatformAdmin")
    schema.get_customer(customer_id)
    require_owner(actor, customer_id)

    items = [
        p for p in store.ordered(store.prescriptions) if p["customer_id"] == customer_id
    ]
    status = request.args.get("status")
    if status:
        items = [p for p in items if p["status"] == status]
    window, meta = paginate(items)
    return array_response(dump_all("prescription", window), meta)


@bp.post("/prescriptions/<rx_id>/verify")
def verify_prescription(rx_id):
    authenticate("OpticianVerifier")
    b = schema.body()
    decision = schema.enum_field(b, "decision", ("VERIFIED", "REJECTED"))
    rejection_reason = schema.string_field(
        b, "rejection_reason", required=(decision == "REJECTED"), default=None
    )

    rx = schema.get_prescription(rx_id)
    if rx["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE")

    if decision == "VERIFIED":
        if not (rx["_expires_at_dt"] > store.clock_now()):
            raise err("ERR_PRESCRIPTION_EXPIRED")
        rx["status"] = "VERIFIED"
        rx["verified_by"] = request.headers.get("X-User-ID")
        rx["rejection_reason"] = None
    else:
        rx["status"] = "REJECTED"
        rx["rejection_reason"] = rejection_reason

    store.touch(rx)
    return object_response(dump("prescription", rx))


@bp.post("/prescriptions/<rx_id>/resubmit")
def resubmit_prescription(rx_id):
    actor = authenticate("Customer")
    b = schema.body()
    values = _read_measurements(b)

    rx = schema.get_prescription(rx_id)
    require_owner(actor, rx["customer_id"])
    if rx["status"] != "REJECTED":
        raise err("ERR_INVALID_STATE")
    _check_pd(values["pd_mm"])

    rx.update(values)
    rx["status"] = "SUBMITTED"
    rx["resubmit_count"] += 1
    rx["rejection_reason"] = None
    store.touch(rx)
    return object_response(dump("prescription", rx))
