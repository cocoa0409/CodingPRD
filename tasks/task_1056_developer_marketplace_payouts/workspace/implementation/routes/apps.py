"""App listings, review rounds, analytics and pricing-plan attachment."""
from decimal import Decimal

from flask import Blueprint, g, request

from core import (
    PRICING_COOLDOWN_HOURS,
    authenticate,
    db,
    fail,
    filter_eq,
    get_body,
    new_record,
    ok,
    ok_list,
    ordered,
    pagination,
    paginate,
    public,
    req_dt,
    req_enum,
    req_int,
    req_str,
    req_str_array,
    opt_int,
    require_owner,
    rhu,
    touch,
)
from services import jurisdiction_for, lookup

bp = Blueprint("apps", __name__)

CATEGORIES = {"PRODUCTIVITY", "GAMES", "FINANCE", "HEALTH", "DEVELOPER_TOOLS"}
PLAN_KINDS = {"ONE_TIME", "SUBSCRIPTION", "IAP"}
SCORED = {"CAPTURED", "PARTIALLY_REFUNDED", "REFUNDED", "CHARGED_BACK"}


@bp.post("/api/apps")
def create_app():
    authenticate({"Developer"})
    body = get_body()
    developer_id = body.get("developer_id")
    if isinstance(developer_id, str) and developer_id != g.user_id:
        fail("ERR_NOT_RESOURCE_OWNER", "developer_id must equal X-User-ID.")
    developer_id = req_str(body, "developer_id")
    name = req_str(body, "name")
    category = req_enum(body, "category", CATEGORIES)
    listed_countries = req_str_array(body, "listed_countries")
    lookup("developers", developer_id)
    rec = new_record(
        developer_id=developer_id,
        name=name,
        category=category,
        listed_countries=listed_countries,
        status="DRAFT",
        review_round=0,
        policy_strike_count=0,
    )
    db.apps[rec["id"]] = rec
    return ok(public(rec), 201)


@bp.get("/api/apps")
def list_apps():
    authenticate({"Developer", "ReviewAgent", "PolicyOfficer", "PlatformAdmin",
                  "FinanceOps", "StorefrontService"})
    limit, offset = pagination()
    rows = ordered(db.apps)
    rows = filter_eq(rows, "developer_id")
    rows = filter_eq(rows, "status")
    rows = filter_eq(rows, "category")
    items, total = paginate(rows, limit, offset)
    return ok_list(items, limit, offset, total)


@bp.get("/api/apps/<app_id>")
def read_app(app_id):
    authenticate({"Developer", "ReviewAgent", "PolicyOfficer", "PlatformAdmin",
                  "FinanceOps", "StorefrontService"})
    app = lookup("apps", app_id)
    require_owner(app["developer_id"])
    return ok(public(app))


@bp.patch("/api/apps/<app_id>")
def edit_app(app_id):
    authenticate({"Developer"})
    app = lookup("apps", app_id)
    require_owner(app["developer_id"])
    body = get_body()
    if "name" in body and body["name"] is not None:
        app["name"] = req_str(body, "name")
    if "category" in body and body["category"] is not None:
        app["category"] = req_enum(body, "category", CATEGORIES)
    if "listed_countries" in body and body["listed_countries"] is not None:
        app["listed_countries"] = req_str_array(body, "listed_countries")
    if app["status"] == "CHANGES_REQUESTED":
        app["status"] = "DRAFT"
    touch(app)
    return ok(public(app))


@bp.post("/api/apps/<app_id>/submit-for-review")
def submit_for_review(app_id):
    authenticate({"Developer"})
    app = lookup("apps", app_id)
    require_owner(app["developer_id"])
    body = get_body()
    submitted_notes = req_str(body, "submitted_notes")
    if app["status"] not in ("DRAFT", "CHANGES_REQUESTED"):
        fail("ERR_INVALID_STATE", "Listing is not submittable from its current state.")
    has_active_plan = any(
        p["app_id"] == app["id"] and p["status"] == "ACTIVE"
        for p in ordered(db.pricing_plans)
    )
    if not has_active_plan:
        fail("ERR_INVALID_STATE", "Listing has no ACTIVE pricing plan.")
    app["status"] = "IN_REVIEW"
    app["review_round"] = app["review_round"] + 1
    touch(app)
    submission = new_record(
        app_id=app["id"],
        round_number=app["review_round"],
        submitted_notes=submitted_notes,
        status="SUBMITTED",
        triaged_by_user_id=None,
        decision_reason=None,
    )
    db.review_submissions[submission["id"]] = submission
    return ok(public(submission), 201)


@bp.post("/api/apps/<app_id>/publish")
def publish_app(app_id):
    authenticate({"Developer"})
    app = lookup("apps", app_id)
    require_owner(app["developer_id"])
    if app["status"] != "APPROVED":
        fail("ERR_INVALID_STATE", "Listing is not APPROVED.")
    dev = db.developers.get(app["developer_id"])
    if dev is None or dev["status"] != "ACTIVE":
        fail("ERR_DEVELOPER_NOT_ACTIVE", "Owning developer is not ACTIVE.")
    app["status"] = "LIVE"
    touch(app)
    return ok(public(app))


@bp.post("/api/apps/<app_id>/suspend")
def suspend_app(app_id):
    authenticate({"PolicyOfficer"})
    app = lookup("apps", app_id)
    body = get_body()
    req_str(body, "reason")
    if app["status"] != "LIVE":
        fail("ERR_INVALID_STATE", "Listing is not LIVE.")
    app["status"] = "SUSPENDED"
    touch(app)
    return ok(public(app))


@bp.post("/api/apps/<app_id>/reinstate")
def reinstate_app(app_id):
    authenticate({"PolicyOfficer"})
    app = lookup("apps", app_id)
    body = get_body()
    req_str(body, "reason")
    if app["status"] != "SUSPENDED":
        fail("ERR_INVALID_STATE", "Listing is not SUSPENDED.")
    dev = db.developers.get(app["developer_id"])
    if dev is None or dev["status"] != "ACTIVE":
        fail("ERR_DEVELOPER_NOT_ACTIVE", "Owning developer is not ACTIVE.")
    app["status"] = "LIVE"
    touch(app)
    return ok(public(app))


@bp.post("/api/apps/<app_id>/delist")
def delist_app_route(app_id):
    from services import delist_app

    authenticate({"PolicyOfficer"})
    app = lookup("apps", app_id)
    body = get_body()
    req_str(body, "reason")
    if app["status"] == "DELISTED":
        fail("ERR_INVALID_STATE", "Listing is already DELISTED.")
    delist_app(app)
    return ok(public(app))


@bp.get("/api/apps/<app_id>/analytics")
def app_analytics(app_id):
    authenticate({"Developer", "PlatformAdmin", "FinanceOps"})
    app = lookup("apps", app_id)
    require_owner(app["developer_id"])
    scored = [
        p for p in ordered(db.purchases)
        if p["app_id"] == app["id"] and p["payment_status"] in SCORED
    ]
    gross = sum(p["gross_cents"] for p in scored)
    tax = sum(p["tax_cents"] for p in scored)
    base = sum(p["revenue_base_cents"] for p in scored)
    net = sum(p.get("provisional_developer_net_cents") or 0 for p in scored)
    refunded = sum(p.get("refunded_gross_cents", 0) for p in scored)
    units = sum(
        sum(li["quantity"] for li in p["line_items"]) for p in scored
    )
    if gross == 0:
        rate = 0
    else:
        rate = rhu(Decimal(refunded) * Decimal(10000) / Decimal(gross))
    return ok(
        {
            "app_id": app["id"],
            "gross_cents": gross,
            "tax_cents": tax,
            "revenue_base_cents": base,
            "developer_net_cents": net,
            "refunded_gross_cents": refunded,
            "unit_count": units,
            "refund_rate_bps": rate,
        }
    )


@bp.get("/api/apps/<app_id>/review-submissions")
def app_review_submissions(app_id):
    authenticate({"Developer", "ReviewAgent", "PolicyOfficer", "PlatformAdmin"})
    app = lookup("apps", app_id)
    require_owner(app["developer_id"])
    limit, offset = pagination()
    rows = [r for r in ordered(db.review_submissions) if r["app_id"] == app["id"]]
    items, total = paginate(rows, limit, offset)
    return ok_list(items, limit, offset, total)


@bp.get("/api/apps/<app_id>/pricing-plans")
def app_pricing_plans(app_id):
    authenticate({"Developer", "ReviewAgent", "PlatformAdmin", "FinanceOps", "StorefrontService"})
    app = lookup("apps", app_id)
    require_owner(app["developer_id"])
    limit, offset = pagination()
    rows = [p for p in ordered(db.pricing_plans) if p["app_id"] == app["id"]]
    rows = filter_eq(rows, "kind")
    rows = filter_eq(rows, "status")
    items, total = paginate(rows, limit, offset)
    return ok_list(items, limit, offset, total)


@bp.post("/api/apps/<app_id>/pricing-plans")
def create_pricing_plan(app_id):
    authenticate({"Developer"})
    app = lookup("apps", app_id)
    require_owner(app["developer_id"])
    body = get_body()
    kind = req_enum(body, "kind", PLAN_KINDS)
    price_cents = req_int(body, "price_cents", minimum=1)
    currency = req_str(body, "currency")
    country_code = req_str(body, "country_code")
    effective_from = req_dt(body, "effective_from")
    effective_to = req_dt(body, "effective_to")
    expected_app_version = req_int(body, "expected_app_version")
    billing_period_months = opt_int(body, "billing_period_months", 0, minimum=0)

    if expected_app_version != app["version"]:
        fail("ERR_STALE_APP_VERSION", "expected_app_version is stale.")

    if jurisdiction_for(country_code) is None:
        fail("ERR_JURISDICTION_NOT_CONFIGURED", "No jurisdiction registered for %s." % country_code)

    if effective_from > effective_to:
        fail("ERR_PRICING_WINDOW_CONFLICT", "effective_from must not be after effective_to.")
    from datetime import timedelta

    cooldown = timedelta(hours=PRICING_COOLDOWN_HOURS)
    for plan in ordered(db.pricing_plans):
        if plan["app_id"] != app["id"] or plan["kind"] != kind:
            continue
        if plan["status"] == "RETIRED":
            continue
        existing_to = plan["_effective_to"]
        if effective_from < existing_to + cooldown:
            fail(
                "ERR_PRICING_WINDOW_CONFLICT",
                "New plan must start at least %d hours after the prior window."
                % PRICING_COOLDOWN_HOURS,
            )

    if kind == "SUBSCRIPTION":
        if billing_period_months < 1:
            fail("ERR_INVALID_PRICING", "SUBSCRIPTION plans require billing_period_months >= 1.")
    else:
        if billing_period_months != 0:
            fail("ERR_INVALID_PRICING", "billing_period_months must be 0 for %s plans." % kind)

    from core import iso

    rec = new_record(
        app_id=app["id"],
        kind=kind,
        price_cents=price_cents,
        currency=currency,
        country_code=country_code,
        billing_period_months=billing_period_months,
        effective_from=iso(effective_from),
        effective_to=iso(effective_to),
        status="ACTIVE",
    )
    rec["_effective_from"] = effective_from
    rec["_effective_to"] = effective_to
    db.pricing_plans[rec["id"]] = rec
    touch(app)
    return ok(public(rec), 201)
