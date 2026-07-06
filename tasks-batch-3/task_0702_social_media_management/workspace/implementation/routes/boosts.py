"""Ad-boost campaign routes (PRD §3.4)."""
from flask import Blueprint, request

import db
import response
from errors import (
    err, ERR_INVALID_STATE, ERR_INVALID_REQUEST, ERR_CLIENT_NOT_ACTIVE,
    ERR_CROSS_CLIENT_REFERENCE, ERR_CONTENT_NOT_PUBLISHED, ERR_STALE_CLIENT_VERSION,
    ERR_BOOST_BUDGET_EXCEEDED, ERR_BOOST_OVERSPEND, ERR_DAILY_CAP_EXCEEDED,
)
from middleware import (
    get_user_context, require_role, get_json_body, get_pagination,
    require_string, require_positive_int, require_min_int, require_int, optional_int,
)
from services import lookup, listing
from services.budget import recompute_client_budget
from services.serialize import boost_out
from services.ledger import append_ledger

bp = Blueprint("boosts", __name__)


@bp.post("/boost-campaigns")
def create_boost():
    _, role = get_user_context()
    require_role(role, {"FinanceController", "AccountManager"})
    body = get_json_body()
    client_id = require_string(body, "client_id")
    content_item_id = require_string(body, "content_item_id")
    with db.LOCK:
        lookup.get_client(client_id)
        lookup.get_content(content_item_id)
        requested = require_positive_int(body, "requested_budget_cents")
        daily_cap = require_positive_int(body, "daily_cap_cents")
        duration_days = require_min_int(body, "duration_days", 1)
        b = {
            "id": db.new_id(),
            "client_id": client_id,
            "content_item_id": content_item_id,
            "requested_budget_cents": requested,
            "daily_cap_cents": daily_cap,
            "duration_days": duration_days,
            "status": "DRAFT",
            "reserved_budget_cents": 0,
            "spent_budget_cents": 0,
            "days_elapsed": 0,
            "current_day_spent_cents": 0,
            # private bookkeeping: per-day spend buckets and the highest day seen
            "_buckets": {},
            "_max_day": None,
        }
        db.stamp_create(b, full=True)
        db.boost_campaigns[b["id"]] = b
        return response.created(boost_out(b))


@bp.get("/boost-campaigns")
def list_boosts():
    _, role = get_user_context()
    require_role(role, {"FinanceController", "AccountManager", "PlatformAdmin"})
    limit, offset = get_pagination()
    with db.LOCK:
        rows = listing.apply_filters(list(db.boost_campaigns.values()), {
            "client_id": request.args.get("client_id"),
            "content_item_id": request.args.get("content_item_id"),
            "status": request.args.get("status"),
        })
        rows = listing.sort_by_created(rows)
        window, total = listing.paginate(rows, limit, offset)
        return response.list_ok([boost_out(b) for b in window], limit, offset, total)


@bp.get("/boost-campaigns/<boost_id>")
def get_boost(boost_id):
    _, role = get_user_context()
    require_role(role, {"FinanceController", "AccountManager", "PlatformAdmin"})
    with db.LOCK:
        b = lookup.get_boost(boost_id)
        return response.ok(boost_out(b))


@bp.post("/boost-campaigns/<boost_id>/reserve")
def reserve_boost(boost_id):
    _, role = get_user_context()
    require_role(role, {"FinanceController"})
    body = get_json_body()
    with db.LOCK:
        b = lookup.get_boost(boost_id)
        client = lookup.get_client(b["client_id"])
        content = lookup.get_content(b["content_item_id"])
        # cross-client referential: content item and client must agree
        if content["client_id"] != b["client_id"]:
            raise err(ERR_CROSS_CLIENT_REFERENCE,
                      "Boosted content item belongs to a different client")
        # basic state-machine check
        if b["status"] != "DRAFT":
            raise err(ERR_INVALID_STATE, "Boost campaign must be DRAFT to reserve")
        # cross-entity state: client ACTIVE, content SCHEDULED or PUBLISHED
        if client["status"] != "ACTIVE":
            raise err(ERR_CLIENT_NOT_ACTIVE, "Owning client must be ACTIVE to reserve budget")
        if content["status"] not in ("SCHEDULED", "PUBLISHED"):
            raise err(ERR_INVALID_STATE,
                      "Boosted content must be SCHEDULED or PUBLISHED to reserve")
        # OCC: expected_client_version must match Client.version (priority 14,
        # before the budget ceiling per PRD §3.8)
        expected = require_int(body, "expected_client_version")
        if expected != client["version"]:
            raise err(ERR_STALE_CLIENT_VERSION,
                      "expected_client_version does not match the client's current version")
        # budget ceiling (priority 15)
        recompute_client_budget(client)
        if b["requested_budget_cents"] > client["boost_available_cents"]:
            raise err(ERR_BOOST_BUDGET_EXCEEDED,
                      "requested_budget_cents exceeds available boost budget")
        # commit
        b["status"] = "RESERVED"
        b["reserved_budget_cents"] = b["requested_budget_cents"]
        db.touch(b)
        recompute_client_budget(client)
        append_ledger(
            client_id=client["id"],
            entry_type="BOOST_RESERVE",
            amount_cents=b["requested_budget_cents"],
            boost_campaign_id=b["id"],
            cycle_index=client["current_cycle_index"],
        )
        # increment Client.version (the only operation that does so)
        db.touch(client)
        return response.ok(boost_out(b))


@bp.post("/boost-campaigns/<boost_id>/launch")
def launch_boost(boost_id):
    _, role = get_user_context()
    require_role(role, {"FinanceController"})
    with db.LOCK:
        b = lookup.get_boost(boost_id)
        if b["status"] != "RESERVED":
            raise err(ERR_INVALID_STATE, "Boost campaign must be RESERVED to launch")
        content = lookup.get_content(b["content_item_id"])
        if content["status"] != "PUBLISHED":
            raise err(ERR_CONTENT_NOT_PUBLISHED,
                      "Boosted content must be PUBLISHED to launch")
        b["status"] = "RUNNING"
        db.touch(b)
        return response.ok(boost_out(b))


@bp.post("/boost-campaigns/<boost_id>/record-spend")
def record_spend(boost_id):
    _, role = get_user_context()
    require_role(role, {"FinanceController"})
    body = get_json_body()
    with db.LOCK:
        b = lookup.get_boost(boost_id)
        if b["status"] != "RUNNING":
            raise err(ERR_INVALID_STATE, "Boost campaign must be RUNNING to record spend")
        amount = require_positive_int(body, "amount_cents")
        # spend_day_index defaults to the current day. The "current day" is the
        # highest index seen so far (or 0 if none recorded yet).
        if b["_max_day"] is None:
            default_day = 0
        else:
            default_day = b["_max_day"]
        spend_day_index = optional_int(body, "spend_day_index", default_day)
        if spend_day_index < 0:
            raise err(ERR_INVALID_REQUEST, "spend_day_index must be >= 0")
        # monotonic non-decreasing
        if b["_max_day"] is not None and spend_day_index < b["_max_day"]:
            raise err(ERR_DAILY_CAP_EXCEEDED,
                      "spend_day_index must be monotonic non-decreasing")
        # daily-cap aggregate window: bucket_total = prior in bucket + amount
        bucket_prior = b["_buckets"].get(spend_day_index, 0)
        if bucket_prior + amount > b["daily_cap_cents"]:
            raise err(ERR_DAILY_CAP_EXCEEDED,
                      "Daily cap exceeded for this spend day")
        # reservation ceiling (independent of the daily window)
        if b["spent_budget_cents"] + amount > b["reserved_budget_cents"]:
            raise err(ERR_BOOST_OVERSPEND,
                      "Spend would exceed the reserved budget")
        # commit
        is_new_day = spend_day_index not in b["_buckets"]
        b["_buckets"][spend_day_index] = bucket_prior + amount
        if is_new_day:
            b["days_elapsed"] += 1
        if b["_max_day"] is None or spend_day_index > b["_max_day"]:
            b["_max_day"] = spend_day_index
        b["spent_budget_cents"] += amount
        b["current_day_spent_cents"] = b["_buckets"][b["_max_day"]]
        db.touch(b)
        client = lookup.get_client(b["client_id"])
        recompute_client_budget(client)
        append_ledger(
            client_id=client["id"],
            entry_type="BOOST_SPEND",
            amount_cents=amount,
            boost_campaign_id=b["id"],
            cycle_index=client["current_cycle_index"],
        )
        return response.ok(boost_out(b))


@bp.post("/boost-campaigns/<boost_id>/complete")
def complete_boost(boost_id):
    _, role = get_user_context()
    require_role(role, {"FinanceController"})
    with db.LOCK:
        b = lookup.get_boost(boost_id)
        if b["status"] != "RUNNING":
            raise err(ERR_INVALID_STATE, "Boost campaign must be RUNNING to complete")
        client = lookup.get_client(b["client_id"])
        unspent = b["reserved_budget_cents"] - b["spent_budget_cents"]
        b["status"] = "COMPLETED"
        if unspent > 0:
            append_ledger(
                client_id=client["id"],
                entry_type="BOOST_RELEASE",
                amount_cents=-unspent,
                boost_campaign_id=b["id"],
                cycle_index=client["current_cycle_index"],
            )
        b["reserved_budget_cents"] = 0
        db.touch(b)
        recompute_client_budget(client)
        return response.ok(boost_out(b))


@bp.post("/boost-campaigns/<boost_id>/cancel")
def cancel_boost(boost_id):
    _, role = get_user_context()
    require_role(role, {"FinanceController"})
    with db.LOCK:
        b = lookup.get_boost(boost_id)
        if b["status"] not in ("DRAFT", "RESERVED"):
            raise err(ERR_INVALID_STATE, "Boost campaign must be DRAFT or RESERVED to cancel")
        client = lookup.get_client(b["client_id"])
        released = b["reserved_budget_cents"]  # 0 from DRAFT
        b["status"] = "CANCELLED"
        if released > 0:
            append_ledger(
                client_id=client["id"],
                entry_type="BOOST_RELEASE",
                amount_cents=-released,
                boost_campaign_id=b["id"],
                cycle_index=client["current_cycle_index"],
            )
        b["reserved_budget_cents"] = 0
        db.touch(b)
        recompute_client_budget(client)
        return response.ok(boost_out(b))
