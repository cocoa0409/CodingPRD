"""Cross-cutting business logic: rating recompute, cascades, existence checks."""
from db import store, touch
from calculations import compute_shop_rating, compute_material_status


def find_shop(shop_id):
    return store.shops.get(shop_id)


def find_variation(listing, variation_id):
    """Return (variation_obj) or None. variation_id may be None."""
    if variation_id is None:
        return None
    for v in listing.get("variations", []):
        if v.get("key") == variation_id:
            return v
    return None


def recompute_shop_rating(shop):
    """Recompute simple + weighted rating from PUBLISHED reviews of this shop.
    Mutates shop (bumps updated_at + version) since scaffold marks these as
    computed fields on the Shop entity."""
    pub = [r for r in store.reviews.values()
           if r["shop_id"] == shop["id"] and r["status"] == "PUBLISHED"]
    n, simple, weighted = compute_shop_rating(pub)
    shop["published_review_count"] = n
    shop["simple_avg_rating"] = simple
    shop["weighted_shop_rating"] = weighted
    touch(shop)


def update_material_status(material):
    material["status"] = compute_material_status(
        material["stock_qty"], material["reorder_threshold"]
    )


def cascade_material_freed(material):
    """After a material's stock rises above OUT_OF_STOCK, return any MADE_TO_ORDER
    listing that was SOLD_OUT solely due to this material back to ACTIVE."""
    if material["status"] == "OUT_OF_STOCK":
        return
    for lst in store.listings.values():
        if (lst.get("primary_material_id") == material["id"]
                and lst["fulfillment_type"] == "MADE_TO_ORDER"
                and lst["status"] == "SOLD_OUT"):
            lst["status"] = "ACTIVE"
            touch(lst)


def cascade_shop_suspended(shop):
    """Suspend/close cascade: listings in {ACTIVE, SOLD_OUT} -> INACTIVE."""
    for lst in store.listings.values():
        if lst["shop_id"] == shop["id"] and lst["status"] in ("ACTIVE", "SOLD_OUT"):
            lst["status"] = "INACTIVE"
            touch(lst)


def pay_cascade_check_sold_out(listing, variation):
    """After the pay decrement, check whether the listing should become SOLD_OUT."""
    if listing["status"] != "ACTIVE":
        return
    if listing["fulfillment_type"] == "READY_TO_SHIP":
        if listing["quantity"] == 0:
            listing["status"] = "SOLD_OUT"
            touch(listing)
    else:  # MADE_TO_ORDER
        mid = listing.get("primary_material_id")
        if mid:
            m = store.materials.get(mid)
            if m and m["status"] == "OUT_OF_STOCK":
                listing["status"] = "SOLD_OUT"
                touch(listing)


def cancel_cascade_restore_listing(listing):
    """After cancel-restore, if listing is SOLD_OUT but now sellable, return ACTIVE."""
    if listing["status"] != "SOLD_OUT":
        return
    if listing["fulfillment_type"] == "READY_TO_SHIP":
        if listing["quantity"] >= 1:
            listing["status"] = "ACTIVE"
            touch(listing)
    else:  # MADE_TO_ORDER
        mid = listing.get("primary_material_id")
        if mid:
            m = store.materials.get(mid)
            if m and m["status"] != "OUT_OF_STOCK":
                listing["status"] = "ACTIVE"
                touch(listing)
        else:
            # No material tracking: unbounded, revive.
            listing["status"] = "ACTIVE"
            touch(listing)


def production_windows_overlap_count(shop_id, paid_at, ship_by):
    """Count the shop's existing orders (currently in a production window) whose
    [paid_at, ship_by_date] (closed interval) overlaps this window."""
    count = 0
    for o in store.orders.values():
        if o["shop_id"] != shop_id:
            continue
        # Only orders that HAVE a production window: MADE_TO_ORDER, paid, not yet done.
        if o.get("paid_at") is None or o.get("ship_by_date") is None:
            continue
        # Only count still-active production: fulfillment_status IN_PRODUCTION.
        # PRD: "counting the shop's orders whose production window ... would overlap".
        # Cancelled/shipped orders have released their production slot.
        if o["fulfillment_status"] not in ("IN_PRODUCTION",):
            continue
        # Closed intervals overlap iff a.start <= b.end AND b.start <= a.end.
        if o["paid_at"] <= ship_by and paid_at <= o["ship_by_date"]:
            count += 1
    return count
