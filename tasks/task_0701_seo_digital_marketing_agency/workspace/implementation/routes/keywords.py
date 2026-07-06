"""KeywordTarget and RankSnapshot routes."""
from flask import Blueprint, request

import calc
from auth import require_auth, require_role
from clock import parse_iso8601
from db import store, base_record, touch
from errors import err
from helpers import (
    get_body, require_str, require_int, opt_str, find, assert_owns_client,
    paginate, parse_pagination,
)
from response import ok_object, ok_list

bp = Blueprint("keywords", __name__)

KEYWORD_STATUSES = {"PLANNED", "TRACKING", "DROPPED"}


@bp.route("/keyword-targets", methods=["POST"])
def create_keyword():
    principal = require_auth()
    require_role(principal, ["AgencyAdmin", "AccountManager"])
    body = get_body()
    client_id = require_str(body, "client_id")
    client = find("client", client_id)
    phrase = require_str(body, "phrase")
    search_volume = require_int(body, "search_volume", minimum=0)
    difficulty = require_int(body, "difficulty", minimum=0, maximum=100)

    # phrase unique per client among non-DROPPED
    for k in store.keyword_targets.values():
        if k["client_id"] == client_id and k["status"] != "DROPPED" and k["phrase"] == phrase:
            raise err("ERR_DUPLICATE_RESOURCE", "Duplicate keyword phrase for this client")

    priority = calc.keyword_priority_score(search_volume, difficulty)

    rec = base_record(versioned=True)
    rec.update({
        "client_id": client_id,
        "phrase": phrase,
        "search_volume": search_volume,
        "difficulty": difficulty,
        "priority_score": priority,
        "current_rank": 0,
        "best_rank": 0,
        "status": "PLANNED",
    })
    store.keyword_targets[rec["id"]] = rec
    return ok_object(rec, 201)


@bp.route("/keyword-targets/<kid>", methods=["GET"])
def get_keyword(kid):
    principal = require_auth()
    require_role(principal, ["AgencyAdmin", "AccountManager", "Client"])
    k = find("keyword_target", kid)
    client = find("client", k["client_id"])
    assert_owns_client(principal, client)
    k["priority_score"] = calc.keyword_priority_score(k["search_volume"], k["difficulty"])
    return ok_object(k, 200)


@bp.route("/keyword-targets", methods=["GET"])
def list_keywords():
    principal = require_auth()
    require_role(principal, ["AgencyAdmin", "AccountManager", "Client"])
    parse_pagination()
    client_filter = request.args.get("client_id")
    status_filter = request.args.get("status")
    records = list(store.keyword_targets.values())
    if principal.role == "Client":
        records = [k for k in records if k["client_id"] == principal.user_id]
    if client_filter is not None:
        records = [k for k in records if k["client_id"] == client_filter]
    if status_filter is not None:
        records = [k for k in records if k["status"] == status_filter]
    page, limit, offset, total = paginate(records)
    return ok_list(page, limit, offset, total)


@bp.route("/keyword-targets/<kid>/activate-tracking", methods=["POST"])
def activate_tracking(kid):
    principal = require_auth()
    require_role(principal, ["AgencyAdmin", "AccountManager"])
    k = find("keyword_target", kid)
    if k["status"] != "PLANNED":
        raise err("ERR_INVALID_STATE", "Keyword must be PLANNED to activate tracking")
    client = find("client", k["client_id"])
    if client["status"] not in ("AUDITED", "ACTIVE"):
        raise err("ERR_CLIENT_NOT_AUDITED", "Client must be AUDITED or ACTIVE")
    k["status"] = "TRACKING"
    touch(k)
    return ok_object(k, 200)


@bp.route("/keyword-targets/<kid>/drop", methods=["POST"])
def drop_keyword(kid):
    principal = require_auth()
    require_role(principal, ["AgencyAdmin", "AccountManager"])
    k = find("keyword_target", kid)
    if k["status"] not in ("PLANNED", "TRACKING"):
        raise err("ERR_INVALID_STATE", "Keyword must be PLANNED or TRACKING to drop")
    k["status"] = "DROPPED"
    touch(k)
    return ok_object(k, 200)


# ---------------------------------------------------------------------------
# RankSnapshot
# ---------------------------------------------------------------------------


@bp.route("/keyword-targets/<kid>/snapshots", methods=["POST"])
def create_snapshot(kid):
    principal = require_auth()
    require_role(principal, ["AgencyAdmin", "AccountManager"])
    k = find("keyword_target", kid)
    body = get_body()
    position = require_int(body, "position", minimum=0, maximum=100)
    organic_traffic = require_int(body, "organic_traffic", minimum=0)
    observed_at_raw = opt_str(body, "observed_at", default=None)
    if observed_at_raw is not None:
        parsed = parse_iso8601(observed_at_raw)
        if parsed is None:
            raise err("ERR_INVALID_REQUEST", "observed_at must be a valid ISO-8601 datetime")
        observed_at = parsed
    else:
        observed_at = store.clock.now()

    from clock import iso_format
    rec = base_record(versioned=False)
    rec.update({
        "keyword_target_id": kid,
        "position": position,
        "organic_traffic": organic_traffic,
        "observed_at": iso_format(observed_at),
    })
    store.rank_snapshots[rec["id"]] = rec

    # update keyword current_rank / best_rank
    k["current_rank"] = position
    if position > 0:
        if k["best_rank"] == 0:
            k["best_rank"] = position
        else:
            k["best_rank"] = min(k["best_rank"], position)
    touch(k)
    return ok_object(rec, 201)


@bp.route("/snapshots/<sid>", methods=["GET"])
def get_snapshot(sid):
    principal = require_auth()
    require_role(principal, ["AgencyAdmin", "AccountManager", "Client"])
    snap = find("rank_snapshot", sid)
    k = find("keyword_target", snap["keyword_target_id"])
    client = find("client", k["client_id"])
    assert_owns_client(principal, client)
    return ok_object(snap, 200)


@bp.route("/keyword-targets/<kid>/snapshots", methods=["GET"])
def list_snapshots(kid):
    principal = require_auth()
    require_role(principal, ["AgencyAdmin", "AccountManager", "Client"])
    k = find("keyword_target", kid)
    client = find("client", k["client_id"])
    assert_owns_client(principal, client)
    parse_pagination()
    records = [s for s in store.rank_snapshots.values() if s["keyword_target_id"] == kid]
    page, limit, offset, total = paginate(records)
    return ok_list(page, limit, offset, total)
