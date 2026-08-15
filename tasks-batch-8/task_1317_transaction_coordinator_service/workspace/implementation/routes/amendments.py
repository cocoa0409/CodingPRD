"""Amendments: draft / route / revise / apply / void."""
from flask import Blueprint, request

import errors as E
import middleware as mw
from db import store, mint, touch, pub, pub_list
from response import ok_object, ok_list
from services import calc, cascade
from util import parse_date

bp = Blueprint("amendments", __name__)

IN_FLIGHT = ("ROUTED", "PARTIALLY_SIGNED", "FULLY_SIGNED")
VOIDABLE = ("DRAFT", "ROUTED", "PARTIALLY_SIGNED", "FULLY_SIGNED")


def _windows_overlap(a_from, a_to, b_from, b_to):
    # Half-open [from, to): sharing exactly one boundary date is allowed.
    return parse_date(a_from) < parse_date(b_to) and parse_date(b_from) < parse_date(a_to)


@bp.post("/tc/amendments")
def create_amendment():
    uid, role = mw.auth()
    mw.require_roles(role, {"Coordinator"})
    data = mw.body()
    # priority 3: body FK existence
    file_rec = None
    if data.get("file_id") is not None:
        file_rec = mw.get_or_404("file", data["file_id"])
    # priority 4: ownership
    if file_rec is not None:
        mw.own_file(uid, file_rec)
    # priority 5: OCC on file version
    expected = data.get("expected_file_version")
    if file_rec is not None and isinstance(expected, int) and not isinstance(expected, bool):
        if expected != file_rec["version"]:
            E.raise_err(E.ERR_STALE_FILE_VERSION,
                        "expected_file_version does not match the file version")
    # priority 8: temporal sanity (amendment date in past, then window validity)
    if isinstance(data.get("new_closing_date"), str) and mw.is_date_str(data["new_closing_date"]):
        if parse_date(data["new_closing_date"]) < store.now.date():
            E.raise_err(E.ERR_AMENDMENT_DATE_IN_PAST,
                        "new_closing_date is before the current clock date")
    if mw.is_date_str(data.get("effective_from")) and mw.is_date_str(data.get("effective_to")):
        if not (parse_date(data["effective_to"]) > parse_date(data["effective_from"])):
            E.raise_err(E.ERR_INVALID_AMENDMENT_WINDOW,
                        "effective_to must be strictly after effective_from")
    # priority 9: window overlap vs amendments ROUTED/PARTIALLY_SIGNED/FULLY_SIGNED/EFFECTIVE
    if file_rec is not None and mw.is_date_str(data.get("effective_from")) \
            and mw.is_date_str(data.get("effective_to")):
        for a in store.amendments.values():
            if a["file_id"] != file_rec["id"] or a["status"] not in IN_FLIGHT + ("EFFECTIVE",):
                continue
            if _windows_overlap(data["effective_from"], data["effective_to"],
                                a["effective_from"], a["effective_to"]):
                E.raise_err(E.ERR_AMENDMENT_WINDOW_OVERLAP,
                            "Amendment window overlaps another in-flight or EFFECTIVE amendment")
    # priority 12: shape
    mw.validate_shape(data, [
        ("file_id", "string", True),
        ("expected_file_version", "int", True),
        ("effective_from", "date", True),
        ("effective_to", "date", True),
        ("new_effective_date", "date", False),
        ("new_closing_date", "date", False),
        ("new_list_price_cents", "int", False),
    ])
    # side effects: supersede an existing DRAFT amendment, create new DRAFT round 1,
    # bump file version.
    for a in list(store.amendments.values()):
        if a["file_id"] == file_rec["id"] and a["status"] == "DRAFT":
            cascade.void_amendment(a)
    rec = mint({
        "file_id": file_rec["id"],
        "round_number": 1,
        "new_effective_date": data.get("new_effective_date"),
        "new_closing_date": data.get("new_closing_date"),
        "new_list_price_cents": data.get("new_list_price_cents"),
        "effective_from": data["effective_from"],
        "effective_to": data["effective_to"],
        "status": "DRAFT",
    })
    store.amendments[rec["id"]] = rec
    touch(file_rec)
    return ok_object(pub("amendment", rec), 201)


@bp.get("/tc/amendments/<amendmentId>")
def get_amendment(amendmentId):
    mw.auth()
    rec = mw.get_or_404("amendment", amendmentId)
    return ok_object(pub("amendment", rec))


@bp.get("/tc/amendments")
def list_amendments():
    mw.auth()
    limit, offset = mw.page_params()
    recs = list(store.amendments.values())
    recs = mw.filter_eq(recs, "file_id", request.args.get("file_id"))
    recs = mw.filter_eq(recs, "status", request.args.get("status"))
    page, total = mw.apply_page(recs, limit, offset)
    return ok_list(pub_list("amendment", page), limit, offset, total)


@bp.post("/tc/amendments/<amendmentId>/route")
def route_amendment(amendmentId):
    uid, role = mw.auth()
    mw.require_roles(role, {"Coordinator"})
    rec = mw.get_or_404("amendment", amendmentId)
    file_rec = mw.own_file_chain(uid, rec, "amendment")
    if rec["status"] != "DRAFT":
        E.raise_err(E.ERR_AMENDMENT_INVALID_STATE, "Only a DRAFT amendment can be routed")
    if file_rec is None or file_rec["status"] != "ACTIVE":
        E.raise_err(E.ERR_FILE_NOT_ACTIVE, "Owning file must be ACTIVE")
    for a in store.amendments.values():
        if a["file_id"] == rec["file_id"] and a["id"] != rec["id"] and a["status"] in IN_FLIGHT:
            E.raise_err(E.ERR_AMENDMENT_IN_FLIGHT,
                        "Another amendment of this file is already in flight")
    rec["status"] = "ROUTED"
    touch(rec)
    signers = []
    if file_rec["contract_type"] == "PURCHASE_SALE" and file_rec.get("buyer_agent_id"):
        signers.append((file_rec["buyer_agent_id"], "BUYER_AGENT"))
    signers.append((file_rec["seller_agent_id"], "SELLER_AGENT"))
    for agent_id, party in signers:
        sr = mint({
            "amendment_id": rec["id"],
            "agent_id": agent_id,
            "signer_party": party,
            "round_number": rec["round_number"],
            "status": "PENDING",
            "signed_at": None,
        })
        store.signature_requests[sr["id"]] = sr
    return ok_object(pub("amendment", rec))


@bp.post("/tc/amendments/<amendmentId>/revise")
def revise_amendment(amendmentId):
    uid, role = mw.auth()
    mw.require_roles(role, {"Coordinator"})
    rec = mw.get_or_404("amendment", amendmentId)
    mw.own_file_chain(uid, rec, "amendment")
    if rec["status"] != "REJECTED":
        E.raise_err(E.ERR_AMENDMENT_INVALID_STATE, "Only a REJECTED amendment can be revised")
    rec["status"] = "DRAFT"
    rec["round_number"] += 1
    touch(rec)
    return ok_object(pub("amendment", rec))


@bp.post("/tc/amendments/<amendmentId>/apply")
def apply_amendment(amendmentId):
    uid, role = mw.auth()
    mw.require_roles(role, {"Coordinator"})
    rec = mw.get_or_404("amendment", amendmentId)
    file_rec = mw.own_file_chain(uid, rec, "amendment")
    if rec["status"] != "FULLY_SIGNED":
        E.raise_err(E.ERR_AMENDMENT_INVALID_STATE,
                    "Only a FULLY_SIGNED amendment can be applied")
    # Link 1: payload lands on the file.
    effective_changed = rec.get("new_effective_date") is not None
    if effective_changed:
        file_rec["effective_date"] = rec["new_effective_date"]
    if rec.get("new_closing_date") is not None:
        file_rec["closing_date"] = rec["new_closing_date"]
    if rec.get("new_list_price_cents") is not None:
        file_rec["list_price_cents"] = rec["new_list_price_cents"]
    touch(file_rec)
    # Link 2: effective_date change recomputes non-terminal milestones and PENDING deadlines.
    if effective_changed:
        for m in store.milestones.values():
            if m["file_id"] == file_rec["id"] and m["status"] in ("PENDING", "IN_PROGRESS", "OVERDUE"):
                new_due = calc.milestone_due_date(file_rec["effective_date"], m["offset_days"])
                if new_due != m["due_date"]:
                    m["due_date"] = new_due
                    touch(m)
        for d in store.deadlines.values():
            if d["file_id"] == file_rec["id"] and d["status"] == "PENDING":
                new_due = calc.deadline_due_date(file_rec["effective_date"], d["offset_days"],
                                                 file_rec["state_code"])
                d["due_date"] = new_due
                touch(d)
                # Link 3: regenerate reminders (SENT preserved).
                calc.regenerate_reminders(d)
    rec["status"] = "EFFECTIVE"
    touch(rec)
    return ok_object(pub("amendment", rec))


@bp.post("/tc/amendments/<amendmentId>/void")
def void_amendment(amendmentId):
    uid, role = mw.auth()
    mw.require_roles(role, {"Coordinator"})
    rec = mw.get_or_404("amendment", amendmentId)
    mw.own_file_chain(uid, rec, "amendment")
    if rec["status"] not in VOIDABLE:
        E.raise_err(E.ERR_AMENDMENT_INVALID_STATE,
                    "Only a DRAFT, ROUTED, PARTIALLY_SIGNED, or FULLY_SIGNED amendment can be voided")
    cascade.void_amendment(rec)
    return ok_object(pub("amendment", rec))
