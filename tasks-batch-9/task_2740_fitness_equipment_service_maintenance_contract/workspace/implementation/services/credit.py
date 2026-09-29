"""Downtime events, the two credit variants and period reconciliation."""
import db
from services import calc, domain


def open_event(contract, equipment_row, call, started_at):
    """Every service call is born with exactly one OPEN downtime event."""
    row = db.base_row()
    row.update({
        "contract_id": contract["id"],
        "equipment_id": equipment_row["id"],
        "service_call_id": call["id"],
        "started_at": db.iso(started_at),
        "ended_at": None,
        "mitigated_at": None,
        "effective_end_at": None,
        "downtime_minutes": None,
        "operating_downtime_minutes": None,
        "provisional_credit_cents": None,
        "final_credit_cents": None,
        "posted_credit_cents": None,
        "status": "OPEN",
        "period_key": None,
        "waive_reason": None,
    })
    db.downtime_events[row["id"]] = row
    return row


def event_for_call(call_id, statuses=None):
    for row in db.ordered(db.downtime_events):
        if row["service_call_id"] != call_id:
            continue
        if statuses is not None and row["status"] not in statuses:
            continue
        return row
    return None


def close_event(event, contract, club):
    """OPEN -> CLOSED with the provisional wall-clock variant."""
    ended_at = db.now()
    started_at = db.parse_iso(event["started_at"])
    mitigated_at = db.parse_iso(event["mitigated_at"])
    effective_end = mitigated_at if mitigated_at is not None else ended_at
    downtime_minutes = calc.minutes_between(started_at, effective_end)
    operating_minutes = calc.operating_overlap_minutes(
        started_at, effective_end,
        club["operating_open_minute"], club["operating_close_minute"],
    )
    provisional = calc.credit_cents(downtime_minutes, contract["coverage_tier"])
    db.apply_changes(event, {
        "status": "CLOSED",
        "ended_at": db.iso(ended_at),
        "effective_end_at": db.iso(effective_end),
        "downtime_minutes": downtime_minutes,
        "operating_downtime_minutes": operating_minutes,
        "period_key": calc.period_key_of(effective_end),
        "provisional_credit_cents": provisional,
    })
    return event


def waive_event(event, reason):
    """Reverse whatever the event had already produced, then mark it WAIVED."""
    previous_status = event["status"]
    contract = db.contracts.get(event["contract_id"])
    equipment_row = db.equipment.get(event["equipment_id"])

    if previous_status in ("CLOSED", "RECONCILED") and contract is not None:
        changes = {
            "credit_provisional_cents":
                contract["credit_provisional_cents"] - (event["provisional_credit_cents"] or 0),
        }
        if previous_status == "RECONCILED":
            posted = event["posted_credit_cents"] or 0
            final = event["final_credit_cents"] or 0
            changes["credit_accrued_cents"] = contract["credit_accrued_cents"] - posted
            changes["credit_forgone_cents"] = contract["credit_forgone_cents"] - (final - posted)
        db.apply_changes(contract, changes)

    db.apply_changes(event, {"status": "WAIVED", "waive_reason": reason})

    if previous_status in ("CLOSED", "RECONCILED") and equipment_row is not None:
        domain.refresh_equipment_condition(equipment_row, {
            "downtime_minutes_ytd":
                equipment_row["downtime_minutes_ytd"] - (event["downtime_minutes"] or 0),
        })
        domain.recompute_contract_fleet(equipment_row["club_id"])
    return event


def reconcile_period(contract, period_key):
    """Settle one period: the cap is consumed in created_at ascending order."""
    candidates = db.ordered(
        db.downtime_events,
        lambda e: (e["contract_id"] == contract["id"]
                   and e["status"] == "CLOSED"
                   and e["period_key"] == period_key),
    )
    final_total = 0
    posted_total = 0
    forgone_total = 0
    accrued = contract["credit_accrued_cents"]
    forgone = contract["credit_forgone_cents"]

    for event in candidates:
        final = calc.credit_cents(
            event["operating_downtime_minutes"] or 0, contract["coverage_tier"]
        )
        remaining_cap = contract["credit_cap_cents"] - accrued
        if remaining_cap < 0:
            remaining_cap = 0
        posted = final if final < remaining_cap else remaining_cap
        event_forgone = final - posted
        db.apply_changes(event, {
            "status": "RECONCILED",
            "final_credit_cents": final,
            "posted_credit_cents": posted,
        })
        # The ledger advances before the next event is considered, but the whole
        # reconciliation is one contract mutation: version rises by exactly one.
        accrued = accrued + posted
        forgone = forgone + event_forgone
        contract["credit_accrued_cents"] = accrued
        contract["credit_forgone_cents"] = forgone
        final_total += final
        posted_total += posted
        forgone_total += event_forgone

    contract["last_reconciled_period_key"] = period_key
    db.touch(contract)
    return {
        "period_key": period_key,
        "reconciled_event_count": len(candidates),
        "final_credit_total_cents": final_total,
        "posted_credit_cents": posted_total,
        "forgone_credit_cents": forgone_total,
        "contract_credit_accrued_cents": contract["credit_accrued_cents"],
        "contract_version": contract["version"],
    }


def credit_summary(contract):
    events = [e for e in db.downtime_events.values() if e["contract_id"] == contract["id"]]
    return {
        "contract_id": contract["id"],
        "credit_provisional_cents": contract["credit_provisional_cents"],
        "credit_accrued_cents": contract["credit_accrued_cents"],
        "credit_forgone_cents": contract["credit_forgone_cents"],
        "credit_cap_cents": contract["credit_cap_cents"],
        "open_event_count": len([e for e in events if e["status"] == "OPEN"]),
        "closed_event_count": len([e for e in events if e["status"] == "CLOSED"]),
        "reconciled_event_count": len([e for e in events if e["status"] == "RECONCILED"]),
    }
