"""Moderation pipeline: report review workflow, strike thresholds, suspension
and ban cascades, overturns, and sanction-based content restrictions
(PRD §2.10, §3.7, §3.8)."""
from test_helpers import (
    ApiErrorId,
    apply_strike,
    assert_iso_instant,
    file_report,
    find_active_strike_action,
    get_member,
    join_group,
    create_group,
    make_member_headers,
    register_member,
    resolve_with_strike,
    setup_group_with_members,
    validate_error,
    validate_paginated,
    validate_success,
)


# ---------------------------------------------------------------------------
# Report workflow invalid transitions + DISMISS resolution
# ---------------------------------------------------------------------------

def test_report_start_review_twice_returns_not_open(api, admin_headers):
    """PRD §3.7: "Review begins when a moderator of the report's group (or a
    `PlatformAdmin`) starts review, moving the report from `OPEN` to
    `UNDER_REVIEW` and stamping `reviewed_by` with the actor — a member id for
    a moderator, the opaque operator id for an administrator; a report not in
    `OPEN` rejects the attempt with `ERR_REPORT_NOT_OPEN`."

    Design: Corner/state_machines/report_start_review_twice_returns_not_open
    """
    r = register_member("srr@x.com", "R")
    t = register_member("srt@x.com", "T")
    group = create_group("Review Group", "98218")
    join_group(r, group)
    rp = file_report(r, group, t["id"])
    validate_success(api.start_review_report(rp["id"], admin_headers), 200)
    res = api.start_review_report(rp["id"], admin_headers)
    validate_error(res, ApiErrorId.ERR_REPORT_NOT_OPEN, expected_status=409)


def test_resolve_open_report_returns_not_under_review(api, admin_headers):
    """PRD §3.7: "Resolution then takes one of two shapes, expressed through the
    `resolution` field, and any resolve attempted on a report not `UNDER_REVIEW`
    fails with `ERR_REPORT_NOT_UNDER_REVIEW`."

    Design: Corner/state_machines/resolve_open_report_returns_not_under_review
    """
    r = register_member("ror@x.com", "R")
    t = register_member("rot@x.com", "T")
    group = create_group("Resolve Group", "98219")
    join_group(r, group)
    rp = file_report(r, group, t["id"])
    res = api.resolve_report(rp["id"], {"resolution": "DISMISS"}, admin_headers)
    validate_error(res, ApiErrorId.ERR_REPORT_NOT_UNDER_REVIEW, expected_status=409)
    after = validate_success(api.get_report(rp["id"], admin_headers), 200)
    assert after["status"] == "OPEN"


def test_report_dismiss_creates_no_moderation_action(api, admin_headers):
    """PRD §3.7: "Resolving with `DISMISS` moves the report to
    `RESOLVED_DISMISSED` with no further action."
    PRD §3.7: "Resolving with `ACTION` moves the report to `RESOLVED_ACTION` and
    requires an `action_type` — `WARNING`, `STRIKE`, or `CONTENT_REMOVAL` — and
    creates a `ModerationAction` whose `member_id` subject is derived from the
    report target: the target itself for a `MEMBER` report, the post's
    `giver_id` for a `GIFT_POST` report, the claim's `claimer_id` for a `CLAIM`
    report, and the alert's `creator_id` for a `CURB_ALERT` report."

    Design: Corner/state_machines/report_dismiss_creates_no_moderation_action
    """
    group, members = setup_group_with_members(
        [("drr@x.com", "R"), ("drt@x.com", "T")], name="Dismiss Group", zip_code="98210"
    )
    r, t = members["drr@x.com"], members["drt@x.com"]
    rp = file_report(r, group, t["id"], category="OTHER")
    validate_success(api.start_review_report(rp["id"], admin_headers), 200)
    res = api.resolve_report(rp["id"], {"resolution": "DISMISS"}, admin_headers)
    resolved = validate_success(res, 200)
    assert resolved["status"] == "RESOLVED_DISMISSED"
    assert_iso_instant(resolved["resolved_at"], "2026-05-10T09:00:00Z")
    data, meta = validate_paginated(
        api.list_moderation_actions(admin_headers, params={"report_id": rp["id"]})
    )
    assert data == [], "DISMISS must not create any moderation action"
    assert meta["total_count"] == 0
    t_after = get_member(t["id"], make_member_headers(t["id"]))
    assert t_after["active_strike_points"] == 0


def test_overturn_twice_returns_not_overturnable(api, admin_headers):
    """PRD §3.7: "A `PlatformAdmin` may instead overturn an `ACTIVE` action into
    `OVERTURNED` — attempting to overturn one in any other state fails with
    `ERR_ACTION_NOT_OVERTURNABLE` — after which the subject's points are
    recomputed"

    Design: Corner/state_machines/overturn_twice_returns_not_overturnable
    """
    t = register_member("ott@x.com", "T")
    r = register_member("otr@x.com", "R")
    group = create_group("Overturn Group", "98220")
    join_group(t, group)
    join_group(r, group)
    apply_strike(r, group, t, severity_points=1)
    action = find_active_strike_action(t)
    validate_success(api.overturn_moderation_action(action["id"], admin_headers), 200)
    res = api.overturn_moderation_action(action["id"], admin_headers)
    validate_error(res, ApiErrorId.ERR_ACTION_NOT_OVERTURNABLE, expected_status=409)
    after = validate_success(api.get_moderation_action(action["id"], admin_headers), 200)
    assert after["status"] == "OVERTURNED"


# ---------------------------------------------------------------------------
# Strike boundary (Difficulty/boundary_precision_check)
# ---------------------------------------------------------------------------

def _setup_member_with_two_strikes():
    """X carries 2 active strike points; a third OPEN report awaits resolution."""
    group, members = setup_group_with_members(
        [("bx@x.com", "X"), ("br@x.com", "R")], name="Boundary Group", zip_code="98110"
    )
    x, r = members["bx@x.com"], members["br@x.com"]
    apply_strike(r, group, x, severity_points=1)
    apply_strike(r, group, x, severity_points=1)
    rp3 = file_report(r, group, x["id"], category="OTHER")
    return group, x, r, rp3


def test_two_strike_points_keep_member_active(api):
    """PRD §2.10: "The boundaries are pinned: at 3 or more points (3 exactly
    included) but fewer than 6, the member is suspended for 14 days; at 6 or
    more points, the member is banned."

    Design: Difficulty/boundary_precision_check/third_strike_point_exactly_suspends
    """
    group, x, r, rp3 = _setup_member_with_two_strikes()
    m = get_member(x["id"], make_member_headers(x["id"]))
    assert m["active_strike_points"] == 2
    assert m["status"] == "ACTIVE", "2 < 3 must NOT suspend"


def test_third_strike_point_exactly_suspends(api, admin_headers):
    """PRD §2.10: "The boundaries are pinned: at 3 or more points (3 exactly
    included) but fewer than 6, the member is suspended for 14 days; at 6 or
    more points, the member is banned."
    PRD §3.8: "When a strike application, an overturn, or the sweep's
    strike-expiry recomputation leaves the total at 3 or more but fewer than 6 —
    the boundary at exactly 3 included — the member moves from `ACTIVE` to
    `SUSPENDED`, `suspension_ends_at` is set 14 days out, and the suspension
    cascade fires"

    Design: Difficulty/boundary_precision_check/third_strike_point_exactly_suspends
    """
    group, x, r, rp3 = _setup_member_with_two_strikes()
    resolve_with_strike(rp3, severity_points=1)
    m = get_member(x["id"], make_member_headers(x["id"]))
    assert m["active_strike_points"] == 3
    assert m["status"] == "SUSPENDED", "the boundary fires at exactly 3 points (>=, not >)"
    assert_iso_instant(
        m["suspension_ends_at"], "2026-05-24T09:00:00Z",
        f"resolve instant 2026-05-10T09:00:00Z + 14 days, got {m['suspension_ends_at']}",
    )


# ---------------------------------------------------------------------------
# Overturn reinstatement (Corner/rbac)
# ---------------------------------------------------------------------------

def test_overturn_strike_reinstates_suspended_member(api, admin_headers):
    """PRD §3.7: "A `PlatformAdmin` may instead overturn an `ACTIVE` action into
    `OVERTURNED` — attempting to overturn one in any other state fails with
    `ERR_ACTION_NOT_OVERTURNABLE` — after which the subject's points are
    recomputed: a suspended subject falling below 3 points returns to `ACTIVE`
    with `suspension_ends_at` cleared, and a banned subject falling below 6
    points is restored to `SUSPENDED` when 3 or more points remain or directly
    to `ACTIVE` when fewer than 3 remain."

    Design: Corner/rbac/overturn_strike_reinstates_suspended_member
    """
    group, members = setup_group_with_members(
        [("ovt@x.com", "T"), ("ovr@x.com", "R")], name="Reinstate Group", zip_code="98237"
    )
    t, r = members["ovt@x.com"], members["ovr@x.com"]
    apply_strike(r, group, t, severity_points=3, category="SAFETY")
    before = get_member(t["id"], make_member_headers(t["id"]))
    assert before["status"] == "SUSPENDED"
    assert_iso_instant(before["suspension_ends_at"], "2026-05-24T09:00:00Z")

    action = find_active_strike_action(t)
    overturned = validate_success(
        api.overturn_moderation_action(action["id"], admin_headers), 200
    )
    assert overturned["status"] == "OVERTURNED"
    after = get_member(t["id"], make_member_headers(t["id"]))
    assert after["status"] == "ACTIVE", "points 3 -> 0 must reinstate the member"
    assert after["active_strike_points"] == 0
    assert after["suspension_ends_at"] is None


def test_banned_member_cannot_create_post(api):
    """PRD §2.10: "The boundaries are pinned: at 3 or more points (3 exactly
    included) but fewer than 6, the member is suspended for 14 days; at 6 or
    more points, the member is banned."
    PRD §3.8: "And while sanctions stand, the member standing rule of §2.6 bites
    — a `SUSPENDED` member attempting any content-creating operation (joining
    groups, posting gifts, claiming, proposing pickups, wishing, posting curb
    alerts, filing reports) is rejected with `ERR_MEMBER_SUSPENDED`, and a
    `BANNED` member with `ERR_MEMBER_BANNED`."

    Design: Corner/validations/banned_member_cannot_create_post
    """
    group, members = setup_group_with_members(
        [("bnb@x.com", "B"), ("bnr@x.com", "R")], name="Ban Group", zip_code="98231"
    )
    b, r = members["bnb@x.com"], members["bnr@x.com"]
    apply_strike(r, group, b, severity_points=3, category="SAFETY")
    apply_strike(r, group, b, severity_points=3, category="HARASSMENT")
    b_after = get_member(b["id"], make_member_headers(b["id"]))
    assert b_after["status"] == "BANNED", "6 >= 6 must ban the member"

    from test_helpers import create_gift_post_payload
    res = api.create_gift_post(
        create_gift_post_payload(group["id"], title="Couch", category="FURNITURE"),
        make_member_headers(b["id"]),
    )
    validate_error(res, ApiErrorId.ERR_MEMBER_BANNED, expected_status=403)
