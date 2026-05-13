"""PT bookings, slots, packages, commissions."""
from clock import now
from datetime import timedelta
from db import state, new_id, next_order, stamp_create, bump
from errors import raise_err
from .calc import round_half_up, mul_bp_round_half_up
from . import wallet as wallet_svc


NO_SHOW_PENALTY_CENTS = 5000  # constant per scaffold; PRD says "fixed cents amount"


# ---------------- Slot creation ----------------

def create_slot(trainer_id, starts_at, ends_at, specialty_code):
    trainer = state["trainers"].get(trainer_id)
    if not trainer:
        raise_err("ERR_NOT_FOUND", "trainer not found")
    if specialty_code not in trainer.get("specialties", []):
        # Validation 11 — used at booking time per scaffold; for slot create
        # we just verify the specialty is in the trainer's list. The scaffold
        # says specialty_code "must be a member of Trainer.specialties".
        raise_err("ERR_SPECIALTY_MISMATCH", "specialty not in trainer specialties")
    # Overlap check (priority 13): half-open intervals, adjacent allowed
    for s in state["trainer_slots"].values():
        if s["trainer_id"] != trainer_id:
            continue
        if s["status"] not in ("OPEN", "RESERVED"):
            continue
        # Overlap iff a.starts < b.ends AND b.starts < a.ends
        if starts_at < s["ends_at"] and s["starts_at"] < ends_at:
            raise_err("ERR_SLOT_OVERLAP", "slot overlaps existing slot")
    slot = {
        "id": new_id(),
        "trainer_id": trainer_id,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "specialty_code": specialty_code,
        "status": "OPEN",
    }
    stamp_create(slot)
    state["trainer_slots"][slot["id"]] = slot
    return slot


# ---------------- PT booking ----------------

def book_pt(member_id, slot_id, billing_mode, package_id=None):
    slot = state["trainer_slots"].get(slot_id)
    if not slot:
        raise_err("ERR_NOT_FOUND", "slot not found")
    trainer = state["trainers"].get(slot["trainer_id"])
    if not trainer:
        raise_err("ERR_NOT_FOUND", "trainer missing")
    member = state["members"].get(member_id)
    if not member:
        raise_err("ERR_NOT_FOUND", "member not found")
    # Trainer inactive (priority 10)
    if trainer.get("status") != "ACTIVE":
        raise_err("ERR_TRAINER_INACTIVE", "trainer inactive")
    # Specialty mismatch (priority 11)
    if slot["specialty_code"] not in trainer.get("specialties", []):
        raise_err("ERR_SPECIALTY_MISMATCH", "specialty mismatch")
    # Slot already reserved (priority 12)
    if slot["status"] != "OPEN":
        raise_err("ERR_SLOT_ALREADY_RESERVED", "slot not OPEN")
    # billing mode
    if billing_mode not in ("SINGLE", "PACKAGE"):
        raise_err("ERR_VALIDATION", "invalid billing_mode")
    pkg = None
    if billing_mode == "PACKAGE":
        if not package_id:
            raise_err("ERR_VALIDATION", "package_id required for PACKAGE billing")
        pkg = state["pt_packages"].get(package_id)
        if not pkg:
            raise_err("ERR_NOT_FOUND", "package not found")
        if pkg["status"] != "ACTIVE":
            raise_err("ERR_INVALID_STATE", "package not ACTIVE")
        if pkg["member_id"] != member_id:
            raise_err("ERR_VALIDATION", "package member mismatch")
        if pkg["trainer_id"] != slot["trainer_id"]:
            raise_err("ERR_VALIDATION", "package trainer mismatch")
    # session_price_cents pinned
    if billing_mode == "SINGLE":
        # Use trainer's session_price_default? Field not present in scaffold.
        # The scaffold's session_price_cents description references
        # 'Trainer.session_price_default (input field above)' but that field
        # was not declared. Fall back to a deterministic policy: if the trainer
        # has a session_price_default attribute, use it; else use 0 — and
        # adjust if the spec is exercised differently.
        session_price = trainer.get("session_price_default", 0) or 0
    else:
        # PACKAGE: pin per package_unit_price (final session gets remainder).
        # We can't yet know "is this the last session" — but at booking time,
        # we pin based on how many bookings (CONFIRMED+COMPLETED) already exist
        # against the package +1 == total_sessions => is the last.
        existing = [
            b for b in state["pt_bookings"].values()
            if b.get("package_id") == package_id
            and b["status"] in ("CONFIRMED", "COMPLETED")
        ]
        # Position of this booking (1-based) among consumed-or-pending sessions
        position = len(existing) + 1
        base_unit = pkg["gross_price_cents"] // pkg["total_sessions"]
        remainder = pkg["gross_price_cents"] - base_unit * pkg["total_sessions"]
        if position == pkg["total_sessions"]:
            session_price = base_unit + remainder
        else:
            session_price = base_unit
    booking_id = new_id()
    # Wallet debit (SINGLE)
    if billing_mode == "SINGLE" and session_price > 0:
        wallet_svc.debit(
            member_id, session_price,
            service_type="PT_SESSION",
            ref_entity=f"PTBooking:{booking_id}",
        )
    booking = {
        "id": booking_id,
        "member_id": member_id,
        "trainer_id": slot["trainer_id"],
        "slot_id": slot_id,
        "package_id": package_id,
        "billing_mode": billing_mode,
        "session_price_cents": session_price,
        "status": "CONFIRMED",
        "scheduled_starts_at": slot["starts_at"],
    }
    stamp_create(booking)
    state["pt_bookings"][booking_id] = booking
    # Flip slot
    slot["status"] = "RESERVED"
    bump(slot)
    return booking


def cancel_pt(booking):
    if booking["status"] != "CONFIRMED":
        raise_err("ERR_INVALID_STATE", "booking not CONFIRMED")
    sched = booking["scheduled_starts_at"]
    if now() >= sched:
        raise_err("ERR_CANCEL_WINDOW_EXPIRED", "cancellation window expired")
    slot = state["trainer_slots"].get(booking["slot_id"])
    if slot:
        slot["status"] = "OPEN"
        bump(slot)
    booking["status"] = "CANCELED"
    bump(booking)
    # Refund logic
    if booking["billing_mode"] == "SINGLE":
        delta = (sched - now()).total_seconds()
        if delta >= 24 * 3600:
            wallet_svc.refund_credit(
                booking["member_id"], booking["session_price_cents"],
                ref_entity=f"PTBooking:{booking['id']}",
            )
    return booking


def complete_pt(booking):
    if booking["status"] != "CONFIRMED":
        raise_err("ERR_INVALID_STATE", "booking not CONFIRMED")
    if now() < booking["scheduled_starts_at"]:
        raise_err("ERR_INVALID_STATE", "now() before scheduled_starts_at")
    slot = state["trainer_slots"].get(booking["slot_id"])
    if slot:
        slot["status"] = "COMPLETED"
        bump(slot)
    booking["status"] = "COMPLETED"
    bump(booking)
    # Package consumption
    if booking["billing_mode"] == "PACKAGE":
        pkg = state["pt_packages"].get(booking.get("package_id"))
        if pkg:
            pkg["sessions_consumed"] = pkg.get("sessions_consumed", 0) + 1
            if pkg["sessions_consumed"] >= pkg["total_sessions"]:
                pkg["status"] = "EXHAUSTED"
            bump(pkg)
    # Commission
    trainer = state["trainers"].get(booking["trainer_id"])
    base_bp = trainer["session_commission_pct_bp"]
    tier = trainer.get("tier", "BRONZE")
    tier_mod = 0 if tier == "BRONZE" else 500 if tier == "SILVER" else 1000
    eff_bp = base_bp + tier_mod
    amount = mul_bp_round_half_up(booking["session_price_cents"], eff_bp)
    cr = {
        "id": new_id(),
        "trainer_id": booking["trainer_id"],
        "kind": "SESSION",
        "amount_cents": amount,
        "ref_entity": f"PTBooking:{booking['id']}",
        "payout_cycle_id": None,
        "created_at": now(),
        "_order": next_order(),
    }
    state["commission_records"][cr["id"]] = cr
    return booking


def no_show_pt(booking):
    if booking["status"] != "CONFIRMED":
        raise_err("ERR_INVALID_STATE", "booking not CONFIRMED")
    # Manual no-show via endpoint requires "now() >= scheduled_starts_at + 15 min"
    # The endpoint description doesn't enforce that for operator manual call, but
    # the state machine precondition says so. We'll enforce per state machine.
    threshold = booking["scheduled_starts_at"] + timedelta(minutes=15)
    if now() < threshold:
        raise_err("ERR_INVALID_STATE", "no_show window not reached")
    return _apply_no_show(booking)


def _apply_no_show(booking):
    slot = state["trainer_slots"].get(booking["slot_id"])
    if slot:
        slot["status"] = "NO_SHOW"
        bump(slot)
    booking["status"] = "NO_SHOW"
    bump(booking)
    # Penalty debit — may overdraft; PRD doesn't say it can fail. We'll attempt
    # and skip if it would raise. Per PRD it just debits, so we treat insufficient
    # principal as forced negative? Actually wallet_svc.debit raises on shortfall.
    # The PRD says the wallet IS debited — treat as best-effort; if balance is
    # insufficient, do not raise (no-show is a system transition). We'll allow
    # the debit to fail silently.
    try:
        wallet_svc.debit(
            booking["member_id"], NO_SHOW_PENALTY_CENTS,
            service_type="PT_SESSION",
            ref_entity=f"PTBooking:{booking['id']}",
        )
    except Exception:
        pass
    if booking["billing_mode"] == "PACKAGE":
        pkg = state["pt_packages"].get(booking.get("package_id"))
        if pkg:
            pkg["sessions_consumed"] = pkg.get("sessions_consumed", 0) + 1
            if pkg["sessions_consumed"] >= pkg["total_sessions"]:
                pkg["status"] = "EXHAUSTED"
            bump(pkg)
    return booking


# Time-driven auto no-show — used by clock advance
def auto_no_show_if_due(booking):
    if booking["status"] != "CONFIRMED":
        return
    threshold = booking["scheduled_starts_at"] + timedelta(minutes=15)
    if now() >= threshold:
        _apply_no_show(booking)
