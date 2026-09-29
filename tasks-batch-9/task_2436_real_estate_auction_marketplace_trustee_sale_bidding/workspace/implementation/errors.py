"""Error catalog (PRD §5 / SCAFFOLD §1.6)."""

ERROR_HTTP = {
    # auth
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    # existence
    "ERR_SELLER_NOT_FOUND": 404,
    "ERR_ASSET_LISTING_NOT_FOUND": 404,
    "ERR_TRUSTEE_SALE_NOT_FOUND": 404,
    "ERR_AUCTION_EVENT_NOT_FOUND": 404,
    "ERR_AUCTION_LOT_NOT_FOUND": 404,
    "ERR_BIDDER_NOT_FOUND": 404,
    "ERR_EXCLUSION_NOT_FOUND": 404,
    "ERR_SALE_CONTRACT_NOT_FOUND": 404,
    "ERR_OFFER_NOT_FOUND": 404,
    "ERR_BID_NOT_FOUND": 404,
    # request shape
    "ERR_INVALID_REQUEST": 400,
    "ERR_DUPLICATE_LOT_NUMBER": 409,
    "ERR_AUDIT_MODE_REQUIRES_LOT": 422,
    # listing / title state
    "ERR_LISTING_NOT_IN_INTAKE": 409,
    "ERR_TITLE_CLEARANCE_ALREADY_SET": 409,
    "ERR_LISTING_NOT_RELISTABLE": 409,
    "ERR_LISTING_NOT_LISTABLE": 409,
    "ERR_TITLE_CLEARANCE_PENDING": 409,
    "ERR_TITLE_DEFECTIVE": 409,
    # trustee sale state
    "ERR_TRUSTEE_SALE_NOT_ACTIONABLE": 409,
    "ERR_TRUSTEE_SALE_NOT_CONFIRMED": 409,
    "ERR_SALE_DATE_NOT_FUTURE": 422,
    "ERR_POSTPONEMENT_LIMIT_EXCEEDED": 409,
    # event state
    "ERR_EVENT_NOT_SCHEDULED": 409,
    "ERR_EVENT_NOT_POSTPONED": 409,
    "ERR_EVENT_NOT_LIVE": 409,
    "ERR_EVENT_HAS_NO_LOTS": 409,
    "ERR_EVENT_NOT_STARTED": 409,
    "ERR_COUNTY_SLOT_CONFLICT": 409,
    # lot state
    "ERR_LOT_NOT_OPEN": 409,
    "ERR_LOT_NOT_CLOSED_SOLD": 409,
    "ERR_LOT_HAS_BIDS": 409,
    "ERR_LOT_WINDOW_CONFLICT": 409,
    "ERR_LOT_WINDOW_OUTSIDE_EVENT": 422,
    "ERR_BID_WINDOW_CLOSED": 409,
    "ERR_LOT_WINDOW_STILL_OPEN": 409,
    "ERR_BID_BELOW_MINIMUM": 422,
    "ERR_RESERVE_BELOW_OPENING": 422,
    # bidder & compliance
    "ERR_BIDDER_NOT_REGISTERED": 409,
    "ERR_IDENTITY_UNVERIFIED": 409,
    "ERR_BIDDER_BARRED": 403,
    "ERR_BIDDER_EXCLUDED": 403,
    "ERR_DEPOSIT_INSUFFICIENT": 402,
    # contract / settlement / fallout / second chance
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_CONTRACT_NOT_EXECUTED": 409,
    "ERR_CLOSING_DEADLINE_PASSED": 409,
    "ERR_NO_BACKUP_BIDDER": 409,
    "ERR_DUPLICATE_ACTIVE_OFFER": 409,
    "ERR_OFFER_NOT_OUTSTANDING": 409,
    "ERR_OFFER_EXPIRED": 409,
    "ERR_COUNTY_MISMATCH": 422,
    # optimistic concurrency
    "ERR_STALE_EVENT_VERSION": 412,
    "ERR_STALE_LOT_VERSION": 412,
}


class ApiError(Exception):
    """Raised anywhere in a request to abort with a catalog error."""

    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.message = message or _default_message(error_id)
        self.http_status = http_status or ERROR_HTTP.get(error_id, 400)


def _default_message(error_id):
    return error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."
