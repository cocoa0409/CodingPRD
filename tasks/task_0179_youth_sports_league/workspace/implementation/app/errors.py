"""Domain error definitions and the APIError exception used throughout the service."""
from __future__ import annotations


class APIError(Exception):
    """A structured API error carrying the error_id, HTTP status, and human-readable message."""

    def __init__(self, error_id: str, http_status: int, message: str | None = None) -> None:
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or DEFAULT_MESSAGES.get(error_id, error_id)


# Error catalog: maps error_id -> (http_status, default_message).
ERROR_CATALOG: dict[str, tuple[int, str]] = {
    "ERR_AUTH_REQUIRED": (401, "X-User-ID and X-User-Role headers are required."),
    "ERR_FORBIDDEN": (403, "Role lacks permission for endpoint."),
    "ERR_NOT_OWNER": (403, "Caller is not the owner of the target resource."),
    "ERR_NOT_TEAM_OWNER": (403, "Acting Coach is not the head coach of the target team."),
    "ERR_SEASON_NOT_FOUND": (404, "Season not found."),
    "ERR_TEAM_NOT_FOUND": (404, "Team not found."),
    "ERR_PLAYER_NOT_FOUND": (404, "Player not found."),
    "ERR_GAME_NOT_FOUND": (404, "Game not found."),
    "ERR_SHIFT_NOT_FOUND": (404, "Volunteer shift not found."),
    "ERR_REFERENCE_NOT_FOUND": (404, "A referenced resource does not exist."),
    "ERR_INVALID_STATE": (409, "Entity is not in a valid source state for this transition."),
    "ERR_INVALID_PLAYER_STATE": (409, "Player is not in a valid source state for this transition."),
    "ERR_SEASON_NOT_DRAFT_OPEN": (409, "Operation requires the season to be in DRAFT_OPEN."),
    "ERR_BIRTH_CERT_REQUIRED": (422, "Birth certificate URI is required for age verification."),
    "ERR_AGE_INELIGIBLE": (422, "Player birth date is outside the season age window."),
    "ERR_COACH_NO_BACKGROUND_CHECK": (422, "Head coach must have a passed background check."),
    "ERR_TIER_A_CAP_EXCEEDED": (422, "Team has reached the cap of 3 TIER_A players."),
    "ERR_NOT_TEAMS_TURN": (409, "It is not this team's turn in the snake draft."),
    "ERR_RAINOUT_WINDOW_EXCEEDED": (422, "New scheduled start exceeds the rainout window."),
    "ERR_FIELD_OVERLAP": (409, "Game overlaps another game on the same field."),
    "ERR_REFEREE_OVERLAP": (409, "Referee assignment conflicts within the 30-minute buffer."),
    "ERR_REFEREE_WEEKLY_CAP_EXCEEDED": (422, "Referee weekly assignment cap would be exceeded."),
    "ERR_GAME_REFEREE_ALREADY_ASSIGNED": (409, "Game already has a referee assigned."),
    "ERR_GAME_REFEREE_REQUIRED": (422, "A referee must be assigned before recording a result."),
    "ERR_INVALID_SCORE": (422, "home_score / away_score invalid (negative or equal)."),
    "ERR_INVALID_GAME_OPPONENTS": (422, "home_team_id and away_team_id must differ."),
    "ERR_GAME_OUT_OF_SEASON_WINDOW": (422, "Game scheduled start is outside the regular season window."),
    "ERR_CHECK_IN_OUTSIDE_WINDOW": (422, "Check-in is outside the allowed window."),
    "ERR_TEAM_DUPLICATE": (422, "Team name or draft_position duplicated in season."),
    "ERR_REGULAR_SEASON_INCOMPLETE": (409, "Regular season has non-terminal games."),
    "ERR_SEASON_NOT_READY": (409, "Season is not ready: insufficient teams or rosters."),
    "ERR_VERSION_CONFLICT": (409, "Optimistic concurrency version mismatch."),
    "ERR_VALIDATION": (422, "Validation failed."),
}

DEFAULT_MESSAGES = {eid: msg for eid, (_, msg) in ERROR_CATALOG.items()}


def raise_error(error_id: str, message: str | None = None) -> None:
    """Convenience helper to raise an APIError using the catalog's HTTP status."""
    http_status, default_msg = ERROR_CATALOG.get(error_id, (500, error_id))
    raise APIError(error_id, http_status, message or default_msg)
