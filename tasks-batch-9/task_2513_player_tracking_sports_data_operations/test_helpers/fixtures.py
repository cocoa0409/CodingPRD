"""
Composite state builders.

The server is restarted with an empty database before every individual test, so
each of these builders drives the public endpoints from scratch. They return the
rows they created so a test can assert against ids and versions without
re-reading everything by hand.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories
from .api_client import ApiClient
from .constants import CLOCK_NOON, SCOPE_POSITIONAL
from .test_users import (
    ENGINEER_ALT_HEADERS,
    ENGINEER_HEADERS,
    OPS_HEADERS,
    REVIEWER_HEADERS,
    STATISTICIAN_HEADERS,
    make_club_data_officer_headers,
    make_licensee_headers,
)
from .types import Headers, Json


@dataclass
class World:
    """The rows a scenario built, in dependency order."""

    venue: Optional[Json] = None
    rig: Optional[Json] = None
    rig_b: Optional[Json] = None
    home_club: Optional[Json] = None
    away_club: Optional[Json] = None
    third_club: Optional[Json] = None
    player: Optional[Json] = None
    away_player: Optional[Json] = None
    consent: Optional[Json] = None
    game: Optional[Json] = None
    licensee: Optional[Json] = None
    window: Optional[Json] = None
    session: Optional[Json] = None
    tag: Optional[Json] = None
    correction: Optional[Json] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    @property
    def venue_id(self) -> str:
        return self.venue["id"]

    @property
    def rig_id(self) -> str:
        return self.rig["id"]

    @property
    def game_id(self) -> str:
        return self.game["id"]

    @property
    def game_version(self) -> int:
        return self.game["version"]

    @property
    def licensee_id(self) -> str:
        return self.licensee["id"]

    @property
    def window_id(self) -> str:
        return self.window["id"]

    @property
    def session_id(self) -> str:
        return self.session["id"]

    @property
    def tag_id(self) -> str:
        return self.tag["id"]

    @property
    def home_officer(self) -> Headers:
        return make_club_data_officer_headers(self.home_club["id"])

    @property
    def away_officer(self) -> Headers:
        return make_club_data_officer_headers(self.away_club["id"])

    @property
    def licensee_headers(self) -> Headers:
        return make_licensee_headers(self.licensee["id"])


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

def pin_clock(api: ApiClient, to_iso8601: str = CLOCK_NOON, headers: Headers = OPS_HEADERS) -> Json:
    """Move the logical clock to a known instant."""
    return get_success_data(api.set_clock(to_iso8601, headers))


# ---------------------------------------------------------------------------
# Venue and rigs
# ---------------------------------------------------------------------------

def register_venue(api: ApiClient, headers: Headers = OPS_HEADERS, **overrides) -> Json:
    return get_success_data(api.create_venue(factories.venue_payload(**overrides), headers))


def deploy_rig(
    api: ApiClient, venue_id: str, headers: Headers = OPS_HEADERS, **overrides
) -> Json:
    return get_success_data(
        api.create_installation(factories.installation_payload(venue_id, **overrides), headers)
    )


def record_run(
    api: ApiClient,
    installation_id: str,
    headers: Headers = ENGINEER_HEADERS,
    **overrides,
) -> Json:
    return get_success_data(
        api.create_calibration_run(
            installation_id, factories.calibration_run_payload(**overrides), headers
        )
    )


def certify_rig(
    api: ApiClient,
    installation_id: str,
    headers: Headers = OPS_HEADERS,
) -> Json:
    return get_success_data(api.certify_installation(installation_id, headers))


def certified_rig(
    api: ApiClient,
    venue_id: str,
    rig_label: str = "RIG-A",
    engineer: Headers = ENGINEER_HEADERS,
    ops: Headers = OPS_HEADERS,
    **rig_overrides,
) -> Json:
    """Deploy a rig, measure a passing run on it, and certify it."""
    rig = deploy_rig(api, venue_id, ops, rig_label=rig_label, **rig_overrides)
    record_run(api, rig["id"], engineer)
    return certify_rig(api, rig["id"], ops)


def certified_venue(api: ApiClient, **venue_overrides) -> World:
    """A venue at CERTIFIED posture behind a single certified rig."""
    world = World()
    world.venue = register_venue(api, **venue_overrides)
    world.rig = certified_rig(api, world.venue["id"])
    world.venue = get_success_data(api.get_venue(world.venue["id"], OPS_HEADERS))
    return world


def two_rig_venue(api: ApiClient, **venue_overrides) -> World:
    """A venue that requires two certified rigs, with both rigs certified.

    The second rig is measured by a different engineer so that either rig can be
    certified by an operator who did not measure it.
    """
    overrides = {"required_certified_installations": 2}
    overrides.update(venue_overrides)
    world = World()
    world.venue = register_venue(api, **overrides)
    world.rig = certified_rig(api, world.venue["id"], rig_label="RIG-A")
    world.rig_b = certified_rig(
        api, world.venue["id"], rig_label="RIG-B", engineer=ENGINEER_ALT_HEADERS
    )
    world.venue = get_success_data(api.get_venue(world.venue["id"], OPS_HEADERS))
    return world


# ---------------------------------------------------------------------------
# Clubs and players
# ---------------------------------------------------------------------------

def register_clubs(api: ApiClient, headers: Headers = OPS_HEADERS) -> Dict[str, Json]:
    home = get_success_data(api.create_club(factories.club_payload(), headers))
    away = get_success_data(api.create_club(factories.away_club_payload(), headers))
    return {"home": home, "away": away}


def register_player(
    api: ApiClient, club_id: str, headers: Headers = OPS_HEADERS, **overrides
) -> Json:
    return get_success_data(
        api.create_player(factories.player_payload(club_id, **overrides), headers)
    )


def granted_biometric_consent(api: ApiClient, player_id: str, club_id: str) -> Json:
    """File and ratify a BIOMETRIC_TRACKING consent so the player reads GRANTED."""
    record = get_success_data(
        api.create_consent_record(
            player_id,
            factories.consent_record_payload(),
            make_club_data_officer_headers(club_id),
        )
    )
    return get_success_data(api.ratify_consent_record(record["id"], OPS_HEADERS))


# ---------------------------------------------------------------------------
# Games
# ---------------------------------------------------------------------------

def scheduled_game_world(api: ApiClient, venue_overrides: Optional[Dict] = None, **game_overrides) -> World:
    """Certified venue, two clubs, one home player, one SCHEDULED game."""
    world = certified_venue(api, **(venue_overrides or {}))
    clubs = register_clubs(api)
    world.home_club = clubs["home"]
    world.away_club = clubs["away"]
    world.player = register_player(api, world.home_club["id"])
    world.game = get_success_data(
        api.create_game(
            factories.game_payload(
                world.venue["id"],
                world.home_club["id"],
                world.away_club["id"],
                **game_overrides,
            ),
            OPS_HEADERS,
        )
    )
    return world


def live_game_world(api: ApiClient, venue_overrides: Optional[Dict] = None, **game_overrides) -> World:
    """The scheduled-game world with collection opened, so the game reads LIVE."""
    world = scheduled_game_world(api, venue_overrides, **game_overrides)
    world.game = get_success_data(api.open_collection(world.game["id"], OPS_HEADERS))
    return world


def onboard_licensee(api: ApiClient, headers: Headers = OPS_HEADERS, **overrides) -> Json:
    return get_success_data(api.create_licensee(factories.licensee_payload(**overrides), headers))


def allocate_window(
    api: ApiClient, game_id: str, holder_id: Optional[str] = None, **overrides
) -> Json:
    return get_success_data(
        api.create_rights_window(
            game_id, factories.rights_window_payload(holder_id, **overrides), OPS_HEADERS
        )
    )


def open_session(
    api: ApiClient,
    licensee_id: str,
    game_id: str,
    window_id: str,
    **overrides,
) -> Json:
    return get_success_data(
        api.create_feed_session(
            factories.feed_session_payload(game_id, window_id, **overrides),
            make_licensee_headers(licensee_id),
        )
    )


def licensed_live_game_world(
    api: ApiClient,
    licensee_overrides: Optional[Dict] = None,
    window_overrides: Optional[Dict] = None,
    venue_overrides: Optional[Dict] = None,
    **game_overrides,
) -> World:
    """A LIVE game with a GOLD licensee and an ACTIVE commercial rights window."""
    world = live_game_world(api, venue_overrides, **game_overrides)
    world.licensee = onboard_licensee(api, **(licensee_overrides or {}))
    world.window = allocate_window(
        api, world.game["id"], world.licensee["id"], **(window_overrides or {})
    )
    world.game = get_success_data(api.get_game(world.game["id"], OPS_HEADERS))
    return world


def active_session_world(
    api: ApiClient,
    session_overrides: Optional[Dict] = None,
    licensee_overrides: Optional[Dict] = None,
    window_overrides: Optional[Dict] = None,
    venue_overrides: Optional[Dict] = None,
    **game_overrides,
) -> World:
    """The licensed LIVE game plus one ACTIVE 20 mbps real-time session."""
    world = licensed_live_game_world(
        api,
        licensee_overrides=licensee_overrides,
        window_overrides=window_overrides,
        venue_overrides=venue_overrides,
        **game_overrides,
    )
    world.session = open_session(
        api,
        world.licensee["id"],
        world.game["id"],
        world.window["id"],
        **(session_overrides or {}),
    )
    world.licensee = get_success_data(
        api.get_licensee(world.licensee["id"], OPS_HEADERS)
    )
    return world


# ---------------------------------------------------------------------------
# Tags, corrections and certification
# ---------------------------------------------------------------------------

def create_tag(
    api: ApiClient,
    game_id: str,
    player_id: str,
    expected_game_version: int,
    headers: Headers = STATISTICIAN_HEADERS,
    **overrides,
) -> Json:
    return get_success_data(
        api.create_event_tag(
            factories.event_tag_payload(
                game_id, player_id, expected_game_version, **overrides
            ),
            headers,
        )
    )


def accepted_tag(
    api: ApiClient,
    game_id: str,
    player_id: str,
    expected_game_version: int,
    tagger: Headers = STATISTICIAN_HEADERS,
    reviewer: Headers = REVIEWER_HEADERS,
    **overrides,
) -> Json:
    """Create, submit and accept one tag; the reviewer differs from the tagger."""
    tag = create_tag(api, game_id, player_id, expected_game_version, tagger, **overrides)
    get_success_data(api.submit_event_tag(tag["id"], tagger))
    return get_success_data(api.accept_event_tag(tag["id"], reviewer))


def accepted_tag_world(api: ApiClient, **tag_overrides) -> World:
    """A LIVE game carrying exactly one ACCEPTED tag, so certification is PROVISIONAL."""
    world = live_game_world(api)
    world.tag = accepted_tag(
        api,
        world.game["id"],
        world.player["id"],
        world.game["version"],
        **tag_overrides,
    )
    world.game = get_success_data(api.get_game(world.game["id"], OPS_HEADERS))
    return world


def collected_game_world(api: ApiClient, **tag_overrides) -> World:
    """The accepted-tag world with collection closed."""
    world = accepted_tag_world(api, **tag_overrides)
    world.game = get_success_data(api.close_collection(world.game["id"], OPS_HEADERS))
    return world


def official_game_world(api: ApiClient, **tag_overrides) -> World:
    """A COLLECTED game certified once, so it reads OFFICIAL and ARCHIVED."""
    world = collected_game_world(api, **tag_overrides)
    world.game = get_success_data(api.certify_game(world.game["id"], OPS_HEADERS))
    return world


def open_correction(
    api: ApiClient,
    tag_id: str,
    headers: Headers = STATISTICIAN_HEADERS,
    **overrides,
) -> Json:
    return get_success_data(
        api.create_correction_request(
            tag_id, factories.correction_request_payload(**overrides), headers
        )
    )


def positional_scope() -> List[str]:
    return [SCOPE_POSITIONAL]
