"""Hot-work permits: issuance constraints, half-open window overlap, fire
watch, validation ordering inside the business-safety rules, terminal
lockdown, and the hot_work_in_progress counter."""
from test_helpers import (
    ApiErrorId,
    assert_hot_work_permit,
    create_permit,
    create_site,
    set_clock,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS
from test_helpers.test_users import (
    make_hot_work_performer_headers,
    make_safety_manager_headers,
)

ENGINEER = TEST_USERS["compliance_engineer_headers"]
SAFETY = TEST_USERS["safety_manager_headers"]


def test_voided_permit_cannot_start(api):
    """PRD §3.6: "A `SafetyManager` may void a permit before it starts; voiding
    moves `ISSUED → VOIDED` and requires the acting `X-User-ID` to equal the
    permit's `issuer_id`. The terminal `VOIDED` status records that the permit
    was cancelled administratively rather than executed or expired."
    PRD §2.10: "**State-machine validity**: the target resource's current state
    allows the requested transition (else `ERR_INVALID_STATE`)."

    Design: Corner/state_machines/hotwork_permit_terminal_lockdown
    """
    set_clock("2026-05-01T00:00:00Z")
    site = create_site(insurer_id="FM-1")
    permit = create_permit(site["id"], "2026-05-01T00:00:00Z",
                           "2026-05-01T04:00:00Z", fire_watch_minutes_after=30,
                           issuer_id="sm-1", performer_id="hp-1")

    voided = validate_success(
        api.void_hot_work_permit(site["id"], permit["id"],
                                 make_safety_manager_headers("sm-1")), 200)
    assert voided["status"] == "VOIDED"

    res = api.start_hot_work_permit(site["id"], permit["id"],
                                    make_hot_work_performer_headers("hp-1"))
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)

    after = validate_success(
        api.get_hot_work_permit(site["id"], permit["id"], SAFETY), 200)
    assert after["status"] == "VOIDED"


def test_permit_window_over_24h_rejected(api):
    """PRD §3.6: "The window itself must be well-formed: `valid_to` must be
    strictly later than `valid_from`, and `valid_to` must not exceed
    `valid_from` plus 24 hours; a malformed window is rejected with
    `ERR_PERMIT_WINDOW_INVALID` (HTTP 422)."

    Design: Corner/validations/permit_window_invalid_over_24h
    """
    site = create_site(insurer_id="FM-1")
    res = api.create_hot_work_permit(
        site["id"],
        {
            "work_description": "W",
            "issuer_id": "sm-1",
            "performer_id": "hp-1",
            "valid_from": "2026-05-01T00:00:00Z",
            "valid_to": "2026-05-03T00:00:00Z",
            "fire_watch_minutes_after": 30,
        },
        SAFETY)
    validate_error(res, ApiErrorId.ERR_PERMIT_WINDOW_INVALID)


def test_fire_watch_below_30_rejected(api):
    """PRD §3.6: "The fire-watch duration must be at least 30 minutes; a
    shorter value is rejected with `ERR_FIRE_WATCH_TOO_SHORT` (HTTP 422)."

    Design: Corner/validations/permit_fire_watch_below_30_rejected
    """
    site = create_site(insurer_id="FM-1")
    res = api.create_hot_work_permit(
        site["id"],
        {
            "work_description": "W",
            "issuer_id": "sm-1",
            "performer_id": "hp-1",
            "valid_from": "2026-05-01T00:00:00Z",
            "valid_to": "2026-05-01T04:00:00Z",
            "fire_watch_minutes_after": 29,
        },
        SAFETY)
    validate_error(res, ApiErrorId.ERR_FIRE_WATCH_TOO_SHORT)

    ok = api.create_hot_work_permit(
        site["id"],
        {
            "work_description": "W",
            "issuer_id": "sm-1",
            "performer_id": "hp-1",
            "valid_from": "2026-05-01T00:00:00Z",
            "valid_to": "2026-05-01T04:00:00Z",
            "fire_watch_minutes_after": 30,
        },
        SAFETY)
    permit = validate_success(ok, 201)
    assert_hot_work_permit(permit)


def test_window_inactive_beats_overlap_error(api):
    """PRD §2.10: "the server evaluates them in a fixed priority order so that
    the error returned is deterministic across implementations".
    PRD §2.10: "**Business safety rules**: vent adequacy at commission,
    filter-change-due at return-to-service, hot-work window active at start,
    fire watch elapsed at close, no permit overlap, combustible dust linked
    before DHA approval, segregation-of-duties constraints."
    PRD §3.6: "the current clock must lie within `[valid_from, valid_to)` —
    that is, greater than or equal to `valid_from` and strictly earlier than
    `valid_to` (else `ERR_PERMIT_WINDOW_INACTIVE`, HTTP 422)".

    Permit B's window has not yet opened (so its window is inactive) while an
    IN_PROGRESS permit A overlaps it: the window-inactive rule is enumerated
    ahead of the overlap rule, so ERR_PERMIT_WINDOW_INACTIVE wins. B is still
    ISSUED (the clock has not passed its `valid_to`, so no auto-expiry), which
    keeps the state-machine check at §2.10 step 4 silent and lets the
    business-safety ordering decide the error.

    Design: Difficulty/priority_pair_validation_conflict/permit_window_inactive_vs_permit_overlap_business_safety_ordering
    """
    set_clock("2026-05-01T00:00:00Z")
    site = create_site()
    perm_a = create_permit(site["id"], "2026-05-01T00:00:00Z",
                           "2026-05-01T08:00:00Z", fire_watch_minutes_after=60,
                           work_description="A", performer_id="hp-1")
    perm_b = create_permit(site["id"], "2026-05-01T04:00:00Z",
                           "2026-05-01T12:00:00Z", fire_watch_minutes_after=60,
                           work_description="B", performer_id="hp-2")
    validate_success(
        api.start_hot_work_permit(site["id"], perm_a["id"],
                                  make_hot_work_performer_headers("hp-1")), 200)

    set_clock("2026-05-01T02:00:00Z")
    res = api.start_hot_work_permit(site["id"], perm_b["id"],
                                    make_hot_work_performer_headers("hp-2"))
    body = res.json()
    assert body["data"]["error_id"] == "ERR_PERMIT_WINDOW_INACTIVE"
    assert body["data"]["error_id"] != "ERR_PERMIT_OVERLAP"
    assert res.status_code == 422


def test_overlap_rejected_when_window_active(api):
    """PRD §3.6: "no *other* HotWorkPermit on the same Site may already be in
    `IN_PROGRESS` with a window overlapping this one's (else
    `ERR_PERMIT_OVERLAP`, HTTP 422)".

    With the candidate permit's window currently active, the overlap rule is
    the one that fires.

    Design: Difficulty/priority_pair_validation_conflict/permit_window_inactive_vs_permit_overlap_business_safety_ordering
    """
    set_clock("2026-05-01T00:00:00Z")
    site = create_site()
    perm_a = create_permit(site["id"], "2026-05-01T00:00:00Z",
                           "2026-05-01T04:00:00Z", fire_watch_minutes_after=60,
                           work_description="A", performer_id="hp-1")
    perm_b = create_permit(site["id"], "2026-05-01T02:00:00Z",
                           "2026-05-01T06:00:00Z", fire_watch_minutes_after=60,
                           work_description="B", performer_id="hp-2")
    validate_success(
        api.start_hot_work_permit(site["id"], perm_a["id"],
                                  make_hot_work_performer_headers("hp-1")), 200)

    set_clock("2026-05-01T03:00:00Z")
    res = api.start_hot_work_permit(site["id"], perm_b["id"],
                                    make_hot_work_performer_headers("hp-2"))
    validate_error(res, ApiErrorId.ERR_PERMIT_OVERLAP)


def test_overlapping_permit_start_rejected(api):
    """PRD §3.6: "no *other* HotWorkPermit on the same Site may already be in
    `IN_PROGRESS` with a window overlapping this one's (else
    `ERR_PERMIT_OVERLAP`, HTTP 422)".

    Permit C's window [03:00, 07:00) intersects IN_PROGRESS permit A's window
    [00:00, 04:00).

    Design: Difficulty/resource_temporal_overlap/hot_work_permit_window_half_open_overlap_rejection
    """
    set_clock("2026-05-01T00:00:00Z")
    site = create_site()
    perm_a = create_permit(site["id"], "2026-05-01T00:00:00Z",
                           "2026-05-01T04:00:00Z", fire_watch_minutes_after=30,
                           work_description="A", performer_id="hp-1")
    perm_c = create_permit(site["id"], "2026-05-01T03:00:00Z",
                           "2026-05-01T07:00:00Z", fire_watch_minutes_after=30,
                           work_description="C", performer_id="hp-3")
    validate_success(
        api.start_hot_work_permit(site["id"], perm_a["id"],
                                  make_hot_work_performer_headers("hp-1")), 200)

    set_clock("2026-05-01T03:00:00Z")
    res = api.start_hot_work_permit(site["id"], perm_c["id"],
                                    make_hot_work_performer_headers("hp-3"))
    validate_error(res, ApiErrorId.ERR_PERMIT_OVERLAP)


def test_boundary_adjacent_permit_allowed(api):
    """PRD §3.6: "a `valid_from` timestamp marking the inclusive start of the
    permit window, a `valid_to` timestamp marking the exclusive end (the
    window is half-open: `[valid_from, valid_to)`)".
    PRD §3.6: "no *other* HotWorkPermit on the same Site may already be in
    `IN_PROGRESS` with a window overlapping this one's (else
    `ERR_PERMIT_OVERLAP`, HTTP 422)".

    Permit B's window [04:00, 08:00) touches IN_PROGRESS permit A's window
    [00:00, 04:00) only at the excluded endpoint, so under half-open semantics
    the windows do not overlap and the start succeeds.

    Design: Difficulty/resource_temporal_overlap/hot_work_permit_window_half_open_overlap_rejection
    """
    set_clock("2026-05-01T00:00:00Z")
    site = create_site()
    perm_a = create_permit(site["id"], "2026-05-01T00:00:00Z",
                           "2026-05-01T04:00:00Z", fire_watch_minutes_after=30,
                           work_description="A", performer_id="hp-1")
    perm_b = create_permit(site["id"], "2026-05-01T04:00:00Z",
                           "2026-05-01T08:00:00Z", fire_watch_minutes_after=30,
                           work_description="B", performer_id="hp-2")
    validate_success(
        api.start_hot_work_permit(site["id"], perm_a["id"],
                                  make_hot_work_performer_headers("hp-1")), 200)

    set_clock("2026-05-01T04:00:00Z")
    started = validate_success(
        api.start_hot_work_permit(site["id"], perm_b["id"],
                                  make_hot_work_performer_headers("hp-2")), 200)
    assert started["status"] == "IN_PROGRESS"

    after = validate_success(
        api.get_hot_work_permit(site["id"], perm_b["id"], SAFETY), 200)
    assert after["status"] == "IN_PROGRESS"


def test_fresh_site_hot_work_counter_zero(api):
    """PRD §3.1: "The new Site is born in `CONDITIONAL` posture with all three
    derived counters at zero: `open_critical_findings` counts
    `InspectionFinding` rows at the site with status `OPEN` and severity
    `CRITICAL`; `open_overdue_housekeeping` counts `HousekeepingAudit` rows at
    the site with status `OVERDUE`; `hot_work_in_progress` counts
    `HotWorkPermit` rows at the site with status `IN_PROGRESS`."

    Design: Difficulty/boundary_precision_check/hot_work_permit_empty_collection_zero_count
    """
    set_clock("2026-05-01T00:00:00Z")
    site = create_site()
    create_permit(site["id"], "2026-05-01T00:00:00Z", "2026-05-01T02:00:00Z",
                  fire_watch_minutes_after=30, work_description="W",
                  performer_id="hp-1")

    before = validate_success(api.get_site(site["id"], ENGINEER), 200)
    assert before["hot_work_in_progress"] == 0


def test_hot_work_counter_returns_to_zero_after_close(api):
    """PRD §3.6: "A successful start increments the Site's
    `hot_work_in_progress` counter by 1, recomputes posture, and increments
    the Site's `version` by 1."
    PRD §3.6: "On close the Site's `hot_work_in_progress` decrements by 1 and
    posture is recomputed."
    PRD §3.6: "The transition requires that the current clock be at or past
    `valid_to` plus `fire_watch_minutes_after` minutes; a close attempted
    earlier is rejected with `ERR_FIRE_WATCH_INCOMPLETE` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/hot_work_permit_empty_collection_zero_count
    """
    set_clock("2026-05-01T00:00:00Z")
    site = create_site()
    permit = create_permit(site["id"], "2026-05-01T00:00:00Z",
                           "2026-05-01T02:00:00Z", fire_watch_minutes_after=30,
                           work_description="W", performer_id="hp-1")

    initial = validate_success(api.get_site(site["id"], ENGINEER), 200)
    assert initial["hot_work_in_progress"] == 0

    validate_success(
        api.start_hot_work_permit(site["id"], permit["id"],
                                  make_hot_work_performer_headers("hp-1")), 200)
    during = validate_success(api.get_site(site["id"], ENGINEER), 200)
    assert during["hot_work_in_progress"] == 1

    set_clock("2026-05-01T03:00:00Z")
    closed = validate_success(
        api.close_hot_work_permit(site["id"], permit["id"],
                                  make_hot_work_performer_headers("hp-1")), 200)
    assert closed["status"] == "CLOSED"
    after = validate_success(api.get_site(site["id"], ENGINEER), 200)
    assert after["hot_work_in_progress"] == 0


def test_hot_work_counter_invariant_single_cycle(api):
    """PRD §3.6: "A successful start increments the Site's
    `hot_work_in_progress` counter by 1, recomputes posture, and increments
    the Site's `version` by 1."
    PRD §3.6: "On close the Site's `hot_work_in_progress` decrements by 1 and
    posture is recomputed."

    A matched (start, close) pair conserves the counter: final == initial.

    Design: Difficulty/compensating_invariant/hot_work_counter_invariant_under_start_close
    """
    set_clock("2026-05-01T00:00:00Z")
    site = create_site()
    before = validate_success(api.get_site(site["id"], ENGINEER), 200)
    assert before["hot_work_in_progress"] == 0

    permit = create_permit(site["id"], "2026-05-01T00:00:00Z",
                           "2026-05-01T01:00:00Z", fire_watch_minutes_after=30,
                           work_description="W1", performer_id="hp-1")
    validate_success(
        api.start_hot_work_permit(site["id"], permit["id"],
                                  make_hot_work_performer_headers("hp-1")), 200)
    set_clock("2026-05-01T02:00:00Z")
    validate_success(
        api.close_hot_work_permit(site["id"], permit["id"],
                                  make_hot_work_performer_headers("hp-1")), 200)

    after = validate_success(api.get_site(site["id"], ENGINEER), 200)
    assert after["hot_work_in_progress"] == 0
    assert after["hot_work_in_progress"] == before["hot_work_in_progress"]


def test_hot_work_counter_invariant_three_cycles(api):
    """PRD §3.6: "A successful start increments the Site's
    `hot_work_in_progress` counter by 1, recomputes posture, and increments
    the Site's `version` by 1."
    PRD §3.6: "On close the Site's `hot_work_in_progress` decrements by 1 and
    posture is recomputed."

    Across three sequential (start, close) cycles the counter rises to 1 and
    returns to the initial value each time.

    Design: Difficulty/compensating_invariant/hot_work_counter_invariant_under_start_close
    """
    set_clock("2026-05-01T00:00:00Z")
    site = create_site()
    initial = validate_success(api.get_site(site["id"], ENGINEER), 200)
    assert initial["hot_work_in_progress"] == 0

    windows = [
        ("2026-05-01T00:00:00Z", "2026-05-01T01:00:00Z",
         "2026-05-01T00:00:00Z", "2026-05-01T01:30:00Z"),
        ("2026-05-01T02:00:00Z", "2026-05-01T03:00:00Z",
         "2026-05-01T02:00:00Z", "2026-05-01T03:30:00Z"),
        ("2026-05-01T04:00:00Z", "2026-05-01T05:00:00Z",
         "2026-05-01T04:00:00Z", "2026-05-01T05:30:00Z"),
    ]
    for i, (valid_from, valid_to, start_at, close_at) in enumerate(windows):
        permit = create_permit(site["id"], valid_from, valid_to,
                               fire_watch_minutes_after=30,
                               work_description=f"W{i + 1}",
                               performer_id="hp-1")
        set_clock(start_at)
        validate_success(
            api.start_hot_work_permit(
                site["id"], permit["id"],
                make_hot_work_performer_headers("hp-1")), 200)
        during = validate_success(api.get_site(site["id"], ENGINEER), 200)
        assert during["hot_work_in_progress"] == 1, (
            f"cycle {i + 1}: counter must be 1 while the permit is IN_PROGRESS")

        set_clock(close_at)
        validate_success(
            api.close_hot_work_permit(
                site["id"], permit["id"],
                make_hot_work_performer_headers("hp-1")), 200)
        after = validate_success(api.get_site(site["id"], ENGINEER), 200)
        assert after["hot_work_in_progress"] == 0, (
            f"cycle {i + 1}: counter must return to 0 after close")

    final = validate_success(api.get_site(site["id"], ENGINEER), 200)
    assert final["hot_work_in_progress"] == initial["hot_work_in_progress"]
