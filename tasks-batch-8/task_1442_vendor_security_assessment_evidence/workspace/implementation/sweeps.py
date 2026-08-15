"""Clock-driven auto-transitions (PRD §2.6): fired when the logical clock is
advanced. Cycle expiry sweep (§3.3), risk-acceptance expiry sweep (§3.6), and
the reassessment-due sweep (§3.8). Every resource the sweeps touch gets its
own version bump and updated_at refresh (PRD §2.11).
"""
from datetime import timedelta

import calc
import db
import helpers
import util


def _cycle_expiry_sweep(now):
    for cycle in sorted(db.cycles.values(), key=lambda c: c["_seq"]):
        if cycle["status"] != "ISSUED" or cycle.get("response_due_at") is None:
            continue
        due = util.parse_dt(cycle["response_due_at"])
        if not now > due:
            continue
        submitted = any(r["cycle_id"] == cycle["id"] and r["status"] == "SUBMITTED"
                        for r in db.responses.values())
        if submitted:
            continue
        vendor = db.vendors.get(cycle["vendor_id"])
        cycle["status"] = "EXPIRED"
        helpers.touch("cycles", cycle)
        if vendor is None:
            continue
        previous_due = (util.parse_dt(vendor["next_reassessment_due"])
                        if vendor.get("next_reassessment_due") else None)
        policy = helpers.active_policy()
        months = (policy or {}).get("tier4_reassessment_months", 6)
        new_due = util.add_months(now, months)
        vendor["posture"] = "SUSPENDED"
        vendor["active_cycle_id"] = None
        vendor["next_reassessment_due"] = util.iso(new_due)
        helpers.append_schedule(vendor["id"], "ALERT_ESCALATION",
                                previous_due, new_due, None)
        helpers.touch("vendors", vendor)
        helpers.refresh_risk(vendor)


def _acceptance_expiry_sweep(now):
    for acc in sorted(db.acceptances.values(), key=lambda r: r["_seq"]):
        if acc["status"] != "APPROVED":
            continue
        try:
            expires = util.parse_dt(acc["expires_at"])
        except (ValueError, TypeError):
            continue
        if not now > expires:
            continue
        acc["status"] = "EXPIRED"
        helpers.touch("acceptances", acc)
        cycle = db.cycles.get(acc["cycle_id"])
        reopened = 0
        for eid in acc.get("exception_ids", []):
            exc = db.exceptions.get(eid)
            if exc is not None and exc["status"] == "CLOSED_ACCEPTED":
                exc["status"] = "OPEN"
                exc["closure_reason"] = "ACCEPTANCE_EXPIRED"
                helpers.touch("exceptions", exc)
                reopened += 1
        if cycle is not None and cycle["status"] not in helpers.TERMINAL_CYCLE:
            cycle["open_exception_count"] += reopened
            helpers.touch("cycles", cycle)
        vendor = db.vendors.get(acc.get("_vendor_id") or
                                (cycle["vendor_id"] if cycle else None))
        if vendor is None:
            continue
        previous_due = (util.parse_dt(vendor["next_reassessment_due"])
                        if vendor.get("next_reassessment_due") else None)
        new_due = calc.pull_forward(
            previous_due, now + timedelta(days=calc.DELTA_ACCEPTANCE_EXPIRY_DAYS))
        vendor["next_reassessment_due"] = util.iso(new_due)
        helpers.append_schedule(vendor["id"], "ACCEPTANCE_EXPIRY",
                                previous_due, new_due, acc["id"])
        helpers.touch("vendors", vendor)
        helpers.refresh_risk(vendor)


def _reassessment_due_sweep(now):
    for vendor in sorted(db.vendors.values(), key=lambda v: v["_seq"]):
        if vendor["posture"] not in ("APPROVED", "CONDITIONAL"):
            continue
        if not vendor.get("next_reassessment_due"):
            continue
        due = util.parse_dt(vendor["next_reassessment_due"])
        if not now >= due:
            continue
        vendor["posture"] = "ASSESSING"
        cycle = {
            "vendor_id": vendor["id"],
            "template_id": None,
            "template_version": None,
            "tier_at_issue": None,
            "status": "DRAFT",
            "issued_at": None,
            "response_due_at": None,
            "questionnaire_score": None,
            "evidence_score": None,
            "composite_score": None,
            "open_exception_count": 0,
            "acceptance_required": False,
            "_evidence_review_completed_by": None,
        }
        helpers.stamp_new("cycles", cycle)
        db.cycles[cycle["id"]] = cycle
        vendor["active_cycle_id"] = cycle["id"]
        helpers.touch("vendors", vendor)
        helpers.refresh_risk(vendor)


def run_sweeps():
    now = util.now()
    _cycle_expiry_sweep(now)
    _acceptance_expiry_sweep(now)
    _reassessment_due_sweep(now)


def make_draft_cycle(vendor):
    """System-created DRAFT cycle (alert escalation / reassessment sweep)."""
    cycle = {
        "vendor_id": vendor["id"],
        "template_id": None,
        "template_version": None,
        "tier_at_issue": None,
        "status": "DRAFT",
        "issued_at": None,
        "response_due_at": None,
        "questionnaire_score": None,
        "evidence_score": None,
        "composite_score": None,
        "open_exception_count": 0,
        "acceptance_required": False,
        "_evidence_review_completed_by": None,
    }
    helpers.stamp_new("cycles", cycle)
    db.cycles[cycle["id"]] = cycle
    return cycle
