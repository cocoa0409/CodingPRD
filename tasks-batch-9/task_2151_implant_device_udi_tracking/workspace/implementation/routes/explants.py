"""Explant disposition, vendor return shipment and return credit."""
from flask import Blueprint

import serialize
from auth import (
    CIRC_CLINICIAN,
    COMPLIANCE_OFFICER,
    INVENTORY_LEAD,
    REVENUE_ANALYST,
    VENDOR_REP,
    actor,
    endpoint,
)
from derive import set_billing, set_custody, vendor_open_consignment_liability
from envelope import array_response, object_response
from errors import ApiError
from graph import record_of_explant, unit_of_record, vendor_of_unit
from resolve import must
from store import db, ordered, touch
from validation import (
    apply_page,
    body,
    filter_enum,
    filter_value,
    pagination,
    req_enum,
    req_int,
    req_str,
)

bp = Blueprint("explants", __name__)

EXPLANT_STATES = (
    "RECORDED",
    "RETURN_AUTHORIZED",
    "SHIPPED",
    "CREDIT_ISSUED",
    "CREDIT_DENIED",
    "DISPOSED_LOCALLY",
)
EXPLANT_READERS = [INVENTORY_LEAD, CIRC_CLINICIAN, COMPLIANCE_OFFICER, REVENUE_ANALYST, VENDOR_REP]


@bp.route("/udi/explant-records/<explant_record_id>", methods=["GET"])
@endpoint(EXPLANT_READERS)
def get_explant(explant_record_id):
    return object_response(serialize.explant_record(must("explant_record_id", explant_record_id)))


@bp.route("/udi/explant-records", methods=["GET"])
@endpoint(EXPLANT_READERS)
def list_explants():
    limit, offset = pagination()
    implant_record_id = filter_value("implant_record_id")
    replacement_device_unit_id = filter_value("replacement_device_unit_id")
    status = filter_enum("status", EXPLANT_STATES)
    rows = []
    for row in db.explant_records.values():
        if implant_record_id is not None and row["implant_record_id"] != implant_record_id:
            continue
        if (
            replacement_device_unit_id is not None
            and row.get("replacement_device_unit_id") != replacement_device_unit_id
        ):
            continue
        if status is not None and row["status"] != status:
            continue
        rows.append(row)
    page, total = apply_page(ordered(rows), limit, offset)
    return array_response([serialize.explant_record(r) for r in page], limit, offset, total)


@bp.route("/udi/explant-records/<explant_record_id>/disposition", methods=["POST"])
@endpoint([INVENTORY_LEAD])
def dispose_explant(explant_record_id):
    data = body()
    disposition = req_enum(data, "disposition", ("RETURN_TO_VENDOR", "DISPOSE_LOCALLY"))
    return_authorization_no = None
    if disposition == "RETURN_TO_VENDOR":
        return_authorization_no = req_str(data, "return_authorization_no")

    explant = must("explant_record_id", explant_record_id)
    if explant["status"] != "RECORDED":                              # step 8
        raise ApiError("ERR_INVALID_LIFECYCLE_STATE", "Only a RECORDED explant takes a disposition.")

    unit = unit_of_record(record_of_explant(explant))

    if disposition == "RETURN_TO_VENDOR":
        explant["status"] = "RETURN_AUTHORIZED"
        explant["return_authorization_no"] = return_authorization_no
        touch(explant)
    else:
        explant["status"] = "DISPOSED_LOCALLY"
        touch(explant)
        if unit is not None:
            set_custody(unit, "DISPOSED")
            if unit["billing_state"] == "CREDIT_PENDING":
                set_billing(unit, "BILLABLE")
    return object_response(serialize.explant_record(explant))


@bp.route("/udi/explant-records/<explant_record_id>/ship", methods=["POST"])
@endpoint([INVENTORY_LEAD])
def ship_explant(explant_record_id):
    explant = must("explant_record_id", explant_record_id)
    if explant["status"] != "RETURN_AUTHORIZED":                     # step 8
        raise ApiError("ERR_INVALID_LIFECYCLE_STATE", "Only an authorized return can ship.")

    explant["status"] = "SHIPPED"
    touch(explant)
    unit = unit_of_record(record_of_explant(explant))
    if unit is not None:
        set_custody(unit, "RETURNED_TO_VENDOR")
    return object_response(serialize.explant_record(explant))


@bp.route("/udi/explant-records/<explant_record_id>/credit", methods=["POST"])
@endpoint([VENDOR_REP])
def credit_explant(explant_record_id):
    data = body()
    credit_issued_cents = req_int(data, "credit_issued_cents", 0)

    explant = must("explant_record_id", explant_record_id)           # step 4

    unit = unit_of_record(record_of_explant(explant))
    vendor = vendor_of_unit(unit) if unit is not None else None
    if vendor is None or vendor["id"] != actor():                    # step 6
        raise ApiError("ERR_UNAUTHORIZED", "A vendor may only credit its own devices.")

    if explant["status"] != "SHIPPED":                               # step 8
        raise ApiError("ERR_INVALID_LIFECYCLE_STATE", "Only a SHIPPED return takes a credit.")

    if credit_issued_cents > int(explant.get("credit_expected_cents") or 0):   # step 31
        raise ApiError("ERR_CREDIT_EXCEEDS_EXPECTED", "credit_issued_cents exceeds the expectation.")

    explant["credit_issued_cents"] = credit_issued_cents
    explant["status"] = "CREDIT_ISSUED" if credit_issued_cents > 0 else "CREDIT_DENIED"
    touch(explant)

    if unit is not None and unit["billing_state"] == "CREDIT_PENDING":
        set_billing(unit, "CREDITED" if credit_issued_cents > 0 else "BILLABLE")
    vendor_open_consignment_liability(vendor)
    return object_response(serialize.explant_record(explant))
