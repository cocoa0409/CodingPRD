"""AdPlacement endpoints: booking, insertion, reconciliation, cancellation.

PRD §3.5 (reservation + pricing), §3.6 (insert/cancel + exhaustion), §3.7
(reconcile). OCC on campaign.version guards create (PRD §2.8).
"""

from flask import request

import calc
import common
import db
import errors
import lifecycle
import ownership
import recompute
import serialize
from common import new_common, touch
from response import success, list_success
from routehelpers import auth_and_role, body


def register(app):
    @app.route("/ad-placements", methods=["POST"])
    def create_placement():
        caller = auth_and_role(["Advertiser"])
        data = body()
        # Required FK references (present-and-typed -> resolvable).
        campaign_id = common.require_str(data, "campaign_id")
        episode_id = common.require_str(data, "episode_id")
        # Existence + ownership of the funding campaign (ownership before the
        # episode FK existence, per PRD §2.5).
        campaign = ownership.get_campaign(campaign_id)
        ownership.assert_advertiser_owns_campaign(caller, campaign)
        episode = ownership.get_episode(episode_id)
        # State (priority 5): funding campaign must be ACTIVE to reserve.
        if campaign["status"] != "ACTIVE":
            raise errors.err(errors.ERR_INVALID_STATE, "Funding campaign must be ACTIVE to book a placement")
        # OCC (PRD §2.8): expected_campaign_version is mandatory and must match.
        expected_version = common.require_int(data, "expected_campaign_version")
        if expected_version != campaign["version"]:
            raise errors.err(errors.ERR_STALE_CAMPAIGN_VERSION,
                             "expected_campaign_version does not match the campaign's current version")
        # Position offered (priority 6).
        position = common.require_enum(data, "position", db.POSITIONS)
        if position not in episode["offered_positions"]:
            raise errors.err(errors.ERR_POSITION_NOT_OFFERED, "Position is not offered by this episode")
        # Remaining field well-formedness.
        offset_ms = common.optional_int(data, "offset_ms", 0)
        if offset_ms < 0:
            raise errors.err(errors.ERR_INVALID_REQUEST, "offset_ms must be >= 0")
        ad_duration_ms = common.require_int(data, "ad_duration_ms")
        if ad_duration_ms <= 0:
            raise errors.err(errors.ERR_INVALID_REQUEST, "ad_duration_ms must be > 0")
        forecast_impressions = common.require_int(data, "forecast_impressions")
        if forecast_impressions <= 0:
            raise errors.err(errors.ERR_INVALID_REQUEST, "forecast_impressions must be > 0")
        # Pricing: estimated cost reserved + frozen at create (PRD §3.5).
        estimated, tier = calc.estimated_placement_cost(
            campaign["bid_cpm_cents"], forecast_impressions,
            campaign["premium_targeting"], episode["fill_rate"])
        # Budget (priority 13): estimated_cost must not exceed available budget.
        if estimated > campaign["available_budget_cents"]:
            raise errors.err(errors.ERR_BUDGET_WOULD_EXCEED,
                             "estimated_cost_cents exceeds the campaign's available budget")
        rec = new_common()
        rec.update({
            "campaign_id": campaign_id,
            "episode_id": episode_id,
            "position": position,
            "offset_ms": offset_ms if position == "MID_ROLL" else 0,
            "ad_duration_ms": ad_duration_ms,
            "forecast_impressions": forecast_impressions,
            "delivered_impressions": 0,
            "estimated_cost_cents": estimated,
            "fill_tier_multiplier": float(tier),
            "final_cost_cents": 0,
            "status": "PROPOSED",
        })
        db.db.ad_placements[rec["id"]] = rec
        # Hold the reserve immediately: ledger recompute bumps campaign.version
        # by one (which is what makes a later stale create fail). PRD §3.5.
        recompute.recompute_campaign_ledger(campaign)
        return success(serialize.ad_placement(rec), status=201)

    @app.route("/ad-placements", methods=["GET"])
    def list_placements():
        auth_and_role(["PlatformAdmin", "Advertiser", "Publisher"])
        limit, offset = common.parse_pagination(request.args)
        items = list(db.db.ad_placements.values())
        campaign_id = request.args.get("campaign_id")
        if campaign_id:
            items = [p for p in items if p["campaign_id"] == campaign_id]
        episode_id = request.args.get("episode_id")
        if episode_id:
            items = [p for p in items if p["episode_id"] == episode_id]
        status = request.args.get("status")
        if status:
            items = [p for p in items if p["status"] == status]
        items = common.sort_by_created(items)
        total = len(items)
        page = common.paginate(items, limit, offset)
        return list_success([serialize.ad_placement(p) for p in page], limit, offset, total)

    @app.route("/ad-placements/<pid>", methods=["GET"])
    def get_placement(pid):
        auth_and_role(["PlatformAdmin", "Advertiser", "Publisher"])
        p = ownership.get_placement(pid)
        return success(serialize.ad_placement(p), status=200)

    @app.route("/ad-placements/<pid>/insert", methods=["POST"])
    def insert_placement(pid):
        caller = auth_and_role(["Advertiser"])
        p = ownership.get_placement(pid)
        ownership.assert_advertiser_owns_placement(caller, p)
        campaign = db.db.ad_campaigns.get(p["campaign_id"])
        episode = db.db.episodes.get(p["episode_id"])
        # State (priority 5): placement PROPOSED, campaign ACTIVE,
        # episode PUBLISHED and media READY.
        if p["status"] != "PROPOSED":
            raise errors.err(errors.ERR_INVALID_STATE, "Only a PROPOSED placement may be inserted")
        if campaign is None or campaign["status"] != "ACTIVE":
            raise errors.err(errors.ERR_INVALID_STATE, "Funding campaign must be ACTIVE to insert")
        if episode is None or episode["publish_status"] != "PUBLISHED" or episode["media_status"] != "READY":
            raise errors.err(errors.ERR_INVALID_STATE, "Episode must be PUBLISHED with READY media to insert")
        show = db.db.shows.get(episode["show_id"])
        # Targeting (priority 7).
        if show is None or show["category"] != campaign["targeting_category"]:
            raise errors.err(errors.ERR_TARGETING_MISMATCH, "Episode show category does not match campaign targeting")
        # Monetization (priority 8).
        if not show["monetization_enabled"]:
            raise errors.err(errors.ERR_MONETIZATION_DISABLED, "Monetization is disabled for this show")
        # MID_ROLL overlap (priority 10).
        if p["position"] == "MID_ROLL" and _midroll_overlaps(p, episode):
            raise errors.err(errors.ERR_MIDROLL_OVERLAP, "MID_ROLL interval overlaps an existing placement")
        # Available slot (priority 12).
        if episode["available_slots"] <= 0:
            raise errors.err(errors.ERR_NO_AVAILABLE_SLOT, "Episode has no available ad slot")
        # Confirm: no re-pricing; placement now counts as filled.
        p["status"] = "INSERTED"
        touch(p)
        recompute.recompute_episode_fill(episode)
        recompute.recompute_campaign_ledger(campaign)
        # Exhaustion boundary (PRD §3.6): if available budget is exactly zero now,
        # campaign ACTIVE -> EXHAUSTED, rejecting remaining PROPOSED placements.
        if campaign["available_budget_cents"] == 0:
            campaign["status"] = "EXHAUSTED"
            touch(campaign)
            lifecycle.reject_proposed_placements(campaign)
        return success(serialize.ad_placement(p), status=200)

    @app.route("/ad-placements/<pid>/reconcile", methods=["POST"])
    def reconcile_placement(pid):
        auth_and_role(["PlatformAdmin"])
        p = ownership.get_placement(pid)
        if p["status"] != "INSERTED":
            raise errors.err(errors.ERR_INVALID_STATE, "Only an INSERTED placement may be reconciled")
        campaign = db.db.ad_campaigns.get(p["campaign_id"])
        # Final billed cost driven by delivered impressions, capped at the reserve.
        final_cost = calc.final_placement_cost(
            campaign["bid_cpm_cents"], p["delivered_impressions"],
            campaign["premium_targeting"], p["fill_tier_multiplier"],
            p["estimated_cost_cents"])
        p["final_cost_cents"] = final_cost
        p["status"] = "DELIVERED"
        touch(p)
        # Move reserve -> spent (ledger recompute). fill_rate unchanged: DELIVERED
        # still counts as filled.
        recompute.recompute_campaign_ledger(campaign)
        episode = db.db.episodes.get(p["episode_id"])
        if episode is not None:
            recompute.recompute_episode_fill(episode)
        return success(serialize.ad_placement(p), status=200)

    @app.route("/ad-placements/<pid>/cancel", methods=["POST"])
    def cancel_placement(pid):
        caller = auth_and_role(["Advertiser"])
        p = ownership.get_placement(pid)
        ownership.assert_advertiser_owns_placement(caller, p)
        if p["status"] not in ("PROPOSED", "INSERTED"):
            raise errors.err(errors.ERR_INVALID_STATE, "Placement cannot be cancelled from its current state")
        p["status"] = "CANCELLED"
        touch(p)
        campaign = db.db.ad_campaigns.get(p["campaign_id"])
        if campaign is not None:
            recompute.recompute_campaign_ledger(campaign)
        episode = db.db.episodes.get(p["episode_id"])
        if episode is not None:
            recompute.recompute_episode_fill(episode)
        return success(serialize.ad_placement(p), status=200)


def _midroll_overlaps(placement, episode):
    """MID_ROLL [offset, offset+ad_duration) + buffer on each side must not overlap
    an existing INSERTED/DELIVERED MID_ROLL on the same episode (PRD §3.6)."""
    buf = db.MID_ROLL_BUFFER_MS
    a_start = placement["offset_ms"] - buf
    a_end = placement["offset_ms"] + placement["ad_duration_ms"] + buf
    for other in db.db.ad_placements.values():
        if other["id"] == placement["id"]:
            continue
        if other["episode_id"] != episode["id"]:
            continue
        if other["position"] != "MID_ROLL":
            continue
        if other["status"] not in ("INSERTED", "DELIVERED"):
            continue
        b_start = other["offset_ms"]
        b_end = other["offset_ms"] + other["ad_duration_ms"]
        # Half-open intervals: overlap iff a_start < b_end and b_start < a_end.
        if a_start < b_end and b_start < a_end:
            return True
    return False
