"""SettlementBatch: aggregations, lock, settle.

Rounding order PINNED:
  partner_share_cents = floor(net_revenue_cents * PARTNER_SHARE_RATIO)
  platform_share_cents = net_revenue_cents - partner_share_cents
"""

import math

from clock import iso, now, parse_iso
from constants import PARTNER_SHARE_RATIO
from db import DB, new_id
from errors import APIError, invalid_request, not_found
from services.audit import append_audit
from services.util import (
    stamp_create,
    stamp_update,
    require_field,
    opt_field,
    check_version,
)


PAYMENT_REQUIRED_STATES = {"PICKUP_PENDING", "PICKED_UP", "LONG_STAY"}


def get_batch(batch_id: str):
    b = DB.settlements.get(batch_id)
    if not b:
        raise not_found(f"SettlementBatch not found: {batch_id}")
    return b


def _partner_machine_ids(partner_id: str):
    return {
        m["id"] for m in DB.locker_machines.values()
        if m.get("partner_id") == partner_id
    }


def _aggregate(b: dict):
    """Recompute gross / refund / net / partner / platform for the batch."""
    if b.get("status") == "LOCKED" or b.get("status") == "SETTLED":
        # Frozen — return persisted values
        return (
            b.get("gross_overtime_revenue_cents", 0),
            b.get("refund_reversal_cents", 0),
            b.get("net_revenue_cents", 0),
            b.get("partner_share_cents", 0),
            b.get("platform_share_cents", 0),
        )

    machines = _partner_machine_ids(b.get("partner_id"))
    period_start = parse_iso(b.get("period_start"))
    period_end = parse_iso(b.get("period_end"))

    gross = 0
    refund = 0
    for r in DB.fee_records.values():
        if r.get("variant") != "FINAL":
            continue
        parcel = DB.parcels.get(r.get("parcel_id"))
        if not parcel or parcel.get("locker_machine_id") not in machines:
            continue
        created = parse_iso(r.get("created_at"))
        if created is None:
            continue
        if r.get("payment_status") == "PAID":
            if period_start <= created < period_end:
                gross += int(r.get("amount_cents") or 0)
        elif r.get("payment_status") == "REFUNDED":
            updated = parse_iso(r.get("updated_at"))
            if updated is not None and period_start <= updated < period_end:
                refund += int(r.get("amount_cents") or 0)
    net = gross - refund
    partner_share = math.floor(net * PARTNER_SHARE_RATIO)
    platform_share = net - partner_share
    return gross, refund, net, partner_share, platform_share


def serialize_batch(b: dict) -> dict:
    g, r, n, ps, pl = _aggregate(b)
    return {
        "id": b["id"],
        "partner_id": b.get("partner_id"),
        "period_start": b.get("period_start"),
        "period_end": b.get("period_end"),
        "gross_overtime_revenue_cents": g,
        "refund_reversal_cents": r,
        "net_revenue_cents": n,
        "partner_share_cents": ps,
        "platform_share_cents": pl,
        "status": b.get("status"),
        "created_at": b.get("created_at"),
        "updated_at": b.get("updated_at"),
        "version": b.get("version", 0),
    }


def create_batch(payload: dict, actor_id: str) -> dict:
    partner_id = require_field(payload, "partner_id")
    period_start = require_field(payload, "period_start")
    period_end = require_field(payload, "period_end")
    # validate datetimes
    try:
        ps = parse_iso(period_start)
        pe = parse_iso(period_end)
    except Exception:
        raise invalid_request("period_start/period_end must be ISO 8601 timestamps")
    if pe <= ps:
        raise invalid_request("period_end must be > period_start")

    rid = new_id()
    base = stamp_create()
    record = {
        "id": rid,
        "partner_id": partner_id,
        "period_start": iso(ps),
        "period_end": iso(pe),
        "status": "DRAFT",
        # frozen fields default to None until lock
        "gross_overtime_revenue_cents": 0,
        "refund_reversal_cents": 0,
        "net_revenue_cents": 0,
        "partner_share_cents": 0,
        "platform_share_cents": 0,
        **base,
    }
    DB.settlements[rid] = record
    return record


def lock_batch(batch_id: str, payload: dict, actor_id: str) -> dict:
    b = get_batch(batch_id)
    check_version(b, opt_field(payload, "version"))
    if b.get("status") == "LOCKED":
        raise APIError("ERR_SETTLEMENT_LOCKED",
                       "Batch is already LOCKED", 409)
    if b.get("status") == "SETTLED":
        raise APIError("ERR_SETTLEMENT_LOCKED",
                       "Batch is already SETTLED", 409)
    pe = parse_iso(b.get("period_end"))
    if pe > now():
        raise APIError("ERR_PERIOD_NOT_CLOSED",
                       "Settlement period has not yet closed", 409)
    # Pending fees in window?
    machines = _partner_machine_ids(b.get("partner_id"))
    ps = parse_iso(b.get("period_start"))
    for r in DB.fee_records.values():
        if r.get("payment_status") != "UNPAID":
            continue
        parcel = DB.parcels.get(r.get("parcel_id"))
        if not parcel or parcel.get("locker_machine_id") not in machines:
            continue
        if parcel.get("status") not in PAYMENT_REQUIRED_STATES:
            continue
        if parcel.get("fee_waived"):
            continue
        if (r.get("amount_cents") or 0) <= 0:
            continue
        created = parse_iso(r.get("created_at"))
        if created is None:
            continue
        if ps <= created < pe:
            raise APIError("ERR_PENDING_FEES_IN_WINDOW",
                           "There are unpaid fees in this window", 409)

    # Freeze totals
    g, r_total, n, partner_share, platform_share = _aggregate(b)
    b["gross_overtime_revenue_cents"] = g
    b["refund_reversal_cents"] = r_total
    b["net_revenue_cents"] = n
    b["partner_share_cents"] = partner_share
    b["platform_share_cents"] = platform_share
    b["status"] = "LOCKED"
    stamp_update(b)
    append_audit("OperationsAdmin", actor_id, "SETTLEMENT_LOCK", "SettlementBatch", b["id"],
                 {"gross": g, "refund": r_total, "net": n,
                  "partner_share": partner_share, "platform_share": platform_share})
    return b


def settle_batch(batch_id: str, payload: dict, actor_id: str) -> dict:
    b = get_batch(batch_id)
    check_version(b, opt_field(payload, "version"))
    if b.get("status") != "LOCKED":
        raise APIError("ERR_PARCEL_STATE_CHANGED",
                       f"Batch must be LOCKED to settle (currently {b.get('status')})", 409)
    b["status"] = "SETTLED"
    stamp_update(b)
    return b


def list_batches(args):
    out = list(DB.settlements.values())
    pid = args.get("partner_id")
    if pid:
        out = [b for b in out if b.get("partner_id") == pid]
    out.sort(key=lambda r: (r.get("created_at") or "", r["id"]))
    return out
