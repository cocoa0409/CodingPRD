import errors
from errors import err
from db import db


def get_taxpayer_or_fk(taxpayer_id):
    tp = db.taxpayers.get(taxpayer_id)
    if tp is None:
        raise err(errors.ERR_FK_NOT_FOUND, "taxpayer_id does not resolve")
    return tp


def get_return_or_404(return_id):
    ret = db.tax_returns.get(return_id)
    if ret is None:
        raise err(errors.ERR_RETURN_NOT_FOUND, "TaxReturn not found")
    return ret


def get_return_or_fk(return_id):
    ret = db.tax_returns.get(return_id)
    if ret is None:
        raise err(errors.ERR_FK_NOT_FOUND, "return_id does not resolve")
    return ret


def get_efiling_or_404(efiling_id):
    sub = db.efilings.get(efiling_id)
    if sub is None:
        raise err(errors.ERR_RETURN_NOT_FOUND, "EFilingSubmission not found")
    return sub


def get_amended_or_404(amended_id):
    am = db.amended_returns.get(amended_id)
    if am is None:
        raise err(errors.ERR_RETURN_NOT_FOUND, "AmendedReturn not found")
    return am


def owner_check_return(role, user_id, ret):
    """Taxpayer/Preparer X-User-ID must equal the owning taxpayer_id."""
    if role in ("Taxpayer", "Preparer") and ret["taxpayer_id"] != user_id:
        raise err(errors.ERR_NOT_RESOURCE_OWNER, "Caller does not own this return")


def owner_check_amended(role, user_id, amended):
    if role in ("Taxpayer", "Preparer") and amended["taxpayer_id"] != user_id:
        raise err(errors.ERR_NOT_RESOURCE_OWNER, "Caller does not own this amendment")
