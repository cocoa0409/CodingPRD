"""Clock sweep (PRD §3.9): pinned five-step order, idempotent, deduped alerts."""

from datetime import date, timedelta

import db as _db
from db import parse_date
from services.pricing import (
    run_pricing,
    reevaluate_claim_after_change,
    touch,
)

RESPONSE_DAYS = {1: 30, 2: 30, 3: 45, 4: 60}


def _alert_exists(contract_id, alert_type, escalator_id=None, amendment_id=None):
    for a in _db.store.alerts.values():
        if (
            a["contract_id"] == contract_id
            and a["alert_type"] == alert_type
            and a.get("escalator_id") == escalator_id
            and a.get("amendment_id") == amendment_id
        ):
            return True
    return False


def _emit_alert(contract_id, alert_type, escalator_id=None, amendment_id=None):
    if _alert_exists(contract_id, alert_type, escalator_id, amendment_id):
        return None
    now = _db.now_iso()
    alert = {
        "id": _db.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "seq": _db.store.next_seq(),
        "contract_id": contract_id,
        "escalator_id": escalator_id,
        "amendment_id": amendment_id,
        "alert_type": alert_type,
        "trigger_date": _db.today().isoformat(),
        "status": "TRIGGERED",
    }
    _db.store.alerts[alert["id"]] = alert
    return alert


def run_clock_sweep():
    """Runs the five pinned steps; returns summary counts."""
    today = _db.today()
    escalators_applied = 0
    amendments_applied = 0
    appeals_expired = 0
    contracts_expired = 0
    alerts_generated = 0

    # Step 1: escalators SCHEDULED with effective_date <= today -> APPLIED
    due_escalators = [
        e for e in _db.store.escalators.values()
        if e["status"] == "SCHEDULED" and parse_date(e["effective_date"]) <= today
    ]
    due_escalators.sort(key=lambda e: (parse_date(e["effective_date"]), e["seq"]))
    for e in due_escalators:
        e["status"] = "APPLIED"
        e["applied_date"] = today.isoformat()
        touch(e)
        escalators_applied += 1

    # Step 2: amendments APPROVED with effective_date <= today -> EFFECTIVE
    due_amendments = [
        a for a in _db.store.amendments.values()
        if a["status"] == "APPROVED" and parse_date(a["effective_date"]) <= today
    ]
    due_amendments.sort(key=lambda a: (parse_date(a["effective_date"]), a["seq"]))
    for a in due_amendments:
        a["status"] = "EFFECTIVE"
        touch(a)
        amendments_applied += 1
        contract = _db.store.contracts.get(a["contract_id"])
        if contract is not None:
            touch(contract)
        # Supersede the chain this amendment names
        seen = set()
        cursor = a.get("supersedes_amendment_id")
        while cursor and cursor not in seen:
            seen.add(cursor)
            other = _db.store.amendments.get(cursor)
            if other is None:
                break
            if other["status"] == "EFFECTIVE":
                other["status"] = "SUPERSEDED"
                touch(other)
            cursor = other.get("supersedes_amendment_id")
        # AMENDMENT_EFFECTIVE alert, deduped per amendment
        if _emit_alert(a["contract_id"], "AMENDMENT_EFFECTIVE", amendment_id=a["id"]) is not None:
            alerts_generated += 1
        # Retroactive reprice cascade
        retro = a.get("retroactive_to_date")
        if retro is not None:
            retro_d = parse_date(retro)
            targets = [
                c for c in _db.store.claims.values()
                if c.get("priced_contract_id") == a["contract_id"]
                and c["pricing_status"] in {"PRICED", "REPRICED"}
                and parse_date(c["discharge_date"]) >= retro_d
            ]
            for claim in targets:
                run_pricing(claim, "RETROSPECTIVE")
                reevaluate_claim_after_change(claim, restate_original=True)

    # Step 3: appeals FILED with today > response_due_date -> EXPIRED
    due_appeals = [
        ap for ap in _db.store.appeals.values()
        if ap["status"] == "FILED"
        and ap.get("response_due_date") is not None
        and today > parse_date(ap["response_due_date"])
    ]
    due_appeals.sort(key=lambda ap: ap["seq"])
    for ap in due_appeals:
        ap["status"] = "EXPIRED"
        ap["outcome"] = "EXPIRED"
        ap["outcome_recorded_date"] = today.isoformat()
        touch(ap)
        appeals_expired += 1
        if ap["level"] == 4:
            case = _db.store.cases.get(ap["case_id"])
            if case is not None and case["status"] not in {
                "RECOVERED", "DENIED_FINAL", "WRITTEN_OFF", "WITHDRAWN",
            }:
                case["status"] = "DENIED_FINAL"
                touch(case)

    # Step 4: contracts ACTIVE with today > expiration_date -> EXPIRED (+ TERM_EXPIRED alert)
    due_contracts = [
        c for c in _db.store.contracts.values()
        if c["status"] == "ACTIVE" and today > parse_date(c["expiration_date"])
    ]
    due_contracts.sort(key=lambda c: c["seq"])
    for c in due_contracts:
        c["status"] = "EXPIRED"
        touch(c)
        contracts_expired += 1
        if _emit_alert(c["id"], "TERM_EXPIRED") is not None:
            alerts_generated += 1

    # Step 5: alert generation (deduped)
    for c in sorted(_db.store.contracts.values(), key=lambda c: c["seq"]):
        if c["status"] in {"ACTIVE", "SUSPENDED"}:
            days_left = (parse_date(c["expiration_date"]) - today).days
            if 0 <= days_left <= 90:
                if _emit_alert(c["id"], "TERM_EXPIRING_90") is not None:
                    alerts_generated += 1
            if 0 <= days_left <= 30:
                if _emit_alert(c["id"], "TERM_EXPIRING_30") is not None:
                    alerts_generated += 1
    for e in sorted(_db.store.escalators.values(), key=lambda e: e["seq"]):
        if e["status"] == "SCHEDULED":
            days_left = (parse_date(e["effective_date"]) - today).days
            if 0 <= days_left <= 30:
                if _emit_alert(e["contract_id"], "ESCALATOR_UPCOMING", escalator_id=e["id"]) is not None:
                    alerts_generated += 1

    return {
        "escalators_applied": escalators_applied,
        "amendments_applied": amendments_applied,
        "appeals_expired": appeals_expired,
        "contracts_expired": contracts_expired,
        "alerts_generated": alerts_generated,
    }
