"""Request-body shape validation and path/body reference resolution."""
from decimal import Decimal, InvalidOperation

from flask import request

from errors import ApiError
from store import db, valid_month_key


def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return data


def bad(msg):
    raise ApiError("ERR_INVALID_REQUEST", msg)


def check_keys(data, allowed):
    for key in data:
        if key not in allowed:
            bad("Unknown field '%s' in request body." % key)


def require(data, key):
    if key not in data or data[key] is None:
        bad("Field '%s' is required." % key)
    return data[key]


def as_string(data, key, required=True, default=None):
    if key not in data or data[key] is None:
        if required:
            bad("Field '%s' is required." % key)
        return default
    value = data[key]
    if not isinstance(value, str) or value == "":
        bad("Field '%s' must be a non-empty string." % key)
    return value


def as_enum(data, key, members, required=True, default=None):
    if key not in data or data[key] is None:
        if required:
            bad("Field '%s' is required." % key)
        return default
    value = data[key]
    if not isinstance(value, str) or value not in members:
        bad("Field '%s' must be one of %s." % (key, ", ".join(members)))
    return value


def as_int(data, key, required=True, default=None, minimum=None, maximum=None):
    if key not in data or data[key] is None:
        if required:
            bad("Field '%s' is required." % key)
        return default
    value = data[key]
    if isinstance(value, bool) or not isinstance(value, int):
        bad("Field '%s' must be an integer." % key)
    if minimum is not None and value < minimum:
        bad("Field '%s' is below its minimum." % key)
    if maximum is not None and value > maximum:
        bad("Field '%s' is above its maximum." % key)
    return value


def to_decimal(value, key):
    if isinstance(value, bool):
        bad("Field '%s' must be a number." % key)
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(repr(value))
    if isinstance(value, str):
        bad("Field '%s' must be a number." % key)
    bad("Field '%s' must be a number." % key)


def as_hours(data, key, required=True, default=None):
    if key not in data or data[key] is None:
        if required:
            bad("Field '%s' is required." % key)
        return default
    value = data[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad("Field '%s' must be a number." % key)
    try:
        dec = Decimal(repr(value)) if isinstance(value, float) else Decimal(value)
    except InvalidOperation:
        bad("Field '%s' must be a number." % key)
    if dec < 0:
        bad("Field '%s' must be at least 0." % key)
    if -dec.as_tuple().exponent > 2:
        bad("Field '%s' carries at most two decimal places." % key)
    return dec.quantize(Decimal("0.01"))


def as_month(data, key, required=True, default=None):
    if key not in data or data[key] is None:
        if required:
            bad("Field '%s' is required." % key)
        return default
    value = data[key]
    if not valid_month_key(value):
        bad("Field '%s' must be a YYYY-MM month key." % key)
    return value


def as_iso_date(data, key, required=True, default=None):
    from datetime import datetime

    if key not in data or data[key] is None:
        if required:
            bad("Field '%s' is required." % key)
        return default
    value = data[key]
    if not isinstance(value, str):
        bad("Field '%s' must be an ISO date." % key)
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        bad("Field '%s' must be an ISO date (YYYY-MM-DD)." % key)
    return value


def as_int_array5(data, key):
    if key not in data or data[key] is None:
        bad("Field '%s' is required." % key)
    value = data[key]
    if not isinstance(value, list) or len(value) != 5:
        bad("Field '%s' must hold exactly five entries." % key)
    out = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int) or item < 0:
            bad("Field '%s' must hold five non-negative integers." % key)
        out.append(item)
    return out


# ---------------------------------------------------------------------
# reference resolution
# ---------------------------------------------------------------------
def _resolve(collection, key, error_id):
    row = collection.get(key)
    if row is None:
        raise ApiError(error_id)
    return row


def get_fund(fund_id):
    return _resolve(db.funds, fund_id, "ERR_FUND_NOT_FOUND")


def get_employer(employer_id):
    return _resolve(db.employers, employer_id, "ERR_EMPLOYER_NOT_FOUND")


def get_participant(participant_id):
    return _resolve(db.participants, participant_id, "ERR_PARTICIPANT_NOT_FOUND")


def get_report(report_id):
    return _resolve(db.reports, report_id, "ERR_REPORT_NOT_FOUND")


def get_coverage_month(cid):
    return _resolve(db.coverage_months, cid, "ERR_COVERAGE_MONTH_NOT_FOUND")


def get_assessment(aid):
    return _resolve(db.assessments, aid, "ERR_ASSESSMENT_NOT_FOUND")


def get_audit(aid):
    return _resolve(db.audits, aid, "ERR_AUDIT_NOT_FOUND")


def get_withdrawal(wid):
    return _resolve(db.withdrawals, wid, "ERR_WITHDRAWAL_NOT_FOUND")


def get_installment(iid):
    return _resolve(db.installments, iid, "ERR_INSTALLMENT_NOT_FOUND")


def get_motion(mid):
    return _resolve(db.motions, mid, "ERR_MOTION_NOT_FOUND")


def get_vote(vid):
    return _resolve(db.votes, vid, "ERR_VOTE_NOT_FOUND")


def get_transfer(tid):
    return _resolve(db.transfers, tid, "ERR_TRANSFER_NOT_FOUND")


def body_ref(data, key, collection, error_id, required=True):
    """Body FK existence (ladder step 5) - runs before shape validation."""
    if key not in data or data[key] is None:
        return None
    value = data[key]
    if not isinstance(value, str):
        return None
    if value not in collection:
        raise ApiError(error_id)
    return collection[value]
