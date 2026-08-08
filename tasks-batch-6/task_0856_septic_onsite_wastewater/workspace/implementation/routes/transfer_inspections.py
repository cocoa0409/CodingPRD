"""Real-estate transfer certificates."""
from flask import Blueprint

import calc
import lookup
import response
import serialize
import store
import validate as v
from auth import authenticate
from derive import recompute_parcel
from errors import ApiError
from store import ordered, touch
from util import add_days, now

bp = Blueprint("transfer_inspections", __name__)

MODES = ("DESK_REVIEW", "FIELD_VERIFIED")
CONDITIONS = ("GOOD", "FAIR", "POOR")
TRANSFER_READ_ROLES = ["Applicant", "EnvironmentalHealthSpecialist",
                       "HealthOfficer", "RecordsClerk"]
DECISIONS = ("CERTIFY", "DENY")


@bp.post("/transfer-inspections")
def request_transfer_inspection():
    actor = authenticate(["Applicant", "RecordsClerk"])
    body = v.body()
    parcel = lookup.parcel(v.req_fk(body, "parcel_id"))
    permit = lookup.operating_permit(v.req_fk(body, "operating_permit_id"))
    expected_version = v.req_int(body, "expected_parcel_version")
    requested_on = v.req_dt(body, "requested_on")
    buyer_name = v.req_str(body, "buyer_name")
    seller_name = v.req_str(body, "seller_name")
    inspection_mode = v.req_enum(body, "inspection_mode", MODES)
    expedited = v.opt_bool(body, "expedited", default=False)
    tank_condition = v.opt_enum(body, "tank_condition", CONDITIONS)
    drainfield_condition = v.opt_enum(body, "drainfield_condition", CONDITIONS)

    if actor.role == "Applicant" and parcel["owner_user_id"] != actor.user_id:
        raise ApiError("ERR_NOT_PARCEL_OWNER")

    if expected_version != parcel["version"]:
        raise ApiError("ERR_STALE_PARCEL_VERSION")

    if inspection_mode == "FIELD_VERIFIED":
        if tank_condition is None or drainfield_condition is None:
            raise ApiError("ERR_FIELD_CONDITIONS_REQUIRED")
    else:
        if tank_condition is not None or drainfield_condition is not None:
            raise ApiError("ERR_FIELD_CONDITIONS_REQUIRED")

    subtotal, expedite_fee, total = calc.transfer_inspection_charges(
        inspection_mode, expedited, parcel["open_repair_order_count"])

    request_row = store.new_record()
    request_row.update({
        "parcel_id": parcel["id"],
        "operating_permit_id": permit["id"],
        "requested_on": requested_on,
        "buyer_name": buyer_name,
        "seller_name": seller_name,
        "inspection_mode": inspection_mode,
        "expedited": expedited,
        "tank_condition": tank_condition,
        "drainfield_condition": drainfield_condition,
        "subtotal_cents": subtotal,
        "expedite_fee_cents": expedite_fee,
        "total_due_cents": total,
        "certificate_grade": None,
        "certified_at": None,
        "certificate_valid_until": None,
        "status": "BLOCKED" if permit["status"] == "SUSPENDED" else "REQUESTED",
    })
    store.transfer_inspections[request_row["id"]] = request_row

    recompute_parcel(parcel, force_bump=True)
    return response.ok(serialize.transfer_inspection(request_row), 201)


@bp.get("/transfer-inspections/<request_id>")
def read_transfer_inspection(request_id):
    authenticate(TRANSFER_READ_ROLES)
    request_row = lookup.transfer_inspection(request_id)
    return response.ok(serialize.transfer_inspection(request_row))


@bp.get("/transfer-inspections")
def list_transfer_inspections():
    authenticate(TRANSFER_READ_ROLES)
    limit, offset = v.pagination()
    rows = ordered(store.transfer_inspections.values())
    for field in ("parcel_id", "operating_permit_id", "status",
                  "inspection_mode"):
        value = v.q(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    page, total = v.paginate(rows, limit, offset)
    return response.ok_list(serialize.many("transfer_inspection", page),
                            limit, offset, total)


@bp.post("/transfer-inspections/<request_id>/certify")
def certify_transfer_inspection(request_id):
    authenticate(["EnvironmentalHealthSpecialist"])
    request_row = lookup.transfer_inspection(request_id)
    body = v.body()
    decision = v.req_enum(body, "decision", DECISIONS)

    if decision == "DENY":
        if request_row["status"] not in ("REQUESTED", "BLOCKED"):
            raise ApiError("ERR_INVALID_STATE")
        request_row["status"] = "DENIED"
        request_row["certificate_grade"] = "UNSATISFACTORY"
        touch(request_row)
        return response.ok(serialize.transfer_inspection(request_row))

    if request_row["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE")

    permit = store.operating_permits[request_row["operating_permit_id"]]
    parcel = store.parcels[request_row["parcel_id"]]
    if permit["status"] != "ACTIVE":
        raise ApiError("ERR_OPERATING_PERMIT_NOT_ACTIVE")
    if parcel["transfer_hold"]:
        raise ApiError("ERR_TRANSFER_HOLD_ACTIVE")
    if parcel["fee_balance_cents"] != 0:
        raise ApiError("ERR_OUTSTANDING_FEE_BALANCE")

    grade = calc.transfer_certificate_grade(
        request_row["inspection_mode"], parcel["open_repair_order_count"],
        permit["status"], permit["compliance_status"],
        parcel["water_quality_flag"], request_row["tank_condition"],
        request_row["drainfield_condition"])

    clock = now()
    request_row["certificate_grade"] = grade
    request_row["certified_at"] = clock
    request_row["certificate_valid_until"] = add_days(
        clock, calc.TRANSFER_CERT_VALIDITY_DAYS)
    request_row["status"] = "CERTIFIED"
    touch(request_row)
    return response.ok(serialize.transfer_inspection(request_row))
