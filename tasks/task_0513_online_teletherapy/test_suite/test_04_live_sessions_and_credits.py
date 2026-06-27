"""Live-session scheduling: temporal-overlap and therapist-buffer conflicts,
session-credit reservation/conservation, OCC on the match version, and session
outcomes (PRD §2.5, §3.5).

Covers the resource_temporal_overlap and compensating_invariant difficulty
instances plus live-session / credit corner probes.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId,
    set_clock, cleared_client, accepting_therapist, propose_match, accept_match,
    active_match, active_match_with_credits, get_match, get_match_version,
    schedule_session, count_credits, subscription_with_paid_cycle,
    create_subscription, charge_cycle,
    api_client, make_client_headers, make_therapist_headers,
)
from test_helpers import TEST_USERS


def _client(cid):
    return make_client_headers(cid)


def _therapist(tid):
    return make_therapist_headers(tid)


def _clinical():
    return TEST_USERS["clinical_admin_headers"]


def _billing():
    return TEST_USERS["billing_admin_headers"]


# NOTE: test_same_match_closed_adjacency_session_allowed was DELETED.
# It asserted that two end-to-start adjacent (0-minute gap) sessions on the SAME match
# are allowed (HTTP 201), citing only PRD §3.5 guard 2 (overlap: end-to-start touching is
# allowed). But the same PRD §3.5 paragraph also states guard 3 verbatim: "the new session
# must respect a 15-minute buffer against every other non-terminal session belonging to the
# same therapist across all of that therapist's matches — two of the therapist's sessions must
# be at least 15 minutes apart". Two sessions on the same match always share a therapist, so a
# 0-minute-gap adjacency unconditionally trips guard 3 and is rejected with
# ERR_THERAPIST_DOUBLE_BOOKED. The asserted outcome (201 allowed) is NOT uniquely derivable from
# PRD — the complete reading contradicts it (STEP 1b). No fixture can make a same-match end-to-
# start adjacency allowable. The buffer-allowed boundary (>= 15 min) is covered by
# test_therapist_exact_buffer_gap_allowed; the overlap-rejection by
# test_session_overlap_same_match_rejected; the buffer-rejection by
# test_therapist_double_book_within_buffer_rejected.


def test_session_overlap_same_match_rejected(api):
    """PRD §3.5: "two sessions conflict when their half-open time intervals
    `[starts_at, ends_at)` intersect ... an overlap is rejected with `ERR_SESSION_OVERLAP`
    (HTTP 409)."

    Design: Corner/validations/session_overlap_same_match_rejected
    """
    set_clock("2026-06-01T00:00:00Z")
    info = active_match_with_credits(state_code="CA", weekly_credit_grant=2)
    match_id = info["match"]["id"]
    client_id = info["client"]["id"]
    schedule_session(match_id, client_id, "2026-06-02T09:00:00Z", "2026-06-02T10:00:00Z")
    version = get_match_version(match_id)
    resp = api.schedule_live_session(
        match_id,
        {"starts_at": "2026-06-02T09:30:00Z", "ends_at": "2026-06-02T10:30:00Z",
         "expected_match_version": version},
        _client(client_id),
    )
    validate_error(resp, ApiErrorId.ERR_SESSION_OVERLAP.value)


# ==========================================================================
# Difficulty: resource_temporal_overlap — therapist 15-min buffer (cross match)
# ==========================================================================
def test_therapist_double_book_within_buffer_rejected(api):
    """PRD §3.5: "the new session must respect a 15-minute buffer against every other non-terminal
    session belonging to the same therapist across all of that therapist's matches — two of the
    therapist's sessions must be at least 15 minutes apart, so a gap of less than a quarter hour
    between them is rejected with `ERR_THERAPIST_DOUBLE_BOOKED` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/therapist_double_book_buffer_adjacency_rejected
    """
    set_clock("2026-06-01T00:00:00Z")
    therapist = accepting_therapist(state_code="CA", max_active_caseload=5)
    # Client A: ACTIVE match, credit, session 09:00-10:00.
    client_a = cleared_client(state_code="CA")
    proposed_a = propose_match(client_a["id"], therapist["id"])
    match_a = accept_match(proposed_a["id"], client_a["id"])
    sub_a = create_subscription(client_a["id"])
    charge_cycle(sub_a["id"])
    schedule_session(match_a["id"], client_a["id"], "2026-06-02T09:00:00Z", "2026-06-02T10:00:00Z")
    # Client B: ACTIVE match to the same therapist, credit.
    client_b = cleared_client(state_code="CA")
    proposed_b = propose_match(client_b["id"], therapist["id"])
    match_b = accept_match(proposed_b["id"], client_b["id"])
    sub_b = create_subscription(client_b["id"])
    charge_cycle(sub_b["id"])
    version_b = get_match_version(match_b["id"])
    # 10:10 is only 10 min after the 09:00-10:00 session ends -> within the 15-min buffer.
    resp = api.schedule_live_session(
        match_b["id"],
        {"starts_at": "2026-06-02T10:10:00Z", "ends_at": "2026-06-02T11:10:00Z",
         "expected_match_version": version_b},
        _client(client_b["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_THERAPIST_DOUBLE_BOOKED.value)


# ==========================================================================
# Difficulty: compensating_invariant — credit count conserved (cancel outside window)
# ==========================================================================
def test_credit_returned_on_cancel_outside_window(api):
    """PRD §3.5: "a within-window cancellation forfeits the credit by moving it to `CONSUMED`,
    while a cancellation outside the window returns the credit to `AVAILABLE`."
    PRD §3.5: "cancellation moves it to `CANCELLED`, sets `cancelled_within_window` to true when
    the cancellation occurs less than 24 hours before `starts_at` and false otherwise"

    Design: Difficulty/compensating_invariant/credit_count_conserved_on_schedule_then_cancel_outside_window
    """
    set_clock("2026-06-01T00:00:00Z")
    info = active_match_with_credits(state_code="CA", weekly_credit_grant=1)
    match_id = info["match"]["id"]
    client_id = info["client"]["id"]
    ls = schedule_session(match_id, client_id, "2026-06-10T09:00:00Z", "2026-06-10T10:00:00Z")
    # cancel while > 24h out (clock still 2026-06-01).
    cancelled = validate_success(api.cancel_live_session(ls["id"], _client(client_id)))
    assert cancelled["status"] == "CANCELLED", cancelled
    assert cancelled["cancelled_within_window"] is False, cancelled
    assert count_credits(client_id, "AVAILABLE") == 1, "credit should be returned to AVAILABLE"


# ==========================================================================
# Corner: no-show after ends_at forfeits the credit
# ==========================================================================
def test_no_show_after_ends_at_consumes_credit(api):
    """PRD §3.5: "The therapist may mark a no-show, legal only when the session is `SCHEDULED` and
    the clock has reached or passed `ends_at`, which moves the session to `NO_SHOW` and forfeits
    the reserved credit by moving it to `CONSUMED`."

    Design: Corner/endpoints/no_show_consumes_credit_after_ends_at
    """
    set_clock("2026-06-01T00:00:00Z")
    info = active_match_with_credits(state_code="CA", weekly_credit_grant=1)
    match_id = info["match"]["id"]
    client_id = info["client"]["id"]
    therapist_id = info["therapist"]["id"]
    ls = schedule_session(match_id, client_id, "2026-06-02T09:00:00Z", "2026-06-02T10:00:00Z")
    set_clock("2026-06-02T10:30:00Z")  # past ends_at
    no_show = validate_success(api.no_show_live_session(ls["id"], _therapist(therapist_id)))
    assert no_show["status"] == "NO_SHOW", no_show
    assert count_credits(client_id, "CONSUMED") == 1, "credit should be forfeited (CONSUMED)"


# ==========================================================================
# Corner: scheduling with no AVAILABLE credit rejected
# ==========================================================================
def test_schedule_without_credit_rejected(api):
    """PRD §3.5: "scheduling requires at least one `AVAILABLE`, non-expired credit to reserve; if
    the client has none, the request is rejected with `ERR_NO_CREDIT` (HTTP 409)."

    Design: Corner/validations/no_credit_to_schedule_rejected
    """
    set_clock("2026-06-01T00:00:00Z")
    client, therapist, match = active_match(state_code="CA")  # no subscription charged -> no credits
    version = get_match_version(match["id"])
    resp = api.schedule_live_session(
        match["id"],
        {"starts_at": "2026-06-10T09:00:00Z", "ends_at": "2026-06-10T10:00:00Z",
         "expected_match_version": version},
        _client(client["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_NO_CREDIT.value)


# ==========================================================================
# Corner: ends_at <= starts_at rejected before business checks
# ==========================================================================
def test_schedule_ends_before_starts_rejected(api):
    """PRD §2.11: "Only then is the request body inspected for well-formedness — required fields
    present, enum values within their allowed sets, numbers within range, and on a live session a
    scheduled end strictly after its start — with any failure raising `ERR_INVALID_REQUEST`
    (HTTP 400)."

    Design: Corner/validations/invalid_request_ends_before_starts
    """
    set_clock("2026-06-01T00:00:00Z")
    info = active_match_with_credits(state_code="CA", weekly_credit_grant=1)
    match_id = info["match"]["id"]
    client_id = info["client"]["id"]
    version = get_match_version(match_id)
    resp = api.schedule_live_session(
        match_id,
        {"starts_at": "2026-06-10T11:00:00Z", "ends_at": "2026-06-10T10:00:00Z",
         "expected_match_version": version},
        _client(client_id),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# ==========================================================================
# Corner (cross-cutting): OCC stale match version on second schedule
# ==========================================================================
def test_stale_match_version_on_schedule_rejected(api):
    """PRD §2.5: "The server compares it to that match's current `version`; if they differ — for
    instance because a prior schedule already advanced the match's version while reserving a
    credit, possibly exhausting the credit pool — the request is rejected with `ERR_STALE_VERSION`
    (HTTP 412), so the caller cannot act on a stale view of the match."

    Design: Corner/cross_cutting_complexity_layers/occ_live_session_schedule_stale_match_version
    """
    set_clock("2026-06-01T00:00:00Z")
    info = active_match_with_credits(state_code="CA", weekly_credit_grant=2)
    match_id = info["match"]["id"]
    client_id = info["client"]["id"]
    version_pre = get_match_version(match_id)
    # First schedule advances the match version while reserving a credit.
    validate_success(api.schedule_live_session(
        match_id,
        {"starts_at": "2026-06-03T09:00:00Z", "ends_at": "2026-06-03T10:00:00Z",
         "expected_match_version": version_pre},
        _client(client_id),
    ), 201)
    # Second schedule carries the now-stale pre-first-schedule version.
    resp = api.schedule_live_session(
        match_id,
        {"starts_at": "2026-06-04T09:00:00Z", "ends_at": "2026-06-04T10:00:00Z",
         "expected_match_version": version_pre},
        _client(client_id),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


# ==========================================================================
# Corner (cross-cutting): scheduled credit expiry on clock advance
# ==========================================================================
def test_unused_credit_expires_on_clock_advance(api):
    """PRD §2.10: "expires any `SessionCredit` whose `expires_on` is at or before the new instant."
    PRD §3.6: "that many `SessionCredit` records are granted in `AVAILABLE` status with an
    `expires_on` of this period's `period_end` plus 28 days"

    Design: Corner/cross_cutting_complexity_layers/scheduled_credit_expiry_on_clock_advance
    """
    set_clock("2026-06-01T00:00:00Z")
    client, therapist, match = active_match(state_code="CA")
    sub, cycle = subscription_with_paid_cycle(client["id"], weekly_credit_grant=1)
    # period_end = 2026-06-08; expires_on = +28 days = 2026-07-06.
    set_clock("2026-07-07T00:00:00Z")  # past expiry
    assert count_credits(client["id"], "EXPIRED") == 1, "credit should be EXPIRED"
    assert count_credits(client["id"], "AVAILABLE") == 0, "no AVAILABLE credit should remain"


# ==========================================================================
# Corner: billing-cycle session-credits listing (computed read)
# ==========================================================================
def test_billing_cycle_lists_granted_credit(api):
    """PRD §3.6: "that many `SessionCredit` records are granted in `AVAILABLE` status ... Each
    granted credit also records the `billing_cycle_id` of the cycle that produced it."

    Design: Corner/endpoints/computed_read_billing_cycle_session_credits_listing
    """
    set_clock("2026-06-01T00:00:00Z")
    client, therapist, match = active_match(state_code="CA")
    sub, cycle = subscription_with_paid_cycle(client["id"], weekly_credit_grant=1)
    items, meta = validate_paginated(
        api.list_billing_cycle_session_credits(cycle["id"], _client(client["id"]))
    )
    assert meta["total_count"] == 1, meta
