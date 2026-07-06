"""Next-of-kin, property items, property releases, indigent disposition, closure cascades."""
from flask import Blueprint, request

import calculations
import errors
import lookup
import validate
from db import db
from middleware import require, json_body, paginate
from records import make_record, touch, public
from response import object_response, array_response
import services

bp = Blueprint("property", __name__)

RELATIONSHIPS = {"SPOUSE", "CHILD", "PARENT", "SIBLING", "OTHER"}


# ---- Next of kin ----
@bp.post("/cases/<case_id>/next-of-kin")
def add_kin(case_id):
    require({"Investigator"})
    lookup.case(case_id)
    body = json_body()
    full_name = validate.req_str(body, "full_name")
    relationship = validate.req_enum(body, "relationship", RELATIONSHIPS)

    rec = make_record({
        "case_id": case_id,
        "full_name": full_name,
        "relationship": relationship,
        "verified": False,
        "contacted_at": db.clock.now_iso(),
    })
    db.next_of_kin[rec["id"]] = rec
    return object_response(public(rec), 201)


@bp.get("/cases/<case_id>/next-of-kin")
def list_case_kin(case_id):
    require({"Admin", "Investigator", "MedicalExaminer"})
    lookup.case(case_id)
    rows = [k for k in db.next_of_kin.values() if k["case_id"] == case_id]
    page, limit, offset, total = paginate(rows)
    return array_response([public(k) for k in page], limit, offset, total)


@bp.get("/next-of-kin/<id_>")
def get_kin(id_):
    require({"Admin", "Investigator", "MedicalExaminer"})
    rec = lookup.next_of_kin(id_)
    return object_response(public(rec), 200)


@bp.post("/next-of-kin/<id_>/verify")
def verify_kin(id_):
    require({"Investigator"})
    rec = lookup.next_of_kin(id_)
    rec["verified"] = True
    touch(rec)
    return object_response(public(rec), 200)


# ---- Property items ----
@bp.post("/cases/<case_id>/property-items")
def add_property_item(case_id):
    require({"Investigator"})
    lookup.case(case_id)
    body = json_body()
    description = validate.req_str(body, "description")
    valuation_cents = validate.req_int(body, "valuation_cents", minimum=0)

    rec = make_record({
        "case_id": case_id,
        "description": description,
        "valuation_cents": valuation_cents,
        "item_status": "HELD",
    })
    db.property_items[rec["id"]] = rec
    return object_response(public(rec), 201)


@bp.get("/cases/<case_id>/property-items")
def list_property_items(case_id):
    require({"Admin", "Investigator", "MedicalExaminer"})
    lookup.case(case_id)
    rows = [p for p in db.property_items.values() if p["case_id"] == case_id]
    page, limit, offset, total = paginate(rows)
    return array_response([public(p) for p in page], limit, offset, total)


@bp.get("/property-items/<id_>")
def get_property_item(id_):
    require({"Admin", "Investigator", "MedicalExaminer"})
    rec = lookup.property_item(id_)
    return object_response(public(rec), 200)


# ---- Property releases ----
@bp.post("/cases/<case_id>/property-releases")
def request_release(case_id):
    require({"Investigator"})
    lookup.case(case_id)
    body = json_body()
    next_of_kin_id = validate.req_str(body, "next_of_kin_id")
    kin = lookup.next_of_kin(next_of_kin_id)

    rec = make_record({
        "case_id": case_id,
        "next_of_kin_id": next_of_kin_id,
        "approver_user_id": None,
        "release_status": "REQUESTED",
        "released_item_count": 0,
    })
    db.property_releases[rec["id"]] = rec
    return object_response(public(rec), 201)


@bp.get("/cases/<case_id>/property-releases")
def list_case_releases(case_id):
    require({"Admin", "Investigator", "MedicalExaminer"})
    lookup.case(case_id)
    rows = [r for r in db.property_releases.values() if r["case_id"] == case_id]
    kin = request.args.get("next_of_kin_id")
    if kin is not None:
        rows = [r for r in rows if r["next_of_kin_id"] == kin]
    page, limit, offset, total = paginate(rows)
    return array_response([public(r) for r in page], limit, offset, total)


@bp.get("/property-releases/<id_>")
def get_release(id_):
    require({"Admin", "Investigator", "MedicalExaminer"})
    rec = lookup.property_release(id_)
    return object_response(public(rec), 200)


@bp.get("/property-releases")
def list_releases():
    require({"Admin", "Investigator", "MedicalExaminer"})
    rows = list(db.property_releases.values())
    kin = request.args.get("next_of_kin_id")
    if kin is not None:
        rows = [r for r in rows if r["next_of_kin_id"] == kin]
    approver = request.args.get("approver_user_id")
    if approver is not None:
        rows = [r for r in rows if r.get("approver_user_id") == approver]
    page, limit, offset, total = paginate(rows)
    return array_response([public(r) for r in page], limit, offset, total)


@bp.post("/property-releases/<id_>/approve")
def approve_release(id_):
    actor = require({"Investigator"})
    rec = lookup.property_release(id_)
    case = db.cases.get(rec["case_id"])

    # state legality (priority 21)
    if rec["release_status"] != "REQUESTED":
        raise errors.err(errors.ERR_INVALID_STATE, "Approve only allowed from REQUESTED")

    # segregation of duties (priority 13): acting investigator != case lead
    if case is not None and actor.user_id == case["investigator_user_id"]:
        raise errors.err(errors.ERR_SEGREGATION_VIOLATION,
                         "Approving investigator must not be the case lead")

    # kin verified (priority 40)
    kin = db.next_of_kin.get(rec["next_of_kin_id"])
    if kin is None or not kin["verified"]:
        raise errors.err(errors.ERR_KIN_UNVERIFIED, "Referenced next-of-kin is not verified")

    # case CERTIFIED or CLOSED
    if case is None or case["status"] not in ("CERTIFIED", "CLOSED"):
        raise errors.err(errors.ERR_INVALID_STATE, "Case must be CERTIFIED or CLOSED")

    rec["release_status"] = "APPROVED"
    rec["approver_user_id"] = actor.user_id

    # cascade: every HELD property item -> RELEASED
    count = 0
    for p in services.case_property_items(rec["case_id"]):
        if p["item_status"] == "HELD":
            p["item_status"] = "RELEASED"
            touch(p)
            count += 1
    rec["released_item_count"] = count
    touch(rec)
    return object_response(public(rec), 200)


@bp.post("/property-releases/<id_>/deny")
def deny_release(id_):
    require({"Investigator"})
    rec = lookup.property_release(id_)
    if rec["release_status"] != "REQUESTED":
        raise errors.err(errors.ERR_INVALID_STATE, "Deny only allowed from REQUESTED")
    rec["release_status"] = "DENIED"
    touch(rec)
    return object_response(public(rec), 200)


# ---- Indigent disposition ----
@bp.post("/cases/<case_id>/indigent-disposition")
def declare_indigent(case_id):
    require({"Investigator"})
    lookup.case(case_id)
    body = json_body()
    statutory_allowance_cents = validate.req_int(body, "statutory_allowance_cents", minimum=0)
    itemized_cost_cents = validate.req_int(body, "itemized_cost_cents", minimum=0)

    rec = make_record({
        "case_id": case_id,
        "statutory_allowance_cents": statutory_allowance_cents,
        "itemized_cost_cents": itemized_cost_cents,
        "county_payable_cents": 0,
        "disposition_status": "DECLARED",
    })
    db.indigent_dispositions[rec["id"]] = rec
    return object_response(public(rec), 201)


@bp.get("/cases/<case_id>/indigent-disposition")
def list_case_indigent(case_id):
    require({"Admin", "Investigator", "MedicalExaminer"})
    lookup.case(case_id)
    rows = [d for d in db.indigent_dispositions.values() if d["case_id"] == case_id]
    page, limit, offset, total = paginate(rows)
    return array_response([public(d) for d in page], limit, offset, total)


@bp.get("/indigent-dispositions/<id_>")
def get_indigent(id_):
    require({"Admin", "Investigator", "MedicalExaminer"})
    rec = lookup.indigent_disposition(id_)
    return object_response(public(rec), 200)


@bp.post("/indigent-dispositions/<id_>/approve")
def approve_indigent(id_):
    require({"MedicalExaminer"})
    rec = lookup.indigent_disposition(id_)

    if rec["disposition_status"] != "DECLARED":
        raise errors.err(errors.ERR_INVALID_STATE, "Approve only allowed from DECLARED")

    # no verified kin claimant (priority 41)
    if services.case_has_verified_kin(rec["case_id"]):
        raise errors.err(errors.ERR_KIN_CLAIMANT_EXISTS, "A verified next-of-kin claimant exists")

    # waterfall payable
    estate = sum(
        p["valuation_cents"] for p in services.case_property_items(rec["case_id"])
        if p["item_status"] == "HELD"
    )
    rec["county_payable_cents"] = calculations.indigent_county_payable(
        rec["itemized_cost_cents"], rec["statutory_allowance_cents"], estate
    )
    rec["disposition_status"] = "APPROVED"

    # cascade clear release_blocked on the case's body
    for b in services.case_bodies(rec["case_id"]):
        if b["release_blocked"]:
            b["release_blocked"] = False
            touch(b)

    touch(rec)
    return object_response(public(rec), 200)


@bp.post("/indigent-dispositions/<id_>/bury")
def bury_indigent(id_):
    require({"Investigator"})
    rec = lookup.indigent_disposition(id_)

    if rec["disposition_status"] != "APPROVED":
        raise errors.err(errors.ERR_INVALID_STATE, "Bury only allowed from APPROVED")

    body = services.case_body(rec["case_id"])
    if body is None or body["storage_status"] != "RELEASED":
        raise errors.err(errors.ERR_INVALID_STATE, "Case body must be RELEASED before burial")

    rec["disposition_status"] = "BURIED"

    # cascade remaining HELD property items -> ESCHEATED
    for p in services.case_property_items(rec["case_id"]):
        if p["item_status"] == "HELD":
            p["item_status"] = "ESCHEATED"
            touch(p)

    touch(rec)
    return object_response(public(rec), 200)
