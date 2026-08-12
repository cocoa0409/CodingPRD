"""Vendor directory and vendor assignments."""

from flask import Blueprint

import calc
import constants as K
import derive
import gates
import services
import store
from errors import ApiError
from routes.helpers import one, listing, filtered
from util import parse_dt, parse_date

bp = Blueprint("vendors", __name__)

VA_READ = ["MOVE_MANAGER", "VENDOR", "BILLING_ADMIN", "CLIENT", "POWER_OF_ATTORNEY"]
VA_TERMINAL = ["PAID", "CANCELLED"]
CAPACITY_STATES = ("SCHEDULED", "COI_BLOCKED", "PERFORMED", "SIGNED_OFF", "PAID")


# ---------------------------------------------------------------------------
# vendors - platform reference data
# ---------------------------------------------------------------------------

@bp.route("/vendors", methods=["POST"])
def create_vendor():
    req = gates.preflight(["PLATFORM_ADMIN"],
                          required=[("name", "string"), ("vendor_type", "string"),
                                    ("coi_expires_on", "date")],
                          optional=[("daily_capacity", "int"), ("holdback_pct", "number")])
    capacity = req.body.get("daily_capacity")
    holdback = req.body.get("holdback_pct")
    record = store.base_record()
    record.update({
        "name": req.body["name"],
        "vendor_type": req.body["vendor_type"],
        "coi_expires_on": req.body["coi_expires_on"],
        "daily_capacity": K.VENDOR_DAILY_CAPACITY_DEFAULT if capacity is None else capacity,
        "holdback_pct": float(K.VENDOR_HOLDBACK_PCT_DEFAULT) if holdback is None else holdback,
        "coi_renewal_count": 0,
    })
    store.insert("vendors", record)
    return one("vendors", record, 201)


@bp.route("/vendors/<vid>", methods=["GET"])
def read_vendor(vid):
    req = gates.preflight(["PLATFORM_ADMIN", "MOVE_MANAGER", "VENDOR", "BILLING_ADMIN"])
    record = gates.path_record("vendors", vid)
    gates.gate4_ownership(req, vendor_id=record["id"])
    return one("vendors", record)


@bp.route("/vendors/<vid>/renew-coi", methods=["POST"])
def renew_coi(vid):
    req = gates.preflight(["PLATFORM_ADMIN", "VENDOR"],
                          required=[("coi_expires_on", "date")])
    record = gates.path_record("vendors", vid)
    gates.gate4_ownership(req, vendor_id=record["id"])

    record["coi_expires_on"] = req.body["coi_expires_on"]
    record["coi_renewal_count"] = record["coi_renewal_count"] + 1
    store.touch(record)
    for assignment in store.where("vendor_assignments", vendor_id=record["id"]):
        if assignment["status"] != "COI_BLOCKED":
            continue
        if parse_date(record["coi_expires_on"]) >= parse_date(assignment["service_date"]):
            assignment["status"] = "SCHEDULED"
            store.touch(assignment)
    return one("vendors", record)


# ---------------------------------------------------------------------------
# vendor assignments
# ---------------------------------------------------------------------------

@bp.route("/vendor-assignments", methods=["POST"])
def create_vendor_assignment():
    req = gates.preflight(["MOVE_MANAGER"],
                          required=[("engagement_id", "string"), ("vendor_id", "string"),
                                    ("service_kind", "string"), ("service_date", "date"),
                                    ("quoted_cents", "int")])
    fks = gates.resolve_body_fks(req.body)
    engagement = fks["engagement_id"]
    vendor = fks["vendor_id"]
    gates.gate3(engagement)
    if K.SERVICE_KIND_TO_VENDOR_TYPE[req.body["service_kind"]] != vendor["vendor_type"]:
        raise ApiError("ERR_VENDOR_TYPE_MISMATCH")

    record = store.base_record()
    record.update({
        "engagement_id": engagement["id"],
        "vendor_id": vendor["id"],
        "signed_off_by_party_id": None,
        "service_kind": req.body["service_kind"],
        "service_date": req.body["service_date"],
        "status": "REQUESTED",
        "quoted_cents": req.body["quoted_cents"],
        "holdback_cents": 0,
        "paid_cents": 0,
        "holdback_released": False,
        "performed_at_utc": None,
        "cancel_reason": None,
    })
    store.insert("vendor_assignments", record)
    return one("vendor_assignments", record, 201)


@bp.route("/vendor-assignments", methods=["GET"])
def list_vendor_assignments():
    req = gates.preflight(VA_READ, is_list=True)
    rows = filtered(store.all_of("vendor_assignments"), req.args,
                    ["engagement_id", "vendor_id", "signed_off_by_party_id", "status",
                     "service_date"])
    return listing("vendor_assignments", req, rows)


@bp.route("/vendor-assignments/<aid>", methods=["GET"])
def read_vendor_assignment(aid):
    req = gates.preflight(VA_READ)
    record = gates.path_record("vendor_assignments", aid)
    gates.gate4_ownership(req, engagement=store.get("engagements", record["engagement_id"]),
                          vendor_id=record["vendor_id"])
    return one("vendor_assignments", record)


def _va_context(aid):
    record = gates.path_record("vendor_assignments", aid)
    engagement = store.get("engagements", record["engagement_id"])
    vendor = store.get("vendors", record["vendor_id"])
    return record, engagement, vendor


@bp.route("/vendor-assignments/<aid>/accept", methods=["POST"])
def accept_vendor_assignment(aid):
    req = gates.preflight(["VENDOR"])
    record, engagement, vendor = _va_context(aid)
    gates.gate3(engagement)
    gates.gate4_ownership(req, vendor_id=record["vendor_id"])
    gates.gate10_state(record["status"], ["REQUESTED"], VA_TERMINAL)
    record["status"] = "ACCEPTED"
    record["holdback_cents"] = calc.vendor_holdback(record["quoted_cents"],
                                                    vendor["holdback_pct"])
    store.touch(record)
    return one("vendor_assignments", record)


@bp.route("/vendor-assignments/<aid>/schedule", methods=["POST"])
def schedule_vendor_assignment(aid):
    gates.preflight(["MOVE_MANAGER"])
    record, engagement, vendor = _va_context(aid)
    gates.gate3(engagement)
    # gate 8 precedes the gate-10 state rung
    if parse_date(vendor["coi_expires_on"]) < parse_date(record["service_date"]):
        raise ApiError("ERR_VENDOR_COI_EXPIRED")
    load = len([a for a in store.where("vendor_assignments", vendor_id=vendor["id"])
                if a["service_date"] == record["service_date"]
                and a["status"] in CAPACITY_STATES])
    if load >= vendor["daily_capacity"]:
        raise ApiError("ERR_VENDOR_DAILY_CAPACITY_EXCEEDED")
    gates.gate10_state(record["status"], ["ACCEPTED"], VA_TERMINAL)

    record["status"] = "SCHEDULED"
    store.touch(record)
    return one("vendor_assignments", record)


@bp.route("/vendor-assignments/<aid>/perform", methods=["POST"])
def perform_vendor_assignment(aid):
    req = gates.preflight(["VENDOR", "MOVE_MANAGER"],
                          required=[("performed_at_utc", "datetime")])
    record, engagement, vendor = _va_context(aid)
    gates.gate3(engagement)
    gates.gate4_ownership(req, vendor_id=record["vendor_id"])
    gates.gate9_not_finalized(engagement, "ERR_BILLING_CLOSED")
    gates.gate10_state(record["status"], ["SCHEDULED"], VA_TERMINAL)
    service_midnight = record["service_date"] + "T00:00:00.000Z"
    gates.require_state(parse_dt(req.body["performed_at_utc"]) >= parse_dt(service_midnight))

    record["status"] = "PERFORMED"
    record["performed_at_utc"] = req.body["performed_at_utc"]
    record["paid_cents"] = record["quoted_cents"] - record["holdback_cents"]
    store.touch(record)
    invoice = derive.invoice_of(engagement["id"])
    services.append_line(invoice, "VENDOR_PASSTHROUGH", record["quoted_cents"],
                         "Vendor pass-through", "SYSTEM")
    return one("vendor_assignments", record)


@bp.route("/vendor-assignments/<aid>/sign-off", methods=["POST"])
def sign_off_vendor_assignment(aid):
    req = gates.preflight(["MOVE_MANAGER", "CLIENT", "POWER_OF_ATTORNEY"],
                          required=[("signed_off_by_party_id", "string")])
    record, engagement, vendor = _va_context(aid)
    gates.resolve_body_fks(req.body)
    gates.gate3(engagement)
    gates.gate4_ownership(req, engagement=engagement)
    gates.gate4_party_membership(engagement, [req.body["signed_off_by_party_id"]])
    gates.gate4_authority(req, "BILLING")
    gates.gate10_state(record["status"], ["PERFORMED"], VA_TERMINAL)

    record["status"] = "SIGNED_OFF"
    record["signed_off_by_party_id"] = req.body["signed_off_by_party_id"]
    record["holdback_released"] = True
    record["paid_cents"] = record["quoted_cents"]
    store.touch(record)
    return one("vendor_assignments", record)


@bp.route("/vendor-assignments/<aid>/pay", methods=["POST"])
def pay_vendor_assignment(aid):
    gates.preflight(["BILLING_ADMIN"])
    record, engagement, vendor = _va_context(aid)
    gates.gate3(engagement)
    gates.gate9_not_finalized(engagement, "ERR_BILLING_CLOSED")
    gates.gate10_state(record["status"], ["SIGNED_OFF"], VA_TERMINAL)
    record["status"] = "PAID"
    store.touch(record)
    return one("vendor_assignments", record)


@bp.route("/vendor-assignments/<aid>/cancel", methods=["POST"])
def cancel_vendor_assignment(aid):
    req = gates.preflight(["MOVE_MANAGER", "VENDOR"], required=[("reason", "nes")])
    record, engagement, vendor = _va_context(aid)
    gates.gate3(engagement)
    gates.gate4_ownership(req, vendor_id=record["vendor_id"])
    gates.gate10_state(record["status"],
                       ["REQUESTED", "ACCEPTED", "SCHEDULED", "COI_BLOCKED"], VA_TERMINAL)
    record["status"] = "CANCELLED"
    record["cancel_reason"] = req.body["reason"]
    store.touch(record)
    return one("vendor_assignments", record)
