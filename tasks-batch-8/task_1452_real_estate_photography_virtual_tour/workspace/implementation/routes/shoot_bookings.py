"""ShootBooking endpoints — core workflow."""

from datetime import timedelta
from flask import Blueprint, request

from db import store
from errors import (
    ApiError, invalid_request, not_found, forbidden,
)
import errors
from middleware import require_roles
from response import success_object, success_list, parse_pagination
from serializers import (
    booking_json, checklist_item_json, addon_json, authorization_json,
    bundle_json, revision_json, tour_json, license_json, reschedule_event_json,
)
from services.domain import (
    touch, sweep_clock, spawn_default_checklist, refresh_readiness,
    cascade_cancel_booking, release_assignment, create_authorization,
    maybe_advance_to_confirmed, active_drone_addons, has_active_drone,
    pending_auths, approved_auths, recompute_booking_window,
    CANCELLABLE_STATES, RESCHEDULABLE_STATES, OPEN_COMMITTED_STATES,
    SHOOT_OR_LATER_STATES,
)
from services.calculations import (
    shoot_duration_minutes, provisional_quote, addon_price_cents,
    addon_extra_minutes, turnaround_deadline, final_invoice,
    license_fee_cents, paid_revision_fee_cents, weather_credit_apply,
    photographer_conflict, capacity_ok, recompute_committed_minutes,
    DRONE_KINDS, REVISION_HARD_CAP, RESCHEDULE_HARD_CAP,
)
from timeutil import (
    new_id, iso_now_ms, now_dt, parse_iso, is_quarter_hour, dt_to_iso,
)

bp = Blueprint("shoot_bookings", __name__)

VALID_PACKAGES = {"STANDARD", "PREMIUM", "LUXURY"}
VALID_TOUR_VARIANTS = {"BRANDED", "UNBRANDED"}
VALID_LICENSE_TIERS = {"MLS_COMPLIANT", "STANDARD_MARKETING", "EXTENDED"}
VALID_ADDON_KINDS = {"TWILIGHT_UPGRADE", "DRONE_STILLS", "DRONE_VIDEO", "RUSH_EDIT", "VIRTUAL_STAGING"}
VALID_WEATHER_REASONS = {"PRECIPITATION", "WIND", "LOW_LIGHT"}
VALID_CLIENT_REASONS = {"SELLER_DELAY", "ACCESS_ISSUE", "STAGING_DELAY"}


def _get_booking_or_404(booking_id):
    b = store.bookings.get(booking_id)
    if not b:
        raise not_found("ShootBooking not found")
    return b


def _get_market(booking):
    return store.markets.get(booking["market_id"])


def _validate_booking_create(data):
    for f in ("order_ref", "market_id", "property_address", "equipment_package",
              "photo_count", "scheduled_start_utc"):
        if f not in data:
            raise invalid_request(f"Missing required field: {f}")
    if data["equipment_package"] not in VALID_PACKAGES:
        raise invalid_request("equipment_package must be STANDARD, PREMIUM, or LUXURY")
    pc = data["photo_count"]
    if not isinstance(pc, int) or isinstance(pc, bool) or pc < 10 or pc > 100:
        raise invalid_request("photo_count must be an integer 10..100")
    if "wants_virtual_tour" in data and not isinstance(data["wants_virtual_tour"], bool):
        raise invalid_request("wants_virtual_tour must be a boolean")
    if "tour_variant" in data and data["tour_variant"] is not None:
        if data["tour_variant"] not in VALID_TOUR_VARIANTS:
            raise invalid_request("tour_variant must be BRANDED or UNBRANDED")
    if "license_tier" in data and data["license_tier"] not in VALID_LICENSE_TIERS:
        raise invalid_request("license_tier must be MLS_COMPLIANT, STANDARD_MARKETING, or EXTENDED")
    if "is_twilight" in data and not isinstance(data["is_twilight"], bool):
        raise invalid_request("is_twilight must be a boolean")
    start = parse_iso(data["scheduled_start_utc"])
    if start is None:
        raise invalid_request("scheduled_start_utc must be a valid ISO 8601 datetime")
    if not is_quarter_hour(start):
        raise ApiError(errors.ERR_INVALID_SLOT_ALIGNMENT, 422,
                       "scheduled_start_utc must land on a quarter-hour boundary")
    wants_tour = data.get("wants_virtual_tour", False)
    tour_variant = data.get("tour_variant")
    if wants_tour and tour_variant is None:
        raise invalid_request("tour_variant is required when wants_virtual_tour=true")


@bp.route("/shoot-bookings", methods=["POST"])
def create_booking():
    user_id, _ = require_roles("ClientAgent")
    data = request.get_json(silent=True) or {}
    _validate_booking_create(data)
    if data["market_id"] not in store.markets:
        raise not_found("Market not found")
    for b in store.bookings.values():
        if b["order_ref"] == data["order_ref"]:
            raise invalid_request("order_ref must be unique")
    market = store.markets[data["market_id"]]
    start = parse_iso(data["scheduled_start_utc"])
    is_twilight = data.get("is_twilight", False)
    duration = shoot_duration_minutes(
        data["equipment_package"], data["photo_count"], is_twilight, market
    )
    now = iso_now_ms()
    booking = {
        "id": new_id(),
        "order_ref": data["order_ref"],
        "client_agent_id": user_id,
        "market_id": data["market_id"],
        "property_address": data["property_address"],
        "equipment_package": data["equipment_package"],
        "photo_count": data["photo_count"],
        "wants_virtual_tour": data.get("wants_virtual_tour", False),
        "tour_variant": data.get("tour_variant"),
        "license_tier": data.get("license_tier", "MLS_COMPLIANT"),
        "scheduled_start_utc": start,
        "scheduled_end_utc": start + timedelta(minutes=duration),
        "shoot_duration_minutes": duration,
        "is_twilight": is_twilight,
        "state": "DRAFT",
        "assigned_photographer_id": None,
        "provisional_quote_cents": None,
        "final_invoice_cents": None,
        "weather_credit_cents": 0,
        "reschedule_count": 0,
        "delivery_due_utc": None,
        "delivered_at_utc": None,
        "revision_window_closes_utc": None,
        "revisions_used": 0,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "addons_at_submit_cents": 0,
    }
    store.bookings[booking["id"]] = booking
    return success_object(booking_json(booking), http_status=201)


@bp.route("/shoot-bookings", methods=["GET"])
def list_bookings():
    require_roles("ClientAgent", "Photographer", "Coordinator", "OpsAdmin")
    sweep_clock()
    limit, offset = parse_pagination(request.args)
    items = sorted(store.bookings.values(), key=lambda b: b["created_at"])
    for f in ("market_id", "state", "client_agent_id", "assigned_photographer_id"):
        v = request.args.get(f)
        if v is not None:
            items = [b for b in items if b.get(f) == v]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([booking_json(b) for b in page], limit, offset, total)


@bp.route("/shoot-bookings/<booking_id>", methods=["GET"])
def get_booking(booking_id):
    require_roles("ClientAgent", "Photographer", "Coordinator", "OpsAdmin")
    sweep_clock()
    b = _get_booking_or_404(booking_id)
    return success_object(booking_json(b))


@bp.route("/shoot-bookings/<booking_id>", methods=["PATCH"])
def patch_booking(booking_id):
    user_id, _ = require_roles("ClientAgent")
    b = _get_booking_or_404(booking_id)
    data = request.get_json(silent=True) or {}
    # Validate enum/payload shapes early
    if "equipment_package" in data and data["equipment_package"] not in VALID_PACKAGES:
        raise invalid_request("equipment_package must be STANDARD, PREMIUM, or LUXURY")
    if "photo_count" in data:
        v = data["photo_count"]
        if not isinstance(v, int) or isinstance(v, bool) or v < 10 or v > 100:
            raise invalid_request("photo_count must be 10..100")
    if "tour_variant" in data and data["tour_variant"] is not None and data["tour_variant"] not in VALID_TOUR_VARIANTS:
        raise invalid_request("tour_variant must be BRANDED or UNBRANDED")
    if "license_tier" in data and data["license_tier"] not in VALID_LICENSE_TIERS:
        raise invalid_request("license_tier must be MLS_COMPLIANT, STANDARD_MARKETING, or EXTENDED")
    if "wants_virtual_tour" in data and not isinstance(data["wants_virtual_tour"], bool):
        raise invalid_request("wants_virtual_tour must be a boolean")
    if "scheduled_start_utc" in data:
        st = parse_iso(data["scheduled_start_utc"])
        if st is None:
            raise invalid_request("scheduled_start_utc invalid")
        if not is_quarter_hour(st):
            raise ApiError(errors.ERR_INVALID_SLOT_ALIGNMENT, 422,
                           "scheduled_start_utc must land on a quarter-hour boundary")
    # State gate
    if b["state"] != "DRAFT":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "PATCH only allowed while DRAFT")
    # Ownership
    if b["client_agent_id"] != user_id:
        raise forbidden("Only the owning ClientAgent may patch this booking")
    # OCC
    if "expected_booking_version" not in data:
        raise invalid_request("expected_booking_version is required")
    expected = data["expected_booking_version"]
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise invalid_request("expected_booking_version must be an integer")
    if expected != b["version"]:
        raise ApiError(errors.ERR_STALE_VERSION, 412,
                       "expected_booking_version does not match current version")
    # Apply mutations
    touched_window = False
    if "equipment_package" in data:
        b["equipment_package"] = data["equipment_package"]
        touched_window = True
    if "photo_count" in data:
        b["photo_count"] = data["photo_count"]
        touched_window = True
    if "wants_virtual_tour" in data:
        b["wants_virtual_tour"] = data["wants_virtual_tour"]
    if "tour_variant" in data:
        b["tour_variant"] = data["tour_variant"]
    if "license_tier" in data:
        b["license_tier"] = data["license_tier"]
    if "scheduled_start_utc" in data:
        b["scheduled_start_utc"] = parse_iso(data["scheduled_start_utc"])
        touched_window = True
    if b["wants_virtual_tour"] and b.get("tour_variant") is None:
        raise invalid_request("tour_variant is required when wants_virtual_tour=true")
    if touched_window:
        market = _get_market(b)
        b["shoot_duration_minutes"] = shoot_duration_minutes(
            b["equipment_package"], b["photo_count"], b["is_twilight"], market
        )
        recompute_booking_window(b)
    touch(b)
    return success_object(booking_json(b))


@bp.route("/shoot-bookings/<booking_id>/submit", methods=["POST"])
def submit_booking(booking_id):
    user_id, _ = require_roles("ClientAgent")
    b = _get_booking_or_404(booking_id)
    if b["state"] != "DRAFT":
        raise ApiError(errors.ERR_BOOKING_NOT_IN_DRAFT, 409,
                       "submit requires DRAFT")
    if b["client_agent_id"] != user_id:
        raise forbidden("Only the owning ClientAgent may submit")
    market = _get_market(b)
    if market["status"] != "ACTIVE":
        raise ApiError(errors.ERR_MARKET_SUSPENDED, 409, "Market is SUSPENDED")
    if b["scheduled_start_utc"] < now_dt() + timedelta(hours=24):
        raise ApiError(errors.ERR_SLOT_TOO_SOON, 422,
                       "scheduled_start_utc must be >= now + 24h")
    quote, addons_at_submit = provisional_quote(b, market)
    b["provisional_quote_cents"] = quote
    b["addons_at_submit_cents"] = addons_at_submit
    spawn_default_checklist(b)
    b["state"] = "AWAITING_READINESS"
    touch(b)
    return success_object(booking_json(b))


@bp.route("/shoot-bookings/<booking_id>/cancel", methods=["POST"])
def cancel_booking(booking_id):
    user_id, _ = require_roles("ClientAgent")
    b = _get_booking_or_404(booking_id)
    if b["state"] not in CANCELLABLE_STATES:
        raise ApiError(errors.ERR_BOOKING_NOT_CANCELLABLE, 409,
                       "cancel not allowed from current state")
    if b["client_agent_id"] != user_id:
        raise forbidden("Only the owning ClientAgent may cancel")
    if b["state"] == "CONFIRMED":
        cutoff = b["scheduled_start_utc"] - timedelta(hours=12)
        if now_dt() >= cutoff:
            raise ApiError(errors.ERR_INSIDE_CANCELLATION_CUTOFF, 422,
                           "Cannot cancel within 12h of scheduled start")
    cascade_cancel_booking(b)
    b["state"] = "CANCELLED_BY_CLIENT"
    touch(b)
    return success_object(booking_json(b))


@bp.route("/shoot-bookings/<booking_id>/assign", methods=["POST"])
def assign_booking(booking_id):
    require_roles("Coordinator")
    b = _get_booking_or_404(booking_id)
    data = request.get_json(silent=True) or {}
    if "photographer_id" not in data:
        raise invalid_request("Missing required field: photographer_id")
    if b["state"] != "READY":
        raise ApiError(errors.ERR_BOOKING_NOT_READY, 409, "assign requires READY")
    p = store.photographers.get(data["photographer_id"])
    if not p:
        raise not_found("Photographer not found")
    if p["status"] != "ACTIVE" or p["market_id"] != b["market_id"]:
        raise ApiError(errors.ERR_PHOTOGRAPHER_NOT_ELIGIBLE, 422,
                       "Photographer INACTIVE or wrong market")
    if b["equipment_package"] not in p["equipment_packages"]:
        raise ApiError(errors.ERR_EQUIPMENT_MISMATCH, 422,
                       "Photographer lacks equipment_package")
    drone_active = has_active_drone(b)
    if drone_active and not p["drone_certified"]:
        raise ApiError(errors.ERR_DRONE_CERT_REQUIRED, 422,
                       "Photographer must be drone_certified")
    market = _get_market(b)
    if photographer_conflict(p, b, b["scheduled_start_utc"], b["scheduled_end_utc"], market):
        raise ApiError(errors.ERR_PHOTOGRAPHER_DOUBLE_BOOKED, 409,
                       "Window collides with existing assignment")
    if not capacity_ok(p, b, b["scheduled_start_utc"], b["scheduled_end_utc"]):
        raise ApiError(errors.ERR_DAY_CAPACITY_EXCEEDED, 409,
                       "Day capacity exceeded")
    b["assigned_photographer_id"] = p["id"]
    if drone_active:
        # Move through ASSIGNED into AUTHORIZATION_PENDING
        b["state"] = "AUTHORIZATION_PENDING"
        for addon in active_drone_addons(b):
            create_authorization(b, addon, attempt_number=1)
    else:
        b["state"] = "ASSIGNED"
    recompute_committed_minutes(p)
    touch(p)
    touch(b)
    return success_object(booking_json(b))


@bp.route("/shoot-bookings/<booking_id>/unassign", methods=["POST"])
def unassign_booking(booking_id):
    require_roles("Coordinator")
    b = _get_booking_or_404(booking_id)
    # PRD §3.3: unassignment "is refused while any airspace authorization on
    # the booking sits in `APPROVED`". An APPROVED authorization only exists
    # on a CONFIRMED booking (approval auto-advances AUTHORIZATION_PENDING →
    # CONFIRMED), so this airspace-safety check must run before the state
    # check, otherwise it would be unreachable.
    if approved_auths(b["id"]):
        raise ApiError(errors.ERR_AUTHORIZATION_STILL_VALID, 409,
                       "Approved authorization must first be obviated by reschedule")
    if b["state"] not in ("ASSIGNED", "AUTHORIZATION_PENDING"):
        raise ApiError(errors.ERR_BOOKING_NOT_ASSIGNED, 409,
                       "unassign requires ASSIGNED or AUTHORIZATION_PENDING")
    # Cancel PENDING/REJECTED authorizations
    for auth in store.airspace_authorizations.values():
        if auth["booking_id"] == b["id"] and auth["state"] in ("PENDING", "REJECTED"):
            auth["state"] = "CANCELLED"
            touch(auth)
    release_assignment(b)
    b["state"] = "READY"
    touch(b)
    return success_object(booking_json(b))


@bp.route("/shoot-bookings/<booking_id>/confirm", methods=["POST"])
def confirm_booking(booking_id):
    require_roles("Coordinator")
    b = _get_booking_or_404(booking_id)
    # PRD §3.3: "attempting to confirm around an unresolved drone authorization
    # fails with `ERR_AUTHORIZATION_PENDING`" — a booking sitting in
    # AUTHORIZATION_PENDING is in that state precisely because a drone
    # authorization is unresolved, so the drone-gate error wins over the
    # generic state-legality error for that state.
    if b["state"] == "AUTHORIZATION_PENDING":
        raise ApiError(errors.ERR_AUTHORIZATION_PENDING, 409,
                       "Drone add-on requires authorization flow")
    if b["state"] != "ASSIGNED":
        raise ApiError(errors.ERR_BOOKING_NOT_ASSIGNED, 409, "confirm requires ASSIGNED")
    if has_active_drone(b):
        raise ApiError(errors.ERR_AUTHORIZATION_PENDING, 409,
                       "Drone add-on requires authorization flow")
    b["state"] = "CONFIRMED"
    touch(b)
    return success_object(booking_json(b))


@bp.route("/shoot-bookings/<booking_id>/mark-shot", methods=["POST"])
def mark_shot(booking_id):
    user_id, _ = require_roles("Photographer")
    b = _get_booking_or_404(booking_id)
    if b["state"] != "CONFIRMED":
        raise ApiError(errors.ERR_BOOKING_NOT_CONFIRMED, 409, "mark-shot requires CONFIRMED")
    if b.get("assigned_photographer_id") != user_id:
        raise forbidden("Only the assigned Photographer may mark shot")
    now = now_dt()
    win_start = b["scheduled_start_utc"] - timedelta(hours=2)
    win_end = b["scheduled_end_utc"] + timedelta(hours=24)
    if not (win_start <= now <= win_end):
        raise ApiError(errors.ERR_OUTSIDE_SHOOT_WINDOW, 422,
                       "mark-shot outside [start-2h, end+24h]")
    market = _get_market(b)
    # Create AssetBundle in EDITING with round_number=1
    bundle = {
        "id": new_id(),
        "booking_id": b["id"],
        "state": "EDITING",
        "photo_asset_count": None,
        "tour_asset_url": None,
        "delivered_at_utc": None,
        "round_number": 1,
        "created_at": iso_now_ms(),
        "updated_at": iso_now_ms(),
        "version": 1,
    }
    store.asset_bundles[bundle["id"]] = bundle
    b["delivery_due_utc"] = turnaround_deadline(b, market, now)
    # Walk through SHOT to IN_EDIT
    b["state"] = "IN_EDIT"
    touch(b)
    return success_object(booking_json(b))


@bp.route("/shoot-bookings/<booking_id>/deliver", methods=["POST"])
def deliver(booking_id):
    user_id, _ = require_roles("Photographer")
    b = _get_booking_or_404(booking_id)
    data = request.get_json(silent=True) or {}
    if "photo_asset_count" not in data:
        raise invalid_request("Missing required field: photo_asset_count")
    if not isinstance(data["photo_asset_count"], int) or isinstance(data["photo_asset_count"], bool):
        raise invalid_request("photo_asset_count must be an integer")
    if b["state"] not in ("IN_EDIT", "REVISION_REQUESTED"):
        raise ApiError(errors.ERR_BOOKING_NOT_IN_EDIT, 409,
                       "deliver requires IN_EDIT or REVISION_REQUESTED")
    if b.get("assigned_photographer_id") != user_id:
        raise forbidden("Only the assigned Photographer may deliver")
    # Quality gates
    if data["photo_asset_count"] < b["photo_count"]:
        raise ApiError(errors.ERR_QUALITY_GUARANTEE_SHORTFALL, 422,
                       "photo_asset_count below contracted photo_count")
    tour_url = data.get("tour_asset_url")
    if b["wants_virtual_tour"] and not tour_url:
        raise ApiError(errors.ERR_TOUR_ASSET_MISSING, 422,
                       "tour_asset_url required when wants_virtual_tour")
    now = now_dt()
    is_first_delivery = b["delivered_at_utc"] is None

    if b["state"] == "REVISION_REQUESTED":
        # Find prior DELIVERED bundle (latest round) — supersede it
        prior_bundles = [x for x in store.asset_bundles.values()
                         if x["booking_id"] == b["id"] and x["state"] == "DELIVERED"]
        prior_bundles.sort(key=lambda x: x["round_number"])
        prior = prior_bundles[-1] if prior_bundles else None
        # Open revisions on prior bundle must be addressed (we just resolve them)
        if prior:
            open_revs = [r for r in store.revisions.values()
                         if r["bundle_id"] == prior["id"] and r["state"] in ("OPEN", "IN_PROGRESS")]
            # The gate says revisions must be "addressed by the new bundle" — delivering
            # the new bundle constitutes addressing them.
            for r in open_revs:
                r["state"] = "RESOLVED"
                touch(r)
            prior["state"] = "SUPERSEDED"
            touch(prior)
            new_round = prior["round_number"] + 1
        else:
            new_round = 1
        # Create new bundle and deliver it
        bundle = {
            "id": new_id(),
            "booking_id": b["id"],
            "state": "DELIVERED",
            "photo_asset_count": data["photo_asset_count"],
            "tour_asset_url": tour_url,
            "delivered_at_utc": now,
            "round_number": new_round,
            "created_at": iso_now_ms(),
            "updated_at": iso_now_ms(),
            "version": 1,
        }
        store.asset_bundles[bundle["id"]] = bundle
        # revision_window_closes_utc NOT extended
    else:
        # First delivery — current EDITING bundle becomes DELIVERED
        bundles = [x for x in store.asset_bundles.values()
                   if x["booking_id"] == b["id"] and x["state"] == "EDITING"]
        bundles.sort(key=lambda x: x["created_at"])
        if not bundles:
            raise ApiError(errors.ERR_BOOKING_NOT_IN_EDIT, 409, "No EDITING bundle found")
        bundle = bundles[-1]
        bundle["state"] = "DELIVERED"
        bundle["photo_asset_count"] = data["photo_asset_count"]
        bundle["tour_asset_url"] = tour_url
        bundle["delivered_at_utc"] = now
        touch(bundle)
        b["delivered_at_utc"] = now
        b["revision_window_closes_utc"] = now + timedelta(hours=72)
        # Spawn entourage
        if b["wants_virtual_tour"]:
            tour = {
                "id": new_id(),
                "booking_id": b["id"],
                "variant": b["tour_variant"],
                "state": "HOSTED",
                "hosted_url": f"https://tours.realestate-media.example/{b['id']}",
                "published_at_utc": None,
                "created_at": iso_now_ms(),
                "updated_at": iso_now_ms(),
                "version": 1,
            }
            store.virtual_tours[tour["id"]] = tour
        license_grant = {
            "id": new_id(),
            "booking_id": b["id"],
            "tier": b["license_tier"],
            "state": "DORMANT",
            "activated_at_utc": None,
            "fee_cents": None,
            "created_at": iso_now_ms(),
            "updated_at": iso_now_ms(),
            "version": 1,
        }
        store.license_grants[license_grant["id"]] = license_grant

    b["state"] = "DELIVERED"
    touch(b)
    return success_object(bundle_json(bundle))


@bp.route("/shoot-bookings/<booking_id>/accept", methods=["POST"])
def accept(booking_id):
    user_id, _ = require_roles("ClientAgent")
    b = _get_booking_or_404(booking_id)
    if b["state"] != "DELIVERED":
        raise ApiError(errors.ERR_BOOKING_NOT_DELIVERED, 409, "accept requires DELIVERED")
    if b["client_agent_id"] != user_id:
        raise forbidden("Only the owning ClientAgent may accept")
    open_revs = [r for r in store.revisions.values()
                 if r["booking_id"] == b["id"] and r["state"] in ("OPEN", "IN_PROGRESS")]
    if open_revs:
        raise ApiError(errors.ERR_OPEN_REVISIONS_EXIST, 409,
                       "OPEN/IN_PROGRESS revisions block acceptance")
    if b["tour_variant"] == "UNBRANDED" and b["license_tier"] != "MLS_COMPLIANT":
        raise ApiError(errors.ERR_UNBRANDED_REQUIRES_MLS_TIER, 422,
                       "UNBRANDED tour requires MLS_COMPLIANT tier")
    market = _get_market(b)
    # License activation
    grant = next((g for g in store.license_grants.values() if g["booking_id"] == b["id"]), None)
    fee = license_fee_cents(b["license_tier"], b["tour_variant"])
    if grant is not None:
        grant["state"] = "ACTIVE"
        grant["activated_at_utc"] = now_dt()
        grant["tier"] = b["license_tier"]
        grant["fee_cents"] = fee
        touch(grant)
    # Final invoice
    b["final_invoice_cents"] = final_invoice(b, market, grant)
    # Tour publish
    tour = next((t for t in store.virtual_tours.values() if t["booking_id"] == b["id"]), None)
    if tour is not None and tour["state"] == "HOSTED":
        tour["state"] = "PUBLISHED"
        tour["published_at_utc"] = now_dt()
        touch(tour)
    # Bundle finalize
    latest = None
    for bun in store.asset_bundles.values():
        if bun["booking_id"] == b["id"] and bun["state"] == "DELIVERED":
            if latest is None or bun["round_number"] > latest["round_number"]:
                latest = bun
    if latest is not None:
        latest["state"] = "FINALIZED"
        touch(latest)
    # Weather credit settles against invoice; zero it on the booking
    b["weather_credit_cents"] = 0
    b["state"] = "ACCEPTED"
    touch(b)
    return success_object(booking_json(b))


@bp.route("/shoot-bookings/<booking_id>/reschedule", methods=["POST"])
def reschedule(booking_id):
    user_id, _ = require_roles("ClientAgent")
    b = _get_booking_or_404(booking_id)
    data = request.get_json(silent=True) or {}
    for f in ("expected_booking_version", "kind", "new_start_utc", "reason_code"):
        if f not in data:
            raise invalid_request(f"Missing required field: {f}")
    kind = data["kind"]
    if kind not in ("WEATHER", "CLIENT"):
        raise invalid_request("kind must be WEATHER or CLIENT")
    new_start = parse_iso(data["new_start_utc"])
    if new_start is None:
        raise invalid_request("new_start_utc invalid")
    expected = data["expected_booking_version"]
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise invalid_request("expected_booking_version must be an integer")

    # State gate
    if b["state"] not in RESCHEDULABLE_STATES:
        raise ApiError(errors.ERR_BOOKING_NOT_RESCHEDULABLE, 409,
                       "reschedule not allowed from current state")
    # Ownership
    if b["client_agent_id"] != user_id:
        raise forbidden("Only the owning ClientAgent may reschedule")
    # OCC
    if expected != b["version"]:
        raise ApiError(errors.ERR_STALE_VERSION, 412,
                       "expected_booking_version does not match current version")
    # Cap
    at_cap = b["reschedule_count"] >= RESCHEDULE_HARD_CAP
    if at_cap:
        if kind == "CLIENT":
            raise ApiError(errors.ERR_RESCHEDULE_CAP_EXCEEDED, 409,
                           "reschedule_count already 3")
        # WEATHER at cap -> CANCELLED_WEATHER path; still validate reason_code
        if data["reason_code"] not in VALID_WEATHER_REASONS:
            raise ApiError(errors.ERR_INVALID_REASON_CODE, 422,
                           "reason_code inconsistent with kind")
        market = _get_market(b)
        # Final weather cancellation credit = one weather_reschedule_credit application
        quote = b["provisional_quote_cents"] or 0
        raw = int((quote * market["weather_reschedule_credit_bps"] + 5000) // 10000)
        agent = store.client_agents.get(b["client_agent_id"])
        if agent:
            agent["credit_balance_cents"] += raw
            touch(agent)
        cascade_cancel_booking(b)
        b["state"] = "CANCELLED_WEATHER"
        touch(b)
        return success_object(booking_json(b))

    # Validate reason code matches kind
    if kind == "WEATHER":
        if data["reason_code"] not in VALID_WEATHER_REASONS:
            raise ApiError(errors.ERR_INVALID_REASON_CODE, 422,
                           "reason_code must be PRECIPITATION, WIND, or LOW_LIGHT for WEATHER")
    else:
        if data["reason_code"] not in VALID_CLIENT_REASONS:
            raise ApiError(errors.ERR_INVALID_REASON_CODE, 422,
                           "reason_code must be SELLER_DELAY, ACCESS_ISSUE, or STAGING_DELAY for CLIENT")

    # Temporal gates
    if not is_quarter_hour(new_start):
        raise ApiError(errors.ERR_INVALID_SLOT_ALIGNMENT, 422,
                       "new_start_utc must be quarter-hour aligned")
    if new_start < now_dt() + timedelta(hours=24):
        raise ApiError(errors.ERR_SLOT_TOO_SOON, 422,
                       "new_start_utc must be >= now + 24h")

    market = _get_market(b)
    old_start = b["scheduled_start_utc"]

    # Compute new end using current shoot_duration + active add-on minutes
    addon_minutes = sum(
        a["extra_minutes"] for a in store.addons.values()
        if a["booking_id"] == b["id"] and a["state"] == "ACTIVE"
    )
    new_end = new_start + timedelta(minutes=b["shoot_duration_minutes"] + addon_minutes)

    # Re-validate photographer on new window
    photographer_kept = True
    p = None
    if b.get("assigned_photographer_id"):
        p = store.photographers.get(b["assigned_photographer_id"])
        if p:
            if photographer_conflict(p, b, new_start, new_end, market):
                photographer_kept = False
            elif not capacity_ok(p, b, new_start, new_end):
                photographer_kept = False
        else:
            photographer_kept = False

    # Apply event
    credit_applied = 0
    if kind == "WEATHER":
        credit_applied = weather_credit_apply(b, market)
    event = {
        "id": new_id(),
        "booking_id": b["id"],
        "kind": kind,
        "old_start_utc": old_start,
        "new_start_utc": new_start,
        "reason_code": data["reason_code"],
        "credit_applied_cents": credit_applied,
        "created_at": iso_now_ms(),
    }
    store.reschedule_events[event["id"]] = event
    b["reschedule_count"] += 1
    b["scheduled_start_utc"] = new_start
    b["scheduled_end_utc"] = new_end
    b["delivery_due_utc"] = None

    # Reset checklist
    for it in store.checklist_items.values():
        if it["booking_id"] == b["id"]:
            if it["checked"]:
                it["checked"] = False
                it["checked_at_utc"] = None
                touch(it)

    # Photographer
    if not photographer_kept:
        release_assignment(b)

    # Authorizations: expire APPROVED whose window no longer matches; cancel PENDING/REJECTED; re-create as needed
    drone_addons = active_drone_addons(b)
    drone_addon_ids = {a["id"] for a in drone_addons}
    for auth in list(store.airspace_authorizations.values()):
        if auth["booking_id"] != b["id"]:
            continue
        if auth["state"] == "APPROVED":
            if auth["window_start_utc"] != new_start or auth["window_end_utc"] != new_end:
                auth["state"] = "EXPIRED"
                touch(auth)
        elif auth["state"] in ("PENDING", "REJECTED"):
            auth["state"] = "CANCELLED"
            touch(auth)
    if drone_addons:
        # Reissue for each drone addon
        for addon in drone_addons:
            prior_attempts = [a["attempt_number"] for a in store.airspace_authorizations.values()
                              if a["addon_id"] == addon["id"]]
            next_attempt = (max(prior_attempts) + 1) if prior_attempts else 1
            if next_attempt > 3:
                addon["state"] = "REFUSED"
                touch(addon)
            else:
                create_authorization(b, addon, next_attempt)

    # Determine landing state. PRD §3.9 explicitly: "the booking lands in
    # `ASSIGNED` — a `CONFIRMED` booking drops back to `ASSIGNED`, and one
    # waiting on airspace approval leaves `AUTHORIZATION_PENDING`". Even when
    # a fresh PENDING authorization is minted by the cascade, the booking
    # still lands in ASSIGNED; the auth gate is re-applied at confirm time.
    if not photographer_kept:
        b["state"] = "READY"
    else:
        b["state"] = "ASSIGNED"
    if photographer_kept and p:
        recompute_committed_minutes(p)
        touch(p)
    touch(b)
    return success_object(booking_json(b))


# ---- Checklist items ----

@bp.route("/shoot-bookings/<booking_id>/checklist-items", methods=["GET"])
def list_checklist(booking_id):
    require_roles("ClientAgent", "Photographer", "Coordinator", "OpsAdmin")
    sweep_clock()
    b = _get_booking_or_404(booking_id)
    limit, offset = parse_pagination(request.args)
    items = sorted(
        (it for it in store.checklist_items.values() if it["booking_id"] == b["id"]),
        key=lambda x: x["created_at"],
    )
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([checklist_item_json(it) for it in page], limit, offset, total)


@bp.route("/shoot-bookings/<booking_id>/checklist-items/<itemId>", methods=["PATCH"])
def patch_checklist_item(booking_id, itemId):
    user_id, _ = require_roles("ClientAgent")
    b = _get_booking_or_404(booking_id)
    it = store.checklist_items.get(itemId)
    if not it or it["booking_id"] != b["id"]:
        raise not_found("Checklist item not found")
    data = request.get_json(silent=True) or {}
    if "checked" not in data or not isinstance(data["checked"], bool):
        raise invalid_request("checked must be a boolean")
    # Ownership
    if b["client_agent_id"] != user_id:
        raise forbidden("Only the owning ClientAgent may patch checklist")
    # Immutability gate
    if b["state"] in SHOOT_OR_LATER_STATES:
        raise ApiError(errors.ERR_CHECKLIST_ITEM_IMMUTABLE, 409,
                       "Checklist frozen once booking reaches SHOT")
    prev_checked = it["checked"]
    new_checked = data["checked"]
    flipped_off = False
    if new_checked and not prev_checked:
        it["checked"] = True
        it["checked_at_utc"] = now_dt()
    elif not new_checked and prev_checked:
        it["checked"] = False
        it["checked_at_utc"] = None
        flipped_off = it["required"]
    touch(it)
    refresh_readiness(b, item_was_unchecked=flipped_off)
    return success_object(checklist_item_json(it))


# ---- AddOns ----

@bp.route("/shoot-bookings/<booking_id>/addons", methods=["POST"])
def create_addon(booking_id):
    user_id, _ = require_roles("ClientAgent")
    b = _get_booking_or_404(booking_id)
    data = request.get_json(silent=True) or {}
    if "kind" not in data:
        raise invalid_request("Missing required field: kind")
    kind = data["kind"]
    if kind not in VALID_ADDON_KINDS:
        raise invalid_request("Invalid add-on kind")
    if b["state"] not in CANCELLABLE_STATES:
        raise ApiError(errors.ERR_BOOKING_NOT_CANCELLABLE, 409,
                       "add-on not allowed in current booking state")
    if b["client_agent_id"] != user_id:
        raise forbidden("Only the owning ClientAgent may add add-ons")
    market = _get_market(b)
    # TWILIGHT_UPGRADE rules
    if kind == "TWILIGHT_UPGRADE":
        if b["is_twilight"]:
            raise ApiError(errors.ERR_TWILIGHT_CONFLICT, 409,
                           "Booking already flagged twilight")
    if kind in DRONE_KINDS:
        # Duplicate drone check
        for a in store.addons.values():
            if a["booking_id"] == b["id"] and a["state"] == "ACTIVE" and a["kind"] in DRONE_KINDS:
                raise ApiError(errors.ERR_DUPLICATE_DRONE_ADDON, 409,
                               "Booking already has an ACTIVE drone add-on")
    addon = {
        "id": new_id(),
        "booking_id": b["id"],
        "kind": kind,
        "state": "ACTIVE",
        "price_cents": addon_price_cents(kind, market),
        "extra_minutes": addon_extra_minutes(kind),
        "created_at": iso_now_ms(),
        "updated_at": iso_now_ms(),
        "version": 1,
    }
    store.addons[addon["id"]] = addon
    if kind == "TWILIGHT_UPGRADE":
        b["is_twilight"] = True
        # Recompute duration under twilight semantics
        b["shoot_duration_minutes"] = market["twilight_slot_minutes"]
    recompute_booking_window(b)
    # Drone triggers authorization flow when ASSIGNED/CONFIRMED
    if kind in DRONE_KINDS and b["state"] in ("ASSIGNED", "CONFIRMED"):
        create_authorization(b, addon, attempt_number=1)
        b["state"] = "AUTHORIZATION_PENDING"
    touch(b)
    return success_object(addon_json(addon), http_status=201)


@bp.route("/shoot-bookings/<booking_id>/addons", methods=["GET"])
def list_addons(booking_id):
    require_roles("ClientAgent", "Photographer", "Coordinator", "OpsAdmin")
    sweep_clock()
    b = _get_booking_or_404(booking_id)
    limit, offset = parse_pagination(request.args)
    items = sorted(
        (a for a in store.addons.values() if a["booking_id"] == b["id"]),
        key=lambda x: x["created_at"],
    )
    state = request.args.get("state")
    if state is not None:
        items = [a for a in items if a["state"] == state]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([addon_json(a) for a in page], limit, offset, total)


@bp.route("/shoot-bookings/<booking_id>/addons/<addonId>", methods=["GET"])
def get_addon(booking_id, addonId):
    require_roles("ClientAgent", "Photographer", "Coordinator", "OpsAdmin")
    sweep_clock()
    b = _get_booking_or_404(booking_id)
    a = store.addons.get(addonId)
    if not a or a["booking_id"] != b["id"]:
        raise not_found("AddOn not found")
    return success_object(addon_json(a))


@bp.route("/shoot-bookings/<booking_id>/addons/<addonId>/cancel", methods=["POST"])
def cancel_addon(booking_id, addonId):
    user_id, _ = require_roles("ClientAgent")
    b = _get_booking_or_404(booking_id)
    a = store.addons.get(addonId)
    if not a or a["booking_id"] != b["id"]:
        raise not_found("AddOn not found")
    if a["state"] != "ACTIVE":
        raise ApiError(errors.ERR_ADDON_NOT_CANCELLABLE, 409, "AddOn not ACTIVE")
    if b["state"] in SHOOT_OR_LATER_STATES:
        raise ApiError(errors.ERR_BOOKING_NOT_RESCHEDULABLE, 409,
                       "Booking already SHOT")
    if b["client_agent_id"] != user_id:
        raise forbidden("Only the owning ClientAgent may cancel add-ons")
    a["state"] = "CANCELLED"
    touch(a)
    if a["kind"] in DRONE_KINDS:
        for auth in store.airspace_authorizations.values():
            if auth["addon_id"] == a["id"] and auth["state"] in ("PENDING", "REJECTED", "APPROVED"):
                auth["state"] = "CANCELLED"
                touch(auth)
        # If booking was waiting on auth and none pending remains -> CONFIRMED
        maybe_advance_to_confirmed(b)
    if a["kind"] == "TWILIGHT_UPGRADE":
        b["is_twilight"] = False
        market = _get_market(b)
        b["shoot_duration_minutes"] = shoot_duration_minutes(
            b["equipment_package"], b["photo_count"], False, market
        )
    recompute_booking_window(b)
    touch(b)
    return success_object(addon_json(a))
