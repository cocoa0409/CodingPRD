"""PTPackage sale and refund."""
from clock import now
from db import state, new_id, next_order, stamp_create, bump
from errors import raise_err
from .calc import mul_bp_round_half_up
from . import wallet as wallet_svc


def sell_package(member_id, trainer_id, total_sessions, gross_price_cents, actor_role, actor_id):
    member = state["members"].get(member_id)
    if not member:
        raise_err("ERR_NOT_FOUND", "member not found")
    trainer = state["trainers"].get(trainer_id)
    if not trainer:
        raise_err("ERR_NOT_FOUND", "trainer not found")
    if trainer.get("status") != "ACTIVE":
        raise_err("ERR_TRAINER_INACTIVE", "trainer inactive")
    if total_sessions < 1:
        raise_err("ERR_VALIDATION", "total_sessions >= 1")
    if gross_price_cents < 0:
        raise_err("ERR_VALIDATION", "gross_price_cents >= 0")
    pkg_id = new_id()
    if gross_price_cents > 0:
        wallet_svc.debit(
            member_id, gross_price_cents,
            service_type="PT_SESSION",  # package debit -- no exact service_type
            ref_entity=f"PTPackage:{pkg_id}",
        )
    pkg = {
        "id": pkg_id,
        "member_id": member_id,
        "trainer_id": trainer_id,
        "total_sessions": total_sessions,
        "gross_price_cents": gross_price_cents,
        "sessions_consumed": 0,
        "sessions_refunded": 0,
        "status": "ACTIVE",
    }
    stamp_create(pkg)
    state["pt_packages"][pkg_id] = pkg
    # Package-sale commission
    amount = mul_bp_round_half_up(gross_price_cents, trainer["package_commission_pct_bp"])
    cr = {
        "id": new_id(),
        "trainer_id": trainer_id,
        "kind": "PACKAGE_SALE",
        "amount_cents": amount,
        "ref_entity": f"PTPackage:{pkg_id}",
        "payout_cycle_id": None,
        "created_at": now(),
        "_order": next_order(),
    }
    state["commission_records"][cr["id"]] = cr
    return pkg


def refund_package(pkg, actor_role, actor_id):
    if pkg["status"] != "ACTIVE":
        raise_err("ERR_INVALID_STATE", "package not ACTIVE")
    if pkg["sessions_consumed"] >= pkg["total_sessions"]:
        raise_err("ERR_INVALID_STATE", "no unused sessions")
    # Refund unused portion
    total_sessions = pkg["total_sessions"]
    consumed = pkg["sessions_consumed"]
    unconsumed = total_sessions - consumed
    base_unit = pkg["gross_price_cents"] // total_sessions
    remainder = pkg["gross_price_cents"] - base_unit * total_sessions
    # Refund unused portion. Final session would have base_unit+remainder; since
    # we are refunding the LAST `unconsumed` sessions, refund includes the
    # remainder iff the last session is unconsumed (consumed < total_sessions).
    refund_amount = base_unit * unconsumed + remainder  # remainder always goes back when last session is unused
    if refund_amount > 0:
        wallet_svc.refund_credit(
            pkg["member_id"], refund_amount,
            ref_entity=f"PTPackage:{pkg['id']}",
        )
    # Commission reversal proportional
    orig = None
    for r in state["commission_records"].values():
        if r["kind"] == "PACKAGE_SALE" and r.get("ref_entity") == f"PTPackage:{pkg['id']}":
            orig = r
            break
    if orig is not None:
        reversal_amount = -mul_bp_round_half_up(
            orig["amount_cents"] * unconsumed,  # will divide via *bp/10000 — emulate directly
            int(10000 * 1)  # placeholder; recompute below cleanly
        )
        # Recompute cleanly:
        from decimal import Decimal, ROUND_HALF_UP
        rev = Decimal(orig["amount_cents"]) * Decimal(unconsumed) / Decimal(total_sessions)
        rev_int = int(rev.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        reversal_amount = -rev_int
        cr = {
            "id": new_id(),
            "trainer_id": pkg["trainer_id"],
            "kind": "REVERSAL",
            "amount_cents": reversal_amount,
            "ref_entity": f"PTPackage:{pkg['id']}",
            "payout_cycle_id": None,
            "created_at": now(),
            "_order": next_order(),
        }
        state["commission_records"][cr["id"]] = cr
    # Cancel each CONFIRMED PTBooking for this package
    for b in list(state["pt_bookings"].values()):
        if b.get("package_id") == pkg["id"] and b["status"] == "CONFIRMED":
            slot = state["trainer_slots"].get(b["slot_id"])
            if slot:
                slot["status"] = "OPEN"
                bump(slot)
            b["status"] = "CANCELED"
            bump(b)
    pkg["status"] = "REFUNDED"
    pkg["sessions_refunded"] = unconsumed
    bump(pkg)
    # Audit log
    audit = {
        "id": new_id(),
        "actor_role": actor_role,
        "actor_id": actor_id,
        "action": "COMMISSION_REVERSAL",
        "target_entity": f"PTPackage:{pkg['id']}",
        "payload": {
            "before": {"status": "ACTIVE", "sessions_consumed": consumed},
            "after": {"status": "REFUNDED", "sessions_refunded": unconsumed},
        },
        "created_at": now(),
        "_order": next_order(),
    }
    state["audit_log"][audit["id"]] = audit
    return pkg


def reverse_unconsumed_for_member(member_id):
    """Called by card refund cascade. Reverse unconsumed package commissions
    for all ACTIVE packages held by this member. No-op when none exist."""
    for pkg in list(state["pt_packages"].values()):
        if pkg["member_id"] != member_id:
            continue
        if pkg["status"] != "ACTIVE":
            continue
        consumed = pkg["sessions_consumed"]
        if consumed >= pkg["total_sessions"]:
            continue
        unconsumed = pkg["total_sessions"] - consumed
        orig = None
        for r in state["commission_records"].values():
            if r["kind"] == "PACKAGE_SALE" and r.get("ref_entity") == f"PTPackage:{pkg['id']}":
                orig = r
                break
        if orig is None:
            continue
        from decimal import Decimal, ROUND_HALF_UP
        rev = Decimal(orig["amount_cents"]) * Decimal(unconsumed) / Decimal(pkg["total_sessions"])
        rev_int = int(rev.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        cr = {
            "id": new_id(),
            "trainer_id": pkg["trainer_id"],
            "kind": "REVERSAL",
            "amount_cents": -rev_int,
            "ref_entity": f"PTPackage:{pkg['id']}",
            "payout_cycle_id": None,
            "created_at": now(),
            "_order": next_order(),
        }
        state["commission_records"][cr["id"]] = cr
