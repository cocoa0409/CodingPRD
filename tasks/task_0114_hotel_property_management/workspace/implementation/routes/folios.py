"""Folio reads + dispute/resolve; Incidental post/get/list/void (PRD §3.6)."""
from flask import Blueprint

import calc
import db
import helpers as H
import serialize as S
from errors import err
from middleware import authenticate, require_role
from response import success, success_list

bp = Blueprint("folios", __name__)

ALL_ROLES = {"RevenueManager", "FrontDeskAgent", "NightAuditor", "Guest"}


def _guest_owns_folio_or_raise(role, user_id, folio):
    if role == "Guest":
        rv = db.reservations.get(folio["reservation_id"])
        if rv is None or rv["guest_id"] != user_id:
            raise err("ERR_FORBIDDEN", "Guest may only read their own folio")


# ----------------------------------------------------------------------------
# Folio reads
# ----------------------------------------------------------------------------
@bp.route("/pms/folios/<resource_id>", methods=["GET"])
def get_folio(resource_id):
    user_id, role = authenticate()
    require_role(role, ALL_ROLES)
    f = H.get_or_404(db.folios, resource_id)
    _guest_owns_folio_or_raise(role, user_id, f)
    return success(S.folio_out(f), status=200)


@bp.route("/pms/folios", methods=["GET"])
def list_folios():
    user_id, role = authenticate()
    require_role(role, ALL_ROLES)
    items, limit, offset, total = H.filter_and_paginate(
        db.folios,
        S.folio_out,
        {
            "hotel_id": H.qparam("hotel_id"),
            "reservation_id": H.qparam("reservation_id"),
            "status": H.qparam("status"),
        },
    )
    # Guest scoping handled post-filter to keep ownership semantics (PRD §2.1)
    if role == "Guest":
        owned_ids = set(rv["id"] for rv in db.reservations.values() if rv["guest_id"] == user_id)
        all_items = [f for f in db.folios.values() if f["reservation_id"] in owned_ids]
        # re-apply filters
        for field, value in {
            "hotel_id": H.qparam("hotel_id"),
            "reservation_id": H.qparam("reservation_id"),
            "status": H.qparam("status"),
        }.items():
            if value is not None:
                all_items = [f for f in all_items if f.get(field) == value]
        all_items.sort(key=lambda it: (it["created_at"], it["_seq"]))
        total = len(all_items)
        page = all_items[offset : offset + limit]
        items = [S.folio_out(f) for f in page]
    return success_list(items, limit, offset, total)


# ----------------------------------------------------------------------------
# Dispute / resolve
# ----------------------------------------------------------------------------
@bp.route("/pms/folios/<resource_id>/dispute", methods=["POST"])
def dispute_folio(resource_id):
    _, role = authenticate()
    require_role(role, {"FrontDeskAgent"})
    f = H.get_or_404(db.folios, resource_id)
    hotel = db.hotels[f["hotel_id"]]
    if hotel["posture"] != "OPEN":
        raise err("ERR_HOTEL_AUDIT_LOCKED", "Hotel is in AUDIT_LOCK posture")
    if f["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Folio is not OPEN")
    f["status"] = "DISPUTED"
    db.touch(f)
    return success(S.folio_out(f), status=200)


@bp.route("/pms/folios/<resource_id>/resolve", methods=["POST"])
def resolve_folio(resource_id):
    _, role = authenticate()
    require_role(role, {"FrontDeskAgent"})
    f = H.get_or_404(db.folios, resource_id)
    hotel = db.hotels[f["hotel_id"]]
    if hotel["posture"] != "OPEN":
        raise err("ERR_HOTEL_AUDIT_LOCKED", "Hotel is in AUDIT_LOCK posture")
    if f["status"] != "DISPUTED":
        raise err("ERR_INVALID_STATE", "Folio is not DISPUTED")
    f["status"] = "OPEN"
    db.touch(f)
    return success(S.folio_out(f), status=200)


# ----------------------------------------------------------------------------
# Incidentals
# ----------------------------------------------------------------------------
INCIDENTAL_KINDS = {"CHARGE", "PAYMENT", "ADJUSTMENT"}


@bp.route("/pms/incidentals", methods=["POST"])
def post_incidental():
    _, role = authenticate()
    require_role(role, {"FrontDeskAgent"})
    body = H.get_json_body()
    H.require_fields(body, ["hotel_id", "folio_id", "kind", "description", "amount_cents"])
    H.resolve_fk(body, "hotel_id")
    folio = H.resolve_fk(body, "folio_id")
    kind = body["kind"]
    H.require_enum(kind, INCIDENTAL_KINDS, "kind")
    description = H.require_str(body, "description")
    amount_cents = H.require_int(body, "amount_cents", min_value=0)

    hotel = db.hotels[folio["hotel_id"]]
    if hotel["posture"] != "OPEN":
        raise err("ERR_HOTEL_AUDIT_LOCKED", "Hotel is in AUDIT_LOCK posture")
    if folio["status"] != "OPEN":
        raise err("ERR_FOLIO_NOT_OPEN", "Folio is not OPEN")

    # PAYMENT lines stored negative; CHARGE/ADJUSTMENT positive.
    stored_amount = -amount_cents if kind == "PAYMENT" else amount_cents

    inc = {
        "hotel_id": body["hotel_id"],
        "folio_id": body["folio_id"],
        "kind": kind,
        "description": description,
        "amount_cents": stored_amount,
        "posted_by_kind": "AGENT",
        "status": "POSTED",
    }
    db.stamp_create(inc)
    db.incidentals[inc["id"]] = inc

    # Folio totals are computed live; the post is a real mutation on the folio,
    # so refresh its updated_at / version.
    db.touch(folio)
    return success(S.incidental_out(inc), status=201)


@bp.route("/pms/incidentals/<resource_id>", methods=["GET"])
def get_incidental(resource_id):
    user_id, role = authenticate()
    require_role(role, ALL_ROLES)
    inc = H.get_or_404(db.incidentals, resource_id)
    if role == "Guest":
        folio = db.folios.get(inc["folio_id"])
        if folio is None:
            raise err("ERR_FORBIDDEN", "Guest may only read their own data")
        _guest_owns_folio_or_raise(role, user_id, folio)
    return success(S.incidental_out(inc), status=200)


@bp.route("/pms/incidentals", methods=["GET"])
def list_incidentals():
    user_id, role = authenticate()
    require_role(role, ALL_ROLES)
    limit, offset = H.parse_pagination()
    items = list(db.incidentals.values())
    if role == "Guest":
        owned_folio_ids = set()
        owned_res = set(rv["id"] for rv in db.reservations.values() if rv["guest_id"] == user_id)
        for f in db.folios.values():
            if f["reservation_id"] in owned_res:
                owned_folio_ids.add(f["id"])
        items = [i for i in items if i["folio_id"] in owned_folio_ids]
    for field, value in {
        "hotel_id": H.qparam("hotel_id"),
        "folio_id": H.qparam("folio_id"),
        "kind": H.qparam("kind"),
        "status": H.qparam("status"),
    }.items():
        if value is not None:
            items = [i for i in items if i.get(field) == value]
    items.sort(key=lambda it: (it["created_at"], it["_seq"]))
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([S.incidental_out(i) for i in page], limit, offset, total)


@bp.route("/pms/incidentals/<resource_id>/void", methods=["POST"])
def void_incidental(resource_id):
    _, role = authenticate()
    require_role(role, {"FrontDeskAgent"})
    inc = H.get_or_404(db.incidentals, resource_id)
    body = H.get_json_body()
    H.require_fields(body, ["expected_folio_version"])
    expected = H.require_int(body, "expected_folio_version")

    folio = db.folios[inc["folio_id"]]
    hotel = db.hotels[folio["hotel_id"]]
    if hotel["posture"] != "OPEN":
        raise err("ERR_HOTEL_AUDIT_LOCKED", "Hotel is in AUDIT_LOCK posture")
    if folio["status"] != "OPEN":
        raise err("ERR_FOLIO_NOT_OPEN", "Folio is not OPEN")
    if inc["status"] != "POSTED":
        raise err("ERR_INVALID_STATE", "Incidental is not POSTED")
    if expected != folio["version"]:
        raise err("ERR_STALE_VERSION", "expected_folio_version does not match")

    inc["status"] = "VOIDED"
    db.touch(inc)
    db.touch(folio)
    return success(S.incidental_out(inc), status=200)
