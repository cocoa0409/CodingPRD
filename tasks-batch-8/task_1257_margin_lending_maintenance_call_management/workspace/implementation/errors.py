"""ApiError carries the scaffold-declared (error_id, http_status) pair.

Error ids and statuses come verbatim from SCAFFOLD.yaml section 1.6 /
PRD section 5. Nothing here is invented.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def err(error_id, status, message):
    return ApiError(error_id, status, message)


# --- auth / request shape -------------------------------------------------
def missing_context(msg="X-User-ID or X-User-Role missing or role unrecognized"):
    return ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400, msg)


def insufficient_permissions(msg="Role not permitted for this endpoint"):
    return ApiError("ERR_INSUFFICIENT_PERMISSIONS", 403, msg)


def invalid_request(msg="Malformed body, missing required field, bad enum, or non-positive amount/quantity"):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


# --- existence (404 catalogue, PRD 2.9) ------------------------------------
def customer_not_found(msg="Customer id does not exist"):
    return ApiError("ERR_CUSTOMER_NOT_FOUND", 404, msg)


def application_not_found(msg="AccountApplication id does not exist"):
    return ApiError("ERR_APPLICATION_NOT_FOUND", 404, msg)


def account_not_found(msg="MarginAccount id does not exist"):
    return ApiError("ERR_ACCOUNT_NOT_FOUND", 404, msg)


def security_not_found(msg="SecurityProfile id does not exist"):
    return ApiError("ERR_SECURITY_NOT_FOUND", 404, msg)


def position_not_found(msg="Position id does not exist"):
    return ApiError("ERR_POSITION_NOT_FOUND", 404, msg)


def call_not_found(msg="MarginCall id does not exist"):
    return ApiError("ERR_CALL_NOT_FOUND", 404, msg)


def liquidation_order_not_found(msg="LiquidationOrder id does not exist"):
    return ApiError("ERR_LIQUIDATION_ORDER_NOT_FOUND", 404, msg)


def dispute_not_found(msg="Dispute id does not exist"):
    return ApiError("ERR_DISPUTE_NOT_FOUND", 404, msg)


def rate_tier_not_found(msg="RateTier id does not exist"):
    return ApiError("ERR_RATE_TIER_NOT_FOUND", 404, msg)


def fill_not_found(msg="TradeFill id does not exist"):
    return ApiError("ERR_FILL_NOT_FOUND", 404, msg)


def day_trade_event_not_found(msg="DayTradeEvent id does not exist"):
    return ApiError("ERR_DAY_TRADE_EVENT_NOT_FOUND", 404, msg)


def mark_not_found(msg="PriceMark id does not exist"):
    return ApiError("ERR_MARK_NOT_FOUND", 404, msg)


def cash_movement_not_found(msg="CashMovement id does not exist"):
    return ApiError("ERR_CASH_MOVEMENT_NOT_FOUND", 404, msg)


def interest_entry_not_found(msg="InterestLedgerEntry id does not exist"):
    return ApiError("ERR_INTEREST_ENTRY_NOT_FOUND", 404, msg)


# --- ownership / state ------------------------------------------------------
def ownership_mismatch(msg="X-User-ID is not the owning customer of the target resource"):
    return ApiError("ERR_ACCOUNT_OWNERSHIP_MISMATCH", 403, msg)


def account_closed(msg="Operation requires a non-CLOSED account"):
    return ApiError("ERR_ACCOUNT_CLOSED", 409, msg)


def account_restricted(msg="Opening orders and withdrawals require account_status ACTIVE"):
    return ApiError("ERR_ACCOUNT_RESTRICTED", 409, msg)


def application_invalid_state(msg="Application not in a valid from-state for the invoked transition"):
    return ApiError("ERR_APPLICATION_INVALID_STATE", 409, msg)


def segregation_of_duties(msg="Same X-User-ID attempted both halves of a controlled step"):
    return ApiError("ERR_SEGREGATION_OF_DUTIES", 403, msg)


def suitability_not_met(msg="Approval suitability: liquid net worth < 200000 cents or experience < 1 year"):
    return ApiError("ERR_SUITABILITY_NOT_MET", 422, msg)


def account_already_exists(msg="Customer already has a MarginAccount"):
    return ApiError("ERR_ACCOUNT_ALREADY_EXISTS", 422, msg)


def pdt_min_equity(msg="PDT-flagged account with equity_realtime below 2500000 cents attempted an opening order"):
    return ApiError("ERR_PDT_MIN_EQUITY", 403, msg)


def security_not_marginable(msg="Opening order on a non-marginable security"):
    return ApiError("ERR_SECURITY_NOT_MARGINABLE", 422, msg)


def no_market_mark(msg="No REALTIME mark exists for the security at order time"):
    return ApiError("ERR_NO_MARKET_MARK", 422, msg)


def invalid_mark(msg="Mark price_cents must be positive"):
    return ApiError("ERR_INVALID_MARK", 400, msg)


def call_not_open(msg="Dispute or waiver requires call OPEN (waive also allows EXPIRED)"):
    return ApiError("ERR_CALL_NOT_OPEN", 409, msg)


def call_not_expired(msg="Liquidation order creation requires the referenced call EXPIRED"):
    return ApiError("ERR_CALL_NOT_EXPIRED", 409, msg)


def dispute_invalid_state(msg="Dispute not in a valid from-state for the invoked transition"):
    return ApiError("ERR_DISPUTE_INVALID_STATE", 409, msg)


def duplicate_dispute(msg="An OPEN or UNDER_REVIEW dispute already exists for this call"):
    return ApiError("ERR_DUPLICATE_DISPUTE", 409, msg)


def liquidation_invalid_state(msg="Fill/cancel requires order PENDING or PARTIALLY_FILLED"):
    return ApiError("ERR_LIQUIDATION_INVALID_STATE", 409, msg)


def fill_exceeds_quantity(msg="filled_quantity <= 0 or exceeds the remaining unfilled quantity"):
    return ApiError("ERR_FILL_EXCEEDS_QUANTITY", 422, msg)


def liquidation_in_progress(msg="Another non-terminal liquidation order exists for this account"):
    return ApiError("ERR_LIQUIDATION_IN_PROGRESS", 409, msg)


def position_reserved(msg="Selected position is already reserved by a non-terminal liquidation order"):
    return ApiError("ERR_POSITION_RESERVED", 409, msg)


def no_liquidatable_positions(msg="No eligible unreserved positions, or total eligible official market value < call amount"):
    return ApiError("ERR_NO_LIQUIDATABLE_POSITIONS", 409, msg)


def insufficient_buying_power(msg="Post-trade equity fails Reg T initial or house requirement"):
    return ApiError("ERR_INSUFFICIENT_BUYING_POWER", 402, msg)


def insufficient_cash(msg="Withdrawal/journal debit exceeds cash_balance_cents"):
    return ApiError("ERR_INSUFFICIENT_CASH", 402, msg)


def maintenance_excess_negative(msg="Post-withdrawal official binding maintenance excess would be < 0"):
    return ApiError("ERR_MAINTENANCE_EXCESS_NEGATIVE", 402, msg)


def rate_tier_overlap(msg="Effective window shares a calendar date with another tier of the same tier_level"):
    return ApiError("ERR_RATE_TIER_OVERLAP", 409, msg)


def positions_exist(msg="Close requires all position quantities == 0"):
    return ApiError("ERR_POSITIONS_EXIST", 409, msg)


def open_calls_exist(msg="Close requires no non-terminal margin calls"):
    return ApiError("ERR_OPEN_CALLS_EXIST", 409, msg)


def nonzero_balance(msg="Close requires cash_balance_cents == 0"):
    return ApiError("ERR_NONZERO_BALANCE", 409, msg)


def clock_regression(msg="set_current_utc to an earlier time than the current logical clock"):
    return ApiError("ERR_CLOCK_REGRESSION", 400, msg)


def stale_version(msg="expected_account_version does not match the account's current version"):
    return ApiError("ERR_STALE_VERSION", 412, msg)
