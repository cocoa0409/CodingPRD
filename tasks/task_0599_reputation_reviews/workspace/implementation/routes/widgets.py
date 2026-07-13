"""The website review widget."""

import uuid

from flask import Blueprint

import store
import validation as v
from auth import endpoint, resolve_location, resolve_widget
from envelope import created, ok, paginate
from errors import err
from services import assert_not_frozen, assert_open, touch

bp = Blueprint("widgets", __name__)


@bp.post("/reputation/locations/<location_id>/widget")
@endpoint(["PlatformAdmin", "BusinessOwner", "LocationManager"])
def create_widget(location_id):
    loc = resolve_location(location_id)
    data = v.body()
    min_rating = v.opt_int(data, "min_rating", 4, minimum=1, maximum=5)
    max_reviews = v.opt_int(data, "max_reviews", 10, minimum=1, maximum=50)

    assert_not_frozen(loc)

    for w in store.widgets.values():
        if w["location_id"] == location_id:
            raise err("ERR_WIDGET_ALREADY_EXISTS")

    rec = store.base_record()
    rec.update({
        "location_id": location_id,
        "min_rating": min_rating,
        "max_reviews": max_reviews,
        "status": "DRAFT",
        "embed_token": uuid.uuid4().hex,
        "published_at": None,
    })
    store.widgets[rec["id"]] = rec
    return created(store.widget_out(rec))


@bp.get("/reputation/locations/<location_id>/widget")
@endpoint(["PlatformAdmin", "BusinessOwner", "LocationManager"])
def get_widget(location_id):
    resolve_location(location_id)
    rows = [w for w in store.widgets.values() if w["location_id"] == location_id]
    return paginate(store.by_created(rows), store.widget_out)


@bp.post("/reputation/widgets/<widget_id>/publish")
@endpoint(["PlatformAdmin", "BusinessOwner", "LocationManager"])
def publish_widget(widget_id):
    widget, loc = resolve_widget(widget_id)
    # priority 8 (FROZEN) then priority 9 (RESTRICTED)
    assert_open(loc)
    if widget["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE")

    widget["status"] = "PUBLISHED"
    widget["published_at"] = store.now()
    touch(widget)
    return ok(store.widget_out(widget))
