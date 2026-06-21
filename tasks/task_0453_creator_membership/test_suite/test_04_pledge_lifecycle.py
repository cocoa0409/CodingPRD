"""Pledge lifecycle: the cyclic reactivate re-entry, the charge fork-join
branching, activation on first charge, and dependency on a published tier.

Covers the non-linear-state-machine and cross-entity-state-dependency depth
instances plus the pledge/charge corner state-machine instances.
"""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    make_creator_headers,
    make_patron_headers,
    make_platform_admin_headers,
    ApiErrorId,
    set_clock,
    create_creator,
    create_published_tier,
    create_patron,
    create_draft_pledge,
    create_active_pledge,
    first_pledge_charge,
    settle_charge,
    get_pledge,
    get_pledge_version,
    setup_active_membership,
    setup_cancelled_lapsed_pledge,
    open_conversation,
)

ADMIN = make_platform_admin_headers()


def test_reactivate_cancelled_lapsed_pledge_loops_back_to_active(api):
    """PRD §3.2: "Reactivation is permitted only when both conditions hold —
    `lifecycle_status` is `CANCELLED` and `billing_status` is `LAPSED` —
    otherwise it is rejected with `ERR_PLEDGE_NOT_REACTIVATABLE`."
    PRD §3.2: "On reactivation the pledge's `lifecycle_status` returns to
    `ACTIVE`, its `billing_status` returns to `CURRENT`, and the owning tier's
    `active_pledge_count` is incremented."

    Design: Difficulty/non_linear_state_machine/nlsm_pledge_reactivate_cycle
    """
    s = setup_cancelled_lapsed_pledge(clock="2026-06-16T00:00:00Z", monthly_fee_cents=1500)
    before = get_pledge(s["pledge"]["id"])
    assert before["lifecycle_status"] == "CANCELLED", before["lifecycle_status"]
    assert before["billing_status"] == "LAPSED", before["billing_status"]

    react = api_client.reactivate_pledge(s["pledge"]["id"], make_patron_headers(s["patron"]["id"]))
    data = validate_success(react, 200)
    assert data["lifecycle_status"] == "ACTIVE", f"reactivate must return to ACTIVE, got {data['lifecycle_status']}"
    assert data["billing_status"] == "CURRENT", f"reactivate must return to CURRENT, got {data['billing_status']}"


def test_charge_fork_join_succeeded_vs_failed_branches(api):
    """PRD §3.5: "if this is the pledge's first charge, the pledge bubbles from
    `DRAFT` to `ACTIVE`."
    PRD §3.5: "When the outcome is failure, the charge moves from `PENDING` to
    `FAILED`, the `wallet_applied_cents` that had been consumed is refunded back
    into the patron's `wallet_credit_cents` so that wallet value is conserved,
    and the failure drives the pledge's billing axis forward through `PAST_DUE`".

    Design: Difficulty/non_linear_state_machine/nlsm_charge_branching_fork_join
    """
    set_clock("2026-06-16T00:00:00Z")
    creator = create_creator(charge_timing="UP_FRONT", platform_plan="STARTER")
    tier = create_published_tier(creator["id"], name="PLUS", monthly_fee_cents=1500)
    p_s = create_patron()
    p_f = create_patron()
    pledge_s = create_draft_pledge(p_s["id"], creator["id"], tier["id"])
    pledge_f = create_draft_pledge(p_f["id"], creator["id"], tier["id"])
    ch_s = first_pledge_charge(pledge_s["id"])
    ch_f = first_pledge_charge(pledge_f["id"])

    # SUCCEEDED branch.
    s_charge = settle_charge(ch_s["id"], "SUCCEEDED")
    assert s_charge["status"] == "SUCCEEDED"
    assert get_pledge(pledge_s["id"])["lifecycle_status"] == "ACTIVE"
    assert api.get_creator(creator["id"], ADMIN).json()["data"]["pending_payout_cents"] == 750

    # FAILED branch (same trigger, divergent effects).
    f_charge = settle_charge(ch_f["id"], "FAILED")
    assert f_charge["status"] == "FAILED"
    pledge_f_now = get_pledge(pledge_f["id"])
    assert pledge_f_now["lifecycle_status"] == "DRAFT", (
        f"FAILED first charge must leave pledge DRAFT, got {pledge_f_now['lifecycle_status']}"
    )
    assert pledge_f_now["billing_status"] == "PAST_DUE", (
        f"FAILED renewal/initial drives billing to PAST_DUE, got {pledge_f_now['billing_status']}"
    )


def test_pledge_to_draft_tier_rejected(api):
    """PRD §3.2: "The pledge may only target a tier whose `status` is
    `PUBLISHED`; pledging an unpublished tier is rejected with
    `ERR_TIER_NOT_PUBLISHED`."

    Design: Difficulty/cross_entity_state_dependency/cesd_pledge_requires_published_tier
    """
    set_clock("2026-06-16T00:00:00Z")
    creator = create_creator(charge_timing="UP_FRONT")
    headers = make_creator_headers(creator["id"])
    # Create a tier but do NOT publish it.
    tier = api_client.create_tier(
        {"creator_id": creator["id"], "name": "PLUS", "billing_model": "MONTHLY", "rank": 1,
         "monthly_fee_cents": 1500}, headers,
    ).json()["data"]
    patron = create_patron()

    resp = api_client.create_pledge(
        {"patron_id": patron["id"], "creator_id": creator["id"], "tier_id": tier["id"]},
        make_patron_headers(patron["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_TIER_NOT_PUBLISHED.value)


def test_pledge_published_tier_accepts_pledge(api):
    """PRD §3.2: "The pledge may only target a tier whose `status` is
    `PUBLISHED`; pledging an unpublished tier is rejected with
    `ERR_TIER_NOT_PUBLISHED`."

    Design: Difficulty/cross_entity_state_dependency/cesd_pledge_requires_published_tier
    """
    set_clock("2026-06-16T00:00:00Z")
    creator = create_creator(charge_timing="UP_FRONT")
    tier = create_published_tier(creator["id"], name="PLUS", monthly_fee_cents=1500)
    patron = create_patron()

    resp = api_client.create_pledge(
        {"patron_id": patron["id"], "creator_id": creator["id"], "tier_id": tier["id"]},
        make_patron_headers(patron["id"]),
    )
    data = validate_success(resp, 201)
    assert data["tier_id"] == tier["id"]


def test_pledge_initial_state_is_draft_current(api):
    """PRD §3.2: "A newly created pledge begins with `lifecycle_status` of
    `DRAFT` and `billing_status` of `CURRENT`."

    Design: Corner/state_machines/pledge_initial_state_is_draft
    """
    set_clock("2026-06-16T00:00:00Z")
    creator = create_creator(charge_timing="UP_FRONT")
    tier = create_published_tier(creator["id"], name="T", monthly_fee_cents=1500)
    patron = create_patron()

    resp = api_client.create_pledge(
        {"patron_id": patron["id"], "creator_id": creator["id"], "tier_id": tier["id"]},
        make_patron_headers(patron["id"]),
    )
    data = validate_success(resp, 201)
    assert data["lifecycle_status"] == "DRAFT", data["lifecycle_status"]
    assert data["billing_status"] == "CURRENT", data["billing_status"]


def test_pledge_activates_on_first_charge_settle(api):
    """PRD §3.2: "The pledge advances from `DRAFT` to `ACTIVE` only once its
    first charge settles `SUCCEEDED`".
    PRD §3.2: "When the first charge settles successfully, the pledge's
    `cycle_anchor_date` is established and `current_cycle_charged_cents` is set
    to the settled charge amount; the owning tier's `active_pledge_count` is
    incremented."

    Design: Corner/state_machines/pledge_activates_on_first_charge_settle
    """
    set_clock("2026-06-16T00:00:00Z")
    creator = create_creator(charge_timing="UP_FRONT")
    tier = create_published_tier(creator["id"], name="T", monthly_fee_cents=1500)
    patron = create_patron()
    pledge = create_draft_pledge(patron["id"], creator["id"], tier["id"])
    charge = first_pledge_charge(pledge["id"])

    settle_charge(charge["id"], "SUCCEEDED")

    refreshed = get_pledge(pledge["id"])
    assert refreshed["lifecycle_status"] == "ACTIVE"
    assert refreshed["current_cycle_charged_cents"] == 750, refreshed["current_cycle_charged_cents"]
    tier_now = api.get_tier(tier["id"], ADMIN).json()["data"]
    assert tier_now["active_pledge_count"] == 1, tier_now["active_pledge_count"]


def test_resume_active_pledge_rejected(api):
    """PRD §3.2: "resuming is permitted only when the pledge is `PAUSED`,
    otherwise it is rejected with `ERR_PLEDGE_NOT_PAUSED`."

    Design: Corner/state_machines/pledge_resume_from_active_returns_not_paused
    """
    s = setup_active_membership(clock="2026-06-16T00:00:00Z", monthly_fee_cents=1500)
    v0 = s["pledge"]["version"]

    resp = api_client.resume_pledge(
        s["pledge"]["id"], {"expected_pledge_version": v0}, make_patron_headers(s["patron"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_PLEDGE_NOT_PAUSED.value)


def test_cancel_closes_orphaned_conversation_cascade(api):
    """PRD §3.2: "any `OPEN` conversation between this patron and this creator
    for which the patron no longer holds any other `ACTIVE` or `PAUSED` pledge is
    moved to `CLOSED`."

    Design: Corner/state_machines/cancel_closes_orphaned_conversation_cascade
    """
    s = setup_active_membership(clock="2026-06-16T00:00:00Z", monthly_fee_cents=1500)
    conv = open_conversation(s["creator"]["id"], s["patron"]["id"])

    cancel = api_client.cancel_pledge(s["pledge"]["id"], make_patron_headers(s["patron"]["id"]))
    validate_success(cancel, 200)

    conv_now = api.get_conversation(conv["id"], make_creator_headers(s["creator"]["id"])).json()["data"]
    assert conv_now["status"] == "CLOSED", (
        f"conversation must cascade to CLOSED on cancel, got {conv_now['status']}"
    )
