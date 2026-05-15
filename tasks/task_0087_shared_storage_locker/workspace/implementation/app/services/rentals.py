"""Rental business logic — creation, renewal, return, sweep transitions."""
from __future__ import annotations

import copy
from datetime import timedelta
from typing import Any, Optional

from .. import constants
from ..audit import emit_audit_event
from ..auth import current_actor
from ..calculations import (
    deposit_settle_force_clearance,
    deposit_settle_return,
    grace_end,
    insurance_premium_cents,
    overdue_fee_cents,
    rental_fee_cents,
)
from ..clock import add_seconds, format_iso, now_dt, parse_iso
from ..errors import ApiError
from ..store import bump_version, common_fields_create, get_store
from .cabinets import get_cabinet_or_404
from .capacity import recompute_cabinet_capacity
from .compartments import get_nested_compartment, get_compartment_or_404
from .pricing_profiles import find_pricing_profile
from .revenue import emit_revenue_record
from .serializers import serialize_rental
from .validation import (
    require_field,
    require_in,
    require_int,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def get_rental_or_404(rental_id: str) -> dict[str, Any]:
    store = get_store()
    r = store.rentals.get(rental_id)
    if r is None:
        raise ApiError("ERR_NOT_FOUND", f"Rental {rental_id} not found.")
    return r


def _check_version(entity: dict[str, Any], supplied_version: Any) -> None:
    if supplied_version is None:
        return
    if not isinstance(supplied_version, int) or isinstance(supplied_version, bool):
        raise ApiError("ERR_BAD_REQUEST", "version must be an integer.")
    if supplied_version != int(entity.get("version", 0)):
        raise ApiError("ERR_VERSION_CONFLICT", "Resource version mismatch.")


def _ownership_check(rental: dict[str, Any]) -> tuple[str, str]:
    actor_id, actor_role = current_actor()
    if actor_role == "Renter" and rental["renter_id"] != actor_id:
        raise ApiError("ERR_FORBIDDEN", "Renter does not own this rental.")
    return actor_id, actor_role


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


def create_rental(cabinet_id: str, compartment_id: str, body: dict[str, Any]) -> dict[str, Any]:
    store = get_store()
    # Path validation (existence) — leftmost first
    cabinet = get_cabinet_or_404(cabinet_id)
    comp = get_nested_compartment(cabinet_id, compartment_id)

    # Parse + structural validation of body fields
    rental_mode = require_in(require_field(body, "rental_mode"), "rental_mode", constants.RENTAL_MODES)
    billing_units = require_int(require_field(body, "billing_units"), "billing_units", min_value=1)
    unlock_channel = require_in(require_field(body, "unlock_channel"), "unlock_channel", constants.UNLOCK_CHANNELS)
    insurance_tier_raw = body.get("insurance_tier", "NONE")
    insurance_tier = require_in(insurance_tier_raw, "insurance_tier", constants.INSURANCE_TIERS)
    declared_value_cents = body.get("declared_value_cents", 0)
    declared_value_cents = require_int(declared_value_cents, "declared_value_cents", min_value=0)

    # Validation order:
    #  - state legality (compartment fault, cabinet offline, compartment occupancy) -> business safety
    # Compartment fault gating first
    if comp["operational_status"] != "OK":
        raise ApiError("ERR_COMPARTMENT_FAULT", "Compartment is in FAULT.")
    # Cabinet offline gating (only PASSWORD allowed when OFFLINE)
    if cabinet["online_status"] == "OFFLINE" and unlock_channel != "PASSWORD":
        raise ApiError("ERR_CABINET_OFFLINE", "Cabinet is OFFLINE; only PASSWORD allowed.")
    # Compartment occupancy gating
    if comp["occupancy_status"] != "IDLE":
        raise ApiError("ERR_COMPARTMENT_UNAVAILABLE", "Compartment is not IDLE.")
    # PricingProfile must resolve
    profile = find_pricing_profile(comp["size_class"], rental_mode)
    if profile is None:
        raise ApiError(
            "ERR_PRICING_PROFILE_NOT_FOUND",
            f"No PricingProfile for ({comp['size_class']}, {rental_mode}).",
        )
    # Insurance coherence
    if insurance_tier == "NONE" and declared_value_cents != 0:
        raise ApiError("ERR_INVALID_INSURANCE", "NONE tier requires declared_value_cents == 0.")
    if insurance_tier in ("BASIC", "PREMIUM"):
        if declared_value_cents <= 0:
            raise ApiError("ERR_INVALID_INSURANCE", f"{insurance_tier} tier requires declared_value_cents > 0.")
        if declared_value_cents > constants.DECLARED_VALUE_CAP_CENTS:
            raise ApiError(
                "ERR_INVALID_INSURANCE",
                f"declared_value_cents > cap of {constants.DECLARED_VALUE_CAP_CENTS}.",
            )

    actor_id, actor_role = current_actor()

    # Build the rental
    started = now_dt()
    duration = constants.unit_duration_seconds(rental_mode)
    expires = add_seconds(started, billing_units * duration)

    rental = common_fields_create()
    fee = rental_fee_cents(billing_units, profile["unit_price_cents"])
    premium = insurance_premium_cents(insurance_tier, declared_value_cents, billing_units, rental_mode)
    total = fee + premium + int(profile["deposit_cents"])

    rental.update(
        {
            "renter_id": actor_id,
            "compartment_id": compartment_id,
            "cabinet_id": cabinet_id,
            "size_class": comp["size_class"],
            "rental_mode": rental_mode,
            "billing_units": billing_units,
            "unit_price_cents_snapshot": int(profile["unit_price_cents"]),
            "deposit_cents_snapshot": int(profile["deposit_cents"]),
            "grace_minutes_snapshot": int(profile["grace_minutes"]),
            "overdue_rate_snapshot": int(profile["overdue_rate_cents_per_hour"]),
            "forced_clearance_hours_snapshot": int(profile["forced_clearance_hours"]),
            "insurance_tier": insurance_tier,
            "declared_value_cents": declared_value_cents,
            "insurance_premium_cents": premium,
            "rental_fee_cents": fee,
            "total_charged_cents": total,
            "started_at": format_iso(started),
            "original_expires_at": format_iso(expires),
            "current_expires_at": format_iso(expires),
            "ended_at": None,
            "status": "ACTIVE",
            "overdue_fee_cents": 0,
            "deposit_forfeited_cents": 0,
            "deposit_refunded_cents": 0,
            "renewal_count": 0,
            "reminder_sent_at": None,
        }
    )
    store.rentals[rental["id"]] = rental

    # Compartment cascade
    comp["occupancy_status"] = "RENTED"
    comp["active_rental_id"] = rental["id"]
    bump_version(comp)
    recompute_cabinet_capacity(cabinet, bump=True)

    # Revenue: RENTAL_FEE row for the initial fee
    emit_revenue_record(rental, "RENTAL_FEE", fee, occurred_at=rental["started_at"])

    # Audit event
    emit_audit_event(
        event_kind="COMPARTMENT_OPENED",
        subject_type="Compartment",
        subject_id=comp["id"],
        actor_role=actor_role,
        actor_id=actor_id,
        unlock_channel=unlock_channel,
        detail={"rental_id": rental["id"], "trigger": "rental_created"},
    )

    return serialize_rental(rental)


# ---------------------------------------------------------------------------
# Get / List
# ---------------------------------------------------------------------------


def _live_overdue_estimate(rental: dict[str, Any]) -> dict[str, Any]:
    """Return a rental snapshot with overdue_fee_cents live-estimated if OVERDUE."""
    out = copy.deepcopy(rental)
    if out["status"] == "OVERDUE":
        try:
            current_expires_dt = parse_iso(out["current_expires_at"])
        except ValueError:
            return out
        out["overdue_fee_cents"] = overdue_fee_cents(
            current_expires_dt,
            int(out["grace_minutes_snapshot"]),
            int(out["overdue_rate_snapshot"]),
            now_dt(),
        )
    return out


def get_rental(rental_id: str) -> dict[str, Any]:
    rental = get_rental_or_404(rental_id)
    actor_id, actor_role = current_actor()
    if actor_role == "Renter" and rental["renter_id"] != actor_id:
        raise ApiError("ERR_FORBIDDEN", "Renter does not own this rental.")
    return _live_overdue_estimate(rental)


def list_rentals(
    renter_id: Optional[str],
    cabinet_id: Optional[str],
    status: Optional[str],
) -> list[dict[str, Any]]:
    store = get_store()
    actor_id, actor_role = current_actor()
    items = list(store.rentals.values())
    if actor_role == "Renter":
        items = [r for r in items if r["renter_id"] == actor_id]
    if renter_id:
        items = [r for r in items if r["renter_id"] == renter_id]
    if cabinet_id:
        items = [r for r in items if r["cabinet_id"] == cabinet_id]
    if status:
        items = [r for r in items if r["status"] == status]
    items.sort(key=lambda r: (r["created_at"], r["id"]))
    return [_live_overdue_estimate(r) for r in items]


# ---------------------------------------------------------------------------
# Renew
# ---------------------------------------------------------------------------


def renew_rental(rental_id: str, body: dict[str, Any]) -> dict[str, Any]:
    store = get_store()
    rental = get_rental_or_404(rental_id)
    _ownership_check(rental)
    _check_version(rental, body.get("version"))

    if rental["status"] not in ("ACTIVE", "EXPIRING_SOON"):
        raise ApiError(
            "ERR_RENEWAL_NOT_PERMITTED",
            f"Cannot renew rental in status {rental['status']}.",
        )

    comp = store.compartments.get(rental["compartment_id"])
    if comp is None or comp["operational_status"] != "OK":
        raise ApiError("ERR_COMPARTMENT_FAULT", "Compartment is in FAULT.")

    renewal_billing_units = require_int(
        require_field(body, "renewal_billing_units"), "renewal_billing_units", min_value=1
    )

    duration = constants.unit_duration_seconds(rental["rental_mode"])
    current_expires_dt = parse_iso(rental["current_expires_at"])
    new_expires = add_seconds(current_expires_dt, renewal_billing_units * duration)
    rental["current_expires_at"] = format_iso(new_expires)

    increment = renewal_billing_units * int(rental["unit_price_cents_snapshot"])
    rental["rental_fee_cents"] = int(rental["rental_fee_cents"]) + increment
    rental["total_charged_cents"] = int(rental["total_charged_cents"]) + increment
    rental["renewal_count"] = int(rental["renewal_count"]) + 1
    rental["reminder_sent_at"] = None

    if rental["status"] == "EXPIRING_SOON":
        rental["status"] = "ACTIVE"

    bump_version(rental)

    emit_revenue_record(rental, "RENTAL_FEE", increment)

    return serialize_rental(rental)


# ---------------------------------------------------------------------------
# Return
# ---------------------------------------------------------------------------


def return_rental(rental_id: str, body: dict[str, Any]) -> dict[str, Any]:
    store = get_store()
    rental = get_rental_or_404(rental_id)
    _ownership_check(rental)
    _check_version(rental, body.get("version"))

    if rental["status"] not in ("ACTIVE", "EXPIRING_SOON", "OVERDUE"):
        raise ApiError("ERR_INVALID_STATE", f"Cannot return rental in status {rental['status']}.")

    comp = store.compartments.get(rental["compartment_id"])
    if comp is None:
        raise ApiError("ERR_NOT_FOUND", "Compartment not found.")
    if comp["operational_status"] != "OK":
        raise ApiError("ERR_COMPARTMENT_FAULT", "Compartment is in FAULT; cannot retrieve item.")

    unlock_channel = require_in(require_field(body, "unlock_channel"), "unlock_channel", constants.UNLOCK_CHANNELS)

    # Final-settled overdue calculation
    ended_dt = now_dt()
    current_expires_dt = parse_iso(rental["current_expires_at"])
    final_overdue = overdue_fee_cents(
        current_expires_dt,
        int(rental["grace_minutes_snapshot"]),
        int(rental["overdue_rate_snapshot"]),
        ended_dt,
    )

    rental["overdue_fee_cents"] = final_overdue
    rental["ended_at"] = format_iso(ended_dt)

    # Deposit settlement (return-path)
    refunded, forfeited = deposit_settle_return(int(rental["deposit_cents_snapshot"]), final_overdue)
    rental["deposit_refunded_cents"] = refunded
    rental["deposit_forfeited_cents"] = forfeited

    rental["status"] = "RETURNED"
    bump_version(rental)

    # Compartment cascade to IDLE
    comp["occupancy_status"] = "IDLE"
    comp["active_rental_id"] = None
    bump_version(comp)

    # Cabinet capacity
    cabinet = store.cabinets[comp["cabinet_id"]]
    recompute_cabinet_capacity(cabinet, bump=True)

    actor_id, actor_role = current_actor()

    # Revenue records — emit final RENTAL_FEE row for any remaining fee since last record?
    # The PRD §3.6 says the return transition "then emits a RENTAL_FEE revenue record for the
    # final rental fee and, if overdue_fee_cents > 0, an OVERDUE_FEE revenue record".
    # However, fees were already emitted at creation and each renewal. To avoid double-counting
    # we DO NOT re-emit a duplicate RENTAL_FEE row here — the per-period total already sums them.
    # Emit only OVERDUE_FEE if applicable.
    if final_overdue > 0:
        emit_revenue_record(rental, "OVERDUE_FEE", final_overdue)

    # Audit
    emit_audit_event(
        event_kind="COMPARTMENT_OPENED",
        subject_type="Compartment",
        subject_id=comp["id"],
        actor_role=actor_role,
        actor_id=actor_id,
        unlock_channel=unlock_channel,
        detail={"rental_id": rental["id"], "trigger": "return"},
    )

    return serialize_rental(rental)


# ---------------------------------------------------------------------------
# Refund
# ---------------------------------------------------------------------------


def refund_rental(rental_id: str, body: dict[str, Any]) -> dict[str, Any]:
    store = get_store()
    rental = get_rental_or_404(rental_id)
    _check_version(rental, body.get("version"))

    if rental["status"] != "RETURNED":
        raise ApiError("ERR_INVALID_STATE", f"Cannot refund rental in status {rental['status']}.")

    # Refund blocked by claim?
    blocking_statuses = {
        "REPORTED", "EVIDENCE_PENDING", "UNDER_REVIEW", "EVIDENCE_REJECTED", "APPROVED", "PAID",
    }
    for claim in store.insurance_claims.values():
        if claim["rental_id"] == rental_id and claim["status"] in blocking_statuses:
            raise ApiError(
                "ERR_REFUND_BLOCKED_BY_CLAIM",
                f"Rental has an active claim in status {claim['status']}.",
            )

    # Sum prior RENTAL_FEE + OVERDUE_FEE gross_cents
    total_to_reverse = 0
    for rec in store.revenue_records.values():
        if rec["rental_id"] != rental_id:
            continue
        if rec["revenue_kind"] in ("RENTAL_FEE", "OVERDUE_FEE"):
            total_to_reverse += int(rec["gross_cents"])

    # REFUND_REVERSAL row with negative gross
    emit_revenue_record(rental, "REFUND_REVERSAL", -total_to_reverse)

    # Any deposit still held → move into deposit_refunded
    deposit_remaining = int(rental["deposit_cents_snapshot"]) - int(rental["deposit_refunded_cents"]) - int(rental["deposit_forfeited_cents"])
    if deposit_remaining > 0:
        rental["deposit_refunded_cents"] = int(rental["deposit_refunded_cents"]) + deposit_remaining

    rental["status"] = "REFUNDED"
    bump_version(rental)
    return serialize_rental(rental)


# ---------------------------------------------------------------------------
# Sweep helpers (time-gated transitions)
# ---------------------------------------------------------------------------


def sweep_rentals(now: Any) -> int:
    """Iterate every rental in non-terminal state and fire any time-gated transitions.

    Returns the count of transitions fired.
    """
    store = get_store()
    transitions = 0

    # Snapshot to avoid mutation issues
    rentals = list(store.rentals.values())
    for rental in rentals:
        status = rental["status"]
        if status in ("RETURNED", "FORCE_CLEARED", "REFUNDED"):
            continue
        current_expires_dt = parse_iso(rental["current_expires_at"])
        grace_end_dt = add_seconds(current_expires_dt, int(rental["grace_minutes_snapshot"]) * 60)
        force_clear_dt = add_seconds(current_expires_dt, int(rental["forced_clearance_hours_snapshot"]) * 3600)
        reminder_dt = add_seconds(current_expires_dt, -constants.REMINDER_LEAD_MINUTES * 60)

        # Force-clearance first (most progressed) — but only if currently OVERDUE
        if status == "OVERDUE" and now >= force_clear_dt:
            _do_force_clearance(rental, now)
            transitions += 1
            continue

        # Overdue from ACTIVE/EXPIRING_SOON
        if status in ("ACTIVE", "EXPIRING_SOON") and now >= grace_end_dt:
            _do_to_overdue(rental, now)
            transitions += 1
            # Then check force-clearance again in same sweep run
            if now >= force_clear_dt:
                _do_force_clearance(rental, now)
                transitions += 1
            continue

        # Expiring-soon from ACTIVE
        if status == "ACTIVE" and reminder_dt <= now < current_expires_dt:
            rental["status"] = "EXPIRING_SOON"
            if rental.get("reminder_sent_at") is None:
                rental["reminder_sent_at"] = format_iso(now)
            bump_version(rental)
            transitions += 1
            continue

    return transitions


def _do_to_overdue(rental: dict[str, Any], now: Any) -> None:
    """Transition rental ACTIVE/EXPIRING_SOON → OVERDUE; cascade compartment."""
    store = get_store()
    rental["status"] = "OVERDUE"
    bump_version(rental)

    comp = store.compartments.get(rental["compartment_id"])
    if comp is not None:
        comp["occupancy_status"] = "OVERDUE"
        bump_version(comp)
        cabinet = store.cabinets.get(comp["cabinet_id"])
        if cabinet is not None:
            recompute_cabinet_capacity(cabinet, bump=True)


def _do_force_clearance(rental: dict[str, Any], now: Any) -> None:
    """Transition rental OVERDUE → FORCE_CLEARED; cascade compartment to HOLDING.
    Emits OVERDUE_FEE and DEPOSIT_FORFEIT revenue records, plus a FORCE_CLEARANCE audit event.
    """
    store = get_store()

    current_expires_dt = parse_iso(rental["current_expires_at"])
    final_overdue = overdue_fee_cents(
        current_expires_dt,
        int(rental["grace_minutes_snapshot"]),
        int(rental["overdue_rate_snapshot"]),
        now,
    )
    rental["overdue_fee_cents"] = final_overdue
    rental["ended_at"] = format_iso(now)

    _, forfeited = deposit_settle_force_clearance(int(rental["deposit_cents_snapshot"]))
    rental["deposit_forfeited_cents"] = forfeited
    rental["deposit_refunded_cents"] = 0

    rental["status"] = "FORCE_CLEARED"
    bump_version(rental)

    comp = store.compartments.get(rental["compartment_id"])
    if comp is not None:
        comp["occupancy_status"] = "HOLDING"
        comp["active_rental_id"] = None
        comp["holding_item_description"] = (
            f"Items from rental {rental['id']} moved to designated storage."
        )
        deadline = add_seconds(now, constants.HOLDING_CLAIM_WINDOW_HOURS * 3600)
        comp["holding_claim_deadline"] = format_iso(deadline)
        bump_version(comp)
        cabinet = store.cabinets.get(comp["cabinet_id"])
        if cabinet is not None:
            recompute_cabinet_capacity(cabinet, bump=True)

    # Revenue
    if final_overdue > 0:
        emit_revenue_record(rental, "OVERDUE_FEE", final_overdue)
    if forfeited > 0:
        emit_revenue_record(rental, "DEPOSIT_FORFEIT", forfeited)

    # Audit
    emit_audit_event(
        event_kind="FORCE_CLEARANCE",
        subject_type="Rental",
        subject_id=rental["id"],
        actor_role="System",
        actor_id="system",
        unlock_channel=None,
        detail={
            "compartment_id": rental["compartment_id"],
            "deposit_forfeited_cents": forfeited,
            "overdue_fee_cents": final_overdue,
        },
    )


def sweep_cabinets(now: Any) -> int:
    """DEGRADED / OFFLINE transitions based on last_heartbeat_at age."""
    store = get_store()
    transitions = 0
    for cabinet in store.cabinets.values():
        last = cabinet.get("last_heartbeat_at")
        if last is None:
            # No heartbeat yet — leave ONLINE by default
            continue
        try:
            last_dt = parse_iso(last)
        except ValueError:
            continue
        age = (now - last_dt).total_seconds()
        new_status = cabinet["online_status"]
        if age >= constants.OFFLINE_THRESHOLD_MINUTES * 60:
            new_status = "OFFLINE"
        elif age >= constants.DEGRADED_THRESHOLD_MINUTES * 60:
            new_status = "DEGRADED"
        else:
            continue  # within 5 minutes — stay current
        if new_status != cabinet["online_status"]:
            cabinet["online_status"] = new_status
            bump_version(cabinet)
            transitions += 1
    return transitions
