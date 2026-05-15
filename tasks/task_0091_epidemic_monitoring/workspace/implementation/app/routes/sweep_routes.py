"""Sweep endpoint: TestOrder expiry, Isolation EXTENDED->ACTIVE rollover."""
from __future__ import annotations

from flask import Flask

from ..audit import append_audit
from ..auth import require_auth
from ..clock import now_dt, now_iso_ms, parse_iso
from ..constants import TEST_VALIDITY_HOURS
from ..store import bump_version, get_store
from ._helpers import ok, with_lock


def register(app: Flask) -> None:
    app.add_url_rule(
        "/_sweep/run",
        view_func=require_auth("CDCSupervisor")(with_lock(run_sweep)),
        methods=["POST"],
    )


def run_sweep():
    store = get_store()
    now = now_dt()
    voided = []
    rolled = []

    # TestOrder expiry: COLLECTED w/ PENDING result, past validity -> VOID
    for order in store.test_orders.values():
        if order.get("status") != "COLLECTED":
            continue
        if order.get("result") != "PENDING":
            continue
        collected = order.get("collected_at")
        if not collected:
            continue
        try:
            cdt = parse_iso(collected)
        except Exception:
            continue
        elapsed_hours = (now - cdt).total_seconds() / 3600.0
        validity = TEST_VALIDITY_HOURS.get(order.get("test_type"), 24)
        if elapsed_hours > validity:
            order["result"] = "INVALID"
            order.setdefault("chain_of_custody", []).append(
                {
                    "actor_role": "system",
                    "actor_id": "system",
                    "action": "EXPIRY_VOID",
                    "at": now_iso_ms(),
                }
            )
            order["status"] = "VOID"
            bump_version(order)
            append_audit(
                "TestOrder",
                order["id"],
                "COLLECTED",
                "VOID",
                actor_role="system",
                actor_id="system",
            )
            voided.append(order["id"])

    # Isolation rollover: EXTENDED -> ACTIVE if now < planned_end_date
    for iso in store.isolations.values():
        if iso.get("status") != "EXTENDED":
            continue
        try:
            ped = parse_iso(iso.get("planned_end_date"))
        except Exception:
            continue
        if now < ped:
            iso["status"] = "ACTIVE"
            bump_version(iso)
            append_audit(
                "Isolation",
                iso["id"],
                "EXTENDED",
                "ACTIVE",
                actor_role="system",
                actor_id="system",
            )
            rolled.append(iso["id"])

    return ok({"voided_test_orders": voided, "rolled_isolations": rolled})
