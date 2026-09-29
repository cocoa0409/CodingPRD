"""Client subscriptions and the polymorphic deliverable lifecycle."""
from datetime import timedelta

from flask import Blueprint

from auth import ALL_ROLES, CLIENT_SERVICE_REP, CLIENT_USER, actor_id, roles
from calculations import (CLIENT_TIERS, MANUAL_HOLD_REASONS, REVISION_LIMIT,
                          TIER_TABLE, billing, days_late_from_seconds)
from common import must, unique_str_list
from errors import ApiError
from response import apply_filters, created, listing, ok
from store import created_key, db
from util import (bad_request, format_iso, get_body, parse_iso, require_fields,
                  seconds_between, want_enum, want_int, want_str,
                  want_str_list)

bp = Blueprint("clients", __name__)

HOLDABLE_STATES = ("SCHEDULED", "REQUESTED", "IN_PROGRESS")
NON_TERMINAL_STATES = ("SCHEDULED", "REQUESTED", "IN_PROGRESS",
                       "REVISION_REQUESTED")


def _sla_due(client):
    return format_iso(db.clock + timedelta(hours=client["delivery_sla_hours"]))


# -------------------------------------------------------------------- clients
@bp.post("/clients")
@roles(CLIENT_SERVICE_REP)
def register_client():
    body = get_body()
    require_fields(body, ["name", "tier", "contract_market_ids"])
    name = want_str(body, "name", min_len=1, max_len=120)
    tier = want_enum(body, "tier", CLIENT_TIERS)
    markets = unique_str_list(body, "contract_market_ids",
                              want_str_list(body, "contract_market_ids"),
                              min_items=1, max_items=10)
    derived = TIER_TABLE[tier]
    client = db.insert("clients", {
        "name": name,
        "tier": tier,
        "contract_market_ids": list(markets),
        "status": "ACTIVE",
        "tier_base_fee_cents": derived["tier_base_fee_cents"],
        "delivery_sla_hours": derived["delivery_sla_hours"],
        "custom_analysis_quota": derived["custom_analysis_quota"],
        "custom_analysis_used": 0,
        "held_deliverable_count": 0,
        "delivery_sla_credit_cents": 0,
        "suspended_reason": None,
    })
    return created(client)


@bp.post("/clients/<client_id>/suspend")
@roles(CLIENT_SERVICE_REP)
def suspend_client(client_id):
    client = must("clients", client_id)
    body = get_body()
    require_fields(body, ["suspended_reason"])
    reason = want_str(body, "suspended_reason", min_len=1)
    client["status"] = "SUSPENDED"
    client["suspended_reason"] = reason
    rows = [d for d in db.where("client_deliverables", client_id=client["id"])
            if d["state"] in NON_TERMINAL_STATES]
    rows.sort(key=created_key)
    for row in rows:
        row["held_from_state"] = row["state"]
        row["state"] = "HELD"
        row["hold_reason"] = "CLIENT_REQUESTED"
        db.touch(row)
    standing = len([d for d in db.where("client_deliverables",
                                        client_id=client["id"])
                    if d["state"] == "HELD"])
    client["held_deliverable_count"] = standing
    db.touch(client)
    return ok(client)


@bp.post("/clients/<client_id>/reinstate")
@roles(CLIENT_SERVICE_REP)
def reinstate_client(client_id):
    client = must("clients", client_id)
    if client["status"] != "SUSPENDED":
        raise ApiError("ERR_CLIENT_NOT_SUSPENDED",
                       "only a SUSPENDED client is reinstated")
    client["status"] = "ACTIVE"
    client["suspended_reason"] = None
    db.touch(client)
    return ok(client)


@bp.post("/clients/<client_id>/scheduled-deliverables")
@roles(CLIENT_SERVICE_REP)
def place_scheduled_dataset(client_id):
    client = must("clients", client_id)
    body = get_body()
    run = None
    if body.get("processing_run_id") is not None:
        run = must("processing_runs", body["processing_run_id"])
    require_fields(body, ["processing_run_id", "requested_cell_count"])
    cells = want_int(body, "requested_cell_count", minimum=0, maximum=24)
    if client["status"] == "SUSPENDED":
        raise ApiError("ERR_CLIENT_SUSPENDED",
                       "a suspended client receives no new deliverables")
    if run["market_id"] not in client["contract_market_ids"]:
        raise ApiError("ERR_MARKET_NOT_CONTRACTED",
                       "the run's market is not on the client's contract")
    if run["state"] == "SUPERSEDED":
        raise ApiError("ERR_RUN_SUPERSEDED",
                       "a superseded run carries no deliverable")
    row = db.insert("client_deliverables", {
        "client_id": client["id"],
        "processing_run_id": run["id"],
        "kind": "SCHEDULED_DATASET",
        "question": None,
        "requested_cell_count": cells,
        "state": "SCHEDULED",
        "held_from_state": None,
        "hold_reason": None,
        "due_at": _sla_due(client) if run["state"] == "PUBLISHED" else None,
        "revision_count": 0,
        "gross_cents": 0,
        "late_penalty_cents": 0,
        "discount_cents": 0,
        "total_cents": 0,
        "days_late": 0,
        "findings_summary": None,
        "delivered_at": None,
    })
    return created(row)


@bp.get("/clients/<client_id>")
@roles(*ALL_ROLES)
def read_client(client_id):
    return ok(must("clients", client_id))


@bp.get("/clients")
@roles(*ALL_ROLES)
def list_clients():
    rows = apply_filters(db.all("clients"), {
        "tier": ("tier", "str"),
        "status": ("status", "str"),
    })
    return listing("clients", rows)


# ------------------------------------------------------------- deliverables
def _price(row, client):
    due_at = row["due_at"]
    if due_at is None:
        days_late = 0
    else:
        days_late = days_late_from_seconds(
            seconds_between(parse_iso(due_at), db.clock))
    figures = billing(client["tier_base_fee_cents"],
                      row["requested_cell_count"], days_late)
    row.update(figures)
    client["delivery_sla_credit_cents"] = (client["delivery_sla_credit_cents"]
                                           + figures["late_penalty_cents"])
    db.touch(client)


@bp.post("/client-deliverables")
@roles(CLIENT_SERVICE_REP)
def file_custom_analysis():
    body = get_body()
    client = run = None
    if body.get("processing_run_id") is not None:
        run = must("processing_runs", body["processing_run_id"])
    if body.get("client_id") is not None:
        client = must("clients", body["client_id"])
    require_fields(body, ["client_id", "processing_run_id", "question",
                          "requested_cell_count"])
    question = want_str(body, "question", min_len=1, max_len=400)
    cells = want_int(body, "requested_cell_count", minimum=1, maximum=24)
    if client["status"] == "SUSPENDED":
        raise ApiError("ERR_CLIENT_SUSPENDED",
                       "a suspended client files no custom analysis")
    if run["market_id"] not in client["contract_market_ids"]:
        raise ApiError("ERR_MARKET_NOT_CONTRACTED",
                       "the run's market is not on the client's contract")
    if run["state"] != "PUBLISHED":
        raise ApiError("ERR_RUN_NOT_PUBLISHED",
                       "a custom analysis reads published data only")
    if client["custom_analysis_used"] >= client["custom_analysis_quota"]:
        raise ApiError("ERR_CUSTOM_ANALYSIS_QUOTA_EXCEEDED",
                       "the client's custom analysis quota is exhausted")
    row = db.insert("client_deliverables", {
        "client_id": client["id"],
        "processing_run_id": run["id"],
        "kind": "CUSTOM_ANALYSIS",
        "question": question,
        "requested_cell_count": cells,
        "state": "REQUESTED",
        "held_from_state": None,
        "hold_reason": None,
        "due_at": _sla_due(client),
        "revision_count": 0,
        "gross_cents": 0,
        "late_penalty_cents": 0,
        "discount_cents": 0,
        "total_cents": 0,
        "days_late": 0,
        "findings_summary": None,
        "delivered_at": None,
    })
    client["custom_analysis_used"] = client["custom_analysis_used"] + 1
    db.touch(client)
    return created(row)


@bp.post("/client-deliverables/<client_deliverable_id>/start")
@roles(CLIENT_SERVICE_REP)
def start_deliverable(client_deliverable_id):
    row = must("client_deliverables", client_deliverable_id)
    client = db.get("clients", row["client_id"])
    if (row["state"] not in ("REQUESTED", "REVISION_REQUESTED")
            or row["kind"] != "CUSTOM_ANALYSIS"
            or client is None or client["status"] != "ACTIVE"):
        raise ApiError("ERR_DELIVERABLE_NOT_DELIVERABLE",
                       "the row does not admit the analyst step")
    row["state"] = "IN_PROGRESS"
    db.touch(row)
    return ok(row)


@bp.post("/client-deliverables/<client_deliverable_id>/dispatch")
@roles(CLIENT_SERVICE_REP)
def dispatch_deliverable(client_deliverable_id):
    row = must("client_deliverables", client_deliverable_id)
    client = db.get("clients", row["client_id"])
    if client is not None and client["status"] == "SUSPENDED":
        raise ApiError("ERR_CLIENT_SUSPENDED",
                       "a suspended client receives no dispatch")
    run = db.get("processing_runs", row["processing_run_id"])
    if run is None or run["state"] != "PUBLISHED":
        raise ApiError("ERR_RUN_NOT_PUBLISHED",
                       "the pinned run must be PUBLISHED to dispatch")
    if row["state"] != "SCHEDULED" or row["kind"] != "SCHEDULED_DATASET":
        raise ApiError("ERR_DELIVERABLE_NOT_DELIVERABLE",
                       "only a SCHEDULED dataset placement is dispatched")
    _price(row, client)
    row["state"] = "DELIVERED"
    row["delivered_at"] = db.now_iso()
    db.touch(row)
    return ok(row)


@bp.post("/client-deliverables/<client_deliverable_id>/deliver")
@roles(CLIENT_SERVICE_REP)
def deliver_deliverable(client_deliverable_id):
    row = must("client_deliverables", client_deliverable_id)
    body = get_body()
    require_fields(body, ["findings_summary"])
    summary = want_str(body, "findings_summary", min_len=1)
    client = db.get("clients", row["client_id"])
    if client is not None and client["status"] == "SUSPENDED":
        raise ApiError("ERR_CLIENT_SUSPENDED",
                       "a suspended client receives no delivery")
    if row["state"] != "IN_PROGRESS":
        raise ApiError("ERR_DELIVERABLE_NOT_DELIVERABLE",
                       "only an IN_PROGRESS analysis is delivered")
    _price(row, client)
    row["state"] = "DELIVERED"
    row["findings_summary"] = summary
    row["delivered_at"] = db.now_iso()
    db.touch(row)
    return ok(row)


@bp.post("/client-deliverables/<client_deliverable_id>/request-revision")
@roles(CLIENT_USER)
def request_revision(client_deliverable_id):
    row = must("client_deliverables", client_deliverable_id)
    if actor_id() != row["client_id"]:
        raise ApiError("ERR_UNAUTHORIZED",
                       "a ClientUser acts only on its own deliverables")
    body = get_body()
    require_fields(body, ["reason"])
    want_str(body, "reason", min_len=1)
    if (row["state"] != "DELIVERED" or row["kind"] != "CUSTOM_ANALYSIS"
            or row["revision_count"] >= REVISION_LIMIT):
        raise ApiError("ERR_REVISION_LIMIT_REACHED",
                       "the row admits no further revision")
    row["state"] = "REVISION_REQUESTED"
    row["revision_count"] = row["revision_count"] + 1
    row["delivered_at"] = None
    row["gross_cents"] = 0
    row["discount_cents"] = 0
    row["late_penalty_cents"] = 0
    row["total_cents"] = 0
    db.touch(row)
    return ok(row)


@bp.post("/client-deliverables/<client_deliverable_id>/hold")
@roles(CLIENT_SERVICE_REP)
def hold_deliverable(client_deliverable_id):
    row = must("client_deliverables", client_deliverable_id)
    body = get_body()
    require_fields(body, ["hold_reason"])
    reason = body["hold_reason"]
    if reason == "UPSTREAM_RUN_REPIN":
        raise bad_request("hold_reason UPSTREAM_RUN_REPIN is reserved "
                          "for the system cascade")
    reason = want_enum(body, "hold_reason", MANUAL_HOLD_REASONS)
    if row["state"] not in HOLDABLE_STATES:
        raise ApiError("ERR_DELIVERABLE_NOT_DELIVERABLE",
                       "only a non-terminal, non-HELD row is held")
    row["held_from_state"] = row["state"]
    row["state"] = "HELD"
    row["hold_reason"] = reason
    db.touch(row)
    client = db.get("clients", row["client_id"])
    if client is not None:
        client["held_deliverable_count"] = client["held_deliverable_count"] + 1
        db.touch(client)
    return ok(row)


@bp.post("/client-deliverables/<client_deliverable_id>/release")
@roles(CLIENT_SERVICE_REP)
def release_deliverable(client_deliverable_id):
    row = must("client_deliverables", client_deliverable_id)
    run = db.get("processing_runs", row["processing_run_id"])
    if run is None or run["state"] != "PUBLISHED":
        raise ApiError("ERR_RUN_NOT_PUBLISHED",
                       "the pinned run must be PUBLISHED before release")
    if row["state"] != "HELD":
        raise ApiError("ERR_DELIVERABLE_NOT_HELD",
                       "only a HELD row is released")
    row["state"] = row["held_from_state"]
    row["held_from_state"] = None
    row["hold_reason"] = None
    db.touch(row)
    client = db.get("clients", row["client_id"])
    if client is not None:
        client["held_deliverable_count"] = max(
            0, client["held_deliverable_count"] - 1)
        db.touch(client)
    return ok(row)


@bp.get("/client-deliverables/<client_deliverable_id>")
@roles(*ALL_ROLES)
def read_deliverable(client_deliverable_id):
    return ok(must("client_deliverables", client_deliverable_id))


@bp.get("/client-deliverables")
@roles(*ALL_ROLES)
def list_deliverables():
    rows = apply_filters(db.all("client_deliverables"), {
        "client_id": ("client_id", "str"),
        "processing_run_id": ("processing_run_id", "str"),
        "kind": ("kind", "str"),
        "state": ("state", "str"),
        "hold_reason": ("hold_reason", "str"),
    })
    return listing("client_deliverables", rows)
