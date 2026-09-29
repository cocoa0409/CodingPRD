"""Read-only navigation over the entity graph.

DeviceUnit is the hub: unit -> lot -> catalog item -> vendor, plus unit ->
consignment agreement, unit -> invoice, unit -> reserved case.
"""
from store import db, ordered


def lot_of(unit):
    if not unit:
        return None
    return db.lots.get(unit.get("lot_id"))


def catalog_of_lot(lot):
    if not lot:
        return None
    return db.catalog_items.get(lot.get("catalog_item_id"))


def catalog_of_unit(unit):
    return catalog_of_lot(lot_of(unit))


def vendor_of_catalog(item):
    if not item:
        return None
    return db.vendors.get(item.get("vendor_id"))


def vendor_of_unit(unit):
    return vendor_of_catalog(catalog_of_unit(unit))


def agreement_of_unit(unit):
    if not unit or not unit.get("consignment_agreement_id"):
        return None
    return db.agreements.get(unit["consignment_agreement_id"])


def units_of_lot(lot_id):
    return ordered([u for u in db.device_units.values() if u["lot_id"] == lot_id])


def units_of_catalog(catalog_item_id):
    out = []
    for unit in db.device_units.values():
        lot = db.lots.get(unit["lot_id"])
        if lot and lot["catalog_item_id"] == catalog_item_id:
            out.append(unit)
    return ordered(out)


def lots_of_catalog(catalog_item_id):
    return ordered([l for l in db.lots.values() if l["catalog_item_id"] == catalog_item_id])


def records_of_case(case_id):
    return ordered([r for r in db.implant_records.values() if r["surgical_case_id"] == case_id])


def records_of_patient(patient_id):
    return ordered([r for r in db.implant_records.values() if r["patient_id"] == patient_id])


def charges_of_record(record_id):
    return ordered([c for c in db.charges.values() if c["implant_record_id"] == record_id])


def submissions_of_record(record_id):
    return ordered(
        [s for s in db.registry_submissions.values() if s["implant_record_id"] == record_id]
    )


def notifications_of_action(field_action_id):
    return ordered(
        [n for n in db.recall_notifications.values() if n["field_action_id"] == field_action_id]
    )


def actions_of_vendor(vendor_id):
    return ordered([a for a in db.field_actions.values() if a["vendor_id"] == vendor_id])


def units_of_invoice(invoice_id):
    return ordered([u for u in db.device_units.values() if u.get("vendor_invoice_id") == invoice_id])


def case_of_record(record):
    if not record:
        return None
    return db.cases.get(record.get("surgical_case_id"))


def unit_of_record(record):
    if not record:
        return None
    return db.device_units.get(record.get("device_unit_id"))


def record_of_charge(charge):
    if not charge:
        return None
    return db.implant_records.get(charge.get("implant_record_id"))


def record_of_submission(submission):
    if not submission:
        return None
    return db.implant_records.get(submission.get("implant_record_id"))


def record_of_explant(explant):
    if not explant:
        return None
    return db.implant_records.get(explant.get("implant_record_id"))


def case_of_charge(charge):
    return case_of_record(record_of_charge(charge))


def case_of_submission(submission):
    return case_of_record(record_of_submission(submission))
