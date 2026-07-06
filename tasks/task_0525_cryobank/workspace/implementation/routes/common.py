"""Shared route helpers: fetch-or-404 for each entity collection."""

import errors
from errors import err
from db import db


def _get_or_404(coll, entity_id):
    ent = coll.get(entity_id)
    if ent is None:
        raise err(errors.ERR_NOT_FOUND, "Referenced entity does not exist")
    return ent


def get_donor(i):
    return _get_or_404(db.donors, i)


def get_application(i):
    return _get_or_404(db.screening_applications, i)


def get_specimen(i):
    return _get_or_404(db.specimens, i)


def get_inventory(i):
    return _get_or_404(db.donor_inventories, i)


def get_recipient(i):
    return _get_or_404(db.recipients, i)


def get_consent(i):
    return _get_or_404(db.recipient_consents, i)


def get_reservation(i):
    return _get_or_404(db.vial_reservations, i)


def get_shipment(i):
    return _get_or_404(db.shipments, i)


def get_storage_account(i):
    return _get_or_404(db.storage_accounts, i)


def get_invoice(i):
    return _get_or_404(db.storage_invoices, i)


def get_registry(i):
    return _get_or_404(db.sibling_registry, i)


def get_appointment(i):
    return _get_or_404(db.collection_appointments, i)


def get_window(i):
    return _get_or_404(db.dewar_maintenance_windows, i)


def get_report(i):
    return _get_or_404(db.regulatory_reports, i)
