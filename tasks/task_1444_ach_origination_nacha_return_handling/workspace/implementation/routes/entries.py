"""AchEntry reads plus returns, re-presentments, NOCs, reversals, and close."""

from __future__ import annotations

from datetime import datetime

from flask import Blueprint

import db
from db import stamp_new, touch
from errors import (
    raise_err,
    ERR_DUPLICATE_ACTIVE_REVERSAL,
    ERR_ENTRY_NOT_RETURNED,
    ERR_ENTRY_NOT_SETTLED,
    ERR_INVALID_REQUEST,
    ERR_INVALID_REVERSAL_REASON,
    ERR_NOT_FOUND,
    ERR_REPRESENTMENT_CODE_PROHIBITED,
    ERR_REPRESENTMENT_EXHAUSTED,
    ERR_RESOURCE_OWNERSHIP,
    ERR_REVERSAL_WINDOW_EXPIRED,
)
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from services.domain import (
    NOC_CODES,
    REPRESENTMENT_CAP,
    RETURN_CODES,
    REVERSAL_REASONS,
    UNAUTH_CODES,
    banking_day_add,
    maybe_auto_open_rate_breach_case,
    originator_id_of_entry,
    refresh_originator_rates,
    today_logical,
)
from util import (
    get_json_body,
    parse_pagination,
    paginate,
    require_enum,
    require_field,
    require_string,
    sort_by_created_at,
)

bp = Blueprint("entries", __name__)


def get_entry_or_404(entry_id: str) -> dict:
    e = db.ach_entries.get(entry_id)
    if e is None:
        raise_err(ERR_NOT_FOUND, "AchEntry not found")
    return e


def require_entry_ownership(entry: dict, user_id: str) -> None:
    if originator_id_of_entry(entry) != user_id:
        raise_err(ERR_RESOURCE_OWNERSHIP, "Caller does not own this entry's file")


@bp.route("/ach/ach-entries/<entry_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_entry(entry_id: str, _user_id: str, _role: str):
    return success_object(get_entry_or_404(entry_id))


@bp.route("/ach/ach-entries/<entry_id>/returns", methods=["POST"])
@require_roles("OdfiOperations")
def register_return(entry_id: str, _user_id: str, _role: str):
    entry = get_entry_or_404(entry_id)
    body = get_json_body()
    # Schema (p5): unknown return code fails here.
    return_code = require_enum(body, "return_code", RETURN_CODES)
    # State (p6): only SETTLED entries accept a return.
    if entry["status"] != "SETTLED":
        raise_err(ERR_ENTRY_NOT_SETTLED, "Entry is not SETTLED")

    case = {
        "entry_id": entry["id"],
        "return_code": return_code,
        "received_at": db.now_logical_iso(),
        "is_unauthorized": return_code in UNAUTH_CODES,
        "representment_number": entry["representment_count"],
        "gl_posted": False,
        "disposition": "OPEN",
    }
    stamp_new(case)
    db.return_cases[case["id"]] = case

    # Entry moves to RETURNED for every return code.
    entry["status"] = "RETURNED"
    entry["last_return_code"] = return_code
    touch(entry)

    # Unauthorized codes: recompute rates at the current clock; the rate-field
    # mutation triggers conditional RATE_BREACH RiskCase auto-open.
    if case["is_unauthorized"]:
        oid = originator_id_of_entry(entry)
        rates = refresh_originator_rates(oid, db.clock())
        if rates["breach"]:
            maybe_auto_open_rate_breach_case(oid)

    return success_object(case, 201)


@bp.route("/ach/ach-entries/<entry_id>/representments", methods=["POST"])
@require_roles("OdfiOperations")
def create_representment(entry_id: str, _user_id: str, _role: str):
    entry = get_entry_or_404(entry_id)
    # State (p6)
    if entry["status"] != "RETURNED":
        raise_err(ERR_ENTRY_NOT_RETURNED, "Entry is not RETURNED")
    # NACHA compliance (p8): R01-only re-presentment.
    if entry["last_return_code"] != "R01":
        raise_err(
            ERR_REPRESENTMENT_CODE_PROHIBITED,
            "Only R01 (insufficient funds) returns may be re-presented",
        )
    # Structural (p10): hard cap of two re-presentments.
    if entry["representment_count"] >= REPRESENTMENT_CAP:
        raise_err(ERR_REPRESENTMENT_EXHAUSTED, "Re-presentment cap of 2 reached")

    entry["representment_count"] += 1
    # The entry's OPEN ReturnCase -> REPRESENTED (terminal).
    for rc in sort_by_created_at(list(db.return_cases.values())):
        if rc["entry_id"] == entry["id"] and rc["disposition"] == "OPEN":
            rc["disposition"] = "REPRESENTED"
            touch(rc)
    # Back to TRANSMITTED; joins the re-flow sweep. first_transmitted_at untouched.
    entry["status"] = "TRANSMITTED"
    touch(entry)
    return success_object(entry)


@bp.route("/ach/ach-entries/<entry_id>/nocs", methods=["POST"])
@require_roles("OdfiOperations")
def register_noc(entry_id: str, _user_id: str, _role: str):
    entry = get_entry_or_404(entry_id)
    body = get_json_body()
    noc_code = require_enum(body, "noc_code", NOC_CODES)
    corrected_data = require_string(body, "corrected_data")
    # State (p6): NOC registration is accepted only from SETTLED or RETURNED.
    if entry["status"] not in ("SETTLED", "RETURNED"):
        raise_err(ERR_ENTRY_NOT_SETTLED, "Entry must be SETTLED or RETURNED for a NOC")

    received = db.clock()
    noc = {
        "entry_id": entry["id"],
        "noc_code": noc_code,
        "corrected_data": corrected_data,
        "received_at": db.format_iso(received),
        "due_date": banking_day_add(received.date(), 6).isoformat(),
        "late_applied": False,
        "status": "RECEIVED",
    }
    stamp_new(noc)
    db.noc_records[noc["id"]] = noc
    return success_object(noc, 201)


@bp.route("/ach/ach-entries/<entry_id>/noc-records", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_noc_records(entry_id: str, _user_id: str, _role: str):
    get_entry_or_404(entry_id)
    limit, offset = parse_pagination()
    items = sort_by_created_at(
        [n for n in db.noc_records.values() if n["entry_id"] == entry_id]
    )
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/ach/ach-entries/<entry_id>/reversals", methods=["POST"])
@require_roles("OriginatorOps")
def request_reversal(entry_id: str, _user_id: str, _role: str):
    # Existence (p4), ownership (p3 on an existing chain).
    entry = get_entry_or_404(entry_id)
    require_entry_ownership(entry, _user_id)
    body = get_json_body()
    # Schema (p5): reason must be present.
    reason = require_field(body, "reason")
    # State (p6): entry must be SETTLED.
    if entry["status"] != "SETTLED":
        raise_err(ERR_ENTRY_NOT_SETTLED, "Entry is not SETTLED")
    # NACHA compliance (p8): reason admissibility.
    if not isinstance(reason, str) or reason not in REVERSAL_REASONS:
        raise_err(
            ERR_INVALID_REVERSAL_REASON,
            f"reason must be one of {sorted(REVERSAL_REASONS)}",
        )
    # Temporal (p9): on or before settled_at date + 5 banking days.
    settled_date = datetime.strptime(entry["settled_at"][:10], "%Y-%m-%d").date()
    window_expires = banking_day_add(settled_date, 5)
    if today_logical() > window_expires:
        raise_err(
            ERR_REVERSAL_WINDOW_EXPIRED,
            "Reversal requested after settled_at + 5 banking days",
        )
    # Structural (p10): one active reversal per entry.
    for rr in db.reversal_requests.values():
        if rr["entry_id"] == entry["id"] and rr["status"] in ("REQUESTED", "TRANSMITTED"):
            raise_err(ERR_DUPLICATE_ACTIVE_REVERSAL, "Entry already has an active reversal")

    reversal = {
        "entry_id": entry["id"],
        "reason": reason,
        "requested_at": db.now_logical_iso(),
        "window_expires_at": window_expires.isoformat(),
        "status": "REQUESTED",
    }
    stamp_new(reversal)
    db.reversal_requests[reversal["id"]] = reversal
    return success_object(reversal, 201)


@bp.route("/ach/ach-entries/<entry_id>/reversal-requests", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_reversal_requests(entry_id: str, _user_id: str, _role: str):
    get_entry_or_404(entry_id)
    limit, offset = parse_pagination()
    items = sort_by_created_at(
        [r for r in db.reversal_requests.values() if r["entry_id"] == entry_id]
    )
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/ach/ach-entries/<entry_id>/return-cases", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_return_cases(entry_id: str, _user_id: str, _role: str):
    get_entry_or_404(entry_id)
    limit, offset = parse_pagination()
    items = sort_by_created_at(
        [r for r in db.return_cases.values() if r["entry_id"] == entry_id]
    )
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/ach/ach-entries/<entry_id>/close", methods=["POST"])
@require_roles("OriginatorOps", "OdfiOperations")
def close_entry(entry_id: str, _user_id: str, _role: str):
    entry = get_entry_or_404(entry_id)
    # Ownership applies to the OriginatorOps caller only.
    if _role == "OriginatorOps":
        require_entry_ownership(entry, _user_id)
    # State (p6): close is allowed from SETTLED or RETURNED.
    if entry["status"] not in ("SETTLED", "RETURNED"):
        raise_err(ERR_ENTRY_NOT_RETURNED, "Close requires SETTLED or RETURNED")

    entry["status"] = "CLOSED"
    touch(entry)
    # Any OPEN ReturnCase on the entry -> FINAL (terminal).
    for rc in sort_by_created_at(list(db.return_cases.values())):
        if rc["entry_id"] == entry["id"] and rc["disposition"] == "OPEN":
            rc["disposition"] = "FINAL"
            touch(rc)
    return success_object(entry)
