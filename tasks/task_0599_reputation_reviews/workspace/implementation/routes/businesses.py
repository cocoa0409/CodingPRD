"""Businesses, locations (create/list), contacts and response templates."""

from decimal import Decimal

from flask import Blueprint, request

import store
import validation as v
from auth import endpoint, resolve_business
from envelope import created, ok, paginate
from errors import err
from services import touch

bp = Blueprint("businesses", __name__)

POSTURES = ("OPEN", "RESTRICTED", "FROZEN")


@bp.post("/reputation/businesses")
@endpoint(["PlatformAdmin"])
def create_business():
    data = v.body()
    name = v.req_str(data, "name")
    plan_tier = v.opt_enum(data, "plan_tier", v.PLAN_TIERS, "BASIC")
    cap_days = v.opt_int(data, "default_frequency_cap_days", 30, minimum=1)

    rec = store.base_record()
    rec.update({
        "name": name,
        "plan_tier": plan_tier,
        "default_frequency_cap_days": cap_days,
        "location_count": 0,
    })
    store.businesses[rec["id"]] = rec
    return created(store.business_out(rec))


@bp.get("/reputation/businesses/<business_id>")
@endpoint(["PlatformAdmin", "BusinessOwner"])
def get_business(business_id):
    biz = resolve_business(business_id)
    return ok(store.business_out(biz))


@bp.post("/reputation/businesses/<business_id>/locations")
@endpoint(["PlatformAdmin", "BusinessOwner"])
def create_location(business_id):
    biz = resolve_business(business_id)
    data = v.body()
    name = v.req_str(data, "name")
    nap_name = v.req_str(data, "nap_name")
    nap_address = v.req_str(data, "nap_address")
    nap_phone = v.req_str(data, "nap_phone")

    rec = store.base_record()
    rec.update({
        "business_id": business_id,
        "name": name,
        "nap_name": nap_name,
        "nap_address": nap_address,
        "nap_phone": nap_phone,
        "compliance_hold": False,
        "posture": "OPEN",
        "review_count": 0,
        "avg_rating": Decimal("0.00"),
        "responded_review_count": 0,
        "sentiment_positive_count": 0,
        "sentiment_neutral_count": 0,
        "sentiment_negative_count": 0,
        "reputation_score_provisional": Decimal("0.00"),
        "reputation_score_certified": Decimal("0.00"),
        "certified_at": None,
        "listing_health_score": Decimal("0.00"),
        "nps_score": Decimal("0.00"),
        "open_escalation_count": 0,
    })
    store.locations[rec["id"]] = rec

    biz["location_count"] += 1
    touch(biz)
    return created(store.location_out(rec))


@bp.get("/reputation/businesses/<business_id>/locations")
@endpoint(["PlatformAdmin", "BusinessOwner"])
def list_locations(business_id):
    resolve_business(business_id)
    posture = v.enum_filter("posture", POSTURES)
    rows = [l for l in store.locations.values() if l["business_id"] == business_id]
    if posture is not None:
        rows = [l for l in rows if l["posture"] == posture]
    return paginate(store.by_created(rows), store.location_out)


@bp.post("/reputation/businesses/<business_id>/contacts")
@endpoint(["PlatformAdmin", "BusinessOwner", "LocationManager"])
def create_contact(business_id):
    resolve_business(business_id)
    data = v.body()
    full_name = v.req_str(data, "full_name")
    email = v.opt_str(data, "email")
    phone = v.opt_str(data, "phone")
    sms_consent = v.opt_bool(data, "sms_consent", False)
    email_consent = v.opt_bool(data, "email_consent", True)

    rec = store.base_record()
    rec.update({
        "business_id": business_id,
        "full_name": full_name,
        "email": email,
        "phone": phone,
        "sms_consent": sms_consent,
        "email_consent": email_consent,
        "opted_out": False,
        "last_requested_at": None,
        "request_count": 0,
    })
    store.contacts[rec["id"]] = rec
    return created(store.contact_out(rec))


@bp.get("/reputation/businesses/<business_id>/contacts")
@endpoint(["PlatformAdmin", "BusinessOwner", "LocationManager"])
def list_contacts(business_id):
    resolve_business(business_id)
    rows = [c for c in store.contacts.values() if c["business_id"] == business_id]
    raw = request.args.get("opted_out")
    if raw is not None:
        if raw not in ("true", "false"):
            raise err("ERR_INVALID_REQUEST", "opted_out must be true or false.")
        want = raw == "true"
        rows = [c for c in rows if c["opted_out"] == want]
    return paginate(store.by_created(rows), store.contact_out)


@bp.post("/reputation/businesses/<business_id>/templates")
@endpoint(["PlatformAdmin", "BusinessOwner"])
def create_template(business_id):
    resolve_business(business_id)
    data = v.body()
    name = v.req_str(data, "name")
    body_text = v.req_str(data, "body")
    min_rating = v.req_int(data, "min_rating", minimum=1, maximum=5)
    max_rating = v.req_int(data, "max_rating", minimum=1, maximum=5)
    if max_rating < min_rating:
        raise err("ERR_INVALID_REQUEST", "max_rating must be >= min_rating.")
    requires_approval = v.opt_bool(data, "requires_approval", True)

    rec = store.base_record()
    rec.update({
        "business_id": business_id,
        "name": name,
        "body": body_text,
        "min_rating": min_rating,
        "max_rating": max_rating,
        "requires_approval": requires_approval,
    })
    store.templates[rec["id"]] = rec
    return created(store.template_out(rec))


@bp.get("/reputation/businesses/<business_id>/templates")
@endpoint(["PlatformAdmin", "BusinessOwner", "ResponseAgent"])
def list_templates(business_id):
    resolve_business(business_id)
    rows = [t for t in store.templates.values() if t["business_id"] == business_id]
    return paginate(store.by_created(rows), store.template_out)
