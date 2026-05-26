"""Error classes and error ID constants."""


class APIError(Exception):
    def __init__(self, error_id: str, http_status: int, message: str = ""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error ID constants
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
ERR_FORBIDDEN = "ERR_FORBIDDEN"
ERR_NOT_FOUND = "ERR_NOT_FOUND"
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_CROSS_ENTITY_STATE = "ERR_CROSS_ENTITY_STATE"
ERR_INVALID_STARTER_PLAYER = "ERR_INVALID_STARTER_PLAYER"
ERR_VETO_SELF_INTEREST = "ERR_VETO_SELF_INTEREST"
ERR_TRADE_PLAYER_NOT_ON_ROSTER = "ERR_TRADE_PLAYER_NOT_ON_ROSTER"
ERR_DROP_PLAYER_NOT_ON_ROSTER = "ERR_DROP_PLAYER_NOT_ON_ROSTER"
ERR_TRADE_LOCKED_DURING_GAME = "ERR_TRADE_LOCKED_DURING_GAME"
ERR_INVALID_WAIVER_WEEK = "ERR_INVALID_WAIVER_WEEK"
ERR_ROSTER_OVER_CAP = "ERR_ROSTER_OVER_CAP"
ERR_KEEPER_OVER_LIMIT = "ERR_KEEPER_OVER_LIMIT"
ERR_FAAB_INSUFFICIENT = "ERR_FAAB_INSUFFICIENT"
ERR_AUCTION_BID_INVALID = "ERR_AUCTION_BID_INVALID"
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"
ERR_STALE_TRADE_VERSION = "ERR_STALE_TRADE_VERSION"
ERR_STALE_WAIVER_VERSION = "ERR_STALE_WAIVER_VERSION"


def err_unauth(msg=""):
    return APIError(ERR_UNAUTHENTICATED, 401, msg or "Missing or empty auth headers.")


def err_forbidden(msg=""):
    return APIError(ERR_FORBIDDEN, 403, msg or "Forbidden.")


def err_not_found(msg=""):
    return APIError(ERR_NOT_FOUND, 404, msg or "Not found.")


def err_invalid_state(msg=""):
    return APIError(ERR_INVALID_STATE, 409, msg or "Invalid state for this transition.")


def err_cross_state(msg=""):
    return APIError(ERR_CROSS_ENTITY_STATE, 409, msg or "Cross-entity state precondition failed.")


def err_invalid_request(msg=""):
    return APIError(ERR_INVALID_REQUEST, 400, msg or "Invalid request.")


def err_faab(msg=""):
    return APIError(ERR_FAAB_INSUFFICIENT, 422, msg or "FAAB insufficient.")


def err_roster_cap(msg=""):
    return APIError(ERR_ROSTER_OVER_CAP, 422, msg or "Roster over cap.")
