"""Resource existence lookups. Each raises ERR_NOT_FOUND (PRD §2.6) when the
id does not resolve."""
from db import db
from errors import err, ERR_NOT_FOUND


def get_technician(tid):
    rec = db.technicians.get(tid)
    if rec is None:
        raise err(ERR_NOT_FOUND, "Technician not found")
    return rec


def get_station(sid):
    rec = db.stations.get(sid)
    if rec is None:
        raise err(ERR_NOT_FOUND, "Station not found")
    return rec


def get_sanitation_log(lid):
    rec = db.sanitation_logs.get(lid)
    if rec is None:
        raise err(ERR_NOT_FOUND, "SanitationLog not found")
    return rec


def get_menu_item(mid):
    rec = db.menu_items.get(mid)
    if rec is None:
        raise err(ERR_NOT_FOUND, "ServiceMenuItem not found")
    return rec


def get_add_on(aid):
    rec = db.add_ons.get(aid)
    if rec is None:
        raise err(ERR_NOT_FOUND, "AddOn not found")
    return rec


def get_client(cid):
    rec = db.clients.get(cid)
    if rec is None:
        raise err(ERR_NOT_FOUND, "Client not found")
    return rec


def get_appointment(aid):
    rec = db.appointments.get(aid)
    if rec is None:
        raise err(ERR_NOT_FOUND, "Appointment not found")
    return rec


def get_appointment_add_on(aid):
    rec = db.appointment_add_ons.get(aid)
    if rec is None:
        raise err(ERR_NOT_FOUND, "AppointmentAddOn not found")
    return rec


def get_gift_card(gid):
    rec = db.gift_cards.get(gid)
    if rec is None:
        raise err(ERR_NOT_FOUND, "GiftCard not found")
    return rec


def get_commission_statement(sid):
    rec = db.commission_statements.get(sid)
    if rec is None:
        raise err(ERR_NOT_FOUND, "CommissionStatement not found")
    return rec
