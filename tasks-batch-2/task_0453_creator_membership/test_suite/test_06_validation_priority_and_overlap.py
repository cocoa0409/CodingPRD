"""Validation precedence pairings, resource-overlap exclusivity, the messaging
gate's pledge dependency, and the win-back redemption window boundary.

Covers the priority-pair, resource-temporal-overlap, cross-entity-dependency
(conversation), and win-back-window-boundary depth instances plus the messaging
and content-gate corner instances.
"""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    make_creator_headers,
    make_patron_headers,
    make_platform_admin_headers,
    ApiErrorId,
    BOGUS_UUID,
    set_clock,
    create_creator,
    create_published_tier,
    create_patron,
    create_active_pledge,
    setup_active_membership,
    setup_cancelled_lapsed_pledge,
    setup_lapsed_pledge_with_offer,
    open_conversation,
)

ADMIN = make_platform_admin_headers()


def test_closed_conversation_state_check_beats_messaging_gate(api):
    """PRD §2.6: "the order is: ... seventh, the target resource being in a state
    that permits the requested transition; ... Domain-specific business rules —
    membership-interval exclusivity, tier-rank uniqueness, messaging gates,
    content gates, win-back windows, billing-model matching, payout availability,
    and optimistic-concurrency checks — are evaluated after these foundational
    checks".
    PRD §3.8: "Messages may be posted only to an `OPEN` conversation; posting to,
    or closing, a conversation that is already `CLOSED` is rejected with
    `ERR_CONVERSATION_CLOSED`."

    Design: Difficulty/priority_pair_validation_conflict/ppvc_state_vs_messaging_gate
    """
    s = setup_active_membership(clock="2026-06-16T00:00:00Z", monthly_fee_cents=1500)
    conv = open_conversation(s["creator"]["id"], s["patron"]["id"])
    # Close it, then cancel the pledge so the patron is no longer ACTIVE/PAUSED.
    validate_success(api_client.close_conversation(conv["id"], make_creator_headers(s["creator"]["id"])), 200)
    validate_success(api_client.cancel_pledge(s["pledge"]["id"], make_patron_headers(s["patron"]["id"])), 200)

    resp = api_client.create_message(
        {"conversation_id": conv["id"], "body": "hi"}, make_patron_headers(s["patron"]["id"]),
    )
    # State (priority 7) wins over the messaging-gate safety check.
    validate_error(resp, ApiErrorId.ERR_CONVERSATION_CLOSED.value)


def test_nonexistent_post_existence_beats_content_gate(api):
    """PRD §2.6: "the order is: ... fourth, existence of path-supplied
    identifiers; ... Domain-specific business rules — ... content gates ... — are
    evaluated after these foundational checks".
    PRD §2.5: "a post `ERR_POST_NOT_FOUND`".

    Design: Difficulty/priority_pair_validation_conflict/ppvc_existence_vs_content_gate
    """
    # A patron with a real low-rank pledge, but the access target is a bogus id.
    s = setup_active_membership(clock="2026-06-16T00:00:00Z", monthly_fee_cents=800)
    resp = api_client.request_post_access(
        BOGUS_UUID, {"patron_id": s["patron"]["id"]}, make_patron_headers(s["patron"]["id"]),
    )
    # Existence (priority 4) wins over the content-gate (priority 11).
    validate_error(resp, ApiErrorId.ERR_POST_NOT_FOUND.value)


def test_membership_interval_exclusivity_rejects_second_pledge(api):
    """PRD §3.2: "A patron may have at most one pledge to a given creator whose
    `lifecycle_status` is `DRAFT`, `ACTIVE`, or `PAUSED` — that is, at most one
    open membership interval. Attempting to create a second pledge to the same
    creator while such an interval is occupied is rejected with
    `ERR_DUPLICATE_PLEDGE`."

    Design: Difficulty/resource_temporal_overlap/rto_membership_interval_exclusivity
    """
    set_clock("2026-06-16T00:00:00Z")
    creator = create_creator(charge_timing="UP_FRONT")
    plus = create_published_tier(creator["id"], name="PLUS", rank=1, monthly_fee_cents=1500)
    basic = create_published_tier(creator["id"], name="BASIC", rank=2, monthly_fee_cents=800)
    patron = create_patron()
    first = create_active_pledge(patron["id"], creator["id"], plus["id"])
    assert first["lifecycle_status"] == "ACTIVE"

    resp = api_client.create_pledge(
        {"patron_id": patron["id"], "creator_id": creator["id"], "tier_id": basic["id"]},
        make_patron_headers(patron["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_PLEDGE.value)


def test_tier_rank_slot_occupation_rejects_second_publish(api):
    """PRD §3.1: "Publishing then enforces that no other non-`RETIRED` tier of
    the same creator already occupies this tier's `rank`; a collision is rejected
    with `ERR_TIER_RANK_TAKEN`."

    Design: Difficulty/resource_temporal_overlap/rto_tier_rank_slot_occupation
    """
    creator = create_creator()
    headers = make_creator_headers(creator["id"])
    ta = get_success_data(api_client.create_tier(
        {"creator_id": creator["id"], "name": "T_A", "billing_model": "MONTHLY", "rank": 2,
         "monthly_fee_cents": 1500}, headers))
    validate_success(api_client.publish_tier(ta["id"], headers), 200)
    tb = get_success_data(api_client.create_tier(
        {"creator_id": creator["id"], "name": "T_B", "billing_model": "MONTHLY", "rank": 2,
         "monthly_fee_cents": 2000}, headers))

    resp = api_client.publish_tier(tb["id"], headers)
    validate_error(resp, ApiErrorId.ERR_TIER_RANK_TAKEN.value)
    assert get_success_data(api_client.get_tier(ta["id"], ADMIN))["status"] == "PUBLISHED"
    assert get_success_data(api_client.get_tier(tb["id"], ADMIN))["status"] == "DRAFT"


def test_conversation_open_requires_active_pledge(api):
    """PRD §3.8: "When a patron opens a conversation or sends a message, the
    patron must hold a pledge to that creator whose `lifecycle_status` is
    `ACTIVE` or `PAUSED`; a patron without such a pledge is rejected with
    `ERR_NOT_A_PATRON_OF_CREATOR`."

    Design: Difficulty/cross_entity_state_dependency/cesd_conversation_open_requires_active_pledge
    """
    # Patron's only pledge to the creator is CANCELLED.
    s = setup_cancelled_lapsed_pledge(clock="2026-06-16T00:00:00Z", monthly_fee_cents=1500)
    assert s["pledge"]["lifecycle_status"] == "CANCELLED"

    resp = api_client.create_conversation(
        {"creator_id": s["creator"]["id"], "patron_id": s["patron"]["id"]},
        make_patron_headers(s["patron"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_NOT_A_PATRON_OF_CREATOR.value)


def test_win_back_offer_expires_at_lapsed_plus_60_days(api):
    """PRD §3.6: "An offer is born in `OFFERED` status; its `expires_at` is
    computed as the pledge's `lapsed_at` plus a win-back window of 60 days
    (UTC)."

    Design: Difficulty/boundary_precision_check/bpc_win_back_window_day_boundary

    NOTE: this test previously also asserted that reactivating past the window is
    rejected with ERR_OFFER_EXPIRED. That assertion was removed because the PRD
    does not uniquely determine it: §3.6's win-back charge algorithm states "If a
    redeemable win-back offer exists, take its `discount_pct`; otherwise the
    discount is zero" — which admits a faithful implementation that, finding no
    *redeemable* offer (the only one being past its window), reactivates at full
    proration with discount 0 rather than rejecting. §3.6 also says "an attempt
    to redeem past the window is rejected with ERR_OFFER_EXPIRED", giving a
    second, equally faithful implementation that rejects. Both are derivable, so
    the rejection outcome is not uniquely determined. The uniquely-derivable
    expires_at = lapsed_at + 60d computation is retained here.
    """
    # Lapse at 2026-04-01 → expires_at = 2026-05-31 (April 1 + 60 days, UTC).
    s = setup_lapsed_pledge_with_offer(lapse_clock="2026-04-01T00:00:00Z", monthly_fee_cents=1500,
                                       discount_pct=0.30)
    assert s["offer"]["expires_at"].startswith("2026-05-31"), (
        f"expires_at must be lapsed_at + 60d = 2026-05-31, got {s['offer']['expires_at']}"
    )


def test_messaging_gate_non_patron_returns_forbidden(api):
    """PRD §3.8: "When a patron opens a conversation or sends a message, the
    patron must hold a pledge to that creator whose `lifecycle_status` is
    `ACTIVE` or `PAUSED`; a patron without such a pledge is rejected with
    `ERR_NOT_A_PATRON_OF_CREATOR`."

    Design: Corner/validations/messaging_gate_non_patron_returns_forbidden
    """
    creator = create_creator()
    patron = create_patron()
    resp = api_client.create_conversation(
        {"creator_id": creator["id"], "patron_id": patron["id"]}, make_patron_headers(patron["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_NOT_A_PATRON_OF_CREATOR.value)


def test_content_gate_tier_too_low_returns_forbidden(api):
    """PRD §3.8: "A patron whose active tier rank falls below the post's
    `min_tier_rank` is rejected with `ERR_TIER_TOO_LOW`."

    Design: Corner/validations/content_gate_tier_too_low_returns_forbidden
    """
    set_clock("2026-06-16T00:00:00Z")
    s = setup_active_membership(clock="2026-06-16T00:00:00Z", monthly_fee_cents=800)
    creator_id = s["creator"]["id"]
    headers = make_creator_headers(creator_id)
    # The membership tier is rank 1; a VIP post requires rank 5.
    post = get_success_data(api_client.create_post(
        {"creator_id": creator_id, "title": "vip", "body": "secret", "min_tier_rank": 5}, headers))
    validate_success(api_client.publish_post(post["id"], headers), 200)

    resp = api_client.request_post_access(
        post["id"], {"patron_id": s["patron"]["id"]}, make_patron_headers(s["patron"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_TIER_TOO_LOW.value)
