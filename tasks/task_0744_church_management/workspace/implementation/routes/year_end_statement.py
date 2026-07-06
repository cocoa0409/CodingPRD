"""YearEndStatement endpoints."""

from flask import Blueprint, request

import db
from common import (
    require_role, get_json_body, stamp_common_create, bump,
    success, must_exist, get_pagination, paginate_list, parse_iso_date,
    clock_now_iso, clock_now_dt, parse_iso8601, format_iso8601,
)
from errors import (
    raise_err, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_NOT_FOUND,
    ERR_STATEMENT_TIMING, ERR_STATEMENT_VARIANT_INVALID, ERR_FORBIDDEN,
)
from datetime import datetime, timezone

bp = Blueprint("year_end_statements", __name__)


def _compute_totals(member_id, tax_year, variant):
    candidates = []
    for d in db.donations.values():
        if d.get("member_id") != member_id:
            continue
        if not d.get("is_tax_deductible", True):
            continue
        try:
            year = parse_iso_date(d["donation_date"]).year
        except Exception:
            continue
        if year != tax_year:
            continue
        # Exclude split-child rows so we don't double-count with parents (parents carry the true
        # aggregate deductible amount for the donor; children just record pledge attribution).
        if d.get("is_split_child"):
            continue
        candidates.append(d)

    included = []
    if variant == "PROVISIONAL":
        for d in candidates:
            if d.get("status") in ("PENDING", "POSTED"):
                included.append(d)
    else:
        # FINAL: status == POSTED AND posted_at <= (Y+1)-01-15T00:00:00Z
        cutoff = datetime(tax_year + 1, 1, 15, 0, 0, 0, tzinfo=timezone.utc)
        for d in candidates:
            if d.get("status") != "POSTED":
                continue
            pa = d.get("posted_at")
            if pa is None:
                continue
            try:
                pa_dt = parse_iso8601(pa)
            except Exception:
                continue
            if pa_dt <= cutoff:
                included.append(d)
    total = sum(d["amount_cents"] for d in included)
    return total, len(included)


@bp.route("/year-end-statements", methods=["POST"])
def create_statement():
    require_role({"FinanceAdmin", "PlatformAdmin"})
    body = get_json_body()
    for k in ("member_id", "tax_year", "variant"):
        if k not in body or body[k] is None:
            raise_err(ERR_INVALID_REQUEST, f"{k} is required")
    if not isinstance(body["tax_year"], int) or isinstance(body["tax_year"], bool):
        raise_err(ERR_INVALID_REQUEST, "tax_year must be an integer")
    if body["variant"] not in ("PROVISIONAL", "FINAL"):
        raise_err(ERR_INVALID_REQUEST, "variant must be PROVISIONAL or FINAL")

    member = db.members.get(body["member_id"])
    if member is None:
        raise_err(ERR_NOT_FOUND, "member_id not found")

    tax_year = body["tax_year"]
    variant = body["variant"]
    now = clock_now_dt()

    # Rung 12: statement timing.
    if variant == "FINAL":
        cutoff = datetime(tax_year + 1, 1, 16, 0, 0, 0, tzinfo=timezone.utc)
        if now < cutoff:
            raise_err(ERR_STATEMENT_TIMING, "FINAL statement may only be created on or after Jan 16 of the following year")
    else:
        # PROVISIONAL: may be created any time during or after the target tax year.
        start_of_year = datetime(tax_year, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        if now < start_of_year:
            raise_err(ERR_STATEMENT_TIMING, "PROVISIONAL statement may only be created during or after tax_year")

    total, count = _compute_totals(member["id"], tax_year, variant)

    rec = {
        "member_id": member["id"],
        "tax_year": tax_year,
        "variant": variant,
        "total_deductible_cents": total,
        "donation_count": count,
        "status": "DRAFT",
        "issued_at": None,
    }
    stamp_common_create(rec)
    db.year_end_statements[rec["id"]] = rec
    return success(rec, 201)


@bp.route("/year-end-statements/<sid>", methods=["GET"])
def get_statement(sid):
    role, user_id = require_role({"FinanceAdmin", "Member", "PlatformAdmin"})
    rec = must_exist(db.year_end_statements, sid, "YearEndStatement")
    if role == "Member" and rec["member_id"] != user_id:
        raise_err(ERR_FORBIDDEN, "Member may only view their own statements")
    return success(rec, 200)


@bp.route("/year-end-statements/<sid>/issue", methods=["POST"])
def issue_statement(sid):
    require_role({"FinanceAdmin", "PlatformAdmin"})
    rec = must_exist(db.year_end_statements, sid, "YearEndStatement")
    if rec["status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE, "statement must be DRAFT to issue")
    if rec["variant"] != "FINAL":
        raise_err(ERR_STATEMENT_VARIANT_INVALID, "PROVISIONAL statements cannot be ISSUED")
    rec["status"] = "ISSUED"
    rec["issued_at"] = clock_now_iso()
    bump(rec)
    return success(rec, 200)


@bp.route("/year-end-statements/<sid>/void", methods=["POST"])
def void_statement(sid):
    require_role({"FinanceAdmin", "PlatformAdmin"})
    rec = must_exist(db.year_end_statements, sid, "YearEndStatement")
    if rec["status"] != "ISSUED":
        raise_err(ERR_INVALID_STATE, "statement must be ISSUED to void")
    rec["status"] = "VOIDED"
    bump(rec)
    return success(rec, 200)


@bp.route("/year-end-statements/<sid>/regenerate", methods=["POST"])
def regenerate_statement(sid):
    require_role({"FinanceAdmin", "PlatformAdmin"})
    rec = must_exist(db.year_end_statements, sid, "YearEndStatement")
    if rec["status"] != "VOIDED":
        raise_err(ERR_INVALID_STATE, "statement must be VOIDED to regenerate")
    total, count = _compute_totals(rec["member_id"], rec["tax_year"], rec["variant"])
    rec["total_deductible_cents"] = total
    rec["donation_count"] = count
    rec["status"] = "DRAFT"
    rec["issued_at"] = None
    bump(rec)
    return success(rec, 200)


@bp.route("/year-end-statements", methods=["GET"])
def list_statements():
    role, user_id = require_role({"FinanceAdmin", "Member", "PlatformAdmin"})
    limit, offset = get_pagination()
    items = list(db.year_end_statements.values())
    if role == "Member":
        items = [s for s in items if s["member_id"] == user_id]
    for k in ("member_id", "status"):
        v = request.args.get(k)
        if v:
            items = [s for s in items if s.get(k) == v]
    tax_year = request.args.get("tax_year")
    if tax_year is not None:
        try:
            ty = int(tax_year)
            items = [s for s in items if s.get("tax_year") == ty]
        except (TypeError, ValueError):
            raise_err(ERR_INVALID_REQUEST, "tax_year must be an integer")
    page, meta = paginate_list(items, limit, offset)
    return success(page, 200, meta_extra=meta)
