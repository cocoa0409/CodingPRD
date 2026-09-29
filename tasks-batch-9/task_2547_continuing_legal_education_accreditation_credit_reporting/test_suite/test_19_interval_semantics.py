"""Three timelines, three interval conventions.

An attorney's compliance periods are half-open, so exact adjacency is legal; a
sponsor's audit windows are closed at both ends, so the very same adjacency
collides, and a separate guard allows the sponsor only one live engagement; and
a sponsor's in-person teaching capacity is an aggregate count of mutually
overlapping session windows, where two are fine and the third is refused.
"""
from datetime import datetime

from test_helpers import (
    api_client,
    create_accredited_provider,
    create_attorney,
    create_cycle,
    create_self_certified_course,
    factories,
    make_provider_admin_headers,
    open_audit,
    read_audit,
    read_course,
    read_cycle,
    read_provider,
    setup_two_concurrent_live_sessions,
    take_audit_to_cleared,
    validate_error,
    validate_paginated,
    validate_success,
)


def _as_instant(value: str) -> datetime:
    """Parses a wire timestamp so two spellings of the same instant compare
    equal."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _open_period_response(attorney_id, period_start, period_end, headers, **extra):
    """Posts one compliance period and hands back the raw response, so a
    refusal can be inspected."""
    payload = factories.create_compliance_cycle_payload(
        period_start=period_start, period_end=period_end, **extra
    )
    return api_client.create_compliance_cycle(attorney_id, payload, headers)


def _open_audit_response(provider_id, audit_period_start, audit_period_end,
                         trigger_type, headers):
    """Posts one audit engagement and hands back the raw response."""
    payload = factories.create_provider_audit_payload(
        provider_id,
        audit_period_start=audit_period_start,
        audit_period_end=audit_period_end,
        trigger_type=trigger_type,
    )
    return api_client.create_provider_audit(payload, headers)


def _create_course_response(provider, title, delivery_format, total_minutes,
                            presented_at, category="GENERAL"):
    """Registers one course for a sponsor and hands back the raw response."""
    payload = factories.create_course_payload(
        title=title,
        delivery_format=delivery_format,
        total_minutes=total_minutes,
        presented_at=presented_at,
        attendance_verification_method="ROSTER"
        if delivery_format == "LIVE_IN_PERSON" else "AFFIRMATION_ONLY",
        credit_allocations=[factories.credit_allocation_entry(category, total_minutes)],
        provider_id=provider["id"],
    )
    return api_client.create_course(
        payload, make_provider_admin_headers(provider["id"])
    )


def _attorney_with_a_middle_period():
    """One attorney on the register holding a single period that runs
    2024-01-01 to 2026-01-01. Returns (attorney, cycle)."""
    attorney = create_attorney(
        bar_number="BAR-1313", full_name="Beatrix Nyongo",
        admission_date="2008-01-01T00:00:00Z", compliance_group="GROUP_1",
    )
    cycle = create_cycle(attorney["id"], "2024-01-01T00:00:00Z", "2026-01-01T00:00:00Z")
    return attorney, cycle


def _sponsor_with_a_cleared_audit():
    """An accredited sponsor holding one self-study course inside a first audit
    window that has already been walked all the way to CLEARED, so no
    engagement slot is occupied. Returns (provider, course, audit)."""
    provider = create_accredited_provider(
        name="Granite Ridge CLE Foundation", provider_type="BAR_ASSOCIATION"
    )
    course = create_self_certified_course(
        provider,
        title="Winter Self-Study Module",
        delivery_format="SELF_STUDY",
        total_minutes=120,
        presented_at="2026-02-01T09:00:00Z",
        attendance_verification_method="AFFIRMATION_ONLY",
        credit_allocations=[factories.credit_allocation_entry("GENERAL", 120)],
    )
    audit = take_audit_to_cleared(
        provider["id"], "2026-01-01T00:00:00Z", "2026-03-31T00:00:00Z", "RANDOM",
        findings_count=0,
    )
    return provider, course, audit


# =========================================================================
# An attorney's compliance timeline: half-open, so adjacency is legal
# =========================================================================

def test_periods_touching_an_existing_period_at_either_end_are_accepted(
        api, board_headers):
    """PRD §3.4: "The period is the half-open interval running from `period_start` inclusive to `period_end` exclusive, and `period_start` must be strictly earlier than `period_end`."
    PRD §3.4: "Two periods of the same attorney may not intersect: an overlap is `ERR_CYCLE_PERIOD_OVERLAP`, while exact adjacency — a new period whose `period_start` equals an existing period's `period_end` — is explicitly allowed, because the half-open convention means the two share no instant."
    PRD §3.4: "Where `previous_cycle_id` is supplied it must name an existing cycle, and the new cycle's `carryover_in_general_minutes` and `carryover_in_ethics_minutes` are set to the predecessor's `carryover_out_general_minutes` and `carryover_out_ethics_minutes` respectively."
    PRD §3.4: "Finally, `filing_deadline` is `period_end` plus an offset drawn from the attorney's `compliance_group`: 31 days for `GROUP_1`, 61 days for `GROUP_2` and 91 days for `GROUP_3`."

    Design: Difficulty/resource_temporal_overlap/attorney_compliance_periods_are_half_open_so_exact_adjacency_is_legal
    """
    attorney, middle = _attorney_with_a_middle_period()

    following = validate_success(
        _open_period_response(
            attorney["id"], "2026-01-01T00:00:00Z", "2028-01-01T00:00:00Z",
            board_headers, previous_cycle_id=middle["id"],
        ),
        expected_status=201,
    )
    assert _as_instant(following["period_start"]) == _as_instant(
        middle["period_end"]
    ), (
        "the successor must start at the very instant the predecessor ends: "
        f"{following['period_start']} vs {middle['period_end']}"
    )
    assert following["carryover_in_general_minutes"] == 0, (
        "a predecessor that never certified hands forward nothing, got "
        f"{following['carryover_in_general_minutes']}"
    )
    assert _as_instant(following["filing_deadline"]) == _as_instant(
        "2028-02-01T00:00:00Z"
    ), (
        "the deadline is the period end plus the group's 31 days, got "
        f"{following['filing_deadline']}"
    )

    preceding = validate_success(
        _open_period_response(
            attorney["id"], "2022-01-01T00:00:00Z", "2024-01-01T00:00:00Z",
            board_headers,
        ),
        expected_status=201,
    )
    assert _as_instant(preceding["period_end"]) == _as_instant(
        middle["period_start"]
    ), (
        "a period ending exactly where an existing one starts is equally legal: "
        f"{preceding['period_end']} vs {middle['period_start']}"
    )
    assert _as_instant(preceding["filing_deadline"]) == _as_instant(
        "2024-02-01T00:00:00Z"
    ), (
        f"the deadline is the period end plus 31 days, got {preceding['filing_deadline']}"
    )

    _data, meta = validate_paginated(
        api_client.list_compliance_cycles(
            board_headers, params={"attorney_id": attorney["id"]}
        )
    )
    assert meta["total_count"] == 3, (
        f"three periods must now stand for this attorney, got {meta['total_count']}"
    )


def test_a_period_straddling_two_existing_periods_is_rejected(api, board_headers):
    """PRD §3.4: "Two periods of the same attorney may not intersect: an overlap is `ERR_CYCLE_PERIOD_OVERLAP`, while exact adjacency — a new period whose `period_start` equals an existing period's `period_end` — is explicitly allowed, because the half-open convention means the two share no instant."
    PRD §2.8: "a new cycle's half-open window does not overlap another cycle of the same attorney (`ERR_CYCLE_PERIOD_OVERLAP`)"

    Design: Difficulty/resource_temporal_overlap/attorney_compliance_periods_are_half_open_so_exact_adjacency_is_legal
    """
    attorney, middle = _attorney_with_a_middle_period()
    validate_success(
        _open_period_response(
            attorney["id"], "2026-01-01T00:00:00Z", "2028-01-01T00:00:00Z",
            board_headers, previous_cycle_id=middle["id"],
        ),
        expected_status=201,
    )

    response = _open_period_response(
        attorney["id"], "2025-06-01T00:00:00Z", "2027-06-01T00:00:00Z", board_headers
    )
    validate_error(response, "ERR_CYCLE_PERIOD_OVERLAP")

    _data, meta = validate_paginated(
        api_client.list_compliance_cycles(
            board_headers, params={"attorney_id": attorney["id"]}
        )
    )
    assert meta["total_count"] == 2, (
        "the refused period must leave no row behind, got "
        f"{meta['total_count']} periods"
    )


def test_a_period_intruding_one_second_into_an_existing_period_is_rejected(
        api, board_headers):
    """PRD §3.4: "Two periods of the same attorney may not intersect: an overlap is `ERR_CYCLE_PERIOD_OVERLAP`, while exact adjacency — a new period whose `period_start` equals an existing period's `period_end` — is explicitly allowed, because the half-open convention means the two share no instant."
    PRD §3.4: "The period is the half-open interval running from `period_start` inclusive to `period_end` exclusive, and `period_start` must be strictly earlier than `period_end`."

    Design: Difficulty/resource_temporal_overlap/attorney_compliance_periods_are_half_open_so_exact_adjacency_is_legal
    """
    attorney, middle = _attorney_with_a_middle_period()
    following = validate_success(
        _open_period_response(
            attorney["id"], "2026-01-01T00:00:00Z", "2028-01-01T00:00:00Z",
            board_headers, previous_cycle_id=middle["id"],
        ),
        expected_status=201,
    )

    response = _open_period_response(
        attorney["id"], "2027-12-31T23:59:59Z", "2029-12-31T23:59:59Z", board_headers
    )
    validate_error(response, "ERR_CYCLE_PERIOD_OVERLAP")

    unchanged = read_cycle(following["id"])
    assert unchanged["version"] == following["version"], (
        "a refused period must not touch the period it intruded on: "
        f"{following['version']} -> {unchanged['version']}"
    )
    _data, meta = validate_paginated(
        api_client.list_compliance_cycles(
            board_headers, params={"attorney_id": attorney["id"]}
        )
    )
    assert meta["total_count"] == 2, (
        "one second of intrusion is still an overlap, so no third period exists, "
        f"got {meta['total_count']}"
    )


# =========================================================================
# A sponsor's audit calendar: closed at both ends, and one engagement at a time
# =========================================================================

def test_an_audit_window_abutting_an_earlier_windows_end_is_rejected(
        api, board_headers):
    """PRD §3.9: "And audit windows of the same provider may neither overlap nor abut — because the audit window is closed at both ends, a new window whose start equals an existing window's end shares that instant and collides, giving `ERR_AUDIT_PERIOD_OVERLAP`."
    PRD §3.9: "The board opens an audit engagement over a **closed** window `[audit_period_start, audit_period_end]`, naming the `provider_id`, a `trigger_type` of `RISK_BASED`, `COMPLAINT_ESCALATION` or `RANDOM`, and optionally an `originating_complaint_id`."

    Design: Difficulty/resource_temporal_overlap/provider_audit_windows_are_closed_so_abutting_periods_collide_and_one_engagement_is_the_limit
    """
    provider, _course, first_audit = _sponsor_with_a_cleared_audit()
    assert first_audit["status"] == "CLEARED", (
        "the first engagement must be terminal before the calendar is tested, got "
        f"{first_audit['status']}"
    )

    response = _open_audit_response(
        provider["id"], "2026-03-31T00:00:00Z", "2026-06-30T00:00:00Z",
        "RISK_BASED", board_headers,
    )
    validate_error(response, "ERR_AUDIT_PERIOD_OVERLAP")

    _data, meta = validate_paginated(
        api_client.list_provider_audits(
            board_headers, params={"provider_id": provider["id"]}
        )
    )
    assert meta["total_count"] == 1, (
        "a window starting on the earlier window's closing instant writes no row, "
        f"got {meta['total_count']} engagements"
    )


def test_an_audit_window_starting_one_day_past_the_earlier_end_is_accepted(
        api, board_headers):
    """PRD §3.9: "And audit windows of the same provider may neither overlap nor abut — because the audit window is closed at both ends, a new window whose start equals an existing window's end shares that instant and collides, giving `ERR_AUDIT_PERIOD_OVERLAP`."
    PRD §3.9: "A new audit is created in `OPENED` with `sample_size` zero, `sampled_course_ids` empty, `findings_count` zero and `sanction_type` of `NONE`."

    Design: Difficulty/resource_temporal_overlap/provider_audit_windows_are_closed_so_abutting_periods_collide_and_one_engagement_is_the_limit
    """
    provider, _course, _first_audit = _sponsor_with_a_cleared_audit()

    second = validate_success(
        _open_audit_response(
            provider["id"], "2026-04-01T00:00:00Z", "2026-06-30T00:00:00Z",
            "RISK_BASED", board_headers,
        ),
        expected_status=201,
    )
    assert second["status"] == "OPENED", (
        f"a clear window opens the engagement, got {second['status']}"
    )
    assert second["sample_size"] == 0, (
        f"creation draws no sample, got sample_size {second['sample_size']}"
    )
    assert second["sampled_course_ids"] == [], (
        f"creation draws no sample, got {second['sampled_course_ids']}"
    )
    assert second["findings_count"] == 0, (
        f"a new engagement carries no findings, got {second['findings_count']}"
    )
    assert second["sanction_type"] == "NONE", (
        f"a new engagement carries no sanction, got {second['sanction_type']}"
    )

    _data, meta = validate_paginated(
        api_client.list_provider_audits(
            board_headers, params={"provider_id": provider["id"]}
        )
    )
    assert meta["total_count"] == 2, (
        f"the sponsor now holds two engagements, got {meta['total_count']}"
    )


def test_a_second_live_engagement_is_refused_even_for_a_disjoint_window(
        api, board_headers):
    """PRD §3.9: "A provider may hold only one live engagement at a time: opening a second while an existing audit of that provider is in `OPENED`, `SAMPLED` or `FINDINGS_ISSUED` is `ERR_AUDIT_ENGAGEMENT_ACTIVE`."
    PRD §3.9: "And audit windows of the same provider may neither overlap nor abut — because the audit window is closed at both ends, a new window whose start equals an existing window's end shares that instant and collides, giving `ERR_AUDIT_PERIOD_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/provider_audit_windows_are_closed_so_abutting_periods_collide_and_one_engagement_is_the_limit
    """
    provider, _course, _first_audit = _sponsor_with_a_cleared_audit()
    live_engagement = open_audit(
        provider["id"], "2026-04-01T00:00:00Z", "2026-06-30T00:00:00Z", "RISK_BASED"
    )
    assert live_engagement["status"] == "OPENED", (
        f"the second engagement must be live, got {live_engagement['status']}"
    )

    response = _open_audit_response(
        provider["id"], "2026-07-01T00:00:00Z", "2026-07-31T00:00:00Z",
        "RANDOM", board_headers,
    )
    validate_error(response, "ERR_AUDIT_ENGAGEMENT_ACTIVE")

    unchanged = read_audit(live_engagement["id"])
    assert unchanged["status"] == "OPENED", (
        "the refusal leaves the live engagement alone, got "
        f"{unchanged['status']}"
    )
    _data, meta = validate_paginated(
        api_client.list_provider_audits(
            board_headers, params={"provider_id": provider["id"]}
        )
    )
    assert meta["total_count"] == 2, (
        "a window that overlaps nothing is still refused while an engagement is "
        f"live, so no third row exists, got {meta['total_count']}"
    )


# =========================================================================
# A sponsor's in-person capacity: an aggregate count, not a pairwise check
# =========================================================================

def test_two_overlapping_live_sessions_stand_and_a_third_overlapping_one_is_refused(
        api, board_headers):
    """PRD §3.2: "Registering a new `LIVE_IN_PERSON` course must not leave the sponsor with more than two courses whose session windows all overlap some common instant; a third overlapping live session is rejected with `ERR_SESSION_WINDOW_CONFLICT`."
    PRD §3.2: "For `LIVE_IN_PERSON` and `LIVE_WEBCAST` it is `presented_at` plus the course's own `total_minutes` — a live session's approval covers the session and nothing more."

    Design: Difficulty/resource_temporal_overlap/concurrent_live_session_capacity_is_an_aggregate_closed_interval_count_not_a_pairwise_check
    """
    provider, first, second = setup_two_concurrent_live_sessions(
        create_accredited_provider(
            name="Bayfront Trial College", provider_type="LAW_SCHOOL"
        )
    )
    assert _as_instant(first["expires_at"]) == _as_instant("2026-05-01T13:00:00Z"), (
        "the morning session runs four hours from nine, got "
        f"{first['expires_at']}"
    )
    assert _as_instant(second["expires_at"]) == _as_instant("2026-05-01T16:00:00Z"), (
        f"the midday session runs four hours from noon, got {second['expires_at']}"
    )
    assert first["status"] == "APPROVED" and second["status"] == "APPROVED", (
        "two sessions overlapping each other are both accepted, got "
        f"{first['status']} and {second['status']}"
    )

    response = _create_course_response(
        provider, "Overlapping Trial Lab C", "LIVE_IN_PERSON", 60,
        "2026-05-01T12:30:00Z",
    )
    validate_error(response, "ERR_SESSION_WINDOW_CONFLICT")

    after = read_provider(provider["id"])
    assert after["courses_total_count"] == 2, (
        "the refused registration writes no course row, got "
        f"{after['courses_total_count']}"
    )
    assert after["courses_self_certified_count"] == 2, (
        "the refused registration writes no course row, got "
        f"{after['courses_self_certified_count']}"
    )


def test_a_live_session_the_next_day_overlaps_nothing_and_is_accepted(
        api, board_headers):
    """PRD §3.2: "Registering a new `LIVE_IN_PERSON` course must not leave the sponsor with more than two courses whose session windows all overlap some common instant; a third overlapping live session is rejected with `ERR_SESSION_WINDOW_CONFLICT`."
    PRD §3.2: "A course on the self-certification pathway is presumptively approved: it is created and immediately transitions `PENDING_APPROVAL → APPROVED` in the same request, its sponsor's `courses_self_certified_count` and `courses_total_count` each rise by one, and the sponsor's `risk_score` is recomputed because the denominator behind its findings rate has changed."

    Design: Difficulty/resource_temporal_overlap/concurrent_live_session_capacity_is_an_aggregate_closed_interval_count_not_a_pairwise_check
    """
    provider, _first, _second = setup_two_concurrent_live_sessions(
        create_accredited_provider(
            name="Bayfront Trial College", provider_type="LAW_SCHOOL"
        )
    )

    next_day = validate_success(
        _create_course_response(
            provider, "Next-Day Trial Lab F", "LIVE_IN_PERSON", 60,
            "2026-05-02T09:00:00Z",
        ),
        expected_status=201,
    )
    assert next_day["status"] == "APPROVED", (
        "a session sharing no instant with the two standing ones is accepted, got "
        f"{next_day['status']}"
    )
    assert _as_instant(next_day["expires_at"]) == _as_instant(
        "2026-05-02T10:00:00Z"
    ), (
        f"one hour of session, one hour of approval, got {next_day['expires_at']}"
    )

    after = read_provider(provider["id"])
    assert after["courses_total_count"] == 3, (
        f"three courses now stand, got {after['courses_total_count']}"
    )
    assert after["courses_self_certified_count"] == 3, (
        f"all three are self-certified, got {after['courses_self_certified_count']}"
    )


def test_an_on_demand_course_inside_the_busy_window_is_accepted(api, board_headers):
    """PRD §3.2: "Registering a new `LIVE_IN_PERSON` course must not leave the sponsor with more than two courses whose session windows all overlap some common instant; a third overlapping live session is rejected with `ERR_SESSION_WINDOW_CONFLICT`."
    PRD §3.2: "For `ON_DEMAND` and `SELF_STUDY` it is `presented_at` plus 36 months, three years of shelf life for recorded material."

    Design: Difficulty/resource_temporal_overlap/concurrent_live_session_capacity_is_an_aggregate_closed_interval_count_not_a_pairwise_check
    """
    provider, _first, second = setup_two_concurrent_live_sessions(
        create_accredited_provider(
            name="Bayfront Trial College", provider_type="LAW_SCHOOL"
        )
    )

    recorded = validate_success(
        _create_course_response(
            provider, "Overlapping On-Demand Module", "ON_DEMAND", 60,
            "2026-05-01T12:30:00Z",
        ),
        expected_status=201,
    )
    assert recorded["status"] == "APPROVED", (
        "the capacity limit counts only in-person sessions, so recorded material "
        f"inside the same window is accepted, got {recorded['status']}"
    )
    assert _as_instant(recorded["presented_at"]) < _as_instant(
        second["expires_at"]
    ), (
        "the recorded course really does sit inside the busy window: "
        f"{recorded['presented_at']} vs {second['expires_at']}"
    )
    assert _as_instant(recorded["expires_at"]) == _as_instant(
        "2029-05-01T12:30:00Z"
    ), (
        f"recorded material keeps three years of shelf life, got {recorded['expires_at']}"
    )

    after = read_provider(provider["id"])
    assert after["courses_total_count"] == 3, (
        f"three courses now stand, got {after['courses_total_count']}"
    )
    assert read_course(recorded["id"])["status"] == "APPROVED", (
        "the recorded course is approved on the register too"
    )
