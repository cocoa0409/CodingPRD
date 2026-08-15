"""Season posture gates, terminal lockdown, and optimistic concurrency control."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    activate_member,
    advance_posture,
    book_audition,
    create_concert,
    create_member,
    create_member_payload,
    create_open_season_with_section,
    create_rehearsal_payload,
    create_season,
    create_section,
    get_success_data,
    validate_error,
    validate_success,
)


class TestOccSeasonConfig:
    def test_occ_season_patch_stale_version_returns_412(self, api,
                                                        president_headers):
        """PRD §2.7: "Updating a Season's configuration requires
        `expected_season_version`, carrying the caller's last observed
        `version` of that Season. If the Season's current `version` has
        advanced since the caller read it — another writer may have
        legitimately changed dues policy or checkpointed the season in between
        — the update is rejected with `ERR_STALE_VERSION` (HTTP 412) and the
        caller must re-read before writing."
        PRD §3.1: "each successful update increments the Season's `version` by
        one."

        Design: Corner/cross_cutting_layers/occ_season_patch_stale_version_returns_412
        """
        season = create_season()
        observed_version = season["version"]

        updated = validate_success(api.patch_season(
            season["id"],
            {"expected_season_version": observed_version,
             "late_fee_weekly_cents": 600},
            president_headers))
        assert updated["version"] == observed_version + 1
        assert updated["late_fee_weekly_cents"] == 600

        # Replaying the stale observed version is rejected and does not land.
        resp = api.patch_season(
            season["id"],
            {"expected_season_version": observed_version,
             "late_fee_weekly_cents": 700},
            president_headers)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        current = validate_success(api.get_season(season["id"], president_headers))
        assert current["late_fee_weekly_cents"] == 600, \
            "stale write must not land"
        assert current["version"] == observed_version + 1


class TestOccCheckpoint:
    def test_occ_checkpoint_stale_version_returns_412(self, api,
                                                      president_headers):
        """PRD §2.7: "Running the ops checkpoint likewise requires
        `expected_season_version`. Each successful checkpoint legitimately
        advances `ops_week_index` and the Season's `version`, so a request
        carrying an older observed `version` is rejected with
        `ERR_STALE_VERSION` (HTTP 412) rather than double-applying epoch side
        effects."

        Design: Corner/cross_cutting_layers/occ_checkpoint_stale_version_returns_412
        """
        season = create_season()
        season = advance_posture(season["id"], "OPEN")
        observed_version = season["version"]
        assert season["ops_week_index"] == 0

        first = validate_success(api.checkpoint_season(
            season["id"], observed_version, president_headers))
        assert first["ops_week_index"] == 1
        assert first["version"] == observed_version + 1

        resp = api.checkpoint_season(season["id"], observed_version,
                                     president_headers)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        current = validate_success(api.get_season(season["id"], president_headers))
        assert current["ops_week_index"] == 1, \
            "stale checkpoint must not double-apply the epoch"


class TestOccGuestContractCounter:
    def test_occ_guest_counter_stale_version_returns_412(self, api,
                                                         director_headers,
                                                         president_headers):
        """PRD §2.7: "Recording a counter-offer on a guest contract requires
        `expected_guest_contract_version`. A counter-offer legitimately
        supersedes the terms of the current offer, so when the GuestContract's
        `version` has advanced beyond the value the caller observed, the
        counter is rejected with `ERR_STALE_VERSION` (HTTP 412) rather than
        silently overwriting newer terms."

        Design: Corner/cross_cutting_layers/occ_guest_counter_stale_version_returns_412
        """
        season = create_season()
        advance_posture(season["id"], "OPEN")
        contract = get_success_data(api.create_contract(
            {"season_id": season["id"], "musician_name": "Cellist",
             "service_lines": [{"kind": "CONCERT", "units": 1,
                                "rate_cents": 30000}],
             "travel_stipend_cents": 0},
            director_headers))
        offered = get_success_data(
            api.offer_contract(contract["id"], {}, director_headers))
        observed_version = offered["version"]

        countered = validate_success(api.counter_contract(
            contract["id"],
            {"expected_guest_contract_version": observed_version,
             "service_lines": [{"kind": "CONCERT", "units": 1,
                                "rate_cents": 28000}]},
            director_headers))
        assert countered["status"] == "COUNTERED"
        assert countered["quoted_fee_cents"] == 28000
        assert countered["counter_count"] == 1

        # Replaying the same observed version fails; newer terms survive.
        resp = api.counter_contract(
            contract["id"],
            {"expected_guest_contract_version": observed_version,
             "service_lines": [{"kind": "CONCERT", "units": 1,
                                "rate_cents": 25000}]},
            director_headers)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        current = validate_success(
            api.get_contract(contract["id"], director_headers))
        assert current["quoted_fee_cents"] == 28000
        assert current["counter_count"] == 1


class TestSeasonPostureGates:
    def test_rehearsal_create_in_open_posture_rejected(self, api,
                                                       director_headers):
        """PRD §2.9: "Rehearsal and attendance writes require `REHEARSING` or
        later. ... A season-scoped write that the current posture does not
        permit is rejected with `ERR_SEASON_POSTURE`."

        Design: Corner/state_machines/rehearsal_create_in_open_posture_rejected
        """
        season = create_season()
        advance_posture(season["id"], "OPEN")
        resp = api.create_rehearsal(
            create_rehearsal_payload(season["id"], "2026-08-05T19:00:00Z"),
            director_headers,
        )
        validate_error(resp, ApiErrorId.ERR_SEASON_POSTURE)

    def test_rehearsing_gate_unbalanced_section_rejected(self, api,
                                                         president_headers):
        """PRD §3.1: "Moving from `OPEN` to `REHEARSING` is gated on the
        voice-part balance: every Section of the season whose `status` is
        `OPEN` must satisfy the balance gate — its `active_count` must be at
        least `target_min` and at most `target_max` — or the advance is
        rejected with `ERR_SECTION_UNBALANCED`"

        Design: Corner/state_machines/rehearsing_gate_unbalanced_section_rejected
        """
        season = create_season()
        create_section(season["id"], "SOPRANO", 1, 2)
        advance_posture(season["id"], "OPEN")
        resp = api.set_season_posture(season["id"], "REHEARSING",
                                      president_headers)
        validate_error(resp, ApiErrorId.ERR_SECTION_UNBALANCED)

        current = validate_success(api.get_season(season["id"], president_headers))
        assert current["posture"] == "OPEN", "failed gate leaves posture OPEN"

    def test_rehearsing_gate_pending_audition_rejected(self, api,
                                                       president_headers):
        """PRD §3.1: "separately, if any audition of the season is still
        `SCHEDULED`, the advance is rejected with `ERR_AUDITIONS_PENDING`."

        Design: Corner/state_machines/rehearsing_gate_pending_audition_rejected
        """
        season, section = create_open_season_with_section(target_max=3)
        # One ACTIVE member satisfies the balance gate (min 1, max 3).
        activate_member(season["id"], section["id"])
        # A second applicant has an audition still SCHEDULED.
        m2 = create_member(season["id"], "Ben", "ben@x.org")
        book_audition(m2["id"], "2026-08-02T11:00:00Z")

        resp = api.set_season_posture(season["id"], "REHEARSING",
                                      president_headers)
        validate_error(resp, ApiErrorId.ERR_AUDITIONS_PENDING)

        current = validate_success(api.get_season(season["id"], president_headers))
        assert current["posture"] == "OPEN", "failed gate leaves posture OPEN"

    def test_archive_blocked_by_open_concerts(self, api, president_headers):
        """PRD §3.1: "From `REHEARSING` the season moves to `CONCERT_LOCK`
        without preconditions, and from `CONCERT_LOCK` to `ARCHIVED` only when
        every concert of the season has reached `PERFORMED` or `CANCELLED` —
        otherwise `ERR_CONCERTS_OPEN`."

        Design: Corner/state_machines/archive_blocked_by_open_concerts
        """
        season, section = create_open_season_with_section()
        activate_member(season["id"], section["id"])
        advance_posture(season["id"], "REHEARSING")
        create_concert(season["id"])
        advance_posture(season["id"], "CONCERT_LOCK")

        resp = api.set_season_posture(season["id"], "ARCHIVED",
                                      president_headers)
        validate_error(resp, ApiErrorId.ERR_CONCERTS_OPEN)

        current = validate_success(api.get_season(season["id"], president_headers))
        assert current["posture"] == "CONCERT_LOCK"

    def test_season_archived_write_rejected(self, api, director_headers,
                                            president_headers):
        """PRD §2.9: "Once a season reaches `ARCHIVED`, every write against it
        is rejected with `ERR_SEASON_TERMINAL`."
        PRD §3.1: "From `DRAFT`, the season may move to `OPEN` unconditionally,
        or directly to `ARCHIVED`."

        Design: Corner/state_machines/season_archived_write_rejected
        """
        season = create_season()
        advance_posture(season["id"], "ARCHIVED")
        resp = api.create_member(
            create_member_payload(season["id"], "Ada", "ada@x.org"),
            director_headers,
        )
        validate_error(resp, ApiErrorId.ERR_SEASON_TERMINAL)


class TestExistenceBeforePosture:
    def test_not_found_beats_posture_gate(self, api, director_headers):
        """PRD §2.8: "Fourth, existence: resource ids appearing in the path and
        in the body are validated left to right, and the first id that does not
        resolve to an existing resource yields `ERR_NOT_FOUND`." and "A failure
        in an earlier tier masks every later check, so a caller always sees the
        highest-priority applicable error." — existence (tier four) precedes
        season posture gating (tier seven).

        Design: Corner/validations/not_found_beats_posture_gate
        """
        create_season()  # stays DRAFT: posture would also block
        resp = api.create_audition(
            {"member_id": NON_EXISTENT_UUID,
             "scheduled_at": "2026-08-02T10:00:00Z"},
            director_headers,
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
