"""Rate-table publication overlap semantics — half-open effectiveness windows
(PRD §3.2)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_rate_table,
    create_carrier,
    create_rate_row,
    publish_rate,
    validate_error,
    validate_success,
)

UW = TEST_USERS["underwriter_headers"]


class TestRateTableHalfOpenOverlap:
    def test_adjacent_rate_windows_do_not_overlap(self, api):
        """PRD §3.2: "Every row carries `rate_per_100_cents_of_liability` and an
        effectiveness window: `effective_from` is inclusive, `effective_to` is
        exclusive, and a null `effective_to` leaves the row open-ended."
        PRD §3.2: "Publishing a row moves it to `PUBLISHED`, but only when no
        other `PUBLISHED` row exists with the same `rating_kind` and the same
        county-and-crop pair (crop-hail) — or the same `rating_kind`, species,
        and an overlapping value band (livestock) — whose effectiveness window
        overlaps the candidate's window; an overlap is rejected with
        `ERR_RATE_TABLE_OVERLAP` (HTTP 409)."
        R1 covers [2026-01-01, 2026-08-01); R2 starts at 2026-08-01 — the
        half-open boundary means the two windows share no instant, so R2
        publishes cleanly.

        Design: Difficulty/resource_temporal_overlap/rate_table_half_open_interval_overlap_rejected
        """
        carrier = create_carrier(carrier_code="CHL-O")
        cid = carrier["id"]
        r1 = create_rate_row(
            cid, "CROP_HAIL", rate_per_100_cents_of_liability=333,
            effective_from="2026-01-01T00:00:00Z",
            effective_to="2026-08-01T00:00:00Z",
        )
        publish_rate(cid, r1["id"])

        r2 = create_rate_row(
            cid, "CROP_HAIL", rate_per_100_cents_of_liability=400,
            effective_from="2026-08-01T00:00:00Z",
        )
        res = api.publish_rate_table(cid, r2["id"], UW)
        published = validate_success(res, 200)
        assert_rate_table(published)
        assert published["status"] == "PUBLISHED", (
            "adjacent half-open windows must publish without overlap"
        )

    def test_overlapping_rate_window_publish_rejected(self, api):
        """PRD §3.2: "Publishing a row moves it to `PUBLISHED`, but only when no
        other `PUBLISHED` row exists with the same `rating_kind` and the same
        county-and-crop pair (crop-hail) — or the same `rating_kind`, species,
        and an overlapping value band (livestock) — whose effectiveness window
        overlaps the candidate's window; an overlap is rejected with
        `ERR_RATE_TABLE_OVERLAP` (HTTP 409)."
        R3 [2026-06-01, 2026-09-01) overlaps R1 [2026-01-01, 2026-08-01).

        Design: Difficulty/resource_temporal_overlap/rate_table_half_open_interval_overlap_rejected
        """
        carrier = create_carrier(carrier_code="CHL-O")
        cid = carrier["id"]
        r1 = create_rate_row(
            cid, "CROP_HAIL", rate_per_100_cents_of_liability=333,
            effective_from="2026-01-01T00:00:00Z",
            effective_to="2026-08-01T00:00:00Z",
        )
        publish_rate(cid, r1["id"])

        r3 = create_rate_row(
            cid, "CROP_HAIL", rate_per_100_cents_of_liability=500,
            effective_from="2026-06-01T00:00:00Z",
            effective_to="2026-09-01T00:00:00Z",
        )
        res = api.publish_rate_table(cid, r3["id"], UW)
        validate_error(res, ApiErrorId.ERR_RATE_TABLE_OVERLAP)
