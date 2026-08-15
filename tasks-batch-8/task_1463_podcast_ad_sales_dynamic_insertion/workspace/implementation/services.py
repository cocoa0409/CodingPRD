"""Business logic: change-tracked mutations, forecast/slot/delivery
recomputes, state-machine cascades, measurement finalization, dynamic
insertion selection, billing math, and make-good settlement."""

from datetime import timedelta
from decimal import Decimal

import db
from helpers import parse_dt, render_like, round_half_up, now_timestamp

# --- Constants from the scaffold's calculation tables -------------------------
FORECAST_HORIZON_DAYS = 30
CAP_NUMERATORS = {"CLEAR": 95, "FLAGGED": 70, "SUSPENDED": 0}  # per-100
POSITION_MULT = {"PRE_ROLL": 800, "MID_ROLL": 1000, "POST_ROLL": 600}  # per mille
ATTRIBUTION_WINDOW_DAYS = 30

FORMAT_TO_KIND = {"HOST_READ": "HOST_READ_SCRIPT", "PRODUCED_SPOT": "PRODUCED_AUDIO"}


class Changes:
    """Unit-of-work: stages field mutations, then commits one version bump
    (+1) and one updated_at refresh per actually-changed entity."""

    def __init__(self):
        self.dirty = {}

    def update(self, entity, **fields):
        changed = False
        for key, value in fields.items():
            if entity.get(key) != value:
                entity[key] = value
                changed = True
        if changed:
            self.dirty[id(entity)] = entity

    def commit(self):
        ts = now_timestamp()
        for entity in self.dirty.values():
            if "version" in entity:
                entity["version"] += 1
                entity["updated_at"] = ts
        self.dirty.clear()


# --- Derived counters ---------------------------------------------------------


def recompute_show(show, ch: Changes):
    """inventory_forecast + reservation pool for one show."""
    now = db.current_dt()
    horizon_end = now + timedelta(days=FORECAST_HORIZON_DAYS)
    eligible = 0
    for ep in db.episodes.values():
        if ep["show_id"] != show["id"]:
            continue
        if ep["status"] not in ("SCHEDULED", "PUBLISHED"):
            continue
        pub = parse_dt(ep["publish_at"])
        if pub is not None and now <= pub <= horizon_end:
            eligible += 1
    cap_num = CAP_NUMERATORS[show["brand_safety_tier"]]
    forecast = (show["avg_downloads_30d"] * eligible * cap_num) // 100
    reserved = sum(
        li["reserved_impressions"]
        for li in db.line_items.values()
        if li.get("show_id") == show["id"] and li["status"] == "ACTIVE"
    )
    ch.update(
        show,
        forecast_impressions=forecast,
        reserved_impressions=reserved,
        available_impressions=forecast - reserved,
    )


def recompute_all_shows(ch: Changes):
    for show in db.shows.values():
        recompute_show(show, ch)


def flight_contains(campaign, instant) -> bool:
    """Half-open [flight_start, flight_end) containment."""
    start = parse_dt(campaign["flight_start"])
    end = parse_dt(campaign["flight_end"])
    return start <= instant < end


def flights_overlap(a_start, a_end, b_start, b_end) -> bool:
    """Half-open overlap: a_start < b_end AND b_start < a_end."""
    return a_start < b_end and b_start < a_end


def recompute_episode_slots(episode, ch: Changes):
    """slots_in_use = ACTIVE episode-targeted line items whose campaign
    flight contains the current logical clock instant."""
    now = db.current_dt()
    count = 0
    for li in db.line_items.values():
        if li.get("episode_id") != episode["id"] or li["status"] != "ACTIVE":
            continue
        campaign = db.campaigns.get(li["campaign_id"])
        if campaign is not None and flight_contains(campaign, now):
            count += 1
    ch.update(episode, slots_in_use=count)


def recompute_all_slots(ch: Changes):
    for ep in db.episodes.values():
        recompute_episode_slots(ep, ch)


def campaign_delivered_count(campaign_id) -> int:
    return sum(
        1
        for imp in db.impressions.values()
        if imp["campaign_id"] == campaign_id and imp["billable_final"] is True
    )


def recompute_campaign_delivered(campaign, ch: Changes):
    ch.update(campaign, delivered_impressions=campaign_delivered_count(campaign["id"]))


def line_item_target_show(li):
    """The show a line item sells against: direct run-of-show target, or the
    owning show of the targeted episode."""
    if li.get("show_id"):
        return db.shows.get(li["show_id"])
    if li.get("episode_id"):
        ep = db.episodes.get(li["episode_id"])
        if ep is not None:
            return db.shows.get(ep["show_id"])
    return None


def release_line_item(li, ch: Changes):
    """Reservation / slot release after a pause or end."""
    if li.get("show_id"):
        show = db.shows.get(li["show_id"])
        if show is not None:
            recompute_show(show, ch)
    if li.get("episode_id"):
        ep = db.episodes.get(li["episode_id"])
        if ep is not None:
            recompute_episode_slots(ep, ch)


def pause_line_item(li, ch: Changes):
    if li["status"] != "ACTIVE":
        return
    ch.update(li, status="PAUSED")
    release_line_item(li, ch)


def end_line_item(li, ch: Changes):
    if li["status"] not in ("ACTIVE", "PAUSED"):
        return
    was_active = li["status"] == "ACTIVE"
    ch.update(li, status="ENDED")
    if was_active:
        release_line_item(li, ch)


# --- Cascades -----------------------------------------------------------------


def cascade_show_suspended(show, ch: Changes):
    """SUSPEND side effects: pause every ACTIVE line item targeting the show
    or any of its episodes; bubble-pause campaigns left with no ACTIVE line
    item among those whose line items were paused by this cascade."""
    episode_ids = {e["id"] for e in db.episodes.values() if e["show_id"] == show["id"]}
    affected_campaigns = set()
    for li in db.line_items.values():
        if li["status"] != "ACTIVE":
            continue
        targets_show = li.get("show_id") == show["id"] or li.get("episode_id") in episode_ids
        if targets_show:
            pause_line_item(li, ch)
            affected_campaigns.add(li["campaign_id"])
    for campaign_id in affected_campaigns:
        campaign = db.campaigns.get(campaign_id)
        if campaign is None or campaign["status"] != "ACTIVE":
            continue
        has_active = any(
            li["campaign_id"] == campaign_id and li["status"] == "ACTIVE"
            for li in db.line_items.values()
        )
        if not has_active:
            ch.update(campaign, status="PAUSED")


def cascade_advertiser_suspended(advertiser, ch: Changes):
    """ACTIVE campaigns of the advertiser -> PAUSED; their ACTIVE line items
    -> PAUSED with reservations released."""
    for campaign in db.campaigns.values():
        if campaign["advertiser_id"] != advertiser["id"] or campaign["status"] != "ACTIVE":
            continue
        ch.update(campaign, status="PAUSED")
        for li in db.line_items.values():
            if li["campaign_id"] == campaign["id"] and li["status"] == "ACTIVE":
                pause_line_item(li, ch)


def cascade_copy_revoked(copy, ch: Changes):
    """APPROVED -> CHANGES_REQUESTED revocation: pause ACTIVE line items
    referencing the copy (no campaign bubble-pause on this cascade)."""
    for li in db.line_items.values():
        if li["ad_copy_id"] == copy["id"] and li["status"] == "ACTIVE":
            pause_line_item(li, ch)


# --- Episode finalization (final measurement lens) ----------------------------


def finalize_episode(episode, ch: Changes):
    """PUBLISHED -> MEASURED: final qualification, impression cascade,
    campaign delivery recomputes, forecast recompute."""
    publish_at = parse_dt(episode["publish_at"])
    window_end = publish_at + timedelta(days=episode["measurement_window_days"])
    ep_downloads = [d for d in db.downloads.values() if d["episode_id"] == episode["id"]]

    # Candidates: HUMAN and occurred_at inside [publish_at, window_end] (inclusive).
    best_by_group = {}
    for d in ep_downloads:
        if d["user_agent_class"] != "HUMAN":
            continue
        occurred = parse_dt(d["occurred_at"])
        if occurred is None or not (publish_at <= occurred <= window_end):
            continue
        group = (d["listener_key"], occurred.date())
        current = best_by_group.get(group)
        if current is None:
            best_by_group[group] = d
        else:
            current_dt = parse_dt(current["occurred_at"])
            if (occurred, d["_seq"]) < (current_dt, current["_seq"]):
                best_by_group[group] = d

    winners = {d["id"] for d in best_by_group.values()}
    measured = 0
    for d in ep_downloads:
        qualified = d["id"] in winners
        d["qualified_final"] = qualified
        if qualified:
            measured += 1
    ch.update(episode, status="MEASURED", measured_download_count=measured)

    affected_campaigns = set()
    for d in ep_downloads:
        for imp in db.impressions.values():
            if imp["download_id"] == d["id"]:
                imp["billable_final"] = d["qualified_final"]
                affected_campaigns.add(imp["campaign_id"])
    for campaign_id in affected_campaigns:
        campaign = db.campaigns.get(campaign_id)
        if campaign is not None:
            recompute_campaign_delivered(campaign, ch)

    show = db.shows.get(episode["show_id"])
    if show is not None:
        recompute_show(show, ch)


# --- Dynamic insertion selector -----------------------------------------------


def select_line_items(episode, occurred_dt):
    """Eligible: line item ACTIVE, campaign ACTIVE, occurred_at inside the
    half-open flight, target matches the episode or its show. Ranked by
    priority DESC, then created_at ASC; top slot_capacity win."""
    eligible = []
    for li in db.line_items.values():
        if li["status"] != "ACTIVE":
            continue
        target_match = li.get("episode_id") == episode["id"] or li.get("show_id") == episode[
            "show_id"
        ]
        if not target_match:
            continue
        campaign = db.campaigns.get(li["campaign_id"])
        if campaign is None or campaign["status"] != "ACTIVE":
            continue
        if not flight_contains(campaign, occurred_dt):
            continue
        eligible.append(li)
    eligible.sort(key=lambda li: (-li["priority"], li["_seq"]))
    return eligible[: episode["slot_capacity"]]


# --- Campaign END / reconcile -------------------------------------------------


def evaluate_make_good_fulfillment(campaign, ch: Changes):
    for mg in db.make_goods.values():
        if mg["campaign_id"] == campaign["id"] and mg["status"] == "ACCEPTED":
            bonus = campaign["delivered_impressions"] - mg["baseline_delivered_impressions"]
            if bonus >= mg["granted_impressions"]:
                ch.update(mg, status="FULFILLED")
            else:
                ch.update(mg, status="EXPIRED")


def maybe_reconcile(campaign, ch: Changes):
    """ENDED -> RECONCILED when the invoice is PAID and no make-good is in
    OFFERED or ACCEPTED."""
    if campaign["status"] != "ENDED":
        return
    invoice = next(
        (inv for inv in db.invoices.values() if inv["campaign_id"] == campaign["id"]), None
    )
    if invoice is None or invoice["status"] != "PAID":
        return
    open_mg = any(
        mg["campaign_id"] == campaign["id"] and mg["status"] in ("OFFERED", "ACCEPTED")
        for mg in db.make_goods.values()
    )
    if not open_mg:
        ch.update(campaign, status="RECONCILED")


def end_campaign(campaign, ch: Changes):
    """ACTIVE/PAUSED -> ENDED: end line items, recompute delivery, evaluate
    make-good fulfillment, then the reconcile check."""
    for li in db.line_items.values():
        if li["campaign_id"] == campaign["id"] and li["status"] in ("ACTIVE", "PAUSED"):
            end_line_item(li, ch)
    recompute_campaign_delivered(campaign, ch)
    evaluate_make_good_fulfillment(campaign, ch)
    ch.update(campaign, status="ENDED")
    maybe_reconcile(campaign, ch)


# --- Billing ------------------------------------------------------------------


def billing_breakdown(campaign):
    """invoice_billing: per-line round_half_up, then sum.

    Returns (lines, delivered_impressions_billed, shortfall_impressions,
    gross_cents) with gross selected by the campaign's billing model."""
    lines = []
    delivered = 0
    line_items = sorted(
        (li for li in db.line_items.values() if li["campaign_id"] == campaign["id"]),
        key=lambda li: li["_seq"],
    )
    for li in line_items:
        billable = sum(
            1
            for imp in db.impressions.values()
            if imp["line_item_id"] == li["id"] and imp["billable_final"] is True
        )
        if billable < 1:
            continue
        line_cents = round_half_up(
            Decimal(billable)
            * campaign["cpm_cents"]
            * POSITION_MULT[li["position"]]
            / Decimal(1_000_000)
        )
        lines.append(
            {
                "line_item_id": li["id"],
                "position": li["position"],
                "billable_impressions": billable,
                "line_cents": line_cents,
            }
        )
        delivered += billable
    shortfall = max(0, campaign["booked_impressions"] - delivered)
    if campaign["billing_model"] == "BOOKED_GROSS":
        gross = round_half_up(Decimal(campaign["booked_impressions"]) * campaign["cpm_cents"] / Decimal(1000))
    else:
        gross = sum(line["line_cents"] for line in lines)
    return lines, delivered, shortfall, gross


def commission_and_net(campaign, gross_cents, shortfall_impressions, credit_cents):
    """invoice_commission pinned order: credit (caller-computed) ->
    commission on post-credit gross -> net."""
    advertiser = db.advertisers.get(campaign["advertiser_id"])
    commission = 0
    if advertiser is not None and advertiser.get("agency_id"):
        agency = db.agencies.get(advertiser["agency_id"])
        if agency is not None:
            commission = round_half_up(
                Decimal(gross_cents - credit_cents) * agency["commission_bps"] / Decimal(10000)
            )
    net = gross_cents - commission - credit_cents
    return commission, net


def shortfall_credit(campaign, shortfall_impressions) -> int:
    return round_half_up(
        Decimal(shortfall_impressions) * campaign["cpm_cents"] / Decimal(1000)
    )


# --- Reports ------------------------------------------------------------------


def campaign_report(campaign):
    delivered = campaign_delivered_count(campaign["id"])
    provisional = sum(
        1
        for imp in db.impressions.values()
        if imp["campaign_id"] == campaign["id"] and imp["billable_provisional"] is True
    )
    shortfall = max(0, campaign["booked_impressions"] - delivered)
    promo = pixel = 0
    for ev in db.attribution_events.values():
        if ev["campaign_id"] == campaign["id"] and ev["attributed"] is True:
            if ev["kind"] == "PROMO_CODE":
                promo += 1
            elif ev["kind"] == "PIXEL":
                pixel += 1
    lines, _delivered_billed, _shortfall, gross = billing_breakdown(campaign)
    gross_estimate = gross
    if delivered == 0:
        effective_cpm = 0
    else:
        effective_cpm = round_half_up(Decimal(gross_estimate) * 1000 / Decimal(delivered))
    return {
        "campaign_id": campaign["id"],
        "status": campaign["status"],
        "booked_impressions": campaign["booked_impressions"],
        "delivered_impressions": delivered,
        "provisional_delivered_impressions": provisional,
        "shortfall_impressions": shortfall,
        "attributed_promo_code_count": promo,
        "attributed_pixel_count": pixel,
        "gross_cents_estimate": gross_estimate,
        "effective_cpm_cents": effective_cpm,
    }


def extend_flight_end(campaign, extension_days, ch: Changes):
    """Make-good acceptance: flight_end += extension_days, rendered in the
    original timestamp style."""
    end_dt = parse_dt(campaign["flight_end"]) + timedelta(days=extension_days)
    ch.update(
        campaign,
        status="ACTIVE",
        flight_end=render_like(campaign["flight_end"], end_dt),
    )
