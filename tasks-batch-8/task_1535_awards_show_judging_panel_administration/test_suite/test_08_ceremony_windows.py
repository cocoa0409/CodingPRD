"""Ceremony interval geometry, scoring-round window gaps, and the rehearsal
season gate (PRD §3.6, §3.7).
"""
from test_helpers import (
    ApiErrorId,
    assert_ceremony,
    create_ceremony_payload,
    create_round_payload,
    validate_error,
    validate_success,
)
from test_helpers import fixtures as fx
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["program_admin_headers"]


class TestCeremonyOverlap:
    def _setup_season_with_first_ceremony(self, api, code: str):
        season = fx.create_season(code)
        category = fx.create_published_category(season["id"], code="CAT_OVL")
        first = fx.get_success_data(
            api.create_ceremony(
                season["id"],
                create_ceremony_payload(
                    venue_name="Hall A",
                    starts_at="2026-10-01T19:00:00Z",
                    ends_at="2026-10-01T21:00:00Z",
                    rundown=[
                        {
                            "segment_no": 1,
                            "category_id": category["id"],
                            "duration_seconds": 600,
                        }
                    ],
                ),
                ADMIN,
            )
        )
        return season, category, first

    def test_adjacent_ceremony_permitted(self, api):
        """PRD §3.7: "Within one season, the half-open intervals from
        `starts_at` to `ends_at` of non-terminal ceremonies must never overlap;
        two ceremonies that merely touch — one ending exactly when the other
        begins — are permitted"

        Design: Difficulty/resource_temporal_overlap/ceremony_half_open_overlap_adjacency
        """
        season, category, _ = self._setup_season_with_first_ceremony(api, "GALA-OVL")
        resp = api.create_ceremony(
            season["id"],
            create_ceremony_payload(
                venue_name="Hall B",
                starts_at="2026-10-01T21:00:00Z",  # exactly the first ceremony's end
                ends_at="2026-10-01T23:00:00Z",
                rundown=[
                    {
                        "segment_no": 1,
                        "category_id": category["id"],
                        "duration_seconds": 300,
                    }
                ],
            ),
            ADMIN,
        )
        ceremony = validate_success(resp, expected_status=201)
        assert_ceremony(ceremony)
        assert ceremony["status"] == "PLANNING"

    def test_overlapping_ceremony_rejected(self, api):
        """PRD §3.7: "Within one season, the half-open intervals from
        `starts_at` to `ends_at` of non-terminal ceremonies must never overlap;
        two ceremonies that merely touch — one ending exactly when the other
        begins — are permitted, and an overlap is rejected with
        `ERR_CEREMONY_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/ceremony_half_open_overlap_adjacency
        """
        season, category, _ = self._setup_season_with_first_ceremony(api, "GALA-OVL2")
        resp = api.create_ceremony(
            season["id"],
            create_ceremony_payload(
                venue_name="Hall C",
                starts_at="2026-10-01T20:59:59Z",  # one second before the first ends
                ends_at="2026-10-01T23:00:00Z",
                rundown=[
                    {
                        "segment_no": 1,
                        "category_id": category["id"],
                        "duration_seconds": 300,
                    }
                ],
            ),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_CEREMONY_OVERLAP)


class TestRoundWindowGap:
    def _setup_category_with_round_one(self, api, code: str):
        season = fx.create_season(code)
        category = fx.create_published_category(season["id"], code="CAT_GAP")
        round_one = fx.get_success_data(
            api.create_round(
                category["id"],
                create_round_payload(
                    round_index=1,
                    scheduled_window_start="2026-09-05T00:00:00Z",
                    scheduled_window_end="2026-09-07T00:00:00Z",
                ),
                ADMIN,
            )
        )
        return season, category, round_one

    def test_round_window_exactly_twelve_hour_gap_accepted(self, api):
        """PRD §3.6: "any two non-`VOIDED` rounds' windows must be separated by
        a closed buffer of at least twelve hours: the gap between the earlier
        window's end and the later window's start must be twelve hours or more,
        mere non-overlap being insufficient, and a violation is
        `ERR_ROUND_WINDOW_TOO_CLOSE`."

        Design: Difficulty/resource_temporal_overlap/scoring_round_window_gap_buffer
        """
        _, category, _ = self._setup_category_with_round_one(api, "GALA-GAP")
        resp = api.create_round(
            category["id"],
            create_round_payload(
                round_index=2,
                scheduled_window_start="2026-09-07T12:00:00Z",  # exactly +12h
                scheduled_window_end="2026-09-09T00:00:00Z",
            ),
            ADMIN,
        )
        round_two = validate_success(resp, expected_status=201)
        assert round_two["status"] == "CONFIGURING"
        assert round_two["round_index"] == 2

    def test_round_window_under_twelve_hour_gap_rejected(self, api):
        """PRD §3.6: "any two non-`VOIDED` rounds' windows must be separated by
        a closed buffer of at least twelve hours: the gap between the earlier
        window's end and the later window's start must be twelve hours or more,
        mere non-overlap being insufficient, and a violation is
        `ERR_ROUND_WINDOW_TOO_CLOSE`."

        Design: Difficulty/resource_temporal_overlap/scoring_round_window_gap_buffer
        """
        _, category, _ = self._setup_category_with_round_one(api, "GALA-GAP2")
        ok = api.create_round(
            category["id"],
            create_round_payload(
                round_index=2,
                scheduled_window_start="2026-09-07T12:00:00Z",
                scheduled_window_end="2026-09-09T00:00:00Z",
            ),
            ADMIN,
        )
        validate_success(ok, expected_status=201)
        resp = api.create_round(
            category["id"],
            create_round_payload(
                round_index=3,
                scheduled_window_start="2026-09-09T11:59:00Z",  # 11h59m after round 2
                scheduled_window_end="2026-09-11T00:00:00Z",
            ),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_ROUND_WINDOW_TOO_CLOSE)


class TestRehearsalSeasonGate:
    def test_rehearse_rejected_before_embargo(self, api):
        """PRD §3.7: "A ceremony begins in `PLANNING` and advances to
        `REHEARSAL` only while the season is `EMBARGOED` and only when its
        rundown covers every `PUBLISHED` category exactly once"
        PRD §3.8: "any action whose source state does not permit the transition
        is refused with `ERR_INVALID_STATE`."

        Design: Difficulty/cross_entity_state_dependency/ceremony_rehearse_requires_season_embargoed
        """
        bundle = fx.setup_finalists_locked(
            num_entries=1, finalist_slots=1, code="GALA-X2"
        )
        record = bundle["finalist_records"][bundle["entries"][0]["id"]]
        fx.get_success_data(api.notify_finalist(record["id"], ADMIN))
        ceremony = fx.create_ceremony_for_season(
            bundle["season"]["id"], [bundle["category"]["id"]], venue="Hall X"
        )
        resp = api.rehearse_ceremony(ceremony["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        fetched = validate_success(api.get_ceremony(ceremony["id"], ADMIN))
        assert fetched["status"] == "PLANNING"

    def test_rehearse_succeeds_after_embargo(self, api):
        """PRD §3.7: "A ceremony begins in `PLANNING` and advances to
        `REHEARSAL` only while the season is `EMBARGOED` and only when its
        rundown covers every `PUBLISHED` category exactly once"

        Design: Difficulty/cross_entity_state_dependency/ceremony_rehearse_requires_season_embargoed
        """
        bundle = fx.setup_embargoed_season(
            num_entries=1, finalist_slots=1, code="GALA-X2B"
        )
        ceremony = fx.create_ceremony_for_season(
            bundle["season"]["id"], [bundle["category"]["id"]], venue="Hall X"
        )
        rehearsed = validate_success(api.rehearse_ceremony(ceremony["id"], ADMIN))
        assert rehearsed["status"] == "REHEARSAL"
