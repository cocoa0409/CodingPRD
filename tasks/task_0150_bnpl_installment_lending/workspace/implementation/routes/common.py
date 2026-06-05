"""Shared route helpers: body parsing, pagination, existence lookups."""
from flask import request

import db
from errors import err

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def get_json_body():
    """Parse the JSON body; an absent/empty body is treated as {}.

    A syntactically invalid JSON body is an ERR_INVALID_REQUEST (422)."""
    if request.data and request.data.strip():
        try:
            data = request.get_json(force=True, silent=False)
        except Exception:
            raise err("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
        if data is None:
            return {}
        if not isinstance(data, dict):
            raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
        return data
    return {}


def parse_pagination():
    """Read limit/offset query params with PRD §2.3 defaults & clamps.

    Out-of-range / non-integer values are rejected with ERR_INVALID_REQUEST."""
    args = request.args
    limit = args.get("limit")
    offset = args.get("offset")

    if limit is None:
        limit_v = PAGINATION_DEFAULT_LIMIT
    else:
        try:
            limit_v = int(limit)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer.")
        if limit_v < PAGINATION_MIN_LIMIT or limit_v > PAGINATION_MAX_LIMIT:
            raise err("ERR_INVALID_REQUEST",
                      "limit must be between %d and %d."
                      % (PAGINATION_MIN_LIMIT, PAGINATION_MAX_LIMIT))

    if offset is None:
        offset_v = PAGINATION_DEFAULT_OFFSET
    else:
        try:
            offset_v = int(offset)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer.")
        if offset_v < 0:
            raise err("ERR_INVALID_REQUEST", "offset must be >= 0.")

    return limit_v, offset_v


def paginate(rows, limit, offset):
    """Apply the page window. Returns (page_rows, pagination_meta)."""
    total = len(rows)
    page = rows[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, meta


def sort_by_created(rows):
    """Default list ordering: created_at ASC (stable via insertion seq)."""
    return sorted(rows, key=lambda r: r["_seq"])


# ── existence lookups (ERR_NOT_FOUND, validated left-to-right by caller) ──────
def require_merchant(merchant_id):
    m = db.merchants.get(merchant_id)
    if m is None:
        raise err("ERR_NOT_FOUND", "Merchant not found.")
    return m


def require_borrower(borrower_id):
    b = db.borrowers.get(borrower_id)
    if b is None:
        raise err("ERR_NOT_FOUND", "Borrower not found.")
    return b


def require_application(application_id):
    a = db.applications.get(application_id)
    if a is None:
        raise err("ERR_NOT_FOUND", "Application not found.")
    return a


def require_loan(loan_id):
    l = db.loans.get(loan_id)
    if l is None:
        raise err("ERR_NOT_FOUND", "Loan not found.")
    return l


def require_disclosure(disclosure_id):
    d = db.disclosure_acceptances.get(disclosure_id)
    if d is None:
        raise err("ERR_NOT_FOUND", "Disclosure acceptance not found.")
    return d


def require_installment(installment_id):
    i = db.installments.get(installment_id)
    if i is None:
        raise err("ERR_NOT_FOUND", "Installment not found.")
    return i


def require_payment(payment_id):
    p = db.payments.get(payment_id)
    if p is None:
        raise err("ERR_NOT_FOUND", "Payment not found.")
    return p


def require_return(return_id):
    r = db.returns.get(return_id)
    if r is None:
        raise err("ERR_NOT_FOUND", "Return not found.")
    return r


def require_mandate(mandate_id):
    m = db.autopay_mandates.get(mandate_id)
    if m is None:
        raise err("ERR_NOT_FOUND", "Autopay mandate not found.")
    return m


def require_settlement(settlement_id):
    s = db.merchant_settlements.get(settlement_id)
    if s is None:
        raise err("ERR_NOT_FOUND", "Merchant settlement not found.")
    return s


def require_int(body, field, required=True, default=None, minimum=None,
                maximum=None, gt=None):
    """Validate an integer field; raises ERR_INVALID_REQUEST on schema issues."""
    if field not in body or body.get(field) is None:
        if required:
            raise err("ERR_INVALID_REQUEST", "Missing required field '%s'." % field)
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise err("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % field)
    if minimum is not None and val < minimum:
        raise err("ERR_INVALID_REQUEST", "Field '%s' must be >= %d." % (field, minimum))
    if maximum is not None and val > maximum:
        raise err("ERR_INVALID_REQUEST", "Field '%s' must be <= %d." % (field, maximum))
    if gt is not None and val <= gt:
        raise err("ERR_INVALID_REQUEST", "Field '%s' must be > %d." % (field, gt))
    return val


def require_str(body, field, required=True):
    if field not in body or body.get(field) is None:
        if required:
            raise err("ERR_INVALID_REQUEST", "Missing required field '%s'." % field)
        return None
    val = body[field]
    if not isinstance(val, str) or val.strip() == "":
        raise err("ERR_INVALID_REQUEST", "Field '%s' must be a non-empty string." % field)
    return val
