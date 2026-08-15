"""Error classes and error ID constants."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


def err_unauthenticated(msg="Missing or malformed X-User-Role / X-User-ID headers"):
    return ApiError("ERR_UNAUTHENTICATED", msg, 401)


def err_forbidden(msg="Role not permitted for endpoint per RBAC"):
    return ApiError("ERR_FORBIDDEN", msg, 403)


def err_segregation(msg="Same actor role attempting both build and approve steps on a ClosingStatement"):
    return ApiError("ERR_SEGREGATION_VIOLATION", msg, 403)


def err_not_found(msg="Referenced resource id does not exist"):
    return ApiError("ERR_NOT_FOUND", msg, 404)


def err_invalid_request(msg="Required field missing, enum out of range, or field type mismatch"):
    return ApiError("ERR_INVALID_REQUEST", msg, 400)


def err_invalid_state(msg="Target resource state does not permit requested transition"):
    return ApiError("ERR_INVALID_STATE", msg, 409)


def err_stale_version(msg="expected version does not match current version"):
    return ApiError("ERR_STALE_VERSION", msg, 412)


def err_duplicate(msg="Uniqueness violation"):
    return ApiError("ERR_DUPLICATE_RESOURCE", msg, 409)


def err_doc_mode(msg="uscg_official_no / state_title_no inconsistent with documentation_mode"):
    return ApiError("ERR_DOC_MODE_MISMATCH", msg, 422)


def err_invalid_deadline(msg="Deadline not in the future, or end_date not after start_date"):
    return ApiError("ERR_INVALID_DEADLINE", msg, 422)


def err_deadline_passed(msg="Acceptance/contingency deadline elapsed at request time"):
    return ApiError("ERR_DEADLINE_PASSED", msg, 422)


def err_lien_instrument(msg="PREFERRED_MORTGAGE recorded on STATE-titled vessel"):
    return ApiError("ERR_LIEN_INSTRUMENT_MISMATCH", msg, 422)


def err_listing_not_accepting(msg="Offer attempted on listing not in ACTIVE (or kick-out eligible UNDER_CONTRACT)"):
    return ApiError("ERR_LISTING_NOT_ACCEPTING", msg, 409)


def err_title_encumbered(msg="FULL warranty of title attempted while vessel.liens_status == ENCUMBERED"):
    return ApiError("ERR_TITLE_ENCUMBERED", msg, 422)


def err_deposit_insufficient(msg="DEPOSIT amount below required_deposit_cents"):
    return ApiError("ERR_DEPOSIT_INSUFFICIENT", msg, 422)


def err_deposit_excessive(msg="DEPOSIT amount exceeds 2x required_deposit_cents (anti-structuring)"):
    return ApiError("ERR_DEPOSIT_EXCESSIVE", msg, 422)


def err_escrow_not_cleared(msg="Release/refund/forfeit attempted on non-CLEARED escrow entry"):
    return ApiError("ERR_ESCROW_NOT_CLEARED", msg, 409)


def err_liens_outstanding(msg="Disbursement attempted while vessel.liens_status == ENCUMBERED"):
    return ApiError("ERR_LIENS_OUTSTANDING", msg, 422)


def err_syndication_stale(msg="Syndication push price != current list price, or listing not ACTIVE"):
    return ApiError("ERR_SYNDICATION_STALE_PRICE", msg, 422)


def err_contingency_unresolved(msg="Closing build/disburse attempted with contingencies outside {SATISFIED, WAIVED}"):
    return ApiError("ERR_CONTINGENCY_UNRESOLVED", msg, 409)


def err_offer_not_accepted(msg="Closing statement created for offer not in ACCEPTED"):
    return ApiError("ERR_OFFER_NOT_ACCEPTED", msg, 409)


def err_waterfall_shortfall(msg="Lien payoff pool insufficient — a lien would remain PARTIALLY_SATISFIED"):
    return ApiError("ERR_WATERFALL_SHORTFALL", msg, 422)
