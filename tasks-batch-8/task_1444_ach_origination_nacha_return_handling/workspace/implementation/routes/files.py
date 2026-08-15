"""AchFile intake, entry assembly, release, and cancellation."""

from __future__ import annotations

import re
from datetime import datetime

from flask import Blueprint, request

import db
from db import stamp_new, touch
from errors import (
    raise_err,
    ERR_EFFECTIVE_DATE_WINDOW,
    ERR_EXPOSURE_LIMIT_EXCEEDED,
    ERR_FILE_EMPTY,
    ERR_FILE_NOT_WAREHOUSED,
    ERR_INVALID_REQUEST,
    ERR_NO_ELIGIBLE_WINDOW,
    ERR_NOT_FOUND,
    ERR_ORIGINATOR_NOT_ACTIVE,
    ERR_RELEASE_DATE_MISMATCH,
    ERR_RESOURCE_OWNERSHIP,
    ERR_SAME_DAY_INELIGIBLE,
    ERR_STALE_VERSION,
)
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from services.domain import (
    SAME_DAY_KINDS,
    SAME_DAY_MAX_ENTRY_CENTS,
    SEC_CODES,
    WINDOW_KINDS,
    assign_window,
    banking_day_add,
    cancel_file,
    compute_exposure,
    compute_file_fee,
    entries_of_file,
    find_or_create_batch,
    is_banking_day,
    recompute_file_totals,
    today_logical,
    window_by_kind,
)
from util import (
    get_json_body,
    parse_pagination,
    paginate,
    require_date,
    require_enum,
    require_int,
    require_list,
    require_string,
    sort_by_created_at,
)

bp = Blueprint("files", __name__)

_ROUTING_RE = re.compile(r"^\d{9}$")


def get_file_or_404(file_id: str) -> dict:
    f = db.ach_files.get(file_id)
    if f is None:
        raise_err(ERR_NOT_FOUND, "AchFile not found")
    return f


def require_file_ownership(file: dict, user_id: str) -> None:
    if file["originator_id"] != user_id:
        raise_err(ERR_RESOURCE_OWNERSHIP, "Caller does not own this file")


@bp.route("/ach/ach-files", methods=["POST"])
@require_roles("OriginatorOps")
def create_file(_user_id: str, _role: str):
    body = get_json_body()
    # Schema (p5): enums + date format; SEC permission is schema (400) too.
    sec_code = require_enum(body, "sec_code", SEC_CODES)
    requested_kind = require_enum(body, "requested_window_kind", WINDOW_KINDS)
    effective_date = require_date(body, "effective_date")
    originator = db.originators.get(_user_id)
    if originator is not None and sec_code not in originator["sec_codes_allowed"]:
        raise_err(ERR_INVALID_REQUEST, "sec_code not in originator.sec_codes_allowed")

    # State (p6): caller identity must be an ACTIVE originator.
    if originator is None or originator["status"] != "ACTIVE":
        raise_err(ERR_ORIGINATOR_NOT_ACTIVE, "Originator is not ACTIVE")

    # Temporal (p9): banking day within [today, today + 2 banking days].
    today = today_logical()
    eff = datetime.strptime(effective_date, "%Y-%m-%d").date()
    if (
        not is_banking_day(eff)
        or eff < today
        or eff > banking_day_add(today, 2)
    ):
        raise_err(
            ERR_EFFECTIVE_DATE_WINDOW,
            "effective_date must be a banking day within [today, today + 2 banking days]",
        )

    # Structural (p10): a window row must exist for the requested kind.
    window = window_by_kind(requested_kind)
    if window is None:
        raise_err(ERR_NO_ELIGIBLE_WINDOW, f"No CutoffWindow for {requested_kind}")

    file = {
        "originator_id": _user_id,
        "sec_code": sec_code,
        "requested_window_kind": requested_kind,
        "effective_date": effective_date,
        "assigned_window_kind": None,
        "settlement_date": None,
        "settlement_batch_id": None,
        "entry_count": 0,
        "total_amount_cents": 0,
        "quoted_fee_cents": window["file_fee_cents"],
        "assessed_fee_cents": None,
        "status": "WAREHOUSED",
    }
    stamp_new(file)
    db.ach_files[file["id"]] = file
    return success_object(file, 201)


@bp.route("/ach/ach-files", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_files(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = sort_by_created_at(list(db.ach_files.values()))
    for name in ("originator_id", "status", "settlement_batch_id"):
        value = request.args.get(name)
        if value is not None and value != "":
            items = [f for f in items if str(f.get(name)) == value]
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/ach/ach-files/<file_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_file(file_id: str, _user_id: str, _role: str):
    return success_object(get_file_or_404(file_id))


@bp.route("/ach/ach-files/<file_id>/entries", methods=["POST"])
@require_roles("OriginatorOps")
def append_entries(file_id: str, _user_id: str, _role: str):
    # Existence (p4), then ownership (p3 semantics on an existing chain).
    file = get_file_or_404(file_id)
    require_file_ownership(file, _user_id)
    body = get_json_body()

    # Schema (p5): OCC field + per-entry shape. Full validation runs before
    # any persistence (bulk atomic append).
    expected_version = require_int(body, "expected_file_version")
    entries_in = require_list(body, "entries")
    parsed = []
    for raw in entries_in:
        if not isinstance(raw, dict):
            raise_err(ERR_INVALID_REQUEST, "Each entry must be an object")
        direction = require_enum(raw, "direction", {"DEBIT", "CREDIT"})
        amount = require_int(raw, "amount_cents", minimum=1)
        account = require_string(raw, "receiver_account")
        routing = require_string(raw, "receiver_routing")
        if not _ROUTING_RE.match(routing):
            raise_err(ERR_INVALID_REQUEST, "receiver_routing must be a 9-digit number")
        parsed.append(
            {
                "direction": direction,
                "amount_cents": amount,
                "receiver_account": account,
                "receiver_routing": routing,
            }
        )

    # State (p6)
    if file["status"] != "WAREHOUSED":
        raise_err(ERR_FILE_NOT_WAREHOUSED, "File is not WAREHOUSED")
    originator = db.originators[file["originator_id"]]
    if originator["status"] != "ACTIVE":
        raise_err(ERR_ORIGINATOR_NOT_ACTIVE, "Originator is not ACTIVE")

    # OCC (p7)
    if expected_version != file["version"]:
        raise_err(ERR_STALE_VERSION, "expected_file_version is stale")

    # NACHA compliance (p8): same-day per-entry cap (strictly greater rejects;
    # exactly $1,000,000.00 is eligible).
    if file["requested_window_kind"] in SAME_DAY_KINDS:
        for e in parsed:
            if e["amount_cents"] > SAME_DAY_MAX_ENTRY_CENTS:
                raise_err(
                    ERR_SAME_DAY_INELIGIBLE,
                    "Same-day files may not contain entries over $1,000,000.00",
                )

    # Structural (p10): the requested window's rate card must exist for the
    # quoted-fee recompute.
    window = window_by_kind(file["requested_window_kind"])
    if window is None:
        raise_err(
            ERR_NO_ELIGIBLE_WINDOW,
            f"No CutoffWindow for {file['requested_window_kind']}",
        )

    # Fiscal (p11): debit-exposure admission (strictly greater rejects;
    # equality admits; pure-CREDIT batches never trip it).
    _, debit_outstanding = compute_exposure(originator["id"])
    incoming_debit = sum(e["amount_cents"] for e in parsed if e["direction"] == "DEBIT")
    if debit_outstanding + incoming_debit > originator["exposure_limit_cents"]:
        raise_err(
            ERR_EXPOSURE_LIMIT_EXCEEDED,
            "Append would push outstanding debit exposure above exposure_limit_cents",
        )

    # Persist (atomic: all checks passed above).
    for e in parsed:
        entry = {
            "file_id": file["id"],
            "direction": e["direction"],
            "amount_cents": e["amount_cents"],
            "receiver_account": e["receiver_account"],
            "receiver_routing": e["receiver_routing"],
            "representment_count": 0,
            "last_return_code": None,
            "first_transmitted_at": None,
            "settled_at": None,
            "status": "WAREHOUSED",
        }
        stamp_new(entry)
        db.ach_entries[entry["id"]] = entry

    recompute_file_totals(file)
    file["quoted_fee_cents"] = compute_file_fee(file, window, originator)
    touch(file)

    # Exposure recompute (entries entered the outstanding set).
    gross, debit = compute_exposure(originator["id"])
    if (
        originator["outstanding_exposure_gross_cents"] != gross
        or originator["outstanding_exposure_debit_cents"] != debit
    ):
        originator["outstanding_exposure_gross_cents"] = gross
        originator["outstanding_exposure_debit_cents"] = debit
        touch(originator)

    return success_object(file)


@bp.route("/ach/ach-files/<file_id>/entries", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_entries(file_id: str, _user_id: str, _role: str):
    get_file_or_404(file_id)
    limit, offset = parse_pagination()
    items = entries_of_file(file_id)
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/ach/ach-files/<file_id>/release", methods=["POST"])
@require_roles("OdfiOperations")
def release_file(file_id: str, _user_id: str, _role: str):
    file = get_file_or_404(file_id)
    # State (p6)
    if file["status"] != "WAREHOUSED":
        raise_err(ERR_FILE_NOT_WAREHOUSED, "File is not WAREHOUSED")
    originator = db.originators[file["originator_id"]]
    if originator["status"] != "ACTIVE":
        raise_err(ERR_ORIGINATOR_NOT_ACTIVE, "Originator is not ACTIVE")
    # Temporal (p9): current banking day must equal the effective date.
    now = db.clock()
    today = now.date()
    if today.isoformat() != file["effective_date"]:
        raise_err(
            ERR_RELEASE_DATE_MISMATCH,
            "Current banking day does not equal the file's effective_date",
        )
    # Structural (p10): non-empty file; window rows support the assignment rule.
    if file["entry_count"] < 1:
        raise_err(ERR_FILE_EMPTY, "File has no entries")
    window = assign_window(file["requested_window_kind"], now)
    if window is None:
        raise_err(ERR_NO_ELIGIBLE_WINDOW, "No CutoffWindow supports the assignment rule")

    assigned_kind = window["window_kind"]
    settlement_date = (
        today.isoformat()
        if assigned_kind in SAME_DAY_KINDS
        else banking_day_add(today, 1).isoformat()
    )
    batch = find_or_create_batch(assigned_kind, settlement_date)

    file["assigned_window_kind"] = assigned_kind
    file["settlement_date"] = settlement_date
    file["settlement_batch_id"] = batch["id"]
    file["assessed_fee_cents"] = compute_file_fee(file, window, originator)
    file["status"] = "RELEASED"
    touch(file)
    return success_object(file)


@bp.route("/ach/ach-files/<file_id>/cancel", methods=["POST"])
@require_roles("OriginatorOps")
def cancel_file_endpoint(file_id: str, _user_id: str, _role: str):
    file = get_file_or_404(file_id)
    require_file_ownership(file, _user_id)
    if file["status"] != "WAREHOUSED":
        raise_err(ERR_FILE_NOT_WAREHOUSED, "File is not WAREHOUSED")
    cancel_file(file)
    return success_object(file)
