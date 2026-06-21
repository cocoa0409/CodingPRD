"""Composite setup helpers.

These encapsulate the multi-step preambles the design indices require so tests
focus on assertions, not plumbing. Each fixture builds its preconditions from
scratch using only PRD-declared endpoints (the harness restarts the server with
an empty database before every test).

All setup calls use get_success_data() (lenient 2xx validator) so a broken
precondition surfaces as a clear "Setup step failed" rather than a confusing
assertion deep inside a test.

Identity threading: after a fixture creates an Account, any ownership-gated
AccountHolder call uses make_account_holder_headers(account["id"]) — never the
shared fallback constant (PRD §2.1 ownership chain).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import TEST_USERS, make_account_holder_headers
from .factories import (
    create_section_payload,
    create_seat_payload,
    create_account_payload,
    create_season_plan_payload,
    create_subscription_payload,
    create_seat_assignment_payload,
    create_payment_plan_payload,
    create_ticket_transfer_payload,
    create_parking_zone_payload,
    create_parking_addon_payload,
    unique_email,
)
from .constants import SEASON_START, SEASON_END

_BOX = TEST_USERS["box_office_headers"]
_FIN = TEST_USERS["finance_headers"]


# --------------------------------------------------------------------------
# Tier 1: single-entity creators (each returns the created resource dict)
# --------------------------------------------------------------------------
def create_section(base_price_cents=200000, tier="STANDARD", name="Lower 100"):
    resp = api_client.create_section(
        create_section_payload(name=name, tier=tier, base_price_cents=base_price_cents), _BOX
    )
    return get_success_data(resp)


def create_seat(section_id, row_label="A", seat_number=1,
                season_start_date=SEASON_START, season_end_date=SEASON_END):
    resp = api_client.create_seat(
        create_seat_payload(
            section_id,
            row_label=row_label,
            seat_number=seat_number,
            season_start_date=season_start_date,
            season_end_date=season_end_date,
        ),
        _BOX,
    )
    return get_success_data(resp)


def create_account(full_name="Test Holder", email=None, consecutive_seasons=None):
    overrides = {"full_name": full_name, "email": email or unique_email()}
    if consecutive_seasons is not None:
        overrides["consecutive_seasons"] = consecutive_seasons
    resp = api_client.create_account(create_account_payload(**overrides), _BOX)
    return get_success_data(resp)


def create_season_plan(plan_type="FULL", price_multiplier_bps=10000,
                       includes_playoffs=None, game_count=41, name="Full 2026"):
    overrides = {
        "name": name,
        "plan_type": plan_type,
        "game_count": game_count,
        "price_multiplier_bps": price_multiplier_bps,
    }
    if includes_playoffs is not None:
        overrides["includes_playoffs"] = includes_playoffs
    resp = api_client.create_season_plan(create_season_plan_payload(**overrides), _BOX)
    return get_success_data(resp)


def create_subscription(account_id, season_plan_id):
    resp = api_client.create_subscription(
        create_subscription_payload(account_id, season_plan_id), _BOX
    )
    return get_success_data(resp)


def create_seat_assignment(subscription_id, seat_id):
    resp = api_client.create_seat_assignment(
        create_seat_assignment_payload(subscription_id, seat_id), _BOX
    )
    return get_success_data(resp)


def grant_points(account_id, points):
    resp = api_client.grant_points(account_id, {"priority_points": points}, _BOX)
    return get_success_data(resp)


def create_parking_zone(capacity=10, price_cents=30000, name="Lot A"):
    resp = api_client.create_parking_zone(
        create_parking_zone_payload(name=name, capacity=capacity, price_cents=price_cents), _BOX
    )
    return get_success_data(resp)


# --------------------------------------------------------------------------
# Tier 2 / 3: a PENDING subscription with N assigned seats, optionally activated
# --------------------------------------------------------------------------
def setup_pending_subscription(
    base_price_cents=200000,
    plan_type="FULL",
    price_multiplier_bps=10000,
    includes_playoffs=None,
    consecutive_seasons=None,
    section_name="Lower 100",
    seat_number=1,
    season_start_date=SEASON_START,
    season_end_date=SEASON_END,
    grant_account_points=None,
):
    """Build section + one seat + plan + account + PENDING subscription with one
    ASSIGNED seat. Returns a dict of all created resources (not yet activated).

    grant_account_points: if set, calls grant-points on the account BEFORE the
    subscription is priced so loyalty tier scenarios can be staged.
    """
    section = create_section(base_price_cents=base_price_cents, name=section_name)
    seat = create_seat(section["id"], seat_number=seat_number,
                       season_start_date=season_start_date, season_end_date=season_end_date)
    plan = create_season_plan(
        plan_type=plan_type,
        price_multiplier_bps=price_multiplier_bps,
        includes_playoffs=includes_playoffs,
    )
    cs = consecutive_seasons if consecutive_seasons is not None else 0
    account = create_account(consecutive_seasons=cs)
    if grant_account_points is not None:
        account = grant_points(account["id"], grant_account_points)
    subscription = create_subscription(account["id"], plan["id"])
    assignment = create_seat_assignment(subscription["id"], seat["id"])
    return {
        "section": section,
        "seat": seat,
        "plan": plan,
        "account": account,
        "subscription": subscription,
        "assignment": assignment,
    }


def setup_active_subscription(**kwargs):
    """setup_pending_subscription + activate. Returns the same dict with the
    activated subscription replacing the PENDING one and an 'activated' key
    holding the activate response payload (carries the post-activation version).
    """
    ctx = setup_pending_subscription(**kwargs)
    resp = api_client.activate_subscription(ctx["subscription"]["id"], _BOX)
    activated = get_success_data(resp)
    ctx["subscription"] = activated
    ctx["activated"] = activated
    return ctx


# --------------------------------------------------------------------------
# Tier 4: financed (payment plan) scenarios
# --------------------------------------------------------------------------
def setup_active_subscription_with_payment_plan(installment_count=4, **kwargs):
    """Active subscription financed by an ACTIVE payment plan. Returns the
    setup_active_subscription dict plus a 'payment_plan' key."""
    ctx = setup_active_subscription(**kwargs)
    resp = api_client.create_payment_plan(
        create_payment_plan_payload(ctx["subscription"]["id"], installment_count=installment_count),
        _FIN,
    )
    ctx["payment_plan"] = get_success_data(resp)
    return ctx


def list_plan_installments(plan_id):
    """Return the installment rows under a plan, sorted by sequence."""
    resp = api_client.list_payment_plan_installments(plan_id, _FIN)
    data = get_success_data(resp)
    return sorted(data, key=lambda i: i["sequence"])


def pay_installment(plan_id, seq):
    resp = api_client.pay_installment(plan_id, seq, _FIN)
    return get_success_data(resp)


# --------------------------------------------------------------------------
# Tier 3: ticket-transfer scenarios
# --------------------------------------------------------------------------
def setup_listed_resale(listing_price_cents=20000, **kwargs):
    """Active subscription owned by a holder, with a RESALE transfer in LISTED
    state. Returns the active-subscription dict plus 'transfer' and a separate
    'buyer' account ready for complete-sale."""
    ctx = setup_active_subscription(**kwargs)
    holder_id = ctx["account"]["id"]
    holder_headers = make_account_holder_headers(holder_id)
    resp = api_client.create_ticket_transfer(
        create_ticket_transfer_payload(
            ctx["assignment"]["id"], "RESALE", listing_price_cents=listing_price_cents
        ),
        holder_headers,
    )
    transfer = get_success_data(resp)
    resp = api_client.list_ticket_transfer(transfer["id"], holder_headers)
    ctx["transfer"] = get_success_data(resp)
    ctx["buyer"] = create_account(full_name="Buyer")
    return ctx


def setup_pending_forward(**kwargs):
    """Active subscription owned by a holder, with a FORWARD transfer in PENDING
    state and an ACTIVE recipient account. Returns active dict plus 'transfer'
    and 'recipient'."""
    ctx = setup_active_subscription(**kwargs)
    holder_id = ctx["account"]["id"]
    recipient = create_account(full_name="Recipient")
    resp = api_client.create_ticket_transfer(
        create_ticket_transfer_payload(
            ctx["assignment"]["id"], "FORWARD", recipient_account_id=recipient["id"]
        ),
        make_account_holder_headers(holder_id),
    )
    ctx["transfer"] = get_success_data(resp)
    ctx["recipient"] = recipient
    return ctx


# --------------------------------------------------------------------------
# Tier 4: parking-capacity scenarios
# --------------------------------------------------------------------------
def add_parking_pass(subscription_id, zone_id):
    resp = api_client.create_parking_addon(
        create_parking_addon_payload(subscription_id, zone_id), _BOX
    )
    return get_success_data(resp)


def setup_zone_at_capacity(capacity, active_subscriptions=None):
    """Create a zone with the given capacity and fill it to `capacity` ACTIVE
    passes, returning (zone, [passes], [active_subscription_ctxs], spare_ctx).

    `spare_ctx` is one extra ACTIVE subscription (in a separate section) that
    can attempt the capacity+1 add-on. Each filling subscription gets its own
    section/seat to avoid window collisions.
    """
    zone = create_parking_zone(capacity=capacity, name="Lot Cap")
    passes = []
    filled_ctxs = []
    for i in range(capacity):
        ctx = setup_active_subscription(section_name=f"Cap Sec {i}", seat_number=1)
        passes.append(add_parking_pass(ctx["subscription"]["id"], zone["id"]))
        filled_ctxs.append(ctx)
    spare = setup_active_subscription(section_name="Cap Spare", seat_number=1)
    # Re-read zone so active_pass_count reflects the fills.
    zone = get_success_data(api_client.get_parking_zone(zone["id"], _BOX))
    return zone, passes, filled_ctxs, spare


# --------------------------------------------------------------------------
# Tier 1: relocation staging
# --------------------------------------------------------------------------
def setup_relocating_subscription(target_seat_count=1, target_in_same_section=True):
    """Active subscription holding one seat, moved into RELOCATING state, with
    one or more AVAILABLE target seats prepared. Returns a dict with keys
    section, seat (original), targets (list), plan, account, subscription
    (RELOCATING), and version_after_begin.
    """
    ctx = setup_active_subscription(section_name="Reloc Sec")
    sub_id = ctx["subscription"]["id"]
    version = ctx["subscription"]["version"]
    targets = []
    for i in range(target_seat_count):
        if target_in_same_section:
            tseat = create_seat(ctx["section"]["id"], row_label="B", seat_number=10 + i)
        else:
            other = create_section(name=f"Other Sec {i}")
            tseat = create_seat(other["id"], row_label="B", seat_number=10 + i)
        targets.append(tseat)
    resp = api_client.relocate_subscription(
        sub_id, {"expected_subscription_version": version}, _BOX
    )
    relocating = get_success_data(resp)
    ctx["subscription"] = relocating
    ctx["targets"] = targets
    ctx["version_after_begin"] = relocating["version"]
    return ctx


__all__ = [
    "create_section",
    "create_seat",
    "create_account",
    "create_season_plan",
    "create_subscription",
    "create_seat_assignment",
    "grant_points",
    "create_parking_zone",
    "setup_pending_subscription",
    "setup_active_subscription",
    "setup_active_subscription_with_payment_plan",
    "list_plan_installments",
    "pay_installment",
    "setup_listed_resale",
    "setup_pending_forward",
    "add_parking_pass",
    "setup_zone_at_capacity",
    "setup_relocating_subscription",
]
