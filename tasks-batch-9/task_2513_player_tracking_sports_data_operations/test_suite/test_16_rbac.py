"""
Authorisation: the header gate that answers before any role list is consulted,
the six operational boundaries between the roles, the per-row authority of an
entity-backed officer, and the three counterparty checks.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as fac
from test_helpers import fixtures as fx
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import (
    ERR_NOT_RESOURCE_OWNER,
    ERR_ROLE_NOT_PERMITTED,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_UNAUTHENTICATED,
)
from test_helpers.assertions import (
    assert_game_dimensions,
    assert_installation_census,
    assert_tag_census,
)
from test_helpers.constants import (
    CERTIFICATION_PENDING,
    CLOCK_NOON,
    COLLECTION_SCHEDULED,
    CONSENT_ACTIVE,
    CONSENT_PENDING,
    CONSENT_WITHDRAWN,
    CORRECTION_APPROVED,
    CORRECTION_SUBMITTED,
    INSTALLATION_CERTIFIED,
    INSTALLATION_VALIDATED,
    POSTURE_UNCERTIFIED,
    RELEASE_GRANTED,
    RELEASE_WITHDRAWN,
    ROLE_LEAGUE_DATA_OPS,
    ROLE_LICENSEE,
    ROLE_QUALITY_REVIEWER,
    TAG_ACCEPTED,
    TAG_SUBMITTED,
)
from test_helpers.test_users import (
    ENGINEER_HEADERS,
    ENGINEER_PRIMARY,
    OPS_HEADERS,
    OPS_PRIMARY,
    REVIEWER_HEADERS,
    REVIEWER_PRIMARY,
    STATISTICIAN_HEADERS,
    STATISTICIAN_PRIMARY,
    headers_without_role,
    headers_without_user_id,
    make_club_data_officer_headers,
    make_headers,
)

UNDECLARED_ROLE = "SystemAdmin"
UNDECLARED_ROLE_USER = "root-01"
UNRESOLVED_LICENSEE = "lic-01"
SECOND_DAY_NOON = "2026-08-02T12:00:00Z"
TAG_CLOCK_MS = 60000
CORRECTED_CLOCK_MS = 61000


# ---------------------------------------------------------------------------
# Priority 1 owns three failure shapes
# ---------------------------------------------------------------------------

def test_a_malformed_identity_is_an_authentication_failure_not_a_role_failure(api):
    """PRD §2.1: "Every request must carry two headers: `X-User-ID`, identifying the acting
    principal, and `X-User-Role`, declaring the capacity that principal is acting in."
    PRD §2.1: "A request that omits either header, or that presents an `X-User-Role`
    value outside those six spellings, is rejected with `ERR_UNAUTHENTICATED` (HTTP
    401)."
    PRD §2.10: "Authentication: both headers present and `X-User-Role` among the six
    declared roles — otherwise `ERR_UNAUTHENTICATED`."

    No role header, no user header, and an invented role all answer 401.

    The third call is the interesting one: the role string is well-formed and the
    operation does have a role list, yet an unrecognised spelling is refused as
    authentication rather than as authorisation.

    Design: Corner/rbac/header_gate_returns_unauthenticated_before_the_role_check
    """
    validate_error(
        api.create_venue(fac.venue_payload(), headers_without_role(OPS_PRIMARY)),
        ERR_UNAUTHENTICATED,
    )
    validate_error(
        api.create_venue(
            fac.venue_payload(), headers_without_user_id(ROLE_LEAGUE_DATA_OPS)
        ),
        ERR_UNAUTHENTICATED,
    )
    validate_error(
        api.create_venue(
            fac.venue_payload(), make_headers(UNDECLARED_ROLE_USER, UNDECLARED_ROLE)
        ),
        ERR_UNAUTHENTICATED,
    )

    venue = get_success_data(
        api.create_venue(fac.venue_payload(), OPS_HEADERS), expected_status=201
    )
    assert venue["data_posture"] == POSTURE_UNCERTIFIED
    assert_installation_census(venue, certified=0, recalibrating=0, uncertified=0)
    assert venue["active_installation_count"] == 0

    read_back = validate_success(api.get_venue(venue["id"], OPS_HEADERS))
    assert read_back["id"] == venue["id"]
    _, meta = validate_paginated(api.list_venue_installations(venue["id"], OPS_HEADERS))
    assert meta["total_count"] == 0


# ---------------------------------------------------------------------------
# Priority 2 sweeps the operational boundaries
# ---------------------------------------------------------------------------

def _validated_rig_and_scheduled_game(api: ApiClient) -> fx.World:
    """A measured but uncertified rig, and a game still waiting to go live."""
    world = fx.World()
    world.venue = fx.register_venue(api)
    world.rig = fx.deploy_rig(api, world.venue_id)
    fx.record_run(api, world.rig_id, ENGINEER_HEADERS)
    clubs = fx.register_clubs(api)
    world.home_club = clubs["home"]
    world.away_club = clubs["away"]
    world.player = fx.register_player(api, world.home_club["id"])
    world.game = get_success_data(
        api.create_game(
            fac.game_payload(
                world.venue_id, world.home_club["id"], world.away_club["id"]
            ),
            OPS_HEADERS,
        )
    )
    return world


def test_each_operation_refuses_every_role_outside_its_own_list(api, clock):
    """PRD §2.1: "A request whose headers are well-formed but whose role is not among the
    roles listed for the target operation in §4 is rejected with
    `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    PRD §2.10: "Role authorisation: the acting role is listed for the operation in §4 —
    otherwise `ERR_ROLE_NOT_PERMITTED`."

    Five well-authenticated calls, five different misplaced roles.

    Two of them would also have failed on domain grounds — the engineer is the
    one who measured the rig, and the game has no accepted tags to certify — so
    the 403 proves the role list is read before any of that.

    Design: Corner/rbac/endpoints_reject_every_role_outside_their_declared_list_as_forbidden
    """
    world = _validated_rig_and_scheduled_game(api)

    validate_error(
        api.create_calibration_run(
            world.rig_id, fac.calibration_run_payload(), OPS_HEADERS
        ),
        ERR_ROLE_NOT_PERMITTED,
    )
    validate_error(
        api.certify_installation(world.rig_id, ENGINEER_HEADERS),
        ERR_ROLE_NOT_PERMITTED,
    )
    validate_error(
        api.create_event_tag(
            fac.event_tag_payload(
                world.game_id,
                world.player["id"],
                world.game_version,
                clock_ms=TAG_CLOCK_MS,
            ),
            REVIEWER_HEADERS,
        ),
        ERR_ROLE_NOT_PERMITTED,
    )
    validate_error(
        api.certify_game(world.game_id, REVIEWER_HEADERS), ERR_ROLE_NOT_PERMITTED
    )
    validate_error(
        api.set_clock(SECOND_DAY_NOON, make_headers(UNRESOLVED_LICENSEE, ROLE_LICENSEE)),
        ERR_ROLE_NOT_PERMITTED,
    )

    rig = validate_success(api.get_installation(world.rig_id, ENGINEER_HEADERS))
    assert rig["status"] == INSTALLATION_VALIDATED
    assert rig["calibration_run_count"] == 1
    assert rig["latest_run_engineer_user_id"] == ENGINEER_PRIMARY

    game = validate_success(api.get_game(world.game_id, OPS_HEADERS))
    assert_game_dimensions(game, COLLECTION_SCHEDULED, CERTIFICATION_PENDING)
    assert_tag_census(
        game, draft=0, submitted=0, accepted=0, under_correction=0, superseded=0, total=0
    )
    assert game["version"] == 1

    # The refused clock call left the logical clock where the scenario pinned it,
    # which the next stamped instant reports.
    certified = validate_success(api.certify_installation(world.rig_id, OPS_HEADERS))
    assert certified["certified_at_utc"] == CLOCK_NOON


# ---------------------------------------------------------------------------
# An entity-backed role is authorised per row
# ---------------------------------------------------------------------------

def test_an_officer_of_the_other_club_is_refused_on_filing_and_on_withdrawal(api, clock):
    """PRD §3.3: "Filing requires the acting `X-User-ID` to equal the addressed player's
    `club_id`; anything else is `ERR_NOT_RESOURCE_OWNER`."
    PRD §3.3: "Withdrawal is the club's unilateral right and belongs to the
    `ClubDataOfficer` whose `X-User-ID` equals the player's `club_id`."
    PRD §3.3: "Ratification moves the record `PENDING → ACTIVE`, stamps
    `ratified_by_user_id` with the ratifying operator's `X-User-ID`, and points the
    player's `active_consent_record_id` at the record."

    The same two calls succeed or fail purely on which club is acting.

    The refusal is repeated once before the record exists and once after it is
    ACTIVE, so it cannot be an artefact of the payload or of the record's state.

    Design: Corner/rbac/club_officer_cannot_touch_another_clubs_consent_records
    """
    clubs = fx.register_clubs(api)
    home = clubs["home"]
    away = clubs["away"]
    player = fx.register_player(api, home["id"])
    home_officer = make_club_data_officer_headers(home["id"])
    away_officer = make_club_data_officer_headers(away["id"])

    validate_error(
        api.create_consent_record(
            player["id"], fac.consent_record_payload(), away_officer
        ),
        ERR_NOT_RESOURCE_OWNER,
    )
    _, empty_meta = validate_paginated(
        api.list_consent_records(player["id"], OPS_HEADERS)
    )
    assert empty_meta["total_count"] == 0

    record = get_success_data(
        api.create_consent_record(
            player["id"], fac.consent_record_payload(), home_officer
        ),
        expected_status=201,
    )
    assert record["status"] == CONSENT_PENDING
    assert record["submitted_by_club_id"] == home["id"]
    assert record["player_id"] == player["id"]

    ratified = validate_success(api.ratify_consent_record(record["id"], OPS_HEADERS))
    assert ratified["status"] == CONSENT_ACTIVE
    assert ratified["ratified_by_user_id"] == OPS_PRIMARY

    granted = validate_success(api.get_player(player["id"], OPS_HEADERS))
    assert granted["biometric_release_state"] == RELEASE_GRANTED
    assert granted["active_consent_record_id"] == record["id"]

    validate_error(
        api.withdraw_consent_record(record["id"], away_officer), ERR_NOT_RESOURCE_OWNER
    )
    rows, meta = validate_paginated(
        api.list_consent_records(player["id"], OPS_HEADERS, params={"status": CONSENT_ACTIVE})
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == record["id"]
    assert rows[0]["terminated_at_utc"] is None

    withdrawn = validate_success(
        api.withdraw_consent_record(record["id"], home_officer)
    )
    assert withdrawn["status"] == CONSENT_WITHDRAWN
    assert withdrawn["terminated_at_utc"] == CLOCK_NOON

    after = validate_success(api.get_player(player["id"], OPS_HEADERS))
    assert after["biometric_release_state"] == RELEASE_WITHDRAWN
    assert after["active_consent_record_id"] is None


# ---------------------------------------------------------------------------
# Three counterparty checks, each cleared by a second pair of hands
# ---------------------------------------------------------------------------

def _two_rig_live_game_with_submitted_tag(api: ApiClient) -> fx.World:
    """One certified rig, one merely validated rig, and a tag awaiting review."""
    world = fx.World()
    world.venue = fx.register_venue(api)
    world.rig = fx.certified_rig(api, world.venue_id)
    world.rig_b = fx.deploy_rig(api, world.venue_id, rig_label="RIG-B")
    fx.record_run(api, world.rig_b["id"], ENGINEER_HEADERS)
    clubs = fx.register_clubs(api)
    world.home_club = clubs["home"]
    world.away_club = clubs["away"]
    world.player = fx.register_player(api, world.home_club["id"])
    world.game = get_success_data(
        api.create_game(
            fac.game_payload(
                world.venue_id, world.home_club["id"], world.away_club["id"]
            ),
            OPS_HEADERS,
        )
    )
    world.game = validate_success(api.open_collection(world.game_id, OPS_HEADERS))
    world.tag = fx.create_tag(
        api,
        world.game_id,
        world.player["id"],
        world.game_version,
        STATISTICIAN_HEADERS,
        clock_ms=TAG_CLOCK_MS,
    )
    world.tag = validate_success(
        api.submit_event_tag(world.tag_id, STATISTICIAN_HEADERS)
    )
    return world


def test_nobody_signs_off_their_own_work_and_a_colleague_signs_off_at_once(api, clock):
    """PRD §2.9: "Three operations compare the acting `X-User-ID` against a counterparty
    identifier already recorded on the resource and refuse to proceed when they are
    equal."
    PRD §2.9: "Certifying a tracking installation compares `X-User-ID` against the rig's
    `latest_run_engineer_user_id`; accepting an event tag compares `X-User-ID` against
    the tag's `tagged_by_user_id`; approving or rejecting a correction request compares
    `X-User-ID` against the request's `submitted_by_user_id`."
    PRD §2.9: "In all four operations — certify, accept, approve and reject — an equal
    comparison is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Certifying, accepting and resolving each refuse the recorded counterparty.

    Every refusal is followed immediately by the identical call from a different
    identifier in the same role, which succeeds, so none of the three can be
    explained by the state of the row.

    Design: Corner/rbac/segregation_of_duties_blocks_self_certification_and_self_review
    """
    world = _two_rig_live_game_with_submitted_tag(api)

    validate_error(
        api.certify_installation(
            world.rig_b["id"], make_headers(ENGINEER_PRIMARY, ROLE_LEAGUE_DATA_OPS)
        ),
        ERR_SEGREGATION_OF_DUTIES,
    )
    assert (
        validate_success(api.get_installation(world.rig_b["id"], ENGINEER_HEADERS))[
            "status"
        ]
        == INSTALLATION_VALIDATED
    )

    certified = validate_success(
        api.certify_installation(world.rig_b["id"], OPS_HEADERS)
    )
    assert certified["status"] == INSTALLATION_CERTIFIED
    assert certified["certified_by_user_id"] == OPS_PRIMARY
    venue = validate_success(api.get_venue(world.venue_id, OPS_HEADERS))
    assert venue["certified_installation_count"] == 2

    validate_error(
        api.accept_event_tag(
            world.tag_id, make_headers(STATISTICIAN_PRIMARY, ROLE_QUALITY_REVIEWER)
        ),
        ERR_SEGREGATION_OF_DUTIES,
    )
    assert (
        validate_success(api.get_event_tag(world.tag_id, STATISTICIAN_HEADERS))[
            "review_status"
        ]
        == TAG_SUBMITTED
    )

    accepted = validate_success(api.accept_event_tag(world.tag_id, REVIEWER_HEADERS))
    assert accepted["review_status"] == TAG_ACCEPTED
    assert accepted["reviewed_by_user_id"] == REVIEWER_PRIMARY

    correction = fx.open_correction(
        api, world.tag_id, STATISTICIAN_HEADERS, proposed_clock_ms=CORRECTED_CLOCK_MS
    )
    assert correction["status"] == CORRECTION_SUBMITTED
    assert correction["submitted_by_user_id"] == STATISTICIAN_PRIMARY

    validate_error(
        api.approve_correction(
            correction["id"], make_headers(STATISTICIAN_PRIMARY, ROLE_QUALITY_REVIEWER)
        ),
        ERR_SEGREGATION_OF_DUTIES,
    )
    rows, meta = validate_paginated(
        api.list_correction_requests(world.tag_id, REVIEWER_HEADERS)
    )
    assert meta["total_count"] == 1
    assert rows[0]["status"] == CORRECTION_SUBMITTED

    approved = validate_success(
        api.approve_correction(correction["id"], REVIEWER_HEADERS)
    )
    assert approved["status"] == CORRECTION_APPROVED
    assert approved["reviewed_by_user_id"] == REVIEWER_PRIMARY

    tag = validate_success(api.get_event_tag(world.tag_id, STATISTICIAN_HEADERS))
    assert tag["clock_ms"] == TAG_CLOCK_MS
    assert tag["corrected_clock_ms"] == CORRECTED_CLOCK_MS
    assert tag["correction_count"] == 1
