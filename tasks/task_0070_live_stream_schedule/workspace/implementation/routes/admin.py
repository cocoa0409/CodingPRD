"""Admin-only endpoints: simulated clock, sweep, external-event injection."""

from datetime import timedelta

from flask import Blueprint, request

import db
import clock
from errors import (
    ERR_NOT_FOUND, ERR_VALIDATION_FAILED, raise_err,
)
from middleware import require_auth, require_role
from response import success
from services import audit
from services.calculations import (
    calc_commission_final, calc_refund, calc_violation_penalty,
)
from services.product_associations import release_all_for_application
from services.streamer_service import apply_cascade, reconcile_suspension


bp = Blueprint("admin", __name__, url_prefix="/live-schedule")


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

@bp.post("/_clock/advance")
def clock_advance():
    user_id, role = require_auth()
    require_role(role, ["PlatformAdmin"])
    body = request.get_json(silent=True) or {}
    to = body.get("to")
    if not to:
        raise_err(ERR_VALIDATION_FAILED, "to is required")
    try:
        target = clock.parse_iso(to)
    except ValueError as e:
        raise_err(ERR_VALIDATION_FAILED, str(e))
    new_now = clock.advance_to(target)
    return success({"now": clock.format_iso(new_now)})


@bp.get("/_clock/now")
def clock_now():
    user_id, role = require_auth()
    require_role(role, ["PlatformAdmin", "OperationsReviewer",
                        "ComplianceReviewer", "Streamer"])
    return success({"now": clock.format_iso(clock.now())})


# ---------------------------------------------------------------------------
# Sweep
# ---------------------------------------------------------------------------

@bp.post("/_sweep/run")
def sweep_run():
    user_id, role = require_auth()
    require_role(role, ["PlatformAdmin"])

    now_dt = clock.now()
    now_iso = clock.format_iso(now_dt)

    # --- 1. Settlements whose return window has closed ---
    for settlement in list(db.raw_all("settlements")):
        if settlement.get("status") != "WINDOW_OPEN":
            continue
        window_end = clock.parse_iso(settlement["return_window_ends_at"])
        if window_end > now_dt:
            continue

        app = db.raw_get("applications", settlement["application_id"])
        pinned = app["pinned_streamer_tier"] if app else "BRONZE"
        gross = int(settlement.get("gross_sales_cents", 0))
        returned = int(settlement.get("returned_sales_cents", 0))

        # Recompute provisional gross_commission as the starting point.
        from services.calculations import calc_commission_provisional
        prov = calc_commission_provisional(
            pinned_tier=pinned, gross_sales_cents=gross,
        )
        previous_gross = prov["gross_commission_cents"]
        result = calc_commission_final(
            pinned_tier=pinned,
            gross_sales_cents=gross,
            returned_sales_cents=returned,
            previous_gross_commission_cents=previous_gross,
        )

        new_status = "READY_FOR_PAYOUT" if result["final_payout_cents"] >= 0 else "REVERSED"

        def m_settle(s, r=result, ns=new_status):
            s["commission_rate_bp"] = r["commission_rate_bp"]
            s["tier_bonus_cents"] = r["tier_bonus_cents"]
            s["tax_withholding_cents"] = r["tax_withholding_cents"]
            s["final_payout_cents"] = r["final_payout_cents"]
            s["status"] = ns
        db.update_entity("settlements", settlement["id"], m_settle)

        # Update application's gross_commission and net_payout snapshots.
        if app is not None:
            def m_app(a, r=result):
                a["gross_commission_cents"] = r["adjusted_gross_cents"]
                if new_status == "READY_FOR_PAYOUT":
                    a["net_payout_cents"] = r["final_payout_cents"]
            db.update_entity("applications", app["id"], m_app)

        # Net-negative penalty: violation_score += 1.
        if new_status == "REVERSED" and app is not None:
            def m_streamer(s):
                s["violation_score"] = s.get("violation_score", 0) + 1
            db.update_entity("streamers", app["streamer_id"], m_streamer)
            apply_cascade(app["streamer_id"])

    # --- 2. Violations whose 7-day appeal window has expired and no appeal ---
    for violation in list(db.raw_all("violations")):
        if violation.get("status") != "OPEN":
            continue
        created = clock.parse_iso(violation["created_at"])
        if now_dt <= created + timedelta(days=7):
            continue
        # Skip if any appeal exists for this violation
        if any(a.get("violation_id") == violation["id"]
               for a in db.raw_all("appeals")):
            continue

        def m_v(v, now_iso=now_iso):
            v["status"] = "ENFORCED"
            v["enforced_at"] = now_iso
        db.update_entity("violations", violation["id"], m_v)

        action = violation.get("penalty_action")
        streamer = db.raw_get("streamers", violation["streamer_id"])
        if streamer is None:
            continue

        if action == "WARNING":
            pass
        elif action == "FINE":
            def m_s(s, sev=int(violation.get("severity", 0))):
                s["violation_score"] = s.get("violation_score", 0) + sev
            db.update_entity("streamers", streamer["id"], m_s)
            apply_cascade(streamer["id"])
        elif action == "SUSPENSION":
            days = int(violation.get("suspension_days", 0))
            until = now_dt + timedelta(days=days)
            def m_s(s, sev=int(violation.get("severity", 0)), until_iso=clock.format_iso(until)):
                s["violation_score"] = s.get("violation_score", 0) + sev
                s["status"] = "SUSPENDED"
                s["suspension_until"] = until_iso
            db.update_entity("streamers", streamer["id"], m_s)
            # Cascade depth-3: cancel future SCHEDULED apps of the streamer
            _cancel_future_apps(streamer["id"])
            apply_cascade(streamer["id"])
        elif action == "BLACKLIST":
            def m_s(s, sev=int(violation.get("severity", 0))):
                s["violation_score"] = s.get("violation_score", 0) + sev
                s["status"] = "BLACKLISTED"
                s["suspension_until"] = None
            db.update_entity("streamers", streamer["id"], m_s)
            _cancel_future_apps(streamer["id"])
            apply_cascade(streamer["id"])

        audit.log(
            subject_kind="VIOLATION",
            subject_id=violation["id"],
            action="PENALTY_ENFORCED",
            actor_role=role,
            actor_id=user_id,
            from_state="OPEN",
            to_state="ENFORCED",
            payload_snapshot={"penalty_action": action},
        )

    # --- 3. Suspension expiry — re-activate streamers whose window passed ---
    for streamer in list(db.raw_all("streamers")):
        if streamer.get("status") != "SUSPENDED":
            continue
        until = streamer.get("suspension_until")
        if not until:
            continue
        if clock.parse_iso(until) <= now_dt:
            def m_s(s):
                s["status"] = "ACTIVE"
                s["suspension_until"] = None
            db.update_entity("streamers", streamer["id"], m_s)
            apply_cascade(streamer["id"])

    return success({"swept_at": now_iso})


def _cancel_future_apps(streamer_id: str) -> None:
    """Cancel every SCHEDULED future application of the streamer; apply refund
    cascade on the invoice and release product associations.
    """
    now_dt = clock.now()
    for app in list(db.raw_all("applications")):
        if app.get("streamer_id") != streamer_id:
            continue
        if app.get("operational_status") != "SCHEDULED":
            continue
        starts_at = clock.parse_iso(app["starts_at"])
        if starts_at <= now_dt:
            continue
        # Apply cancel cascade
        def m_app(a):
            a["operational_status"] = "CANCELLED"
        db.update_entity("applications", app["id"], m_app)

        invoice = _find_invoice_by_app(app["id"])
        if invoice is not None:
            deposit_due = int(invoice.get("deposit_due_cents", 0))
            if invoice.get("status") == "ISSUED":
                def m_inv(inv):
                    inv["status"] = "REFUNDED_FULL"
                    inv["refund_cents"] = 0
                db.update_entity("invoices", invoice["id"], m_inv)
            else:
                refund_cents = calc_refund(
                    starts_at=starts_at, deposit_due_cents=deposit_due,
                )
                if refund_cents >= deposit_due:
                    new_status = "REFUNDED_FULL"
                    refund_cents = deposit_due
                elif refund_cents > 0:
                    new_status = "REFUNDED_PARTIAL"
                else:
                    new_status = "REFUNDED_PARTIAL"
                def m_inv(inv, rc=refund_cents, ns=new_status):
                    inv["refund_cents"] = rc
                    inv["status"] = ns
                db.update_entity("invoices", invoice["id"], m_inv)

        release_all_for_application(app["id"])


def _find_invoice_by_app(app_id: str):
    for inv in db.raw_all("invoices"):
        if inv.get("application_id") == app_id:
            return inv
    return None


# ---------------------------------------------------------------------------
# External event injection
# ---------------------------------------------------------------------------

_EVENT_SOURCES = {"PAYMENT", "IM", "ECOMMERCE", "CONTENT_MOD"}
_EVENT_KINDS = {
    "DEPOSIT_PAID", "DEPOSIT_REFUNDED", "BROADCAST_GMV", "RETURN_REPORTED",
    "CONTENT_FLAGGED", "IM_CHANNEL_OPENED",
}


@bp.post("/_events/emit")
def events_emit():
    user_id, role = require_auth()
    require_role(role, ["PlatformAdmin"])
    body = request.get_json(silent=True) or {}

    for key in ("source", "kind", "occurred_at"):
        if key not in body:
            raise_err(ERR_VALIDATION_FAILED, f"Missing field: {key}")
    if body["source"] not in _EVENT_SOURCES:
        raise_err(ERR_VALIDATION_FAILED, "Invalid source")
    if body["kind"] not in _EVENT_KINDS:
        raise_err(ERR_VALIDATION_FAILED, "Invalid kind")

    application_id = body.get("application_id")
    streamer_id = body.get("streamer_id")

    if application_id is not None and db.raw_get("applications", application_id) is None:
        raise_err(ERR_NOT_FOUND, "Application not found")
    if streamer_id is not None and db.raw_get("streamers", streamer_id) is None:
        raise_err(ERR_NOT_FOUND, "Streamer not found")

    event_payload = {
        "source": body["source"],
        "kind": body["kind"],
        "application_id": application_id,
        "streamer_id": streamer_id,
        "amount_cents": int(body.get("amount_cents", 0) or 0),
        "occurred_at": body["occurred_at"],
    }
    event = db.create_entity("external_events", event_payload)

    # Apply the event's domain effect
    kind = body["kind"]
    if kind == "DEPOSIT_PAID":
        _apply_deposit_paid(event)
    elif kind == "DEPOSIT_REFUNDED":
        # We don't actively transition the invoice — refunds happen via cancel
        # cascade. Just record on AuditLog.
        audit.log(
            subject_kind="INVOICE",
            subject_id=event.get("application_id") or "",
            action="DEPOSIT_REFUNDED",
            actor_role=role,
            actor_id=user_id,
            payload_snapshot={"amount_cents": event.get("amount_cents", 0)},
        )
    elif kind == "BROADCAST_GMV":
        _apply_broadcast_gmv(event)
    elif kind == "RETURN_REPORTED":
        _apply_return_reported(event)
    elif kind == "CONTENT_FLAGGED":
        _apply_content_flagged(event, actor_role=role, actor_id=user_id)
    elif kind == "IM_CHANNEL_OPENED":
        audit.log(
            subject_kind="STREAMER",
            subject_id=event.get("streamer_id") or "",
            action="IM_CHANNEL_OPENED",
            actor_role=role,
            actor_id=user_id,
        )

    return success(event, http_status=201)


def _apply_deposit_paid(event: dict) -> None:
    app_id = event.get("application_id")
    if not app_id:
        return
    invoice = None
    for inv in db.raw_all("invoices"):
        if inv.get("application_id") == app_id:
            invoice = inv
            break
    if invoice is None:
        return
    if invoice.get("status") != "ISSUED":
        return
    if int(event.get("amount_cents", 0)) != int(invoice.get("deposit_due_cents", 0)):
        return  # Mismatch — no transition

    def m_inv(inv):
        inv["status"] = "DEPOSIT_PAID"
    db.update_entity("invoices", invoice["id"], m_inv)

    def m_app(a):
        a["deposit_paid"] = True
    db.update_entity("applications", app_id, m_app)


def _apply_broadcast_gmv(event: dict) -> None:
    app_id = event.get("application_id")
    if not app_id:
        return
    settlement = None
    for s in db.raw_all("settlements"):
        if s.get("application_id") == app_id:
            settlement = s
            break
    if settlement is None:
        return
    occurred = clock.parse_iso(event["occurred_at"])
    window_end = clock.parse_iso(settlement["return_window_ends_at"])
    if occurred > window_end:
        return
    if settlement.get("status") not in ("WINDOW_OPEN", "READY_FOR_PAYOUT", "PENDING"):
        return

    def m(s, amt=int(event.get("amount_cents", 0))):
        s["gross_sales_cents"] = s.get("gross_sales_cents", 0) + amt
    db.update_entity("settlements", settlement["id"], m)


def _apply_return_reported(event: dict) -> None:
    app_id = event.get("application_id")
    if not app_id:
        return
    settlement = None
    for s in db.raw_all("settlements"):
        if s.get("application_id") == app_id:
            settlement = s
            break
    if settlement is None:
        return
    occurred = clock.parse_iso(event["occurred_at"])
    window_end = clock.parse_iso(settlement["return_window_ends_at"])
    if occurred > window_end:
        return

    def m(s, amt=int(event.get("amount_cents", 0))):
        s["returned_sales_cents"] = s.get("returned_sales_cents", 0) + amt
    db.update_entity("settlements", settlement["id"], m)


def _apply_content_flagged(event: dict, *, actor_role: str, actor_id: str) -> None:
    streamer_id = event.get("streamer_id")
    if not streamer_id:
        return
    streamer = db.raw_get("streamers", streamer_id)
    if streamer is None:
        return
    refs = [event["id"]]
    penalty = calc_violation_penalty(
        violation_type="VIOLATING_CONTENT",
        evidence_refs_count=len(refs),
        current_violation_score=streamer.get("violation_score", 0),
    )
    violation = db.create_entity("violations", {
        "streamer_id": streamer_id,
        "application_id": event.get("application_id"),
        "violation_type": "VIOLATING_CONTENT",
        "evidence_refs": refs,
        "severity": penalty["severity"],
        "penalty_action": penalty["penalty_action"],
        "fine_cents": penalty["fine_cents"],
        "suspension_days": penalty["suspension_days"],
        "status": "OPEN",
        "enforced_at": None,
    })
    audit.log(
        subject_kind="VIOLATION",
        subject_id=violation["id"],
        action="CREATE",
        actor_role=actor_role,
        actor_id=actor_id,
        from_state=None,
        to_state="OPEN",
        payload_snapshot={"trigger": "CONTENT_FLAGGED"},
    )
