"""Resource representations.

Derived figures (cell counters, beam congestion, ledgers, the latest qualifying
scan verdict) are projected at serialisation time from the stored rows, so a
read can never disagree with the ledger a write admitted against.
"""

import capacity
from clock import fmt
from db import db, ordered
from numeric import num


def _common(record, with_common_fields=True):
    payload = {"id": record["id"], "created_at": fmt(record["created_at"])}
    if with_common_fields:
        payload["updated_at"] = fmt(record["updated_at"])
        payload["version"] = record["version"]
    return payload


def spectrum_license(record):
    payload = _common(record)
    payload.update(
        {
            "license_code": record["license_code"],
            "jurisdiction_code": record["jurisdiction_code"],
            "frequency_band": record["frequency_band"],
            "max_eirp_dbw": num(record["max_eirp_dbw"]),
            "expires_at": fmt(record["expires_at"]),
            "consumer_disclosure_version": record["consumer_disclosure_version"],
            "in_motion_permitted": record["in_motion_permitted"],
            "license_state": record["license_state"],
            "coordination_state": record["coordination_state"],
            "coordination_note": record["coordination_note"],
            "enforcement_reason": record["enforcement_reason"],
        }
    )
    return payload


def beam(record):
    payload = _common(record)
    payload.update(
        {
            "beam_code": record["beam_code"],
            "satellite_code": record["satellite_code"],
            "spectrum_license_id": record["spectrum_license_id"],
            "forward_capacity_mbps": num(record["forward_capacity_mbps"]),
            "oversubscription_limit": num(record["oversubscription_limit"]),
            "deprioritization_grace_gb": record["deprioritization_grace_gb"],
            "weighted_sold_mbps": num(capacity.weighted_sold_mbps(record)),
            "oversubscription_ratio": num(capacity.oversubscription_ratio(record)),
            "capacity_state": capacity.capacity_state(record),
            "beam_state": record["beam_state"],
            "billing_cycle_index": record["billing_cycle_index"],
            "last_cycle_closed_at": fmt(record["last_cycle_closed_at"]),
        }
    )
    return payload


def service_cell(record):
    payload = _common(record)
    payload.update(
        {
            "cell_code": record["cell_code"],
            "beam_id": record["beam_id"],
            "jurisdiction_code": record["jurisdiction_code"],
            "max_active_terminals": record["max_active_terminals"],
            "committed_terminal_count": capacity.committed_terminal_count(record),
            "reserved_slot_count": capacity.reserved_slot_count(record),
            "free_slot_count": capacity.free_slot_count(record),
            "waitlist_depth": capacity.waitlist_depth(record),
            "availability_state": capacity.availability_state(record),
        }
    )
    return payload


def service_plan(record):
    payload = _common(record)
    payload.update(
        {
            "plan_code": record["plan_code"],
            "committed_rate_mbps": num(record["committed_rate_mbps"]),
            "priority_tier": record["priority_tier"],
            "monthly_fee_cents": record["monthly_fee_cents"],
            "priority_data_gb": record["priority_data_gb"],
            "deprioritized_rate_mbps": num(record["deprioritized_rate_mbps"]),
            "overage_rate_cents_per_gb": record["overage_rate_cents_per_gb"],
            "roaming_allowed": record["roaming_allowed"],
            "in_motion_allowed": record["in_motion_allowed"],
        }
    )
    return payload


def _credit_balance_cents(subscriber_id):
    total = 0
    for credit in db.outage_credits.values():
        if credit["credit_state"] != "APPROVED":
            continue
        subscription = db.subscriptions.get(credit["subscription_id"])
        if subscription and subscription["subscriber_id"] == subscriber_id:
            total += credit["final_credit_cents"] or 0
    return total


def _pending_credit_cents(subscriber_id):
    total = 0
    for credit in db.outage_credits.values():
        if credit["credit_state"] not in ("DRAFT", "SUBMITTED"):
            continue
        subscription = db.subscriptions.get(credit["subscription_id"])
        if subscription and subscription["subscriber_id"] == subscriber_id:
            total += credit["provisional_credit_cents"] or 0
    return total


def subscriber(record):
    payload = _common(record)
    payload.update(
        {
            "email": record["email"],
            "full_name": record["full_name"],
            "jurisdiction_code": record["jurisdiction_code"],
            "account_state": record["account_state"],
            "credit_balance_cents": _credit_balance_cents(record["id"]),
            "pending_credit_cents": _pending_credit_cents(record["id"]),
            "pending_charge_cents": record["pending_charge_cents"],
        }
    )
    return payload


def service_order(record):
    payload = _common(record)
    payload.update(
        {
            "subscriber_id": record["subscriber_id"],
            "service_cell_id": record["service_cell_id"],
            "requested_plan_id": record["requested_plan_id"],
            "order_state": record["order_state"],
            "reservation_expires_at": fmt(record["reservation_expires_at"]),
            "waitlist_priority_score": record["waitlist_priority_score"],
            "promoted_at": fmt(record["promoted_at"]),
            "cancel_reason": record["cancel_reason"],
        }
    )
    return payload


def last_scan_verdict(terminal):
    """The newest scan at or after max(created_at, ownership_changed_at)."""
    floor_moment = terminal["created_at"]
    if terminal["ownership_changed_at"] is not None:
        floor_moment = max(floor_moment, terminal["ownership_changed_at"])
    qualifying = [
        s
        for s in db.scans.values()
        if s["terminal_id"] == terminal["id"] and s["scanned_at"] >= floor_moment
    ]
    if not qualifying:
        return None
    qualifying.sort(key=lambda s: (s["scanned_at"], s["created_at"], s["_seq"]))
    return qualifying[-1]["scan_verdict"]


def terminal(record):
    payload = _common(record)
    payload.update(
        {
            "serial_number": record["serial_number"],
            "subscriber_id": record["subscriber_id"],
            "replaces_terminal_id": record["replaces_terminal_id"],
            "warranty_expires_at": fmt(record["warranty_expires_at"]),
            "terminal_state": record["terminal_state"],
            "installed_at": fmt(record["installed_at"]),
            "ownership_changed_at": fmt(record["ownership_changed_at"]),
            "last_scan_verdict": last_scan_verdict(record),
            "return_condition": record["return_condition"],
        }
    )
    return payload


def obstruction_scan(record):
    payload = _common(record, with_common_fields=False)
    payload.update(
        {
            "terminal_id": record["terminal_id"],
            "obstructed_sample_count": record["obstructed_sample_count"],
            "total_sample_count": record["total_sample_count"],
            "obstruction_pct": num(record["obstruction_pct"]),
            "scan_verdict": record["scan_verdict"],
            "scanned_at": fmt(record["scanned_at"]),
        }
    )
    return payload


def subscription(record):
    payload = _common(record)
    payload.update(
        {
            "subscriber_id": record["subscriber_id"],
            "service_order_id": record["service_order_id"],
            "service_cell_id": record["service_cell_id"],
            "service_plan_id": record["service_plan_id"],
            "terminal_id": record["terminal_id"],
            "deauthorized_by_license_id": record["deauthorized_by_license_id"],
            "service_state": record["service_state"],
            "authorization_state": record["authorization_state"],
            "priority_state": record["priority_state"],
            "disclosure_ack_state": record["disclosure_ack_state"],
            "disclosure_version_issued": record["disclosure_version_issued"],
            "disclosure_ack_deadline_at": fmt(record["disclosure_ack_deadline_at"]),
            "cycle_priority_gb_used": num(record["cycle_priority_gb_used"]),
            "cycle_billing_index": record["cycle_billing_index"],
            "cycle_charge_cents": record["cycle_charge_cents"],
            "effective_rate_mbps": num(capacity.effective_rate_mbps(record)),
            "activated_at": fmt(record["activated_at"]),
            "deprioritized_at": fmt(record["deprioritized_at"]),
            "terminated_at": fmt(record["terminated_at"]),
            "suspension_reason": record["suspension_reason"],
        }
    )
    return payload


def usage_record(record):
    payload = _common(record, with_common_fields=False)
    payload.update(
        {
            "subscription_id": record["subscription_id"],
            "billing_cycle_index": record["billing_cycle_index"],
            "gb_used": num(record["gb_used"]),
            "counted": record["counted"],
            "recorded_at": fmt(record["recorded_at"]),
        }
    )
    return payload


def roaming_authorization(record):
    payload = _common(record)
    payload.update(
        {
            "subscription_id": record["subscription_id"],
            "mode": record["mode"],
            "target_jurisdiction_code": record["target_jurisdiction_code"],
            "target_service_cell_id": record["target_service_cell_id"],
            "effective_from": fmt(record["effective_from"]),
            "effective_until": fmt(record["effective_until"]),
            "auth_state": record["auth_state"],
            "info_round_count": record["info_round_count"],
            "governing_license_id": record["governing_license_id"],
            "decision_note": record["decision_note"],
            "revoked_reason": record["revoked_reason"],
        }
    )
    return payload


def outage_event(record):
    payload = _common(record)
    payload.update(
        {
            "beam_id": record["beam_id"],
            "cause": record["cause"],
            "severity": record["severity"],
            "started_at": fmt(record["started_at"]),
            "ended_at": fmt(record["ended_at"]),
            "event_state": record["event_state"],
            "outage_minutes": record["outage_minutes"],
            "credit_eligible": record["credit_eligible"],
            "generated_credit_count": record["generated_credit_count"],
        }
    )
    return payload


def outage_credit(record):
    payload = _common(record)
    payload.update(
        {
            "subscription_id": record["subscription_id"],
            "outage_event_id": record["outage_event_id"],
            "provisional_credit_cents": record["provisional_credit_cents"],
            "final_credit_cents": record["final_credit_cents"],
            "credit_state": record["credit_state"],
            "submitted_by_user_id": record["submitted_by_user_id"],
            "decided_by_user_id": record["decided_by_user_id"],
            "decision_reason": record["decision_reason"],
        }
    )
    return payload


def collection(records, serializer):
    return [serializer(record) for record in records]


def default_order(records):
    return ordered(records)
