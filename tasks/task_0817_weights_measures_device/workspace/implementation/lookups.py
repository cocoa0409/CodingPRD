"""Entity lookup helpers that raise the correct not-found ApiError."""

from core import store, ApiError


def _get(coll, _id, err):
    ent = coll.get(_id)
    if ent is None:
        raise ApiError(err)
    return ent


def get_establishment(_id):
    return _get(store.establishments, _id, "ERR_ESTABLISHMENT_NOT_FOUND")


def get_inspector(_id):
    return _get(store.inspectors, _id, "ERR_INSPECTOR_NOT_FOUND")


def get_device(_id):
    return _get(store.devices, _id, "ERR_DEVICE_NOT_FOUND")


def get_inspection(_id):
    return _get(store.inspections, _id, "ERR_INSPECTION_NOT_FOUND")


def get_complaint(_id):
    return _get(store.complaints, _id, "ERR_COMPLAINT_NOT_FOUND")


def get_penalty(_id):
    return _get(store.penalties, _id, "ERR_PENALTY_NOT_FOUND")


def get_fee_invoice(_id):
    return _get(store.fee_invoices, _id, "ERR_FEE_INVOICE_NOT_FOUND")


def get_seal(_id):
    return _get(store.seals, _id, "ERR_NOT_FOUND")


def get_condemnation(_id):
    return _get(store.condemnations, _id, "ERR_NOT_FOUND")
