"""Scheduled-window overlap rules: closed-interval interpreter double-booking and
half-open client window conflicts."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_client, create_language_pair, create_rate_plan, create_interpreter,
    add_certification, add_language_grant, create_request, dispatch_request,
    set_clock, make_interpreter_headers, make_client_headers, coordinator_headers,
    factories,
)


def _court_video_env(max_concurrent_load=2):
    client = create_client(org_name="County Court", org_type="COURT", contact_email="court@x.com")
    create_rate_plan(client["id"], certification_tier="COURT", modality="VIDEO",
                     billing_mode="PER_MINUTE", rate_cents=240, min_block_units=10)
    lp = create_language_pair(source_lang="en", target_lang="es")
    itp = create_interpreter(full_name="Court I", max_concurrent_load=max_concurrent_load)
    add_certification(itp["id"], tier="COURT", expires_at="2027-01-01T00:00:00Z")
    add_language_grant(itp["id"], lp["id"])
    return client, lp, itp


def test_interpreter_double_booked_touching_window_rejected(api):
    """PRD 3.3: "when the only obstacle is that the otherwise-chosen interpreter's scheduled
    window collides with one of their existing windows, it is rejected with
    `ERR_INTERPRETER_DOUBLE_BOOKED` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/interpreter_double_booked_closed_interval
    """
    client, lp, itp = _court_video_env()
    set_clock("2026-03-10T08:00:00Z")
    # First scheduled window 11:00-12:00, accepted by the only qualified interpreter.
    r1 = create_request(client["id"], lp["id"], modality="VIDEO", required_tier="COURT",
                        scheduling_mode="SCHEDULED",
                        window_start="2026-03-10T11:00:00Z", window_end="2026-03-10T12:00:00Z")
    a1 = dispatch_request(r1["id"], r1["version"])
    validate_success(api.accept_assignment(a1["id"], make_interpreter_headers(itp["id"])))
    # Second window 12:00-13:00 touches the first at 12:00 -> closed-interval conflict.
    r2 = create_request(client["id"], lp["id"], modality="VIDEO", required_tier="COURT",
                        scheduling_mode="SCHEDULED",
                        window_start="2026-03-10T12:00:00Z", window_end="2026-03-10T13:00:00Z")
    # Only candidate is double-booked under closed-interval -> the only obstacle is the
    # window collision -> ERR_INTERPRETER_DOUBLE_BOOKED.
    resp = api.dispatch_request(r2["id"], factories.dispatch_payload(r2["version"]), coordinator_headers())
    validate_error(resp, ApiErrorId.ERR_INTERPRETER_DOUBLE_BOOKED.value)


def test_no_accepted_assignment_for_double_booked_window(api):
    """PRD 3.3: "when the only obstacle is that the otherwise-chosen interpreter's scheduled
    window collides with one of their existing windows, it is rejected with
    `ERR_INTERPRETER_DOUBLE_BOOKED` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/interpreter_double_booked_closed_interval
    """
    client, lp, itp = _court_video_env()
    set_clock("2026-03-10T08:00:00Z")
    r1 = create_request(client["id"], lp["id"], modality="VIDEO", required_tier="COURT",
                        scheduling_mode="SCHEDULED",
                        window_start="2026-03-10T11:00:00Z", window_end="2026-03-10T12:00:00Z")
    a1 = dispatch_request(r1["id"], r1["version"])
    validate_success(api.accept_assignment(a1["id"], make_interpreter_headers(itp["id"])))
    r2 = create_request(client["id"], lp["id"], modality="VIDEO", required_tier="COURT",
                        scheduling_mode="SCHEDULED",
                        window_start="2026-03-10T12:00:00Z", window_end="2026-03-10T13:00:00Z")
    resp = api.dispatch_request(r2["id"], factories.dispatch_payload(r2["version"]), coordinator_headers())
    validate_error(resp, ApiErrorId.ERR_INTERPRETER_DOUBLE_BOOKED.value)
    # The rejected dispatch mints no assignment for r2.
    from test_helpers import validate_paginated
    data, meta = validate_paginated(
        api.list_assignments(coordinator_headers(), params={"request_id": r2["id"]})
    )
    assert meta["total_count"] == 0, f"no assignment should exist for r2, found {meta['total_count']}"


def test_client_window_conflict_overlap_rejected(api):
    """PRD 3.2: "its window - treated as a half-open interval that includes its start instant
    and excludes its end instant - must not overlap the window of any other OPEN or ASSIGNED
    SCHEDULED request belonging to the same client ... any genuine overlap is rejected with
    ERR_CLIENT_WINDOW_CONFLICT (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/client_window_conflict_half_open
    """
    client = create_client(org_name="County Court", org_type="COURT", contact_email="court@x.com")
    lp = create_language_pair(source_lang="en", target_lang="es")
    set_clock("2026-03-10T08:00:00Z")
    create_request(client["id"], lp["id"], modality="VIDEO", required_tier="COURT",
                   scheduling_mode="SCHEDULED",
                   window_start="2026-03-10T11:00:00Z", window_end="2026-03-10T12:00:00Z")
    # 11:30-12:30 genuinely overlaps 11:00-12:00.
    client_h = make_client_headers(client["id"])
    resp = api.create_request(
        factories.create_request_payload(
            client_id=client["id"], language_pair_id=lp["id"], modality="VIDEO",
            required_tier="COURT", scheduling_mode="SCHEDULED",
            window_start="2026-03-10T11:30:00Z", window_end="2026-03-10T12:30:00Z",
        ),
        client_h,
    )
    validate_error(resp, ApiErrorId.ERR_CLIENT_WINDOW_CONFLICT.value)


def test_client_window_touching_adjacency_allowed(api):
    """PRD 3.2: "Under half-open semantics, two windows that merely touch at an endpoint (one
    ending exactly when the next begins) do not conflict."

    Design: Difficulty/resource_temporal_overlap/client_window_conflict_half_open
    """
    client = create_client(org_name="County Court", org_type="COURT", contact_email="court@x.com")
    lp = create_language_pair(source_lang="en", target_lang="es")
    set_clock("2026-03-10T08:00:00Z")
    create_request(client["id"], lp["id"], modality="VIDEO", required_tier="COURT",
                   scheduling_mode="SCHEDULED",
                   window_start="2026-03-10T11:00:00Z", window_end="2026-03-10T12:00:00Z")
    # 12:00-13:00 touches the first only at 12:00 -> half-open permits adjacency.
    client_h = make_client_headers(client["id"])
    created = validate_success(
        api.create_request(
            factories.create_request_payload(
                client_id=client["id"], language_pair_id=lp["id"], modality="VIDEO",
                required_tier="COURT", scheduling_mode="SCHEDULED",
                window_start="2026-03-10T12:00:00Z", window_end="2026-03-10T13:00:00Z",
            ),
            client_h,
        ),
        expected_status=201,
    )
    assert created["status"] == "OPEN"
