"""Reverse-reachability reads: bare-id GETs and nested collection reads off
bare ids (PRD §2.7). Same envelope, pagination, and read-permission rules as
the district-rooted reads."""
from flask import Blueprint, request

import db
from middleware import ALL_ROLES, get_bare, require_roles
from response import ok_list, ok_object, paginate
from services import (ser_area, ser_boil_order, ser_cycle, ser_invoice,
                      ser_master, ser_member, ser_notification, ser_payment,
                      ser_petition, ser_reading, ser_reserve_entry,
                      ser_sample, ser_schedule, ser_tap)

bp = Blueprint("reverse", __name__)


def _list(items, ser):
    page, limit, offset, total = paginate(items, request.args)
    return ok_list([ser(x) for x in page], limit, offset, total)


# ------------------------------------------------------------- bare-id reads

@bp.get("/rate-schedules/<entity_id>")
@require_roles(ALL_ROLES)
def get_schedule_bare(user_id, role, entity_id):
    return ok_object(ser_schedule(get_bare(db.rate_schedules, entity_id, "ERR_SCHEDULE_NOT_FOUND", "RateSchedule")))


@bp.get("/service-areas/<entity_id>")
@require_roles(ALL_ROLES)
def get_area_bare(user_id, role, entity_id):
    return ok_object(ser_area(get_bare(db.service_areas, entity_id, "ERR_AREA_NOT_FOUND", "ServiceArea")))


@bp.get("/members/<entity_id>")
@require_roles(ALL_ROLES)
def get_member_bare(user_id, role, entity_id):
    return ok_object(ser_member(get_bare(db.members, entity_id, "ERR_MEMBER_NOT_FOUND", "Member")))


@bp.get("/taps/<entity_id>")
@require_roles(ALL_ROLES)
def get_tap_bare(user_id, role, entity_id):
    return ok_object(ser_tap(get_bare(db.taps, entity_id, "ERR_TAP_NOT_FOUND", "TapConnection")))


@bp.get("/billing-cycles/<entity_id>")
@require_roles(ALL_ROLES)
def get_cycle_bare(user_id, role, entity_id):
    return ok_object(ser_cycle(get_bare(db.billing_cycles, entity_id, "ERR_CYCLE_NOT_FOUND", "BillingCycle")))


@bp.get("/invoices/<entity_id>")
@require_roles(ALL_ROLES)
def get_invoice_bare(user_id, role, entity_id):
    return ok_object(ser_invoice(get_bare(db.invoices, entity_id, "ERR_INVOICE_NOT_FOUND", "Invoice")))


@bp.get("/boil-orders/<entity_id>")
@require_roles(ALL_ROLES)
def get_order_bare(user_id, role, entity_id):
    return ok_object(ser_boil_order(get_bare(db.boil_orders, entity_id, "ERR_ORDER_NOT_FOUND", "BoilOrder")))


# -------------------------------------------- nested collections off bare ids

@bp.get("/service-areas/<entity_id>/members")
@require_roles(ALL_ROLES)
def area_members(user_id, role, entity_id):
    a = get_bare(db.service_areas, entity_id, "ERR_AREA_NOT_FOUND", "ServiceArea")
    return _list([m for m in db.members.values() if m["service_area_id"] == a["id"]], ser_member)


@bp.get("/service-areas/<entity_id>/annexation-petitions")
@require_roles(ALL_ROLES)
def area_petitions(user_id, role, entity_id):
    a = get_bare(db.service_areas, entity_id, "ERR_AREA_NOT_FOUND", "ServiceArea")
    return _list([p for p in db.petitions.values() if p["parent_service_area_id"] == a["id"]], ser_petition)


@bp.get("/members/<entity_id>/taps")
@require_roles(ALL_ROLES)
def member_taps(user_id, role, entity_id):
    m = get_bare(db.members, entity_id, "ERR_MEMBER_NOT_FOUND", "Member")
    return _list([t for t in db.taps.values() if t["member_id"] == m["id"]], ser_tap)


@bp.get("/members/<entity_id>/invoices")
@require_roles(ALL_ROLES)
def member_invoices(user_id, role, entity_id):
    m = get_bare(db.members, entity_id, "ERR_MEMBER_NOT_FOUND", "Member")
    return _list([i for i in db.invoices.values() if i["member_id"] == m["id"]], ser_invoice)


@bp.get("/members/<entity_id>/payments")
@require_roles(ALL_ROLES)
def member_payments(user_id, role, entity_id):
    m = get_bare(db.members, entity_id, "ERR_MEMBER_NOT_FOUND", "Member")
    return _list([p for p in db.payments.values() if p["member_id"] == m["id"]], ser_payment)


@bp.get("/members/<entity_id>/notifications")
@require_roles(ALL_ROLES)
def member_notifications(user_id, role, entity_id):
    m = get_bare(db.members, entity_id, "ERR_MEMBER_NOT_FOUND", "Member")
    return _list([n for n in db.notifications.values() if n["member_id"] == m["id"]], ser_notification)


@bp.get("/taps/<entity_id>/meter-readings")
@require_roles(ALL_ROLES)
def tap_readings(user_id, role, entity_id):
    t = get_bare(db.taps, entity_id, "ERR_TAP_NOT_FOUND", "TapConnection")
    return _list([r for r in db.readings.values() if r["tap_id"] == t["id"]], ser_reading)


@bp.get("/taps/<entity_id>/invoices")
@require_roles(ALL_ROLES)
def tap_invoices(user_id, role, entity_id):
    t = get_bare(db.taps, entity_id, "ERR_TAP_NOT_FOUND", "TapConnection")
    return _list([i for i in db.invoices.values() if i["tap_id"] == t["id"]], ser_invoice)


@bp.get("/billing-cycles/<entity_id>/meter-readings")
@require_roles(ALL_ROLES)
def cycle_readings(user_id, role, entity_id):
    c = get_bare(db.billing_cycles, entity_id, "ERR_CYCLE_NOT_FOUND", "BillingCycle")
    return _list([r for r in db.readings.values() if r["cycle_id"] == c["id"]], ser_reading)


@bp.get("/billing-cycles/<entity_id>/master-meter-readings")
@require_roles(ALL_ROLES)
def cycle_masters(user_id, role, entity_id):
    c = get_bare(db.billing_cycles, entity_id, "ERR_CYCLE_NOT_FOUND", "BillingCycle")
    return _list([r for r in db.master_readings.values() if r["cycle_id"] == c["id"]], ser_master)


@bp.get("/billing-cycles/<entity_id>/invoices")
@require_roles(ALL_ROLES)
def cycle_invoices(user_id, role, entity_id):
    c = get_bare(db.billing_cycles, entity_id, "ERR_CYCLE_NOT_FOUND", "BillingCycle")
    return _list([i for i in db.invoices.values() if i["cycle_id"] == c["id"]], ser_invoice)


@bp.get("/billing-cycles/<entity_id>/reserve-entries")
@require_roles(ALL_ROLES)
def cycle_reserve_entries(user_id, role, entity_id):
    c = get_bare(db.billing_cycles, entity_id, "ERR_CYCLE_NOT_FOUND", "BillingCycle")
    return _list([e for e in db.reserve_entries.values() if e["cycle_id"] == c["id"]], ser_reserve_entry)


@bp.get("/invoices/<entity_id>/payments")
@require_roles(ALL_ROLES)
def invoice_payments(user_id, role, entity_id):
    inv = get_bare(db.invoices, entity_id, "ERR_INVOICE_NOT_FOUND", "Invoice")
    return _list([p for p in db.payments.values() if p["invoice_id"] == inv["id"]], ser_payment)


@bp.get("/boil-orders/<entity_id>/notifications")
@require_roles(ALL_ROLES)
def order_notifications(user_id, role, entity_id):
    o = get_bare(db.boil_orders, entity_id, "ERR_ORDER_NOT_FOUND", "BoilOrder")
    return _list([n for n in db.notifications.values() if n["boil_order_id"] == o["id"]], ser_notification)


@bp.get("/boil-orders/<entity_id>/compliance-samples")
@require_roles(ALL_ROLES)
def order_samples(user_id, role, entity_id):
    o = get_bare(db.boil_orders, entity_id, "ERR_ORDER_NOT_FOUND", "BoilOrder")
    return _list([s for s in db.samples.values() if s["boil_order_id"] == o["id"]], ser_sample)


@bp.get("/rate-schedules/<entity_id>/invoices")
@require_roles(ALL_ROLES)
def schedule_invoices(user_id, role, entity_id):
    s = get_bare(db.rate_schedules, entity_id, "ERR_SCHEDULE_NOT_FOUND", "RateSchedule")
    return _list([i for i in db.invoices.values() if i["rate_schedule_id"] == s["id"]], ser_invoice)
