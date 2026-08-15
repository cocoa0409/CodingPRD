"""Release endpoints (PRD §3.6-§3.8)."""

from __future__ import annotations

from decimal import Decimal

from flask import Blueprint, g, request

import db
from db import clock_date, new_record, sort_key, touch
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_FORBIDDEN,
    ERR_JOB_ACCOUNT_NOT_FOUND,
    ERR_QUOTE_NOT_FOUND,
    ERR_CATALOG_ITEM_NOT_FOUND,
    ERR_RELEASE_NOT_FOUND,
    ERR_STALE_JOB_ACCOUNT_VERSION,
    ERR_JOB_NOT_OPEN,
    ERR_JOB_ON_CREDIT_HOLD,
    ERR_LIEN_WAIVER_REQUIRED,
    ERR_CREDIT_LIMIT_EXCEEDED,
    ERR_ITEM_NOT_ON_QUOTE,
    ERR_BELOW_MIN_CUT,
    ERR_RELEASE_NOT_REQUESTED,
    ERR_RELEASE_NOT_CREDIT_APPROVED,
    ERR_RELEASE_NOT_ALLOCATED,
    ERR_RELEASE_NOT_SCHEDULED,
    ERR_RELEASE_NOT_DELIVERED,
    ERR_RELEASE_NOT_CANCELLABLE,
    ERR_DELIVERY_WINDOW_PAST,
    ERR_TRUCK_WINDOW_OVERLAP,
    ERR_JOBSITE_DAY_CONFLICT,
)
from middleware import ROLES, atomic, require_roles
from response import success_list, success_object
from serializers import ser_release
from services.billing import line_amount
from util import (
    get_json_body,
    paginate,
    parse_date,
    require_date,
    require_int,
    require_string,
    to_decimal,
)

bp = Blueprint("releases", __name__, url_prefix="/distributor")

CANCELLABLE_STATUSES = ("REQUESTED", "CREDIT_APPROVED", "PARTIALLY_ALLOCATED", "ALLOCATED")


def _query_arg(name: str):
    value = request.args.get(name)
    return value if value not in (None, "") else None


def _get_release_or_404(release_id: str) -> dict:
    release = db.releases.get(release_id)
    if release is None:
        raise_err(ERR_RELEASE_NOT_FOUND, "No release with the given id")
    return release


def _release_lines(release: dict) -> list:
    lines = [l for l in db.release_lines.values() if l["release_id"] == release["id"]]
    return sorted(lines, key=sort_key)


def _check_contractor_ownership(job: dict) -> None:
    """Contractor-role callers may act only on their own job accounts."""
    if g.user_role == "Contractor" and job["contractor_id"] != g.user_id:
        raise_err(ERR_FORBIDDEN, "Contractor callers may act only on their own job accounts")


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


@bp.post("/releases")
@require_roles("SalesRep", "Contractor")
@atomic
def create_release():
    body = get_json_body()
    job_account_id = require_string(body, "job_account_id")
    quote_id = require_string(body, "quote_id")
    expected_version = require_int(body, "expected_job_account_version")
    raw_lines = body.get("lines")
    if not isinstance(raw_lines, list) or len(raw_lines) == 0:
        raise_err(ERR_INVALID_REQUEST, "lines must be a non-empty array")
    parsed = []
    for entry in raw_lines:
        if not isinstance(entry, dict):
            raise_err(ERR_INVALID_REQUEST, "each line must be an object with catalog_item_id and qty")
        if "catalog_item_id" not in entry or not isinstance(entry["catalog_item_id"], str) or entry["catalog_item_id"].strip() == "":
            raise_err(ERR_INVALID_REQUEST, "each line requires catalog_item_id")
        qty = to_decimal(entry.get("qty"))
        if qty is None or qty <= 0:
            raise_err(ERR_INVALID_REQUEST, "each line qty must be > 0")
        parsed.append((entry["catalog_item_id"], qty))

    # Existence, left to right: account, quote, then each line's item.
    job = db.job_accounts.get(job_account_id)
    if job is None:
        raise_err(ERR_JOB_ACCOUNT_NOT_FOUND, "No job account with the given id")
    quote = db.quotes.get(quote_id)
    if quote is None:
        raise_err(ERR_QUOTE_NOT_FOUND, "No quote with the given id")
    items = []
    for catalog_item_id, _qty in parsed:
        item = db.catalog_items.get(catalog_item_id)
        if item is None:
            raise_err(ERR_CATALOG_ITEM_NOT_FOUND, "No catalog item with the given id")
        items.append(item)

    _check_contractor_ownership(job)

    if expected_version != job["version"]:
        raise_err(ERR_STALE_JOB_ACCOUNT_VERSION, "expected_job_account_version does not match the job account's current version")

    if job["status"] != "OPEN":
        raise_err(ERR_JOB_NOT_OPEN, "Release creation requires the job account in OPEN")

    if quote["status"] != "AWARDED" or quote["job_account_id"] != job["id"]:
        raise_err(ERR_INVALID_REQUEST, "quote must be an AWARDED quote belonging to the same job account")

    quote_lines = [l for l in db.quote_lines.values() if l["quote_id"] == quote["id"]]
    for (catalog_item_id, qty), item in zip(parsed, items):
        if not any(l["catalog_item_id"] == catalog_item_id for l in quote_lines):
            raise_err(ERR_ITEM_NOT_ON_QUOTE, "Release line references a catalog item not present on the release's quote")
        if item["sell_uom"] == "FOOT" and qty < item["min_cut_ft"]:
            raise_err(ERR_BELOW_MIN_CUT, "FOOT line qty below the item's min_cut_ft")

    release = new_record(
        {
            "job_account_id": job["id"],
            "quote_id": quote["id"],
            "status": "REQUESTED",
            "estimated_total_cents": 0,
            "billed_total_cents": None,
            "truck_id": None,
            "delivery_date": None,
            "window_start_hour": None,
            "window_end_hour": None,
            "invoiced_on": None,
        }
    )
    db.releases[release["id"]] = release

    # Provisional extension: billing formula with qty_requested and the
    # logical clock at creation.
    estimated_total = 0
    for (catalog_item_id, qty), item in zip(parsed, items):
        line = new_record(
            {
                "release_id": release["id"],
                "catalog_item_id": catalog_item_id,
                "qty_requested": qty,
                "qty_allocated": Decimal(0),
                "qty_shipped": Decimal(0),
                "billed_amount_cents": None,
                "status": "OPEN",
            }
        )
        db.release_lines[line["id"]] = line
        estimated_total += line_amount(job, quote, item, catalog_item_id, qty)
    release["estimated_total_cents"] = estimated_total

    # Release creation legitimately mutates the account (OCC anchor).
    touch(job)
    return success_object(ser_release(release), 201)


@bp.get("/releases")
@require_roles(*ROLES)
def list_releases():
    job_account_id = _query_arg("job_account_id")
    quote_id = _query_arg("quote_id")
    status = _query_arg("status")
    items = sorted(db.releases.values(), key=sort_key)
    if job_account_id is not None:
        items = [r for r in items if r["job_account_id"] == job_account_id]
    if quote_id is not None:
        items = [r for r in items if r["quote_id"] == quote_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    page, limit, offset, total = paginate(items)
    return success_list([ser_release(r) for r in page], limit, offset, total)


@bp.get("/releases/<release_id>")
@require_roles(*ROLES)
def get_release(release_id: str):
    release = _get_release_or_404(release_id)
    return success_object(ser_release(release))


# ---------------------------------------------------------------------------
# Credit approval (PRD §3.6)
# ---------------------------------------------------------------------------


@bp.post("/releases/<release_id>/credit-approve")
@require_roles("CreditManager")
@atomic
def credit_approve_release(release_id: str):
    release = _get_release_or_404(release_id)
    if release["status"] != "REQUESTED":
        raise_err(ERR_RELEASE_NOT_REQUESTED, "Credit-approve requires the release in REQUESTED")
    job = db.job_accounts[release["job_account_id"]]
    if job["status"] != "OPEN":
        raise_err(ERR_JOB_ON_CREDIT_HOLD, "Credit-approve requires the job account not be in CREDIT_HOLD")
    if job["lien_waiver_required"]:
        expires_on = job["lien_waiver_expires_on"]
        if expires_on is None or parse_date(expires_on) < clock_date():
            raise_err(ERR_LIEN_WAIVER_REQUIRED, "Job requires a current lien waiver on file")
    contractor = db.contractors[job["contractor_id"]]
    headroom = (
        contractor["credit_limit_cents"]
        - contractor["invoiced_balance_cents"]
        - contractor["committed_balance_cents"]
    )
    if release["estimated_total_cents"] > headroom:
        raise_err(ERR_CREDIT_LIMIT_EXCEEDED, "estimated_total_cents exceeds credit headroom")
    release["status"] = "CREDIT_APPROVED"
    touch(release)
    contractor["committed_balance_cents"] += release["estimated_total_cents"]
    touch(contractor)
    return success_object(ser_release(release))


# ---------------------------------------------------------------------------
# Allocation (PRD §3.7)
# ---------------------------------------------------------------------------


@bp.post("/releases/<release_id>/allocate")
@require_roles("WarehouseManager")
@atomic
def allocate_release(release_id: str):
    release = _get_release_or_404(release_id)
    if release["status"] != "CREDIT_APPROVED":
        raise_err(ERR_RELEASE_NOT_CREDIT_APPROVED, "Allocate requires the release in CREDIT_APPROVED")
    lines = _release_lines(release)
    all_full = True
    for line in lines:
        item = db.catalog_items[line["catalog_item_id"]]
        alloc = min(line["qty_requested"], item["stock_on_hand"])
        if alloc != line["qty_allocated"]:
            line["qty_allocated"] = alloc
            item["stock_on_hand"] -= alloc
            item["stock_allocated"] += alloc
            touch(item)
        if alloc == line["qty_requested"]:
            line["status"] = "ALLOCATED"
        else:
            all_full = False
            line["status"] = "OPEN"
            backorder = new_record(
                {
                    "release_line_id": line["id"],
                    "catalog_item_id": line["catalog_item_id"],
                    "qty_open": line["qty_requested"] - alloc,
                    "status": "OPEN",
                }
            )
            db.backorder_allocations[backorder["id"]] = backorder
        touch(line)
    release["status"] = "ALLOCATED" if all_full else "PARTIALLY_ALLOCATED"
    touch(release)
    return success_object(ser_release(release))


# ---------------------------------------------------------------------------
# Scheduling, delivery, invoicing (PRD §3.8)
# ---------------------------------------------------------------------------


@bp.post("/releases/<release_id>/schedule")
@require_roles("Dispatcher")
@atomic
def schedule_release(release_id: str):
    body = get_json_body()
    truck_id = require_string(body, "truck_id")
    delivery_date = require_date(body, "delivery_date")
    window_start = require_int(body, "window_start_hour")
    window_end = require_int(body, "window_end_hour")
    if not (0 <= window_start <= 23) or not (1 <= window_end <= 24) or window_end <= window_start:
        raise_err(ERR_INVALID_REQUEST, "window_end_hour must be strictly later than window_start_hour")

    release = _get_release_or_404(release_id)
    if release["status"] != "ALLOCATED":
        raise_err(ERR_RELEASE_NOT_ALLOCATED, "Schedule requires the release in ALLOCATED")
    if parse_date(delivery_date) < clock_date():
        raise_err(ERR_DELIVERY_WINDOW_PAST, "delivery_date is before the logical clock date")

    for other in db.releases.values():
        if other["id"] == release["id"] or other["status"] not in ("SCHEDULED", "DELIVERED"):
            continue
        # Half-open window overlap: no conflict iff the new window ends at or
        # before the existing start, or begins at or after the existing end.
        if (
            other["truck_id"] == truck_id
            and other["delivery_date"] == delivery_date
            and not (window_end <= other["window_start_hour"] or window_start >= other["window_end_hour"])
        ):
            raise_err(ERR_TRUCK_WINDOW_OVERLAP, "Same truck, same date, half-open window overlap")

    for other in db.releases.values():
        if other["id"] == release["id"] or other["status"] not in ("SCHEDULED", "DELIVERED"):
            continue
        if other["job_account_id"] == release["job_account_id"] and other["delivery_date"] == delivery_date:
            raise_err(ERR_JOBSITE_DAY_CONFLICT, "Another release on the same job account already has a delivery on that date")

    release["truck_id"] = truck_id
    release["delivery_date"] = delivery_date
    release["window_start_hour"] = window_start
    release["window_end_hour"] = window_end
    release["status"] = "SCHEDULED"
    touch(release)
    return success_object(ser_release(release))


@bp.post("/releases/<release_id>/deliver")
@require_roles("Dispatcher")
@atomic
def deliver_release(release_id: str):
    release = _get_release_or_404(release_id)
    if release["status"] != "SCHEDULED":
        raise_err(ERR_RELEASE_NOT_SCHEDULED, "Deliver requires the release in SCHEDULED")
    for line in _release_lines(release):
        item = db.catalog_items[line["catalog_item_id"]]
        line["qty_shipped"] = line["qty_allocated"]
        line["status"] = "SHIPPED"
        touch(line)
        item["stock_allocated"] -= line["qty_shipped"]
        touch(item)
    release["status"] = "DELIVERED"
    touch(release)
    return success_object(ser_release(release))


@bp.post("/releases/<release_id>/invoice")
@require_roles("CreditManager")
@atomic
def invoice_release(release_id: str):
    release = _get_release_or_404(release_id)
    if release["status"] != "DELIVERED":
        raise_err(ERR_RELEASE_NOT_DELIVERED, "Invoice requires the release in DELIVERED")
    job = db.job_accounts[release["job_account_id"]]
    quote = db.quotes[release["quote_id"]]

    billed_total = 0
    for line in _release_lines(release):
        item = db.catalog_items[line["catalog_item_id"]]
        amount = line_amount(job, quote, item, line["catalog_item_id"], line["qty_shipped"])
        line["billed_amount_cents"] = amount
        line["status"] = "INVOICED"
        touch(line)
        billed_total += amount
    release["billed_total_cents"] = billed_total
    release["invoiced_on"] = clock_date().isoformat()
    release["status"] = "INVOICED"
    touch(release)

    contractor = db.contractors[job["contractor_id"]]
    contractor["committed_balance_cents"] -= release["estimated_total_cents"]
    contractor["invoiced_balance_cents"] += billed_total
    touch(contractor)

    # Credit contagion: over the limit, every OPEN job account of the
    # contractor goes on CREDIT_HOLD (PRD §3.8).
    if contractor["invoiced_balance_cents"] > contractor["credit_limit_cents"]:
        for other_job in db.job_accounts.values():
            if other_job["contractor_id"] == contractor["id"] and other_job["status"] == "OPEN":
                other_job["status"] = "CREDIT_HOLD"
                touch(other_job)
    return success_object(ser_release(release))


# ---------------------------------------------------------------------------
# Cancel (PRD §3.6)
# ---------------------------------------------------------------------------


@bp.post("/releases/<release_id>/cancel")
@require_roles("SalesRep", "Contractor")
@atomic
def cancel_release(release_id: str):
    release = _get_release_or_404(release_id)
    job = db.job_accounts[release["job_account_id"]]
    _check_contractor_ownership(job)
    if release["status"] not in CANCELLABLE_STATUSES:
        raise_err(ERR_RELEASE_NOT_CANCELLABLE, "Cancel requires the release in REQUESTED, CREDIT_APPROVED, PARTIALLY_ALLOCATED, or ALLOCATED")

    prior_status = release["status"]
    if prior_status in ("PARTIALLY_ALLOCATED", "ALLOCATED"):
        lines = _release_lines(release)
        line_ids = {l["id"] for l in lines}
        for line in lines:
            if line["qty_allocated"] > 0:
                item = db.catalog_items[line["catalog_item_id"]]
                item["stock_on_hand"] += line["qty_allocated"]
                item["stock_allocated"] -= line["qty_allocated"]
                touch(item)
            line["status"] = "CANCELLED"
            touch(line)
        for bo in db.backorder_allocations.values():
            if bo["release_line_id"] in line_ids and bo["status"] == "OPEN":
                bo["status"] = "CANCELLED"
                touch(bo)

    if prior_status in ("CREDIT_APPROVED", "PARTIALLY_ALLOCATED", "ALLOCATED"):
        contractor = db.contractors[job["contractor_id"]]
        contractor["committed_balance_cents"] -= release["estimated_total_cents"]
        touch(contractor)

    release["status"] = "CANCELLED"
    touch(release)
    return success_object(ser_release(release))
