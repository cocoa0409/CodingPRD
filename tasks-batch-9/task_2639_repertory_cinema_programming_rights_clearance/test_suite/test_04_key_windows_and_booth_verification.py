"""KDM validity windows, coverage of a screening, and the booth playback test.

Key validity is a closed interval measured against a screening's `end_at`,
whereas screen occupancy runs to `blocked_until` — the asymmetry is deliberate
and every test here pins one side of it.
"""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_kdm_key,
    advance_asset,
    book_asset,
    issue_kdm,
    kdm_key_payload,
    place_showtime,
    read_asset,
    read_kdm,
    read_showtime,
    setup_ingested_package_world,
    setup_programming_baseline,
    validate_error,
    validate_paginated,
    verify_booth_playback,
    walk_asset_to,
)


def _two_package_world():
    """Two encrypted, ingested packages of one title, one screening on each."""
    world = setup_ingested_package_world(
        asset_overrides={
            "carrier_ref": "WB-77120",
            "ingest_window_start_at": "2026-07-30T08:00:00Z",
            "ingest_window_end_at": "2026-07-31T08:00:00Z",
        }
    )
    second_asset = book_asset(
        world["title"]["id"],
        world["distributor"]["id"],
        world["venue"]["id"],
        is_encrypted=True,
        carrier_ref="WB-77121",
        ingest_window_start_at="2026-07-29T08:00:00Z",
        ingest_window_end_at="2026-07-30T08:00:00Z",
    )
    world["second_asset"] = walk_asset_to(second_asset["id"], "INGESTED")
    world["first_showtime"] = place_showtime(world, "2026-08-14T12:00:00Z")
    world["second_showtime"] = place_showtime(
        world, "2026-08-15T12:00:00Z", dcp_asset_id=world["second_asset"]["id"]
    )
    return world


class TestKeyCoverageMeasuredToEndAt:
    """A key need not span the turnaround buffer, only the on-screen content."""

    def test_key_expiring_exactly_at_end_at_arms_the_screening(self):
        """A key stopping on the final frame still covers the screening.

        PRD: "Coverage means the key's `valid_from` is at or before the screening's `start_at` and its `valid_until` is at or after the screening's `end_at`; note the deliberate asymmetry with screen occupancy, which is measured to `blocked_until` — the projector is idle during turnaround, so a key need not span the reset buffer, and a key expiring at exactly `end_at` still covers."

        Design: Difficulty/boundary_precision_check/kdm_valid_until_equal_to_showtime_end_at_still_covers
        """
        world = _two_package_world()
        assert world["first_showtime"]["end_at"] == "2026-08-14T13:56:00.000Z"
        assert world["first_showtime"]["blocked_until"] == "2026-08-14T14:21:00.000Z"

        key = issue_kdm(
            world["asset"]["id"],
            world["venue"]["id"],
            "2026-08-14T11:00:00Z",
            "2026-08-14T13:56:00Z",
        )

        assert_kdm_key(key)
        assert key["status"] == "ISSUED"
        assert key["valid_until"] == "2026-08-14T13:56:00.000Z", (
            "the key expires before the reset buffer ends"
        )
        armed = read_showtime(world["first_showtime"]["id"])
        assert armed["playback_status"] == "KEY_PENDING"

    def test_key_expiring_one_minute_before_end_at_does_not_arm_the_screening(self):
        """One minute short of the final frame is not coverage.

        PRD: "A successful issue creates the key in `ISSUED` with a null `revoked_reason`, and it arms the calendar: every screening at that auditorium on that package whose status is `SCHEDULED` and whose `playback_status` is either `UNVERIFIED` or `PLAYBACK_FAILED`, and which the new key covers, moves to `KEY_PENDING`."

        Design: Difficulty/boundary_precision_check/kdm_valid_until_equal_to_showtime_end_at_still_covers
        """
        world = _two_package_world()
        assert world["second_showtime"]["end_at"] == "2026-08-15T13:56:00.000Z"

        key = issue_kdm(
            world["second_asset"]["id"],
            world["venue"]["id"],
            "2026-08-15T11:00:00Z",
            "2026-08-15T13:55:00Z",
        )

        assert key["status"] == "ISSUED"
        assert key["revoked_reason"] is None
        uncovered = read_showtime(world["second_showtime"]["id"])
        assert uncovered["playback_status"] == "UNVERIFIED", (
            "a key one minute short of end_at arms nothing"
        )

    def test_booth_test_passes_on_the_key_that_stops_at_end_at(self):
        """The armed screening clears its booth test while its sibling does not.

        PRD: "A passing test moves `KEY_PENDING → PLAYBACK_VERIFIED`; a failing one moves `KEY_PENDING → PLAYBACK_FAILED`, from which cutting a fresh covering key re-arms the screening back to `KEY_PENDING` and the booth can test again — the retest cycle exists precisely because a failed test is usually a bad KDM rather than a bad print."

        Design: Difficulty/boundary_precision_check/kdm_valid_until_equal_to_showtime_end_at_still_covers
        """
        world = _two_package_world()
        covering = issue_kdm(
            world["asset"]["id"],
            world["venue"]["id"],
            "2026-08-14T11:00:00Z",
            "2026-08-14T13:56:00Z",
        )
        short = issue_kdm(
            world["second_asset"]["id"],
            world["venue"]["id"],
            "2026-08-15T11:00:00Z",
            "2026-08-15T13:55:00Z",
        )

        verified = verify_booth_playback(world["first_showtime"]["id"], "PASS")

        assert verified["playback_status"] == "PLAYBACK_VERIFIED"
        assert verified["status"] == "SCHEDULED"
        assert read_showtime(world["second_showtime"]["id"])["playback_status"] == (
            "UNVERIFIED"
        )
        assert read_kdm(covering["id"])["status"] == "ISSUED"
        assert read_kdm(short["id"])["status"] == "ISSUED"
        assert read_asset(world["asset"]["id"])["status"] == "INGESTED"


class TestKeyWindowsMustBeStrictlyDisjoint:
    """Two issued keys on one package-and-venue pair may not even touch."""

    def test_key_starting_exactly_at_another_keys_valid_until_is_an_overlap(
        self, technical_manager_headers
    ):
        """The shared instant belongs to both closed intervals, so it is refused.

        PRD: "**Key validity is closed.** An issued key covers the closed interval from its `valid_from` through its `valid_until` inclusive, and two issued keys for the same package-and-venue pair must be **strictly disjoint**: a candidate whose `valid_from` falls exactly on another issued key's `valid_until` is an overlap and is refused."

        Design: Difficulty/resource_temporal_overlap/kdm_validity_closed_interval_requires_strictly_disjoint_keys
        """
        world = setup_programming_baseline(asset_overrides={"is_encrypted": True})
        issue_kdm(
            world["asset"]["id"],
            world["venue"]["id"],
            "2026-08-14T08:00:00Z",
            "2026-08-14T20:00:00Z",
            server_ref="SRV-CERT-9",
        )

        response = api_client.create_kdm_key(
            kdm_key_payload(
                world["asset"]["id"],
                world["venue"]["id"],
                "2026-08-14T20:00:00Z",
                "2026-08-15T02:00:00Z",
            ),
            technical_manager_headers,
        )

        validate_error(response, ApiErrorId.ERR_KDM_WINDOW_OVERLAP)

    def test_key_starting_one_second_after_the_previous_valid_until_is_admitted(self):
        """A single second of separation makes the two intervals disjoint.

        PRD: "Key-window disjointness — a new key's closed validity interval is strictly disjoint from every other issued key for the same package-and-venue pair, and its start is strictly before its end (`ERR_KDM_WINDOW_OVERLAP`)."

        Design: Difficulty/resource_temporal_overlap/kdm_validity_closed_interval_requires_strictly_disjoint_keys
        """
        world = setup_programming_baseline(asset_overrides={"is_encrypted": True})
        issue_kdm(
            world["asset"]["id"],
            world["venue"]["id"],
            "2026-08-14T08:00:00Z",
            "2026-08-14T20:00:00Z",
            server_ref="SRV-CERT-9",
        )

        second = issue_kdm(
            world["asset"]["id"],
            world["venue"]["id"],
            "2026-08-14T20:00:01Z",
            "2026-08-15T02:00:00Z",
        )

        assert_kdm_key(second)
        assert second["status"] == "ISSUED"
        assert second["valid_from"] == "2026-08-14T20:00:01.000Z"
        assert second["valid_until"] == "2026-08-15T02:00:00.000Z"

    def test_refused_key_leaves_one_issued_key_and_an_untouched_package(
        self, technical_manager_headers
    ):
        """The refusal mints nothing, and the admitted pair both stay issued.

        PRD: "Issuing one names the `dcp_asset_id` it unlocks, the `venue_id` whose projection server it is bound to, the `server_ref` naming the projector or server certificate the KDM was cut for, and the closed validity interval `valid_from` through `valid_until`, the latter strictly after the former."

        Design: Difficulty/resource_temporal_overlap/kdm_validity_closed_interval_requires_strictly_disjoint_keys
        """
        world = setup_programming_baseline(asset_overrides={"is_encrypted": True})
        first = issue_kdm(
            world["asset"]["id"],
            world["venue"]["id"],
            "2026-08-14T08:00:00Z",
            "2026-08-14T20:00:00Z",
            server_ref="SRV-CERT-9",
        )

        validate_error(
            api_client.create_kdm_key(
                kdm_key_payload(
                    world["asset"]["id"],
                    world["venue"]["id"],
                    "2026-08-14T20:00:00Z",
                    "2026-08-15T02:00:00Z",
                ),
                technical_manager_headers,
            ),
            ApiErrorId.ERR_KDM_WINDOW_OVERLAP,
        )

        rows, meta = validate_paginated(
            api_client.list_kdm_keys(
                technical_manager_headers, {"dcp_asset_id": world["asset"]["id"]}
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == first["id"]
        assert rows[0]["status"] == "ISSUED"

        issue_kdm(
            world["asset"]["id"],
            world["venue"]["id"],
            "2026-08-14T20:00:01Z",
            "2026-08-15T02:00:00Z",
        )
        rows, meta = validate_paginated(
            api_client.list_kdm_keys(
                technical_manager_headers, {"dcp_asset_id": world["asset"]["id"]}
            )
        )
        assert meta["total_count"] == 2
        assert all(row["status"] == "ISSUED" for row in rows)
        assert read_asset(world["asset"]["id"])["status"] == "REQUESTED"


def _received_package_world():
    """An encrypted package stopped at RECEIVED, with a covering key already cut."""
    world = setup_programming_baseline(
        asset_overrides={"is_encrypted": True}, asset_target_status="RECEIVED"
    )
    world["showtime"] = place_showtime(world, "2026-08-14T12:00:00Z")
    world["key"] = issue_kdm(
        world["asset"]["id"],
        world["venue"]["id"],
        "2026-08-14T11:00:00Z",
        "2026-08-14T14:30:00Z",
    )
    world["showtime"] = read_showtime(world["showtime"]["id"])
    return world


class TestBoothTestReadsIngestStateBeforeKeyCoverage:
    """The package's ingest state is checked before any key is considered."""

    def test_booth_test_on_a_received_package_reports_the_dependency_failure(
        self, technical_manager_headers
    ):
        """A covering key is present, so only the ingest state can be at fault.

        PRD: "The referenced package must then be in `INGESTED`, or the test is refused with `ERR_DEPENDENCY_STATE_INVALID`; and at least one surviving `ISSUED` key must cover the screening under the rule just stated, or the test is refused with `ERR_NO_COVERING_KDM`."

        Design: Difficulty/cross_entity_state_dependency/verify_playback_reads_dcp_asset_ingest_state_ahead_of_key_coverage
        """
        world = _received_package_world()
        assert world["showtime"]["playback_status"] == "KEY_PENDING"

        response = api_client.verify_playback(
            world["showtime"]["id"], {"result": "PASS"}, technical_manager_headers
        )

        validate_error(response, ApiErrorId.ERR_DEPENDENCY_STATE_INVALID)
        assert read_asset(world["asset"]["id"])["status"] == "RECEIVED"
        assert read_showtime(world["showtime"]["id"])["playback_status"] == "KEY_PENDING"

    def test_identical_booth_test_passes_once_the_package_reaches_ingested(
        self, technical_manager_headers
    ):
        """Walking the print two steps further turns the same call into a pass.

        PRD: "Print traffic then advances one declared step at a time, each step supplied as a `new_status`, and the chain is strictly linear: `REQUESTED → IN_TRANSIT → RECEIVED → INGESTING → INGESTED → RETURNED`."

        Design: Difficulty/cross_entity_state_dependency/verify_playback_reads_dcp_asset_ingest_state_ahead_of_key_coverage
        """
        world = _received_package_world()
        validate_error(
            api_client.verify_playback(
                world["showtime"]["id"], {"result": "PASS"}, technical_manager_headers
            ),
            ApiErrorId.ERR_DEPENDENCY_STATE_INVALID,
        )

        advance_asset(world["asset"]["id"], "INGESTING")
        ingested = advance_asset(world["asset"]["id"], "INGESTED")

        verified = verify_booth_playback(world["showtime"]["id"], "PASS")

        assert ingested["status"] == "INGESTED"
        assert ingested["ingested_at"] is not None
        assert verified["playback_status"] == "PLAYBACK_VERIFIED"
        assert verified["status"] == "SCHEDULED"
        assert read_kdm(world["key"]["id"])["status"] == "ISSUED"
