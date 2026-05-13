"""Operational endpoints: external events, clock, sweep."""
import datetime as _dt

import clock as clock_module
from clock import format_dt, iso_now, now, parse_dt
from db import LOCK, get_db, new_id
from errors import APIError
from helpers import (new_entity, require_body, require_enum, require_field, touch)
from middleware import require_roles
from response import success
from services import audit, elder as elder_svc, waitlist as waitlist_svc


VALID_SOURCES = {"PAYMENT", "IM", "HOSPITAL", "GOVT_SUBSIDY"}


def _apply_external_event(source, event_type, payload, actor_id, actor_role):
    """Apply an external event's domain mutation. Returns (result_status, error_id?, message?).

    result_status is one of APPLIED, REJECTED. DUPLICATE handled by caller.
    """
    db = get_db()
    try:
        if source == "PAYMENT":
            if event_type == "PAYMENT_RECEIVED":
                bill_id = payload.get("bill_id")
                ref = payload.get("external_payment_ref")
                if not bill_id or not ref:
                    raise APIError("ERR_VALIDATION", "PAYMENT_RECEIVED requires bill_id+external_payment_ref", 422)
                b = db.bills.get(bill_id)
                if b is None:
                    raise APIError("ERR_FK_NOT_FOUND", f"Bill {bill_id} not found", 404)
                if b["status"] != "FINALIZED":
                    raise APIError("ERR_BILL_NOT_FINALIZED", "Bill not in FINALIZED", 409)
                existing = db.bill_external_payment_refs.get(ref)
                if existing is not None and existing != bill_id:
                    raise APIError("ERR_DUPLICATE_PAYMENT", "external_payment_ref reused", 409)
                b["status"] = "PAID"
                b["paid_at"] = iso_now()
                b["external_payment_ref"] = ref
                db.bill_external_payment_refs[ref] = bill_id
                touch(b)
                elder_svc.recompute_outstanding_balance(b["elder_id"])
                return "APPLIED", None, None, b
        elif source == "HOSPITAL":
            if event_type == "ELDER_TRANSFERRED_TO_HOSPITAL":
                elder_id = payload.get("elder_id")
                elder = db.elders.get(elder_id)
                if elder is None:
                    raise APIError("ERR_FK_NOT_FOUND", f"Elder {elder_id} not found", 404)
                elder_svc.go_on_leave(elder, actor_id, actor_role,
                                      reason=payload.get("reason", "hospital transfer"))
                return "APPLIED", None, None, elder
        elif source == "GOVT_SUBSIDY":
            if event_type == "SUBSIDY_GRANT":
                bill_id = payload.get("bill_id")
                amount = payload.get("amount_cents")
                b = db.bills.get(bill_id)
                if b is None:
                    raise APIError("ERR_FK_NOT_FOUND", f"Bill {bill_id} not found", 404)
                if not isinstance(amount, int) or isinstance(amount, bool) or amount < 0:
                    raise APIError("ERR_VALIDATION", "amount_cents must be a non-negative int", 422)
                # Credit subsidy line for a draft or finalized bill
                if b["status"] not in ("DRAFT", "FINALIZED"):
                    raise APIError("ERR_INVALID_STATE",
                                   "Subsidy grant requires DRAFT or FINALIZED bill", 409)
                b["government_subsidy_cents"] = int(b.get("government_subsidy_cents", 0)) + amount
                touch(b)
                return "APPLIED", None, None, b
        elif source == "IM":
            # IM events are informational — we acknowledge but don't mutate domain state
            return "APPLIED", None, None, None

        raise APIError("ERR_VALIDATION",
                       f"Unsupported event_type {event_type} for source {source}", 422)
    except APIError as e:
        return "REJECTED", e.error_id, e.message, None


def register(app):

    @app.post("/_events/external")
    @require_roles("SystemSync")
    def ingest_event(user_id, role):
        body = require_body()
        source = require_enum(body, "source", VALID_SOURCES)
        idempotency_key = require_field(body, "idempotency_key", str)
        event_type = require_field(body, "event_type", str)
        payload = body.get("payload") or {}
        if not isinstance(payload, dict):
            raise APIError("ERR_VALIDATION", "payload must be an object", 422)
        with LOCK:
            db = get_db()
            existing = db.external_event_index.get((source, idempotency_key))
            if existing is not None:
                prior = db.external_events.get(existing)
                # PRD §2.7 #26: duplicate ingestion -> ERR_DUPLICATE_EVENT
                # Replay original processing result but raise the error.
                raise APIError(
                    "ERR_DUPLICATE_EVENT",
                    f"Event already processed; prior result_status={prior.get('result_status')}",
                    409,
                )
            # First time: apply
            result_status, err_id, msg, _target = _apply_external_event(
                source, event_type, payload, user_id, role)
            ev_id = new_id()
            event_row = {
                "id": ev_id,
                "source": source,
                "idempotency_key": idempotency_key,
                "event_type": event_type,
                "payload": payload,
                "applied_at": iso_now(),
                "result_status": result_status,
                "created_at": iso_now(),
            }
            db.external_events[ev_id] = event_row
            db.external_event_index[(source, idempotency_key)] = ev_id
            if result_status == "REJECTED":
                raise APIError(err_id, msg, _ERR_HTTP.get(err_id, 422))
            return success(dict(event_row))

    @app.post("/_clock/advance")
    @require_roles("Admin")
    def clock_advance(user_id, role):
        body = require_body()
        seconds = require_field(body, "seconds", int)
        clock_module.advance(seconds)
        return success({"advanced_seconds": seconds, "now": iso_now()})

    @app.post("/_sweep/run")
    @require_roles("Admin")
    def sweep_run(user_id, role):
        with LOCK:
            _run_sweep(user_id, role)
        return success({"swept_at": iso_now()})


# Re-import error HTTP codes lazily
from errors import ERROR_CATALOG as _ERR_HTTP


def _run_sweep(actor_id, actor_role):
    """Periodic sweep:
      - WaitlistEntry OFFERED -> QUEUED if offer >= 24h old.
      - CarePlan ACTIVE -> UNDER_REVIEW if next_review_due_at has passed.
      - CarePlan SUPERSEDED -> ARCHIVED if >= 30 days in state.
      - VisitReservation RESERVED -> DENIED if mode==LOCKDOWN.
    """
    db = get_db()
    current = now()

    # Waitlist OFFERED expiry
    for entry in list(db.waitlist.values()):
        if entry["status"] == "OFFERED":
            offered_at = db.waitlist_offered_at.get(entry["id"])
            if offered_at is None:
                continue
            elapsed = (current - offered_at).total_seconds()
            if elapsed >= 24 * 3600:
                bed_id = entry.get("offered_bed_id")
                entry["status"] = "QUEUED"
                entry["offered_bed_id"] = None
                db.waitlist_offered_at.pop(entry["id"], None)
                if bed_id:
                    bed = db.beds.get(bed_id)
                    if bed is not None and bed["status"] == "AVAILABLE":
                        waitlist_svc.promote_for_bed(bed)

    # CarePlan ACTIVE -> UNDER_REVIEW when due
    for plan in list(db.care_plans.values()):
        if plan["status"] == "ACTIVE":
            due = plan.get("next_review_due_at")
            if due is not None:
                due_dt = parse_dt(due)
                if current >= due_dt:
                    prev = plan["status"]
                    plan["status"] = "UNDER_REVIEW"
                    touch(plan)
                    audit.log(actor_role, actor_id, "CarePlan", plan["id"],
                              "REVIEW_FLAGGED", prev, plan["status"])

    # SUPERSEDED -> ARCHIVED after 30 days
    for plan in list(db.care_plans.values()):
        if plan["status"] == "SUPERSEDED":
            since = db.care_plans_superseded_at.get(plan["id"])
            if since is None:
                continue
            if (current - since).days >= 30:
                prev = plan["status"]
                plan["status"] = "ARCHIVED"
                touch(plan)
                audit.log(actor_role, actor_id, "CarePlan", plan["id"],
                          "ARCHIVE", prev, plan["status"])

    # LOCKDOWN sweep — RESERVED -> DENIED
    cfg = db.epidemic_config
    if cfg is not None and cfg.get("mode") == "LOCKDOWN":
        for r in list(db.visit_reservations.values()):
            if r["status"] == "RESERVED":
                r["status"] = "DENIED"
                touch(r)
