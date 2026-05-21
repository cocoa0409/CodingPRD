"""Ingest a toll event end-to-end: attribute, price, post side-effects."""
from typing import Optional, Tuple

from ..clock import iso_now, parse_iso
from ..errors import ApiError, raise_api_error
from ..store import store
from .accounts_svc import recompute_outstanding_and_cascade
from .pricing import (
    HOV_MIN_OCCUPANTS,
    LATE_PENALTY_CENTS,
    compute_fine_amount,
    compute_toll,
    lookup_interop_policy,
)
from datetime import timedelta


def _read_minute_key(read_at_iso: str) -> str:
    """Truncate ISO timestamp to the minute (YYYY-MM-DDTHH:MM)."""
    dt = parse_iso(read_at_iso)
    return dt.strftime("%Y-%m-%dT%H:%M")


def _dedup_key(payload: dict) -> Tuple[str, str, str]:
    """Build the deduplication tuple per validation #14.

    (gantry_id, read_at_minute, plate_number+plate_state OR transponder_serial)
    """
    minute = _read_minute_key(payload["read_at"])
    if payload.get("transponder_serial"):
        ident = f"TRANSPONDER::{payload['transponder_serial']}"
    elif payload.get("plate_number"):
        ident = f"PLATE::{payload['plate_number']}::{payload.get('plate_state', '')}"
    else:
        ident = "UNKNOWN"
    return (payload["gantry_id"], minute, ident)


def _check_duplicate(payload: dict) -> None:
    key = _dedup_key(payload)
    for e in store.toll_events.values():
        existing_key = (
            e["gantry_id"],
            _read_minute_key(e["read_at"]),
        )
        if e.get("transponder_serial"):
            existing_ident = f"TRANSPONDER::{e['transponder_serial']}"
        elif e.get("plate_number"):
            existing_ident = f"PLATE::{e['plate_number']}::{e.get('plate_state', '')}"
        else:
            existing_ident = "UNKNOWN"
        if (existing_key + (existing_ident,)) == key:
            raise_api_error("ERR_DUPLICATE_TOLL_EVENT")


def _create_violation_and_fine(toll_event: dict, account_id: Optional[str], vehicle_id: Optional[str], reason_code: str) -> dict:
    """Create persistent Violation + Fine records linked to this toll event."""
    violation = store.stamp_new({
        "toll_event_id": toll_event["id"],
        "account_id": account_id,
        "vehicle_id": vehicle_id,
        "reason_code": reason_code,
        "status": "OPEN",
    })
    store.violations[violation["id"]] = violation

    vehicle = store.vehicles.get(vehicle_id) if vehicle_id else None
    account = store.accounts.get(account_id) if account_id else None
    home_agency_code = account["home_agency_code"] if account else None

    amount_cents, civil_penalty = compute_fine_amount(toll_event, vehicle, home_agency_code, reason_code)
    issued_at = toll_event["created_at"]
    due_dt = parse_iso(issued_at) + timedelta(days=30)
    due_at = due_dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{due_dt.microsecond // 1000:03d}Z"

    fine = store.stamp_new({
        "violation_id": violation["id"],
        "amount_cents": amount_cents,
        "civil_penalty_cents": civil_penalty,
        "settlement_status": "PENDING",
        "due_at": due_at,
        "issued_at": issued_at,
        "dispute_count": 0,
    })
    store.fines[fine["id"]] = fine
    return violation


def _maybe_auto_reload(account: dict, toll_event: dict) -> None:
    """Run the auto-reload check post-debit. Inclusive comparison: <=."""
    if not account.get("auto_reload_enabled"):
        return
    if int(account["balance_cents"]) > int(account["auto_reload_threshold_cents"]):
        return
    # Per-minute guard: at most one auto-reload per account per minute
    minute = _read_minute_key(toll_event["read_at"])
    guard_key = (account["id"], minute)
    if store.autoreload_minute_guard.get(guard_key):
        # Already credited this minute. Per concurrency rule the second posting
        # should observe balance > threshold; if it doesn't, we skip silently
        # (the first credit already restored the balance for the first event).
        return

    balance_before = int(account["balance_cents"])
    topup = int(account["auto_reload_topup_cents"])
    account["balance_cents"] = balance_before + topup

    reload_event = store.stamp_event({
        "account_id": account["id"],
        "kind": "AUTO",
        "amount_cents": topup,
        "balance_before_cents": balance_before,
        "balance_after_cents": account["balance_cents"],
        "triggered_by_event_id": toll_event["id"],
    })
    store.reload_events[reload_event["id"]] = reload_event
    store.bump(account)
    store.autoreload_minute_guard[guard_key] = True


def ingest_toll_event(payload: dict) -> dict:
    """Implements the full PENDING -> { POSTED | TOLL_BY_PLATE_INVOICED | EXEMPTED | VIOLATED } pipeline."""
    with store.lock:
        # ---- Dedup check (validation #14)
        _check_duplicate(payload)

        # ---- Stamp the toll event id/created_at now
        toll_event = {
            "gantry_id": payload["gantry_id"],
            "agency_code": payload["agency_code"],
            "base_rate_cents": payload["base_rate_cents"],
            "read_at": payload["read_at"],
            "capture_method": None,
            "transponder_serial": payload.get("transponder_serial"),
            "plate_number": payload.get("plate_number"),
            "plate_state": payload.get("plate_state"),
            "declared_occupants": payload.get("declared_occupants", 1),
            "hov_lane": payload.get("hov_lane", False),
            "account_id": None,
            "vehicle_id": None,
            "billing_status": "PENDING",
            "gross_toll_cents": 0,
            "net_toll_cents": 0,
            "hov_exempt_applied": False,
        }
        store.stamp_event(toll_event)

        # ---- Attribution
        transponder = None
        vehicle = None
        account = None
        if toll_event["transponder_serial"]:
            cand = store.find_transponder_by_serial(toll_event["transponder_serial"])
            if cand and cand.get("status") == "ACTIVE":
                transponder = cand
                if cand.get("bound_vehicle_id"):
                    vehicle = store.vehicles.get(cand["bound_vehicle_id"])
                    if vehicle:
                        account = store.accounts.get(vehicle["account_id"])

        if vehicle is None and toll_event["plate_number"] and toll_event["plate_state"]:
            cand_v = store.find_vehicle_by_plate(toll_event["plate_number"], toll_event["plate_state"])
            if cand_v:
                vehicle = cand_v
                account = store.accounts.get(cand_v["account_id"])

        if transponder and vehicle and account:
            toll_event["capture_method"] = "TRANSPONDER"
        elif vehicle and account:
            toll_event["capture_method"] = "PLATE"
        else:
            toll_event["capture_method"] = "UNRESOLVED"

        if vehicle:
            toll_event["vehicle_id"] = vehicle["id"]
        if account:
            toll_event["account_id"] = account["id"]

        # ---- Eligibility / HOV check
        hov_qualifies = False
        hov_lane = bool(toll_event["hov_lane"])
        occupants = int(toll_event["declared_occupants"])
        if hov_lane:
            if vehicle and vehicle.get("hov_capable") and occupants >= HOV_MIN_OCCUPANTS:
                hov_qualifies = True

        # Detect HOV fraud case (priority #11): hov_lane=true, occupants<3, vehicle hov_capable
        hov_fraud = False
        if hov_lane and vehicle and vehicle.get("hov_capable") and occupants < HOV_MIN_OCCUPANTS:
            hov_fraud = True

        # ---- Determine billing outcome
        # Branch 1: HOV exemption applies
        if hov_qualifies:
            toll_event["hov_exempt_applied"] = True
            toll_event["billing_status"] = "EXEMPTED"
            # capture_method already set; gross/net stay 0
            store.toll_events[toll_event["id"]] = toll_event
            return toll_event

        # Branch 2: HOV fraud (vehicle resolved, hov_capable, but occupants<3)
        if hov_fraud:
            # Pre-check interop ambiguity using a "what if it billed" path
            _check_interop_ambiguity_or_raise(account, toll_event["agency_code"])
            toll_event["billing_status"] = "VIOLATED"
            toll_event["gross_toll_cents"] = 0
            toll_event["net_toll_cents"] = 0
            store.toll_events[toll_event["id"]] = toll_event
            _create_violation_and_fine(toll_event, account["id"] if account else None,
                                       vehicle["id"] if vehicle else None, "HOV_FRAUD")
            if account:
                recompute_outstanding_and_cascade(account["id"])
            # Return 409 with ERR_HOV_FRAUD_RECORDED; side effects persisted.
            raise_api_error("ERR_HOV_FRAUD_RECORDED")

        # Branch 3: Attribution failed entirely -> UNREAD_TRANSPONDER_NO_PLATE
        if account is None or vehicle is None:
            toll_event["billing_status"] = "VIOLATED"
            store.toll_events[toll_event["id"]] = toll_event
            _create_violation_and_fine(toll_event, None, None, "UNREAD_TRANSPONDER_NO_PLATE")
            return toll_event

        # From here, both account and vehicle are resolved.
        # Vehicle blocked -> violation BLOCKED_VEHICLE (priority #10)
        if vehicle["status"] == "BLOCKED":
            toll_event["billing_status"] = "VIOLATED"
            store.toll_events[toll_event["id"]] = toll_event
            _create_violation_and_fine(toll_event, account["id"], vehicle["id"], "BLOCKED_VEHICLE")
            recompute_outstanding_and_cascade(account["id"])
            return toll_event

        # Account not ACTIVE -> per validation priority #6 attribution to non-active
        # account is a state-machine violation rather than a normal posting; we
        # represent this as a violation as well.
        if account["status"] != "ACTIVE":
            toll_event["billing_status"] = "VIOLATED"
            store.toll_events[toll_event["id"]] = toll_event
            _create_violation_and_fine(toll_event, account["id"], vehicle["id"], "BLOCKED_VEHICLE")
            recompute_outstanding_and_cascade(account["id"])
            return toll_event

        # Now compute pricing in the appropriate variant.
        capture_method = toll_event["capture_method"]
        gross, net, ambiguous = compute_toll(
            base_rate_cents=toll_event["base_rate_cents"],
            vehicle_class=vehicle["vehicle_class"],
            home_agency_code=account["home_agency_code"],
            gantry_agency=toll_event["agency_code"],
            capture_method=capture_method,
            hov_exempt_applied=False,
        )
        if ambiguous:
            raise_api_error("ERR_INTEROP_POLICY_AMBIGUOUS")

        post_debit_balance = int(account["balance_cents"]) - net

        if capture_method == "TRANSPONDER":
            # POSTED if post-debit >= -topup OR auto-reload enabled
            ok = (post_debit_balance >= -int(account.get("auto_reload_topup_cents", 0))) or bool(account.get("auto_reload_enabled"))
            if not ok:
                toll_event["billing_status"] = "VIOLATED"
                store.toll_events[toll_event["id"]] = toll_event
                _create_violation_and_fine(toll_event, account["id"], vehicle["id"], "INSUFFICIENT_FUNDS_ON_PLATE_BILL")
                recompute_outstanding_and_cascade(account["id"])
                return toll_event
            toll_event["billing_status"] = "POSTED"
            toll_event["gross_toll_cents"] = gross
            toll_event["net_toll_cents"] = net
            account["balance_cents"] = post_debit_balance
            store.bump(account)
            store.toll_events[toll_event["id"]] = toll_event
            _maybe_auto_reload(account, toll_event)
            return toll_event

        # capture_method == "PLATE"
        if post_debit_balance < 0 and not bool(account.get("auto_reload_enabled")):
            toll_event["billing_status"] = "VIOLATED"
            store.toll_events[toll_event["id"]] = toll_event
            _create_violation_and_fine(toll_event, account["id"], vehicle["id"], "INSUFFICIENT_FUNDS_ON_PLATE_BILL")
            recompute_outstanding_and_cascade(account["id"])
            return toll_event

        toll_event["billing_status"] = "TOLL_BY_PLATE_INVOICED"
        toll_event["gross_toll_cents"] = gross
        toll_event["net_toll_cents"] = net
        account["balance_cents"] = post_debit_balance
        store.bump(account)
        store.toll_events[toll_event["id"]] = toll_event
        _maybe_auto_reload(account, toll_event)
        return toll_event


def _check_interop_ambiguity_or_raise(account, gantry_agency):
    if account is None:
        return
    if account["home_agency_code"] == gantry_agency:
        return
    _, ambiguous = lookup_interop_policy(account["home_agency_code"], gantry_agency)
    if ambiguous:
        raise_api_error("ERR_INTEROP_POLICY_AMBIGUOUS")


def void_toll_event(toll_event: dict) -> dict:
    """Implement the toll-event void transitions per the state machine."""
    from datetime import timedelta as _td
    from ..clock import clock as _clock
    with store.lock:
        # 24-hour window
        created = parse_iso(toll_event["created_at"])
        if _clock.now() - created > _td(hours=24):
            raise_api_error("ERR_VOID_WINDOW_EXPIRED")

        status = toll_event["billing_status"]
        if status not in ("POSTED", "TOLL_BY_PLATE_INVOICED", "VIOLATED"):
            raise_api_error("ERR_INVALID_STATE")

        if status in ("POSTED", "TOLL_BY_PLATE_INVOICED"):
            account = store.accounts.get(toll_event["account_id"]) if toll_event.get("account_id") else None
            if account:
                account["balance_cents"] = int(account["balance_cents"]) + int(toll_event["net_toll_cents"])
                store.bump(account)
            toll_event["net_toll_cents"] = 0
            toll_event["gross_toll_cents"] = 0
            toll_event["billing_status"] = "VOIDED"
            return toll_event

        # status == VIOLATED: cascade Violation -> CLEARED, Fine -> DISMISSED
        violation = _find_violation_for_toll(toll_event["id"])
        if violation is None:
            raise_api_error("ERR_INVALID_STATE")
        fine = _find_fine_for_violation(violation["id"])
        if fine is None or fine["settlement_status"] != "PENDING":
            raise_api_error("ERR_INVALID_STATE")
        violation["status"] = "CLEARED"
        store.bump(violation)
        fine["settlement_status"] = "DISMISSED"
        store.bump(fine)
        toll_event["billing_status"] = "VOIDED"
        toll_event["net_toll_cents"] = 0
        toll_event["gross_toll_cents"] = 0
        if violation.get("account_id"):
            recompute_outstanding_and_cascade(violation["account_id"])
        return toll_event


def _find_violation_for_toll(toll_event_id: str):
    for v in store.violations.values():
        if v["toll_event_id"] == toll_event_id:
            return v
    return None


def _find_fine_for_violation(violation_id: str):
    for f in store.fines.values():
        if f["violation_id"] == violation_id:
            return f
    return None


def overdue_sweep() -> int:
    """Move PENDING fines past due_at into OVERDUE, applying late penalty and cascades.

    Returns the number of fines swept.
    """
    from ..clock import clock as _clock
    swept = 0
    with store.lock:
        now = _clock.now()
        for fine in list(store.fines.values()):
            if fine["settlement_status"] != "PENDING":
                continue
            due_at = parse_iso(fine["due_at"])
            if due_at > now:
                continue
            # Transition PENDING -> OVERDUE
            fine["amount_cents"] = int(fine["amount_cents"]) + LATE_PENALTY_CENTS
            fine["civil_penalty_cents"] = int(fine["civil_penalty_cents"]) + LATE_PENALTY_CENTS
            fine["settlement_status"] = "OVERDUE"
            store.bump(fine)
            swept += 1

            violation = store.violations.get(fine["violation_id"])
            if violation and fine["dispute_count"] >= 2 and violation["status"] == "OPEN":
                # Cascade: Violation OPEN -> ESCALATED
                violation["status"] = "ESCALATED"
                store.bump(violation)
                if violation.get("vehicle_id"):
                    veh = store.vehicles.get(violation["vehicle_id"])
                    if veh and veh["status"] != "BLOCKED":
                        veh["status"] = "BLOCKED"
                        store.bump(veh)

            if violation and violation.get("account_id"):
                recompute_outstanding_and_cascade(violation["account_id"])
    return swept
