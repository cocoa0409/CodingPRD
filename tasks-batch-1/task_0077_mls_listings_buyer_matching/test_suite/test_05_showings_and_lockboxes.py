"""Showing confirmation conflicts, temporal gates, and lockbox lifecycle."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    setup_active_listing,
    setup_confirmed_showing,
    install_lockbox,
    request_showing,
    confirm_showing,
    set_clock,
    make_listing_agent_headers,
    make_buyer_agent_headers,
)


def test_showing_buffer_exact_adjacency_no_conflict(api):
    """PRD §3.4: "Because the intervals are half-open, two showings that abut exactly at
    the buffer boundary — where one window's buffered end equals the next window's start
    — do not conflict."

    Design: Difficulty/boundary_precision_check/showing_buffer_exact_adjacency_no_conflict
    """
    # First CONFIRMED [15:00,15:30), buffer 30 -> buffered end 16:00.
    s = setup_confirmed_showing(start_at="2026-07-01T15:00:00Z",
                                end_at="2026-07-01T15:30:00Z", turnaround_minutes=30)
    la, ba = s["listing_agent"]["id"], s["buyer_agent"]["id"]
    sh2 = request_showing(s["lockbox"]["id"], ba, s["buyer"]["id"],
                          "2026-07-01T16:00:00Z", "2026-07-01T16:30:00Z")
    confirmed = confirm_showing(sh2["id"], la)
    assert confirmed["status"] == "CONFIRMED", confirmed


def test_showing_buffer_adjacency_no_conflict_earlier_window(api):
    """PRD §3.4: "two showings that abut exactly at the buffer boundary — where one
    window's buffered end equals the next window's start — do not conflict."

    Design: Difficulty/boundary_precision_check/showing_buffer_exact_adjacency_no_conflict
    """
    # First CONFIRMED [16:00,16:30). A candidate [15:00,15:30) has buffered end 16:00,
    # exactly equal to the confirmed window's start -> no conflict (half-open boundary).
    s = setup_confirmed_showing(start_at="2026-07-01T16:00:00Z",
                                end_at="2026-07-01T16:30:00Z", turnaround_minutes=30)
    la, ba = s["listing_agent"]["id"], s["buyer_agent"]["id"]
    earlier = request_showing(s["lockbox"]["id"], ba, s["buyer"]["id"],
                              "2026-07-01T15:00:00Z", "2026-07-01T15:30:00Z")
    confirmed = confirm_showing(earlier["id"], la)
    assert confirmed["status"] == "CONFIRMED", confirmed


def test_showing_buffered_overlap_within_turnaround_conflicts(api):
    """PRD §3.4: "the candidate is treated as running from its `start_at` up to `end_at`
    plus the buffer, and each existing `CONFIRMED` showing on the same lockbox is treated
    as running from its `start_at` up to its `end_at` plus the buffer. The two conflict
    when the candidate's start is strictly before the existing window's buffered end and
    the existing window's start is strictly before the candidate's buffered end".

    Design: Difficulty/resource_temporal_overlap/showing_buffered_overlap_within_turnaround
    """
    # First CONFIRMED [15:00,15:30), buffered end 16:00. Candidate at 15:59:59 < 16:00.
    s = setup_confirmed_showing(start_at="2026-07-01T15:00:00Z",
                                end_at="2026-07-01T15:30:00Z", turnaround_minutes=30)
    la, ba = s["listing_agent"]["id"], s["buyer_agent"]["id"]
    sh2 = request_showing(s["lockbox"]["id"], ba, s["buyer"]["id"],
                          "2026-07-01T15:59:59Z", "2026-07-01T16:30:00Z")
    resp = api.confirm_showing(sh2["id"], headers=make_listing_agent_headers(la))
    validate_error(resp, ApiErrorId.ERR_SHOWING_CONFLICT.value)


def test_showing_direct_overlap_conflicts(api):
    """PRD §3.4: "The two conflict when the candidate's start is strictly before the
    existing window's buffered end and the existing window's start is strictly before
    the candidate's buffered end; the candidate showing being confirmed is itself
    excluded from the comparison set."
    PRD §3.4: "A genuine overlap is rejected with `ERR_SHOWING_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/showing_buffered_overlap_within_turnaround
    """
    # First CONFIRMED [15:00,15:30). A candidate [15:15,15:45) overlaps the raw window
    # directly (well inside the buffered end of 16:00) -> conflict.
    s = setup_confirmed_showing(start_at="2026-07-01T15:00:00Z",
                                end_at="2026-07-01T15:30:00Z", turnaround_minutes=30)
    la, ba = s["listing_agent"]["id"], s["buyer_agent"]["id"]
    sh2 = request_showing(s["lockbox"]["id"], ba, s["buyer"]["id"],
                          "2026-07-01T15:15:00Z", "2026-07-01T15:45:00Z")
    resp = api.confirm_showing(sh2["id"], headers=make_listing_agent_headers(la))
    validate_error(resp, ApiErrorId.ERR_SHOWING_CONFLICT.value)


def test_confirm_showing_on_disabled_lockbox_rejected(api):
    """PRD §3.3: "a showing may still be *requested* against a `DISABLED` lockbox, but it
    can never be *confirmed* — confirmation against a disabled lockbox is rejected with
    `ERR_LOCKBOX_DISABLED` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/showing_confirm_requires_lockbox_installed
    """
    # Keep the listing ACTIVE via a second lockbox; disable lb_a, request on it, confirm.
    s = setup_active_listing()
    la, ba = s["listing_agent"]["id"], s["buyer_agent"]["id"]
    lb_a = s["lockbox"]
    install_lockbox(s["listing"]["id"], la)  # lb_b keeps activation valid history
    validate_success(api.disable_lockbox(lb_a["id"],
                     headers=make_listing_agent_headers(la)), 200)
    showing = request_showing(lb_a["id"], ba, s["buyer"]["id"],
                              "2026-07-01T15:00:00Z", "2026-07-01T15:30:00Z")
    resp = api.confirm_showing(showing["id"], headers=make_listing_agent_headers(la))
    validate_error(resp, ApiErrorId.ERR_LOCKBOX_DISABLED.value)


def test_confirm_showing_succeeds_while_lockbox_installed(api):
    """PRD §3.4: "Confirmation is the listing agent's action, moving a showing from
    `REQUESTED` to `CONFIRMED`. It is barred to anyone but the parent listing's listing
    agent (`ERR_NOT_LISTING_AGENT`), refused when the lockbox is `DISABLED`
    (`ERR_LOCKBOX_DISABLED`)".

    Design: Difficulty/cross_entity_state_dependency/showing_confirm_requires_lockbox_installed
    """
    # Positive side of the same Lockbox-INSTALLED gate: confirmation succeeds while the
    # lockbox remains INSTALLED.
    s = setup_active_listing()
    la, ba = s["listing_agent"]["id"], s["buyer_agent"]["id"]
    showing = request_showing(s["lockbox"]["id"], ba, s["buyer"]["id"],
                              "2026-07-01T15:00:00Z", "2026-07-01T15:30:00Z")
    confirmed = confirm_showing(showing["id"], la)
    assert confirmed["status"] == "CONFIRMED", confirmed


def test_disable_lockbox_cancels_requested_showing_cascade(api):
    """PRD §3.3: "When disabling does proceed, every showing on the lockbox still in
    `REQUESTED` status is cascaded to `CANCELLED`."

    Design: Corner/state_machines/disable_lockbox_cancels_requested_showing_cascade
    """
    s = setup_active_listing()
    la, ba = s["listing_agent"]["id"], s["buyer_agent"]["id"]
    showing = request_showing(s["lockbox"]["id"], ba, s["buyer"]["id"],
                              "2026-07-01T15:00:00Z", "2026-07-01T15:30:00Z")
    la_h = make_listing_agent_headers(la)
    disabled = validate_success(api.disable_lockbox(s["lockbox"]["id"], headers=la_h), 200)
    assert disabled["status"] == "DISABLED", disabled
    sh = validate_success(api.get_showing(showing["id"], headers=la_h), 200)
    assert sh["status"] == "CANCELLED", sh


def test_disable_lockbox_with_confirmed_showing_rejected(api):
    """PRD §3.3: "disabling is refused while any showing on the lockbox is in `CONFIRMED`
    status — that rejection is `ERR_LOCKBOX_HAS_SHOWINGS` (HTTP 409)."

    Design: Corner/validations/disable_lockbox_with_confirmed_showing_rejected
    """
    s = setup_confirmed_showing(turnaround_minutes=30)
    la = s["listing_agent"]["id"]
    resp = api.disable_lockbox(s["lockbox"]["id"], headers=make_listing_agent_headers(la))
    validate_error(resp, ApiErrorId.ERR_LOCKBOX_HAS_SHOWINGS.value)


def test_showing_bad_time_window_rejected(api):
    """PRD §3.4: "The window must be well-formed: `end_at` strictly later than
    `start_at`, or the request is rejected with `ERR_BAD_TIME_WINDOW` (HTTP 422)."

    Design: Corner/validations/showing_bad_time_window_rejected
    """
    s = setup_active_listing()
    ba = s["buyer_agent"]["id"]
    from test_helpers import create_showing_payload
    resp = api.create_showing(
        s["lockbox"]["id"],
        create_showing_payload(ba, s["buyer"]["id"],
                               "2026-07-01T16:00:00Z", "2026-07-01T15:00:00Z"),
        headers=make_buyer_agent_headers(ba))
    validate_error(resp, ApiErrorId.ERR_BAD_TIME_WINDOW.value)


def test_complete_showing_before_end_rejected(api):
    """PRD §3.4: "both require that the server's current clock be at or after the
    showing's `end_at`; an attempt before the window has elapsed is rejected with
    `ERR_SHOWING_NOT_OVER` (HTTP 409)."

    Design: Corner/validations/complete_showing_before_end_rejected
    """
    set_clock("2026-07-01T14:00:00Z")
    s = setup_confirmed_showing(start_at="2026-07-01T15:00:00Z",
                                end_at="2026-07-01T15:30:00Z")
    la = s["listing_agent"]["id"]
    set_clock("2026-07-01T15:15:00Z")  # before end 15:30
    resp = api.complete_showing(s["showing"]["id"], headers=make_listing_agent_headers(la))
    validate_error(resp, ApiErrorId.ERR_SHOWING_NOT_OVER.value)
