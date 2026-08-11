"""Application record and rinsate record routes."""

from flask import Blueprint, request

from store import store
from util import (require_roles, get_body, req_str, req_nonempty_str, req_pos_num,
                  req_enum, opt_str, ok, paginate, now, dec, ApiError,
                  not_found, forbidden, invalid_state, conflict)
from domain import (new_evidence, serialize, touch, validate_actual_lines,
                    find_invoice, final_amount_cents, RINSATE_KINDS)

bp = Blueprint("records", __name__, url_prefix="/api")


# ---------------------------------------------------------------------------
# Application records
# ---------------------------------------------------------------------------

@bp.get("/application-records/<rid>")
def get_application_record(rid):
    require_roles("Dispatcher", "Applicator", "ComplianceOfficer", "CoopAdmin")
    r = store.application_records.get(rid)
    if r is None:
        raise not_found("application record not found")
    return ok(serialize("application_record", r))


@bp.get("/application-records")
def list_application_records():
    require_roles("Dispatcher", "Applicator", "ComplianceOfficer", "CoopAdmin")
    items = sorted(store.application_records.values(),
                   key=lambda r: (r["created_at"], r["_seq"]))
    for param in ("work_order_id", "applicator_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [r for r in items if r[param] == v]
    return paginate([serialize("application_record", r) for r in items])


@bp.post("/application-records/<rid>/certify")
def certify_application_record(rid):
    uid, _role = require_roles("ComplianceOfficer", "Applicator")
    r = store.application_records.get(rid)
    if r is None:
        raise not_found("application record not found")
    # segregation of duties: the certifier must differ from the performing applicator
    if uid == r["applicator_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "the certifier must differ from the performing applicator", 403)
    if r["status"] != "SUBMITTED":
        raise invalid_state("only a SUBMITTED application record can be certified")
    r["certified_by_user_id"] = uid
    w = store.work_orders[r["work_order_id"]]
    customer = store.customers[w["customer_id"]]
    inv = find_invoice(w["id"])
    inv["final_amount_cents"] = final_amount_cents(w, customer, r)
    touch(inv)
    r["status"] = "CERTIFIED"
    touch(r)
    return ok(serialize("application_record", r))


@bp.post("/application-records/<rid>/return")
def return_application_record(rid):
    require_roles("ComplianceOfficer")
    r = store.application_records.get(rid)
    if r is None:
        raise not_found("application record not found")
    note = req_nonempty_str(get_body(), "returned_note")
    if r["status"] != "SUBMITTED":
        raise invalid_state("only a SUBMITTED application record can be returned")
    r["status"] = "RETURNED"
    r["returned_note"] = note
    touch(r)
    return ok(serialize("application_record", r))


@bp.post("/application-records/<rid>/resubmit")
def resubmit_application_record(rid):
    uid, _role = require_roles("Applicator")
    r = store.application_records.get(rid)
    if r is None:
        raise not_found("application record not found")
    if r["applicator_id"] != uid:
        raise forbidden("only the performing applicator may resubmit this record")
    w = store.work_orders[r["work_order_id"]]
    rx = store.prescriptions[w["prescription_id"]]
    lines = validate_actual_lines(get_body().get("lines"), rx)
    if r["status"] != "RETURNED":
        raise invalid_state("only a RETURNED application record can be resubmitted")
    r["lines"] = lines
    r["returned_note"] = None
    r["status"] = "SUBMITTED"
    touch(r)
    return ok(serialize("application_record", r))


# ---------------------------------------------------------------------------
# Rinsate records (evidence; decrement the work order's rinsate balance)
# ---------------------------------------------------------------------------

@bp.post("/rinsate-records")
def create_rinsate_record():
    require_roles("Applicator")
    body = get_body()
    work_order_id = req_str(body, "work_order_id")
    kind = req_enum(body, "kind", RINSATE_KINDS)
    volume = req_pos_num(body, "volume_gal")
    disposal_field_id = None
    manifest_no = None
    if kind == "FIELD_DISPOSAL":
        disposal_field_id = req_str(body, "disposal_field_id")
        manifest_no = opt_str(body, "manifest_no")
    else:
        manifest_no = req_nonempty_str(body, "manifest_no")
        disposal_field_id = opt_str(body, "disposal_field_id")
    w = store.work_orders.get(work_order_id)
    if w is None:
        raise not_found("work order not found")
    if disposal_field_id is not None and disposal_field_id not in store.fields:
        raise not_found("disposal field not found")
    if w["status"] != "COMPLETED":
        raise invalid_state("rinsate can only be recorded against a COMPLETED work order")
    vol = dec(volume)
    if vol > w["rinsate_balance_gal"]:
        raise conflict("ERR_RINSATE_OVER_DISPOSAL",
                       "disposal volume exceeds the current rinsate_balance_gal")
    if kind == "FIELD_DISPOSAL" and disposal_field_id != w["field_id"]:
        raise conflict("ERR_DISPOSAL_FIELD_MISMATCH",
                       "FIELD_DISPOSAL must land back on the work order's own field")
    rec = new_evidence({
        "work_order_id": work_order_id,
        "kind": kind,
        "volume_gal": volume,
        "disposal_field_id": disposal_field_id,
        "manifest_no": manifest_no,
        "recorded_at": now(),
    })
    store.rinsate_records[rec["id"]] = rec
    w["rinsate_balance_gal"] = w["rinsate_balance_gal"] - vol
    touch(w)
    return ok(serialize("rinsate_record", rec), 201)


@bp.get("/rinsate-records/<rid>")
def get_rinsate_record(rid):
    require_roles("Dispatcher", "Applicator", "ComplianceOfficer", "CoopAdmin")
    r = store.rinsate_records.get(rid)
    if r is None:
        raise not_found("rinsate record not found")
    return ok(serialize("rinsate_record", r))


@bp.get("/rinsate-records")
def list_rinsate_records():
    require_roles("Dispatcher", "Applicator", "ComplianceOfficer", "CoopAdmin")
    items = sorted(store.rinsate_records.values(), key=lambda r: (r["created_at"], r["_seq"]))
    wo = request.args.get("work_order_id")
    if wo is not None:
        items = [r for r in items if r["work_order_id"] == wo]
    df = request.args.get("disposal_field_id")
    if df is not None:
        items = [r for r in items if r["disposal_field_id"] == df]
    return paginate([serialize("rinsate_record", r) for r in items])
