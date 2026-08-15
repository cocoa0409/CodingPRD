"""Reference-data and admin routes: logical clock, products, channels,
taxonomy categories, response templates, trend snapshots."""
from flask import Blueprint, request

import services as svc
from db import store
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE_TRANSITION,
    ERR_NOT_FOUND,
    ERR_SNAPSHOT_WINDOW_OVERLAP,
    ERR_TEMPLATE_IN_USE,
)
from middleware import (
    ALL_ROLES,
    get_body,
    opt_bool,
    opt_str,
    pagination_params,
    req_datetime,
    req_str,
    require_roles,
)
from response import ok, ok_list

bp = Blueprint("admin", __name__)

MANAGER = ("ComplaintManager",)
SNAPSHOT_READERS = ("ComplaintManager", "CaseHandler", "ExecutiveReviewer", "Auditor")
SNAPSHOT_WRITERS = ("ComplaintManager", "ExecutiveReviewer")
TEMPLATE_READERS = ("ComplaintManager", "CaseHandler", "QAReviewer", "ExecutiveReviewer", "Auditor")


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

@bp.post("/_clock/set_current_utc")
@require_roles(*MANAGER)
def set_clock():
    body = get_body()
    to = req_datetime(body, "to_iso8601")
    store.set_clock(to)
    # Setting the clock shifts the trailing-90-day window: recompute all postures.
    for product in store.products.values():
        svc.recompute_posture(product)
    return ok({"current_utc": svc.iso(store.now())}, 200)


# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------

@bp.post("/products")
@require_roles(*MANAGER)
def create_product():
    body = get_body()
    product_code = req_str(body, "product_code")
    display_name = req_str(body, "display_name")
    if product_code in store.product_by_code:
        raise ApiError(ERR_INVALID_REQUEST, f"Product code '{product_code}' already exists.", 400)
    p = svc.fresh_rec(
        product_code=product_code,
        display_name=display_name,
        posture="OPEN",
        open_complaint_count=0,
        substantiated_count_90d=0,
        early_warning_active=False,
    )
    store.products[p.id] = p
    store.product_by_code[p.product_code] = p
    return ok(svc.ser_product(p), 201)


@bp.get("/products/<productId>")
@require_roles(*ALL_ROLES)
def get_product(productId):
    return ok(svc.ser_product(svc.get_product(productId)), 200)


@bp.get("/products")
@require_roles(*ALL_ROLES)
def list_products():
    limit, offset = pagination_params()
    recs = list(store.products.values())
    posture = request.args.get("posture")
    if posture is not None:
        recs = [p for p in recs if p.posture == posture]
    items, total = svc.paged(recs, svc.ser_product, limit, offset)
    return ok_list(items, total, limit, offset)


@bp.post("/products/<productId>/unfreeze")
@require_roles(*MANAGER)
def unfreeze_product(productId):
    p = svc.get_product(productId)
    if p.posture != "FROZEN":
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            f"Product posture is {p.posture}; manual unfreeze requires FROZEN.",
            409,
        )
    p.posture = "WATCH"
    svc.touch(p)
    return ok(svc.ser_product(p), 200)


@bp.get("/products/<pid>/complaints")
@require_roles(*ALL_ROLES)
def list_product_complaints(pid):
    p = svc.get_product(pid)
    limit, offset = pagination_params()
    recs = [c for c in store.complaints.values() if c.product_code == p.product_code]
    status = request.args.get("status")
    if status is not None:
        recs = [c for c in recs if c.status == status]
    items, total = svc.paged(recs, svc.ser_complaint, limit, offset)
    return ok_list(items, total, limit, offset)


# ---------------------------------------------------------------------------
# Trend snapshots
# ---------------------------------------------------------------------------

@bp.get("/products/<pid>/trend-snapshots")
@require_roles(*SNAPSHOT_READERS)
def list_snapshots(pid):
    p = svc.get_product(pid)
    limit, offset = pagination_params()
    recs = [s for s in store.snapshots.values() if s.product_code == p.product_code]
    items, total = svc.paged(recs, svc.ser_snapshot, limit, offset)
    return ok_list(items, total, limit, offset)


@bp.post("/products/<pid>/trend-snapshots")
@require_roles(*SNAPSHOT_WRITERS)
def create_snapshot(pid):
    p = svc.get_product(pid)
    body = get_body()
    start = req_datetime(body, "period_start_at")
    end = req_datetime(body, "period_end_at")
    if end < start:
        raise ApiError(
            ERR_INVALID_REQUEST,
            "period_end_at must be at or after period_start_at.",
            400,
        )
    # Closed-interval overlap: shared boundary counts as overlap.
    for ex in store.snapshots.values():
        if ex.product_code != p.product_code:
            continue
        if start <= ex.period_end_at and ex.period_start_at <= end:
            raise ApiError(
                ERR_SNAPSHOT_WINDOW_OVERLAP,
                "TrendSnapshot window overlaps an existing snapshot of this product under closed-interval semantics.",
                409,
            )
    # early_warning_threshold calculation with pinned evaluation order.
    windowed = [
        c for c in store.complaints.values()
        if c.product_code == p.product_code and start <= c.received_at <= end
    ]
    complaint_count = len(windowed)
    substantiated_count = 0
    for c in windowed:
        r = svc.latest_rca(c.id)
        if r is not None and r.status == "COMPLETED" and r.verdict == "SUBSTANTIATED":
            substantiated_count += 1
    if complaint_count == 0:
        rate_bps = 0
    else:
        rate_bps = (substantiated_count * 10000) // complaint_count
    open_now = sum(1 for c in store.complaints.values()
                   if c.product_code == p.product_code and c.status in svc.OPEN_STATUSES)
    early_warning = (
        complaint_count >= svc.EW_MIN_COUNT
        and (rate_bps >= svc.EW_RATE_BPS or open_now >= svc.EW_OPEN_COUNT)
    )
    snap = svc.fresh_audit_rec(
        product_code=p.product_code,
        period_start_at=start,
        period_end_at=end,
        complaint_count=complaint_count,
        substantiated_count=substantiated_count,
        substantiation_rate_bps=rate_bps,
        early_warning=early_warning,
        evaluated_at=store.now(),
    )
    store.snapshots[snap.id] = snap
    # Persisting a snapshot updates early_warning_active and recomputes posture.
    p.early_warning_active = early_warning
    svc.recompute_posture(p)
    return ok(svc.ser_snapshot(snap), 201)


# ---------------------------------------------------------------------------
# Channels
# ---------------------------------------------------------------------------

@bp.post("/channels")
@require_roles(*MANAGER)
def create_channel():
    body = get_body()
    channel_code = req_str(body, "channel_code")
    display_name = req_str(body, "display_name")
    is_portal = opt_bool(body, "is_regulator_portal", False)
    if channel_code in store.channel_by_code:
        raise ApiError(ERR_INVALID_REQUEST, f"Channel code '{channel_code}' already exists.", 400)
    c = svc.fresh_rec(
        channel_code=channel_code,
        display_name=display_name,
        is_regulator_portal=is_portal,
    )
    store.channels[c.id] = c
    store.channel_by_code[c.channel_code] = c
    return ok(svc.ser_channel(c), 201)


@bp.get("/channels/<channelId>")
@require_roles(*ALL_ROLES)
def get_channel(channelId):
    return ok(svc.ser_channel(svc.get_channel(channelId)), 200)


@bp.get("/channels")
@require_roles(*ALL_ROLES)
def list_channels():
    limit, offset = pagination_params()
    items, total = svc.paged(list(store.channels.values()), svc.ser_channel, limit, offset)
    return ok_list(items, total, limit, offset)


# ---------------------------------------------------------------------------
# Taxonomy categories
# ---------------------------------------------------------------------------

@bp.post("/taxonomy-categories")
@require_roles(*MANAGER)
def create_category():
    body = get_body()
    category_code = req_str(body, "category_code")
    parent_code = opt_str(body, "parent_category_code", None)
    if category_code in store.category_by_code:
        raise ApiError(ERR_INVALID_REQUEST, f"Category code '{category_code}' already exists.", 400)
    if parent_code is not None and parent_code not in store.category_by_code:
        raise ApiError(
            ERR_NOT_FOUND,
            f"Parent category code '{parent_code}' does not resolve.",
            404,
        )
    c = svc.fresh_rec(
        category_code=category_code,
        parent_category_code=parent_code,
        retired=False,
    )
    store.categories[c.id] = c
    store.category_by_code[c.category_code] = c
    return ok(svc.ser_category(c), 201)


@bp.get("/taxonomy-categories/<categoryId>")
@require_roles(*ALL_ROLES)
def get_category(categoryId):
    return ok(svc.ser_category(svc.get_category(categoryId)), 200)


@bp.get("/taxonomy-categories")
@require_roles(*ALL_ROLES)
def list_categories():
    limit, offset = pagination_params()
    recs = list(store.categories.values())
    parent = request.args.get("parent_category_code")
    if parent is not None:
        recs = [c for c in recs if c.parent_category_code == parent]
    retired = request.args.get("retired")
    if retired is not None:
        if retired.lower() == "true":
            recs = [c for c in recs if c.retired]
        elif retired.lower() == "false":
            recs = [c for c in recs if not c.retired]
    items, total = svc.paged(recs, svc.ser_category, limit, offset)
    return ok_list(items, total, limit, offset)


@bp.post("/taxonomy-categories/<categoryId>/retire")
@require_roles(*MANAGER)
def retire_category(categoryId):
    c = svc.get_category(categoryId)
    c.retired = True
    svc.touch(c)
    return ok(svc.ser_category(c), 200)


# ---------------------------------------------------------------------------
# Response templates
# ---------------------------------------------------------------------------

@bp.post("/response-templates")
@require_roles(*MANAGER)
def create_template():
    body = get_body()
    template_key = req_str(body, "template_key")
    channel_code = req_str(body, "channel_code")
    category_code = req_str(body, "category_code")
    body_text = req_str(body, "body")
    svc.channel_by_code(channel_code)
    svc.category_by_code(category_code)
    if template_key in store.template_by_key:
        raise ApiError(ERR_INVALID_REQUEST, f"Template key '{template_key}' already exists.", 400)
    t = svc.fresh_rec(
        template_key=template_key,
        channel_code=channel_code,
        category_code=category_code,
        body=body_text,
        status="DRAFT",
    )
    store.templates[t.id] = t
    store.template_by_key[t.template_key] = t
    return ok(svc.ser_template(t), 201)


@bp.get("/response-templates/<templateId>")
@require_roles(*TEMPLATE_READERS)
def get_template(templateId):
    return ok(svc.ser_template(svc.get_template(templateId)), 200)


@bp.get("/response-templates")
@require_roles(*TEMPLATE_READERS)
def list_templates():
    limit, offset = pagination_params()
    recs = list(store.templates.values())
    channel_code = request.args.get("channel_code")
    if channel_code is not None:
        recs = [t for t in recs if t.channel_code == channel_code]
    category_code = request.args.get("category_code")
    if category_code is not None:
        recs = [t for t in recs if t.category_code == category_code]
    status = request.args.get("status")
    if status is not None:
        recs = [t for t in recs if t.status == status]
    items, total = svc.paged(recs, svc.ser_template, limit, offset)
    return ok_list(items, total, limit, offset)


@bp.post("/response-templates/<templateId>/publish")
@require_roles(*MANAGER)
def publish_template(templateId):
    t = svc.get_template(templateId)
    if t.status != "DRAFT":
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            f"Template status is {t.status}; publish requires DRAFT.",
            409,
        )
    # Supersede-on-publish: at most one ACTIVE per (channel_code, category_code).
    for other in store.templates.values():
        if (
            other.id != t.id
            and other.status == "ACTIVE"
            and other.channel_code == t.channel_code
            and other.category_code == t.category_code
        ):
            other.status = "RETIRED"
            svc.touch(other)
    t.status = "ACTIVE"
    svc.touch(t)
    return ok(svc.ser_template(t), 200)


@bp.post("/response-templates/<templateId>/retire")
@require_roles(*MANAGER)
def retire_template(templateId):
    t = svc.get_template(templateId)
    if t.status != "ACTIVE":
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            f"Template status is {t.status}; retire requires ACTIVE.",
            409,
        )
    for c in store.complaints.values():
        if c.response_template_key == t.template_key and c.status in ("RESPONSE_DRAFTED", "RESPONSE_QA"):
            raise ApiError(
                ERR_TEMPLATE_IN_USE,
                "Template is referenced by a complaint in RESPONSE_DRAFTED or RESPONSE_QA.",
                409,
            )
    t.status = "RETIRED"
    svc.touch(t)
    return ok(svc.ser_template(t), 200)
