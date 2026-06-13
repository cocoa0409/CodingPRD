"""Composite setup helpers for multi-step test prerequisites (CSA Box API).

Uses get_success_data() (lenient validator) internally so setup failures produce
clear "Setup failed" errors instead of confusing assertion failures.

Each test runs against a fresh, empty database — every fixture builds its whole
precondition chain from scratch using only PRD-declared endpoints. Member is
entity-backed, so member-actor calls thread make_member_headers(member["id"]).
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from . import factories as f
from .test_users import (
    TEST_USERS,
    make_member_headers,
)

FM = TEST_USERS["farm_manager_headers"]
DC = TEST_USERS["delivery_coordinator_headers"]
PA = TEST_USERS["platform_admin_headers"]


# ─── Primitive builders ──────────────────────────────────────────────────────

def register_member(tier=None, email=None, full_name="Test Member"):
    """Register a member (Anonymous). Returns the member dict.

    Omits sliding_scale_tier unless given, so the server-side default applies.
    """
    payload = f.create_member_payload(full_name=full_name)
    if email is not None:
        payload["email"] = email
    if tier is not None:
        payload["sliding_scale_tier"] = tier
    return get_success_data(api_client.create_member(payload))


def set_clock(iso_instant):
    """Advance the simulated clock to the given ISO instant (PlatformAdmin)."""
    return api_client.set_clock({"to_iso8601": iso_instant}, PA)


def get_season_version(season_id):
    """Read the season's current version (for OCC expected_season_version)."""
    season = get_success_data(api_client.get_season(season_id, FM))
    return season["version"]


# ─── Tier 1/2: Catalog + open season ─────────────────────────────────────────

def setup_open_season(week_count=12, total_share_capacity=100,
                      signup_close_date="2026-12-30T00:00:00Z",
                      first_delivery_date="2026-07-01T00:00:00Z",
                      site_kind="PICKUP", site_weekly_capacity=100,
                      delivery_surcharge_cents=None,
                      share_size="MEDIUM", base_price_cents=50000, items_per_box=8,
                      season_name="Test Season"):
    """Create a season + one site + one share type, then OPEN the season.

    Returns dict with keys: season, site, share (each the created entity dict).
    """
    season = get_success_data(api_client.create_season(
        f.create_season_payload(
            name=season_name, week_count=week_count,
            first_delivery_date=first_delivery_date,
            signup_close_date=signup_close_date,
            total_share_capacity=total_share_capacity),
        FM))

    site_overrides = {"name": "Downtown", "kind": site_kind,
                      "weekly_capacity": site_weekly_capacity}
    if delivery_surcharge_cents is not None:
        site_overrides["delivery_surcharge_cents"] = delivery_surcharge_cents
    site = get_success_data(api_client.create_pickup_site(
        f.create_pickup_site_payload(season["id"], **site_overrides), DC))

    share = get_success_data(api_client.create_share_type(
        f.create_share_type_payload(
            season["id"], size=share_size,
            base_price_cents=base_price_cents, items_per_box=items_per_box),
        FM))

    get_success_data(api_client.open_season(season["id"], FM))
    return {"season": season, "site": site, "share": share}


def add_add_on(season_id, kind="EGGS", weekly_price_cents=800, weekly_supply_cap=50):
    """Create an add-on for the season. Returns the add-on dict."""
    return get_success_data(api_client.create_add_on(
        f.create_add_on_payload(
            season_id, kind=kind,
            weekly_price_cents=weekly_price_cents, weekly_supply_cap=weekly_supply_cap),
        FM))


# ─── Tier 2: Pending subscription ────────────────────────────────────────────

def setup_pending_subscription(tier="BASELINE", working_share_opt_in=None,
                               base_price_cents=50000, week_count=12,
                               site_kind="PICKUP", delivery_surcharge_cents=None,
                               signup_close_date="2026-12-30T00:00:00Z",
                               total_share_capacity=100, site_weekly_capacity=100,
                               share_size="MEDIUM", items_per_box=8,
                               clock=None):
    """OPEN season + member + a PENDING_PAYMENT subscription.

    Returns dict: season, site, share, member, member_headers, subscription.
    """
    base = setup_open_season(
        week_count=week_count, total_share_capacity=total_share_capacity,
        signup_close_date=signup_close_date, site_kind=site_kind,
        site_weekly_capacity=site_weekly_capacity,
        delivery_surcharge_cents=delivery_surcharge_cents,
        share_size=share_size, base_price_cents=base_price_cents,
        items_per_box=items_per_box)

    if clock is not None:
        set_clock(clock)

    member = register_member(tier=tier)
    mh = make_member_headers(member["id"])

    sub_overrides = {}
    if working_share_opt_in is not None:
        sub_overrides["working_share_opt_in"] = working_share_opt_in
    subscription = get_success_data(api_client.create_subscription(
        f.create_subscription_payload(
            base["season"]["id"], member["id"], base["share"]["id"],
            base["site"]["id"], **sub_overrides),
        mh))

    return {
        "season": base["season"], "site": base["site"], "share": base["share"],
        "member": member, "member_headers": mh, "subscription": subscription,
    }


# ─── Tier 3: Confirmed subscription ──────────────────────────────────────────

def confirm_subscription(season_id, subscription_id, headers=FM):
    """Confirm a subscription, reading the current season version for OCC."""
    sea_v = get_season_version(season_id)
    return get_success_data(api_client.confirm_subscription(
        subscription_id, {"expected_season_version": sea_v}, headers))


def setup_confirmed_subscription(tier="BASELINE", working_share_opt_in=None,
                                 base_price_cents=50000, week_count=12,
                                 site_kind="PICKUP", delivery_surcharge_cents=None,
                                 signup_close_date="2026-12-30T00:00:00Z",
                                 total_share_capacity=100, site_weekly_capacity=100,
                                 share_size="MEDIUM", items_per_box=8,
                                 clock=None):
    """OPEN season + member + CONFIRMED subscription (boxes generated).

    Returns dict: season, site, share, member, member_headers, subscription
    (the confirmed subscription dict).
    """
    ctx = setup_pending_subscription(
        tier=tier, working_share_opt_in=working_share_opt_in,
        base_price_cents=base_price_cents, week_count=week_count,
        site_kind=site_kind, delivery_surcharge_cents=delivery_surcharge_cents,
        signup_close_date=signup_close_date, total_share_capacity=total_share_capacity,
        site_weekly_capacity=site_weekly_capacity, share_size=share_size,
        items_per_box=items_per_box, clock=clock)

    confirmed = confirm_subscription(ctx["season"]["id"], ctx["subscription"]["id"])
    ctx["subscription"] = confirmed
    return ctx


def list_weekly_boxes(subscription_id, member_headers):
    """Return the subscription's weekly boxes (sorted by created_at ASC =
    week_index ASC), as a list."""
    res = api_client.list_subscription_weekly_boxes(
        subscription_id, member_headers, params={"limit": 100})
    data, _meta = _paginated(res)
    return data


def box_for_week(subscription_id, member_headers, week_index):
    """Return the WeeklyBox dict for a 1-based week_index."""
    boxes = list_weekly_boxes(subscription_id, member_headers)
    for b in boxes:
        if b["week_index"] == week_index:
            return b
    # Fallback to positional ordering if week_index missing.
    return boxes[week_index - 1]


def _paginated(res):
    """Local helper: extract (data_list, meta) from a list response without the
    strict validator, so setup code stays lenient."""
    body = res.json()
    return body.get("data", []), body.get("meta", {})


# ─── Tier 3: Held-box scenario ───────────────────────────────────────────────

def setup_confirmed_with_refund_hold(week_index=5, clock="2026-06-15T00:00:00Z",
                                     tier="BASELINE", base_price_cents=50000,
                                     week_count=12):
    """CONFIRMED subscription with a REFUND-mode VacationHold on the box at
    `week_index`. Returns dict including: ... box (the held box), hold."""
    ctx = setup_confirmed_subscription(
        tier=tier, base_price_cents=base_price_cents, week_count=week_count, clock=clock)
    box = box_for_week(ctx["subscription"]["id"], ctx["member_headers"], week_index)
    hold = get_success_data(api_client.create_vacation_hold(
        f.create_vacation_hold_payload(ctx["subscription"]["id"], box["id"]),
        ctx["member_headers"]))
    ctx["box"] = box
    ctx["hold"] = hold
    return ctx


# ─── Tier 3: Add-on attached ─────────────────────────────────────────────────

def setup_confirmed_with_addon(kind="EGGS", weekly_price_cents=800, weekly_supply_cap=50,
                               clock="2026-06-15T00:00:00Z", tier="BASELINE",
                               base_price_cents=50000, week_count=12):
    """CONFIRMED subscription + an add-on ATTACHED to it.

    Returns dict including: ... add_on, subscription_add_on.
    """
    # Build catalog with an add-on, then a confirmed subscription manually so the
    # add-on shares the season.
    base = setup_open_season(week_count=week_count, base_price_cents=base_price_cents)
    add_on = add_add_on(base["season"]["id"], kind=kind,
                        weekly_price_cents=weekly_price_cents,
                        weekly_supply_cap=weekly_supply_cap)
    if clock is not None:
        set_clock(clock)
    member = register_member(tier=tier)
    mh = make_member_headers(member["id"])
    sub = get_success_data(api_client.create_subscription(
        f.create_subscription_payload(
            base["season"]["id"], member["id"], base["share"]["id"], base["site"]["id"]),
        mh))
    confirmed = confirm_subscription(base["season"]["id"], sub["id"])
    sao = get_success_data(api_client.create_subscription_add_on(
        f.create_subscription_add_on_payload(confirmed["id"], add_on["id"]), mh))
    return {
        "season": base["season"], "site": base["site"], "share": base["share"],
        "member": member, "member_headers": mh, "subscription": confirmed,
        "add_on": add_on, "subscription_add_on": sao,
    }


# ─── Tier 3: Working-share with completed shift ──────────────────────────────

def setup_confirmed_working_share(tier="BASELINE", base_price_cents=50000,
                                  week_count=12, share_size="MEDIUM", items_per_box=8,
                                  clock=None):
    """CONFIRMED subscription with working_share_opt_in == true.

    Returns dict: season, site, share, member, member_headers, subscription.
    """
    return setup_confirmed_subscription(
        tier=tier, working_share_opt_in=True, base_price_cents=base_price_cents,
        week_count=week_count, share_size=share_size, items_per_box=items_per_box,
        clock=clock)


def schedule_shift(subscription_id, member_headers, scheduled_date, hours):
    """Schedule a work-share shift. Returns the shift dict."""
    return get_success_data(api_client.create_work_share_shift(
        subscription_id,
        f.create_work_share_shift_payload(scheduled_date=scheduled_date, hours=hours),
        member_headers))


def complete_shift(shift_id):
    """Complete a work-share shift (FarmManager). Returns the shift dict."""
    return get_success_data(api_client.complete_work_share_shift(shift_id, FM))


# ─── Tier 3: Delivered first box (axis activation) ───────────────────────────

def setup_first_box_delivered(clock_confirm="2026-06-15T00:00:00Z",
                              clock_deliver="2026-07-01T08:00:00Z",
                              tier="BASELINE", base_price_cents=50000, week_count=12):
    """CONFIRMED subscription, then week-1 box packed and delivered (first
    delivery). Returns dict including: ... box (week-1, now DELIVERED)."""
    ctx = setup_confirmed_subscription(
        tier=tier, base_price_cents=base_price_cents, week_count=week_count,
        clock=clock_confirm)
    box = box_for_week(ctx["subscription"]["id"], ctx["member_headers"], 1)
    set_clock(clock_deliver)
    get_success_data(api_client.pack_weekly_box(box["id"], FM))
    delivered = get_success_data(api_client.deliver_weekly_box(box["id"], FM))
    ctx["box"] = delivered
    return ctx


# ─── Tier 3: Waitlist promoted to OFFERED ────────────────────────────────────

def setup_offered_waitlist(clock="2026-06-01T00:00:00Z", total_share_capacity=5,
                           site_weekly_capacity=5, base_price_cents=50000,
                           week_count=12, signup_close_date="2026-12-30T00:00:00Z"):
    """OPEN season + a WAITING entry promoted to OFFERED (offer_expires_at set).

    Returns dict: season, site, share, member, member_headers, waitlist_entry.
    """
    base = setup_open_season(
        week_count=week_count, total_share_capacity=total_share_capacity,
        site_weekly_capacity=site_weekly_capacity, base_price_cents=base_price_cents,
        signup_close_date=signup_close_date)
    set_clock(clock)
    member = register_member(tier="BASELINE")
    mh = make_member_headers(member["id"])
    wl = get_success_data(api_client.create_waitlist_entry(
        f.create_waitlist_entry_payload(
            base["season"]["id"], member["id"], base["share"]["id"], base["site"]["id"])))
    sea_v = get_season_version_via_dc(base["season"]["id"])
    promoted = get_success_data(api_client.promote_waitlist(
        base["season"]["id"],
        f.promote_waitlist_payload(base["share"]["id"], base["site"]["id"], sea_v),
        DC))
    return {
        "season": base["season"], "site": base["site"], "share": base["share"],
        "member": member, "member_headers": mh, "waitlist_entry": promoted,
    }


def get_season_version_via_dc(season_id):
    """Read season version as DeliveryCoordinator (used before promotion)."""
    season = get_success_data(api_client.get_season(season_id, DC))
    return season["version"]


# ─── Tier 4: Capacity at boundary ────────────────────────────────────────────

def setup_capacity_one_remaining(total_share_capacity=2, site_weekly_capacity=100,
                                 base_price_cents=50000, week_count=12,
                                 clock="2026-06-01T00:00:00Z"):
    """OPEN season with `total_share_capacity` confirmed slots, ONE already
    confirmed, plus a second PENDING_PAYMENT subscription ready to confirm at
    the boundary. Returns dict: season, site, share, sub_b, member_b_headers."""
    base = setup_open_season(
        week_count=week_count, total_share_capacity=total_share_capacity,
        site_weekly_capacity=site_weekly_capacity, base_price_cents=base_price_cents,
        signup_close_date="2026-12-30T00:00:00Z")
    set_clock(clock)

    member_a = register_member(tier="BASELINE")
    mha = make_member_headers(member_a["id"])
    sub_a = get_success_data(api_client.create_subscription(
        f.create_subscription_payload(
            base["season"]["id"], member_a["id"], base["share"]["id"], base["site"]["id"]),
        mha))

    member_b = register_member(tier="BASELINE")
    mhb = make_member_headers(member_b["id"])
    sub_b = get_success_data(api_client.create_subscription(
        f.create_subscription_payload(
            base["season"]["id"], member_b["id"], base["share"]["id"], base["site"]["id"]),
        mhb))

    confirm_subscription(base["season"]["id"], sub_a["id"])

    return {
        "season": base["season"], "site": base["site"], "share": base["share"],
        "sub_a": sub_a, "sub_b": sub_b, "member_b_headers": mhb,
    }
