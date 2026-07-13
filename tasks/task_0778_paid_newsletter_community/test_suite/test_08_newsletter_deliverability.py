"""Newsletter sending and email deliverability posture.

Difficulty (queue A): bounce cascade to SUSPENDED; the inclusive 0.50 boundary;
send-window overlap rejection. Corner (queue B): send blocked while SUSPENDED.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    new_publication, new_post,
    setup_publication_with_two_free_members_sent,
    set_clock, reset_clock, get_pub,
)

CREATOR = TEST_USERS["creator_headers"]
ADMIN = TEST_USERS["admin_headers"]


# ---------------------------------------------------------------------------
# Difficulty A8 — bounce cascades bounce_count -> rate -> SUSPENDED
# ---------------------------------------------------------------------------

def test_bounce_drives_deliverability_suspended(api):
    """PRD §3.6: "A platform administrator records a hard bounce against a
    `member_id`, which sets that member's `email_bounced` to true, moves the
    member's `status` to `BOUNCED`, increments the publication's `bounce_count`
    by one, and recomputes `bounce_rate` and the deliverability posture against
    the breakpoints of §2.11."

    Design: Difficulty/transitive_cascade/email_bounce_cascades_bounce_count_to_deliverability_suspend
    """
    base = setup_publication_with_two_free_members_sent(api)
    api.record_bounce({"member_id": base["member_a"]["id"]}, ADMIN)
    pub = get_pub(api, base["pub_id"])
    assert pub["deliverability_status"] == "SUSPENDED"


def test_bounce_increments_count_and_rate(api):
    """PRD §2.11: "The publication tracks `sent_count` (cumulative newsletter
    recipient-sends) and `bounce_count` (cumulative hard bounces), and its
    `bounce_rate` is `bounce_count` divided by the greater of one and
    `sent_count`."

    Design: Difficulty/transitive_cascade/email_bounce_cascades_bounce_count_to_deliverability_suspend
    """
    base = setup_publication_with_two_free_members_sent(api)
    api.record_bounce({"member_id": base["member_a"]["id"]}, ADMIN)
    pub = get_pub(api, base["pub_id"])
    assert pub["bounce_count"] == 1
    assert pub["bounce_rate"] == 0.5


# ---------------------------------------------------------------------------
# Difficulty A11 — bounce_rate exactly 0.50 suspends (inclusive boundary)
# ---------------------------------------------------------------------------

def test_bounce_rate_exactly_half_is_suspended(api):
    """PRD §2.11: "the posture is `SUSPENDED` when the bounce rate is at least
    0.50 ... The 0.50 boundary is inclusive — a rate of exactly one half lands in
    `SUSPENDED`, not `THROTTLED`."

    Design: Difficulty/boundary_precision_check/bounce_rate_exactly_point_five_suspends_inclusive
    """
    base = setup_publication_with_two_free_members_sent(api)  # sent_count 2
    api.record_bounce({"member_id": base["member_a"]["id"]}, ADMIN)  # bounce 1 -> rate 0.50
    pub = get_pub(api, base["pub_id"])
    assert pub["deliverability_status"] == "SUSPENDED"


def test_bounce_rate_value_is_exactly_half(api):
    """PRD §2.11: "its `bounce_rate` is `bounce_count` divided by the greater of
    one and `sent_count`."

    Design: Difficulty/boundary_precision_check/bounce_rate_exactly_point_five_suspends_inclusive
    """
    base = setup_publication_with_two_free_members_sent(api)
    api.record_bounce({"member_id": base["member_a"]["id"]}, ADMIN)
    pub = get_pub(api, base["pub_id"])
    assert pub["bounce_rate"] == 0.5, f"expected 0.5, got {pub['bounce_rate']}"


# ---------------------------------------------------------------------------
# Difficulty A16 — overlapping send-throttle windows rejected
# ---------------------------------------------------------------------------

def _pub_with_two_newsletters_first_sent(api):
    reset_clock(api)
    pub = new_publication(api)
    p1 = new_post(api, pub["id"], publish=False, content_type="NEWSLETTER", title="N1", body="B1")
    p2 = new_post(api, pub["id"], publish=False, content_type="NEWSLETTER", title="N2", body="B2")
    validate_success(api.send_post(p1["id"], CREATOR), expected_status=200)  # window [00:00,01:00)
    set_clock(api, "2026-03-01T00:30:00Z")
    return pub, p1, p2


def test_send_window_overlap_rejected(api):
    """PRD §3.6: "A send is rejected with `ERR_SEND_WINDOW_CONFLICT` when its
    window would overlap that of a prior send within the sixty-minute throttle
    window ..."

    Design: Difficulty/resource_temporal_overlap/newsletter_send_window_overlap_rejected
    """
    _, _, p2 = _pub_with_two_newsletters_first_sent(api)
    resp = api.send_post(p2["id"], CREATOR)
    validate_error(resp, ApiErrorId.ERR_SEND_WINDOW_CONFLICT.value)


def test_send_window_overlap_leaves_post_unsent(api):
    """PRD §3.6: "Sending a newsletter advances a post to `SENT`, stamps a
    throttle window, and emails the eligible audience."

    Design: Difficulty/resource_temporal_overlap/newsletter_send_window_overlap_rejected
    """
    pub, _, p2 = _pub_with_two_newsletters_first_sent(api)
    api.send_post(p2["id"], CREATOR)
    post_after = validate_success(api.get_post_content(p2["id"], CREATOR), expected_status=200)
    assert post_after["status"] == "DRAFT", "a rejected send must not advance the post to SENT"


# ---------------------------------------------------------------------------
# Corner — send blocked while deliverability is SUSPENDED
# ---------------------------------------------------------------------------

def test_send_newsletter_while_suspended_rejected(api):
    """PRD §3.6: "and is rejected with `ERR_DELIVERABILITY_SUSPENDED` when the
    publication's `deliverability_status` is `SUSPENDED`."

    Design: Corner/validations/send_newsletter_deliverability_suspended_returns_409
    """
    base = setup_publication_with_two_free_members_sent(api)
    api.record_bounce({"member_id": base["member_a"]["id"]}, ADMIN)  # -> SUSPENDED
    p2 = new_post(api, base["pub_id"], publish=False, content_type="NEWSLETTER",
                  title="N2", body="B2")
    resp = api.send_post(p2["id"], CREATOR)
    validate_error(resp, ApiErrorId.ERR_DELIVERABILITY_SUSPENDED.value)
