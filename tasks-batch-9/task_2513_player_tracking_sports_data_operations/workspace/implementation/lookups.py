"""Resource resolution helpers (PRD §2.5, rejection ranks 3 and 5).

Path identifiers are resolved strictly left to right and the first unresolvable
one determines the rejection.  The same catalogue serves body-borne references.
"""

from db import store
from errors import ApiError

_COLLECTION_ERRORS = (
    ("venues", "ERR_VENUE_NOT_FOUND"),
    ("installations", "ERR_INSTALLATION_NOT_FOUND"),
    ("clubs", "ERR_CLUB_NOT_FOUND"),
    ("players", "ERR_PLAYER_NOT_FOUND"),
    ("consent_records", "ERR_CONSENT_RECORD_NOT_FOUND"),
    ("games", "ERR_GAME_NOT_FOUND"),
    ("event_tags", "ERR_EVENT_TAG_NOT_FOUND"),
    ("correction_requests", "ERR_CORRECTION_REQUEST_NOT_FOUND"),
    ("rights_windows", "ERR_RIGHTS_WINDOW_NOT_FOUND"),
    ("licensees", "ERR_LICENSEE_NOT_FOUND"),
    ("feed_sessions", "ERR_FEED_SESSION_NOT_FOUND"),
)


def _require(collection, error_id, resource_id):
    row = getattr(store, collection).get(resource_id) if isinstance(resource_id, str) else None
    if row is None:
        raise ApiError(error_id, "Resource %s was not found." % resource_id)
    return row


def require_venue(resource_id):
    return _require("venues", "ERR_VENUE_NOT_FOUND", resource_id)


def require_installation(resource_id):
    return _require("installations", "ERR_INSTALLATION_NOT_FOUND", resource_id)


def require_club(resource_id):
    return _require("clubs", "ERR_CLUB_NOT_FOUND", resource_id)


def require_player(resource_id):
    return _require("players", "ERR_PLAYER_NOT_FOUND", resource_id)


def require_consent_record(resource_id):
    return _require("consent_records", "ERR_CONSENT_RECORD_NOT_FOUND", resource_id)


def require_game(resource_id):
    return _require("games", "ERR_GAME_NOT_FOUND", resource_id)


def require_event_tag(resource_id):
    return _require("event_tags", "ERR_EVENT_TAG_NOT_FOUND", resource_id)


def require_correction_request(resource_id):
    return _require("correction_requests", "ERR_CORRECTION_REQUEST_NOT_FOUND",
                    resource_id)


def require_rights_window(resource_id):
    return _require("rights_windows", "ERR_RIGHTS_WINDOW_NOT_FOUND", resource_id)


def require_licensee(resource_id):
    return _require("licensees", "ERR_LICENSEE_NOT_FOUND", resource_id)


def require_feed_session(resource_id):
    return _require("feed_sessions", "ERR_FEED_SESSION_NOT_FOUND", resource_id)
