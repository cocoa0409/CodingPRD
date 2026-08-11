"""Manifest endpoints (PRD §3.3, §3.4 scanning, §3.8 quote creation)."""

from decimal import Decimal

from flask import Blueprint, request

import db
import serialize
import utils
import clocktime
from errors import (ApiError, ERR_ACCOUNT_NOT_FOUND, ERR_ACCOUNT_SUSPENDED,
                    ERR_CLOSE_SETTLEMENT_UNPAID, ERR_INVALID_STATE,
                    ERR_MANIFEST_EMPTY, ERR_MANIFEST_HAS_ITEMS,
                    ERR_MANIFEST_ITEM_COUNT_MISMATCH, ERR_MANIFEST_NOT_FOUND,
                    ERR_ROUTE_WINDOW_CONFLICT, ERR_SETTLEMENT_ALREADY_FINALIZED,
                    ERR_STALE_VERSION, ERR_UNAUTHORIZED, ERR_VALIDATION,
                    ERR_WINDOW_IN_PAST)
from middleware import require_roles, check_owns_account
from response import ok_object, paginate, sort_created
from services import calculations as calc
from services import workflow

bp = Blueprint("manifests", __name__)

MODES = {"PICKUP", "DROPOFF"}
ITEM_PROCESSING_STATUSES = {"INTAKE", "FOR_RESALE", "FOR_REFURB", "FOR_RECYCLE",
                            "LISTED", "SOLD", "BATCHED", "DOWNSTREAM", "COMPLETE"}


def get_manifest_or_404(manifest_id):
    manifest = db.manifests.get(manifest_id)
    if manifest is None:
        raise ApiError(ERR_MANIFEST_NOT_FOUND, 404, "no Manifest with the given id")
    return manifest


def _refresh_manifest_counts(manifest):
    count = sum(1 for i in db.items.values() if i["manifest_id"] == manifest["id"])
    manifest["received_item_count"] = count
    manifest["discrepancy_flag"] = count != manifest["declared_item_count"]


def _validate_window_pair(start, end):
    if start is not None and end is not None and not (end > start):
        raise ApiError(ERR_VALIDATION, 400,
                       "scheduled_end must be strictly after scheduled_start")


@bp.post("/itad/manifests")
def create_manifest():
    uid, role = require_roles("AccountManager")
    data = request.get_json(force=True, silent=True)
    if not isinstance(data, dict):
        raise ApiError(ERR_VALIDATION, 400, "request body must be a JSON object")
    # Creation path order (PRD §3.3): ownership first, then body validation,
    # then the account-activity check.
    raw_account_id = data.get("account_id")
    if isinstance(raw_account_id, str) and raw_account_id != uid:
        raise ApiError(ERR_UNAUTHORIZED, 403,
                       "AccountManager may only create manifests for its own account")
    account_id = utils.req_str(data, "account_id")
    mode = utils.req_enum(data, "mode", MODES)
    pickup_route = utils.opt_str(data, "pickup_route")
    scheduled_start = utils.opt_datetime(data, "scheduled_start")
    scheduled_end = utils.opt_datetime(data, "scheduled_end")
    declared_item_count = utils.req_int(data, "declared_item_count")
    if declared_item_count < 1:
        raise ApiError(ERR_VALIDATION, 400, "declared_item_count must be >= 1")
    if mode == "PICKUP" and not pickup_route:
        raise ApiError(ERR_VALIDATION, 400, "pickup_route is required for PICKUP manifests")
    if mode == "DROPOFF" and pickup_route is not None:
        raise ApiError(ERR_VALIDATION, 400, "pickup_route must be absent for DROPOFF manifests")
    _validate_window_pair(scheduled_start, scheduled_end)

    account = db.accounts.get(account_id)
    if account is None:
        raise ApiError(ERR_ACCOUNT_NOT_FOUND, 404, "no BusinessAccount with the given id")
    if account["status"] != "ACTIVE":
        raise ApiError(ERR_ACCOUNT_SUSPENDED, 422, "account is not ACTIVE")

    manifest = {
        "id": utils.new_id(),
        "account_id": account_id,
        "mode": mode,
        "pickup_route": pickup_route,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "declared_item_count": declared_item_count,
        "received_item_count": 0,
        "discrepancy_flag": False,
        "status": "DRAFT",
    }
    utils.stamp_new(manifest)
    db.manifests[manifest["id"]] = manifest
    return ok_object(serialize.manifest(manifest), code=201)


@bp.get("/itad/manifests/<manifest_id>")
def read_manifest(manifest_id):
    uid, role = require_roles("PlatformAdmin", "AccountManager", "IntakeOperator",
                              "LogisticsCoordinator")
    manifest = get_manifest_or_404(manifest_id)
    check_owns_account(uid, role, manifest["account_id"])
    return ok_object(serialize.manifest(manifest))


@bp.patch("/itad/manifests/<manifest_id>")
def amend_manifest(manifest_id):
    uid, role = require_roles("AccountManager")
    manifest = get_manifest_or_404(manifest_id)
    check_owns_account(uid, role, manifest["account_id"])
    data = utils.body_json()
    expected = utils.req_int(data, "expected_manifest_version")
    pickup_route_given = "pickup_route" in data
    pickup_route = utils.opt_str(data, "pickup_route")
    scheduled_start = utils.opt_datetime(data, "scheduled_start")
    scheduled_end = utils.opt_datetime(data, "scheduled_end")
    declared_item_count = utils.opt_int(data, "declared_item_count")
    if declared_item_count is not None and declared_item_count < 1:
        raise ApiError(ERR_VALIDATION, 400, "declared_item_count must be >= 1")

    # Effective values merged with the stored ones for window/route rules.
    eff_start = scheduled_start if scheduled_start is not None else manifest["scheduled_start"]
    eff_end = scheduled_end if scheduled_end is not None else manifest["scheduled_end"]
    eff_route = pickup_route if pickup_route_given else manifest["pickup_route"]
    _validate_window_pair(eff_start, eff_end)
    if manifest["mode"] == "PICKUP" and not eff_route:
        raise ApiError(ERR_VALIDATION, 400, "pickup_route is required for PICKUP manifests")
    if manifest["mode"] == "DROPOFF" and eff_route is not None:
        raise ApiError(ERR_VALIDATION, 400, "pickup_route must be absent for DROPOFF manifests")

    # OCC (priority 6) before the DRAFT state gate (priority 7).
    if expected != manifest["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_manifest_version does not match the manifest version")
    if manifest["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409, "only DRAFT manifests may be amended")

    if pickup_route_given:
        manifest["pickup_route"] = pickup_route
    if scheduled_start is not None:
        manifest["scheduled_start"] = scheduled_start
    if scheduled_end is not None:
        manifest["scheduled_end"] = scheduled_end
    if declared_item_count is not None:
        manifest["declared_item_count"] = declared_item_count
        manifest["discrepancy_flag"] = (
            manifest["received_item_count"] != manifest["declared_item_count"]
        )
    utils.touch(manifest)
    return ok_object(serialize.manifest(manifest))


@bp.post("/itad/manifests/<manifest_id>/schedule")
def schedule_manifest(manifest_id):
    uid, role = require_roles("LogisticsCoordinator")
    manifest = get_manifest_or_404(manifest_id)
    if manifest["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409, "only DRAFT manifests can be scheduled")
    account = db.accounts[manifest["account_id"]]
    if account["status"] != "ACTIVE":
        raise ApiError(ERR_ACCOUNT_SUSPENDED, 422, "owning account is not ACTIVE")
    if manifest["scheduled_start"] is None or manifest["scheduled_end"] is None:
        raise ApiError(ERR_VALIDATION, 400,
                       "scheduled_start and scheduled_end must be set before scheduling")
    if not (manifest["scheduled_end"] > clocktime.now()):
        raise ApiError(ERR_WINDOW_IN_PAST, 422,
                       "scheduled_end must lie strictly after the current clock")
    if manifest["mode"] == "PICKUP":
        for other in db.manifests.values():
            if other["id"] == manifest["id"]:
                continue
            if other["status"] not in ("SCHEDULED", "RECEIVED"):
                continue
            if other.get("pickup_route") != manifest["pickup_route"]:
                continue
            if other["scheduled_start"] is None or other["scheduled_end"] is None:
                continue
            # Half-open [start, end): adjacency (end == start) is allowed.
            if (manifest["scheduled_start"] < other["scheduled_end"]
                    and other["scheduled_start"] < manifest["scheduled_end"]):
                raise ApiError(ERR_ROUTE_WINDOW_CONFLICT, 409,
                               "pickup route window overlaps another scheduled manifest")
    manifest["status"] = "SCHEDULED"
    utils.touch(manifest)
    return ok_object(serialize.manifest(manifest))


@bp.post("/itad/manifests/<manifest_id>/receive")
def receive_manifest(manifest_id):
    uid, role = require_roles("IntakeOperator")
    manifest = get_manifest_or_404(manifest_id)
    if manifest["status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE, 409, "only SCHEDULED manifests can be received")
    manifest["status"] = "RECEIVED"
    utils.touch(manifest)
    workflow.write_custody("MANIFEST", manifest["id"], "RECEIVED_FACILITY", uid)
    return ok_object(serialize.manifest(manifest))


@bp.post("/itad/manifests/<manifest_id>/reconcile")
def reconcile_manifest(manifest_id):
    uid, role = require_roles("IntakeOperator")
    manifest = get_manifest_or_404(manifest_id)
    if manifest["status"] != "RECEIVED":
        raise ApiError(ERR_INVALID_STATE, 409, "only RECEIVED manifests can be reconciled")
    items = workflow.manifest_items(manifest["id"])
    if any(i["processing_status"] == "INTAKE" for i in items):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "all items must be triaged before reconciliation")
    if manifest["received_item_count"] < 1:
        raise ApiError(ERR_MANIFEST_EMPTY, 422, "no items scanned into the manifest")
    if manifest["received_item_count"] != manifest["declared_item_count"]:
        raise ApiError(ERR_MANIFEST_ITEM_COUNT_MISMATCH, 422,
                       "received_item_count differs from declared_item_count")
    manifest["status"] = "RECONCILED"
    utils.touch(manifest)
    return ok_object(serialize.manifest(manifest))


@bp.post("/itad/manifests/<manifest_id>/close")
def close_manifest(manifest_id):
    uid, role = require_roles("AccountManager")
    manifest = get_manifest_or_404(manifest_id)
    check_owns_account(uid, role, manifest["account_id"])
    if manifest["status"] != "RECONCILED":
        raise ApiError(ERR_INVALID_STATE, 409, "only RECONCILED manifests can be closed")
    settlements = workflow.manifest_settlements(manifest["id"])
    if not settlements or any(
        s["status"] not in ("SUPERSEDED", "PAID", "VOIDED") for s in settlements
    ):
        raise ApiError(ERR_CLOSE_SETTLEMENT_UNPAID, 422,
                       "every non-SUPERSEDED settlement must be PAID or VOIDED")
    manifest["status"] = "CLOSED"
    utils.touch(manifest)
    return ok_object(serialize.manifest(manifest))


@bp.post("/itad/manifests/<manifest_id>/cancel")
def cancel_manifest(manifest_id):
    uid, role = require_roles("AccountManager")
    manifest = get_manifest_or_404(manifest_id)
    check_owns_account(uid, role, manifest["account_id"])
    if manifest["status"] not in ("DRAFT", "SCHEDULED"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "only DRAFT or SCHEDULED manifests can be cancelled")
    if manifest["received_item_count"] != 0:
        raise ApiError(ERR_MANIFEST_HAS_ITEMS, 422,
                       "cannot cancel a manifest with scanned items")
    manifest["status"] = "CANCELLED"
    utils.touch(manifest)
    return ok_object(serialize.manifest(manifest))


# ---------------------------------------------------------------------------
# Item scanning under a manifest
# ---------------------------------------------------------------------------

@bp.post("/itad/manifests/<manifest_id>/items")
def scan_item(manifest_id):
    uid, role = require_roles("IntakeOperator")
    manifest = get_manifest_or_404(manifest_id)
    data = utils.body_json()
    serial_number = utils.req_str(data, "serial_number")
    category = utils.req_enum(data, "category", calc.CATEGORIES)
    weight_kg = utils.req_weight(data, "weight_kg")
    data_bearing = utils.req_bool(data, "data_bearing")
    hazmat_flag = utils.req_bool(data, "hazmat_flag")
    declared_grade = utils.req_enum(data, "declared_grade", calc.GRADES)
    for other in db.items.values():
        if (other["manifest_id"] == manifest["id"]
                and other["serial_number"] == serial_number):
            raise ApiError(ERR_VALIDATION, 400,
                           "serial_number must be unique within the manifest")
    if manifest["status"] not in ("DRAFT", "RECEIVED"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "items may be scanned only while the manifest is DRAFT or RECEIVED")
    item = {
        "id": utils.new_id(),
        "manifest_id": manifest["id"],
        "serial_number": serial_number,
        "category": category,
        "weight_kg": weight_kg,
        "data_bearing": data_bearing,
        "hazmat_flag": hazmat_flag,
        "declared_grade": declared_grade,
        "disposition": "NONE",
        "processing_status": "INTAKE",
        "data_status": "PENDING" if data_bearing else "NOT_REQUIRED",
        "recycle_batch_id": None,
        "provisional_value_cents": 0,
        "final_value_cents": 0,
    }
    utils.stamp_new(item)
    db.items[item["id"]] = item
    _refresh_manifest_counts(manifest)
    utils.touch(manifest)
    return ok_object(serialize.item(item), code=201)


@bp.get("/itad/manifests/<manifest_id>/items")
def list_manifest_items(manifest_id):
    uid, role = require_roles("PlatformAdmin", "AccountManager", "IntakeOperator",
                              "LogisticsCoordinator", "ComplianceOfficer")
    manifest = get_manifest_or_404(manifest_id)
    check_owns_account(uid, role, manifest["account_id"])
    records = workflow.manifest_items(manifest["id"])
    status_filter = request.args.get("processing_status")
    if status_filter is not None:
        if status_filter not in ITEM_PROCESSING_STATUSES:
            raise ApiError(ERR_VALIDATION, 400, "invalid processing_status filter")
        records = [i for i in records if i["processing_status"] == status_filter]
    records = sort_created(records)
    return paginate([serialize.item(i) for i in records])


# ---------------------------------------------------------------------------
# Settlements under a manifest
# ---------------------------------------------------------------------------

@bp.get("/itad/manifests/<manifest_id>/settlements")
def list_manifest_settlements(manifest_id):
    uid, role = require_roles("PlatformAdmin", "AccountManager", "IntakeOperator")
    manifest = get_manifest_or_404(manifest_id)
    check_owns_account(uid, role, manifest["account_id"])
    records = sort_created(workflow.manifest_settlements(manifest["id"]))
    return paginate([serialize.settlement(s) for s in records])


@bp.post("/itad/manifests/<manifest_id>/settlements")
def create_quote_settlement(manifest_id):
    uid, role = require_roles("IntakeOperator")
    manifest = get_manifest_or_404(manifest_id)
    data = utils.body_json()
    expected = utils.req_int(data, "expected_manifest_version")
    if expected != manifest["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_manifest_version does not match the manifest version")
    if manifest["status"] not in ("RECEIVED", "RECONCILED"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "quotes may be requested only after receipt")
    settlements = workflow.manifest_settlements(manifest["id"])
    if any(s["status"] in ("FINALIZED", "PAID") for s in settlements):
        raise ApiError(ERR_SETTLEMENT_ALREADY_FINALIZED, 422,
                       "a settlement of this manifest is already FINALIZED or PAID")
    prior_open = next((s for s in settlements if s["status"] == "QUOTE_OPEN"), None)
    figures = calc.compute_settlement_figures(
        manifest, workflow.manifest_items(manifest["id"]), "QUOTE"
    )
    settlement = {
        "id": utils.new_id(),
        "manifest_id": manifest["id"],
        "kind": "QUOTE",
        "status": "QUOTE_OPEN",
        "supersedes_settlement_id": prior_open["id"] if prior_open else None,
        **figures,
    }
    utils.stamp_new(settlement)
    db.settlements[settlement["id"]] = settlement
    if prior_open is not None:
        prior_open["status"] = "SUPERSEDED"
        utils.touch(prior_open)
    utils.touch(manifest)
    return ok_object(serialize.settlement(settlement), code=201)
