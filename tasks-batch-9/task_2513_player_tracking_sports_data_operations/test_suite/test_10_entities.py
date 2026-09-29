"""
Resource shapes: what a create returns, what a read returns, which inputs are
required, which are defaulted, and which are the server's alone to set.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as fac
from test_helpers import fixtures as fx
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import ERR_INVALID_REQUEST, ERR_PLAYER_NOT_FOUND
from test_helpers.assertions import (
    assert_immutable_record_shape,
    assert_installation_census,
    assert_mutable_audit_fields,
    assert_page_meta,
    assert_two_dp,
)
from test_helpers.constants import (
    CERTIFICATION_PENDING,
    COLLECTION_SCHEDULED,
    CURRENT_CBA_VERSION,
    CONSENT_PENDING,
    INSTALLATION_DEPLOYED,
    POSTURE_UNCERTIFIED,
    RELEASE_NONE,
    RESULT_PASS,
    SCOPE_BIOMETRIC_TRACKING,
    TIER_BRONZE,
)
from test_helpers.test_users import (
    ENGINEER_HEADERS,
    ENGINEER_PRIMARY,
    OPS_HEADERS,
    make_club_data_officer_headers,
)


def test_registering_a_venue_seeds_an_empty_census_and_an_uncertified_posture(api):
    """PRD §3.1: "A freshly registered venue starts with `data_posture` of `UNCERTIFIED`
    and with `active_installation_count`, `certified_installation_count`,
    `recalibrating_installation_count`, `uncertified_installation_count` and
    `retired_installation_count` all zero."
    PRD §4: "Creation endpoints return HTTP 201 with the newly minted resource in
    `data`; every other successful operation, including all state transitions, all reads
    and the administrative clock capability, returns HTTP 200 with the affected resource
    in `data`."

    A brand new venue answers 201 with every counter at zero.

    No rig is certified yet, so the posture cannot be anything but UNCERTIFIED.

    Design: Corner/entities/venue_creation_returns_seeded_census_and_uncertified_posture
    """
    venue = get_success_data(
        api.create_venue(fac.venue_payload(), OPS_HEADERS), expected_status=201
    )

    assert venue["name"] == "Harbor Arena"
    assert venue["city"] == "Harbor"
    assert venue["tracking_tech"] == "HYBRID"
    assert venue["required_certified_installations"] == 1
    assert venue["transport_capacity_mbps"] == 100
    assert venue["min_achievable_latency_ms"] == 200
    assert venue["data_posture"] == POSTURE_UNCERTIFIED
    assert_installation_census(venue, certified=0, recalibrating=0, uncertified=0)
    assert venue["active_installation_count"] == 0
    assert is_valid_uuid(venue["id"])
    assert_mutable_audit_fields(venue, expected_version=1)


def test_a_rig_reads_back_with_null_run_mirrors_before_its_first_run(api):
    """PRD §3.1: "A new rig enters the world in `DEPLOYED` status, with
    `latest_run_result`, `latest_run_composite_rms_mm`, `latest_run_recorded_at_utc`,
    `latest_run_engineer_user_id`, `certified_at_utc` and `certified_by_user_id` all
    null, and with `calibration_run_count` and `drift_flag_count` at zero."

    The four latest-run mirrors and both certification stamps are null, not absent.

    Design: Corner/entities/installation_retrieval_returns_null_run_mirrors_before_first_run
    """
    venue = fx.register_venue(api)
    rig = fx.deploy_rig(api, venue["id"])

    fetched = validate_success(api.get_installation(rig["id"], ENGINEER_HEADERS))
    assert fetched["venue_id"] == venue["id"]
    assert fetched["rig_label"] == "RIG-A"
    assert fetched["modality"] == "UWB_ANCHOR"
    assert fetched["status"] == INSTALLATION_DEPLOYED
    for field in (
        "latest_run_result",
        "latest_run_composite_rms_mm",
        "latest_run_recorded_at_utc",
        "latest_run_engineer_user_id",
        "certified_at_utc",
        "certified_by_user_id",
    ):
        assert field in fetched, f"expected the response to carry '{field}'"
        assert fetched[field] is None, f"expected {field} to be null"
    assert fetched["calibration_run_count"] == 0
    assert fetched["drift_flag_count"] == 0


def test_a_listing_reports_the_full_match_count_not_the_page_length(api):
    """PRD §2.3: "Every list response reports `limit`, `offset`, `total_count` and
    `has_more` inside `meta`, where `total_count` is the number of rows matching the
    filters before pagination is applied and `has_more` indicates whether rows remain
    beyond the returned page."

    Two games, a page of one: total_count is 2 and has_more is true.

    Design: Corner/entities/games_listing_returns_pagination_envelope_with_has_more
    """
    venue = fx.register_venue(api)
    clubs = fx.register_clubs(api)
    get_success_data(
        api.create_game(
            fac.game_payload(venue["id"], clubs["home"]["id"], clubs["away"]["id"]),
            OPS_HEADERS,
        )
    )
    get_success_data(
        api.create_game(
            fac.game_payload(
                venue["id"],
                clubs["away"]["id"],
                clubs["home"]["id"],
                scheduled_start_utc="2026-08-02T18:00:00Z",
            ),
            OPS_HEADERS,
        )
    )

    rows, meta = validate_paginated(
        api.list_games(OPS_HEADERS, params={"limit": 1, "offset": 0})
    )
    assert_page_meta(meta, limit=1, offset=0, total_count=2, has_more=True)
    assert len(rows) == 1
    for row in rows:
        assert row["collection_status"] == COLLECTION_SCHEDULED
        assert row["certification_status"] == CERTIFICATION_PENDING


def test_a_venue_without_its_latency_floor_is_refused(api):
    """PRD §3.1: "`min_achievable_latency_ms` is the physical latency floor of the venue's
    transport path, and must be at least 1; no feed session may ask for a delivery
    latency below it."
    PRD §2.10: "Body schema: required fields present, types correct, enum members among
    the declared values, arrays declared non-empty actually non-empty (`allowed_scopes`
    on a rights window and `scope` on a feed session), numeric ranges honoured, no
    unknown fields — otherwise `ERR_INVALID_REQUEST`."

    min_achievable_latency_ms has no default, so omitting it is malformed.

    Design: Corner/entities/venue_missing_required_latency_floor_rejected
    """
    validate_error(
        api.create_venue(
            fac.venue_payload(drop=("min_achievable_latency_ms",)), OPS_HEADERS
        ),
        ERR_INVALID_REQUEST,
    )

    _, meta = validate_paginated(api.list_games(OPS_HEADERS))
    assert meta["total_count"] == 0


def test_biometric_entitlement_defaults_to_false_and_the_ledger_is_seeded(api):
    """PRD §3.8: "The payload names the licensee, declares its `licensee_class` —
    `BROADCASTER`, `COMMERCIAL_LICENSEE` or `DEVELOPER` — its access `tier` of `BRONZE`,
    `SILVER` or `GOLD`, the `granted_units` its licence covers for the term, which must
    be non-negative, and the optional `biometric_entitled` flag, which defaults to false
    and records whether the licence paperwork permits biometric data at all."
    PRD §3.8: "On creation `available_units` is initialised to `granted_units`, while
    `reserved_units`, `consumed_units`, `settled_charge_cents`, `sla_credit_cents` and
    `audit_flag_count` all start at zero."

    The one optional input on a licensee comes back false when omitted.

    Design: Corner/entities/licensee_biometric_entitled_defaults_to_false
    """
    licensee = get_success_data(
        api.create_licensee(
            fac.licensee_payload(
                licensee_class="DEVELOPER",
                tier=TIER_BRONZE,
                drop=("biometric_entitled",),
            ),
            OPS_HEADERS,
        ),
        expected_status=201,
    )

    assert licensee["biometric_entitled"] is False
    assert licensee["granted_units"] == 5000
    assert licensee["available_units"] == 5000
    assert licensee["reserved_units"] == 0
    assert licensee["consumed_units"] == 0
    assert licensee["settled_charge_cents"] == 0
    assert licensee["sla_credit_cents"] == 0
    assert licensee["audit_flag_count"] == 0


def test_a_client_may_not_dictate_a_calibration_verdict(api):
    """PRD §2.10: "Body schema: required fields present, types correct, enum members among
    the declared values, arrays declared non-empty actually non-empty (`allowed_scopes`
    on a rights window and `scope` on a feed session), numeric ranges honoured, no
    unknown fields — otherwise `ERR_INVALID_REQUEST`."
    PRD §3.2: "Two derived values are written onto the run before anything else
    happens."

    composite_rms_mm and result are the server's to compute, not to accept.

    Design: Corner/entities/calibration_run_computed_composite_input_ignored
    """
    venue = fx.register_venue(api)
    rig = fx.deploy_rig(api, venue["id"])

    validate_error(
        api.create_calibration_run(
            rig["id"],
            fac.calibration_run_payload(composite_rms_mm=5.0, result=RESULT_PASS),
            ENGINEER_HEADERS,
        ),
        ERR_INVALID_REQUEST,
    )

    unchanged = validate_success(api.get_installation(rig["id"], ENGINEER_HEADERS))
    assert unchanged["status"] == INSTALLATION_DEPLOYED
    assert unchanged["calibration_run_count"] == 0
    assert unchanged["latest_run_result"] is None

    _, meta = validate_paginated(
        api.list_calibration_runs(rig["id"], ENGINEER_HEADERS)
    )
    assert meta["total_count"] == 0


def test_a_consent_filing_is_stamped_from_the_caller_and_starts_pending(api, clock):
    """PRD §3.3: "A successfully filed record is created in `PENDING`, with
    `submitted_by_club_id` stamped from the filing officer's `X-User-ID`, and with
    `ratified_by_user_id` and `terminated_at_utc` still null."
    PRD §3.3: "The record echoes its `player_id`."

    The filing club comes from the caller's identity and the status is forced.

    Design: Corner/entities/consent_record_system_fields_stamped_from_headers_and_clock
    """
    club = get_success_data(api.create_club(fac.club_payload(), OPS_HEADERS))
    player = fx.register_player(api, club["id"])

    record = get_success_data(
        api.create_consent_record(
            player["id"],
            fac.consent_record_payload(
                effective_from_utc="2026-08-01T12:00:00Z",
                expires_at_utc="2026-08-31T00:00:00Z",
            ),
            make_club_data_officer_headers(club["id"]),
        ),
        expected_status=201,
    )

    assert record["player_id"] == player["id"]
    assert record["scope"] == SCOPE_BIOMETRIC_TRACKING
    assert record["cba_agreement_version"] == CURRENT_CBA_VERSION
    assert record["status"] == CONSENT_PENDING
    assert record["submitted_by_club_id"] == club["id"]
    assert record["ratified_by_user_id"] is None
    assert record["terminated_at_utc"] is None
    assert record["version"] == 1

    unchanged = validate_success(api.get_player(player["id"], OPS_HEADERS))
    assert unchanged["biometric_release_state"] == RELEASE_NONE
    assert unchanged["active_consent_record_id"] is None


def test_a_venue_enum_and_a_venue_range_are_both_enforced(api):
    """PRD §3.1: "A `LeagueDataOps` operator registers one by supplying its `name`, the
    `city` it sits in, and the `tracking_tech` family installed there, which is one of
    `OPTICAL`, `SENSOR_UWB` or `HYBRID`."
    PRD §3.1: "`required_certified_installations` is the number of certified rigs the
    venue needs before it may be considered fully certified, and must be at least 1."
    PRD §2.10: "Body schema: required fields present, types correct, enum members among
    the declared values, arrays declared non-empty actually non-empty (`allowed_scopes`
    on a rights window and `scope` on a feed session), numeric ranges honoured, no
    unknown fields — otherwise `ERR_INVALID_REQUEST`."

    An unlisted tracking family and a zero rig requirement are each malformed.

    Design: Corner/entities/venue_invalid_tracking_tech_enum_rejected
    """
    validate_error(
        api.create_venue(fac.venue_payload(tracking_tech="THERMAL"), OPS_HEADERS),
        ERR_INVALID_REQUEST,
    )
    validate_error(
        api.create_venue(
            fac.venue_payload(required_certified_installations=0), OPS_HEADERS
        ),
        ERR_INVALID_REQUEST,
    )

    venue = fx.register_venue(api)
    _, meta = validate_paginated(
        api.list_venue_installations(venue["id"], OPS_HEADERS)
    )
    assert meta["total_count"] == 0


def test_a_recorded_calibration_run_carries_no_version_or_update_stamp(api):
    """PRD §2.4: "Two record types are immutable once written and therefore carry a
    narrower shape: a `CalibrationRun` and a `LicenseUsageRecord` expose only `id` and
    `created_at`."
    PRD §2.4: "Both `updated_at` and `version` are absent from those two resources."

    An accuracy measurement is an audit fact: id and created_at only.

    Design: Corner/entities/calibration_run_is_immutable_with_no_version_field
    """
    venue = fx.register_venue(api)
    rig = fx.deploy_rig(api, venue["id"])
    fx.record_run(api, rig["id"], ENGINEER_HEADERS)

    rows, meta = validate_paginated(
        api.list_calibration_runs(rig["id"], ENGINEER_HEADERS)
    )
    assert meta["total_count"] == 1
    row = rows[0]
    assert_immutable_record_shape(row)
    assert row["recorded_by_user_id"] == ENGINEER_PRIMARY
    assert_two_dp(row["composite_rms_mm"], 90.00)
    assert row["result"] == RESULT_PASS


def test_an_unknown_player_in_the_path_is_refused_before_the_body_is_judged(api, clock):
    """PRD §2.10: "Path resolution: every path-parameter resource exists, resolved left to
    right — otherwise the matching 404 from §2.5."
    PRD §2.5: "The resolution errors are `ERR_VENUE_NOT_FOUND`,
    `ERR_INSTALLATION_NOT_FOUND`, `ERR_CLUB_NOT_FOUND`, `ERR_PLAYER_NOT_FOUND`,
    `ERR_CONSENT_RECORD_NOT_FOUND`, `ERR_GAME_NOT_FOUND`, `ERR_EVENT_TAG_NOT_FOUND`,
    `ERR_CORRECTION_REQUEST_NOT_FOUND`, `ERR_RIGHTS_WINDOW_NOT_FOUND`,
    `ERR_LICENSEE_NOT_FOUND` and `ERR_FEED_SESSION_NOT_FOUND`, each carrying HTTP 404."

    The parent lookup runs first, even with a deliberately invalid agreement.

    Design: Corner/entities/consent_record_requires_existing_parent_player
    """
    club = get_success_data(api.create_club(fac.club_payload(), OPS_HEADERS))

    validate_error(
        api.create_consent_record(
            NON_EXISTENT_UUID,
            fac.consent_record_payload(
                cba_agreement_version="CBA-2019Z",
                effective_from_utc="2026-08-01T12:00:00Z",
                expires_at_utc="2026-08-31T00:00:00Z",
            ),
            make_club_data_officer_headers(club["id"]),
        ),
        ERR_PLAYER_NOT_FOUND,
    )
