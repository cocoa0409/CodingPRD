"""Per-creation paid-post billing: the nested min/max cap calculation and its
exact-zero boundary.

Covers the per-creation combinatorial calculation, the cap boundary precision
instance, and the billing-model-mismatch corner instance.
"""
from test_helpers import (
    api_client,
    validate_paginated,
    validate_error,
    make_creator_headers,
    make_platform_admin_headers,
    ApiErrorId,
    create_creator,
    setup_per_creation_membership,
    create_paid_post,
    publish_post,
    get_pledge,
    create_post_payload,
)

ADMIN = make_platform_admin_headers()


def _per_creation_charges(pledge_id):
    data, meta = validate_paginated(api_client.list_charges(ADMIN, params={"pledge_id": pledge_id}))
    pc = [c for c in data if c["charge_kind"] == "PER_CREATION"]
    return pc, meta


def test_per_creation_cap_nested_min_max_500_500_200(api):
    """PRD §3.6: "First, determine the remaining cap for the pledge: it is the
    tier's `per_creation_monthly_cap_cents` minus the pledge's
    `current_cycle_charged_cents`, floored at zero so it is never negative. The
    charge amount is then the smaller of the tier's `per_creation_fee_cents` and
    that remaining cap."

    Design: Difficulty/combinatorial_formula/cf_per_creation_cap_nested_min_max
    """
    s = setup_per_creation_membership(
        clock="2026-06-10T00:00:00Z", per_creation_fee_cents=500, per_creation_monthly_cap_cents=1200,
    )
    creator_id, pledge_id = s["creator"]["id"], s["pledge"]["id"]

    p1 = create_paid_post(creator_id, min_tier_rank=1)
    p2 = create_paid_post(creator_id, min_tier_rank=1)
    p3 = create_paid_post(creator_id, min_tier_rank=1)
    publish_post(p1["id"], creator_id)
    publish_post(p2["id"], creator_id)
    publish_post(p3["id"], creator_id)

    pc, _ = _per_creation_charges(pledge_id)
    grosses = [c["gross_amount_cents"] for c in pc]
    # min(500, 1200-0)=500; min(500, 1200-500)=500; min(500, 1200-1000)=200.
    assert grosses == [500, 500, 200], f"Expected [500, 500, 200], got {grosses}"
    assert get_pledge(pledge_id)["current_cycle_charged_cents"] == 1200, (
        f"current_cycle_charged_cents must be 1200, got {get_pledge(pledge_id)['current_cycle_charged_cents']}"
    )


def test_per_creation_cap_exact_zero_creates_no_charge(api):
    """PRD §3.6: "If the charge amount works out to zero — the cap is already
    exhausted for this cycle — no charge row is created for that pledge this
    cycle; this is the normal, non-error outcome of a full cap."

    Design: Difficulty/boundary_precision_check/bpc_per_creation_cap_exact_zero
    """
    s = setup_per_creation_membership(
        clock="2026-06-10T00:00:00Z", per_creation_fee_cents=500, per_creation_monthly_cap_cents=1000,
    )
    creator_id, pledge_id = s["creator"]["id"], s["pledge"]["id"]

    # Exhaust the cap with two 500-cent publishes (charged total = 1000 = cap).
    p1 = create_paid_post(creator_id, min_tier_rank=1)
    p2 = create_paid_post(creator_id, min_tier_rank=1)
    p3 = create_paid_post(creator_id, min_tier_rank=1)
    publish_post(p1["id"], creator_id)
    publish_post(p2["id"], creator_id)

    pc_before, _ = _per_creation_charges(pledge_id)
    assert len(pc_before) == 2, f"two publishes should bill twice, got {len(pc_before)}"
    assert get_pledge(pledge_id)["current_cycle_charged_cents"] == 1000

    # Third publish at exact cap: remaining_cap = 1000-1000 = 0 → no charge.
    publish_post(p3["id"], creator_id)

    pc_after, _ = _per_creation_charges(pledge_id)
    assert len(pc_after) == 2, (
        f"third publish at exhausted cap must create no charge, got {len(pc_after)} per-creation charges"
    )
    assert get_pledge(pledge_id)["current_cycle_charged_cents"] == 1000, (
        "current_cycle_charged_cents must be unchanged by the third publish"
    )


def test_paid_creation_on_monthly_creator_rejected(api):
    """PRD §3.6: "A paid-creation publish is only meaningful for the per-creation
    model; attempting it where the creator's or tier's billing model is not
    `PER_CREATION` is rejected with `ERR_BILLING_MODEL_MISMATCH`."

    Design: Corner/validations/cross_link_charge_pledge_mismatch_excluded
    """
    creator = create_creator(billing_mode="MONTHLY")
    headers = make_creator_headers(creator["id"])
    post = api_client.create_post(
        create_post_payload(creator["id"], min_tier_rank=0, is_paid_creation=True), headers
    ).json()["data"]

    resp = api_client.publish_post(post["id"], headers)
    validate_error(resp, ApiErrorId.ERR_BILLING_MODEL_MISMATCH.value)
