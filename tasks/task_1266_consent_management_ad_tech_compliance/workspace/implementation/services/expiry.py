"""Lazy time-based compliance evaluation (PRD section 2.4).

evaluate_time_based_effects() is idempotent and is invoked after clock-set
and around reads/writes:
  (a) ConsentRecords in GRANTED|WITHDRAWN whose expires_at_pinned <= now
      transition to EXPIRED with source_of_decision EXPIRY. A previously
      GRANTED record also decrements the property's granted_purpose_count.
  (b) RegulatorySweeps in OPEN|EVIDENCE_COLLECTION with response_due_at < now
      auto-escalate with the full escalation cascade.
Boundary discipline: expiry fires when now >= expires_at_pinned (the expiry
instant itself counts); escalation fires strictly when now > response_due_at.
"""
from db import store, touch
from clock import get_now
from services.consent import parse_dt, adjust_granted_count
from services.sweep import escalate_sweep


def evaluate_time_based_effects():
    now = get_now()

    # (a) consent retention expiry (pinned horizon is authoritative)
    for record in list(store.get("consent_records", {}).values()):
        if record.get("status") not in ("GRANTED", "WITHDRAWN"):
            continue
        expires = parse_dt(record.get("expires_at_pinned"))
        if expires is None or now < expires:
            continue
        previous = record.get("status")
        record["status"] = "EXPIRED"
        record["source_of_decision"] = "EXPIRY"
        touch(record)
        if previous == "GRANTED":
            adjust_granted_count(record.get("property_id"), -1)

    # (b) sweep deadline escalation (strictly past the deadline)
    for sweep in list(store.get("regulatory_sweeps", {}).values()):
        if sweep.get("status") not in ("OPEN", "EVIDENCE_COLLECTION"):
            continue
        due = parse_dt(sweep.get("response_due_at"))
        if due is None or now <= due:
            continue
        escalate_sweep(sweep)
