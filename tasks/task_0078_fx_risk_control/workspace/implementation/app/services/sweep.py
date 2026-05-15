"""End-of-day sweep — §3.10."""
from __future__ import annotations

from app.clock import clock, parse_iso
from app.numeric import to_decimal, ZERO
from app.services import positions as positions_service
from app.services.compliance import file_report
from app.store import Store, now_iso


def run_sweep(store: Store, actor_user_id: str = "SYSTEM", actor_role: str = "RiskOfficer") -> dict:
    """Idempotent six-step EOD sweep."""
    summary = {
        "expired_adjustments": 0,
        "rearmed_stop_loss": 0,
        "archived_stop_loss": 0,
        "report_id": None,
    }
    current_trading_day = clock.today_iso_date()
    now = clock.now()

    # Step 1: expire APPROVED LimitAdjustmentRequests whose expires_at has passed.
    for adj in list(store.limit_adjustments.values()):
        if adj["status"] != "APPROVED":
            continue
        try:
            exp = parse_iso(adj["expires_at"])
        except Exception:
            continue
        if exp > now:
            continue
        # Transition APPROVED -> EXPIRED
        before = {"status": "APPROVED",
                  "temporary_override_usd": float(_limit_override(store, adj))}
        adj["status"] = "EXPIRED"
        adj["updated_at"] = now_iso()
        adj["version"] = adj["version"] + 1
        limit = store.limits.get(adj["limit_id"])
        if limit is not None:
            new_override = to_decimal(limit.get("temporary_override_usd") or 0) - to_decimal(adj["requested_delta_usd"])
            if new_override < ZERO:
                new_override = ZERO
            limit["temporary_override_usd"] = new_override
            limit["updated_at"] = now_iso()
            limit["version"] = limit["version"] + 1
            positions_service.recompute_limit_utilization(store, limit, current_trading_day)
            positions_service.recompute_warning_status_for_trader(store, limit["trader_id"], current_trading_day)
        summary["expired_adjustments"] += 1
        store.audit(
            event_type="LIMIT_OVERRIDE_EXPIRED",
            actor_user_id=actor_user_id,
            actor_role=actor_role,
            subject_entity="LimitAdjustmentRequest",
            subject_id=adj["id"],
            before_snapshot=before,
            after_snapshot={"status": "EXPIRED"},
        )

    # Step 2 + 3: snapshot EOD net_open_usd and recompute warning_status with OVERNIGHT caps.
    # We don't carry a dedicated eod_net_open_usd field on Position (the scaffold's
    # description acknowledges it as a derived bucket value), so we just rerun the
    # cascade with the current trading day.
    affected_traders = {p["trader_id"] for p in store.positions.values()}
    for trader_id in affected_traders:
        positions_service.recompute_warning_status_for_trader(store, trader_id, current_trading_day)

    # Step 4: re-arm OVERRIDDEN stop-loss events.
    for event in store.stop_loss_events.values():
        if event["state"] == "OVERRIDDEN":
            before = {"state": "OVERRIDDEN"}
            event["state"] = "ARMED"
            event["triggered_at"] = None
            event["triggering_value"] = None
            event["updated_at"] = now_iso()
            event["version"] = event["version"] + 1
            summary["rearmed_stop_loss"] += 1
            store.audit(
                event_type="STOP_LOSS_OVERRIDDEN",
                actor_user_id="SYSTEM",
                actor_role="SYSTEM",
                subject_entity="StopLossEvent",
                subject_id=event["id"],
                before_snapshot=before,
                after_snapshot={"state": "ARMED"},
            )

    # Step 5: archive EXECUTED stop-loss events.
    for event in store.stop_loss_events.values():
        if event["state"] == "EXECUTED":
            before = {"state": "EXECUTED"}
            event["state"] = "ARCHIVED"
            event["updated_at"] = now_iso()
            event["version"] = event["version"] + 1
            summary["archived_stop_loss"] += 1
            store.audit(
                event_type="STOP_LOSS_OVERRIDDEN",
                actor_user_id="SYSTEM",
                actor_role="SYSTEM",
                subject_entity="StopLossEvent",
                subject_id=event["id"],
                before_snapshot=before,
                after_snapshot={"state": "ARCHIVED"},
            )

    # Step 6: emit one INTERNAL_CONTROL ComplianceReport per trading_day.
    # Idempotent: if one already exists for today, increment its version family.
    payload = {"trading_day": current_trading_day,
               "summary": {**summary, "report_id": None}}
    report = file_report(
        store,
        report_type="INTERNAL_CONTROL",
        reference_trade_id=None,
        payload=payload,
        filed_by_user_id="SYSTEM",
    )
    summary["report_id"] = report["id"]
    store.audit(
        event_type="REPORT_FILED",
        actor_user_id="SYSTEM",
        actor_role="SYSTEM",
        subject_entity="ComplianceReport",
        subject_id=report["id"],
        before_snapshot=None,
        after_snapshot={"report_type": "INTERNAL_CONTROL",
                        "version": report["version"]},
    )
    return summary


def _limit_override(store: Store, adj: dict) -> ZERO.__class__:
    limit = store.limits.get(adj["limit_id"])
    if limit is None:
        return ZERO
    return to_decimal(limit.get("temporary_override_usd") or 0)
