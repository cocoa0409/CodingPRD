"""Lot lifecycle, registration, announcement, withdrawal — PRD §3.1."""
from __future__ import annotations

from typing import Any

from datetime import timedelta

from ..audit import emit_audit, emit_system_audit
from ..clock import now_dt, parse_iso
from ..constants import (
    ASSET_PROFILES,
    ENCUMBRANCE_KINDS,
    MAX_ROUND_NUMBER,
    STATUTORY_NOTICE_DAYS,
)
from ..errors import ApiError
from ..store import bump_version, common_fields_create, get_store, now_iso
from .auctions import create_auction_row, deposit_amount_calc_for
from .calculations import starting_price_first, starting_price_reauction


def _validate_encumbrances(items: Any) -> list[dict[str, Any]]:
    if items is None:
        return []
    if not isinstance(items, list):
        raise ApiError("ERR_VALIDATION", "encumbrances must be an array.")
    out = []
    for entry in items:
        if not isinstance(entry, dict):
            raise ApiError("ERR_VALIDATION", "Each encumbrance must be an object.")
        kind = entry.get("kind")
        desc = entry.get("description", "")
        if kind not in ENCUMBRANCE_KINDS:
            raise ApiError("ERR_VALIDATION", f"encumbrance.kind must be one of {sorted(ENCUMBRANCE_KINDS)}.")
        out.append({"kind": kind, "description": desc})
    return out


def create_lot(body: dict[str, Any]) -> dict[str, Any]:
    """POST /lots — register a new lot and spawn round-1 Auction."""
    store = get_store()

    # ----- Field-level validation -----
    court_order_no = body.get("court_order_no")
    if not isinstance(court_order_no, str) or not court_order_no.strip():
        raise ApiError("ERR_VALIDATION", "court_order_no must be a non-empty string.")
    asset_profile = body.get("asset_profile")
    if asset_profile not in ASSET_PROFILES:
        raise ApiError(
            "ERR_VALIDATION",
            f"asset_profile must be one of {sorted(ASSET_PROFILES)}.",
        )
    assessment_value_cents = body.get("assessment_value_cents")
    if (
        isinstance(assessment_value_cents, bool)
        or not isinstance(assessment_value_cents, int)
        or assessment_value_cents < 1
    ):
        raise ApiError("ERR_VALIDATION", "assessment_value_cents must be a positive integer.")
    report_uri = body.get("assessment_report_uri")
    if not isinstance(report_uri, str) or not report_uri.strip():
        raise ApiError("ERR_VALIDATION", "assessment_report_uri must be a non-empty string.")

    encumbrances = _validate_encumbrances(body.get("encumbrances"))

    for required in ("auction_scheduled_start_at", "inspection_window_start_at", "inspection_window_end_at"):
        if not body.get(required):
            raise ApiError("ERR_VALIDATION", f"{required} required.")
    try:
        scheduled_start = parse_iso(body["auction_scheduled_start_at"])
        insp_start = parse_iso(body["inspection_window_start_at"])
        insp_end = parse_iso(body["inspection_window_end_at"])
    except ValueError as exc:
        raise ApiError("ERR_VALIDATION", str(exc))

    # Inspection window must precede auction
    if insp_end >= scheduled_start:
        raise ApiError(
            "ERR_INSPECTION_OVERLAPS_AUCTION",
            "inspection_window_end_at must be strictly before auction_scheduled_start_at.",
        )
    if insp_start >= insp_end:
        raise ApiError(
            "ERR_VALIDATION",
            "inspection_window_start_at must be strictly before inspection_window_end_at.",
        )

    # Uniqueness on court_order_no
    for lot in store.lots.values():
        if lot.get("court_order_no") == court_order_no:
            raise ApiError("ERR_DUPLICATE", f"court_order_no already exists: {court_order_no}")

    # ----- Optional auction-config inputs supplied at lot-registration time -----
    deposit_mode = body.get("deposit_mode", "PERCENT")
    if deposit_mode not in ("FIXED", "PERCENT"):
        raise ApiError("ERR_VALIDATION", "deposit_mode must be FIXED or PERCENT.")
    deposit_fixed_cents = body.get("deposit_fixed_cents")
    deposit_percent_bps = body.get("deposit_percent_bps")
    bid_cap_cents = body.get("bid_cap_cents")
    deposit_deadline_at = body.get("deposit_deadline_at")
    payment_deadline_days = body.get("payment_deadline_days", 30)
    scheduled_end_at = body.get("scheduled_end_at")
    soft_close_window_seconds = body.get("soft_close_window_seconds", 300)
    soft_close_extension_seconds = body.get("soft_close_extension_seconds", 300)

    if not isinstance(payment_deadline_days, int) or payment_deadline_days < 1:
        raise ApiError("ERR_VALIDATION", "payment_deadline_days must be an integer >= 1.")
    if not isinstance(soft_close_window_seconds, int) or soft_close_window_seconds < 1:
        raise ApiError("ERR_VALIDATION", "soft_close_window_seconds must be >= 1.")
    if not isinstance(soft_close_extension_seconds, int) or soft_close_extension_seconds < 1:
        raise ApiError("ERR_VALIDATION", "soft_close_extension_seconds must be >= 1.")

    # Default scheduled_end = scheduled_start + 24h if not provided
    if scheduled_end_at is None:
        scheduled_end_dt = scheduled_start + timedelta(hours=24)
        scheduled_end_iso = scheduled_end_dt.isoformat().replace("+00:00", "Z")
    else:
        try:
            parse_iso(scheduled_end_at)
        except ValueError as exc:
            raise ApiError("ERR_VALIDATION", str(exc))
        scheduled_end_iso = scheduled_end_at

    if deposit_deadline_at is None:
        deposit_deadline_iso = body["auction_scheduled_start_at"]
    else:
        try:
            parse_iso(deposit_deadline_at)
        except ValueError as exc:
            raise ApiError("ERR_VALIDATION", str(exc))
        deposit_deadline_iso = deposit_deadline_at

    # ----- Build the Lot row -----
    cf = common_fields_create()
    lot = {
        **cf,
        "court_order_no": court_order_no,
        "asset_profile": asset_profile,
        "assessment_value_cents": int(assessment_value_cents),
        "assessment_report_uri": report_uri,
        "encumbrances": encumbrances,
        "status": "REGISTERED",
        "announcement_published_at": None,
        "auction_scheduled_start_at": body["auction_scheduled_start_at"],
        "inspection_window_start_at": body["inspection_window_start_at"],
        "inspection_window_end_at": body["inspection_window_end_at"],
        "round_number": 1,
    }
    store.lots[lot["id"]] = lot

    # Seed inspection windows
    store.inspection_windows.setdefault(lot["id"], []).append(
        {"start_at": body["inspection_window_start_at"], "end_at": body["inspection_window_end_at"]}
    )

    # ----- Spawn round-1 Auction -----
    starting_price = starting_price_first(int(assessment_value_cents))
    create_auction_row(
        lot_id=lot["id"],
        round_number=1,
        starting_price_cents=starting_price,
        bid_cap_cents=bid_cap_cents,
        deposit_mode=deposit_mode,
        deposit_fixed_cents=deposit_fixed_cents,
        deposit_percent_bps=deposit_percent_bps,
        deposit_deadline_at=deposit_deadline_iso,
        payment_deadline_days=int(payment_deadline_days),
        scheduled_end_at=scheduled_end_iso,
        soft_close_window_seconds=int(soft_close_window_seconds),
        soft_close_extension_seconds=int(soft_close_extension_seconds),
        scheduled_start_at=body["auction_scheduled_start_at"],
    )
    return lot


def add_inspection_window(lot_id: str, body: dict[str, Any]) -> dict[str, Any]:
    store = get_store()
    lot = store.lots.get(lot_id)
    if lot is None:
        raise ApiError("ERR_NOT_FOUND", f"Lot {lot_id} not found.")

    start_at = body.get("start_at")
    end_at = body.get("end_at")
    if not start_at or not end_at:
        raise ApiError("ERR_VALIDATION", "start_at and end_at required.")
    try:
        start_dt = parse_iso(start_at)
        end_dt = parse_iso(end_at)
    except ValueError as exc:
        raise ApiError("ERR_VALIDATION", str(exc))
    if start_dt >= end_dt:
        raise ApiError("ERR_VALIDATION", "start_at must precede end_at.")

    # Check overlap (closed-interval semantics — adjacency counts as overlap)
    windows = store.inspection_windows.setdefault(lot_id, [])
    for w in windows:
        ws = parse_iso(w["start_at"])
        we = parse_iso(w["end_at"])
        # Overlap if start <= we AND end >= ws (closed)
        if not (end_dt < ws or start_dt > we):
            raise ApiError(
                "ERR_INSPECTION_WINDOW_CONFLICT",
                "Inspection windows overlap or touch.",
            )
    windows.append({"start_at": start_at, "end_at": end_at})

    bump_version(lot)
    return lot


def announce_lot(lot_id: str) -> dict[str, Any]:
    store = get_store()
    lot = store.lots.get(lot_id)
    if lot is None:
        raise ApiError("ERR_NOT_FOUND", f"Lot {lot_id} not found.")

    if lot["status"] != "REGISTERED":
        raise ApiError("ERR_INVALID_STATE", f"Cannot announce a lot in status {lot['status']}.")

    # Find the sibling Auction for current round_number
    current_round = int(lot.get("round_number") or 1)
    sibling = None
    for au in store.auctions.values():
        if au.get("lot_id") == lot_id and int(au.get("round_number") or 0) == current_round:
            sibling = au
            break
    if sibling is None:
        raise ApiError("ERR_INVALID_STATE", "No sibling Auction in SCHEDULED status.")
    if sibling.get("status") != "SCHEDULED":
        raise ApiError(
            "ERR_INVALID_STATE",
            f"Sibling Auction status must be SCHEDULED, got {sibling.get('status')}.",
        )

    # Statutory notice: scheduled_start - now >= 15 days
    try:
        scheduled_start = parse_iso(sibling["scheduled_start_at"])
    except (KeyError, ValueError):
        raise ApiError("ERR_VALIDATION", "Auction scheduled_start_at missing or invalid.")
    delta = scheduled_start - now_dt()
    if delta.total_seconds() < STATUTORY_NOTICE_DAYS * 86400:
        raise ApiError(
            "ERR_STATUTORY_NOTICE_INSUFFICIENT",
            f"Announcement must precede auction start by at least {STATUTORY_NOTICE_DAYS} days.",
        )

    # Pin deposit_amount_cents via deposit_amount_calc
    deposit_amount_calc_for(sibling)
    bump_version(sibling)

    lot["announcement_published_at"] = now_iso()
    lot["status"] = "ANNOUNCED"
    bump_version(lot)
    return lot


def withdraw_lot(lot_id: str, reason: str | None = None) -> dict[str, Any]:
    store = get_store()
    lot = store.lots.get(lot_id)
    if lot is None:
        raise ApiError("ERR_NOT_FOUND", f"Lot {lot_id} not found.")
    if lot["status"] != "REGISTERED":
        raise ApiError("ERR_INVALID_STATE", f"Cannot withdraw a lot in status {lot['status']}.")

    for au in store.auctions.values():
        if au.get("lot_id") == lot_id and au.get("status") in {"LIVE", "SOLD"}:
            raise ApiError(
                "ERR_INVALID_STATE",
                "Cannot withdraw a lot with LIVE or SOLD auction.",
            )

    lot["status"] = "WITHDRAWN"
    bump_version(lot)
    return lot


def bubble_lot_to_auctioned(lot_id: str) -> None:
    """Cascade: when sibling Auction reaches SOLD or UNSOLD, Lot.status → AUCTIONED."""
    store = get_store()
    lot = store.lots.get(lot_id)
    if lot is None:
        return
    if lot["status"] == "ANNOUNCED":
        lot["status"] = "AUCTIONED"
        bump_version(lot)


def trigger_reauction(lot_id: str, *, reason: str) -> dict[str, Any] | None:
    """Re-auction cascade. Returns the new Auction row or None if max round reached."""
    store = get_store()
    lot = store.lots.get(lot_id)
    if lot is None:
        return None

    current_round = int(lot.get("round_number") or 1)
    if current_round >= MAX_ROUND_NUMBER:
        raise ApiError(
            "ERR_REAUCTION_LIMIT_REACHED",
            f"Lot.round_number already at {MAX_ROUND_NUMBER}; no further re-auction allowed.",
        )

    # Find prior round's auction to read its starting_price
    prior = None
    for au in store.auctions.values():
        if au.get("lot_id") == lot_id and int(au.get("round_number") or 0) == current_round:
            prior = au
            break
    if prior is None:
        raise ApiError("ERR_INVALID_STATE", "No prior auction to re-auction from.")

    lot["round_number"] = current_round + 1
    lot["status"] = "ANNOUNCED"
    new_starting_price = starting_price_reauction(int(prior["starting_price_cents"]))
    new_auction = create_auction_row(
        lot_id=lot_id,
        round_number=current_round + 1,
        starting_price_cents=new_starting_price,
        bid_cap_cents=prior.get("bid_cap_cents"),
        deposit_mode=prior["deposit_mode"],
        deposit_fixed_cents=prior.get("deposit_fixed_cents"),
        deposit_percent_bps=prior.get("deposit_percent_bps"),
        deposit_deadline_at=prior["deposit_deadline_at"],
        payment_deadline_days=int(prior["payment_deadline_days"]),
        scheduled_end_at=prior["scheduled_end_at"],
        soft_close_window_seconds=int(prior["soft_close_window_seconds"]),
        soft_close_extension_seconds=int(prior["soft_close_extension_seconds"]),
        scheduled_start_at=prior["scheduled_start_at"],
    )
    # Pin deposit_amount immediately on new sibling
    deposit_amount_calc_for(new_auction)
    bump_version(new_auction)
    bump_version(lot)
    emit_system_audit(
        "REAUCTION_TRIGGERED",
        subject_entity="Lot",
        subject_id=lot_id,
        payload={"reason": reason, "new_round_number": current_round + 1, "new_auction_id": new_auction["id"]},
    )
    return new_auction
