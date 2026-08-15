"""Blackout window creation rules, interval merge, and OCC-guarded extension."""
from test_helpers import (
    ApiErrorId,
    api_client,
    as_officer,
    assert_same_instant,
    create_event_window,
    create_officer,
    create_quarterly_window,
    get_success_data,
    set_logical_clock,
    validate_error,
    validate_success,
)


class TestWindowCreationRules:
    def test_window_end_not_after_start_rejected(self, api):
        """PRD §3.2: "an `end_at` that is not strictly later than `start_at` is
        rejected with `ERR_DATE_RANGE_INVALID` (422)".

        Design: Corner/validations/window_end_before_start_returns_date_error
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        officer = create_officer("officer_v2@x.com")
        resp = api.create_blackout_window(
            {
                "kind": "QUARTERLY",
                "fiscal_year": 2026,
                "fiscal_quarter": "Q4",
                "start_at": "2026-10-01T00:00:00Z",
                "end_at": "2026-10-01T00:00:00Z",
            },
            as_officer(officer),
        )
        validate_error(resp, ApiErrorId.ERR_DATE_RANGE_INVALID)

    def test_adjacent_quarterly_window_accepted(self, api):
        """PRD §3.2: "Adjacency is not overlap: a new quarterly window whose
        `start_at` equals an existing window's `end_at` is accepted."

        Design: Difficulty/resource_temporal_overlap/quarterly_window_half_open_adjacency
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        officer = create_officer("officer14@x.com")
        create_quarterly_window(
            officer, "2026-07-01T00:00:00Z", "2026-09-30T00:00:00Z",
            fiscal_year=2026, fiscal_quarter="Q3",
        )
        resp = api.create_blackout_window(
            {
                "kind": "QUARTERLY",
                "fiscal_year": 2026,
                "fiscal_quarter": "Q4",
                "start_at": "2026-09-30T00:00:00Z",
                "end_at": "2026-12-31T00:00:00Z",
            },
            as_officer(officer),
        )
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "SCHEDULED"

    def test_overlapping_quarterly_window_rejected(self, api):
        """PRD §3.2: "If the half-open interval of a new `QUARTERLY` window overlaps
        the half-open interval of an existing `SCHEDULED` or `ACTIVE` `QUARTERLY`
        window, creation is rejected with `ERR_DUPLICATE_QUARTER_WINDOW` (409)."

        Design: Difficulty/resource_temporal_overlap/quarterly_window_half_open_adjacency
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        officer = create_officer("officer14b@x.com")
        create_quarterly_window(
            officer, "2026-07-01T00:00:00Z", "2026-09-30T00:00:00Z",
            fiscal_year=2026, fiscal_quarter="Q3",
        )
        resp = api.create_blackout_window(
            {
                "kind": "QUARTERLY",
                "fiscal_year": 2026,
                "fiscal_quarter": "Q4",
                "start_at": "2026-09-29T00:00:00Z",
                "end_at": "2026-12-01T00:00:00Z",
            },
            as_officer(officer),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_QUARTER_WINDOW)


class TestEventWindowMerge:
    def test_touching_event_windows_merge(self, api):
        """PRD §3.2: "When a new `EVENT_DRIVEN` window for a ticker overlaps or touches
        an existing `SCHEDULED` or `ACTIVE` `EVENT_DRIVEN` window on the same ticker —
        where touching means the candidate's `start_at` equals the survivor's `end_at`
        or vice versa — the candidate is absorbed. The surviving window's `start_at`
        becomes the earlier of the two starts, its `end_at` becomes the later of the
        two ends, and its `version` increments. The candidate record is still created,
        but is immediately set to `MERGED` with its `merged_into_id` pointing at the
        survivor."

        Design: Corner/calculations/event_window_merge_absorbs_touching_window
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        officer = create_officer("officer_c4@x.com")
        w1 = create_event_window(officer, "ZETA", "2026-08-10T00:00:00Z",
                                 "2026-08-12T00:00:00Z")
        w2 = create_event_window(officer, "ZETA", "2026-08-12T00:00:00Z",
                                 "2026-08-15T00:00:00Z")
        assert w2["status"] == "MERGED"
        assert w2["merged_into_id"] == w1["id"]

        survivor = get_success_data(api.get_blackout_window(w1["id"], as_officer(officer)))
        assert_same_instant(survivor["start_at"], "2026-08-10T00:00:00Z", "survivor start_at")
        assert_same_instant(survivor["end_at"], "2026-08-15T00:00:00Z", "survivor end_at")


class TestWindowExtendOcc:
    def test_window_extend_with_stale_version_rejected(self, api):
        """PRD §2.7: "A request to `POST /blackout-windows/{id}/extend` must carry
        `expected_blackout_window_version` holding the `version` of the window the
        client last observed. An earlier extension already moved the window's end and
        incremented its version, so an extension carrying the previously observed
        version is stale — even though the window remains extendable — and is rejected
        with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/window_extend_stale_version_returns_412
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        officer = create_officer("officer_x3@x.com")
        win = create_quarterly_window(
            officer, "2026-08-10T00:00:00Z", "2026-08-20T00:00:00Z",
            fiscal_year=2026, fiscal_quarter="Q3",
        )
        resp = api.extend_blackout_window(
            win["id"],
            {
                "new_end_at": "2026-08-25T00:00:00Z",
                "expected_blackout_window_version": win["version"] - 1,
            },
            as_officer(officer),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        fresh = get_success_data(api.get_blackout_window(win["id"], as_officer(officer)))
        assert_same_instant(fresh["end_at"], "2026-08-20T00:00:00Z", "end_at unchanged")

    def test_window_extend_with_fresh_version_succeeds(self, api):
        """PRD §3.2: "a successful extension moves `end_at` to `new_end_at` and
        increments the window's `version`."

        Design: Corner/cross_cutting_layers/window_extend_success_with_fresh_version
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        officer = create_officer("officer_x4@x.com")
        win = create_quarterly_window(
            officer, "2026-08-10T00:00:00Z", "2026-08-20T00:00:00Z",
            fiscal_year=2026, fiscal_quarter="Q3",
        )
        data = validate_success(
            api.extend_blackout_window(
                win["id"],
                {
                    "new_end_at": "2026-08-25T00:00:00Z",
                    "expected_blackout_window_version": win["version"],
                },
                as_officer(officer),
            )
        )
        assert_same_instant(data["end_at"], "2026-08-25T00:00:00Z", "extended end_at")
        assert data["version"] == win["version"] + 1
