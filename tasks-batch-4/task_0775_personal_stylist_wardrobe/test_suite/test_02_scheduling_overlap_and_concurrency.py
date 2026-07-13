"""Session scheduling guards: stylist half-open overlap, client travel-buffer overlap,
the ordering of overlap vs package-availability, package-hours sufficiency, and the
optimistic-concurrency version check on the engagement.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_stylist, register_client, create_active_engagement, schedule_session,
    create_session_payload, make_client_headers, make_admin_headers,
)


# ─────────────── priority_pair / stylist_overlap_beats_package_fiscal_on_schedule ───────────────
def _setup_overlap_and_over_package(api):
    """Stylist STY shared by two clients: C1 HOURLY E1 with a session at 10:00-11:30;
    C2 PACKAGE E2 (package_blocks 4). Returns the response of scheduling a 6-block session
    under E2 at the same window (overlaps the stylist AND exceeds the 4-block pool)."""
    sty = create_stylist(api)
    c1 = register_client(api)
    c2 = register_client(api)
    e1 = create_active_engagement(api, c1["id"], sty["id"], mode="HOURLY", block_rate_cents=3000)
    schedule_session(api, e1["id"], c1["id"], e1["version"],
                     scheduled_start="2026-04-09T10:00:00Z", scheduled_end="2026-04-09T11:30:00Z")
    e2 = create_active_engagement(api, c2["id"], sty["id"], mode="PACKAGE", block_rate_cents=3000,
                                  package_blocks=4, package_price_cents=12000)
    return api.create_session(
        e2["id"],
        create_session_payload("2026-04-09T10:00:00Z", "2026-04-09T11:30:00Z", e2["version"]),
        make_client_headers(c2["id"]))


def test_schedule_overlap_and_over_package_returns_stylist_conflict(api):
    """PRD §2.11: "For the schedule-a-session endpoint in particular, after the general checks
    the stylist-overlap check runs, then the client-buffer check, then the package-availability
    check, and the optimistic-concurrency version check runs last of all."

    Design: Difficulty/priority_pair_validation_conflict/stylist_overlap_beats_package_fiscal_on_schedule
    """
    resp = _setup_overlap_and_over_package(api)
    validate_error(resp, ApiErrorId.ERR_STYLIST_TIME_CONFLICT.value)


def test_stylist_conflict_preempts_package_hours_check(api):
    """PRD §2.11: "the stylist-overlap check runs, then the client-buffer check, then the
    package-availability check, and the optimistic-concurrency version check runs last of all."

    Design: Difficulty/priority_pair_validation_conflict/stylist_overlap_beats_package_fiscal_on_schedule
    """
    resp = _setup_overlap_and_over_package(api)
    body = resp.json()["data"]
    assert body["error_id"] != ApiErrorId.ERR_INSUFFICIENT_PACKAGE_HOURS.value, (
        "stylist overlap must pre-empt the later package-availability check")
    assert body["error_id"] == ApiErrorId.ERR_STYLIST_TIME_CONFLICT.value


# ─────────────── resource_temporal_overlap / stylist_half_open_overlap_rejected ───────────────
def _two_engagements_same_stylist(api):
    sty = create_stylist(api)
    c1 = register_client(api)
    c2 = register_client(api)
    e1 = create_active_engagement(api, c1["id"], sty["id"], mode="HOURLY", block_rate_cents=3000)
    schedule_session(api, e1["id"], c1["id"], e1["version"],
                     scheduled_start="2026-04-12T10:00:00Z", scheduled_end="2026-04-12T11:30:00Z")
    e2 = create_active_engagement(api, c2["id"], sty["id"], mode="HOURLY", block_rate_cents=3000)
    return c2, e2


def test_overlapping_stylist_sessions_rejected(api):
    """PRD §3.4: "the new or rescheduled window [scheduled_start, scheduled_end) must not overlap
    any other non-terminal session (one that is SCHEDULED or CONFIRMED) belonging to any
    engagement of the same stylist ... A violation returns ERR_STYLIST_TIME_CONFLICT."

    Design: Difficulty/resource_temporal_overlap/stylist_half_open_overlap_rejected
    """
    c2, e2 = _two_engagements_same_stylist(api)
    resp = api.create_session(
        e2["id"],
        create_session_payload("2026-04-12T11:00:00Z", "2026-04-12T12:00:00Z", e2["version"]),
        make_client_headers(c2["id"]))
    validate_error(resp, ApiErrorId.ERR_STYLIST_TIME_CONFLICT.value)


def test_stylist_sessions_touching_at_endpoint_allowed(api):
    """PRD §3.4: "Intervals are half-open, so two sessions that merely touch at an endpoint —
    one ending exactly when the next begins — do not conflict."

    Design: Difficulty/resource_temporal_overlap/stylist_half_open_overlap_rejected
    """
    c2, e2 = _two_engagements_same_stylist(api)
    # New window starts exactly when session A ends (11:30) -> touching, not overlapping.
    resp = api.create_session(
        e2["id"],
        create_session_payload("2026-04-12T11:30:00Z", "2026-04-12T12:30:00Z", e2["version"]),
        make_client_headers(c2["id"]))
    validate_success(resp, 201)


# ─────────────── resource_temporal_overlap / client_buffer_overlap_rejected ───────────────
def _client_two_stylists_first_in_person(api):
    sty1 = create_stylist(api)
    sty2 = create_stylist(api)
    cl = register_client(api)
    e1 = create_active_engagement(api, cl["id"], sty1["id"], mode="HOURLY", block_rate_cents=3000)
    schedule_session(api, e1["id"], cl["id"], e1["version"], modality="IN_PERSON",
                     scheduled_start="2026-04-13T10:00:00Z", scheduled_end="2026-04-13T11:00:00Z")
    e2 = create_active_engagement(api, cl["id"], sty2["id"], mode="HOURLY", block_rate_cents=3000)
    return cl, e2


def test_client_travel_buffer_conflict_rejected(api):
    """PRD §3.4: "the window expanded by sixty minutes on each side must not overlap any other
    non-terminal IN_PERSON session of the same client, so consecutive in-person sessions for one
    client need at least a sixty-minute gap between them and mere adjacency is not enough. A
    violation returns ERR_CLIENT_TIME_CONFLICT."

    Design: Difficulty/resource_temporal_overlap/client_buffer_overlap_rejected
    """
    cl, e2 = _client_two_stylists_first_in_person(api)
    # Second IN_PERSON session starts 11:30 -> only a 30-minute gap after the 11:00 end.
    resp = api.create_session(
        e2["id"],
        create_session_payload("2026-04-13T11:30:00Z", "2026-04-13T12:30:00Z", e2["version"],
                               session_type="SHOPPING", modality="IN_PERSON"),
        make_client_headers(cl["id"]))
    validate_error(resp, ApiErrorId.ERR_CLIENT_TIME_CONFLICT.value)


def test_virtual_second_session_exempt_from_client_buffer(api):
    """PRD §3.4: "VIRTUAL sessions are exempt from the client buffer but are still subject to the
    stylist-overlap rule."

    Design: Difficulty/resource_temporal_overlap/client_buffer_overlap_rejected
    """
    cl, e2 = _client_two_stylists_first_in_person(api)
    # A VIRTUAL session in the same tight window is exempt from the client buffer; the two
    # engagements use different stylists, so the stylist-overlap rule is not triggered either.
    resp = api.create_session(
        e2["id"],
        create_session_payload("2026-04-13T11:30:00Z", "2026-04-13T12:30:00Z", e2["version"],
                               session_type="VIRTUAL", modality="VIRTUAL"),
        make_client_headers(cl["id"]))
    validate_success(resp, 201)


# ─────────────── Corner: schedule_exceeds_package_hours_rejected ───────────────
def test_schedule_exceeds_package_hours_rejected(api):
    """PRD §3.4: "For a PACKAGE engagement, scheduling or rescheduling additionally requires that
    hours_available_blocks be at least the requested session's estimated_blocks; when the pool
    cannot cover the reservation the request is rejected with ERR_INSUFFICIENT_PACKAGE_HOURS."

    Design: Corner/validations/schedule_exceeds_package_hours_rejected
    """
    sty = create_stylist(api)
    cl = register_client(api)
    eng = create_active_engagement(api, cl["id"], sty["id"], mode="PACKAGE", block_rate_cents=3000,
                                   package_blocks=4, package_price_cents=12000)
    # 90 min -> 6 blocks requested against a 4-block pool.
    resp = api.create_session(
        eng["id"],
        create_session_payload("2026-04-21T10:00:00Z", "2026-04-21T11:30:00Z", eng["version"]),
        make_client_headers(cl["id"]))
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PACKAGE_HOURS.value)


# ─────────────── Corner (OCC): schedule_with_stale_engagement_version_returns_412 ───────────────
def test_schedule_with_stale_engagement_version_rejected(api):
    """PRD §2.6: "If they do not match — because a prior successful schedule call already reserved
    blocks from the finite prepaid pool and advanced the engagement's version since the client last
    read it — the request is rejected with ERR_STALE_ENGAGEMENT_VERSION (HTTP 412) and no
    reservation is made."

    Design: Corner/cross_cutting/schedule_with_stale_engagement_version_returns_412
    """
    sty = create_stylist(api)
    cl = register_client(api)
    eng = create_active_engagement(api, cl["id"], sty["id"], mode="PACKAGE", block_rate_cents=3000,
                                   package_blocks=20, package_price_cents=60000)
    stale_version = eng["version"]
    # First schedule succeeds and advances the engagement version.
    schedule_session(api, eng["id"], cl["id"], stale_version,
                     scheduled_start="2026-04-23T10:00:00Z", scheduled_end="2026-04-23T11:30:00Z")
    # A second schedule still carrying the pre-schedule version is stale.
    resp = api.create_session(
        eng["id"],
        create_session_payload("2026-04-24T10:00:00Z", "2026-04-24T11:30:00Z", stale_version),
        make_client_headers(cl["id"]))
    validate_error(resp, ApiErrorId.ERR_STALE_ENGAGEMENT_VERSION.value)


# ─────────────── Corner (OCC): schedule_with_correct_version_succeeds_and_bumps_version ───────────────
def test_schedule_with_correct_version_bumps_engagement_version(api):
    """PRD §3.3: "For a PACKAGE engagement the scheduling reserves the session's estimated_blocks:
    they are added to hours_reserved_blocks and subtracted from hours_available_blocks, and the
    engagement's version is incremented by one."

    Design: Corner/cross_cutting/schedule_with_correct_version_succeeds_and_bumps_version
    """
    sty = create_stylist(api)
    cl = register_client(api)
    eng = create_active_engagement(api, cl["id"], sty["id"], mode="PACKAGE", block_rate_cents=3000,
                                   package_blocks=20, package_price_cents=60000)
    base_version = eng["version"]
    resp = api.create_session(
        eng["id"],
        create_session_payload("2026-04-25T10:00:00Z", "2026-04-25T11:30:00Z", base_version),
        make_client_headers(cl["id"]))
    validate_success(resp, 201)
    after = validate_success(api.get_engagement(eng["id"], make_admin_headers()), 200)
    assert after["version"] == base_version + 1, f"version should bump by 1, got {after['version']}"
    assert after["hours_reserved_blocks"] == 6
    assert after["hours_available_blocks"] == 14
