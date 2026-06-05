"""Core domain logic: common fields, posture, cascades, event emission."""
from __future__ import annotations

import datetime as _dt
from typing import Optional

import db
from services import calculations


# ----------------------- Common fields & timestamps -----------------------

def stamp_create_common(record: dict) -> dict:
    now = db.now_utc()
    record["id"] = db.gen_uuid()
    record["created_at"] = db.iso_format(now)
    record["updated_at"] = db.iso_format(now)
    record["version"] = 1
    record["_created_seq"] = db.next_seq()
    record["_created_at_dt"] = now
    record["_updated_at_dt"] = now
    return record


def stamp_update_common(record: dict) -> dict:
    now = db.now_utc()
    record["updated_at"] = db.iso_format(now)
    record["version"] = int(record.get("version", 1)) + 1
    record["_updated_at_dt"] = now
    return record


def emit_event(business_entity_id: str, event_type: str, payload: dict) -> dict:
    now = db.now_utc()
    ev = {
        "id": db.gen_uuid(),
        "business_entity_id": business_entity_id,
        "event_type": event_type,
        "event_payload": payload,
        "event_at": db.iso_format(now),
        "_created_seq": db.next_seq(),
        "_event_at_dt": now,
    }
    db.compliance_events[ev["id"]] = ev
    return ev


# ----------------------- Child enumeration helpers -----------------------

def children_registered_agents(business_entity_id: str) -> list:
    return [r for r in db.registered_agents.values()
            if r["business_entity_id"] == business_entity_id]


def children_ein_applications(business_entity_id: str) -> list:
    return [r for r in db.ein_applications.values()
            if r["business_entity_id"] == business_entity_id]


def children_operating_agreements(business_entity_id: str) -> list:
    return [r for r in db.operating_agreements.values()
            if r["business_entity_id"] == business_entity_id]


def children_annual_reports(business_entity_id: str) -> list:
    return [r for r in db.annual_reports.values()
            if r["business_entity_id"] == business_entity_id]


def children_foreign_qualifications(business_entity_id: str) -> list:
    return [r for r in db.foreign_qualifications.values()
            if r["business_entity_id"] == business_entity_id]


def children_boi_disclosures(business_entity_id: str) -> list:
    return [r for r in db.boi_disclosures.values()
            if r["business_entity_id"] == business_entity_id]


def active_registered_agent_count(business_entity_id: str) -> int:
    """Count home-state ACTIVE agents for the parent BE.

    PRD §3.3: "Foreign-state agents ... do not satisfy the home-state coverage
    requirement and never count toward the activation precondition for the
    parent." So the home-state coverage counter excludes foreign-state agents.
    """
    be = db.business_entities.get(business_entity_id)
    if be is None:
        return 0
    home_code = be["formation_state_code"]
    return sum(1 for r in children_registered_agents(business_entity_id)
               if r["status"] == "ACTIVE" and r["agent_state_code"] == home_code)


# ----------------------- Compliance posture -----------------------

def compute_compliance_posture(business_entity_id: str, at_clock: Optional[_dt.datetime] = None) -> str:
    """Compute compliance_posture per §1.3 / §3.6.

    Priority cascade:
      DISSOLVED  -> FROZEN
      SUSPENDED  -> FROZEN
      any AnnualReport DELINQUENT for this entity -> RESTRICTED
      no ACTIVE RegisteredAgent             -> RESTRICTED
      BOI exists and most-recent.submitted_at + 365 days < now -> RESTRICTED
      else                                  -> GOOD_STANDING
    """
    be = db.business_entities.get(business_entity_id)
    if not be:
        return "GOOD_STANDING"
    if be["status"] == "DISSOLVED":
        return "FROZEN"
    if be["status"] == "SUSPENDED":
        return "FROZEN"
    for ar in children_annual_reports(business_entity_id):
        if ar["status"] == "DELINQUENT":
            return "RESTRICTED"
    if active_registered_agent_count(business_entity_id) == 0:
        return "RESTRICTED"
    # BOI staleness check: most-recent submitted_at + 365 days < now (strict)
    bois = children_boi_disclosures(business_entity_id)
    if bois:
        # Most-recent SUBMITTED -- by submitted_at, only those with submitted_at set
        submitted = [b for b in bois if b.get("_submitted_at_dt") is not None]
        if submitted:
            most_recent = max(submitted, key=lambda b: b["_submitted_at_dt"])
            now = at_clock if at_clock is not None else db.now_utc()
            cutoff = most_recent["_submitted_at_dt"] + _dt.timedelta(days=365)
            if cutoff < now:
                return "RESTRICTED"
    return "GOOD_STANDING"


# ----------------------- BusinessEntity computed fields -----------------------

def recompute_be_fiscal_fields(be: dict) -> None:
    reports = children_annual_reports(be["id"])
    filed = [r for r in reports if r["status"] == "FILED"]
    if filed:
        be["franchise_tax_paid_through_year"] = max(r["period_year"] for r in filed)
        be["cumulative_franchise_tax_paid_cents"] = sum(
            r["franchise_tax_amount_cents"] + r["late_fee_cents"] for r in filed
        )
    else:
        be["franchise_tax_paid_through_year"] = 0
        be["cumulative_franchise_tax_paid_cents"] = 0


# ----------------------- BusinessEntity state machine -----------------------

def try_promote_forming_to_active(be: dict) -> None:
    """Auto-promote BusinessEntity FORMING -> ACTIVE if preconditions hold.

    Conditions (SCAFFOLD §1.2 / PRD §3.2):
      - exactly one RegisteredAgent in ACTIVE
      - exactly one EINApplication in ISSUED
      - if entity_type in {LLC, LP}: at least one OperatingAgreement in EXECUTED
    """
    if be["status"] != "FORMING":
        return
    if active_registered_agent_count(be["id"]) != 1:
        return
    issued_eins = [e for e in children_ein_applications(be["id"]) if e["status"] == "ISSUED"]
    if len(issued_eins) != 1:
        return
    if be["entity_type"] in ("LLC", "LP"):
        executed = [o for o in children_operating_agreements(be["id"]) if o["status"] == "EXECUTED"]
        if not executed:
            return
    # Transition
    old = be["status"]
    be["status"] = "ACTIVE"
    stamp_update_common(be)
    be["compliance_posture"] = compute_compliance_posture(be["id"])
    emit_event(be["id"], "STATUS_CHANGED", {"from": old, "to": "ACTIVE"})


def try_active_to_delinquent(be: dict) -> None:
    if be["status"] != "ACTIVE":
        return
    has_delinquent = any(r["status"] == "DELINQUENT" for r in children_annual_reports(be["id"]))
    if not has_delinquent:
        return
    old = be["status"]
    be["status"] = "DELINQUENT"
    stamp_update_common(be)
    be["compliance_posture"] = compute_compliance_posture(be["id"])
    emit_event(be["id"], "STATUS_CHANGED", {"from": old, "to": "DELINQUENT"})


def try_delinquent_to_active(be: dict) -> None:
    if be["status"] != "DELINQUENT":
        return
    now = db.now_utc()
    clock_year = now.year
    # No AnnualReport with status=DELINQUENT or DRAFT remains for period_year < clock_year.
    for ar in children_annual_reports(be["id"]):
        if ar["period_year"] < clock_year and ar["status"] in ("DRAFT", "DELINQUENT"):
            return
    # Also: PRD §3.6 phrasing requires every delinquent for period_year < clock_year is now FILED/VOIDED.
    old = be["status"]
    be["status"] = "ACTIVE"
    stamp_update_common(be)
    be["compliance_posture"] = compute_compliance_posture(be["id"])
    emit_event(be["id"], "STATUS_CHANGED", {"from": old, "to": "ACTIVE"})


def try_delinquent_to_suspended(be: dict) -> None:
    if be["status"] != "DELINQUENT":
        return
    delinquent_years = sorted({r["period_year"] for r in children_annual_reports(be["id"])
                               if r["status"] == "DELINQUENT"})
    # need two consecutive period_year values
    consecutive = False
    for i in range(len(delinquent_years) - 1):
        if delinquent_years[i + 1] == delinquent_years[i] + 1:
            consecutive = True
            break
    if not consecutive:
        return
    old = be["status"]
    be["status"] = "SUSPENDED"
    stamp_update_common(be)
    be["compliance_posture"] = compute_compliance_posture(be["id"])
    emit_event(be["id"], "STATUS_CHANGED", {"from": old, "to": "SUSPENDED"})


def recompute_be_posture(be: dict) -> None:
    be["compliance_posture"] = compute_compliance_posture(be["id"])


def cascade_after_child_change(be: dict) -> None:
    """After any child mutation, recompute fiscal fields, attempt auto BE transitions,
    refresh posture.
    """
    recompute_be_fiscal_fields(be)
    # Try various automatic transitions; the order matches §1.2 triggers.
    try_promote_forming_to_active(be)
    try_active_to_delinquent(be)
    try_delinquent_to_suspended(be)
    try_delinquent_to_active(be)
    recompute_be_posture(be)


# ----------------------- Time-driven cascades -----------------------

def reevaluate_time_gated_transitions() -> None:
    """After clock advance: flip any DRAFT AnnualReport whose deadline passed
    to DELINQUENT; cascade parent BE ACTIVE->DELINQUENT->SUSPENDED.
    """
    now = db.now_utc()
    # Sort reports by created_seq for deterministic processing
    reports = sorted(db.annual_reports.values(), key=lambda r: r["_created_seq"])
    affected_be_ids: set = set()
    for ar in reports:
        if ar["status"] != "DRAFT":
            continue
        deadline = calculations.annual_report_deadline_utc(ar["period_year"])
        if now > deadline:
            ar["status"] = "DELINQUENT"
            stamp_update_common(ar)
            emit_event(ar["business_entity_id"], "DELINQUENT_AUTO", {
                "annual_report_id": ar["id"],
                "period_year": ar["period_year"],
            })
            affected_be_ids.add(ar["business_entity_id"])
    for be_id in affected_be_ids:
        be = db.business_entities.get(be_id)
        if be is None:
            continue
        # Recompute / cascade
        recompute_be_fiscal_fields(be)
        try_active_to_delinquent(be)
        try_delinquent_to_suspended(be)
        recompute_be_posture(be)


# ----------------------- Snapshot helpers -----------------------

# (No snapshot endpoint listed in §1.5, but logic exists in §1.3 variants.
# We do not implement a route for it because no endpoint is declared.)
