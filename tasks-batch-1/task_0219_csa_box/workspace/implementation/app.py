"""CSA Box API — Flask entry point.

Wires error handling, all endpoints, RBAC, ownership, state machines, and
calculations. In-memory only; no seeding at startup. Boots clean every run.
"""
import os
import socket as _socket

# Werkzeug's dev server calls socket.getfqdn(host) during server_bind purely to
# compose its "Running on http://..." startup banner. On some hosts (notably
# macOS) getfqdn("0.0.0.0") blocks ~5s on a reverse-DNS (PTR) lookup that times
# out, because the unspecified address has no hostname. Under per-test-server
# isolation the server reboots before every test, so that 5s stall is paid
# hundreds of times and, under the concurrent stability sweep, can push a boot
# past the runner's restart-poll window and surface as "could not be restarted".
# Short-circuit the unspecified-address cases here so boot is fast regardless of
# whether the runner's own getfqdn shim is loaded. Named addresses fall through
# to the real resolver unchanged; getfqdn's result is only ever the banner host.
_real_getfqdn = _socket.getfqdn
_UNSPECIFIED_HOSTS = {"", "0.0.0.0", "::", "0:0:0:0:0:0:0:0"}


def _fast_getfqdn(name=""):
    if name in _UNSPECIFIED_HOSTS:
        return "localhost"
    return _real_getfqdn(name)


_socket.getfqdn = _fast_getfqdn

from flask import Flask, request

import db
import calc
import services
from models import stamp_new, touch, parse_iso, iso_from_dt
from response import success, error
from serialize import public, public_list
from errors import (
    ApiError, err,
    ERR_NOT_FOUND, ERR_NOT_RESOURCE_OWNER, ERR_SEASON_MISMATCH,
    ERR_INVALID_STATE, ERR_SIGNUP_CLOSED, ERR_HOLD_WINDOW_PASSED,
    ERR_INVALID_SWAP_TARGET, ERR_OFFER_EXPIRED, ERR_ADDON_SUPPLY_EXHAUSTED,
    ERR_NOT_WORKING_SHARE, ERR_SITE_CAPACITY_FULL, ERR_SEASON_CAPACITY_FULL,
    ERR_INVALID_REQUEST, ERR_DUPLICATE_EMAIL, ERR_STALE_VERSION,
)
from middleware import require_auth, require_role
import validation as V

app = Flask(__name__)
app.url_map.strict_slashes = False

ALL_AUTH_ROLES = ["FarmManager", "DeliveryCoordinator", "Member", "PlatformAdmin"]


# ==========================================================================
# Error handling
# ==========================================================================
@app.errorhandler(ApiError)
def handle_api_error(e):
    return error(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return error("ERR_NOT_FOUND", "Resource not found.", 404)


@app.errorhandler(405)
def handle_405(e):
    return error("ERR_NOT_FOUND", "Method not allowed.", 404)


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return error(e.error_id, e.message, e.http_status)
    return error("ERR_INTERNAL", "Internal server error: %s" % str(e), 500)


# ==========================================================================
# Lookup helpers (existence -> ERR_NOT_FOUND, priority 4)
# ==========================================================================
def must_get(table, _id):
    rec = table.get(_id)
    if rec is None:
        raise err(ERR_NOT_FOUND, "Resource not found: %s" % _id)
    return rec


def fk_exists(table, _id):
    """FK existence check; None-valued FK is treated as missing -> 404."""
    if _id is None:
        raise err(ERR_NOT_FOUND, "Referenced resource not found.")
    rec = table.get(_id)
    if rec is None:
        raise err(ERR_NOT_FOUND, "Referenced resource not found: %s" % _id)
    return rec


# ==========================================================================
# Ownership (priority 3, PRD §2.1)
# ==========================================================================
def check_owner_member(sub_member_id, user_id, role):
    """For Member-actor endpoints: the resource's owning member_id must equal
    X-User-ID. Only enforced when acting as Member (other roles are opaque)."""
    if role == "Member" and sub_member_id != user_id:
        raise err(ERR_NOT_RESOURCE_OWNER,
                  "Acting member does not own this resource.")


# ==========================================================================
# Pagination response helper
# ==========================================================================
def list_response(records):
    """Sort by created_at ASC (tie-break by internal seq), paginate, envelope."""
    limit, offset = V.parse_pagination()
    ordered = sorted(records, key=lambda r: (r["created_at"], r.get("_seq", 0)))
    page, meta = V.paginate(ordered, limit, offset)
    return success(public_list(page), status=200, is_array=True, pagination=meta)


# ==========================================================================
# SEASON
# ==========================================================================
@app.route("/seasons", methods=["POST"])
def create_season():
    require_role(["FarmManager"])
    body = V.get_json_body()
    name = V.require_string(body, "name")
    week_count = V.require_int(body, "week_count", minimum=1, maximum=52)
    first_delivery_date = V.require_string(body, "first_delivery_date")
    signup_close_date = V.require_string(body, "signup_close_date")
    total_share_capacity = V.require_int(body, "total_share_capacity", minimum=0)
    if parse_iso(first_delivery_date) is None:
        raise err(ERR_INVALID_REQUEST, "first_delivery_date must be ISO 8601.")
    if parse_iso(signup_close_date) is None:
        raise err(ERR_INVALID_REQUEST, "signup_close_date must be ISO 8601.")

    rec = {
        "name": name,
        "week_count": week_count,
        "first_delivery_date": first_delivery_date,
        "signup_close_date": signup_close_date,
        "total_share_capacity": total_share_capacity,
        "status": "DRAFT",
        "confirmed_share_count": 0,
    }
    stamp_new(rec)
    db.seasons[rec["id"]] = rec
    return success(public(rec), status=201)


@app.route("/seasons/<sid>", methods=["GET"])
def get_season(sid):
    require_role(ALL_AUTH_ROLES)
    rec = must_get(db.seasons, sid)
    return success(public(rec), status=200)


@app.route("/seasons", methods=["GET"])
def list_seasons():
    require_role(ALL_AUTH_ROLES)
    status = request.args.get("status")
    records = list(db.seasons.values())
    if status is not None:
        records = [r for r in records if r["status"] == status]
    return list_response(records)


@app.route("/seasons/<sid>/open", methods=["POST"])
def open_season(sid):
    require_role(["FarmManager"])
    season = must_get(db.seasons, sid)
    # state validity (priority 6): only DRAFT may open
    if season["status"] != "DRAFT":
        raise err(ERR_INVALID_STATE, "Season is not in DRAFT.")
    # precondition: >=1 ShareType and >=1 PickupSite (PRD §3.1)
    has_share = any(st["season_id"] == sid for st in db.share_types.values())
    has_site = any(ps["season_id"] == sid for ps in db.pickup_sites.values())
    if not (has_share and has_site):
        raise err(ERR_INVALID_STATE,
                  "Season needs >= 1 share type and >= 1 pickup site to open.")
    season["status"] = "OPEN"
    touch(season)
    return success(public(season), status=200)


@app.route("/seasons/<sid>/close", methods=["POST"])
def close_season(sid):
    require_role(["FarmManager"])
    season = must_get(db.seasons, sid)
    if season["status"] != "OPEN":
        raise err(ERR_INVALID_STATE, "Season is not OPEN.")
    season["status"] = "CLOSED"
    touch(season)
    return success(public(season), status=200)


@app.route("/seasons/<sid>/promote-waitlist", methods=["POST"])
def promote_waitlist(sid):
    require_role(["DeliveryCoordinator"])
    body = V.get_json_body()
    season = must_get(db.seasons, sid)

    share_type_id = V.require_string(body, "share_type_id")
    requested_site_id = V.require_string(body, "requested_site_id")
    if "expected_season_version" not in body or body.get("expected_season_version") is None:
        raise err(ERR_INVALID_REQUEST, "Missing required field: expected_season_version")
    expected_version = body["expected_season_version"]

    # existence (priority 4)
    share_type = fk_exists(db.share_types, share_type_id)
    site = fk_exists(db.pickup_sites, requested_site_id)

    # select earliest WAITING entry for (season, site, share_type) — drives
    # whether a transition is even defined (state validity, priority 6).
    candidates = [
        e for e in db.waitlist_entries.values()
        if e["season_id"] == sid
        and e["requested_site_id"] == requested_site_id
        and e["share_type_id"] == share_type_id
        and e["status"] == "WAITING"
    ]
    if not candidates:
        raise err(ERR_INVALID_STATE,
                  "No WAITING waitlist entry to promote.")
    candidates.sort(key=lambda e: (e["created_at"], e.get("_seq", 0)))
    entry = candidates[0]

    # business gates (PRD §3.8): season slot, site room, then OCC
    if not (season["confirmed_share_count"] < season["total_share_capacity"]):
        raise err(ERR_SEASON_CAPACITY_FULL, "No season slot available.")
    if not (site["active_subscription_count"] < site["weekly_capacity"]):
        raise err(ERR_SITE_CAPACITY_FULL, "Requested site is at capacity.")
    if not isinstance(expected_version, int) or isinstance(expected_version, bool):
        raise err(ERR_INVALID_REQUEST, "expected_season_version must be an integer.")
    if expected_version != season["version"]:
        raise err(ERR_STALE_VERSION, "Season version is stale.")

    # promote
    now = db.get_clock()
    from datetime import timedelta
    expires = now + timedelta(hours=48)
    entry["status"] = "OFFERED"
    entry["offer_expires_at"] = iso_from_dt(expires)
    touch(entry)
    # increment season version (§1.5 side effect)
    touch(season)
    return success(public(entry), status=200)


# ==========================================================================
# PICKUP SITE
# ==========================================================================
@app.route("/pickup-sites", methods=["POST"])
def create_pickup_site():
    require_role(["DeliveryCoordinator"])
    body = V.get_json_body()
    season_id = V.require_string(body, "season_id")
    name = V.require_string(body, "name")
    kind = V.require_enum(body, "kind", {"PICKUP", "HOME_DELIVERY"})
    weekly_capacity = V.require_int(body, "weekly_capacity", minimum=0)
    surcharge = V.require_int(body, "delivery_surcharge_cents", minimum=0,
                              required=False, default=0)
    fk_exists(db.seasons, season_id)

    rec = {
        "season_id": season_id,
        "name": name,
        "kind": kind,
        "weekly_capacity": weekly_capacity,
        "delivery_surcharge_cents": surcharge,
        "active_subscription_count": 0,
    }
    stamp_new(rec)
    db.pickup_sites[rec["id"]] = rec
    return success(public(rec), status=201)


@app.route("/pickup-sites/<pid>", methods=["GET"])
def get_pickup_site(pid):
    require_role(ALL_AUTH_ROLES)
    return success(public(must_get(db.pickup_sites, pid)), status=200)


@app.route("/pickup-sites", methods=["GET"])
def list_pickup_sites():
    require_role(ALL_AUTH_ROLES)
    season_id = request.args.get("season_id")
    records = list(db.pickup_sites.values())
    if season_id is not None:
        records = [r for r in records if r["season_id"] == season_id]
    return list_response(records)


# ==========================================================================
# SHARE TYPE
# ==========================================================================
@app.route("/share-types", methods=["POST"])
def create_share_type():
    require_role(["FarmManager"])
    body = V.get_json_body()
    season_id = V.require_string(body, "season_id")
    size = V.require_enum(body, "size", {"SMALL", "MEDIUM", "LARGE"})
    base_price_cents = V.require_int(body, "base_price_cents", positive=True)
    items_per_box = V.require_int(body, "items_per_box", minimum=1)
    fk_exists(db.seasons, season_id)

    rec = {
        "season_id": season_id,
        "size": size,
        "base_price_cents": base_price_cents,
        "items_per_box": items_per_box,
    }
    stamp_new(rec)
    db.share_types[rec["id"]] = rec
    return success(public(rec), status=201)


@app.route("/share-types/<stid>", methods=["GET"])
def get_share_type(stid):
    require_role(ALL_AUTH_ROLES)
    return success(public(must_get(db.share_types, stid)), status=200)


@app.route("/share-types", methods=["GET"])
def list_share_types():
    require_role(ALL_AUTH_ROLES)
    season_id = request.args.get("season_id")
    records = list(db.share_types.values())
    if season_id is not None:
        records = [r for r in records if r["season_id"] == season_id]
    return list_response(records)


# ==========================================================================
# ADD-ON
# ==========================================================================
@app.route("/add-ons", methods=["POST"])
def create_add_on():
    require_role(["FarmManager"])
    body = V.get_json_body()
    season_id = V.require_string(body, "season_id")
    kind = V.require_enum(body, "kind", {"EGGS", "FLOWERS"})
    weekly_price_cents = V.require_int(body, "weekly_price_cents", positive=True)
    weekly_supply_cap = V.require_int(body, "weekly_supply_cap", minimum=0)
    fk_exists(db.seasons, season_id)

    rec = {
        "season_id": season_id,
        "kind": kind,
        "weekly_price_cents": weekly_price_cents,
        "weekly_supply_cap": weekly_supply_cap,
        "committed_count": 0,
    }
    stamp_new(rec)
    db.add_ons[rec["id"]] = rec
    return success(public(rec), status=201)


@app.route("/add-ons/<aid>", methods=["GET"])
def get_add_on(aid):
    require_role(ALL_AUTH_ROLES)
    return success(public(must_get(db.add_ons, aid)), status=200)


@app.route("/add-ons", methods=["GET"])
def list_add_ons():
    require_role(ALL_AUTH_ROLES)
    season_id = request.args.get("season_id")
    records = list(db.add_ons.values())
    if season_id is not None:
        records = [r for r in records if r["season_id"] == season_id]
    return list_response(records)


# ==========================================================================
# MEMBER (registration is Anonymous / no auth)
# ==========================================================================
@app.route("/members", methods=["POST"])
def create_member():
    body = V.get_json_body()
    email = V.require_string(body, "email", allow_empty=False)
    full_name = V.require_string(body, "full_name")
    tier = V.require_enum(body, "sliding_scale_tier",
                          {"SOLIDARITY", "BASELINE", "SUSTAINER"},
                          required=False, default="BASELINE")
    # case-insensitive unique email (priority 16)
    for m in db.members.values():
        if m["email"].lower() == email.lower():
            raise err(ERR_DUPLICATE_EMAIL, "Email already registered.")

    rec = {
        "email": email,
        "full_name": full_name,
        "sliding_scale_tier": tier,
        "wallet_credit_cents": 0,
    }
    stamp_new(rec)
    db.members[rec["id"]] = rec
    return success(public(rec), status=201)


@app.route("/members/<mid>", methods=["GET"])
def get_member(mid):
    require_role(ALL_AUTH_ROLES)
    return success(public(must_get(db.members, mid)), status=200)


# ==========================================================================
# SUBSCRIPTION
# ==========================================================================
@app.route("/subscriptions", methods=["POST"])
def create_subscription():
    user_id, role = require_role(["Member"])
    body = V.get_json_body()
    season_id = V.require_string(body, "season_id")
    member_id = V.require_string(body, "member_id")
    share_type_id = V.require_string(body, "share_type_id")
    current_site_id = V.require_string(body, "current_site_id")
    opt_in = V.require_bool(body, "working_share_opt_in", default=False)

    # ownership (priority 3): the created subscription's member must be caller
    check_owner_member(member_id, user_id, role)

    # existence (priority 4)
    season = fk_exists(db.seasons, season_id)
    fk_exists(db.members, member_id)
    share_type = fk_exists(db.share_types, share_type_id)
    site = fk_exists(db.pickup_sites, current_site_id)

    # season cohesion (priority 5)
    if share_type["season_id"] != season_id or site["season_id"] != season_id:
        raise err(ERR_SEASON_MISMATCH,
                  "ShareType/PickupSite must belong to the named season.")

    # state validity (priority 6): season must be OPEN to create subscription
    if season["status"] != "OPEN":
        raise err(ERR_INVALID_STATE, "Season is not OPEN.")

    rec = {
        "season_id": season_id,
        "member_id": member_id,
        "share_type_id": share_type_id,
        "current_site_id": current_site_id,
        "working_share_opt_in": opt_in,
        "billing_status": "PENDING_PAYMENT",
        "fulfillment_status": "NOT_STARTED",
        "season_price_cents": 0,
        "outstanding_balance_cents": 0,
    }
    stamp_new(rec)
    db.subscriptions[rec["id"]] = rec
    return success(public(rec), status=201)


@app.route("/subscriptions/<sid>", methods=["GET"])
def get_subscription(sid):
    require_role(ALL_AUTH_ROLES)
    return success(public(must_get(db.subscriptions, sid)), status=200)


@app.route("/subscriptions", methods=["GET"])
def list_subscriptions():
    require_role(ALL_AUTH_ROLES)
    records = list(db.subscriptions.values())
    for key in ("season_id", "member_id", "share_type_id", "current_site_id"):
        val = request.args.get(key)
        if val is not None:
            records = [r for r in records if r[key] == val]
    return list_response(records)


@app.route("/subscriptions/<sid>/confirm", methods=["POST"])
def confirm_subscription(sid):
    require_role(["FarmManager"])
    body = V.get_json_body()
    sub = must_get(db.subscriptions, sid)
    season = must_get(db.seasons, sub["season_id"])
    site = must_get(db.pickup_sites, sub["current_site_id"])
    share_type = must_get(db.share_types, sub["share_type_id"])
    member = must_get(db.members, sub["member_id"])

    if "expected_season_version" not in body or body.get("expected_season_version") is None:
        raise err(ERR_INVALID_REQUEST, "Missing required field: expected_season_version")
    expected_version = body["expected_season_version"]
    if not isinstance(expected_version, int) or isinstance(expected_version, bool):
        raise err(ERR_INVALID_REQUEST, "expected_season_version must be an integer.")

    # state validity (priority 6): confirm only defined from PENDING_PAYMENT
    # and the season must be OPEN for confirm to be defined at all (PRD §3.3).
    if sub["billing_status"] != "PENDING_PAYMENT" or season["status"] != "OPEN":
        raise err(ERR_INVALID_STATE,
                  "Confirm is not defined from the current state.")

    # business gates in priority order (PRD §3.3):
    #  7  signup window, 13 site capacity, 14 season capacity, 17 OCC
    now = db.get_clock()
    close = parse_iso(season["signup_close_date"])
    if close is not None and now > close:
        raise err(ERR_SIGNUP_CLOSED, "Signup window has closed.")
    if not (site["active_subscription_count"] < site["weekly_capacity"]):
        raise err(ERR_SITE_CAPACITY_FULL, "Site weekly capacity is full.")
    if not (season["confirmed_share_count"] < season["total_share_capacity"]):
        raise err(ERR_SEASON_CAPACITY_FULL, "Season capacity is full.")
    if expected_version != season["version"]:
        raise err(ERR_STALE_VERSION, "Season version is stale.")

    # ---- confirm cascade (PRD §3.3) ----
    sub["billing_status"] = "CONFIRMED"

    # season price pinned via §1.3 season_share_price
    price = calc.season_share_price(share_type["base_price_cents"],
                                    member["sliding_scale_tier"])
    sub["season_price_cents"] = price
    services.post_ledger(sid, "CHARGE_SEASON", price, "Full-season share charge")

    # HOME_DELIVERY surcharge
    if site["kind"] == "HOME_DELIVERY":
        surcharge_total = site["delivery_surcharge_cents"] * season["week_count"]
        if surcharge_total != 0:
            services.post_ledger(sid, "CHARGE_SURCHARGE", surcharge_total,
                                 "Home-delivery surcharge")

    # generate WeeklyBox rows 1..week_count
    for wi in range(1, season["week_count"] + 1):
        box = {
            "subscription_id": sid,
            "week_index": wi,
            "site_id": sub["current_site_id"],
            "status": "SCHEDULED",
            "item_count": 0,
        }
        stamp_new(box)
        db.weekly_boxes[box["id"]] = box

    # recompute balance, counters, versions
    services.recompute_balance(sub)
    touch(sub)  # explicit subscription version bump for the confirm action
    services.recompute_season_confirmed_count(season)  # bumps season version
    services.recompute_site_active_count(site)
    return success(public(sub), status=200)


@app.route("/subscriptions/<sid>/cancel", methods=["POST"])
def cancel_subscription(sid):
    user_id, role = require_role(["Member"])
    sub = must_get(db.subscriptions, sid)
    check_owner_member(sub["member_id"], user_id, role)

    # state validity (priority 6): cancel only from non-terminal billing states
    if sub["billing_status"] not in ("PENDING_PAYMENT", "CONFIRMED", "ACTIVE"):
        raise err(ERR_INVALID_STATE, "Subscription is not in a cancellable state.")

    season = db.seasons.get(sub["season_id"])
    site = db.pickup_sites.get(sub["current_site_id"])
    share_type = db.share_types.get(sub["share_type_id"])

    sub["billing_status"] = "CANCELLED"

    # ---- three-hop cascade (PRD §3.10) ----
    boxes = services.boxes_for(sid)
    refundable_weeks = []  # week_index list of non-terminal boxes being skipped
    for box in boxes:
        if box["status"] in ("SCHEDULED", "HELD"):
            was_held = box["status"] == "HELD"
            refundable_weeks.append(box["week_index"])
            box["status"] = "SKIPPED"
            box["item_count"] = 0
            touch(box)
            # hop 2: release covering hold (ACTIVE -> RELEASED)
            if was_held:
                hold = next(
                    (h for h in db.vacation_holds.values()
                     if h["held_box_id"] == box["id"] and h["status"] == "ACTIVE"),
                    None,
                )
                if hold is not None:
                    hold["status"] = "RELEASED"
                    touch(hold)

    # hop 3: detach ATTACHED add-ons; decrement committed_count
    for sa in db.subscription_add_ons.values():
        if sa["subscription_id"] == sid and sa["status"] == "ATTACHED":
            sa["status"] = "DETACHED"
            touch(sa)
            add_on = db.add_ons.get(sa["add_on_id"])
            if add_on is not None:
                services.recompute_addon_committed_count(add_on)

    # post CREDIT_HOLD_REFUND for undelivered prepaid weeks
    if season is not None and sub["season_price_cents"] > 0:
        total_refund = 0
        for wi in refundable_weeks:
            total_refund += calc.hold_refund_value(
                sub["season_price_cents"], season["week_count"], wi)
        if total_refund != 0:
            services.post_ledger(sid, "CREDIT_HOLD_REFUND", -total_refund,
                                 "Cancellation refund for undelivered weeks")

    services.recompute_balance(sub)
    touch(sub)
    if season is not None:
        services.recompute_season_confirmed_count(season)
    if site is not None:
        services.recompute_site_active_count(site)
    return success(public(sub), status=200)


# ==========================================================================
# SUBSCRIPTION ADD-ON (junction)
# ==========================================================================
@app.route("/subscription-add-ons", methods=["POST"])
def attach_add_on():
    user_id, role = require_role(["Member"])
    body = V.get_json_body()
    subscription_id = V.require_string(body, "subscription_id")
    add_on_id = V.require_string(body, "add_on_id")

    sub = fk_exists(db.subscriptions, subscription_id)
    check_owner_member(sub["member_id"], user_id, role)
    add_on = fk_exists(db.add_ons, add_on_id)

    # season cohesion (priority 5)
    if add_on["season_id"] != sub["season_id"]:
        raise err(ERR_SEASON_MISMATCH,
                  "Add-on must belong to the subscription's season.")

    # supply gate (priority 11): committed_count < weekly_supply_cap (strict)
    if not (add_on["committed_count"] < add_on["weekly_supply_cap"]):
        raise err(ERR_ADDON_SUPPLY_EXHAUSTED, "Add-on supply is exhausted.")

    rec = {
        "subscription_id": subscription_id,
        "add_on_id": add_on_id,
        "status": "ATTACHED",
    }
    stamp_new(rec)
    db.subscription_add_ons[rec["id"]] = rec

    # increment committed_count (recompute)
    services.recompute_addon_committed_count(add_on)

    # CHARGE_ADDON = weekly_price_cents × remaining_weeks (PRD §3.5)
    remaining_weeks = _remaining_weeks(sub)
    charge = add_on["weekly_price_cents"] * remaining_weeks
    services.post_ledger(subscription_id, "CHARGE_ADDON", charge,
                         "Add-on charge")
    services.recompute_balance(sub)
    return success(public(rec), status=201)


def _remaining_weeks(sub):
    """Count of subscription's WeeklyBox not terminal; if none exist (still
    PENDING_PAYMENT, unconfirmed), = Season.week_count (PRD §3.5)."""
    boxes = services.boxes_for(sub["id"])
    if not boxes:
        season = db.seasons.get(sub["season_id"])
        return season["week_count"] if season else 0
    return sum(1 for b in boxes
               if b["status"] not in services.TERMINAL_BOX_STATES)


@app.route("/subscription-add-ons/<said>", methods=["DELETE"])
def detach_add_on(said):
    user_id, role = require_role(["Member"])
    sa = must_get(db.subscription_add_ons, said)
    sub = db.subscriptions.get(sa["subscription_id"])
    if sub is not None:
        check_owner_member(sub["member_id"], user_id, role)

    # state validity (priority 6): only ATTACHED can detach
    if sa["status"] != "ATTACHED":
        raise err(ERR_INVALID_STATE, "Add-on attachment is not ATTACHED.")

    sa["status"] = "DETACHED"
    touch(sa)
    add_on = db.add_ons.get(sa["add_on_id"])
    if add_on is not None:
        services.recompute_addon_committed_count(add_on)

    # offsetting credit for undelivered weeks (PRD §3.5)
    if sub is not None and add_on is not None:
        remaining_weeks = _remaining_weeks(sub)
        credit = add_on["weekly_price_cents"] * remaining_weeks
        if credit != 0:
            services.post_ledger(sa["subscription_id"], "CREDIT_HOLD_REFUND",
                                 -credit, "Add-on detach credit")
        services.recompute_balance(sub)
    return success(public(sa), status=200)


@app.route("/subscriptions/<sid>/add-ons", methods=["GET"])
def list_subscription_add_ons(sid):
    require_role(ALL_AUTH_ROLES)
    must_get(db.subscriptions, sid)
    records = [sa for sa in db.subscription_add_ons.values()
               if sa["subscription_id"] == sid]
    return list_response(records)


@app.route("/subscription-add-ons/<said>", methods=["GET"])
def get_subscription_add_on(said):
    require_role(ALL_AUTH_ROLES)
    return success(public(must_get(db.subscription_add_ons, said)), status=200)


@app.route("/subscription-add-ons", methods=["GET"])
def list_all_subscription_add_ons():
    require_role(["FarmManager", "DeliveryCoordinator", "PlatformAdmin"])
    records = list(db.subscription_add_ons.values())
    for key in ("add_on_id", "subscription_id"):
        val = request.args.get(key)
        if val is not None:
            records = [r for r in records if r[key] == val]
    return list_response(records)


# ==========================================================================
# WEEKLY BOX
# ==========================================================================
@app.route("/subscriptions/<sid>/weekly-boxes", methods=["GET"])
def list_subscription_boxes(sid):
    require_role(ALL_AUTH_ROLES)
    must_get(db.subscriptions, sid)
    records = services.boxes_for(sid)
    status = request.args.get("status")
    if status is not None:
        records = [r for r in records if r["status"] == status]
    return list_response(records)


@app.route("/weekly-boxes/<bid>", methods=["GET"])
def get_weekly_box(bid):
    require_role(ALL_AUTH_ROLES)
    return success(public(must_get(db.weekly_boxes, bid)), status=200)


@app.route("/weekly-boxes", methods=["GET"])
def list_weekly_boxes():
    require_role(["FarmManager", "DeliveryCoordinator", "PlatformAdmin"])
    records = list(db.weekly_boxes.values())
    for key in ("site_id", "subscription_id"):
        val = request.args.get(key)
        if val is not None:
            records = [r for r in records if r[key] == val]
    status = request.args.get("status")
    if status is not None:
        records = [r for r in records if r["status"] == status]
    return list_response(records)


@app.route("/weekly-boxes/<bid>/pack", methods=["POST"])
def pack_box(bid):
    require_role(["FarmManager"])
    box = must_get(db.weekly_boxes, bid)
    # state validity (priority 6)
    if box["status"] != "SCHEDULED":
        raise err(ERR_INVALID_STATE, "Box is not SCHEDULED.")
    site = db.pickup_sites.get(box["site_id"])
    # capacity guard (PRD §3.6): active_subscription_count <= weekly_capacity
    if site is not None and not (site["active_subscription_count"] <= site["weekly_capacity"]):
        raise err(ERR_SITE_CAPACITY_FULL, "Site weekly capacity exceeded.")

    sub = db.subscriptions.get(box["subscription_id"])
    share_type = db.share_types.get(sub["share_type_id"]) if sub else None
    items = share_type["items_per_box"] if share_type else 0
    # double box if this box is the SWAP target of an ACTIVE hold
    if _is_active_swap_target(box["id"]):
        items = items * 2
    box["item_count"] = items
    box["status"] = "PACKED"
    touch(box)
    return success(public(box), status=200)


def _is_active_swap_target(box_id):
    return any(
        h["swap_target_box_id"] == box_id
        and h["mode"] == "SWAP"
        and h["status"] == "ACTIVE"
        for h in db.vacation_holds.values()
    )


@app.route("/weekly-boxes/<bid>/deliver", methods=["POST"])
def deliver_box(bid):
    require_role(["FarmManager"])
    box = must_get(db.weekly_boxes, bid)
    if box["status"] != "PACKED":
        raise err(ERR_INVALID_STATE, "Box is not PACKED.")
    box["status"] = "DELIVERED"
    touch(box)

    sub = db.subscriptions.get(box["subscription_id"])
    if sub is not None:
        # first DELIVERED box: billing CONFIRMED->ACTIVE, fulfillment
        # NOT_STARTED->IN_SEASON (PRD §3.6)
        delivered = [b for b in services.boxes_for(sub["id"])
                     if b["status"] == "DELIVERED"]
        if len(delivered) == 1:
            if sub["billing_status"] == "CONFIRMED":
                sub["billing_status"] = "ACTIVE"
                touch(sub)
            if sub["fulfillment_status"] == "NOT_STARTED" and \
                    sub["billing_status"] in ("CONFIRMED", "ACTIVE"):
                sub["fulfillment_status"] = "IN_SEASON"
                touch(sub)
        # all-terminal bubble-up -> COMPLETED
        services.maybe_complete_fulfillment(sub)
    return success(public(box), status=200)


# ==========================================================================
# VACATION HOLD
# ==========================================================================
@app.route("/vacation-holds", methods=["POST"])
def create_vacation_hold():
    user_id, role = require_role(["Member"])
    body = V.get_json_body()
    subscription_id = V.require_string(body, "subscription_id")
    held_box_id = V.require_string(body, "held_box_id")
    swap_target_box_id = body.get("swap_target_box_id")

    sub = fk_exists(db.subscriptions, subscription_id)
    check_owner_member(sub["member_id"], user_id, role)
    box = fk_exists(db.weekly_boxes, held_box_id)
    if swap_target_box_id is not None:
        fk_exists(db.weekly_boxes, swap_target_box_id)

    # held box must belong to the subscription
    if box["subscription_id"] != subscription_id:
        raise err(ERR_NOT_FOUND, "Held box does not belong to the subscription.")

    # state validity (priority 6): box must be SCHEDULED to be held
    if box["status"] != "SCHEDULED":
        raise err(ERR_INVALID_STATE, "Box is not SCHEDULED.")

    season = must_get(db.seasons, sub["season_id"])

    # temporal window (priority 8): clock strictly before delivery date
    now = db.get_clock()
    deliver_dt = services.box_delivery_date(season, box["week_index"])
    if deliver_dt is not None and now >= deliver_dt:
        raise err(ERR_HOLD_WINDOW_PASSED, "Hold window has passed.")

    # swap target validity (priority 9)
    mode = "REFUND"
    if swap_target_box_id is not None:
        target = db.weekly_boxes.get(swap_target_box_id)
        if (target is None
                or target["subscription_id"] != subscription_id
                or target["week_index"] <= box["week_index"]
                or target["status"] != "SCHEDULED"):
            raise err(ERR_INVALID_SWAP_TARGET, "Invalid swap target.")
        mode = "SWAP"

    rec = {
        "subscription_id": subscription_id,
        "held_box_id": held_box_id,
        "swap_target_box_id": swap_target_box_id,
        "mode": mode,
        "status": "ACTIVE",
    }
    stamp_new(rec)
    db.vacation_holds[rec["id"]] = rec

    # held box SCHEDULED -> HELD
    box["status"] = "HELD"
    touch(box)

    if mode == "REFUND":
        refund = calc.hold_refund_value(
            sub["season_price_cents"], season["week_count"], box["week_index"])
        if refund != 0:
            services.post_ledger(subscription_id, "CREDIT_HOLD_REFUND", -refund,
                                 "Vacation hold refund")
        services.recompute_balance(sub)
    # SWAP mode: no ledger change; double box arranged at pack/deliver time
    return success(public(rec), status=201)


@app.route("/vacation-holds/<hid>", methods=["GET"])
def get_vacation_hold(hid):
    require_role(ALL_AUTH_ROLES)
    return success(public(must_get(db.vacation_holds, hid)), status=200)


@app.route("/vacation-holds", methods=["GET"])
def list_vacation_holds():
    require_role(ALL_AUTH_ROLES)
    records = list(db.vacation_holds.values())
    for key in ("held_box_id", "swap_target_box_id", "subscription_id"):
        val = request.args.get(key)
        if val is not None:
            records = [r for r in records if r.get(key) == val]
    status = request.args.get("status")
    if status is not None:
        records = [r for r in records if r["status"] == status]
    return list_response(records)


@app.route("/subscriptions/<sid>/vacation-holds", methods=["GET"])
def list_subscription_holds(sid):
    require_role(ALL_AUTH_ROLES)
    must_get(db.subscriptions, sid)
    records = [h for h in db.vacation_holds.values()
               if h["subscription_id"] == sid]
    status = request.args.get("status")
    if status is not None:
        records = [r for r in records if r["status"] == status]
    return list_response(records)


@app.route("/vacation-holds/<hid>/release", methods=["POST"])
def release_vacation_hold(hid):
    user_id, role = require_role(["Member"])
    hold = must_get(db.vacation_holds, hid)
    sub = db.subscriptions.get(hold["subscription_id"])
    if sub is not None:
        check_owner_member(sub["member_id"], user_id, role)

    # state validity (priority 6): only ACTIVE holds release
    if hold["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Hold is not ACTIVE.")

    box = db.weekly_boxes.get(hold["held_box_id"])
    season = db.seasons.get(sub["season_id"]) if sub else None

    # temporal window (priority 8): clock strictly before delivery date
    if box is not None and season is not None:
        now = db.get_clock()
        deliver_dt = services.box_delivery_date(season, box["week_index"])
        if deliver_dt is not None and now >= deliver_dt:
            raise err(ERR_HOLD_WINDOW_PASSED, "Hold window has passed.")

    hold["status"] = "RELEASED"
    touch(hold)
    if box is not None and box["status"] == "HELD":
        box["status"] = "SCHEDULED"
        touch(box)

    # REFUND mode: reverse the CREDIT_HOLD_REFUND by posting an offsetting charge
    if hold["mode"] == "REFUND" and sub is not None and season is not None:
        refund = calc.hold_refund_value(
            sub["season_price_cents"], season["week_count"], box["week_index"])
        if refund != 0:
            services.post_ledger(hold["subscription_id"], "CHARGE_SEASON", refund,
                                 "Reversal of vacation-hold refund")
        services.recompute_balance(sub)
    return success(public(hold), status=200)


# ==========================================================================
# WAITLIST ENTRY (join is Anonymous / no auth)
# ==========================================================================
@app.route("/waitlist-entries", methods=["POST"])
def create_waitlist_entry():
    body = V.get_json_body()
    season_id = V.require_string(body, "season_id")
    member_id = V.require_string(body, "member_id")
    share_type_id = V.require_string(body, "share_type_id")
    requested_site_id = V.require_string(body, "requested_site_id")

    fk_exists(db.seasons, season_id)
    fk_exists(db.members, member_id)
    share_type = fk_exists(db.share_types, share_type_id)
    site = fk_exists(db.pickup_sites, requested_site_id)

    # season cohesion (priority 5)
    if share_type["season_id"] != season_id or site["season_id"] != season_id:
        raise err(ERR_SEASON_MISMATCH,
                  "ShareType/PickupSite must belong to the named season.")

    rec = {
        "season_id": season_id,
        "member_id": member_id,
        "share_type_id": share_type_id,
        "requested_site_id": requested_site_id,
        "status": "WAITING",
        "offer_expires_at": None,
    }
    stamp_new(rec)
    db.waitlist_entries[rec["id"]] = rec
    return success(public(rec), status=201)


@app.route("/waitlist-entries/<wid>", methods=["GET"])
def get_waitlist_entry(wid):
    require_role(ALL_AUTH_ROLES)
    return success(public(must_get(db.waitlist_entries, wid)), status=200)


@app.route("/waitlist-entries", methods=["GET"])
def list_waitlist_entries():
    require_role(ALL_AUTH_ROLES)
    records = list(db.waitlist_entries.values())
    for key in ("season_id", "member_id", "share_type_id", "requested_site_id"):
        val = request.args.get(key)
        if val is not None:
            records = [r for r in records if r[key] == val]
    status = request.args.get("status")
    if status is not None:
        records = [r for r in records if r["status"] == status]
    return list_response(records)


@app.route("/waitlist-entries/<wid>/accept", methods=["POST"])
def accept_waitlist_entry(wid):
    user_id, role = require_role(["Member"])
    entry = must_get(db.waitlist_entries, wid)
    check_owner_member(entry["member_id"], user_id, role)

    # state validity (priority 6): only OFFERED accepts
    if entry["status"] != "OFFERED":
        raise err(ERR_INVALID_STATE, "Waitlist entry is not OFFERED.")

    # temporal window (priority 10): clock <= offer_expires_at
    now = db.get_clock()
    exp = parse_iso(entry["offer_expires_at"])
    if exp is not None and now > exp:
        raise err(ERR_OFFER_EXPIRED, "Offer has expired.")

    entry["status"] = "CONVERTED"
    touch(entry)

    # create a fresh PENDING_PAYMENT subscription (PRD §3.8)
    sub = {
        "season_id": entry["season_id"],
        "member_id": entry["member_id"],
        "share_type_id": entry["share_type_id"],
        "current_site_id": entry["requested_site_id"],
        "working_share_opt_in": False,
        "billing_status": "PENDING_PAYMENT",
        "fulfillment_status": "NOT_STARTED",
        "season_price_cents": 0,
        "outstanding_balance_cents": 0,
    }
    stamp_new(sub)
    db.subscriptions[sub["id"]] = sub
    return success(public(entry), status=200)


@app.route("/waitlist-entries/<wid>/decline", methods=["POST"])
def decline_waitlist_entry(wid):
    user_id, role = require_role(["Member"])
    entry = must_get(db.waitlist_entries, wid)
    check_owner_member(entry["member_id"], user_id, role)
    if entry["status"] != "OFFERED":
        raise err(ERR_INVALID_STATE, "Waitlist entry is not OFFERED.")
    entry["status"] = "DECLINED"
    touch(entry)
    return success(public(entry), status=200)


# ==========================================================================
# WORK-SHARE SHIFT
# ==========================================================================
@app.route("/subscriptions/<sid>/work-share-shifts", methods=["POST"])
def create_work_share_shift(sid):
    user_id, role = require_role(["FarmManager", "Member"])
    body = V.get_json_body()
    sub = must_get(db.subscriptions, sid)
    # ownership only enforced for Member actors
    check_owner_member(sub["member_id"], user_id, role)

    scheduled_date = V.require_string(body, "scheduled_date")
    hours = V.require_number(body, "hours", positive=True)
    if parse_iso(scheduled_date) is None:
        raise err(ERR_INVALID_REQUEST, "scheduled_date must be ISO 8601.")

    # working-share gate (priority 12)
    if not sub["working_share_opt_in"]:
        raise err(ERR_NOT_WORKING_SHARE, "Subscription did not opt into working-share.")

    rec = {
        "subscription_id": sid,
        "scheduled_date": scheduled_date,
        "hours": hours,
        "status": "SCHEDULED",
        "credit_earned_cents": 0,
    }
    stamp_new(rec)
    db.work_share_shifts[rec["id"]] = rec
    return success(public(rec), status=201)


@app.route("/subscriptions/<sid>/work-share-shifts", methods=["GET"])
def list_work_share_shifts(sid):
    require_role(ALL_AUTH_ROLES)
    must_get(db.subscriptions, sid)
    records = [s for s in db.work_share_shifts.values()
               if s["subscription_id"] == sid]
    status = request.args.get("status")
    if status is not None:
        records = [r for r in records if r["status"] == status]
    return list_response(records)


@app.route("/work-share-shifts/<wsid>", methods=["GET"])
def get_work_share_shift(wsid):
    require_role(ALL_AUTH_ROLES)
    return success(public(must_get(db.work_share_shifts, wsid)), status=200)


@app.route("/work-share-shifts/<wsid>/complete", methods=["POST"])
def complete_work_share_shift(wsid):
    require_role(["FarmManager"])
    shift = must_get(db.work_share_shifts, wsid)
    sub = db.subscriptions.get(shift["subscription_id"])

    # state validity (priority 6)
    if shift["status"] != "SCHEDULED":
        raise err(ERR_INVALID_STATE, "Shift is not SCHEDULED.")
    # working-share gate (priority 12)
    if sub is None or not sub["working_share_opt_in"]:
        raise err(ERR_NOT_WORKING_SHARE, "Subscription did not opt into working-share.")

    # compute prior same-UTC-date COMPLETED hours, created earlier (§1.3)
    this_date = parse_iso(shift["scheduled_date"]).date()
    prior = 0
    for other in db.work_share_shifts.values():
        if other["id"] == wsid:
            continue
        if other["subscription_id"] != shift["subscription_id"]:
            continue
        if other["status"] != "COMPLETED":
            continue
        od = parse_iso(other["scheduled_date"])
        if od is None or od.date() != this_date:
            continue
        if other.get("_seq", 0) < shift.get("_seq", 0):
            prior += other["hours"]

    credit = calc.workshare_credit(shift["hours"], prior)
    shift["credit_earned_cents"] = credit
    shift["status"] = "COMPLETED"
    touch(shift)

    # cascade (PRD §3.9): ledger, wallet, balance
    if credit != 0:
        services.post_ledger(shift["subscription_id"], "CREDIT_WORKSHARE",
                             -credit, "Working-share labor credit")
    member = db.members.get(sub["member_id"])
    if member is not None:
        member["wallet_credit_cents"] += credit
        touch(member)
    services.recompute_balance(sub)
    return success(public(shift), status=200)


@app.route("/work-share-shifts/<wsid>/mark-no-show", methods=["POST"])
def mark_no_show_work_share_shift(wsid):
    require_role(["FarmManager"])
    shift = must_get(db.work_share_shifts, wsid)
    if shift["status"] != "SCHEDULED":
        raise err(ERR_INVALID_STATE, "Shift is not SCHEDULED.")
    shift["status"] = "NO_SHOW"
    touch(shift)
    return success(public(shift), status=200)


# ==========================================================================
# LEDGER / PAYMENTS
# ==========================================================================
@app.route("/subscriptions/<sid>/ledger-entries", methods=["GET"])
def list_ledger_entries(sid):
    require_role(ALL_AUTH_ROLES)
    must_get(db.subscriptions, sid)
    records = services.ledger_for(sid)
    entry_type = request.args.get("entry_type")
    if entry_type is not None:
        records = [r for r in records if r["entry_type"] == entry_type]
    return list_response(records)


@app.route("/subscriptions/<sid>/payments", methods=["POST"])
def apply_payment(sid):
    user_id, role = require_role(["Member", "FarmManager"])
    body = V.get_json_body()
    sub = must_get(db.subscriptions, sid)
    check_owner_member(sub["member_id"], user_id, role)

    amount_cents = V.require_int(body, "amount_cents", positive=True)
    memo = V.require_string(body, "memo", required=False, default="")

    # PAYMENT entries carry a negative amount (PRD §3.4)
    entry = services.post_ledger(sid, "PAYMENT", -amount_cents, memo)
    services.recompute_balance(sub)
    return success(public(entry), status=201)


# ==========================================================================
# CLOCK (PlatformAdmin test-driving)
# ==========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_role(["PlatformAdmin"])
    body = V.get_json_body()
    to_iso = V.require_string(body, "to_iso8601")
    dt = parse_iso(to_iso)
    if dt is None:
        raise err(ERR_INVALID_REQUEST, "to_iso8601 must be a valid ISO 8601 datetime.")
    db.set_clock(dt)
    # fire clock-driven transitions (PRD §3.11)
    services.run_clock_transitions()
    return success({"current_utc": to_iso}, status=200)


# ==========================================================================
# Entry point
# ==========================================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
