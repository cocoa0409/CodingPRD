"""Test-driving sweeps: clock advance, recertification, settlement."""
from datetime import timedelta
from decimal import Decimal

from db import store, iso_to_dt
from services.utils import stamp_update, round_half_up_int
from services.personnel import refresh_skill_tags, has_active_cert
from services.audit import append_audit


def advance_clock(seconds: float):
    """PRD §3.11: shift logical clock forward. Per PRD §3.5, when the deadline
    passes (whether driven by clock advance or wall time) the order auto-
    transitions back to PENDING_DISPATCH. We do this lazily so that an explicit
    accept-after-deadline can still surface ERR_DISPATCH_DEADLINE_PASSED (PRD
    §3.5). Other observers (list/get) see the post-expire state via the
    `_realize_dispatch_expiries` helper invoked from listing endpoints."""
    store.advance_clock(float(seconds))


def _expire_one_dispatched(o):
    """Auto-revert a DISPATCHED order whose deadline has passed."""
    prev = o.get("assigned_personnel_id")
    if prev and prev in store.personnel:
        p = store.personnel[prev]
        p["workload_active_orders"] = max(0, int(p.get("workload_active_orders", 0)) - 1)
        stamp_update(p)
    o["assigned_personnel_id"] = None
    o["status"] = "PENDING_DISPATCH"
    stamp_update(o)
    append_audit("DISPATCH_EXPIRED", "Order", o["id"], "system", "",
                 {"reason": "deadline_passed", "previous_personnel_id": prev})


def realize_dispatch_expiries():
    """Apply deadline-pass auto-reverts. Idempotent."""
    for o in list(store.orders.values()):
        if o.get("status") == "DISPATCHED":
            dl = iso_to_dt(o.get("dispatch_deadline_at"))
            if dl is not None and store.now() >= dl:
                _expire_one_dispatched(o)


def run_recertification_sweep():
    """Expire health, expire skill certs, cascade to personnel SUSPENDED, revert orders."""
    now = store.now()
    # 1) Expire ACTIVE certifications whose expires_at has passed
    for cert in store.certifications.values():
        if cert["status"] == "ACTIVE":
            exp = iso_to_dt(cert.get("expires_at"))
            if exp is not None and now >= exp:
                cert["status"] = "EXPIRED"
                stamp_update(cert)
                refresh_skill_tags(cert["personnel_id"])

    # 2) Personnel suspension cascade
    for p in store.personnel.values():
        if p["status"] != "ACTIVE":
            continue
        health = iso_to_dt(p.get("health_cert_expires_at"))
        health_expired = health is None or now >= health
        no_active_cert = not has_active_cert(p["id"])
        if health_expired or no_active_cert:
            p["status"] = "SUSPENDED"
            stamp_update(p)
            # Revert any DISPATCHED orders for this personnel
            for o in store.orders.values():
                if o.get("assigned_personnel_id") == p["id"] and o.get("status") == "DISPATCHED":
                    prev = p["id"]
                    o["assigned_personnel_id"] = None
                    o["status"] = "PENDING_DISPATCH"
                    p["workload_active_orders"] = max(0, int(p.get("workload_active_orders", 0)) - 1)
                    stamp_update(o)
                    append_audit("DISPATCH_EXPIRED", "Order", o["id"], "system", "",
                                 {"reason": "personnel_suspended", "previous_personnel_id": prev})
            stamp_update(p)

    # 3) Stamp last_recert_at on every personnel
    for p in store.personnel.values():
        p["last_recert_at"] = store.now_iso()
        stamp_update(p)


def run_settlement_sweep(cycle_id: str):
    """Post TAX and PAYOUT entries for the given cycle, per personnel."""
    now = store.now()
    # Group eligible entries by personnel
    eligible_by_personnel = {}
    for e in store.settlement_entries.values():
        if e["kind"] not in {"COMMISSION", "BONUS", "REVERSAL"}:
            continue
        wu = e.get("withheld_until")
        if wu is not None:
            wu_dt = iso_to_dt(wu)
            if wu_dt is not None and wu_dt > now:
                continue
        eligible_by_personnel.setdefault(e["personnel_id"], []).append(e)
    for personnel_id, entries in eligible_by_personnel.items():
        # Walk in chronological order
        entries.sort(key=lambda x: (x.get("posted_at", ""), x.get("id", "")))
        pre_tax_sum = sum(int(e["amount_cents"]) for e in entries)
        payout_base = max(0, pre_tax_sum)
        tax_cents = round_half_up_int(Decimal(payout_base) * Decimal("0.10"))
        payout_cents = payout_base - tax_cents
        # Post TAX entry
        tax_entry = {
            "personnel_id": personnel_id,
            "order_id": None,
            "kind": "TAX",
            "amount_cents": -int(tax_cents),
            "posted_at": store.now_iso(),
            "cycle_id": cycle_id,
            "withheld_until": None,
        }
        tax_entry["id"] = store.new_id()
        tax_entry["created_at"] = store.now_iso()
        store.settlement_entries[tax_entry["id"]] = tax_entry
        # Post PAYOUT entry
        payout_entry = {
            "personnel_id": personnel_id,
            "order_id": None,
            "kind": "PAYOUT",
            "amount_cents": -int(payout_cents),
            "posted_at": store.now_iso(),
            "cycle_id": cycle_id,
            "withheld_until": None,
        }
        payout_entry["id"] = store.new_id()
        payout_entry["created_at"] = store.now_iso()
        store.settlement_entries[payout_entry["id"]] = payout_entry
