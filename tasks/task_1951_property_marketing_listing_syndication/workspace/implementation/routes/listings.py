from datetime import timedelta

from flask import Blueprint, request

import clock
from db import store
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_STALE_VERSION,
    ERR_NOT_FOUND,
    ERR_LISTING_INCOMPLETE,
    ERR_NO_READY_PHOTO,
    ERR_REVIEW_ALREADY_PENDING,
    ERR_COMPLIANCE_NOT_APPROVED,
    ERR_PRICE_UNCHANGED,
    ERR_PRICE_CHANGE_TOO_SMALL,
    ERR_RELIST_COOLDOWN_ACTIVE,
)
from middleware import (
    authenticate, require_roles, check_listing_ownership, get_body,
    f_str, f_int, f_num, f_dt, f_enum, invalid, not_found, paginate,
)
from response import success_object, success_list
from services import derived
from services.ops import (
    stamp, touch, append_event, scan_fair_housing, lifecycle_transition,
    queue_jobs_for_subscribed_subs,
)
from services.serialize import (
    listing_json, review_json, event_json, relist_request_json,
)

bp = Blueprint("listings", __name__)

READ_ROLES = ("ListingAgent", "MarketingCoordinator", "ComplianceOfficer",
              "MarketingDirector")
WRITE_ROLES = ("ListingAgent", "MarketingCoordinator")
PROPERTY_TYPES = ("SINGLE_FAMILY", "CONDO", "TOWNHOUSE", "MULTI_FAMILY", "LAND")


def get_listing_or_404(listing_id):
    listing = store.listings.get(listing_id)
    if listing is None:
        raise not_found("Listing not found")
    return listing


def load_for_mutation(listing_id):
    """Auth + role + (when resolvable) ownership; 404 when the id is unknown."""
    uid, role = authenticate()
    require_roles(role, WRITE_ROLES)
    listing = store.listings.get(listing_id)
    if listing is not None:
        check_listing_ownership(role, uid, listing)
    else:
        raise not_found("Listing not found")
    return uid, role, listing


# ---------------------------------------------------------------- listings


@bp.route("/listings", methods=["POST"])
def create_listing():
    uid, role = authenticate()
    require_roles(role, WRITE_ROLES)
    body = get_body()
    # Ownership (priority 3) on the raw body agent_id before FK resolution.
    raw_agent_id = body.get("agent_id")
    if role == "ListingAgent" and raw_agent_id is not None and raw_agent_id != uid:
        from errors import ERR_FORBIDDEN_OWNERSHIP
        raise ApiError(ERR_FORBIDDEN_OWNERSHIP, 403,
                       "ListingAgent may only create listings they own")
    # Existence (priority 4): agent_id must resolve when present.
    if raw_agent_id is not None and raw_agent_id not in store.agents:
        raise not_found("agent_id does not resolve")
    # Field validity (priority 5).
    agent_id = f_str(body, "agent_id", required=True)
    address_line1 = f_str(body, "address_line1", required=True)
    city = f_str(body, "city", required=True)
    state_code = f_str(body, "state_code", required=True)
    postal_code = f_str(body, "postal_code", required=True)
    property_type = f_enum(body, "property_type", PROPERTY_TYPES, required=True)
    list_price_cents = f_int(body, "list_price_cents", required=True)
    listing_expires_on = f_dt(body, "listing_expires_on", required=True)
    bedrooms = f_int(body, "bedrooms")
    bathrooms = f_num(body, "bathrooms")
    square_feet = f_int(body, "square_feet")
    marketing_remarks = f_str(body, "marketing_remarks")
    mls_number = f_str(body, "mls_number")
    # Fair-housing scan (priority 9) when remarks are present at creation.
    scan_fair_housing(marketing_remarks)
    now = clock.now()
    listing = stamp({
        "agent_id": agent_id,
        "address_line1": address_line1,
        "city": city,
        "state_code": state_code,
        "postal_code": postal_code,
        "property_type": property_type,
        "list_price_cents": list_price_cents,
        "listing_expires_on": listing_expires_on,
        "bedrooms": bedrooms,
        "bathrooms": bathrooms,
        "square_feet": square_feet,
        "marketing_remarks": marketing_remarks,
        "mls_number": mls_number,
        "lifecycle_status": "DRAFT",
        "relist_count": 0,
        "terminal_entered_at": None,
        "terminal_price_cents": None,
    }, now)
    store.listings[listing["id"]] = listing
    return success_object(listing_json(listing, now), status=201)


@bp.route("/listings", methods=["GET"])
def list_listings():
    _, role = authenticate()
    require_roles(role, READ_ROLES)
    agent_id = request.args.get("agent_id")
    lifecycle = request.args.get("lifecycle_status")
    items = sorted(store.listings.values(),
                   key=lambda l: (l["created_at"], l["_seq"]))
    if agent_id is not None:
        items = [l for l in items if l["agent_id"] == agent_id]
    if lifecycle is not None:
        items = [l for l in items if l["lifecycle_status"] == lifecycle]
    page, limit, offset, total = paginate(items)
    now = clock.now()
    return success_list([listing_json(l, now) for l in page], limit, offset, total)


@bp.route("/listings/<listing_id>", methods=["GET"])
def get_listing(listing_id):
    _, role = authenticate()
    require_roles(role, READ_ROLES)
    listing = get_listing_or_404(listing_id)
    return success_object(listing_json(listing, clock.now()))


@bp.route("/listings/<listing_id>", methods=["PATCH"])
def patch_listing(listing_id):
    _, _, listing = load_for_mutation(listing_id)
    body = get_body()
    expected = f_int(body, "expected_listing_version", required=True)
    bedrooms = f_int(body, "bedrooms")
    bathrooms = f_num(body, "bathrooms")
    square_feet = f_int(body, "square_feet")
    marketing_remarks = f_str(body, "marketing_remarks")
    mls_number = f_str(body, "mls_number")
    expires = f_dt(body, "listing_expires_on")
    now = clock.now()
    # Posture guard (priority 7).
    if derived.compute_posture(listing, now) == "SUSPENDED":
        from errors import ERR_POSTURE_SUSPENDED
        raise ApiError(ERR_POSTURE_SUSPENDED, 409,
                       "Mutation forbidden while posture is SUSPENDED")
    # OCC (priority 8).
    if expected != listing["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_listing_version does not match current version")
    # Fair-housing scan (priority 9) on the new remarks when supplied.
    if "marketing_remarks" in body and marketing_remarks is not None:
        scan_fair_housing(marketing_remarks)
    if "bedrooms" in body:
        listing["bedrooms"] = bedrooms
    if "bathrooms" in body:
        listing["bathrooms"] = bathrooms
    if "square_feet" in body:
        listing["square_feet"] = square_feet
    remarks_changed = False
    if "marketing_remarks" in body and marketing_remarks != listing["marketing_remarks"]:
        old_remarks = listing["marketing_remarks"]
        listing["marketing_remarks"] = marketing_remarks
        remarks_changed = True
    if "mls_number" in body:
        listing["mls_number"] = mls_number
    if "listing_expires_on" in body:
        listing["listing_expires_on"] = expires
    if remarks_changed:
        append_event(listing, now, "REMARKS_UPDATE",
                     old_remarks=old_remarks, new_remarks=marketing_remarks)
        if listing["lifecycle_status"] == "ACTIVE":
            queue_jobs_for_subscribed_subs(listing, "REMARKS_UPDATE", now)
    touch(listing, now)
    return success_object(listing_json(listing, now))


# ------------------------------------------------- lifecycle state machine


@bp.route("/listings/<listing_id>/submit-review", methods=["POST"])
def submit_review(listing_id):
    _, _, listing = load_for_mutation(listing_id)
    get_body()
    now = clock.now()
    # State gate admits DRAFT and PENDING_REVIEW: a PENDING review can only
    # coexist with a PENDING_REVIEW listing, so §3.3's fourth check
    # (ERR_REVIEW_ALREADY_PENDING) is reachable only from PENDING_REVIEW.
    if listing["lifecycle_status"] not in ("DRAFT", "PENDING_REVIEW"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "submit-review requires lifecycle DRAFT")
    # Business checks in PRD 3.3 order: scan, completeness, photo, pending.
    scan_fair_housing(listing["marketing_remarks"])
    if any(listing[k] is None for k in
           ("bedrooms", "bathrooms", "square_feet", "marketing_remarks", "mls_number")):
        raise ApiError(ERR_LISTING_INCOMPLETE, 422,
                       "Listing is missing required fields")
    has_ready_photo = any(
        m["listing_id"] == listing["id"] and m["kind"] == "PHOTO"
        and m["status"] == "READY"
        for m in store.media_assets.values())
    if not has_ready_photo:
        raise ApiError(ERR_NO_READY_PHOTO, 422,
                       "No READY PHOTO media asset for this listing")
    if any(r["listing_id"] == listing["id"] and r["status"] == "PENDING"
           for r in store.reviews.values()):
        raise ApiError(ERR_REVIEW_ALREADY_PENDING, 409,
                       "A PENDING compliance review already exists")
    review = stamp({
        "listing_id": listing["id"],
        "status": "PENDING",
        "remarks_snapshot": listing["marketing_remarks"],
        "flagged_terms": None,
        "notes": None,
        "decided_at": None,
    }, now)
    store.reviews[review["id"]] = review
    append_event(listing, now, "STATUS_CHANGE",
                 from_lifecycle=listing["lifecycle_status"],
                 to_lifecycle="PENDING_REVIEW")
    listing["lifecycle_status"] = "PENDING_REVIEW"
    touch(listing, now)
    return success_object(review_json(review), status=201)


@bp.route("/listings/<listing_id>/activate", methods=["POST"])
def activate(listing_id):
    _, _, listing = load_for_mutation(listing_id)
    get_body()
    now = clock.now()
    if listing["lifecycle_status"] != "PENDING_REVIEW":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "activate requires lifecycle PENDING_REVIEW")
    if not now < listing["listing_expires_on"]:
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Listing agreement has expired")
    reviews = [r for r in store.reviews.values()
               if r["listing_id"] == listing["id"]]
    latest = max(reviews, key=lambda r: (r["created_at"], r["_seq"]), default=None)
    if latest is None or latest["status"] != "APPROVED":
        raise ApiError(ERR_COMPLIANCE_NOT_APPROVED, 409,
                       "Latest compliance review is not APPROVED")
    listing["lifecycle_status"] = "ACTIVE"
    append_event(listing, now, "STATUS_CHANGE",
                 from_lifecycle="PENDING_REVIEW", to_lifecycle="ACTIVE")
    touch(listing, now)
    return success_object(listing_json(listing, now))


@bp.route("/listings/<listing_id>/revise", methods=["POST"])
def revise(listing_id):
    _, _, listing = load_for_mutation(listing_id)
    get_body()
    now = clock.now()
    if listing["lifecycle_status"] != "COMPLIANCE_HOLD":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "revise requires lifecycle COMPLIANCE_HOLD")
    listing["lifecycle_status"] = "DRAFT"
    append_event(listing, now, "STATUS_CHANGE",
                 from_lifecycle="COMPLIANCE_HOLD", to_lifecycle="DRAFT")
    touch(listing, now)
    return success_object(listing_json(listing, now))


@bp.route("/listings/<listing_id>/mark-under-contract", methods=["POST"])
def mark_under_contract(listing_id):
    _, _, listing = load_for_mutation(listing_id)
    get_body()
    now = clock.now()
    if listing["lifecycle_status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "mark-under-contract requires lifecycle ACTIVE")
    listing["lifecycle_status"] = "UNDER_CONTRACT"
    append_event(listing, now, "STATUS_CHANGE",
                 from_lifecycle="ACTIVE", to_lifecycle="UNDER_CONTRACT")
    touch(listing, now)
    queue_jobs_for_subscribed_subs(listing, "STATUS_UPDATE", now)
    return success_object(listing_json(listing, now))


@bp.route("/listings/<listing_id>/reactivate", methods=["POST"])
def reactivate(listing_id):
    _, _, listing = load_for_mutation(listing_id)
    get_body()
    now = clock.now()
    if listing["lifecycle_status"] != "UNDER_CONTRACT":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "reactivate requires lifecycle UNDER_CONTRACT")
    listing["lifecycle_status"] = "ACTIVE"
    append_event(listing, now, "STATUS_CHANGE",
                 from_lifecycle="UNDER_CONTRACT", to_lifecycle="ACTIVE")
    touch(listing, now)
    queue_jobs_for_subscribed_subs(listing, "STATUS_UPDATE", now)
    return success_object(listing_json(listing, now))


@bp.route("/listings/<listing_id>/close-sold", methods=["POST"])
def close_sold(listing_id):
    _, _, listing = load_for_mutation(listing_id)
    get_body()
    now = clock.now()
    if listing["lifecycle_status"] != "UNDER_CONTRACT":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "close-sold requires lifecycle UNDER_CONTRACT")
    lifecycle_transition(listing, "SOLD", now,
                         terminal=False, queue_terminal_sync=True)
    return success_object(listing_json(listing, now))


@bp.route("/listings/<listing_id>/withdraw", methods=["POST"])
def withdraw(listing_id):
    _, _, listing = load_for_mutation(listing_id)
    get_body()
    now = clock.now()
    if listing["lifecycle_status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "withdraw requires lifecycle ACTIVE")
    lifecycle_transition(listing, "WITHDRAWN", now,
                         terminal=True, queue_terminal_sync=True)
    return success_object(listing_json(listing, now))


# ------------------------------------------------------------------ relist


def _cooldown_until(listing):
    if listing["terminal_entered_at"] is None:
        return None
    return listing["terminal_entered_at"] + timedelta(
        days=derived.RELIST_COOLDOWN_DAYS)


@bp.route("/listings/<listing_id>/relist", methods=["POST"])
def relist(listing_id):
    _, _, listing = load_for_mutation(listing_id)
    body = get_body()
    new_price = f_int(body, "new_list_price_cents")
    new_remarks = f_str(body, "new_marketing_remarks")
    now = clock.now()
    if listing["lifecycle_status"] not in ("WITHDRAWN", "EXPIRED"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "relist requires lifecycle WITHDRAWN or EXPIRED")
    # Safety scan runs before the cooldown check (PRD 2.10 / 3.9).
    scan_fair_housing(new_remarks if new_remarks is not None
                      else listing["marketing_remarks"])
    until = _cooldown_until(listing)
    if until is None or now < until:
        raise ApiError(ERR_RELIST_COOLDOWN_ACTIVE, 422,
                       "Fewer than 30 days since terminal entry")
    effective = new_price if new_price is not None else listing["list_price_cents"]
    fee, pct = derived.relist_fee_and_pct(listing, new_price)
    record = stamp({
        "listing_id": listing["id"],
        "relist_count_before": listing["relist_count"],
        "price_reduction_pct": pct,
        "new_list_price_cents": effective,
        "fee_cents": fee,
    }, now)
    store.relist_requests[record["id"]] = record
    listing["relist_count"] += 1
    if new_price is not None:
        append_event(listing, now, "PRICE_CHANGE",
                     old_price_cents=listing["list_price_cents"],
                     new_price_cents=new_price)
        listing["list_price_cents"] = new_price
    old = listing["lifecycle_status"]
    listing["lifecycle_status"] = "DRAFT"
    append_event(listing, now, "STATUS_CHANGE",
                 from_lifecycle=old, to_lifecycle="DRAFT")
    touch(listing, now)
    return success_object(relist_request_json(record), status=201)


@bp.route("/listings/<listing_id>/relist-quote", methods=["GET"])
def relist_quote(listing_id):
    uid, role = authenticate()
    require_roles(role, ("ListingAgent", "MarketingCoordinator",
                         "MarketingDirector"))
    listing = get_listing_or_404(listing_id)
    raw = request.args.get("new_list_price_cents")
    new_price = None
    if raw is not None:
        try:
            new_price = int(raw)
        except (ValueError, TypeError):
            raise invalid("new_list_price_cents must be an integer")
    now = clock.now()
    until = _cooldown_until(listing)
    eligible = (listing["lifecycle_status"] in ("WITHDRAWN", "EXPIRED")
                and until is not None and now >= until)
    fee, pct = derived.relist_fee_and_pct(listing, new_price)
    return success_object({
        "eligible": eligible,
        "fee_cents": fee,
        "cooldown_until": clock.iso_fmt(until),
        "relist_count_before": listing["relist_count"],
        "price_reduction_pct": pct,
    })


@bp.route("/listings/<listing_id>/relist-requests", methods=["GET"])
def relist_requests(listing_id):
    _, role = authenticate()
    require_roles(role, ("ListingAgent", "MarketingCoordinator",
                         "MarketingDirector"))
    listing = get_listing_or_404(listing_id)
    items = sorted(
        (r for r in store.relist_requests.values()
         if r["listing_id"] == listing["id"]),
        key=lambda r: (r["created_at"], r["_seq"]))
    page, limit, offset, total = paginate(items)
    return success_list([relist_request_json(r) for r in page],
                        limit, offset, total)


# ------------------------------------------------- summary / events / price


@bp.route("/listings/<listing_id>/summary", methods=["GET"])
def summary(listing_id):
    _, role = authenticate()
    require_roles(role, READ_ROLES)
    listing = get_listing_or_404(listing_id)
    now = clock.now()
    audited, provisional = derived.compute_breach_counts(listing["id"], now)
    raw, weighted = derived.compute_scores(listing["id"], now)
    return success_object({
        "listing_id": listing["id"],
        "lifecycle_status": listing["lifecycle_status"],
        "syndication_posture": derived.compute_posture(listing, now),
        "feedback_score_raw": raw,
        "feedback_score_weighted": weighted,
        "audited_breach_count": audited,
        "provisional_breach_count": provisional,
        "headline_display_price_cents":
            derived.headline_display_price_cents(listing),
        "relist_count": listing["relist_count"],
    })


@bp.route("/listings/<listing_id>/events", methods=["GET"])
def list_events(listing_id):
    _, role = authenticate()
    require_roles(role, READ_ROLES)
    listing = get_listing_or_404(listing_id)
    event_type = request.args.get("event_type")
    items = sorted(
        (e for e in store.events.values() if e["listing_id"] == listing["id"]),
        key=lambda e: e["seq"])
    if event_type is not None:
        items = [e for e in items if e["event_type"] == event_type]
    page, limit, offset, total = paginate(items)
    return success_list([event_json(e) for e in page], limit, offset, total)


@bp.route("/listings/<listing_id>/price-changes", methods=["POST"])
def price_change(listing_id):
    from decimal import Decimal, ROUND_HALF_UP
    _, _, listing = load_for_mutation(listing_id)
    body = get_body()
    new_price = f_int(body, "new_price_cents", required=True)
    expected = f_int(body, "expected_listing_version", required=True)
    f_str(body, "change_reason")
    now = clock.now()
    if listing["lifecycle_status"] not in ("ACTIVE", "UNDER_CONTRACT"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "price changes require lifecycle ACTIVE or UNDER_CONTRACT")
    if derived.compute_posture(listing, now) == "SUSPENDED":
        from errors import ERR_POSTURE_SUSPENDED
        raise ApiError(ERR_POSTURE_SUSPENDED, 409,
                       "Mutation forbidden while posture is SUSPENDED")
    if expected != listing["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_listing_version does not match current version")
    current = listing["list_price_cents"]
    if new_price == current:
        raise ApiError(ERR_PRICE_UNCHANGED, 422,
                       "new_price_cents equals current price")
    delta = abs(new_price - current)
    delta_pct = Decimal(0)
    if current:
        delta_pct = (Decimal(100) * Decimal(delta) / Decimal(current)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP)
    if delta < 50000 and delta_pct < Decimal("1.0"):
        raise ApiError(ERR_PRICE_CHANGE_TOO_SMALL, 422,
                       "Price change below materiality threshold")
    old_price = listing["list_price_cents"]
    listing["list_price_cents"] = new_price
    ev = append_event(listing, now, "PRICE_CHANGE",
                      old_price_cents=old_price, new_price_cents=new_price)
    touch(listing, now)
    queue_jobs_for_subscribed_subs(listing, "PRICE_UPDATE", now)
    return success_object(event_json(ev), status=201)
