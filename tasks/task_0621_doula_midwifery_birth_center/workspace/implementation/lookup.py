"""Existence lookups (§2.5). Each returns the record or raises ERR_NOT_FOUND."""
from db import db
from errors import err, ERR_NOT_FOUND


def _get(coll, key, label):
    rec = coll.get(key)
    if rec is None:
        raise err(ERR_NOT_FOUND, "%s not found" % label)
    return rec


def get_client(cid):
    return _get(db.clients, cid, "Client")


def get_care_package(code):
    return _get(db.care_packages, code, "CarePackage")


def get_supply_kit(sku):
    return _get(db.supply_kits, sku, "SupplyKit")


def get_provider(pid):
    return _get(db.providers, pid, "Provider")


def get_room(rid):
    return _get(db.rooms, rid, "Room")


def get_episode(eid):
    return _get(db.episodes, eid, "Episode")


def get_visit(vid):
    return _get(db.prenatal_visits, vid, "PrenatalVisit")


def get_assignment(aid):
    return _get(db.on_call_assignments, aid, "OnCallAssignment")


def get_booking(bid):
    return _get(db.bookings, bid, "Booking")


def get_claim(cid):
    return _get(db.insurance_claims, cid, "InsuranceClaim")


def get_charge(cid):
    return _get(db.charges, cid, "Charge")


def get_payment_plan(pid):
    return _get(db.payment_plans, pid, "PaymentPlan")
