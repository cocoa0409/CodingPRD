"""Temporal-overlap guards: half-open subscription coverage windows and
closed-interval share-grant validity windows.
"""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated, get_success_data,
    setup_plan, set_clock, register_member, create_pending_subscription, activate,
    make_member_headers, setup_executed_will_with_share_grant, ADMIN,
)


# ─── Difficulty: resource_temporal_overlap / subscription_period_halfopen_overlap ─
def _member_with_active_sub1_and_pending_sub2():
    setup_plan(plan_tier="PLUS", base_price_cents=20000, included_document_types=["WILL"])
    set_clock("2026-06-01T00:00:00Z")
    member = register_member(email="overlap@example.com")
    hdr = make_member_headers(member["id"])
    sub1 = create_pending_subscription(member["id"], plan_tier="PLUS")
    activate(sub1["id"])
    sub2 = create_pending_subscription(member["id"], plan_tier="PLUS")
    return member, hdr, sub1, sub2


def test_activation_overlapping_period_rejected(api):
    """PRD §3.2: "Activation is refused with `ERR_SUBSCRIPTION_PERIOD_OVERLAP` (HTTP
    409) if the resulting half-open window `[current_period_start, current_period_end)`
    would overlap the coverage window of any other non-terminal subscription belonging
    to the same member; adjacency is allowed, so a new window whose start equals an
    existing window's end does not overlap."

    Design: Difficulty/resource_temporal_overlap/subscription_period_halfopen_overlap
    """
    member, hdr, sub1, sub2 = _member_with_active_sub1_and_pending_sub2()
    res = api.simulate_payment({"subscription_id": sub2["id"], "outcome": "SUCCEEDED"}, ADMIN)
    validate_error(res, "ERR_SUBSCRIPTION_PERIOD_OVERLAP")


def test_overlapping_subscription_stays_pending(api):
    """PRD §3.2: "Activation is refused with `ERR_SUBSCRIPTION_PERIOD_OVERLAP` (HTTP
    409) if the resulting half-open window `[current_period_start, current_period_end)`
    would overlap the coverage window of any other non-terminal subscription belonging
    to the same member".

    Design: Difficulty/resource_temporal_overlap/subscription_period_halfopen_overlap
    """
    member, hdr, sub1, sub2 = _member_with_active_sub1_and_pending_sub2()
    api.simulate_payment({"subscription_id": sub2["id"], "outcome": "SUCCEEDED"}, ADMIN)
    after = validate_success(api.get_subscription(sub2["id"], hdr), 200)
    assert after["status"] == "PENDING_PAYMENT"


# ─── Difficulty: resource_temporal_overlap / share_window_closed_overlap ─
def test_share_grant_overlapping_window_rejected(api):
    """PRD §3.11: "a new `ACTIVE` grant for the same `grantee_email` and `document_id`
    is rejected with `ERR_SHARE_WINDOW_OVERLAP` when its closed validity window from
    `created_at` to `expires_at` touches or overlaps the window of an existing `ACTIVE`
    grant for that same grantee and document — adjacency is not allowed here, so even
    touching windows conflict."

    Design: Difficulty/resource_temporal_overlap/share_window_closed_overlap
    """
    ctx = setup_executed_will_with_share_grant(
        grantee_email="g@example.com", expires_at="2027-01-01T00:00:00Z")
    doc, hdr = ctx["document"], ctx["headers"]
    res = api.create_share_grant(
        {"document_id": doc["id"], "grantee_email": "g@example.com",
         "scope": "FULL", "expires_at": "2027-03-01T00:00:00Z"}, hdr)
    validate_error(res, "ERR_SHARE_WINDOW_OVERLAP")


def test_share_grant_overlap_leaves_first_grant_active(api):
    """PRD §3.11: "a new `ACTIVE` grant for the same `grantee_email` and `document_id`
    is rejected with `ERR_SHARE_WINDOW_OVERLAP` when its closed validity window from
    `created_at` to `expires_at` touches or overlaps the window of an existing `ACTIVE`
    grant for that same grantee and document".

    Design: Difficulty/resource_temporal_overlap/share_window_closed_overlap
    """
    ctx = setup_executed_will_with_share_grant(
        grantee_email="g@example.com", expires_at="2027-01-01T00:00:00Z")
    doc, hdr, grant1 = ctx["document"], ctx["headers"], ctx["grant"]
    api.create_share_grant(
        {"document_id": doc["id"], "grantee_email": "g@example.com",
         "scope": "FULL", "expires_at": "2027-03-01T00:00:00Z"}, hdr)
    grants, _meta = validate_paginated(api.list_document_share_grants(doc["id"], hdr))
    first = [g for g in grants if g["id"] == grant1["id"]][0]
    assert first["status"] == "ACTIVE"
