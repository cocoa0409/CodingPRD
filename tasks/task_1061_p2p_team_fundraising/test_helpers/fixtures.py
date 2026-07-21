"""Composite setup helpers.

Every helper builds its preconditions from scratch through published endpoints —
the database is empty at the start of each test. Setup calls use the lenient
validator so a broken precondition surfaces as a setup failure, not as a
confusing assertion failure inside the test body.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import REVIEWER_ONE_ID, REVIEWER_TWO_ID
from .factories import (
    create_campaign_payload,
    create_donation_payload,
    create_donor_payload,
    create_event_payload,
    create_incentive_tier_payload,
    create_match_pool_payload,
    create_organization_payload,
    create_participant_payload,
    create_registration_payload,
    create_team_payload,
)
from .test_users import (
    make_campaign_manager_headers,
    make_donor_headers,
    make_finance_reviewer_headers,
    make_participant_headers,
    make_platform_admin_headers,
    make_anonymous_headers,
)

ADMIN = make_platform_admin_headers()
ANON = make_anonymous_headers()
REVIEWER_ONE = make_finance_reviewer_headers(REVIEWER_ONE_ID)
REVIEWER_TWO = make_finance_reviewer_headers(REVIEWER_TWO_ID)


# ---- Tier 1: single resources -------------------------------------------


def set_clock(to_iso8601: str, api=api_client) -> str:
    """Move the logical clock and return the reported instant."""
    data = get_success_data(api.set_clock({"to_iso8601": to_iso8601}, ADMIN))
    return data.get("current_utc", to_iso8601)


def create_organization(api=api_client, **overrides) -> dict:
    return get_success_data(
        api.create_organization(create_organization_payload(**overrides), ADMIN)
    )


def verify_payout_account(organization_id: str, api=api_client, status: str = "VERIFIED") -> dict:
    return get_success_data(
        api.set_payout_account(organization_id, {"status": status}, ADMIN)
    )


def create_draft_campaign(organization_id: str, api=api_client, **overrides) -> dict:
    headers = make_campaign_manager_headers(organization_id)
    return get_success_data(
        api.create_campaign(create_campaign_payload(organization_id, **overrides), headers)
    )


def create_donor(api=api_client, **overrides) -> dict:
    return get_success_data(api.create_donor(create_donor_payload(**overrides), ANON))


# ---- Tier 2: an organization plus a published campaign -------------------


def setup_published_campaign(api=api_client, verified_payout_account: bool = False,
                             **campaign_overrides) -> dict:
    """Organization + PUBLISHED campaign.

    Returns a context dict carrying the ids and the campaign manager's headers.
    """
    org = create_organization(api=api)
    if verified_payout_account:
        verify_payout_account(org["id"], api=api)
    cm_headers = make_campaign_manager_headers(org["id"])
    campaign = get_success_data(
        api.create_campaign(create_campaign_payload(org["id"], **campaign_overrides), cm_headers)
    )
    campaign = get_success_data(api.publish_campaign(campaign["id"], cm_headers))
    return {
        "org_id": org["id"],
        "organization": org,
        "campaign_id": campaign["id"],
        "campaign": campaign,
        "cm_headers": cm_headers,
    }


def setup_two_published_campaigns(api=api_client, **campaign_overrides) -> dict:
    """One organization owning two PUBLISHED campaigns, A and B."""
    org = create_organization(api=api)
    cm_headers = make_campaign_manager_headers(org["id"])
    camp_a = get_success_data(
        api.create_campaign(
            create_campaign_payload(org["id"], title="Campaign A", **campaign_overrides),
            cm_headers,
        )
    )
    get_success_data(api.publish_campaign(camp_a["id"], cm_headers))
    camp_b = get_success_data(
        api.create_campaign(
            create_campaign_payload(org["id"], title="Campaign B", **campaign_overrides),
            cm_headers,
        )
    )
    get_success_data(api.publish_campaign(camp_b["id"], cm_headers))
    return {
        "org_id": org["id"],
        "campaign_a_id": camp_a["id"],
        "campaign_b_id": camp_b["id"],
        "cm_headers": cm_headers,
    }


# ---- Tier 2: children of a published campaign ---------------------------


def create_participant(campaign_id: str, api=api_client, **overrides) -> dict:
    return get_success_data(
        api.create_participant(create_participant_payload(campaign_id, **overrides), ANON)
    )


def create_active_participant(campaign_id: str, api=api_client, **overrides) -> dict:
    """Create a fundraiser page and walk it PENDING -> ACTIVE."""
    participant = create_participant(campaign_id, api=api, **overrides)
    headers = make_participant_headers(participant["id"])
    return get_success_data(api.activate_participant(participant["id"], headers))


def create_team(campaign_id: str, cm_headers: dict, api=api_client, **overrides) -> dict:
    return get_success_data(
        api.create_team(create_team_payload(campaign_id, **overrides), cm_headers)
    )


def create_event(campaign_id: str, cm_headers: dict, api=api_client, **overrides) -> dict:
    return get_success_data(
        api.create_event(create_event_payload(campaign_id, **overrides), cm_headers)
    )


def create_match_pool(campaign_id: str, cm_headers: dict, api=api_client, **overrides) -> dict:
    return get_success_data(
        api.create_match_pool(create_match_pool_payload(campaign_id, **overrides), cm_headers)
    )


def create_incentive_tier(campaign_id: str, cm_headers: dict, api=api_client, **overrides) -> dict:
    return get_success_data(
        api.create_incentive_tier(
            create_incentive_tier_payload(campaign_id, **overrides), cm_headers
        )
    )


def create_registration(participant_id: str, event_id: str, headers: dict,
                        api=api_client, **overrides) -> dict:
    return get_success_data(
        api.create_registration(
            create_registration_payload(participant_id, event_id, **overrides), headers
        )
    )


# ---- Tier 3: gifts through their lifecycle ------------------------------


def create_gift(campaign_id: str, donor_id: str, designation_type: str,
                designation_id: str, amount_cents: int, api=api_client, **overrides) -> dict:
    """Create a PENDING gift as the donor themselves."""
    return get_success_data(
        api.create_donation(
            create_donation_payload(
                campaign_id, donor_id, designation_type, designation_id,
                amount_cents, **overrides,
            ),
            make_donor_headers(donor_id),
        )
    )


def settle_gift(donation_id: str, api=api_client, outcome: str = "SETTLED") -> dict:
    return get_success_data(api.settle_donation(donation_id, {"outcome": outcome}, ADMIN))


def create_settled_gift(campaign_id: str, donor_id: str, designation_type: str,
                        designation_id: str, amount_cents: int, api=api_client,
                        **overrides) -> dict:
    """Create a gift and settle it, returning the settled gift."""
    gift = create_gift(
        campaign_id, donor_id, designation_type, designation_id, amount_cents,
        api=api, **overrides,
    )
    return settle_gift(gift["id"], api=api)


def refund_gift(donation_id: str, api=api_client, reason: str = "donor requested") -> dict:
    return get_success_data(api.refund_donation(donation_id, {"reason": reason}, ADMIN))


def receipt_for_gift(donation_id: str, headers: dict, api=api_client) -> dict:
    """The settle cascade is the only minter of receipts; read it back by filter."""
    data, _meta = _paginated(api.list_receipts(headers, params={"donation_id": donation_id}))
    assert data, f"No receipt found for donation {donation_id}"
    return data[0]


def awards_for_participant(participant_id: str, headers: dict, api=api_client,
                           tier_id: str = None) -> list:
    """Awards are discoverable only by reading them back."""
    params = {"participant_id": participant_id}
    if tier_id:
        params["tier_id"] = tier_id
    data, _meta = _paginated(api.list_incentive_awards(headers, params=params))
    return data


# ---- Tier 4: a campaign carrying spendable balance ----------------------


def setup_campaign_with_balance(api=api_client, amount_cents: int = 100000,
                                verified_payout_account: bool = False, **campaign_overrides) -> dict:
    """PUBLISHED campaign with one SETTLED CAMPAIGN-designated gift and no pool.

    A 100000-cent gift carries a fee of 7930, so lifetime_net_cents is 92070.
    """
    ctx = setup_published_campaign(
        api=api, verified_payout_account=verified_payout_account, **campaign_overrides
    )
    donor = create_donor(api=api)
    gift = create_settled_gift(
        ctx["campaign_id"], donor["id"], "CAMPAIGN", ctx["campaign_id"], amount_cents, api=api
    )
    ctx["donor_id"] = donor["id"]
    ctx["donation_id"] = gift["id"]
    ctx["donation"] = gift
    return ctx


def current_campaign_version(campaign_id: str, headers: dict, api=api_client) -> int:
    return get_success_data(api.get_campaign(campaign_id, headers))["version"]


def request_payout(campaign_id: str, cm_headers: dict, amount_cents: int,
                   api=api_client, note: str = "tranche") -> dict:
    """Request a disbursement using the campaign's current version."""
    version = current_campaign_version(campaign_id, cm_headers, api=api)
    return get_success_data(
        api.create_payout(
            campaign_id,
            {
                "amount_cents": amount_cents,
                "expected_campaign_version": version,
                "note": note,
            },
            cm_headers,
        )
    )


def setup_payout_under_review(api=api_client, amount_cents: int = 50000,
                              gift_cents: int = 100000,
                              verified_payout_account: bool = False) -> dict:
    """Campaign with balance + a payout moved REQUESTED -> UNDER_REVIEW."""
    ctx = setup_campaign_with_balance(
        api=api, amount_cents=gift_cents, verified_payout_account=verified_payout_account
    )
    payout = request_payout(ctx["campaign_id"], ctx["cm_headers"], amount_cents, api=api)
    payout = get_success_data(api.review_payout(payout["id"], REVIEWER_ONE))
    ctx["payout_id"] = payout["id"]
    ctx["payout"] = payout
    return ctx


def setup_approved_payout(api=api_client, amount_cents: int = 50000,
                          gift_cents: int = 100000,
                          verified_payout_account: bool = False) -> dict:
    """A payout walked all the way to APPROVED by two distinct reviewers."""
    ctx = setup_payout_under_review(
        api=api, amount_cents=amount_cents, gift_cents=gift_cents,
        verified_payout_account=verified_payout_account,
    )
    ctx["payout"] = get_success_data(api.approve_payout(ctx["payout_id"], REVIEWER_TWO))
    return ctx


def setup_released_payout(api=api_client, amount_cents: int = 50000,
                          gift_cents: int = 100000) -> dict:
    """A payout disbursed against a VERIFIED payout account."""
    ctx = setup_approved_payout(
        api=api, amount_cents=amount_cents, gift_cents=gift_cents,
        verified_payout_account=True,
    )
    ctx["payout"] = get_success_data(api.release_payout(ctx["payout_id"], ADMIN))
    return ctx


# ---- Tier 5: threshold-targeting scenarios ------------------------------


def setup_participant_at_credit(credited_cents: int, api=api_client,
                                fundraising_minimum_cents: int = 0,
                                with_event: bool = False, **campaign_overrides) -> dict:
    """ACTIVE fundraiser whose single settled gift credits exactly credited_cents.

    No match pool exists, so the credited figure equals the gift amount.
    """
    ctx = setup_published_campaign(
        api=api, fundraising_minimum_cents=fundraising_minimum_cents, **campaign_overrides
    )
    participant = create_active_participant(ctx["campaign_id"], api=api)
    donor = create_donor(api=api)
    gift = create_settled_gift(
        ctx["campaign_id"], donor["id"], "PARTICIPANT", participant["id"],
        credited_cents, api=api,
    )
    ctx.update(
        {
            "participant_id": participant["id"],
            "participant_headers": make_participant_headers(participant["id"]),
            "donor_id": donor["id"],
            "donation_id": gift["id"],
        }
    )
    if with_event:
        event = create_event(ctx["campaign_id"], ctx["cm_headers"], api=api)
        ctx["event_id"] = event["id"]
    return ctx


def setup_participant_at_credit_with_match(api=api_client,
                                           fundraising_minimum_cents: int = 15000,
                                           gift_cents: int = 10000,
                                           pool_amount_cents: int = 5000,
                                           match_ratio: float = 0.5,
                                           per_donation_cap_cents: int = 5000,
                                           with_event: bool = True) -> dict:
    """ACTIVE fundraiser whose settled gift drew a sponsor match.

    With a 10000-cent gift, ratio 0.5 and a 5000-cent pool, the match is 5000 and
    credited_cents lands on 15000 while the pool is driven to EXHAUSTED.
    """
    ctx = setup_published_campaign(api=api, fundraising_minimum_cents=fundraising_minimum_cents)
    pool = create_match_pool(
        ctx["campaign_id"], ctx["cm_headers"], api=api,
        pool_amount_cents=pool_amount_cents, match_ratio=match_ratio,
        per_donation_cap_cents=per_donation_cap_cents,
    )
    if with_event:
        event = create_event(ctx["campaign_id"], ctx["cm_headers"], api=api)
        ctx["event_id"] = event["id"]
    participant = create_active_participant(ctx["campaign_id"], api=api)
    donor = create_donor(api=api)
    gift = create_settled_gift(
        ctx["campaign_id"], donor["id"], "PARTICIPANT", participant["id"], gift_cents, api=api
    )
    ctx.update(
        {
            "pool_id": pool["id"],
            "participant_id": participant["id"],
            "participant_headers": make_participant_headers(participant["id"]),
            "donor_id": donor["id"],
            "donation_id": gift["id"],
            "donation": gift,
        }
    )
    return ctx


def setup_full_event_with_reservation(api=api_client, capacity: int = 1, **event_overrides) -> dict:
    """An event whose capacity is entirely consumed by one RESERVED registration."""
    ctx = setup_published_campaign(api=api)
    event = create_event(
        ctx["campaign_id"], ctx["cm_headers"], api=api, capacity=capacity, **event_overrides
    )
    participant = create_active_participant(ctx["campaign_id"], api=api)
    headers = make_participant_headers(participant["id"])
    registration = create_registration(participant["id"], event["id"], headers, api=api)
    ctx.update(
        {
            "event_id": event["id"],
            "participant_id": participant["id"],
            "participant_headers": headers,
            "registration_id": registration["id"],
        }
    )
    return ctx


def setup_two_teams_with_credit(api=api_client) -> dict:
    """Two ACTIVE teams whose members carry settled gifts of 20000 and 15000 cents.

    Alpha's goal is 100000 and Beta's is 30000, so the two leaderboard variants
    rank them in opposite orders.
    """
    ctx = setup_published_campaign(api=api, fundraising_minimum_cents=0)
    team_a = create_team(
        ctx["campaign_id"], ctx["cm_headers"], api=api,
        name="Team Alpha", goal_amount_cents=100000,
    )
    team_b = create_team(
        ctx["campaign_id"], ctx["cm_headers"], api=api,
        name="Team Beta", goal_amount_cents=30000,
    )
    p_a = create_participant(
        ctx["campaign_id"], api=api, display_name="Pat Alpha", team_id=team_a["id"]
    )
    p_b = create_participant(
        ctx["campaign_id"], api=api, display_name="Bo Beta", team_id=team_b["id"]
    )
    donor = create_donor(api=api)
    create_settled_gift(
        ctx["campaign_id"], donor["id"], "PARTICIPANT", p_a["id"], 20000, api=api
    )
    create_settled_gift(
        ctx["campaign_id"], donor["id"], "PARTICIPANT", p_b["id"], 15000, api=api
    )
    ctx.update(
        {
            "team_a_id": team_a["id"],
            "team_b_id": team_b["id"],
            "participant_a_id": p_a["id"],
            "participant_b_id": p_b["id"],
            "donor_id": donor["id"],
        }
    )
    return ctx


def setup_two_tier_participant_with_awards(api=api_client) -> dict:
    """A fundraiser at 15000 credited cents holding a Bronze and a Gold award.

    Two settled gifts of 5000 and 10000 cents cross a 5000-cent Bronze tier and a
    15000-cent Gold tier; no pool exists, so credit equals the gift amounts.
    """
    ctx = setup_published_campaign(api=api)
    bronze = create_incentive_tier(
        ctx["campaign_id"], ctx["cm_headers"], api=api,
        name="Bronze Shirt", threshold_cents=5000, reward_description="Event shirt",
    )
    gold = create_incentive_tier(
        ctx["campaign_id"], ctx["cm_headers"], api=api,
        name="Gold Jacket", threshold_cents=15000, reward_description="Champion jacket",
    )
    participant = create_participant(ctx["campaign_id"], api=api)
    donor = create_donor(api=api)
    small = create_settled_gift(
        ctx["campaign_id"], donor["id"], "PARTICIPANT", participant["id"], 5000, api=api
    )
    big = create_settled_gift(
        ctx["campaign_id"], donor["id"], "PARTICIPANT", participant["id"], 10000, api=api
    )
    bronze_awards = awards_for_participant(
        participant["id"], ctx["cm_headers"], api=api, tier_id=bronze["id"]
    )
    gold_awards = awards_for_participant(
        participant["id"], ctx["cm_headers"], api=api, tier_id=gold["id"]
    )
    assert bronze_awards, "Setup expected a Bronze award from the settle cascade"
    assert gold_awards, "Setup expected a Gold award from the settle cascade"
    ctx.update(
        {
            "tier_bronze_id": bronze["id"],
            "tier_gold_id": gold["id"],
            "participant_id": participant["id"],
            "donor_id": donor["id"],
            "donation_small_id": small["id"],
            "donation_big_id": big["id"],
            "award_bronze_id": bronze_awards[0]["id"],
            "award_gold_id": gold_awards[0]["id"],
        }
    )
    return ctx


def setup_exhausted_pool_with_settled_gift(api=api_client) -> dict:
    """A 5000-cent pool fully consumed by one 10000-cent PARTICIPANT gift.

    The match is min(5000, 5000, 5000) = 5000, which drives the pool to EXHAUSTED.
    """
    ctx = setup_published_campaign(api=api)
    pool = create_match_pool(
        ctx["campaign_id"], ctx["cm_headers"], api=api,
        pool_amount_cents=5000, match_ratio=0.5, per_donation_cap_cents=5000,
    )
    participant = create_participant(ctx["campaign_id"], api=api)
    donor = create_donor(api=api)
    gift = create_settled_gift(
        ctx["campaign_id"], donor["id"], "PARTICIPANT", participant["id"], 10000, api=api
    )
    ctx.update(
        {
            "pool_id": pool["id"],
            "participant_id": participant["id"],
            "donor_id": donor["id"],
            "donation_id": gift["id"],
            "donation": gift,
        }
    )
    return ctx


# ---- internal ------------------------------------------------------------


def _paginated(response):
    body = response.json()
    assert response.status_code == 200, f"List read failed: {response.text}"
    return body["data"], body.get("meta", {})
