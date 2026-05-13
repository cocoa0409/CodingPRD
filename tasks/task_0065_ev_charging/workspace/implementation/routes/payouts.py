"""Payout endpoints."""

from flask import Blueprint, g, request

import db
from clock import parse_iso
from errors import raise_error
from middleware import require_roles
from response import paginated, success
from services import settlement
from validators import (
    check_version,
    get_pagination,
    paginate_list,
    parse_json_body,
    require_str,
)


bp = Blueprint("payouts", __name__)


def _recompute_payout_totals(payout: dict) -> None:
    operator_id = payout["operator_id"]
    try:
        ps = parse_iso(payout["period_start"])
        pe = parse_iso(payout["period_end"])
    except Exception:
        return
    gross = 0
    reversal = 0
    for entry in db.ledger_entries.values():
        if entry["operator_id"] != operator_id:
            continue
        source_session = db.sessions.get(entry["session_id"])
        if source_session is None or not source_session.get("ended_at"):
            continue
        try:
            ended = parse_iso(source_session["ended_at"])
        except Exception:
            continue
        if not (ps <= ended < pe):
            continue
        amt = int(entry["amount_cents"])
        if amt > 0:
            gross += amt
        if entry["reason"] == "REFUND_REVERSAL" and amt < 0:
            reversal += -amt
    payout["gross_cents"] = gross
    payout["reversal_cents"] = reversal
    payout["net_cents"] = gross - reversal


@bp.post("/payouts")
@require_roles({"PlatformOperator"})
def create_payout():
    body = parse_json_body()
    operator_id = require_str(body, "operator_id")
    if operator_id not in db.operators:
        raise_error("ERR_NOT_FOUND", "operator_id not found")
    period_start = require_str(body, "period_start")
    period_end = require_str(body, "period_end")
    try:
        ps = parse_iso(period_start)
        pe = parse_iso(period_end)
    except Exception:
        raise_error("ERR_VALIDATION", "period_start/end must be ISO 8601")
    if not (pe > ps):
        raise_error("ERR_INVALID_PAYOUT_WINDOW", "period_end must be > period_start")

    record = {
        "operator_id": operator_id,
        "period_start": period_start,
        "period_end": period_end,
        "gross_cents": 0,
        "reversal_cents": 0,
        "net_cents": 0,
        "status": "PENDING",
    }
    db.with_common_fields(record)
    _recompute_payout_totals(record)
    db.payouts[record["id"]] = record
    return success(db.public(record), status=201)


@bp.post("/payouts/<payout_id>/issue")
@require_roles({"PlatformOperator"})
def issue_payout(payout_id: str):
    payout = db.payouts.get(payout_id)
    if payout is None:
        raise_error("ERR_NOT_FOUND", "payout not found")
    body = parse_json_body()
    check_version(body, payout)
    if payout["status"] != "PENDING":
        raise_error("ERR_INVALID_STATE", "payout not in PENDING state")

    # PRD §3.7: If a refund arrived while PENDING, the subsequent issue is
    # rejected with ERR_PAYOUT_PERIOD_DRIFT. The dispatcher sets the flag.
    if payout.get("_drifted_by_refund"):
        raise_error("ERR_PAYOUT_PERIOD_DRIFT", "refund drifted payout since creation")

    # Refresh totals in case ledger changed since draft (e.g. issued in race).
    prev_net = payout["net_cents"]
    _recompute_payout_totals(payout)
    if payout["net_cents"] != prev_net:
        # Defensive: any other source of drift also rejects.
        raise_error("ERR_PAYOUT_PERIOD_DRIFT", "payout net drifted since creation")

    if payout["net_cents"] < 0:
        raise_error("ERR_PAYOUT_NEGATIVE_NET", "payout net is negative")

    payout["status"] = "ISSUED"
    db.bump(payout)

    operator = db.operators.get(payout["operator_id"])
    role_kind = (operator or {}).get("role_kind", "PLATFORM")
    counterparty_kind = {
        "STATION_OWNER": "STATION_OWNER_SHARE",
        "ROAMING_PARTNER": "ROAMING_PARTNER",
        "PLATFORM": "PLATFORM_SERVICE_FEE",
    }.get(role_kind, "PLATFORM_SERVICE_FEE")

    settlement.write_ledger_entry(
        session_id=payout["id"],
        operator_id=payout["operator_id"],
        counterparty_kind=counterparty_kind,
        amount_cents=-int(payout["net_cents"]),
        reason="PAYOUT",
        tax_cents=0,
    )
    return success(db.public(payout))


@bp.get("/payouts/<payout_id>")
@require_roles({"PlatformOperator", "StationOwner"})
def get_payout(payout_id: str):
    payout = db.payouts.get(payout_id)
    if payout is None:
        raise_error("ERR_NOT_FOUND", "payout not found")
    if g.role == "StationOwner" and payout["operator_id"] != g.user_id:
        raise_error("ERR_FORBIDDEN", "not your payout")
    return success(db.public(payout))


@bp.get("/payouts")
@require_roles({"PlatformOperator", "StationOwner"})
def list_payouts():
    operator_id = request.args.get("operator_id")
    status = request.args.get("status")
    limit, offset = get_pagination()
    items = sorted(db.payouts.values(), key=lambda r: r["_seq"])
    if g.role == "StationOwner":
        items = [p for p in items if p["operator_id"] == g.user_id]
    if operator_id:
        items = [p for p in items if p["operator_id"] == operator_id]
    if status:
        items = [p for p in items if p["status"] == status]
    page, total = paginate_list(items, limit, offset)
    return paginated(db.public_list(page), limit, offset, total)
