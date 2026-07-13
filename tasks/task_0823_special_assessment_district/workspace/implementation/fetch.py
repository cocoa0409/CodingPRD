"""Path-resource lookups that raise the correct 404 error."""
from store import DB
from web import ApiError

_MAP = {
    "districts": "ERR_DISTRICT_NOT_FOUND",
    "parcels": "ERR_PARCEL_NOT_FOUND",
    "rolls": "ERR_ROLL_NOT_FOUND",
    "bonds": "ERR_BOND_NOT_FOUND",
    "installments": "ERR_INSTALLMENT_NOT_FOUND",
    "payments": "ERR_PAYMENT_NOT_FOUND",
    "quotes": "ERR_QUOTE_NOT_FOUND",
    "foreclosures": "ERR_FORECLOSURE_NOT_FOUND",
}


def _get(kind, rid):
    ent = DB[kind].get(rid)
    if ent is None:
        raise ApiError(_MAP[kind])
    return ent


def get_district(rid):
    return _get("districts", rid)


def get_parcel(rid):
    return _get("parcels", rid)


def get_roll(rid):
    return _get("rolls", rid)


def get_bond(rid):
    return _get("bonds", rid)


def get_installment(rid):
    return _get("installments", rid)


def get_payment(rid):
    return _get("payments", rid)


def get_quote(rid):
    return _get("quotes", rid)


def get_foreclosure(rid):
    return _get("foreclosures", rid)
