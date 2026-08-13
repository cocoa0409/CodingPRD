"""Line item endpoints: create (XOR target, safety + referential gates),
get, list, ACTIVATE / PAUSE / END with the full sales-integrity gate."""

from flask import Blueprint, request

import db
from errors import (
    err_not_found,
    err_invalid,
    err_conflict,
    ERR_CAMPAIGN_NOT_EDITABLE,
    ERR_CAMPAIGN_NOT_ACTIVE,
    ERR_LINE_ITEM_STATE,
    ERR_SHOW_SUSPENDED,
    ERR_BRAND_SAFETY_CONFLICT,
    ERR_COPY_NOT_APPROVED,
    ERR_COPY_CAMPAIGN_MISMATCH,
    ERR_TARGET_SCOPE_INVALID,
    ERR_CATEGORY_EXCLUSIVE_CONFLICT,
    ERR_SLOT_CAPACITY_EXCEEDED,
    ERR_INSUFFICIENT_INVENTORY,
)
from helpers import (
    body_of,
    new_id,
    now_timestamp,
    require_string,
    require_enum,
    require_int,
    parse_dt,
)
from middleware import require_roles, ALL_ROLES
from response import success_object, list_response, serialize
from services import (
    Changes,
    FORMAT_TO_KIND,
    flights_overlap,
    line_item_target_show,
    recompute_show,
    recompute_episode_slots,
    pause_line_item,
    end_line_item,
)

bp = Blueprint("line_items", __name__)

AD_FORMATS = {"HOST_READ", "PRODUCED_SPOT"}
POSITIONS = {"PRE_ROLL", "MID_ROLL", "POST_ROLL"}


def get_line_item_or_404(line_item_id):
    li = db.line_items.get(line_item_id)
    if li is None:
        raise err_not_found(f"LineItem '{line_item_id}' not found")
    return li


def _resolve_target(campaign_id, show_id, episode_id):
    """Return (show, episode) after existence checks on whichever target
    fields are set."""
    show = episode = None
    if isinstance(show_id, str):
        show = db.shows.get(show_id)
        if show is None:
            raise err_not_found(f"Show '{show_id}' not found")
    if isinstance(episode_id, str):
        episode = db.episodes.get(episode_id)
        if episode is None:
            raise err_not_found(f"Episode '{episode_id}' not found")
        if show is None:
            show = db.shows.get(episode["show_id"])
    return show, episode


@bp.route("/adnet/line-items", methods=["POST"])
def create_line_item():
    require_roles({"AdOps"})
    body = body_of(request)

    campaign_id = body.get("campaign_id")
    ad_copy_id = body.get("ad_copy_id")
    show_id = body.get("show_id")
    episode_id = body.get("episode_id")

    # Existence (priority 4): body FKs must reference existing resources.
    campaign = None
    if isinstance(campaign_id, str):
        campaign = db.campaigns.get(campaign_id)
        if campaign is None:
            raise err_not_found(f"Campaign '{campaign_id}' not found")
    show, episode = _resolve_target(campaign_id, show_id, episode_id)
    copy = None
    if isinstance(ad_copy_id, str):
        copy = db.ad_copies.get(ad_copy_id)
        if copy is None:
            raise err_not_found(f"AdCopy '{ad_copy_id}' not found")

    # State (priority 6): campaign must be DRAFT / ACTIVE / PAUSED.
    if campaign is not None and campaign["status"] not in ("DRAFT", "ACTIVE", "PAUSED"):
        raise err_conflict(
            ERR_CAMPAIGN_NOT_EDITABLE,
            f"Campaign is {campaign['status']}; line items may be added only while DRAFT, ACTIVE or PAUSED",
        )

    # Brand safety (priority 7): screened at creation as well as activation.
    if show is not None:
        if show["brand_safety_tier"] == "SUSPENDED":
            raise err_conflict(ERR_SHOW_SUSPENDED, "Target show is SUSPENDED")
        advertiser = db.advertisers.get(campaign["advertiser_id"]) if campaign else None
        if (
            advertiser is not None
            and advertiser["category"] in show["blocked_advertiser_categories"]
        ):
            raise err_conflict(
                ERR_BRAND_SAFETY_CONFLICT,
                "Advertiser category is blocked on the target show",
            )

    # Cross-reference integrity (priority 8).
    has_show = isinstance(show_id, str) and show_id != ""
    has_episode = isinstance(episode_id, str) and episode_id != ""
    if has_show == has_episode:
        raise err_invalid_scope()
    if copy is not None and campaign is not None and copy["campaign_id"] != campaign["id"]:
        raise err_conflict(
            ERR_COPY_CAMPAIGN_MISMATCH,
            "ad_copy_id belongs to a different campaign than the line item's campaign_id",
        )
    ad_format = body.get("ad_format")
    if copy is not None and ad_format in FORMAT_TO_KIND:
        if FORMAT_TO_KIND[ad_format] != copy["kind"]:
            raise err_invalid(
                f"ad_format {ad_format} does not match ad copy kind {copy['kind']}"
            )

    # Field shape (catch-all).
    campaign_id = require_string(body, "campaign_id")
    ad_copy_id = require_string(body, "ad_copy_id")
    ad_format = require_enum(body, "ad_format", AD_FORMATS)
    position = require_enum(body, "position", POSITIONS)
    reserved_impressions = require_int(body, "reserved_impressions", minimum=1)
    priority = require_int(body, "priority")
    if show_id is not None and not isinstance(show_id, str):
        raise err_invalid("Field 'show_id' must be a string when provided")
    if episode_id is not None and not isinstance(episode_id, str):
        raise err_invalid("Field 'episode_id' must be a string when provided")

    ts = now_timestamp()
    li = {
        "id": new_id(),
        "campaign_id": campaign_id,
        "show_id": show_id if has_show else None,
        "episode_id": episode_id if has_episode else None,
        "ad_format": ad_format,
        "position": position,
        "reserved_impressions": reserved_impressions,
        "priority": priority,
        "ad_copy_id": ad_copy_id,
        "status": "DRAFT",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.line_items[li["id"]] = li
    return success_object(serialize(li), 201)


def err_invalid_scope():
    from errors import ApiError

    return ApiError(
        ERR_TARGET_SCOPE_INVALID,
        "Exactly one of show_id / episode_id must be set",
        400,
    )


@bp.route("/adnet/line-items/<line_item_id>", methods=["GET"])
def get_line_item(line_item_id):
    require_roles(ALL_ROLES)
    return success_object(serialize(get_line_item_or_404(line_item_id)))


@bp.route("/adnet/line-items", methods=["GET"])
def list_line_items():
    require_roles(ALL_ROLES)
    items = list(db.line_items.values())
    for param in ("campaign_id", "show_id", "episode_id", "ad_copy_id", "status"):
        value = request.args.get(param)
        if value is not None:
            items = [li for li in items if li.get(param) == value]
    return list_response(items, request.args)


@bp.route("/adnet/line-items/<line_item_id>/transition", methods=["POST"])
def transition_line_item(line_item_id):
    require_roles({"AdOps"})
    li = get_line_item_or_404(line_item_id)
    body = body_of(request)
    action = body.get("action")
    if action not in ("ACTIVATE", "PAUSE", "END"):
        raise err_invalid("Field 'action' must be one of ACTIVATE, PAUSE, END")

    status = li["status"]
    allowed = {
        "ACTIVATE": {"DRAFT", "PAUSED"},
        "PAUSE": {"ACTIVE"},
        "END": {"ACTIVE", "PAUSED"},
    }[action]
    if status not in allowed:
        raise err_conflict(
            ERR_LINE_ITEM_STATE,
            f"LineItem is {status}; {action} is not permitted from this state",
        )

    if action == "ACTIVATE":
        _run_activation_gates(li)
        ch = Changes()
        ch.update(li, status="ACTIVE")
        if li.get("show_id"):
            show = db.shows.get(li["show_id"])
            if show is not None:
                recompute_show(show, ch)
        else:
            ep = db.episodes.get(li["episode_id"])
            if ep is not None:
                recompute_episode_slots(ep, ch)
        ch.commit()
    elif action == "PAUSE":
        ch = Changes()
        pause_line_item(li, ch)
        ch.commit()
    else:  # END
        ch = Changes()
        end_line_item(li, ch)
        ch.commit()
    return success_object(serialize(li))


def _run_activation_gates(li):
    """The full sales-integrity gate, in the pipeline order of PRD §2.8."""
    campaign = db.campaigns.get(li["campaign_id"])

    # 1. State: owning campaign must be ACTIVE.
    if campaign is None or campaign["status"] != "ACTIVE":
        raise err_conflict(
            ERR_CAMPAIGN_NOT_ACTIVE, "Owning campaign is not ACTIVE"
        )

    show = line_item_target_show(li)
    advertiser = db.advertisers.get(campaign["advertiser_id"])

    # 2-3. Brand safety.
    if show is not None:
        if show["brand_safety_tier"] == "SUSPENDED":
            raise err_conflict(ERR_SHOW_SUSPENDED, "Target show is SUSPENDED")
        if (
            advertiser is not None
            and advertiser["category"] in show["blocked_advertiser_categories"]
        ):
            raise err_conflict(
                ERR_BRAND_SAFETY_CONFLICT,
                "Advertiser category is blocked on the target show",
            )

    # 4. Referenced copy must be APPROVED.
    copy = db.ad_copies.get(li["ad_copy_id"])
    if copy is None or copy["status"] != "APPROVED":
        raise err_conflict(ERR_COPY_NOT_APPROVED, "Referenced ad copy is not APPROVED")

    cand_start = parse_dt(campaign["flight_start"])
    cand_end = parse_dt(campaign["flight_end"])

    # 5. Category exclusivity: no other ACTIVE line item of a different
    #    advertiser with the same category targeting the same show with an
    #    overlapping half-open flight.
    if show is not None and advertiser is not None:
        for other in db.line_items.values():
            if other["id"] == li["id"] or other["status"] != "ACTIVE":
                continue
            other_show = line_item_target_show(other)
            if other_show is None or other_show["id"] != show["id"]:
                continue
            other_campaign = db.campaigns.get(other["campaign_id"])
            if other_campaign is None:
                continue
            other_advertiser = db.advertisers.get(other_campaign["advertiser_id"])
            if other_advertiser is None:
                continue
            if other_advertiser["id"] == advertiser["id"]:
                continue
            if other_advertiser["category"] != advertiser["category"]:
                continue
            if flights_overlap(
                cand_start,
                cand_end,
                parse_dt(other_campaign["flight_start"]),
                parse_dt(other_campaign["flight_end"]),
            ):
                raise err_conflict(
                    ERR_CATEGORY_EXCLUSIVE_CONFLICT,
                    "Another advertiser of the same category holds an overlapping ACTIVE line item on this show",
                )

    # 6. Episode slot aggregate capacity (episode-targeted only).
    if li.get("episode_id"):
        episode = db.episodes.get(li["episode_id"])
        if episode is not None:
            overlapping = 0
            for other in db.line_items.values():
                if (
                    other["id"] == li["id"]
                    or other.get("episode_id") != episode["id"]
                    or other["status"] != "ACTIVE"
                ):
                    continue
                other_campaign = db.campaigns.get(other["campaign_id"])
                if other_campaign is None:
                    continue
                if flights_overlap(
                    cand_start,
                    cand_end,
                    parse_dt(other_campaign["flight_start"]),
                    parse_dt(other_campaign["flight_end"]),
                ):
                    overlapping += 1
            if overlapping >= episode["slot_capacity"]:
                raise err_conflict(
                    ERR_SLOT_CAPACITY_EXCEEDED,
                    "Episode slot capacity would be exceeded",
                )

    # 7. Inventory sufficiency (run-of-show only; equality allowed).
    if li.get("show_id"):
        if show is not None and li["reserved_impressions"] > show["available_impressions"]:
            raise err_conflict(
                ERR_INSUFFICIENT_INVENTORY,
                "reserved_impressions exceeds the show's available_impressions",
            )
