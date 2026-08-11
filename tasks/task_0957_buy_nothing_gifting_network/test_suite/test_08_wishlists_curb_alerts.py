"""Wishlists (match / rematch / cancel) and curb alerts (half-open zone
capacity, sweep lifecycle, cancel rules) (PRD §2.11, §3.5, §3.6)."""
from test_helpers import (
    ApiErrorId,
    create_curb_alert,
    create_group,
    create_post,
    create_wishlist,
    join_group,
    make_member_headers,
    publish_post,
    register_member,
    set_clock,
    setup_group_with_members,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# Wishlist rematch cycle (Corner/state_machines)
# ---------------------------------------------------------------------------

def test_wishlist_rematch_cycle_on_post_withdraw(api):
    """PRD §3.2: "Publication is the moment wishlists come alive: every `ACTIVE`
    wishlist in the same group whose `keyword` appears as a case-insensitive
    substring of the post's `title`, and whose `category` is either unset or
    equal to the post's `category`, flips to `MATCHED` with `matched_post_id`
    pointing at the new post (§3.5)."
    PRD §3.5: "The bond is fragile by design — if the matched post is later
    withdrawn or expires, the wishlist drops back from `MATCHED` to `ACTIVE` and
    `matched_post_id` clears, resuming the wait for the next matching post."

    Design: Corner/state_machines/wishlist_rematch_cycle_on_post_withdraw
    """
    group, members = setup_group_with_members(
        [("wlm@x.com", "W"), ("wlg@x.com", "G")], name="Rematch Group", zip_code="98209"
    )
    w, g = members["wlm@x.com"], members["wlg@x.com"]
    wl = create_wishlist(w, group, keyword="lamp", category="HOUSEHOLD")
    post = create_post(g, group, title="Desk Lamp", category="HOUSEHOLD")
    publish_post(g, post)

    matched = validate_success(
        api.get_wishlist(wl["id"], make_member_headers(w["id"])), 200
    )
    assert matched["status"] == "MATCHED", (
        "publish must match the case-insensitive keyword substring ('lamp' in 'Desk Lamp')"
    )
    assert matched["matched_post_id"] == post["id"]

    validate_success(api.withdraw_gift_post(post["id"], make_member_headers(g["id"])), 200)
    rematched = validate_success(
        api.get_wishlist(wl["id"], make_member_headers(w["id"])), 200
    )
    assert rematched["status"] == "ACTIVE", "withdrawal of the matched post must cycle back"
    assert rematched["matched_post_id"] is None


def test_wishlist_cancel_twice_returns_not_active(api):
    """PRD §3.5: "A member may also cancel their own entry while it is `ACTIVE`
    or `MATCHED`, moving it to `CANCELLED`; attempting to cancel an entry
    already in a terminal state fails with `ERR_WISHLIST_NOT_ACTIVE`."

    Design: Corner/state_machines/wishlist_cancel_twice_returns_not_active
    """
    w = register_member("wc@x.com", "W")
    group = create_group("Cancel Wish Group", "98214")
    join_group(w, group)
    wl = create_wishlist(w, group, keyword="bike")
    validate_success(api.cancel_wishlist(wl["id"], make_member_headers(w["id"])), 200)
    res = api.cancel_wishlist(wl["id"], make_member_headers(w["id"]))
    validate_error(res, ApiErrorId.ERR_WISHLIST_NOT_ACTIVE, expected_status=409)
    after = validate_success(api.get_wishlist(wl["id"], make_member_headers(w["id"])), 200)
    assert after["status"] == "CANCELLED"


# ---------------------------------------------------------------------------
# Curb-alert zone capacity (Difficulty/resource_temporal_overlap)
# ---------------------------------------------------------------------------

def _setup_zone_with_three_alerts():
    """Zone ELM already holds three mutually overlapping live alerts on
    2026-05-12: [09:00,10:00), [09:30,10:30), [09:45,11:00)."""
    group, members = setup_group_with_members(
        [("zu@x.com", "U")], name="Zone Group", zip_code="98115"
    )
    u = members["zu@x.com"]
    create_curb_alert(u, group, zone="ELM",
                      starts_at="2026-05-12T09:00:00Z", ends_at="2026-05-12T10:00:00Z")
    create_curb_alert(u, group, zone="ELM",
                      starts_at="2026-05-12T09:30:00Z", ends_at="2026-05-12T10:30:00Z")
    create_curb_alert(u, group, zone="ELM",
                      starts_at="2026-05-12T09:45:00Z", ends_at="2026-05-12T11:00:00Z")
    return group, u


def test_curb_alert_fourth_overlapping_rejected(api):
    """PRD §3.6: "Creation is rejected with `ERR_CURB_ALERT_CAPACITY` (HTTP 409)
    whenever the new interval would overlap three or more existing `SCHEDULED`
    or `ACTIVE` alerts in the same group and zone — that is, at most three
    mutually overlapping live alerts are permitted per zone, and it is the
    fourth overlapping one that fails."

    Design: Difficulty/resource_temporal_overlap/curb_alert_zone_capacity_and_adjacency
    """
    group, u = _setup_zone_with_three_alerts()
    # [09:50, 10:05) overlaps all three live alerts -> the 4th overlapping fails.
    res = api.create_curb_alert(
        {"group_id": group["id"], "zone": "ELM",
         "starts_at": "2026-05-12T09:50:00Z", "ends_at": "2026-05-12T10:05:00Z"},
        make_member_headers(u["id"]),
    )
    validate_error(res, ApiErrorId.ERR_CURB_ALERT_CAPACITY, expected_status=409)


def test_curb_alert_exactly_adjacent_allowed(api):
    """PRD §2.11: "Curb-alert windows are **half-open intervals** — an alert
    occupies from its `starts_at` up to but not including its `ends_at` — and
    two such intervals overlap only when each starts before the other ends; two
    alerts that merely touch, one ending exactly when the other begins, do not
    overlap."

    Design: Difficulty/resource_temporal_overlap/curb_alert_zone_capacity_and_adjacency
    """
    group, u = _setup_zone_with_three_alerts()
    # [11:00, 12:00) touches [09:45, 11:00) at exactly 11:00 -> half-open adjacency
    # is not overlap, so only zero overlaps -> allowed.
    res = api.create_curb_alert(
        {"group_id": group["id"], "zone": "ELM",
         "starts_at": "2026-05-12T11:00:00Z", "ends_at": "2026-05-12T12:00:00Z"},
        make_member_headers(u["id"]),
    )
    alert = validate_success(res, 201)
    assert alert["status"] == "SCHEDULED", (
        "an exactly adjacent alert must be accepted (touching is not overlapping)"
    )


# ---------------------------------------------------------------------------
# Curb-alert sweep + cancel rules (Corner/state_machines, Corner/validations)
# ---------------------------------------------------------------------------

def test_curb_alert_sweep_activation_and_end(api):
    """PRD §3.6: "The epoch sweep animates the lifecycle: an alert flips from
    `SCHEDULED` to `ACTIVE` when the logical now reaches `starts_at`, and from
    `ACTIVE` to `ENDED` when it reaches `ends_at`."

    Design: Corner/state_machines/curb_alert_sweep_activation_and_end
    """
    group, members = setup_group_with_members(
        [("cau@x.com", "U")], name="Alert Group", zip_code="98213"
    )
    u = members["cau@x.com"]
    alert = create_curb_alert(u, group, zone="PINE",
                              starts_at="2026-05-10T10:00:00Z",
                              ends_at="2026-05-10T11:00:00Z")
    assert alert["status"] == "SCHEDULED"

    set_clock("2026-05-10T10:00:00Z")  # exactly starts_at
    read = validate_success(api.get_curb_alert(alert["id"], make_member_headers(u["id"])), 200)
    assert read["status"] == "ACTIVE", "the >= boundary flips SCHEDULED -> ACTIVE"

    set_clock("2026-05-10T11:00:00Z")  # exactly ends_at
    read = validate_success(api.get_curb_alert(alert["id"], make_member_headers(u["id"])), 200)
    assert read["status"] == "ENDED", "the >= boundary flips ACTIVE -> ENDED"


def test_curb_alert_inverted_range_returns_invalid_time_range(api):
    """PRD §3.6: "A member creates one with the `group_id`, a free-form `zone`
    label naming the block or area, a `starts_at`, and an `ends_at` that must be
    strictly later (`ERR_INVALID_TIME_RANGE` otherwise); the creator is recorded
    as `creator_id` and the alert is born `SCHEDULED`."

    Design: Corner/validations/curb_alert_inverted_range_returns_invalid_time_range
    """
    u = register_member("tru@x.com", "U")
    group = create_group("Range Group", "98227")
    join_group(u, group)
    res = api.create_curb_alert(
        {"group_id": group["id"], "zone": "ASH",
         "starts_at": "2026-05-12T10:00:00Z", "ends_at": "2026-05-12T09:00:00Z"},
        make_member_headers(u["id"]),
    )
    validate_error(res, ApiErrorId.ERR_INVALID_TIME_RANGE, expected_status=422)


def test_curb_alert_cancel_twice_returns_not_cancellable(api):
    """PRD §3.6: "Before it ends, the alert may be cancelled into `CANCELLED`
    either by its creator or by a moderator of the group; cancelling an alert
    already `ENDED` or `CANCELLED` fails with `ERR_CURB_ALERT_NOT_CANCELLABLE`."

    Design: Corner/state_machines/curb_alert_cancel_twice_returns_not_cancellable
    """
    u = register_member("ccu@x.com", "U")
    group = create_group("Cancel Alert Group", "98221")
    join_group(u, group)
    alert = create_curb_alert(u, group, zone="OAK")
    validate_success(api.cancel_curb_alert(alert["id"], make_member_headers(u["id"])), 200)
    res = api.cancel_curb_alert(alert["id"], make_member_headers(u["id"]))
    validate_error(res, ApiErrorId.ERR_CURB_ALERT_NOT_CANCELLABLE, expected_status=409)
