"""Cascade helpers per PRD section 2.9.

- Lead re-queuing: leads ROUTED through an affected assignment or dealer go
  back to NEW with routing fields cleared (declined_dealer_ids untouched).
- Termination cascade: dealer -> ACTIVE agreements TERMINATED -> their ACTIVE
  assignments RELEASED -> leads routed via them re-queued.
- Chargeback suspension cascade is handled in the claims route.
"""

from __future__ import annotations

import db


def requeue_leads_for_assignment(assignment_id: str) -> None:
    for lead in db.leads.values():
        if lead["status"] == "ROUTED" and lead.get("routed_assignment_id") == assignment_id:
            lead["status"] = "NEW"
            lead["routed_dealer_id"] = None
            lead["routed_assignment_id"] = None
            lead["routed_at"] = None
            db.touch(lead)


def requeue_leads_for_dealer(dealer_id: str) -> None:
    for lead in db.leads.values():
        if lead["status"] == "ROUTED" and lead.get("routed_dealer_id") == dealer_id:
            lead["status"] = "NEW"
            lead["routed_dealer_id"] = None
            lead["routed_assignment_id"] = None
            lead["routed_at"] = None
            db.touch(lead)


def release_assignment(assignment: dict) -> None:
    """ACTIVE -> RELEASED and re-queue its ROUTED leads."""
    if assignment["status"] != "ACTIVE":
        return
    assignment["status"] = "RELEASED"
    db.touch(assignment)
    requeue_leads_for_assignment(assignment["id"])


def terminate_agreement_cascade(agreement: dict) -> None:
    """Agreement -> TERMINATED; release its ACTIVE assignments; re-queue leads."""
    if agreement["status"] not in ("DRAFT", "ACTIVE"):
        return
    was_active = agreement["status"] == "ACTIVE"
    agreement["status"] = "TERMINATED"
    db.touch(agreement)
    if was_active:
        for asg in db.assignments.values():
            if asg["agreement_id"] == agreement["id"] and asg["status"] == "ACTIVE":
                release_assignment(asg)


def expire_agreement_cascade(agreement: dict) -> None:
    """Agreement -> EXPIRED; release its ACTIVE assignments; re-queue leads."""
    agreement["status"] = "EXPIRED"
    db.touch(agreement)
    for asg in db.assignments.values():
        if asg["agreement_id"] == agreement["id"] and asg["status"] == "ACTIVE":
            release_assignment(asg)
