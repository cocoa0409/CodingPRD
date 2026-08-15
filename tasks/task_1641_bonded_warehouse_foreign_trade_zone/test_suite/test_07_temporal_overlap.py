"""Resource temporal overlap: half-open weekly-entry windows vs CLOSED
badge-validity windows — opposite adjacency treatment."""
from test_helpers import (
    ApiErrorId,
    api_client,
    create_access_badge_payload,
    create_badge,
    create_weekly_entry,
    create_zone,
    get_success_data,
    make_importer_headers,
    make_zone_operator_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestWeeklyEntryHalfOpenWindowOverlap:
    """Half-open [week_start, week_start+7d): interior start conflicts; exact
    adjacency at week_end is legal."""

    def test_interior_start_conflicts(self):
        """PRD §3.6: "Two entries on the same zone may not have overlapping weeks:
        because the interval is half-open, a new entry whose `week_start_date`
        coincides exactly with an existing entry's `week_end_date` is adjacent
        rather than overlapping and is permitted, but any true intersection is
        rejected with `ERR_WEEK_WINDOW_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/weekly_entry_half_open_window_overlap
        """
        zone = create_zone(bond_coverage_cents=10_000_000_000, name="Overlap Zone", zone_code="Z-OV")
        create_weekly_entry(zone["id"], week_start_date="2026-08-03T00:00:00Z", importer_id="imp-1")
        imp = make_importer_headers("imp-1")
        # 2026-08-05 falls inside [08-03, 08-10)
        resp = api_client.create_weekly_entry(
            {"zone_id": zone["id"], "week_start_date": "2026-08-05T00:00:00Z"}, imp,
        )
        validate_error(resp, ApiErrorId.ERR_WEEK_WINDOW_OVERLAP, expected_status=409)

    def test_exact_adjacency_at_week_end_is_legal(self):
        """PRD §3.6: "a new entry whose `week_start_date` coincides exactly with an
        existing entry's `week_end_date` is adjacent rather than overlapping and is
        permitted"
        PRD §3.6: "The entry's `week_end_date` is derived as exactly seven days
        after `week_start_date`"

        Design: Difficulty/resource_temporal_overlap/weekly_entry_half_open_window_overlap
        """
        zone = create_zone(bond_coverage_cents=10_000_000_000, name="Overlap Zone 2", zone_code="Z-O2")
        create_weekly_entry(zone["id"], week_start_date="2026-08-03T00:00:00Z", importer_id="imp-1")
        imp = make_importer_headers("imp-1")
        resp = api_client.create_weekly_entry(
            {"zone_id": zone["id"], "week_start_date": "2026-08-10T00:00:00Z"}, imp,
        )
        data = validate_success(resp, expected_status=201)
        assert data["week_end_date"] == "2026-08-17T00:00:00Z", (
            f"week_end must be start + 7 days, got {data['week_end_date']}"
        )
        assert data["status"] == "OPEN"

        op = make_zone_operator_headers()
        _rows, meta = validate_paginated(
            api_client.list_weekly_entries(op, params={"zone_id": zone["id"]})
        )
        assert meta["total_count"] == 2, f"both entries must exist, got {meta['total_count']}"


class TestBadgeClosedIntervalWindowOverlap:
    """CLOSED [valid_from, valid_until]: a touching start conflicts; a start one
    day later is legal."""

    def test_touching_bounds_conflict(self):
        """PRD §3.8: "if another badge exists for the same zone and the same
        `holder_name` with status `ACTIVE` or `SUSPENDED` whose closed validity
        window intersects the new badge's window — and because both intervals are
        closed, windows that merely touch at a boundary instant also conflict —
        issuance is rejected with `ERR_BADGE_WINDOW_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/badge_closed_interval_window_overlap
        """
        zone = create_zone(bond_coverage_cents=10_000_000_000, name="Badge Zone", zone_code="Z-BDG")
        create_badge(zone["id"], holder_name="Ada Lovelace",
                     valid_from="2026-08-01T00:00:00Z", valid_until="2026-08-31T00:00:00Z")
        op = make_zone_operator_headers()
        # valid_from exactly touches the existing badge's valid_until.
        resp = api_client.create_access_badge(
            create_access_badge_payload(
                zone_id=zone["id"], holder_name="Ada Lovelace",
                valid_from="2026-08-31T00:00:00Z", valid_until="2026-09-30T00:00:00Z",
            ), op,
        )
        validate_error(resp, ApiErrorId.ERR_BADGE_WINDOW_OVERLAP, expected_status=409)

    def test_start_after_existing_window_is_legal(self):
        """PRD §3.8: "The window is a closed interval — both bounds inclusive" — so
        only a shared instant conflicts; a start strictly after valid_until does
        not intersect.
        PRD §3.8: "A new badge starts in `ACTIVE` status."

        Design: Difficulty/resource_temporal_overlap/badge_closed_interval_window_overlap
        """
        zone = create_zone(bond_coverage_cents=10_000_000_000, name="Badge Zone 2", zone_code="Z-B2")
        create_badge(zone["id"], holder_name="Ada Lovelace",
                     valid_from="2026-08-01T00:00:00Z", valid_until="2026-08-31T00:00:00Z")
        op = make_zone_operator_headers()
        resp = api_client.create_access_badge(
            create_access_badge_payload(
                zone_id=zone["id"], holder_name="Ada Lovelace",
                valid_from="2026-09-01T00:00:00Z", valid_until="2026-09-30T00:00:00Z",
            ), op,
        )
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "ACTIVE", f"new badge must start ACTIVE, got {data['status']}"

        _rows, meta = validate_paginated(
            api_client.list_access_badges(op, params={"zone_id": zone["id"], "holder_name": "Ada Lovelace"})
        )
        assert meta["total_count"] == 2, f"both badges must exist, got {meta['total_count']}"
