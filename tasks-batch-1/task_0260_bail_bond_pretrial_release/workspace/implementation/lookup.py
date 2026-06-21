"""Path-existence lookups (left-to-right), raising ERR_NOT_FOUND (404).

These enforce PRD §2.5: validate each path identifier in order, reject the
request at the first identifier that does not resolve.
"""
import db
from errors import err


def get_defendant(defendant_id):
    d = db.defendants.get(defendant_id)
    if d is None:
        raise err("ERR_NOT_FOUND", "Defendant not found.")
    return d


def get_bail_order(order_id):
    o = db.bail_orders.get(order_id)
    if o is None:
        raise err("ERR_NOT_FOUND", "Bail order not found.")
    return o


def get_bond(bond_id):
    b = db.bonds.get(bond_id)
    if b is None:
        raise err("ERR_NOT_FOUND", "Bond not found.")
    return b


def get_bond_for_defendant(defendant_id, bond_id):
    """Defendant first (left), then bond, then verify the bond belongs to it."""
    get_defendant(defendant_id)
    b = db.bonds.get(bond_id)
    if b is None or b["defendant_id"] != defendant_id:
        raise err("ERR_NOT_FOUND", "Bond not found for this defendant.")
    return b


def get_indemnitor(indemnitor_id):
    i = db.indemnitors.get(indemnitor_id)
    if i is None:
        raise err("ERR_NOT_FOUND", "Indemnitor not found.")
    return i


def get_indemnity_agreement(agreement_id):
    a = db.indemnity_agreements.get(agreement_id)
    if a is None:
        raise err("ERR_NOT_FOUND", "Indemnity agreement not found.")
    return a


def get_court_date(court_date_id):
    c = db.court_dates.get(court_date_id)
    if c is None:
        raise err("ERR_NOT_FOUND", "Court date not found.")
    return c


def get_court_date_for_defendant(defendant_id, court_date_id):
    """Defendant first, then court date; the court date's bond must belong to
    the defendant in the path."""
    get_defendant(defendant_id)
    c = db.court_dates.get(court_date_id)
    if c is None:
        raise err("ERR_NOT_FOUND", "Court date not found.")
    bond = db.bonds.get(c["bond_id"])
    if bond is None or bond["defendant_id"] != defendant_id:
        raise err("ERR_NOT_FOUND", "Court date not found for this defendant.")
    return c


def get_device(device_id):
    d = db.gps_devices.get(device_id)
    if d is None:
        raise err("ERR_NOT_FOUND", "GPS device not found.")
    return d


def get_device_for_defendant(defendant_id, device_id):
    get_defendant(defendant_id)
    d = db.gps_devices.get(device_id)
    if d is None:
        raise err("ERR_NOT_FOUND", "GPS device not found.")
    bond = db.bonds.get(d.get("assigned_bond_id"))
    if bond is None or bond["defendant_id"] != defendant_id:
        raise err("ERR_NOT_FOUND", "GPS device not found for this defendant.")
    return d


def get_forfeiture(proceeding_id):
    f = db.forfeitures.get(proceeding_id)
    if f is None:
        raise err("ERR_NOT_FOUND", "Forfeiture proceeding not found.")
    return f


def get_forfeiture_for_defendant(defendant_id, proceeding_id):
    get_defendant(defendant_id)
    f = db.forfeitures.get(proceeding_id)
    if f is None:
        raise err("ERR_NOT_FOUND", "Forfeiture proceeding not found.")
    bond = db.bonds.get(f["bond_id"])
    if bond is None or bond["defendant_id"] != defendant_id:
        raise err("ERR_NOT_FOUND", "Forfeiture proceeding not found for this defendant.")
    return f
