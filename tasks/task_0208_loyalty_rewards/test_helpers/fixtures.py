"""Composite setup helpers for the Loyalty Rewards API.

Every test runs against a freshly-launched server with an empty database, so each
fixture builds its preconditions from scratch using only PRD-declared endpoints.
All setup calls go through get_success_data() (lenient), so a broken precondition
surfaces as a clear "Setup step failed" error rather than a confusing assertion.

Unless a call is being exercised for ownership/role behaviour, setup runs as
ProgramAdmin — whose identity is opaque and never compared to any entity id
(PRD Section 2.1), so it can act on any shared operation.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import TEST_USERS, make_member_headers, make_partner_operator_headers
from .factories import (
    create_program_payload,
    create_tier_payload,
    create_member_payload,
    create_promotion_payload,
    create_reward_payload,
    create_partner_payload,
    create_blackout_payload,
    create_purchase_event_payload,
    create_redemption_payload,
    redemption_line,
    create_referral_payload,
    create_partner_transfer_payload,
)
from .constants import TIER_STANDARD, TIER_SILVER, TIER_GOLD, TIER_PLATINUM

ADMIN = TEST_USERS["program_admin_headers"]


# ---------------------------------------------------------------------------
# Tier ladder presets
# ---------------------------------------------------------------------------
STANDARD_ONLY = [TIER_STANDARD]
STANDARD_SILVER_GOLD = [TIER_STANDARD, TIER_SILVER, TIER_GOLD]
STANDARD_GOLD = [TIER_STANDARD, TIER_GOLD]
FULL_LADDER = [TIER_STANDARD, TIER_SILVER, TIER_GOLD, TIER_PLATINUM]


# ---------------------------------------------------------------------------
# Tier 1: Program standup
# ---------------------------------------------------------------------------
def create_program(activate=False, **program_overrides):
    """Create a DRAFT program (no tiers). Optionally activate. Returns program dict."""
    resp = api_client.create_program(create_program_payload(**program_overrides), ADMIN)
    prog = get_success_data(resp)
    if activate:
        prog = get_success_data(api_client.activate_program(prog["id"], ADMIN))
    return prog


def define_tiers(program_id, tiers):
    """Define each tier in `tiers` (list of dicts) under the program."""
    created = []
    for t in tiers:
        payload = create_tier_payload(program_id, **t)
        created.append(get_success_data(api_client.create_tier(program_id, payload, ADMIN)))
    return created


def setup_program(tiers=STANDARD_ONLY, clock=None, **program_overrides):
    """Create program + tiers, then ACTIVATE. Optionally set the clock afterward.

    Returns {"program": program, "tiers": [tier, ...]}.
    """
    prog = create_program(**program_overrides)
    created_tiers = define_tiers(prog["id"], tiers)
    prog = get_success_data(api_client.activate_program(prog["id"], ADMIN))
    if clock is not None:
        get_success_data(api_client.set_clock(clock, ADMIN))
    return {"program": prog, "tiers": created_tiers}


def set_clock(iso):
    return get_success_data(api_client.set_clock(iso, ADMIN))


# ---------------------------------------------------------------------------
# Tier 2: Members and balances
# ---------------------------------------------------------------------------
def register_member(program_id, email="m@x.com", full_name="M",
                    birth_month_day="03-10", **overrides):
    payload = create_member_payload(program_id, email=email, full_name=full_name,
                                    birth_month_day=birth_month_day, **overrides)
    return get_success_data(api_client.create_member(payload, ADMIN))


def post_purchase(member_id, eligible_amount_cents, **overrides):
    payload = create_purchase_event_payload(member_id, eligible_amount_cents, **overrides)
    return get_success_data(api_client.create_purchase_event(payload, ADMIN))


def get_member(member_id):
    return get_success_data(api_client.get_member(member_id, ADMIN))


def member_version(member_id):
    return get_member(member_id)["version"]


def setup_member_with_points(eligible_amount_cents=60000, tiers=STANDARD_ONLY,
                             clock=None, member_email="m@x.com",
                             birth_month_day="03-10", **program_overrides):
    """Active program + one STANDARD member + a single purchase of the given
    eligible amount (default 60000c => 600 points at STANDARD).

    Returns {"program", "tiers", "member", "purchase"}.
    """
    base = setup_program(tiers=tiers, clock=clock, **program_overrides)
    prog = base["program"]
    member = register_member(prog["id"], email=member_email, birth_month_day=birth_month_day)
    purchase = post_purchase(member["id"], eligible_amount_cents)
    member = get_member(member["id"])
    return {"program": prog, "tiers": base["tiers"], "member": member, "purchase": purchase}


# ---------------------------------------------------------------------------
# Tier 2/3: Rewards and redemptions
# ---------------------------------------------------------------------------
def add_reward(program_id, name="R", point_cost=600, tier_discount_pct=0.0, stock=5):
    payload = create_reward_payload(program_id, name=name, point_cost=point_cost,
                                    tier_discount_pct=tier_discount_pct, stock=stock)
    return get_success_data(api_client.create_reward(program_id, payload, ADMIN))


def quote_redemption(member_id, lines):
    payload = create_redemption_payload(member_id, lines)
    return get_success_data(api_client.create_redemption(payload, ADMIN))


def setup_quoted_redemption(reward_point_cost=600, reward_stock=5, quantity=1,
                            purchase_cents=100000, tiers=STANDARD_ONLY,
                            tier_discount_pct=0.0, clock=None):
    """Active program + reward + member with points + a QUOTED redemption (1 line).

    Returns {"program", "tiers", "member", "reward", "redemption"}.
    """
    base = setup_program(tiers=tiers, clock=clock)
    prog = base["program"]
    reward = add_reward(prog["id"], point_cost=reward_point_cost,
                        tier_discount_pct=tier_discount_pct, stock=reward_stock)
    member = register_member(prog["id"])
    post_purchase(member["id"], purchase_cents)
    member = get_member(member["id"])
    redemption = quote_redemption(member["id"], [redemption_line(reward["id"], quantity)])
    return {"program": prog, "tiers": base["tiers"], "member": member,
            "reward": reward, "redemption": redemption}


def confirm_redemption(redemption_id, member_id):
    """Confirm a QUOTED redemption using the member's live version."""
    v = member_version(member_id)
    return get_success_data(
        api_client.confirm_redemption(redemption_id, {"expected_member_version": v}, ADMIN)
    )


def setup_confirmed_redemption(reward_point_cost=600, reward_stock=5, quantity=1,
                               purchase_cents=100000, tiers=STANDARD_ONLY,
                               tier_discount_pct=0.0, clock=None):
    """A QUOTED redemption advanced to CONFIRMED.

    Returns {"program", "tiers", "member", "reward", "redemption"} where
    redemption is the CONFIRMED resource.
    """
    s = setup_quoted_redemption(reward_point_cost=reward_point_cost, reward_stock=reward_stock,
                                quantity=quantity, purchase_cents=purchase_cents,
                                tiers=tiers, tier_discount_pct=tier_discount_pct, clock=clock)
    confirmed = confirm_redemption(s["redemption"]["id"], s["member"]["id"])
    s["redemption"] = confirmed
    return s


# ---------------------------------------------------------------------------
# Tier 3: Partners and transfers
# ---------------------------------------------------------------------------
def add_partner(program_id, name="Air", transfer_block_size=100, min_transfer_points=100):
    payload = create_partner_payload(program_id, name=name,
                                     transfer_block_size=transfer_block_size,
                                     min_transfer_points=min_transfer_points)
    return get_success_data(api_client.create_partner(program_id, payload, ADMIN))


def setup_member_and_partner(purchase_cents=90000, tiers=STANDARD_ONLY,
                             clock="2026-03-01T00:00:00Z",
                             transfer_block_size=100, min_transfer_points=100):
    """Active program + ACTIVE partner + member with points.

    Returns {"program", "tiers", "member", "partner"}.
    """
    base = setup_program(tiers=tiers)
    prog = base["program"]
    partner = add_partner(prog["id"], transfer_block_size=transfer_block_size,
                          min_transfer_points=min_transfer_points)
    if clock is not None:
        set_clock(clock)
    member = register_member(prog["id"])
    post_purchase(member["id"], purchase_cents)
    member = get_member(member["id"])
    return {"program": prog, "tiers": base["tiers"], "member": member, "partner": partner}


def submit_transfer(member_id, partner_id, loyalty_points):
    """Submit a transfer using the member's live version. Returns the transfer dict."""
    v = member_version(member_id)
    payload = create_partner_transfer_payload(member_id, partner_id, loyalty_points, v)
    return get_success_data(api_client.create_partner_transfer(payload, ADMIN))


def setup_submitted_transfer(loyalty_points=500, purchase_cents=90000,
                             tiers=STANDARD_ONLY, clock="2026-03-01T00:00:00Z"):
    """Active program + partner + member with points + a SUBMITTED transfer.

    Returns {"program", "tiers", "member", "partner", "transfer"}.
    """
    s = setup_member_and_partner(purchase_cents=purchase_cents, tiers=tiers, clock=clock)
    transfer = submit_transfer(s["member"]["id"], s["partner"]["id"], loyalty_points)
    s["transfer"] = transfer
    return s


# ---------------------------------------------------------------------------
# Tier 4: Blackouts
# ---------------------------------------------------------------------------
def schedule_blackout(partner_id, starts_at, ends_at):
    payload = create_blackout_payload(partner_id, starts_at, ends_at)
    return get_success_data(api_client.create_blackout(partner_id, payload, ADMIN))


# ---------------------------------------------------------------------------
# Tier 4: Referrals
# ---------------------------------------------------------------------------
def create_referral(program_id, referrer_member_id, referee_email):
    payload = create_referral_payload(program_id, referrer_member_id, referee_email)
    return get_success_data(api_client.create_referral(payload, ADMIN))


def setup_pending_referral(clock=None, referrer_email="ref@x.com",
                           referee_email="friend@x.com", tiers=STANDARD_ONLY):
    """Active program + referrer member + a PENDING referral for referee_email.

    Returns {"program", "tiers", "referrer", "referral"}.
    """
    base = setup_program(tiers=tiers, clock=clock)
    prog = base["program"]
    referrer = register_member(prog["id"], email=referrer_email, full_name="Ref")
    referral = create_referral(prog["id"], referrer["id"], referee_email)
    return {"program": prog, "tiers": base["tiers"], "referrer": referrer, "referral": referral}


def setup_referral_with_registered_referee(clock=None, tiers=STANDARD_ONLY,
                                           referrer_email="ref@x.com",
                                           referee_email="friend@x.com"):
    """A PENDING referral whose referee has registered (referred_by_member_id set),
    so the referral is bound and ready to complete on a qualifying purchase.

    Returns {"program", "tiers", "referrer", "referee", "referral"}.
    """
    s = setup_pending_referral(clock=clock, referrer_email=referrer_email,
                               referee_email=referee_email, tiers=tiers)
    referee = register_member(s["program"]["id"], email=referee_email, full_name="Friend",
                              birth_month_day="04-20", referred_by_member_id=s["referrer"]["id"])
    s["referee"] = referee
    return s
