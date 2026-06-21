"""Catalog & config routes: patrons, plans, slots, exhibits/sessions, partners."""
from flask import Blueprint, request

import db
import serializers as S
from errors import ApiError, ERR_EMAIL_TAKEN, not_found
from listing import list_response
from middleware import get_identity, require_role
from response import ok, created
from routes.helpers import resolve
from timeutil import parse_iso, format_iso
import validate as V

bp = Blueprint("catalog", __name__)


# --------------------------- Patron ---------------------------

@bp.post("/patrons")
def create_patron():
    _, role = get_identity()
    require_role(role, {"BoxOffice", "MembershipAdmin"})
    body = V.get_body()
    email = V.require_str(body, "email")
    full_name = V.require_str(body, "full_name")
    home_partner_id = V.opt_str(body, "home_partner_id", None)
    # Resolve home_partner_id if provided (left-to-right existence).
    if home_partner_id is not None:
        resolve(db.reciprocal_partners, home_partner_id)
    # Email uniqueness (priority 6).
    for p in db.patrons.values():
        if p["email"] == email:
            raise ApiError(ERR_EMAIL_TAKEN, 409, "Email already registered")
    rec = {"email": email, "full_name": full_name, "home_partner_id": home_partner_id}
    db.stamp_create(rec)
    db.patrons[rec["id"]] = rec
    return created(S.patron(db.public(rec)))


@bp.get("/patrons/<rid>")
def read_patron(rid):
    get_identity()
    rec = resolve(db.patrons, rid)
    return ok(S.patron(db.public(rec)))


@bp.get("/patrons")
def list_patrons():
    _, role = get_identity()
    require_role(role, {"BoxOffice", "MembershipAdmin"})
    filters = {
        "email": request.args.get("email"),
        "home_partner_id": request.args.get("home_partner_id"),
    }
    return list_response(db.patrons, lambda r: S.patron(db.public(r)), filters)


# --------------------------- MembershipPlan ---------------------------

VALID_TIERS = {"INDIVIDUAL", "DUAL", "HOUSEHOLD", "PATRON_CIRCLE"}


@bp.post("/membership-plans")
def create_plan():
    _, role = get_identity()
    require_role(role, {"MembershipAdmin"})
    body = V.get_body()
    rec = {
        "tier": V.require_enum(body, "tier", VALID_TIERS),
        "annual_fee_cents": V.require_int_nonneg(body, "annual_fee_cents"),
        "household_max": V.require_int_nonneg(body, "household_max"),
        "guest_passes_granted": V.require_int_nonneg(body, "guest_passes_granted"),
        "member_admission_cents": V.require_int_nonneg(body, "member_admission_cents"),
        "exhibit_surcharge_waived": V.opt_bool(body, "exhibit_surcharge_waived", False),
        "reciprocal_eligible": V.opt_bool(body, "reciprocal_eligible", False),
        "term_days": V.opt_int_min(body, "term_days", 1, 365),
        "reinstatement_fee_cents": V.opt_int_nonneg(body, "reinstatement_fee_cents", 0),
    }
    db.stamp_create(rec)
    db.membership_plans[rec["id"]] = rec
    return created(S.membership_plan(db.public(rec)))


@bp.get("/membership-plans/<rid>")
def read_plan(rid):
    get_identity()
    rec = resolve(db.membership_plans, rid)
    return ok(S.membership_plan(db.public(rec)))


@bp.get("/membership-plans")
def list_plans():
    get_identity()
    filters = {"tier": request.args.get("tier")}
    return list_response(db.membership_plans, lambda r: S.membership_plan(db.public(r)), filters)


# --------------------------- TimedEntrySlot ---------------------------

@bp.post("/timed-entry-slots")
def create_slot():
    _, role = get_identity()
    require_role(role, {"MembershipAdmin"})
    body = V.get_body()
    starts_at = parse_iso(V.require_str(body, "starts_at"))
    ends_at = parse_iso(V.require_str(body, "ends_at"))
    if not (ends_at > starts_at):
        raise ApiError("ERR_INVALID_REQUEST", 422, "ends_at must be after starts_at")
    rec = {
        "starts_at": format_iso(starts_at),
        "ends_at": format_iso(ends_at),
        "capacity_total": V.require_int_min(body, "capacity_total", 1),
        "reserved_count": 0,
        "status": "OPEN",
        "non_member_admission_cents": V.require_int_nonneg(body, "non_member_admission_cents"),
    }
    db.stamp_create(rec)
    db.timed_entry_slots[rec["id"]] = rec
    return created(S.timed_entry_slot(db.public(rec)))


@bp.get("/timed-entry-slots/<rid>")
def read_slot(rid):
    get_identity()
    rec = resolve(db.timed_entry_slots, rid)
    return ok(S.timed_entry_slot(db.public(rec)))


@bp.get("/timed-entry-slots")
def list_slots():
    get_identity()
    filters = {"status": request.args.get("status")}
    return list_response(db.timed_entry_slots, lambda r: S.timed_entry_slot(db.public(r)), filters)


@bp.post("/timed-entry-slots/<rid>/close")
def close_slot(rid):
    _, role = get_identity()
    require_role(role, {"MembershipAdmin"})
    rec = resolve(db.timed_entry_slots, rid)
    rec["status"] = "CLOSED"
    db.touch(rec)
    return ok(S.timed_entry_slot(db.public(rec)))


# --------------------------- SpecialExhibit + ExhibitSession ---------------------------

@bp.post("/special-exhibits")
def create_exhibit():
    _, role = get_identity()
    require_role(role, {"MembershipAdmin"})
    body = V.get_body()
    rec = {
        "name": V.require_str(body, "name"),
        "surcharge_cents": V.require_int_nonneg(body, "surcharge_cents"),
        "member_surcharge_discount_pct": V.opt_fraction(body, "member_surcharge_discount_pct", 0),
        "buffer_minutes": V.opt_int_nonneg(body, "buffer_minutes", 0),
    }
    db.stamp_create(rec)
    db.special_exhibits[rec["id"]] = rec
    return created(S.special_exhibit(db.public(rec)))


@bp.get("/special-exhibits/<rid>")
def read_exhibit(rid):
    get_identity()
    rec = resolve(db.special_exhibits, rid)
    return ok(S.special_exhibit(db.public(rec)))


@bp.get("/special-exhibits")
def list_exhibits():
    get_identity()
    return list_response(db.special_exhibits, lambda r: S.special_exhibit(db.public(r)), {})


@bp.post("/special-exhibits/<rid>/sessions")
def create_session(rid):
    _, role = get_identity()
    require_role(role, {"MembershipAdmin"})
    exhibit = resolve(db.special_exhibits, rid)
    body = V.get_body()
    starts_at = parse_iso(V.require_str(body, "starts_at"))
    ends_at = parse_iso(V.require_str(body, "ends_at"))
    if not (ends_at > starts_at):
        raise ApiError("ERR_INVALID_REQUEST", 422, "ends_at must be after starts_at")
    rec = {
        "exhibit_id": exhibit["id"],
        "starts_at": format_iso(starts_at),
        "ends_at": format_iso(ends_at),
        "capacity_total": V.require_int_min(body, "capacity_total", 1),
        "reserved_count": 0,
    }
    db.stamp_create(rec)
    db.exhibit_sessions[rec["id"]] = rec
    return created(S.exhibit_session(db.public(rec)))


@bp.get("/special-exhibits/<rid>/sessions")
def list_exhibit_sessions(rid):
    get_identity()
    exhibit = resolve(db.special_exhibits, rid)
    filters = {"exhibit_id": exhibit["id"]}
    return list_response(db.exhibit_sessions, lambda r: S.exhibit_session(db.public(r)), filters)


@bp.get("/exhibit-sessions/<rid>")
def read_session(rid):
    get_identity()
    rec = resolve(db.exhibit_sessions, rid)
    return ok(S.exhibit_session(db.public(rec)))


# --------------------------- ReciprocalPartner ---------------------------

VALID_BENEFIT = {"FREE", "DISCOUNT"}


@bp.post("/reciprocal-partners")
def create_partner():
    _, role = get_identity()
    require_role(role, {"MembershipAdmin"})
    body = V.get_body()
    rec = {
        "org_name": V.require_str(body, "org_name"),
        "benefit_type": V.require_enum(body, "benefit_type", VALID_BENEFIT),
        "discount_pct": V.opt_fraction(body, "discount_pct", 0),
    }
    db.stamp_create(rec)
    db.reciprocal_partners[rec["id"]] = rec
    return created(S.reciprocal_partner(db.public(rec)))


@bp.get("/reciprocal-partners/<rid>")
def read_partner(rid):
    get_identity()
    rec = resolve(db.reciprocal_partners, rid)
    return ok(S.reciprocal_partner(db.public(rec)))


@bp.get("/reciprocal-partners")
def list_partners():
    get_identity()
    return list_response(db.reciprocal_partners, lambda r: S.reciprocal_partner(db.public(r)), {})
