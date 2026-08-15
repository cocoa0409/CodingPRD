"""Domain helpers: entity lookup, cascade logic shared across routes."""

import db
from errors import (
    ERR_APPLICATION_NOT_FOUND,
    ERR_BOOKING_NOT_FOUND,
    ERR_BUILDER_NOT_FOUND,
    ERR_COMMITMENT_NOT_FOUND,
    ERR_CREW_NOT_FOUND,
    ERR_GIS_NOT_FOUND,
    ERR_INSPECTION_NOT_FOUND,
    ERR_INSPECTOR_NOT_FOUND,
    ERR_INVOICE_NOT_FOUND,
    ERR_LOAD_NOT_FOUND,
    ERR_MAIN_EXTENSION_NOT_FOUND,
    ERR_METER_SET_NOT_FOUND,
    ERR_PAYMENT_NOT_FOUND,
    ERR_PERMIT_NOT_FOUND,
    ERR_TEST_NOT_FOUND,
    ERR_TURN_ON_NOT_FOUND,
    raise_error,
)


def touch(entity):
    """Refresh updated_at and bump version (cascaded mutations included)."""
    entity["updated_at"] = db.now_iso()
    entity["version"] = entity.get("version", 1) + 1


# --- Lookup helpers (404 with the entity-specific error id) ---

def get_builder(bid):
    b = db.builders.get(bid)
    if b is None:
        raise_error(ERR_BUILDER_NOT_FOUND, f"Builder {bid} not found")
    return b


def get_application(aid):
    a = db.service_applications.get(aid)
    if a is None:
        raise_error(ERR_APPLICATION_NOT_FOUND, f"Service application {aid} not found")
    return a


def get_load(lid):
    r = db.appliance_loads.get(lid)
    if r is None:
        raise_error(ERR_LOAD_NOT_FOUND, f"Appliance load {lid} not found")
    return r


def get_main_extension(mid):
    m = db.main_extensions.get(mid)
    if m is None:
        raise_error(ERR_MAIN_EXTENSION_NOT_FOUND, f"Main extension {mid} not found")
    return m


def get_invoice(iid):
    inv = db.ciac_invoices.get(iid)
    if inv is None:
        raise_error(ERR_INVOICE_NOT_FOUND, f"CIAC invoice {iid} not found")
    return inv


def get_payment(pid):
    p = db.ciac_payments.get(pid)
    if p is None:
        raise_error(ERR_PAYMENT_NOT_FOUND, f"CIAC payment {pid} not found")
    return p


def get_permit(pid):
    p = db.permits.get(pid)
    if p is None:
        raise_error(ERR_PERMIT_NOT_FOUND, f"Permit {pid} not found")
    return p


def get_crew(cid):
    c = db.field_crews.get(cid)
    if c is None:
        raise_error(ERR_CREW_NOT_FOUND, f"Field crew {cid} not found")
    return c


def get_booking(bid):
    b = db.crew_bookings.get(bid)
    if b is None:
        raise_error(ERR_BOOKING_NOT_FOUND, f"Crew booking {bid} not found")
    return b


def get_inspector(iid):
    i = db.inspectors.get(iid)
    if i is None:
        raise_error(ERR_INSPECTOR_NOT_FOUND, f"Inspector {iid} not found")
    return i


def get_inspection(iid):
    i = db.inspections.get(iid)
    if i is None:
        raise_error(ERR_INSPECTION_NOT_FOUND, f"Inspection {iid} not found")
    return i


def get_meter_set(mid):
    m = db.meter_sets.get(mid)
    if m is None:
        raise_error(ERR_METER_SET_NOT_FOUND, f"Meter set {mid} not found")
    return m


def get_test(tid):
    t = db.purge_leak_tests.get(tid)
    if t is None:
        raise_error(ERR_TEST_NOT_FOUND, f"Purge/leak test {tid} not found")
    return t


def get_turn_on(tid):
    t = db.turn_on_events.get(tid)
    if t is None:
        raise_error(ERR_TURN_ON_NOT_FOUND, f"Turn-on event {tid} not found")
    return t


def get_commitment(cid):
    c = db.timeline_commitments.get(cid)
    if c is None:
        raise_error(ERR_COMMITMENT_NOT_FOUND, f"Timeline commitment {cid} not found")
    return c


def get_gis(gid):
    g = db.gis_as_builts.get(gid)
    if g is None:
        raise_error(ERR_GIS_NOT_FOUND, f"GIS as-built {gid} not found")
    return g


# --- Collection queries ---

def loads_for_application(app_id):
    return [r for r in db.appliance_loads.values() if r["service_application_id"] == app_id]


def main_extension_for_application(app_id):
    """The (at most one) non-CANCELLED main extension for an application, or None."""
    for m in db.main_extensions.values():
        if m["service_application_id"] == app_id and m["status"] != "CANCELLED":
            return m
    return None


def invoice_for_main_extension(me_id):
    for inv in db.ciac_invoices.values():
        if inv["main_extension_id"] == me_id:
            return inv
    return None


def invoice_for_application(app_id):
    for inv in db.ciac_invoices.values():
        if inv["service_application_id"] == app_id:
            return inv
    return None


def payments_for_invoice(invoice_id, direction=None):
    rows = [p for p in db.ciac_payments.values() if p["ciac_invoice_id"] == invoice_id]
    if direction is not None:
        rows = [p for p in rows if p["direction"] == direction]
    return rows


def permits_for_application(app_id):
    return [p for p in db.permits.values() if p["service_application_id"] == app_id]


def bookings_for_application(app_id):
    return [b for b in db.crew_bookings.values() if b["service_application_id"] == app_id]


def inspections_for_application(app_id):
    return [i for i in db.inspections.values() if i["service_application_id"] == app_id]


def meter_set_for_application(app_id):
    for m in db.meter_sets.values():
        if m["service_application_id"] == app_id and m["status"] != "CANCELLED":
            return m
    return None


def tests_for_meter_set(meter_set_id):
    return [t for t in db.purge_leak_tests.values() if t["meter_set_id"] == meter_set_id]


def turn_ons_for_application(app_id):
    return [t for t in db.turn_on_events.values() if t["service_application_id"] == app_id]


def commitment_for_application(app_id):
    for c in db.timeline_commitments.values():
        if c["service_application_id"] == app_id and c["status"] != "CANCELLED":
            return c
    return None


def gis_for_application(app_id):
    for g in db.gis_as_builts.values():
        if g["service_application_id"] == app_id and g["status"] != "CANCELLED":
            return g
    return None


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------

def advance_application(app, new_status):
    app["status"] = new_status
    touch(app)


def cancel_application_cascade(app):
    """§3.9 cancellation cascade. Application itself is set CANCELLED by the caller;
    this unwinds every child. Each cascaded child gets its own version bump."""
    # MainExtension non-terminal → CANCELLED; forces invoice unwind
    me = main_extension_for_application(app["id"])
    if me is not None and me["status"] not in ("FINALIZED", "CANCELLED", "EXPIRED"):
        me["status"] = "CANCELLED"
        touch(me)
        inv = invoice_for_main_extension(me["id"])
        if inv is not None and inv["status"] not in ("SETTLED", "REFUNDED", "VOID"):
            if inv["status"] == "ISSUED" and inv["payments_applied_cents"] == 0:
                inv["status"] = "VOID"
            elif inv["status"] in ("ISSUED", "PARTIALLY_PAID", "PAID"):
                inv["status"] = "REFUND_PENDING"
                inv["refund_required_cents"] = inv["payments_applied_cents"]
            touch(inv)
    # Permits: DRAFT/FILED → WITHDRAWN; APPROVED/CLOSED never withdrawn
    for p in permits_for_application(app["id"]):
        if p["status"] in ("DRAFT", "FILED"):
            p["status"] = "WITHDRAWN"
            touch(p)
    # Bookings REQUESTED/CONFIRMED → CANCELLED
    for b in bookings_for_application(app["id"]):
        if b["status"] in ("REQUESTED", "CONFIRMED"):
            b["status"] = "CANCELLED"
            touch(b)
    # Inspections SCHEDULED → CANCELLED
    for i in inspections_for_application(app["id"]):
        if i["status"] == "SCHEDULED":
            i["status"] = "CANCELLED"
            touch(i)
    # Turn-on events SCHEDULED/FAILED → CANCELLED
    for t in turn_ons_for_application(app["id"]):
        if t["status"] in ("SCHEDULED", "FAILED"):
            t["status"] = "CANCELLED"
            touch(t)
    # MeterSet non-terminal → CANCELLED; RECORDED tests → REJECTED
    ms = meter_set_for_application(app["id"])
    if ms is not None and ms["status"] not in ("ENERGIZED", "CANCELLED"):
        ms["status"] = "CANCELLED"
        touch(ms)
        for t in tests_for_meter_set(ms["id"]):
            if t["status"] == "RECORDED":
                t["status"] = "REJECTED"
                touch(t)
    # TimelineCommitment non-terminal → CANCELLED
    c = commitment_for_application(app["id"])
    if c is not None and c["status"] not in ("MET", "MISSED", "CANCELLED"):
        c["status"] = "CANCELLED"
        touch(c)
    # GISAsBuilt SUBMITTED/REJECTED → CANCELLED
    g = gis_for_application(app["id"])
    if g is not None and g["status"] in ("SUBMITTED", "REJECTED"):
        g["status"] = "CANCELLED"
        touch(g)


def expire_application_cascade(app):
    """§3.9 quote-expiry unwind: app QUOTED→EXPIRED cascade."""
    me = main_extension_for_application(app["id"])
    if me is not None and me["status"] == "QUOTED":
        me["status"] = "EXPIRED"
        touch(me)
        inv = invoice_for_main_extension(me["id"])
        if inv is not None and inv["status"] not in ("SETTLED", "REFUNDED", "VOID"):
            if inv["payments_applied_cents"] == 0:
                inv["status"] = "VOID"
            else:
                inv["status"] = "REFUND_PENDING"
                inv["refund_required_cents"] = inv["payments_applied_cents"]
            touch(inv)
    c = commitment_for_application(app["id"])
    if c is not None and c["status"] not in ("MET", "MISSED", "CANCELLED"):
        c["status"] = "CANCELLED"
        touch(c)
