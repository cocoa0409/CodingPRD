"""Error catalog and exception type.

Every error_id and HTTP status is taken verbatim from SCAFFOLD.yaml §1.6
and PRD §5 (41 entries).
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


# --- auth (401/403) ---
def err_unauthenticated(msg="X-User-ID or X-User-Role header missing, or role unknown"):
    return ApiError("ERR_UNAUTHENTICATED", 401, msg)


def err_unauthorized_role(msg="Role not permitted for this endpoint"):
    return ApiError("ERR_UNAUTHORIZED_ROLE", 403, msg)


def err_beneficiary_ownership(msg="Beneficiary caller does not own the target case"):
    return ApiError("ERR_BENEFICIARY_OWNERSHIP_MISMATCH", 403, msg)


def err_bidder_ownership(msg="ThirdPartyBidder caller may act only through its own registration"):
    return ApiError("ERR_BIDDER_OWNERSHIP_MISMATCH", 403, msg)


def err_segregation(msg="Claim reviewer must differ from the claim filer"):
    return ApiError("ERR_SEGREGATION_OF_DUTIES", 403, msg)


# --- existence / request shape ---
def err_not_found(msg="Path identifier does not resolve"):
    return ApiError("ERR_RESOURCE_NOT_FOUND", 404, msg)


def err_invalid_request(msg="Request body not well-formed"):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


# --- entity state (409) ---
def err_invalid_case_state(msg="Case lifecycle_status does not permit this operation"):
    return ApiError("ERR_INVALID_CASE_STATE", 409, msg)


def err_invalid_nots_state(msg="NoticeOfTrusteeSale status does not permit this operation"):
    return ApiError("ERR_INVALID_NOTS_STATE", 409, msg)


def err_invalid_sale_state(msg="AuctionSale status does not permit this operation"):
    return ApiError("ERR_INVALID_SALE_STATE", 409, msg)


def err_invalid_quote_state(msg="Quote status is not ISSUED"):
    return ApiError("ERR_INVALID_QUOTE_STATE", 409, msg)


def err_invalid_registration_state(msg="BidderRegistration status does not permit this operation"):
    return ApiError("ERR_INVALID_REGISTRATION_STATE", 409, msg)


def err_invalid_claim_state(msg="SurplusClaim status is not FILED"):
    return ApiError("ERR_INVALID_CLAIM_STATE", 409, msg)


def err_invalid_deed_state(msg="TrusteesDeed status is not DRAFTED, or a live deed already exists"):
    return ApiError("ERR_INVALID_DEED_STATE", 409, msg)


def err_invalid_instruction_state(msg="BiddingInstruction status is not ACTIVE"):
    return ApiError("ERR_INVALID_INSTRUCTION_STATE", 409, msg)


def err_invalid_disbursement_state(msg="Disbursement status is not CLEARED"):
    return ApiError("ERR_INVALID_DISBURSEMENT_STATE", 409, msg)


def err_stay_not_active(msg="StayOrder status is not ACTIVE"):
    return ApiError("ERR_STAY_NOT_ACTIVE", 409, msg)


def err_active_stay(msg="Case is under an active stay; sale-side action blocked"):
    return ApiError("ERR_ACTIVE_STAY", 409, msg)


def err_sale_not_voidable(msg="Sale is not voidable: recorded deed or surplus distribution exists"):
    return ApiError("ERR_SALE_NOT_VOIDABLE", 409, msg)


def err_auction_conflict(msg="Venue occupied by another scheduled/conducted sale"):
    return ApiError("ERR_AUCTION_SCHEDULE_CONFLICT", 409, msg)


# --- business temporal / constraint / fiscal (422) ---
def err_nots_too_early(msg="Clock date is before NOD recording + 90 days"):
    return ApiError("ERR_NOTS_TOO_EARLY", 422, msg)


def err_publication_gap(msg="run_date must be at least 7 days after the latest sibling run and not in the future"):
    return ApiError("ERR_PUBLICATION_GAP_VIOLATION", 422, msg)


def err_publication_limit(msg="NoticeOfTrusteeSale already has 3 publications"):
    return ApiError("ERR_PUBLICATION_LIMIT", 422, msg)


def err_publication_incomplete(msg="NoticeOfTrusteeSale has not reached PUBLICATION_COMPLETE"):
    return ApiError("ERR_PUBLICATION_INCOMPLETE", 422, msg)


def err_sale_date_too_soon(msg="Sale start before first publication + 20d or NOTS recording + 14d"):
    return ApiError("ERR_SALE_DATE_TOO_SOON", 422, msg)


def err_postponement_limit(msg="NoticeOfTrusteeSale postponement_count already == 3"):
    return ApiError("ERR_POSTPONEMENT_LIMIT", 422, msg)


def err_postponement_window(msg="New start must be in (current start, current start + 30 days]"):
    return ApiError("ERR_POSTPONEMENT_WINDOW", 422, msg)


def err_quote_expired(msg="Clock date is past the quote good_through_date"):
    return ApiError("ERR_QUOTE_EXPIRED", 422, msg)


def err_reinstatement_cutoff(msg="Reinstatement tendered after the sale date minus 5 business days"):
    return ApiError("ERR_REINSTATEMENT_CUTOFF_PASSED", 422, msg)


def err_payment_shortfall(msg="tendered_amount_cents does not equal quote.total_cents"):
    return ApiError("ERR_PAYMENT_SHORTFALL", 422, msg)


def err_no_active_instruction(msg="No ACTIVE BiddingInstruction exists on the case"):
    return ApiError("ERR_NO_ACTIVE_BIDDING_INSTRUCTION", 422, msg)


def err_opening_exceeds_max(msg="opening_bid_cents exceeds max_bid_cents"):
    return ApiError("ERR_OPENING_BID_EXCEEDS_MAX", 422, msg)


def err_deposit_insufficient(msg="deposit_cents below required_deposit_cents"):
    return ApiError("ERR_DEPOSIT_INSUFFICIENT", 422, msg)


def err_bid_too_low(msg="Bid amount below the minimum next bid"):
    return ApiError("ERR_BID_TOO_LOW", 422, msg)


def err_claims_deadline(msg="Claim filed after sale close + 180 days"):
    return ApiError("ERR_CLAIMS_DEADLINE_PASSED", 422, msg)


def err_deed_late(msg="Deed record after close + 15 days without court_order_extension"):
    return ApiError("ERR_DEED_RECORDING_LATE", 422, msg)


def err_sale_not_today(msg="Clock UTC date differs from the scheduled sale date"):
    return ApiError("ERR_SALE_NOT_TODAY", 422, msg)


def err_no_distributable(msg="Nothing to distribute: no surplus, no payable claims, no residue work"):
    return ApiError("ERR_NO_DISTRIBUTABLE_SURPLUS", 422, msg)


def err_beneficiary_suspended(msg="Beneficiary is SUSPENDED; NOD recording blocked"):
    return ApiError("ERR_BENEFICIARY_SUSPENDED", 422, msg)


# --- optimistic concurrency (412) ---
def err_stale_case_version(msg="expected_foreclosure_case_version does not match case.version"):
    return ApiError("ERR_STALE_CASE_VERSION", 412, msg)


def err_stale_sale_version(msg="expected_auction_sale_version does not match sale.version"):
    return ApiError("ERR_STALE_SALE_VERSION", 412, msg)
