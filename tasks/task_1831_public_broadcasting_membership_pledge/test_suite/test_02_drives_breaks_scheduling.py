"""Drive scheduling, on-air break programming, and temporal overlap rules."""
from test_helpers import (
    ApiErrorId,
    add_break,
    assert_break,
    create_break_payload,
    create_challenge,
    create_drive,
    create_level,
    create_pledge_payload,
    get_drive,
    go_live_drive,
    is_valid_uuid,
    schedule_drive,
    setup_donor_membership,
    setup_on_air_drive,
    setup_station,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestBreakOverlapBuffer:
    def test_break_overlap_with_buffer_semantics(
            self, api, station_admin_headers):
        """PRD §3.3: "The breaks of a single drive are half-open intervals
        `[starts_at, ends_at)` with a mandatory 5-minute buffer to any other
        break in the same drive: a break A starting at exactly break B's
        `ends_at` plus 5 minutes is allowed, but anything closer is rejected
        with `ERR_BREAK_OVERLAP` (422)."

        Design: Difficulty/resource_temporal_overlap/break_overlap_with_buffer_semantics
        """
        create_level()
        drive = create_drive()
        add_break(drive["id"], drive["version"],
                  starts_at="2026-08-02T18:00:00Z",
                  ends_at="2026-08-02T18:20:00Z")
        drive = get_drive(drive["id"])

        # 18:24 is only 4 minutes after the 18:20 end — inside the buffer.
        resp = api.create_break(
            drive["id"],
            create_break_payload(drive["version"],
                                 starts_at="2026-08-02T18:24:00Z",
                                 ends_at="2026-08-02T18:40:00Z",
                                 program_title="Late Pledge A"),
            station_admin_headers)
        validate_error(resp, ApiErrorId.ERR_BREAK_OVERLAP)

        # 18:25 is exactly ends_at plus 5 minutes — allowed.
        drive = get_drive(drive["id"])
        resp = api.create_break(
            drive["id"],
            create_break_payload(drive["version"],
                                 starts_at="2026-08-02T18:25:00Z",
                                 ends_at="2026-08-02T18:40:00Z",
                                 program_title="Late Pledge B"),
            station_admin_headers)
        brk = validate_success(resp, 201)
        assert is_valid_uuid(brk["id"]), "the exact-plus-5-minute break is accepted"
        assert_break(brk)

    def test_break_buffer_applies_before_existing_break(
            self, api, station_admin_headers):
        """PRD §3.3: "The breaks of a single drive are half-open intervals
        `[starts_at, ends_at)` with a mandatory 5-minute buffer to any other
        break in the same drive: a break A starting at exactly break B's
        `ends_at` plus 5 minutes is allowed, but anything closer is rejected
        with `ERR_BREAK_OVERLAP` (422)."

        Design: Difficulty/resource_temporal_overlap/break_overlap_with_buffer_semantics
        """
        create_level()
        drive = create_drive()
        add_break(drive["id"], drive["version"],
                  starts_at="2026-08-02T18:00:00Z",
                  ends_at="2026-08-02T18:20:00Z")
        drive = get_drive(drive["id"])

        # Ending at 17:56 leaves only 4 minutes before the 18:00 start.
        resp = api.create_break(
            drive["id"],
            create_break_payload(drive["version"],
                                 starts_at="2026-08-02T17:35:00Z",
                                 ends_at="2026-08-02T17:56:00Z",
                                 program_title="Early Pledge Too Close"),
            station_admin_headers)
        validate_error(resp, ApiErrorId.ERR_BREAK_OVERLAP)

        # Ending at 17:55 leaves exactly the 5-minute buffer — allowed.
        drive = get_drive(drive["id"])
        resp = api.create_break(
            drive["id"],
            create_break_payload(drive["version"],
                                 starts_at="2026-08-02T17:35:00Z",
                                 ends_at="2026-08-02T17:55:00Z",
                                 program_title="Early Pledge"),
            station_admin_headers)
        brk = validate_success(resp, 201)
        assert is_valid_uuid(brk["id"])


class TestDriveOverlap:
    def test_drive_overlap_half_open_no_buffer(
            self, api, station_admin_headers):
        """PRD §3.3: "At schedule time the server checks that no other drive in
        `SCHEDULED` or `ON_AIR` status overlaps the half-open `[starts_at,
        ends_at)` window; a drive ending exactly when another starts is
        allowed, but any real overlap is rejected with `ERR_DRIVE_OVERLAP`
        (422)."

        Design: Difficulty/resource_temporal_overlap/drive_overlap_half_open_no_buffer
        """
        create_level()
        drive_a = create_drive(name="Fall 2026 A")
        add_break(drive_a["id"], drive_a["version"])
        schedule_drive(drive_a["id"])

        drive_b = create_drive(name="Fall 2026 B",
                               starts_at="2026-08-14T00:00:00Z",
                               ends_at="2026-08-30T00:00:00Z")
        add_break(drive_b["id"], drive_b["version"],
                  starts_at="2026-08-16T18:00:00Z",
                  ends_at="2026-08-16T18:20:00Z",
                  program_title="Evening Pledge B")

        drive_c = create_drive(name="Fall 2026 C",
                               starts_at="2026-08-15T00:00:00Z",
                               ends_at="2026-08-30T00:00:00Z")
        add_break(drive_c["id"], drive_c["version"],
                  starts_at="2026-08-16T18:00:00Z",
                  ends_at="2026-08-16T18:20:00Z",
                  program_title="Evening Pledge C")

        # B overlaps A's [08-01, 08-15) window by a full day — rejected.
        resp = api.schedule_drive(drive_b["id"], station_admin_headers)
        validate_error(resp, ApiErrorId.ERR_DRIVE_OVERLAP)

        # C starts exactly when A ends — half-open, allowed.
        resp = api.schedule_drive(drive_c["id"], station_admin_headers)
        scheduled = validate_success(resp, 200)
        assert scheduled["status"] == "SCHEDULED"

    def test_drive_overlap_check_also_covers_on_air_drive(
            self, api, station_admin_headers):
        """PRD §3.3: "At schedule time the server checks that no other drive in
        `SCHEDULED` or `ON_AIR` status overlaps the half-open `[starts_at,
        ends_at)` window; a drive ending exactly when another starts is
        allowed, but any real overlap is rejected with `ERR_DRIVE_OVERLAP`
        (422)."

        Design: Difficulty/resource_temporal_overlap/drive_overlap_half_open_no_buffer
        """
        create_level()
        drive_a = setup_on_air_drive(name="Fall 2026 Live")
        assert drive_a["status"] == "ON_AIR"

        drive_b = create_drive(name="Fall 2026 Overlapper",
                               starts_at="2026-08-10T00:00:00Z",
                               ends_at="2026-08-30T00:00:00Z")
        add_break(drive_b["id"], drive_b["version"],
                  starts_at="2026-08-16T18:00:00Z",
                  ends_at="2026-08-16T18:20:00Z")

        resp = api.schedule_drive(drive_b["id"], station_admin_headers)
        validate_error(resp, ApiErrorId.ERR_DRIVE_OVERLAP)
        drive_b_after = get_drive(drive_b["id"])
        assert drive_b_after["status"] == "DRAFT", (
            "the rejected schedule leaves the drive in DRAFT")


class TestBreakCreationFrozenLineup:
    def test_break_create_on_live_drive_with_overlap_state_beats_temporal(
            self, api, station_admin_headers):
        """PRD §3.3: "Breaks are scheduled against a drive that is in `DRAFT`
        or `SCHEDULED` status; once the drive is `ON_AIR`, `CLOSED`, or
        `RECONCILED` the break lineup is frozen and break creation is rejected
        with `ERR_INVALID_STATE`."
        PRD §2.9: "When multiple validations could fire on the same request,
        they are evaluated in a strict priority order so that the surfaced
        error is deterministic."

        Design: Difficulty/priority_pair_validation_conflict/break_create_on_live_drive_with_overlap_state_beats_temporal
        """
        create_level()
        drive = setup_on_air_drive()
        assert drive["status"] == "ON_AIR"

        # 18:22 would also violate the existing 18:00-18:20 break's 5-minute
        # buffer, but the frozen-lineup state check fires first.
        resp = api.create_break(
            drive["id"],
            create_break_payload(drive["version"],
                                 starts_at="2026-08-02T18:22:00Z",
                                 ends_at="2026-08-02T18:40:00Z",
                                 program_title="Late Pledge"),
            station_admin_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        drive_after = get_drive(drive["id"])
        assert drive_after["version"] == drive["version"], (
            "the rejected break creation does not mutate the drive")
        breaks, _meta = validate_paginated(
            api.list_breaks(drive["id"], station_admin_headers))
        assert len(breaks) == 1, "no new break is persisted"

    def test_break_create_on_closed_drive_rejected_invalid_state(
            self, api, station_admin_headers):
        """PRD §3.3: "Breaks are scheduled against a drive that is in `DRAFT`
        or `SCHEDULED` status; once the drive is `ON_AIR`, `CLOSED`, or
        `RECONCILED` the break lineup is frozen and break creation is rejected
        with `ERR_INVALID_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/break_create_on_live_drive_with_overlap_state_beats_temporal
        """
        create_level()
        drive = setup_on_air_drive()
        resp = api.close_drive(drive["id"], station_admin_headers)
        closed = validate_success(resp, 200)
        assert closed["status"] == "CLOSED"

        # A perfectly legal, non-overlapping slot is still rejected: the
        # lineup is frozen once the drive leaves DRAFT/SCHEDULED.
        drive = get_drive(drive["id"])
        resp = api.create_break(
            drive["id"],
            create_break_payload(drive["version"],
                                 starts_at="2026-08-03T19:00:00Z",
                                 ends_at="2026-08-03T19:20:00Z",
                                 program_title="Post-Close Pledge"),
            station_admin_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestPledgeCaptureRequiresOnAir:
    def test_pledge_capture_depends_on_drive_on_air_scheduled(
            self, api, phone_volunteer_headers):
        """PRD §2.9: "Target resource state permits the operation (generic) →
        `ERR_INVALID_STATE` (409). Pledge capture against a drive not `ON_AIR`
        is the one exception and yields the more specific `ERR_DRIVE_NOT_OPEN`
        (409)."
        PRD §3.3: "From this point pledge capture endpoints accept pledges for
        the drive."

        Design: Difficulty/cross_entity_state_dependency/pledge_capture_depends_on_drive_on_air
        """
        create_level()
        donor, membership = setup_donor_membership()
        drive = create_drive()
        add_break(drive["id"], drive["version"])
        schedule_drive(drive["id"])
        drive = get_drive(drive["id"])
        assert drive["status"] == "SCHEDULED"

        resp = api.create_pledge(
            create_pledge_payload(donor["id"], membership["id"], drive["id"],
                                  channel="PHONE", kind="ONE_TIME",
                                  amount_cents=6000),
            phone_volunteer_headers)
        validate_error(resp, ApiErrorId.ERR_DRIVE_NOT_OPEN)

    def test_pledge_capture_depends_on_drive_on_air_closed(
            self, api, phone_volunteer_headers, station_admin_headers):
        """PRD §3.3: "Closing the drive moves it `ON_AIR` → `CLOSED`, at which
        point three cascades fire: further pledge capture is rejected with
        `ERR_DRIVE_NOT_OPEN`; every `OnAirBreak` still in `SCHEDULED`
        transitions to `AIRED`; and every `MatchingChallenge` still in `OPEN`
        transitions to `EXPIRED` with its progress frozen."

        Design: Difficulty/cross_entity_state_dependency/pledge_capture_depends_on_drive_on_air
        """
        station = setup_station()
        resp = api.close_drive(station["drive"]["id"], station_admin_headers)
        assert validate_success(resp, 200)["status"] == "CLOSED"

        resp = api.create_pledge(
            create_pledge_payload(station["donor"]["id"],
                                  station["membership"]["id"],
                                  station["drive"]["id"],
                                  channel="WEB", kind="ONE_TIME",
                                  amount_cents=6000),
            phone_volunteer_headers)
        validate_error(resp, ApiErrorId.ERR_DRIVE_NOT_OPEN)


class TestBreakRequestShape:
    def test_error_invalid_request_break_end_before_start(
            self, api, station_admin_headers):
        """PRD §2.9: "Request body well-formedness (missing fields, wrong
        types, malformed enums, `ends_at` not strictly after `starts_at`) →
        `ERR_INVALID_REQUEST` (400)."

        Design: Corner/errors/error_invalid_request_break_end_before_start
        """
        create_level()
        drive = create_drive()
        resp = api.create_break(
            drive["id"],
            create_break_payload(drive["version"],
                                 starts_at="2026-08-02T18:20:00Z",
                                 ends_at="2026-08-02T18:00:00Z",
                                 program_title="Backwards"),
            station_admin_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestDriveOccAndCloseCascade:
    def test_occ_stale_drive_version_on_break_create(
            self, api, station_admin_headers):
        """PRD §2.7: "Break scheduling against a drive requires
        `expected_drive_version` carrying the client's last observed `version`
        of the target `PledgeDrive`. A mismatch is rejected with
        `ERR_STALE_DRIVE_VERSION` (HTTP 412)."
        PRD §3.3: "Break creation also requires `expected_drive_version`
        matching the drive's current `version`, per §2.7; on success the
        drive's `version` increments."

        Design: Corner/cross_cutting_layers/occ_stale_drive_version_on_break_create
        """
        create_level()
        drive = create_drive()
        stale_version = drive["version"]
        add_break(drive["id"], stale_version,
                  starts_at="2026-08-02T18:00:00Z",
                  ends_at="2026-08-02T18:20:00Z")

        # The first break bumped the drive version, so the captured one is stale.
        resp = api.create_break(
            drive["id"],
            create_break_payload(stale_version,
                                 starts_at="2026-08-02T19:00:00Z",
                                 ends_at="2026-08-02T19:20:00Z",
                                 program_title="Night Pledge"),
            station_admin_headers)
        validate_error(resp, ApiErrorId.ERR_STALE_DRIVE_VERSION)

        breaks, meta = validate_paginated(
            api.list_breaks(drive["id"], station_admin_headers))
        assert len(breaks) == 1, "no second break is persisted"
        drive_after = get_drive(drive["id"])
        assert drive_after["version"] == stale_version + 1, (
            "the rejected break does not advance the drive version")

    def test_drive_close_cascades_breaks_aired_and_challenges_expired(
            self, api, station_admin_headers):
        """PRD §3.3: "Closing the drive moves it `ON_AIR` → `CLOSED`, at which
        point three cascades fire: further pledge capture is rejected with
        `ERR_DRIVE_NOT_OPEN`; every `OnAirBreak` still in `SCHEDULED`
        transitions to `AIRED`; and every `MatchingChallenge` still in `OPEN`
        transitions to `EXPIRED` with its progress frozen."

        Design: Corner/state_machines/drive_close_cascades_breaks_aired_and_challenges_expired
        """
        create_level()
        drive = create_drive()
        brk = add_break(drive["id"], drive["version"])
        challenge = create_challenge(drive["id"], sponsor_name="Acme",
                                     goal_cents=999999, match_cents=1000)
        schedule_drive(drive["id"])
        go_live_drive(drive["id"])

        resp = api.close_drive(drive["id"], station_admin_headers)
        closed = validate_success(resp, 200)
        assert closed["status"] == "CLOSED"

        breaks, _meta = validate_paginated(
            api.list_breaks(drive["id"], station_admin_headers))
        assert len(breaks) == 1
        assert breaks[0]["id"] == brk["id"]
        assert breaks[0]["status"] == "AIRED", "break cascades to AIRED"

        challenge_after = validate_success(
            api.get_matching_challenge(challenge["id"], station_admin_headers))
        assert challenge_after["status"] == "EXPIRED", (
            "open challenge cascades to EXPIRED with progress frozen")
