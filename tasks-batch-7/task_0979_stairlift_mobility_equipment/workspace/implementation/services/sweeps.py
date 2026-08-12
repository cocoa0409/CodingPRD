"""Logical clock sweeps and cross-entity cascades."""

from datetime import timedelta

import db
from services.core import audit, touch, recompute_customer_outstanding, parse_iso8601

QUOTE_TTL_DAYS = 30
SERVICE_INTERVAL_DAYS = 180
SERVICE_LAPSE_OVERDUE_DAYS = 90


def run_sweeps():
    """Fire quote-expiry and service-plan-lapse sweeps for the current clock."""
    now = db.get_now()
    # Quote expiry sweep
    for q in list(db.quotes.values()):
        if q["status"] == "ISSUED" and q.get("expires_at"):
            exp = parse_iso8601(q["expires_at"])
            if exp is not None and exp <= now:
                q["status"] = "EXPIRED"
                touch(q)
                audit("Quote", q["id"], "QUOTE_EXPIRED", "system",
                      {"from": "ISSUED", "to": "EXPIRED"})
    # ServicePlan lapse sweep
    threshold = now - timedelta(days=SERVICE_LAPSE_OVERDUE_DAYS)
    for sp in list(db.service_plans.values()):
        if sp["status"] != "ACTIVE":
            continue
        ag = db.agreements.get(sp["agreement_id"])
        if ag is None or ag["status"] != "ACTIVE":
            continue
        due = parse_iso8601(sp["next_service_due_utc"])
        if due is not None and due < threshold:
            sp["status"] = "LAPSED"
            touch(sp)
            audit("ServicePlan", sp["id"], "SERVICE_PLAN_LAPSED", "system",
                  {"from": "ACTIVE", "to": "LAPSED"})
    # Rental month accrual: each ACTIVE rental agreement's unit gains a month
    # per logical-month rollover while ACTIVE. We track the last accrual month
    # on the agreement (internal field) and top up on each sweep.
    for ag in list(db.agreements.values()):
        if ag["status"] != "ACTIVE" or ag["mode"] != "RENTAL":
            continue
        unit = db.equipment_units.get(ag.get("equipment_unit_id"))
        if unit is None:
            continue
        # anchor: when agreement became ACTIVE (stored at activation)
        anchor_iso = ag.get("_activated_at")
        if not anchor_iso:
            continue
        anchor = parse_iso8601(anchor_iso)
        if anchor is None:
            continue
        # months elapsed since activation
        months = (now.year - anchor.year) * 12 + (now.month - anchor.month)
        if now.day < anchor.day:
            months -= 1
        if months < 0:
            months = 0
        last = ag.get("_rental_months_accrued", 0)
        if months > last:
            unit["lifetime_rental_months"] = unit.get("lifetime_rental_months", 0) + (months - last)
            touch(unit)
            ag["_rental_months_accrued"] = months
            touch(ag)


def supersede_quotes_for_assessment(assessment_id, actor_role="system"):
    """Cascade: any DRAFT/ISSUED quote referencing this assessment -> SUPERSEDED."""
    for q in list(db.quotes.values()):
        if q["home_assessment_id"] == assessment_id and q["status"] in ("DRAFT", "ISSUED"):
            q["status"] = "SUPERSEDED"
            touch(q)
            audit("Quote", q["id"], "QUOTE_SUPERSEDED", actor_role,
                  {"from": "DRAFT/ISSUED", "to": "SUPERSEDED",
                   "reason": "assessment superseded"})
