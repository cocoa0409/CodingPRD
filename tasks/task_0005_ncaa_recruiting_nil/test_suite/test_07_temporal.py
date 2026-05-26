"""Temporal-overlap and time-window claims: Period [start, end) half-open
adjacency vs overlap, transfer-portal 45-day half-open window, clock-set
driving window_closes_at (PRD §2.8, §3.1, §3.6).
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    create_program, setup_certified_athlete,
    set_clock, enter_portal,
    create_period_payload,
    make_student_athlete_headers,
    create_transfer_portal_entry_payload,
    match_transfer_portal_entry_payload,
    TEST_USERS,
)


# ─── Difficulty: resource_temporal_overlap / Period (Rule 8, instance 1) ─


def test_period_adjacency_permitted_one_second_overlap_rejected(api):
    """PRD §3.1: "Adjacency is permitted — a new period whose
    `starts_at` is exactly equal to an existing period's `ends_at` is
    accepted, because the existing period excludes its endpoint."
    PRD §3.1: "Periods within the same program may not overlap: if a
    newly supplied period's half-open interval `[starts_at, ends_at)`
    intersects the interval of any existing period for that same
    `program_id`, the create is rejected with `ERR_PERIOD_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/period_overlap_halfopen_adjacency_permitted
    """
    program = create_program(sport_code="FOOTBALL", school_name="Overlap U",
                             scholarship_slot_cap=85)

    # Initial CONTACT [2026-07-01..2026-07-10).
    first = validate_success(api.create_period(
        program["id"],
        create_period_payload(period_type="CONTACT",
                              starts_at="2026-07-01T00:00:00Z",
                              ends_at="2026-07-10T00:00:00Z"),
        TEST_USERS["compliance_officer_headers"],
    ), 201)

    # Adjacent DEAD [2026-07-10..2026-07-15): permitted.
    adj_res = api.create_period(
        program["id"],
        create_period_payload(period_type="DEAD",
                              starts_at="2026-07-10T00:00:00Z",
                              ends_at="2026-07-15T00:00:00Z"),
        TEST_USERS["compliance_officer_headers"],
    )
    validate_success(adj_res, 201)

    # Overlapping QUIET [2026-07-09T23:59:00..2026-07-20): rejected.
    overlap_res = api.create_period(
        program["id"],
        create_period_payload(period_type="QUIET",
                              starts_at="2026-07-09T23:59:00Z",
                              ends_at="2026-07-20T00:00:00Z"),
        TEST_USERS["compliance_officer_headers"],
    )
    validate_error(overlap_res, ApiErrorId.ERR_PERIOD_OVERLAP.value)


def test_period_overlap_within_existing_rejected(api):
    """PRD §3.1: "The merest overlap, including a one-cent overlap, is
    rejected."
    PRD §3.1: "Periods within the same program may not overlap"

    Design: Difficulty/resource_temporal_overlap/period_overlap_halfopen_adjacency_permitted
    """
    program = create_program(sport_code="FOOTBALL", school_name="Inner U",
                             scholarship_slot_cap=85)
    validate_success(api.create_period(
        program["id"],
        create_period_payload(period_type="CONTACT",
                              starts_at="2026-08-01T00:00:00Z",
                              ends_at="2026-08-30T00:00:00Z"),
        TEST_USERS["compliance_officer_headers"],
    ), 201)

    # New period fully inside the existing one: overlap → rejected.
    res = api.create_period(
        program["id"],
        create_period_payload(period_type="QUIET",
                              starts_at="2026-08-10T00:00:00Z",
                              ends_at="2026-08-15T00:00:00Z"),
        TEST_USERS["compliance_officer_headers"],
    )
    validate_error(res, ApiErrorId.ERR_PERIOD_OVERLAP.value)


# ─── Difficulty: resource_temporal_overlap / Portal window (Rule 8, instance 2) ─


def test_portal_match_rejected_at_exact_window_close_boundary(api):
    """PRD §3.6: "The window is open while the current UTC instant is
    strictly less than `window_closes_at`; the boundary at exactly
    `entered_at` plus 45 days is the moment the window closes, and
    operations attempted at or after that boundary are rejected as
    `ERR_PORTAL_WINDOW_CLOSED`."
    PRD §3.6: "On entry, the system stamps `entered_at` from the current
    UTC clock and computes `window_closes_at` as `entered_at` plus
    exactly 45 days, with no clamping or alignment to any boundary"

    Design: Difficulty/resource_temporal_overlap/portal_window_45day_exact_halfopen
    """
    set_clock("2026-01-01T00:00:00Z")
    source = create_program(sport_code="MBB", school_name="Portal U",
                            scholarship_slot_cap=13)
    destination = create_program(sport_code="MBB", school_name="Destination U",
                                 scholarship_slot_cap=13)
    athlete = setup_certified_athlete(sport_code="MBB", full_name="Athlete W")
    entry = enter_portal(athlete, source)
    assert entry["entered_at"] == "2026-01-01T00:00:00Z" or \
        entry["entered_at"].startswith("2026-01-01T00:00:00")

    # Move the clock to entered_at + 45 days exactly.
    set_clock("2026-02-15T00:00:00Z")
    res = api.match_transfer_portal_entry(
        entry["id"],
        match_transfer_portal_entry_payload(
            matched_program_id=destination["id"],
            expected_transferportalentry_version=entry["version"],
        ),
        TEST_USERS["compliance_officer_headers"],
    )
    validate_error(res, ApiErrorId.ERR_PORTAL_WINDOW_CLOSED.value)


def test_portal_match_succeeds_just_before_window_close(api):
    """PRD §3.6: "The window is open while the current UTC instant is
    strictly less than `window_closes_at`"
    PRD §3.6: "A `ComplianceOfficer` matches the entry to a destination
    program through a transition that moves `status` from `ENTERED` to
    `MATCHED`."

    Design: Difficulty/resource_temporal_overlap/portal_window_45day_exact_halfopen
    """
    set_clock("2026-01-01T00:00:00Z")
    source = create_program(sport_code="MBB", school_name="Src U", scholarship_slot_cap=13)
    destination = create_program(sport_code="MBB", school_name="Dst U", scholarship_slot_cap=13)
    athlete = setup_certified_athlete(sport_code="MBB")
    entry = enter_portal(athlete, source)

    # One second before the 45-day boundary.
    set_clock("2026-02-14T23:59:59Z")
    res = api.match_transfer_portal_entry(
        entry["id"],
        match_transfer_portal_entry_payload(
            matched_program_id=destination["id"],
            expected_transferportalentry_version=entry["version"],
        ),
        TEST_USERS["compliance_officer_headers"],
    )
    matched = validate_success(res, 200)
    assert matched["status"] == "MATCHED"
    assert matched["matched_program_id"] == destination["id"]


def test_clock_set_drives_window_closes_at_at_entered_at_plus_45_days(api):
    """PRD §3.6: "On entry, the system stamps `entered_at` from the
    current UTC clock and computes `window_closes_at` as `entered_at`
    plus exactly 45 days, with no clamping or alignment to any boundary"
    PRD §2.8: "For deterministic time-gated tests, the system exposes a
    clock-setting capability (`ComplianceOfficer`-only). Setting the
    clock pins `current_utc` to the supplied `to_iso8601` value;
    subsequent operations that read the current time — period selection
    for a recruiting contact, the transfer-portal window check, and the
    portal-expiration sweep — read from this pinned clock."

    Design: Corner/cross_cutting_complexity_layers/clock_set_current_utc_drives_window_logic
    """
    set_clock("2026-01-01T00:00:00Z")
    source = create_program(sport_code="MBB", school_name="Clock U", scholarship_slot_cap=13)
    athlete = setup_certified_athlete(sport_code="MBB", full_name="Cl")

    res = api.create_transfer_portal_entry(
        create_transfer_portal_entry_payload(
            student_athlete_id=athlete["id"],
            source_program_id=source["id"],
        ),
        make_student_athlete_headers(athlete["id"]),
    )
    entry = validate_success(res, 201)
    # entered_at is stamped from the clock; window_closes_at = entered_at + 45d.
    assert entry["entered_at"].startswith("2026-01-01T00:00:00")
    assert entry["window_closes_at"].startswith("2026-02-15T00:00:00")
