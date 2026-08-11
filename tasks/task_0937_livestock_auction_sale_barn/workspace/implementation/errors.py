"""Error catalogue (PRD 5). Every id below appears in the PRD table."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or _DEFAULT_MESSAGES.get(error_id, error_id)


CATALOG = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_RESOURCE_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_ENUM": 400,
    "ERR_REFERENCE_NOT_FOUND": 404,
    "ERR_OWNERSHIP_VIOLATION": 403,
    "ERR_SALE_DAY_MISMATCH": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_DUPLICATE_BUYER_NUMBER": 409,
    "ERR_SALE_DAY_CANCELLED": 409,
    "ERR_LOT_QUARANTINED": 409,
    "ERR_SALE_DAY_FROZEN": 409,
    "ERR_PARTY_SUSPENDED": 403,
    "ERR_SETTLEMENT_RELEASED": 409,
    "ERR_INVALID_STATE": 409,
    "ERR_SCALE_NOT_CERTIFIED": 409,
    "ERR_WEIGH_TICKET_OPEN": 409,
    "ERR_REWEIGH_LIMIT_EXCEEDED": 409,
    "ERR_STAND_TIME_NOT_MET": 409,
    "ERR_PEN_SPECIES_MISMATCH": 422,
    "ERR_PEN_CAPACITY_EXCEEDED": 409,
    "ERR_CREW_OFF_DUTY": 409,
    "ERR_CREW_MOVE_OVERLAP": 409,
    "ERR_HEAD_COUNT_EXCEEDED": 422,
    "ERR_SETTLE_WEIGHT_MISSING": 409,
    "ERR_RERING_LIMIT_EXCEEDED": 409,
    "ERR_INSPECTION_NOT_CLEARED": 409,
    "ERR_CVI_EXPIRED": 409,
    "ERR_RETEST_LIMIT_EXCEEDED": 409,
    "ERR_BUYER_NOT_APPROVED": 403,
    "ERR_BUYER_CREDIT_HOLD": 409,
    "ERR_BID_BELOW_OPENING": 422,
    "ERR_BID_BELOW_INCREMENT": 422,
    "ERR_CREDIT_LIMIT_EXCEEDED": 402,
    "ERR_RESERVE_NOT_MET": 409,
    "ERR_TRAILER_HEAD_CAPACITY_EXCEEDED": 422,
    "ERR_TRAILER_WEIGHT_CAPACITY_EXCEEDED": 422,
    "ERR_LOAD_NOT_ASSIGNED": 409,
    "ERR_FUNDS_NOT_CLEARED": 409,
    "ERR_AMOUNT_EXCEEDS_BALANCE": 422,
}

_DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Authentication headers are missing or name an unknown role.",
    "ERR_FORBIDDEN_ROLE": "The acting role is not authorized for this endpoint.",
    "ERR_RESOURCE_NOT_FOUND": "A resource addressed in the path does not exist.",
    "ERR_INVALID_REQUEST": "The request body is missing a field, mistyped it, or violated a numeric constraint.",
    "ERR_INVALID_ENUM": "A closed-set field carries a value outside its vocabulary.",
    "ERR_REFERENCE_NOT_FOUND": "A foreign key supplied in the request body does not resolve.",
    "ERR_OWNERSHIP_VIOLATION": "The acting party does not own this resource.",
    "ERR_SALE_DAY_MISMATCH": "Cross-referenced rows belong to different sale days.",
    "ERR_STALE_VERSION": "The supplied expected version does not match the parent's current version.",
    "ERR_DUPLICATE_BUYER_NUMBER": "That buyer number is already used on this sale day.",
    "ERR_SALE_DAY_CANCELLED": "The sale day is cancelled and its subtree is read-only.",
    "ERR_LOT_QUARANTINED": "The lot is under a quarantine hold.",
    "ERR_SALE_DAY_FROZEN": "The sale day is frozen: bidding and yard work are closed.",
    "ERR_PARTY_SUSPENDED": "The owning party is suspended.",
    "ERR_SETTLEMENT_RELEASED": "A released settlement accepts no further mutation.",
    "ERR_INVALID_STATE": "The resource is not in a state that admits this operation.",
    "ERR_SCALE_NOT_CERTIFIED": "The named scale is not certified at the current clock date.",
    "ERR_WEIGH_TICKET_OPEN": "The lot already has an open weigh ticket.",
    "ERR_REWEIGH_LIMIT_EXCEEDED": "The lot's re-weigh limit has been reached.",
    "ERR_STAND_TIME_NOT_MET": "The required stand time has not elapsed.",
    "ERR_PEN_SPECIES_MISMATCH": "The destination pen is rigged for another species class.",
    "ERR_PEN_CAPACITY_EXCEEDED": "The pen would hold more head than its capacity.",
    "ERR_CREW_OFF_DUTY": "The named drover crew is not on duty.",
    "ERR_CREW_MOVE_OVERLAP": "The requested move window collides with an existing booking.",
    "ERR_HEAD_COUNT_EXCEEDED": "More head were requested than the consignment still has.",
    "ERR_SETTLE_WEIGHT_MISSING": "The lot has no settle weight yet.",
    "ERR_RERING_LIMIT_EXCEEDED": "The lot's re-ring limit has been reached.",
    "ERR_INSPECTION_NOT_CLEARED": "A required inspection document is missing, not cleared, or covers too few head.",
    "ERR_CVI_EXPIRED": "A required inspection document has expired.",
    "ERR_RETEST_LIMIT_EXCEEDED": "The inspection record's retest limit has been reached.",
    "ERR_BUYER_NOT_APPROVED": "The buyer registration is not approved.",
    "ERR_BUYER_CREDIT_HOLD": "The buyer registration is on credit hold.",
    "ERR_BID_BELOW_OPENING": "The bid is below the lot's opening bid.",
    "ERR_BID_BELOW_INCREMENT": "The bid is below the current high plus the minimum increment.",
    "ERR_CREDIT_LIMIT_EXCEEDED": "The bid would push the buyer past their effective limit.",
    "ERR_RESERVE_NOT_MET": "The winning price is below the lot's reserve price.",
    "ERR_TRAILER_HEAD_CAPACITY_EXCEEDED": "The trailer's head capacity would be exceeded.",
    "ERR_TRAILER_WEIGHT_CAPACITY_EXCEEDED": "The trailer's weight capacity would be exceeded.",
    "ERR_LOAD_NOT_ASSIGNED": "The lot is not on a dispatched or delivered manifest.",
    "ERR_FUNDS_NOT_CLEARED": "The funds covering this release have not cleared.",
    "ERR_AMOUNT_EXCEEDS_BALANCE": "The amount exceeds the balance it is applied against.",
}


def fail(error_id, message=None):
    raise ApiError(error_id, CATALOG[error_id], message)
