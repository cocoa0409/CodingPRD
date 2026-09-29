"""Catalog eligibility, product assignments and the out-of-stock chain
(PRD 3.5)."""
from flask import Blueprint

from core import F, db, fail, insert, new_row, now, ok, rows, touch
import derive as D
import helpers as H
from guard import guard

bp = Blueprint("catalog", __name__)

PRODUCT_WRITE = ("NetworkAdmin", "CatalogOps")
PRODUCT_READ = ("NetworkAdmin", "CatalogOps", "AccountManager",
                "AuctionService", "AdvertiserUser")
ASSIGNMENT_WRITE = ("NetworkAdmin", "AccountManager", "CatalogOps",
                    "AdvertiserUser")
ASSIGNMENT_READ = ("NetworkAdmin", "AccountManager", "CatalogOps",
                   "AuctionService", "AdvertiserUser")
RESTRICTED_REASONS = ("AGE_RESTRICTED", "REGULATORY", "BRAND_SAFETY")

PRODUCT_FILTERS = (
    ("category_code", "category_code", "string"),
    ("eligibility_status", "eligibility_status", "string"),
    ("sku", "sku", "string"),
)
ASSIGNMENT_FILTERS = (
    ("line_item_id", "line_item_id", "string"),
    ("catalog_product_id", "catalog_product_id", "string"),
    ("assignment_status", "assignment_status", "string"),
    ("is_hero", "is_hero", "bool"),
)


# ---------------------------------------------------------------------------
# Shared cascade machinery
# ---------------------------------------------------------------------------
def _line_items_of(assignments):
    seen = []
    out = []
    for a in assignments:
        li = db.line_items.get(a["line_item_id"])
        if li is not None and li["id"] not in seen:
            seen.append(li["id"])
            out.append(li)
    return out


def _rollup_campaigns(line_items):
    """Level three: a DELIVERING campaign whose every non-ended line item is
    paused rolls up to PAUSED."""
    seen = []
    for li in line_items:
        camp = D.campaign_of_line_item(li)
        if camp is None or camp["id"] in seen:
            continue
        seen.append(camp["id"])
        if camp["delivery_status"] != "DELIVERING":
            continue
        live = [l for l in D.line_items_of_campaign(camp["id"])
                if l["line_item_status"] not in ("ENDED", "REJECTED")]
        if live and all(l["line_item_status"] in ("OOS_PAUSED", "MANUAL_PAUSED")
                        for l in live):
            camp["delivery_status"] = "PAUSED"
            touch(camp)


def _pause_line_items(line_items, reason):
    """Level two: a line item whose eligible product count reaches zero pauses."""
    touched = []
    for li in line_items:
        if D.eligible_product_count(li) >= 1:
            continue
        if reason == "OUT_OF_STOCK" and li["line_item_status"] != "SERVING":
            continue
        if reason == "CATALOG_RESTRICTED" and \
                li["line_item_status"] not in ("SERVING", "ELIGIBLE"):
            continue
        li["line_item_status"] = "OOS_PAUSED"
        li["pause_reason"] = reason
        li["last_pause_at"] = now()
        touch(li)
        touched.append(li)
    _rollup_campaigns(touched)
    return touched


def _touch_line_items(line_items):
    for li in line_items:
        touch(li)


def out_of_stock_chain(product):
    """Depth-three pausing chain of PRD 3.5."""
    affected = []
    for a in D.assignments_of_product(product["id"]):
        if a["assignment_status"] == "ACTIVE":
            a["assignment_status"] = "PAUSED_OOS"
            a["relevance_contribution"] = 0.0
            touch(a)
            affected.append(a)
    line_items = _line_items_of(affected)
    for li in line_items:
        D.recompute_relevance_contributions(li["id"])
    paused = _pause_line_items(line_items, "OUT_OF_STOCK")
    for li in line_items:
        if li not in paused:
            touch(li)


def back_in_stock_chain(product):
    """The compensating action of PRD 3.5."""
    affected = []
    for a in D.assignments_of_product(product["id"]):
        if a["assignment_status"] == "PAUSED_OOS":
            a["assignment_status"] = "ACTIVE"
            touch(a)
            affected.append(a)
    line_items = _line_items_of(affected)
    for li in line_items:
        D.recompute_relevance_contributions(li["id"])
        if li["line_item_status"] == "OOS_PAUSED" and \
                D.eligible_product_count(li) >= 1:
            camp = D.campaign_of_line_item(li)
            if camp is not None and camp["delivery_status"] == "DELIVERING":
                li["line_item_status"] = "SERVING"
            else:
                li["line_item_status"] = "ELIGIBLE"
            li["pause_reason"] = "NONE"
            li["priority_tier"] = D.priority_tier(li)
        touch(li)


# ---------------------------------------------------------------------------
# Catalog products
# ---------------------------------------------------------------------------
@bp.post("/rmn/catalog-products")
def create_product():
    specs = (
        F("sku", "string", required=True),
        F("category_code", "string", required=True),
        F("title", "string", required=True),
        F("price_cents", "integer", required=True, minimum=1),
        F("in_stock_units", "integer", minimum=0, default=0, has_default=True),
        F("margin_pct", "number", minimum=0.0, maximum=0.9, default=0.2,
          has_default=True),
        F("min_stock_units_for_serving", "integer", minimum=0, default=3,
          has_default=True),
    )
    ctx = guard(PRODUCT_WRITE, body_specs=specs)
    data = ctx.data
    if any(p["sku"] == data["sku"] for p in db.catalog_products.values()):
        fail("ERR_DUPLICATE_RESOURCE_CODE", "sku is already in use.")
    status = ("ELIGIBLE"
              if data["in_stock_units"] >= data["min_stock_units_for_serving"]
              else "OUT_OF_STOCK")
    row = new_row()
    row.update({
        "sku": data["sku"],
        "category_code": data["category_code"],
        "title": data["title"],
        "price_cents": data["price_cents"],
        "in_stock_units": data["in_stock_units"],
        "min_stock_units_for_serving": data["min_stock_units_for_serving"],
        "eligibility_status": status,
        "restricted_reason": "NONE",
        "margin_pct": data["margin_pct"],
        "last_stock_change_at": None,
    })
    insert("catalog_product", row)
    return ok(D.ser_catalog_product(row), 201)


@bp.get("/rmn/catalog-products")
def list_products():
    ctx = guard(PRODUCT_READ, paginated=True)
    return H.respond_list(ctx, "catalog_product", rows("catalog_product"),
                          PRODUCT_FILTERS)


@bp.get("/rmn/catalog-products/<pid>")
def read_product(pid):
    ctx = guard(PRODUCT_READ, path_refs=(("catalog_product", pid),))
    return ok(D.ser_catalog_product(ctx.get("catalog_product")))


@bp.post("/rmn/catalog-products/<pid>/stock-adjustments")
def stock_adjustment(pid):
    specs = (
        F("delta_units", "integer", required=True),
        F("adjustment_reference", "string"),
    )
    ctx = guard(PRODUCT_WRITE, path_refs=(("catalog_product", pid),),
                body_specs=specs)
    product = ctx.get("catalog_product")
    if product["eligibility_status"] == "DELISTED":
        fail("ERR_PRODUCT_DELISTED", "The product is DELISTED.")
    before = product["eligibility_status"]
    units = product["in_stock_units"] + ctx.data["delta_units"]
    if units < 0:
        units = 0
    product["in_stock_units"] = units
    product["last_stock_change_at"] = now()
    threshold = product["min_stock_units_for_serving"]
    touch(product)
    if units < threshold and before == "ELIGIBLE":
        product["eligibility_status"] = "OUT_OF_STOCK"
        out_of_stock_chain(product)
    elif units >= threshold and before == "OUT_OF_STOCK":
        product["eligibility_status"] = "ELIGIBLE"
        back_in_stock_chain(product)
    return ok(D.ser_catalog_product(product))


@bp.post("/rmn/catalog-products/<pid>/restrict")
def restrict_product(pid):
    specs = (
        F("restricted_reason", "enum", required=True, enum=RESTRICTED_REASONS),
        F("restriction_note", "string"),
    )
    ctx = guard(PRODUCT_WRITE, path_refs=(("catalog_product", pid),),
                body_specs=specs)
    product = ctx.get("catalog_product")
    if product["eligibility_status"] == "DELISTED":
        fail("ERR_PRODUCT_DELISTED", "The product is DELISTED.")
    if product["eligibility_status"] not in ("ELIGIBLE", "OUT_OF_STOCK"):
        fail("ERR_PRODUCT_RESTRICTED",
             "A product in %s may not be restricted."
             % product["eligibility_status"])
    product["eligibility_status"] = "RESTRICTED"
    product["restricted_reason"] = ctx.data["restricted_reason"]
    touch(product)
    affected = []
    for a in D.assignments_of_product(product["id"]):
        if a["assignment_status"] in ("ACTIVE", "PAUSED_OOS"):
            if a["assignment_status"] == "ACTIVE":
                a["relevance_contribution"] = 0.0
            a["assignment_status"] = "PAUSED_RESTRICTED"
            touch(a)
            affected.append(a)
    line_items = _line_items_of(affected)
    for li in line_items:
        D.recompute_relevance_contributions(li["id"])
    paused = _pause_line_items(line_items, "CATALOG_RESTRICTED")
    for li in line_items:
        if li not in paused:
            touch(li)
    return ok(D.ser_catalog_product(product))


@bp.post("/rmn/catalog-products/<pid>/reinstate")
def reinstate_product(pid):
    specs = (F("reinstatement_note", "string"),)
    ctx = guard(PRODUCT_WRITE, path_refs=(("catalog_product", pid),),
                body_specs=specs)
    product = ctx.get("catalog_product")
    if product["eligibility_status"] == "DELISTED":
        fail("ERR_PRODUCT_DELISTED", "The product is DELISTED.")
    if product["eligibility_status"] != "RESTRICTED":
        fail("ERR_PRODUCT_RESTRICTED",
             "Only a RESTRICTED product may be reinstated; this one is %s."
             % product["eligibility_status"])
    product["restricted_reason"] = "NONE"
    in_stock = product["in_stock_units"] >= product["min_stock_units_for_serving"]
    product["eligibility_status"] = "ELIGIBLE" if in_stock else "OUT_OF_STOCK"
    touch(product)
    affected = []
    for a in D.assignments_of_product(product["id"]):
        if a["assignment_status"] == "PAUSED_RESTRICTED":
            a["assignment_status"] = "ACTIVE" if in_stock else "PAUSED_OOS"
            touch(a)
            affected.append(a)
    line_items = _line_items_of(affected)
    for li in line_items:
        D.recompute_relevance_contributions(li["id"])
        if in_stock and li["line_item_status"] == "OOS_PAUSED" and \
                li["pause_reason"] == "CATALOG_RESTRICTED" and \
                D.eligible_product_count(li) >= 1:
            li["line_item_status"] = "ELIGIBLE"
            li["pause_reason"] = "NONE"
            li["priority_tier"] = D.priority_tier(li)
        touch(li)
    return ok(D.ser_catalog_product(product))


@bp.post("/rmn/catalog-products/<pid>/delist")
def delist_product(pid):
    specs = (F("delist_reason", "string", required=True),)
    ctx = guard(PRODUCT_WRITE, path_refs=(("catalog_product", pid),),
                body_specs=specs)
    product = ctx.get("catalog_product")
    if product["eligibility_status"] == "DELISTED":
        fail("ERR_PRODUCT_DELISTED", "The product is already DELISTED.")
    if product["eligibility_status"] not in ("RESTRICTED", "OUT_OF_STOCK"):
        fail("ERR_PRODUCT_RESTRICTED",
             "A product in %s may not be delisted."
             % product["eligibility_status"])
    if product["eligibility_status"] == "OUT_OF_STOCK" and \
            product["in_stock_units"] != 0:
        fail("ERR_PRODUCT_RESTRICTED",
             "An out-of-stock product may only be delisted at zero units.")
    product["eligibility_status"] = "DELISTED"
    touch(product)
    affected = []
    for a in D.assignments_of_product(product["id"]):
        if a["assignment_status"] != "REMOVED":
            a["assignment_status"] = "REMOVED"
            a["removed_at"] = now()
            a["relevance_contribution"] = 0.0
            touch(a)
            affected.append(a)
    line_items = _line_items_of(affected)
    ended = []
    for li in line_items:
        D.recompute_relevance_contributions(li["id"])
        if D.eligible_product_count(li) < 1 and li["line_item_status"] in \
                ("SERVING", "ELIGIBLE", "OOS_PAUSED"):
            li["line_item_status"] = "ENDED"
            li["reserved_cents"] = 0
            ended.append(li)
            slot = D.slot_of_line_item(li)
            if slot is not None:
                touch(slot)
        touch(li)
    _rollup_campaigns([l for l in line_items if l not in ended])
    return ok(D.ser_catalog_product(product))


# ---------------------------------------------------------------------------
# Product assignments
# ---------------------------------------------------------------------------
@bp.post("/rmn/product-assignments")
def create_assignment():
    specs = (
        F("line_item_id", "string", required=True),
        F("catalog_product_id", "string", required=True),
        F("is_hero", "boolean", default=False, has_default=True),
        F("expected_line_item_version", "integer", required=True),
    )
    ctx = guard(ASSIGNMENT_WRITE, body_specs=specs,
                body_refs=(("line_item", "line_item_id"),
                           ("catalog_product", "catalog_product_id")),
                occ=("expected_line_item_version", "line_item",
                     "ERR_STALE_LINE_ITEM_VERSION"),
                mutating=True)
    li = ctx.get("line_item")
    product = ctx.get("catalog_product")
    if product["eligibility_status"] == "DELISTED":
        fail("ERR_PRODUCT_DELISTED", "The product is DELISTED.")
    if product["eligibility_status"] != "ELIGIBLE":
        fail("ERR_PRODUCT_RESTRICTED",
             "The product is %s." % product["eligibility_status"])
    row = new_row(versioned=True)
    row.update({
        "line_item_id": li["id"],
        "catalog_product_id": product["id"],
        "assignment_status": "ACTIVE",
        "is_hero": ctx.data["is_hero"],
        "relevance_contribution": 0.0,
        "removed_at": None,
    })
    insert("product_assignment", row)
    D.recompute_relevance_contributions(li["id"])
    li["relevance_score"] = li["relevance_score"]
    touch(li)
    return ok(D.ser_product_assignment(row), 201)


@bp.get("/rmn/product-assignments")
def list_assignments():
    ctx = guard(ASSIGNMENT_READ, paginated=True)
    return H.respond_list(ctx, "product_assignment", rows("product_assignment"),
                          ASSIGNMENT_FILTERS, owner_kind="product_assignment")


@bp.get("/rmn/product-assignments/<aid>")
def read_assignment(aid):
    ctx = guard(ASSIGNMENT_READ, path_refs=(("product_assignment", aid),))
    return ok(D.ser_product_assignment(ctx.get("product_assignment")))


@bp.delete("/rmn/product-assignments/<aid>")
def remove_assignment(aid):
    ctx = guard(ASSIGNMENT_WRITE, path_refs=(("product_assignment", aid),),
                mutating=True)
    assignment = ctx.get("product_assignment")
    li = db.line_items.get(assignment["line_item_id"])
    if assignment["assignment_status"] == "REMOVED":
        fail("ERR_PRODUCT_ASSIGNMENT_NOT_FOUND",
             "The assignment is already REMOVED.")
    if li is not None and li["line_item_status"] == "ENDED":
        fail("ERR_LINE_ITEM_INVALID_STATE", "The line item is ENDED.")
    if li is not None and li["line_item_status"] != "DRAFT":
        heroes = [a for a in D.assignments_of_line_item(li["id"])
                  if a["assignment_status"] == "ACTIVE" and a["is_hero"]
                  and a["id"] != assignment["id"]]
        if assignment["is_hero"] and assignment["assignment_status"] == "ACTIVE" \
                and not heroes:
            fail("ERR_HERO_ASSIGNMENT_REQUIRED",
                 "The last active hero assignment may not be removed.")
    assignment["assignment_status"] = "REMOVED"
    assignment["removed_at"] = now()
    assignment["relevance_contribution"] = 0.0
    touch(assignment)
    if li is not None:
        D.recompute_relevance_contributions(li["id"])
        touch(li)
    return ok({}, 204)
