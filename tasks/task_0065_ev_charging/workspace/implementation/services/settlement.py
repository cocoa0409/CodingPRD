"""Session and operator settlement calculations."""

from __future__ import annotations

from decimal import Decimal

import db
from errors import raise_error
from services.money import bps_apply, cents_from_milli, round_half_up


PLATFORM_BASE_FEE_BPS = 500
ROAMING_PARTNER_BPS = 1500


def compute_window_energy(session_id: str) -> tuple[int, int, int]:
    """Walk the session's curve points in sampled_at order and aggregate
    per-window deltas (peak/flat/valley) in milli-kWh. Returns (peak, flat,
    valley)."""
    points = [
        p for p in db.curve_points.values() if p["session_id"] == session_id
    ]
    # sampled_at is monotonically increasing per validation; sort for safety.
    points.sort(key=lambda p: (p["sampled_at"], p["_seq"]))

    peak = 0
    flat = 0
    valley = 0
    prev_cum = 0
    for p in points:
        cum = p["cumulative_energy_milli"]
        delta = cum - prev_cum
        if delta < 0:
            delta = 0  # defensive
        tag = p["window_tag"]
        if tag == "PEAK":
            peak += delta
        elif tag == "VALLEY":
            valley += delta
        else:
            flat += delta
        prev_cum = cum
    return peak, flat, valley


def compute_session_fees(session: dict, until_point_count: int | None = None) -> dict:
    """Compute electricity / service / tax / total cents for a session.

    If until_point_count is set, only the first N curve points (sorted by
    sampled_at) are considered — used for provisional estimates.
    """
    pricing_version = db.pricing_versions.get(session.get("pricing_version_id"))
    if pricing_version is None:
        # estimate may be requested before start: zero out
        return {
            "electricity_fee_cents": 0,
            "service_fee_cents": 0,
            "tax_cents": 0,
            "total_cents": 0,
            "peak_milli": 0,
            "flat_milli": 0,
            "valley_milli": 0,
        }

    points = [
        p for p in db.curve_points.values() if p["session_id"] == session["id"]
    ]
    points.sort(key=lambda p: (p["sampled_at"], p["_seq"]))
    if until_point_count is not None:
        points = points[:until_point_count]

    peak = flat = valley = 0
    prev_cum = 0
    for p in points:
        cum = p["cumulative_energy_milli"]
        delta = cum - prev_cum
        if delta < 0:
            delta = 0
        tag = p["window_tag"]
        if tag == "PEAK":
            peak += delta
        elif tag == "VALLEY":
            valley += delta
        else:
            flat += delta
        prev_cum = cum

    total_milli = peak + flat + valley

    # Step B: electricity fee — round per window then sum.
    electricity_fee_cents = (
        cents_from_milli(peak, pricing_version["peak_rate_per_kwh_cents"])
        + cents_from_milli(flat, pricing_version["flat_rate_per_kwh_cents"])
        + cents_from_milli(valley, pricing_version["valley_rate_per_kwh_cents"])
    )

    # Step C: service fee with stacked discounts.
    member = db.members.get(session["member_id"]) or {}
    tier = member.get("tier", "BASIC")
    tier_disc_map = pricing_version.get("tier_service_fee_discount_bps") or {}
    tier_disc = int(tier_disc_map.get(tier, 0))

    promo_disc = 0
    promo_id = session.get("promo_activity_id")
    if promo_id and promo_id in db.promo_activities:
        promo = db.promo_activities[promo_id]
        if tier in promo.get("applies_to_tiers", []):
            promo_disc = int(promo["service_fee_discount_bps"])

    base_service_cents = cents_from_milli(
        total_milli, pricing_version["service_fee_per_kwh_cents"]
    )
    effective_factor = (10_000 - tier_disc) * (10_000 - promo_disc)  # bps^2
    service_fee_cents = round_half_up(
        Decimal(base_service_cents) * Decimal(effective_factor) / Decimal(100_000_000)
    )

    # Step D: tax.
    tax_cents = round_half_up(
        Decimal(electricity_fee_cents + service_fee_cents)
        * Decimal(int(pricing_version["tax_bps"]))
        / Decimal(10_000)
    )
    total_cents = electricity_fee_cents + service_fee_cents + tax_cents

    return {
        "electricity_fee_cents": electricity_fee_cents,
        "service_fee_cents": service_fee_cents,
        "tax_cents": tax_cents,
        "total_cents": total_cents,
        "peak_milli": peak,
        "flat_milli": flat,
        "valley_milli": valley,
    }


def compute_operator_allocation(session: dict, fees: dict) -> dict:
    """Allocate the net (excluding tax) across the four counterparties.

    Returns a dict keyed by counterparty_kind with positive cents amounts.
    Raises ERR_SETTLEMENT_OVER_ALLOCATION if the combined bps exceeds 10000.
    """
    pile = db.piles[session["pile_id"]]
    station = db.stations[pile["station_id"]]
    member = db.members[session["member_id"]]

    revenue_share_bps = int(station["revenue_share_bps"])
    is_roaming = member["home_operator_id"] != station["operator_id"]

    # Over-allocation safety guard
    combined = revenue_share_bps + PLATFORM_BASE_FEE_BPS + (
        ROAMING_PARTNER_BPS if is_roaming else 0
    )
    if combined > 10_000:
        raise_error(
            "ERR_SETTLEMENT_OVER_ALLOCATION",
            "combined revenue/platform/roaming shares exceed 100%",
        )

    net_cents = fees["electricity_fee_cents"] + fees["service_fee_cents"]
    tax_cents = fees["tax_cents"]

    roaming_cents = bps_apply(net_cents, ROAMING_PARTNER_BPS) if is_roaming else 0
    after_roaming = net_cents - roaming_cents
    platform_cents = bps_apply(after_roaming, PLATFORM_BASE_FEE_BPS)
    after_platform = after_roaming - platform_cents
    station_owner_cents = bps_apply(after_platform, revenue_share_bps)

    return {
        "STATION_OWNER_SHARE": {
            "amount_cents": station_owner_cents,
            "operator_id": station["station_owner_id"],
            "tax_cents": 0,
        },
        "PLATFORM_SERVICE_FEE": {
            "amount_cents": platform_cents,
            "operator_id": station["operator_id"],
            "tax_cents": 0,
        },
        "ROAMING_PARTNER": {
            "amount_cents": roaming_cents,
            "operator_id": member["home_operator_id"],
            "tax_cents": 0,
            "applies": is_roaming,
        },
        "TAX_AUTHORITY": {
            "amount_cents": tax_cents,
            "operator_id": station["operator_id"],
            "tax_cents": tax_cents,
        },
    }


def write_ledger_entry(session_id: str, operator_id: str, counterparty_kind: str,
                       amount_cents: int, reason: str, tax_cents: int = 0) -> dict:
    record = {
        "session_id": session_id,
        "operator_id": operator_id,
        "counterparty_kind": counterparty_kind,
        "amount_cents": int(amount_cents),
        "tax_cents": int(tax_cents),
        "reason": reason,
    }
    db.append_only_record(record)
    db.ledger_entries[record["id"]] = record
    return record


def write_settlement_ledger(session: dict, fees: dict, allocation: dict,
                            reason: str, sign: int) -> list[dict]:
    """Write one ledger row per counterparty with the given sign (+1 or -1).

    ROAMING_PARTNER row is only written when the session is roaming.
    """
    rows = []
    so = allocation["STATION_OWNER_SHARE"]
    plat = allocation["PLATFORM_SERVICE_FEE"]
    roaming = allocation["ROAMING_PARTNER"]
    tax = allocation["TAX_AUTHORITY"]

    rows.append(write_ledger_entry(
        session["id"], so["operator_id"], "STATION_OWNER_SHARE",
        sign * so["amount_cents"], reason,
    ))
    rows.append(write_ledger_entry(
        session["id"], plat["operator_id"], "PLATFORM_SERVICE_FEE",
        sign * plat["amount_cents"], reason,
    ))
    if roaming.get("applies"):
        rows.append(write_ledger_entry(
            session["id"], roaming["operator_id"], "ROAMING_PARTNER",
            sign * roaming["amount_cents"], reason,
        ))
    rows.append(write_ledger_entry(
        session["id"], tax["operator_id"], "TAX_AUTHORITY",
        sign * tax["amount_cents"], reason, tax_cents=tax["tax_cents"],
    ))
    return rows


def settle_session(session: dict) -> None:
    """SETTLING -> SETTLED: compute fees, debit wallet, write ledger rows."""
    fees = compute_session_fees(session)
    allocation = compute_operator_allocation(session, fees)

    session["peak_kwh_milli"] = fees["peak_milli"]
    session["flat_kwh_milli"] = fees["flat_milli"]
    session["valley_kwh_milli"] = fees["valley_milli"]
    session["electricity_fee_cents"] = fees["electricity_fee_cents"]
    session["service_fee_cents"] = fees["service_fee_cents"]
    session["tax_cents"] = fees["tax_cents"]
    session["total_cents"] = fees["total_cents"]
    session["status"] = "SETTLED"
    db.bump(session)

    member = db.members.get(session["member_id"])
    if member is not None:
        member["wallet_balance_cents"] = max(
            0, int(member["wallet_balance_cents"]) - int(fees["total_cents"])
        )
        db.bump(member)

    write_settlement_ledger(session, fees, allocation, "SESSION_SETTLE", sign=+1)


def reverse_session(session: dict) -> dict:
    """Refund-reversal: re-compute allocation from CURRENT station fields and
    write four reversal ledger rows with negative sign. Returns the operator
    allocation used."""
    fees = {
        "electricity_fee_cents": session["electricity_fee_cents"],
        "service_fee_cents": session["service_fee_cents"],
        "tax_cents": session["tax_cents"],
    }
    allocation = compute_operator_allocation(session, fees)
    write_settlement_ledger(session, fees, allocation, "REFUND_REVERSAL", sign=-1)
    # Adjust session.total_cents to zero out
    session["total_cents"] = 0
    db.bump(session)
    return allocation
