"""OvertimeFeeRecord — tiered pricing, payment cascade, refunds, waivers."""

from clock import iso, now, parse_iso
from constants import (
    FREE_HOURS,
    TIER1_END_HOURS,
    TIER2_END_HOURS,
    TIER1_RATE_CENTS,
    TIER2_RATE_CENTS,
    TIER3_RATE_CENTS,
    FEE_CAP_CENTS,
)
from db import DB, new_id
from errors import APIError
from services.audit import append_audit
from services.util import stamp_create, stamp_update


def compute_fee_cents(deposited_at_iso: str, cutoff_at_iso: str, fee_waived: bool) -> int:
    if fee_waived:
        return 0
    deposited = parse_iso(deposited_at_iso)
    cutoff = parse_iso(cutoff_at_iso)
    seconds = (cutoff - deposited).total_seconds()
    if seconds < 0:
        seconds = 0
    elapsed_hours = int(seconds // 3600)
    tier1 = max(0, min(elapsed_hours - FREE_HOURS, TIER1_END_HOURS - FREE_HOURS))
    tier2 = max(0, min(elapsed_hours - TIER1_END_HOURS, TIER2_END_HOURS - TIER1_END_HOURS))
    tier3 = max(0, elapsed_hours - TIER2_END_HOURS)
    raw_cents = tier1 * TIER1_RATE_CENTS + tier2 * TIER2_RATE_CENTS + tier3 * TIER3_RATE_CENTS
    return min(raw_cents, FEE_CAP_CENTS)


def serialize_fee(r: dict) -> dict:
    return {
        "id": r["id"],
        "parcel_id": r.get("parcel_id"),
        "variant": r.get("variant"),
        "cutoff_at": r.get("cutoff_at"),
        "amount_cents": r.get("amount_cents"),
        "payment_status": r.get("payment_status"),
        "payment_external_id": r.get("payment_external_id"),
        "created_at": r.get("created_at"),
        "updated_at": r.get("updated_at"),
        "version": r.get("version", 0),
    }


def create_fee_record(parcel_id: str, variant: str, cutoff_at_iso: str,
                      amount_cents: int, payment_status: str = "UNPAID") -> dict:
    rid = new_id()
    base = stamp_create()
    record = {
        "id": rid,
        "parcel_id": parcel_id,
        "variant": variant,
        "cutoff_at": cutoff_at_iso,
        "amount_cents": amount_cents,
        "payment_status": payment_status,
        "payment_external_id": None,
        **base,
    }
    DB.fee_records[rid] = record
    DB.parcel_fees.setdefault(parcel_id, []).append(rid)
    return record


def latest_provisional(parcel_id: str):
    fees = [DB.fee_records[fid] for fid in DB.parcel_fees.get(parcel_id, [])
            if DB.fee_records[fid].get("variant") == "PROVISIONAL"]
    if not fees:
        return None
    fees.sort(key=lambda f: f.get("created_at") or "")
    return fees[-1]


def latest_final(parcel_id: str):
    fees = [DB.fee_records[fid] for fid in DB.parcel_fees.get(parcel_id, [])
            if DB.fee_records[fid].get("variant") == "FINAL"]
    if not fees:
        return None
    fees.sort(key=lambda f: f.get("created_at") or "")
    return fees[-1]


def latest_fee(parcel_id: str):
    fees = [DB.fee_records[fid] for fid in DB.parcel_fees.get(parcel_id, [])]
    if not fees:
        return None
    fees.sort(key=lambda f: f.get("created_at") or "")
    return fees[-1]


def all_parcel_fees(parcel_id: str):
    fees = [DB.fee_records[fid] for fid in DB.parcel_fees.get(parcel_id, [])]
    fees.sort(key=lambda f: f.get("created_at") or "")
    return fees
