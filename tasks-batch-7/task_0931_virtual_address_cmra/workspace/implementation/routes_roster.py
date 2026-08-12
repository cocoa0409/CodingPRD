"""Roster members, Form 1583 applications and identification documents."""

from flask import Blueprint, g, request

import domain
import ladder as L
import serializers as S
import store
from errors import ApiError
from response import created, listing, ok, touch
from store import DB, insert
from util import (
    CLOCK, FORM_1583_VALIDITY_DAYS, STATUS_ENUMS, USPS_ROSTER_CAP, add_days, parse_date,
)

bp = Blueprint("roster", __name__)


# ------------------------------------------------------------------ roster
@bp.post("/boxes/<ident>/recipients")
@L.endpoint(roles=["CmraOperator"], primary="box")
def create_recipient(box):
    b = L.body()
    # rung 7 -- a guarantor_recipient_id supplied in the body resolves
    guarantor_id = b.get("guarantor_recipient_id")
    if guarantor_id is not None:
        if not isinstance(guarantor_id, str) or guarantor_id not in DB.recipients:
            raise ApiError("ERR_RECIPIENT_NOT_FOUND")
    legal_name = L.req_str(b, "legal_name")                       # rung 9
    L.req_present(b, "recipient_kind")
    aliases = L.opt_list(b, "dba_aliases", [])
    sig = L.req_bool(b, "signature_authorization_on_file", False)
    kind = L.enum_body(b, "recipient_kind", "recipient_kind")     # rung 10
    L.gate_a("recipient_create", box)                             # rung 11
    L.gate_b("recipient_create", box)                             # rung 12 (exempt)

    # rung 25 -- the guarantor pairing rule is symmetric and strict
    if kind == "MINOR":
        g_row = DB.recipients.get(guarantor_id) if guarantor_id else None
        if (g_row is None or g_row["box_id"] != box["id"]
                or g_row["recipient_kind"] == "MINOR"):
            raise ApiError("ERR_GUARANTOR_REQUIRED")
    elif guarantor_id is not None:
        raise ApiError("ERR_GUARANTOR_REQUIRED")

    # rung 26 -- roster capacity
    tier = store.tier_of_box(box)
    included = tier["included_recipients"] if tier else 0
    effective_cap = min(included + box["extra_recipient_slots"], USPS_ROSTER_CAP)
    occupied = sum(1 for r in store.recipients_of_box(box["id"])
                   if r["roster_status"] in ("PENDING", "AUTHORIZED", "SUSPENDED"))
    if occupied >= effective_cap:
        raise ApiError("ERR_ROSTER_CAP_EXCEEDED")

    row = insert(DB.recipients, {
        "box_id": box["id"], "legal_name": legal_name, "recipient_kind": kind,
        "dba_aliases": aliases, "guarantor_recipient_id": guarantor_id,
        "signature_authorization_on_file": sig,
        "roster_status": "PENDING", "release_eligibility": "BLOCKED",
        "blocked_reason": "NO_ACCEPTED_1583", "form_1583_accepted_at": None,
    })
    return created(S.recipient(row))


@bp.get("/boxes/<ident>/recipients")
@L.endpoint(roles=["PlatformAdmin", "CmraOperator", "ComplianceOfficer", "BoxHolder"],
            primary="box", scope=True)
def list_box_recipients(box):
    status = L.enum_query("roster_status", "roster_status")
    data = [r for r in store.recipients_of_box(box["id"])
            if status is None or r["roster_status"] == status]
    items, total, limit, offset = L.paginate(data, S.recipient)
    return listing(items, total, limit, offset)


@bp.get("/recipients")
@L.endpoint(roles=["PlatformAdmin", "CmraOperator", "ComplianceOfficer"])
def list_recipients():
    roster = L.enum_query("roster_status", "roster_status")
    elig = L.enum_query("release_eligibility", "release_eligibility")
    box_id = request.args.get("box_id")
    guarantor = request.args.get("guarantor_recipient_id")
    data = store.rows(DB.recipients)
    if box_id is not None:
        data = [r for r in data if r["box_id"] == box_id]
    if guarantor is not None:
        data = [r for r in data if r["guarantor_recipient_id"] == guarantor]
    if roster is not None:
        data = [r for r in data if r["roster_status"] == roster]
    if elig is not None:
        data = [r for r in data if r["release_eligibility"] == elig]
    items, total, limit, offset = L.paginate(data, S.recipient)
    return listing(items, total, limit, offset)


@bp.get("/recipients/<ident>")
@L.endpoint(roles=["PlatformAdmin", "CmraOperator", "ComplianceOfficer", "BoxHolder", "Recipient"],
            primary="recipient", scope=True)
def read_recipient(r):
    return ok(S.recipient(r))


@bp.patch("/recipients/<ident>")
@L.endpoint(roles=["CmraOperator"], primary="recipient")
def patch_recipient(r):
    b = L.body()
    aliases = b.get("dba_aliases")
    if aliases is not None:
        aliases = L.req_list(b, "dba_aliases")
    sig = b.get("signature_authorization_on_file")
    if sig is not None:
        sig = L.req_bool(b, "signature_authorization_on_file")
    L.gate_b("recipient_patch", store.box_of_recipient(r))
    if aliases is not None:
        r["dba_aliases"] = aliases
    if sig is not None:
        r["signature_authorization_on_file"] = sig
    touch(r)
    return ok(S.recipient(r))


@bp.post("/recipients/<ident>/remove")
@L.endpoint(roles=["CmraOperator"], primary="recipient")
def remove_recipient(r):
    box = store.box_of_recipient(r)
    L.gate_b("recipient_remove", box)
    if r["roster_status"] not in ("PENDING", "AUTHORIZED", "SUSPENDED"):
        raise ApiError("ERR_INVALID_STATE")
    for other in store.recipients_of_box(r["box_id"]):
        if other["guarantor_recipient_id"] == r["id"] and other["roster_status"] != "REMOVED":
            raise ApiError("ERR_INVALID_STATE",
                           "A guarantor cannot be removed while it still guarantees a member.")
    if r["roster_status"] == "AUTHORIZED":
        for item in store.mail_items_of_box(r["box_id"]):
            if (item["matched_recipient_id"] == r["id"]
                    and item["handling_status"] in ("AWAITING_CLEARANCE", "HELD",
                                                    "PENDING_DISPOSITION")):
                raise ApiError("ERR_INVALID_STATE", "Live custody must be cleared first.")
        r["release_eligibility"] = "BLOCKED"
        r["blocked_reason"] = "NO_ACCEPTED_1583"
    r["roster_status"] = "REMOVED"
    touch(r)
    return ok(S.recipient(r))


# ------------------------------------------------------------------ Form 1583
@bp.post("/recipients/<ident>/form-1583")
@L.endpoint(roles=["CmraOperator"], primary="recipient")
def create_form(r):
    b = L.body()
    line = L.req_str(b, "home_address_line")
    L.gate_b("form_create", store.box_of_recipient(r))
    row = insert(DB.form1583s, {
        "recipient_id": r["id"], "home_address_line": line, "status": "DRAFT",
        "notarized_at": None, "notary_user_id": None, "accepted_on": None,
        "expires_on": None, "accepted_by_user_id": None, "rejection_reason": None,
    })
    return created(S.form1583(row))


@bp.get("/recipients/<ident>/form-1583")
@L.endpoint(roles=["PlatformAdmin", "CmraOperator", "ComplianceOfficer", "BoxHolder"],
            primary="recipient", scope=True)
def list_forms(r):
    status = L.enum_query("status", members=STATUS_ENUMS["form1583"])
    data = [f for f in store.forms_of_recipient(r["id"])
            if status is None or f["status"] == status]
    items, total, limit, offset = L.paginate(data, S.form1583)
    return listing(items, total, limit, offset)


@bp.get("/form-1583/<ident>")
@L.endpoint(roles=["PlatformAdmin", "CmraOperator", "ComplianceOfficer", "Notary"],
            primary="form1583")
def read_form(f):
    return ok(S.form1583(f))


@bp.post("/form-1583/<ident>/notarize")
@L.endpoint(roles=["Notary"], primary="form1583")
def notarize_form(f):
    L.gate_b("form_notarize", store.box_of_form(f))
    if f["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE")
    f["status"] = "NOTARIZED"
    f["notarized_at"] = CLOCK.now
    f["notary_user_id"] = g.user_id
    touch(f)
    return ok(S.form1583(f))


@bp.post("/form-1583/<ident>/accept")
@L.endpoint(roles=["ComplianceOfficer"], primary="form1583")
def accept_form(f):
    r = store.recipient(f["recipient_id"])
    box = store.box_of_recipient(r)
    L.gate_b("form_accept", box)                                  # rung 12
    if f["status"] != "NOTARIZED":                                # rung 14
        raise ApiError("ERR_INVALID_STATE")
    if f["notary_user_id"] is not None and g.user_id == f["notary_user_id"]:   # rung 15
        raise ApiError("ERR_UNAUTHORIZED",
                       "The acceptor may not be the notary who witnessed the form.")
    has_photo = any(d["doc_class"] == "PHOTO" and d["status"] == "VERIFIED"
                    for d in store.docs_of_recipient(r["id"]))
    if not has_photo:
        raise ApiError("ERR_INVALID_STATE",
                       "The member holds no VERIFIED PHOTO identification document.")
    meters = r["roster_status"] == "PENDING"
    if meters and box is not None:                                # rung 36
        domain.raise_quota(box, "RECIPIENT", 1)

    f["status"] = "ACCEPTED"
    f["accepted_on"] = CLOCK.date()
    f["accepted_by_user_id"] = g.user_id
    f["expires_on"] = add_days(f["accepted_on"], FORM_1583_VALIDITY_DAYS)
    touch(f)
    r["form_1583_accepted_at"] = CLOCK.now
    touch(r)
    if meters:
        r["roster_status"] = "AUTHORIZED"
        if box is not None:
            domain.meter(box, "RECIPIENT", 1, "RECIPIENT_AUTHORIZED")
    domain.rederive_eligibility(r)
    return ok(S.form1583(f))


@bp.post("/form-1583/<ident>/reject")
@L.endpoint(roles=["ComplianceOfficer"], primary="form1583")
def reject_form(f):
    b = L.body()
    L.req_present(b, "rejection_reason")
    reason = L.enum_body(b, "rejection_reason", "rejection_reason")
    L.gate_b("form_reject", store.box_of_form(f))
    if f["status"] != "NOTARIZED":
        raise ApiError("ERR_INVALID_STATE")
    f["status"] = "REJECTED"
    f["rejection_reason"] = reason
    touch(f)
    return ok(S.form1583(f))


# ------------------------------------------------------------------ id documents
@bp.post("/recipients/<ident>/id-documents")
@L.endpoint(roles=["CmraOperator"], primary="recipient")
def create_id_document(r):
    b = L.body()
    L.req_present(b, "doc_class")
    L.req_present(b, "doc_type")
    expires_raw = L.req_str(b, "expires_on")
    expires = parse_date(expires_raw)
    if expires is None:
        L._bad("expires_on", "must be a YYYY-MM-DD calendar date")
    doc_class = L.enum_body(b, "doc_class", "doc_class")
    doc_type = L.enum_body(b, "doc_type", "doc_type")
    L.gate_b("id_document_create", store.box_of_recipient(r))
    row = insert(DB.id_documents, {
        "recipient_id": r["id"], "doc_class": doc_class, "doc_type": doc_type,
        "expires_on": expires_raw, "_expires_date": expires,
        "status": "PENDING_REVIEW", "verified_at": None,
    })
    return created(S.id_document(row))


@bp.get("/recipients/<ident>/id-documents")
@L.endpoint(roles=["PlatformAdmin", "CmraOperator", "ComplianceOfficer", "BoxHolder"],
            primary="recipient", scope=True)
def list_id_documents(r):
    doc_class = L.enum_query("doc_class", "doc_class")
    status = L.enum_query("status", members=STATUS_ENUMS["id_document"])
    data = store.docs_of_recipient(r["id"])
    if doc_class is not None:
        data = [d for d in data if d["doc_class"] == doc_class]
    if status is not None:
        data = [d for d in data if d["status"] == status]
    items, total, limit, offset = L.paginate(data, S.id_document)
    return listing(items, total, limit, offset)


@bp.post("/id-documents/<ident>/verify")
@L.endpoint(roles=["CmraOperator"], primary="id_document")
def verify_id_document(d):
    r = store.recipient(d["recipient_id"])
    L.gate_b("id_document_verify", store.box_of_recipient(r))
    if d["status"] != "PENDING_REVIEW":
        raise ApiError("ERR_INVALID_STATE")
    if d["_expires_date"] is None or CLOCK.date() > d["_expires_date"]:
        raise ApiError("ERR_INVALID_STATE",
                       "A document may be verified on its expiry date but not the day after.")
    d["status"] = "VERIFIED"
    d["verified_at"] = CLOCK.now
    touch(d)
    for other in store.docs_of_recipient(r["id"]):
        if (other["id"] != d["id"] and other["doc_class"] == d["doc_class"]
                and other["status"] == "VERIFIED"):
            other["status"] = "SUPERSEDED"
            touch(other)
    domain.rederive_eligibility(r)
    return ok(S.id_document(d))
