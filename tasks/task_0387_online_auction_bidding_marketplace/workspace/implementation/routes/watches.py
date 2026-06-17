"""Watch endpoints. PRD §2.4 (soft-deletable toggle), §2.6 (reverse lookups)."""
from flask import Blueprint, request

import db
import errors
import response
import middleware as mw
from services import core
from routes.helpers import get_json_body, paginate_list

bp = Blueprint("watches", __name__)


@bp.route("/listings/<listing_id>/watch", methods=["POST"])
def watch_listing(listing_id):
    caller = mw.require_auth()                          # priority 1
    mw.require_role(caller, {"Buyer", "Seller"})        # priority 2
    body = get_json_body()
    listing = db.listings.get(listing_id)               # existence (priority 4)
    if listing is None:
        raise errors.not_found("Listing not found.")

    watcher_account_id = body.get("watcher_account_id")
    if not isinstance(watcher_account_id, str) or watcher_account_id == "":
        raise errors.invalid_request("watcher_account_id is required.")
    # Ownership (priority 3): the watcher must be the acting account.
    if watcher_account_id != caller.user_id:
        raise errors.not_owner("watcher_account_id must be the acting account.")
    watcher = db.accounts.get(watcher_account_id)
    if watcher is None:
        raise errors.not_found("Watcher account not found.")
    mw.check_account_not_closed(caller)

    # At most one active watch for (listing_id, watcher_account_id). Watching a
    # listing with an inactive watch for that pair reactivates it (PRD §2.4).
    existing = None
    for w in db.watches.values():
        if w["listing_id"] == listing_id and w["watcher_account_id"] == watcher_account_id:
            existing = w
            break
    if existing is not None:
        existing["active"] = True
        # Watch carries only id + created_at; no version/updated_at to bump.
        return response.success(core.ser_watch(existing), status=201)

    wid = db.new_id()
    watch = {
        "id": wid,
        "listing_id": listing_id,
        "watcher_account_id": watcher_account_id,
        "active": True,
    }
    core.stamp_new(watch, with_version=False)
    db.watches[wid] = watch
    return response.success(core.ser_watch(watch), status=201)


@bp.route("/watches/<watch_id>", methods=["GET"])
def get_watch(watch_id):
    caller = mw.require_auth()
    mw.require_role(caller, {"Buyer", "Seller", "PlatformAdmin"})
    watch = db.watches.get(watch_id)
    if watch is None:
        raise errors.not_found("Watch not found.")
    return response.success(core.ser_watch(watch), status=200)


@bp.route("/watches/<watch_id>", methods=["DELETE"])
def unwatch(watch_id):
    caller = mw.require_auth()                          # priority 1
    mw.require_role(caller, {"Buyer", "Seller"})        # priority 2
    watch = db.watches.get(watch_id)                    # existence (priority 4)
    if watch is None:
        raise errors.not_found("Watch not found.")
    # Ownership (priority 3): only the watcher may unwatch.
    if watch["watcher_account_id"] != caller.user_id:
        raise errors.not_owner("Only the watcher may unwatch this listing.")
    mw.check_account_not_closed(caller)

    watch["active"] = False   # soft delete (PRD §2.4)
    return response.success(core.ser_watch(watch), status=200)


@bp.route("/watches", methods=["GET"])
def list_watches():
    caller = mw.require_auth()
    mw.require_role(caller, {"Buyer", "Seller", "PlatformAdmin"})
    listing_id = request.args.get("listing_id")
    watcher_account_id = request.args.get("watcher_account_id")
    include_inactive = request.args.get("include_inactive")
    inactive_flag = str(include_inactive).lower() in ("1", "true", "yes") if include_inactive is not None else False

    items = list(db.watches.values())
    if listing_id is not None:
        items = [w for w in items if w["listing_id"] == listing_id]
    if watcher_account_id is not None:
        items = [w for w in items if w["watcher_account_id"] == watcher_account_id]
    # Active-only by default (PRD §2.6).
    if not inactive_flag:
        items = [w for w in items if w["active"]]
    return paginate_list(items, core.ser_watch)
