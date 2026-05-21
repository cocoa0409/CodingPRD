"""Domain error definitions for the Fantasy Football League API."""


class APIError(Exception):
    """Raised to signal a structured error response."""

    def __init__(self, error_id: str, message: str, http_status: int):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# ---- Auth ----
def err_auth_missing(msg="X-User-ID or X-User-Role header missing."):
    return APIError("ERR_AUTH_MISSING", msg, 401)


def err_auth_invalid_role(msg="X-User-Role is not Commissioner or Manager."):
    return APIError("ERR_AUTH_INVALID_ROLE", msg, 401)


def err_forbidden(msg="Role not permitted for this endpoint."):
    return APIError("ERR_FORBIDDEN", msg, 403)


def err_not_team_owner(msg="Acting Manager does not own this team."):
    return APIError("ERR_NOT_TEAM_OWNER", msg, 403)


def err_not_eligible_voter(msg="Voter is proposer/counterparty or has already voted."):
    return APIError("ERR_NOT_ELIGIBLE_VOTER", msg, 403)


# ---- Existence ----
def err_resource_not_found(msg="Path-referenced resource does not exist."):
    return APIError("ERR_RESOURCE_NOT_FOUND", msg, 404)


def err_reference_not_found(msg="Body-referenced foreign key does not exist."):
    return APIError("ERR_REFERENCE_NOT_FOUND", msg, 422)


# ---- State ----
def err_invalid_state(msg="State precondition violated."):
    return APIError("ERR_INVALID_STATE", msg, 409)


def err_version_conflict(msg="Optimistic concurrency version mismatch."):
    return APIError("ERR_VERSION_CONFLICT", msg, 409)


# ---- Draft / Roster ----
def err_player_already_drafted(msg="Player already drafted in this league."):
    return APIError("ERR_PLAYER_ALREADY_DRAFTED", msg, 409)


def err_player_already_rostered(msg="Player already on a roster in this league."):
    return APIError("ERR_PLAYER_ALREADY_ROSTERED", msg, 409)


def err_player_not_on_roster(msg="Player not currently on the relevant team's roster."):
    return APIError("ERR_PLAYER_NOT_ON_ROSTER", msg, 422)


def err_player_no_longer_eligible(msg="Player is no longer eligible for this claim."):
    return APIError("ERR_PLAYER_NO_LONGER_ELIGIBLE", msg, 409)


def err_player_not_in_waivers(msg="Player is not currently in waivers period."):
    return APIError("ERR_PLAYER_NOT_IN_WAIVERS", msg, 422)


def err_lineup_locked(msg="Lineup is locked for this week."):
    return APIError("ERR_LINEUP_LOCKED", msg, 409)


def err_ir_ineligible(msg="IR slot can only hold OUT or IR_ELIGIBLE players."):
    return APIError("ERR_IR_INELIGIBLE", msg, 422)


def err_roster_shape_invalid(msg="Starter count mismatch or bench overflow."):
    return APIError("ERR_ROSTER_SHAPE_INVALID", msg, 422)


def err_roster_full(msg="Roster size cap would be exceeded."):
    return APIError("ERR_ROSTER_FULL", msg, 422)


def err_position_constraint(msg="Starter slot count per position violated."):
    return APIError("ERR_POSITION_CONSTRAINT", msg, 422)


def err_position_ineligible(msg="Player.position incompatible with slot position_label."):
    return APIError("ERR_POSITION_INELIGIBLE", msg, 422)


def err_faab_insufficient(msg="WaiverClaim.bid_dollars exceeds Team.faab_balance_dollars."):
    return APIError("ERR_FAAB_INSUFFICIENT", msg, 422)


def err_auction_budget_exceeded(msg="AUCTION pick would leave fewer dollars than required."):
    return APIError("ERR_AUCTION_BUDGET_EXCEEDED", msg, 422)


def err_waiver_settle_in_past(msg="settle_ts must be > League.now_ts."):
    return APIError("ERR_WAIVER_SETTLE_IN_PAST", msg, 422)


def err_keeper_cap_exceeded(msg="KeeperDesignation count exceeds keeper_cap."):
    return APIError("ERR_KEEPER_CAP_EXCEEDED", msg, 422)


def err_not_your_turn(msg="Not this team's snake draft turn."):
    return APIError("ERR_NOT_YOUR_TURN", msg, 409)


def err_two_way_faab_forbidden(msg="Trade specifies non-zero FAAB in both directions."):
    return APIError("ERR_TWO_WAY_FAAB_FORBIDDEN", msg, 422)


def err_trade_not_open_for_voting(msg="Trade is not in ACCEPTED_PENDING_REVIEW."):
    return APIError("ERR_TRADE_NOT_OPEN_FOR_VOTING", msg, 409)


def err_validation(msg="Field type, range, or format invalid."):
    return APIError("ERR_VALIDATION", msg, 422)
