"""Test clock + read-only endpoints for append-only / derived resources."""
from flask import Blueprint, request

import db
import errors
import store
import serializers as S
import middleware as M
from response import ok, ok_list

bp = Blueprint("misc", __name__)


# ---------------- Test clock ----------------

@bp.post("/rental/_clock/set")
def set_clock():
    body = M.get_json_body()
    M.require_fields(body, ["to_iso8601"])
    when = M.parse_dt(body["to_iso8601"], "to_iso8601")
    _, role = M.get_auth()
    M.require_role(role, {"ShopAdmin"})
    db.set_clock(when)
    # Mutates no business resource and returns no resource body.
    return ok({})


# ---------------- ReservationAddOn reads ----------------

@bp.get("/rental/reservation-addons")
def list_reservation_addons():
    _, role = M.get_auth()
    M.require_role(role, {"ShopAdmin", "RentalAgent", "Renter"})
    limit, offset = M.parse_pagination()
    items = list(db.reservation_addons.values())
    reservation_id = request.args.get("reservation_id")
    addon_id = request.args.get("addon_id")
    if reservation_id is not None:
        items = [r for r in items if r["reservation_id"] == reservation_id]
    if addon_id is not None:
        items = [r for r in items if r["addon_id"] == addon_id]
    page, total = store.paginate(items, limit, offset)
    return ok_list([S.reservation_addon(r) for r in page], limit, offset, total)


@bp.get("/rental/reservation-addons/<id>")
def get_reservation_addon(id):
    _, role = M.get_auth()
    M.require_role(role, {"ShopAdmin", "RentalAgent", "Renter"})
    rec = db.reservation_addons.get(id)
    if not rec:
        raise errors.not_found("reservation add-on not found")
    return ok(S.reservation_addon(rec))


# ---------------- ConditionReport reads ----------------

@bp.get("/rental/condition-reports/<id>")
def get_condition_report(id):
    _, role = M.get_auth()
    M.require_role(role, {"ShopAdmin", "RentalAgent", "Renter"})
    rec = db.condition_reports.get(id)
    if not rec:
        raise errors.not_found("condition report not found")
    return ok(S.condition_report(rec))


@bp.get("/rental/condition-reports")
def list_condition_reports():
    _, role = M.get_auth()
    M.require_role(role, {"ShopAdmin", "RentalAgent", "Renter"})
    limit, offset = M.parse_pagination()
    items = list(db.condition_reports.values())
    reservation_id = request.args.get("reservation_id")
    gear_unit_id = request.args.get("gear_unit_id")
    if reservation_id is not None:
        items = [r for r in items if r["reservation_id"] == reservation_id]
    if gear_unit_id is not None:
        items = [r for r in items if r["gear_unit_id"] == gear_unit_id]
    page, total = store.paginate(items, limit, offset)
    return ok_list([S.condition_report(r) for r in page], limit, offset, total)


# ---------------- DamageAssessment reads ----------------

@bp.get("/rental/damage-assessments/<id>")
def get_damage_assessment(id):
    _, role = M.get_auth()
    M.require_role(role, {"ShopAdmin", "RentalAgent", "Renter"})
    rec = db.damage_assessments.get(id)
    if not rec:
        raise errors.not_found("damage assessment not found")
    return ok(S.damage_assessment(rec))


@bp.get("/rental/damage-assessments")
def list_damage_assessments():
    _, role = M.get_auth()
    M.require_role(role, {"ShopAdmin", "RentalAgent", "Renter"})
    limit, offset = M.parse_pagination()
    items = list(db.damage_assessments.values())
    reservation_id = request.args.get("reservation_id")
    checkin_report_id = request.args.get("checkin_report_id")
    if reservation_id is not None:
        items = [r for r in items if r["reservation_id"] == reservation_id]
    if checkin_report_id is not None:
        items = [r for r in items if r["checkin_report_id"] == checkin_report_id]
    page, total = store.paginate(items, limit, offset)
    return ok_list([S.damage_assessment(r) for r in page], limit, offset, total)


# ---------------- LedgerEntry reads ----------------

@bp.get("/rental/ledger-entries/<id>")
def get_ledger_entry(id):
    _, role = M.get_auth()
    M.require_role(role, {"ShopAdmin", "RentalAgent", "Renter"})
    rec = db.ledger_entries.get(id)
    if not rec:
        raise errors.not_found("ledger entry not found")
    return ok(S.ledger_entry(rec))


@bp.get("/rental/ledger-entries")
def list_ledger_entries():
    _, role = M.get_auth()
    M.require_role(role, {"ShopAdmin", "RentalAgent", "Renter"})
    limit, offset = M.parse_pagination()
    items = list(db.ledger_entries.values())
    reservation_id = request.args.get("reservation_id")
    customer_id = request.args.get("customer_id")
    if reservation_id is not None:
        items = [r for r in items if r["reservation_id"] == reservation_id]
    if customer_id is not None:
        items = [r for r in items if r["customer_id"] == customer_id]
    page, total = store.paginate(items, limit, offset)
    return ok_list([S.ledger_entry(r) for r in page], limit, offset, total)
