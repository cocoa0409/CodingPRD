"""Cascading side effects: request expiry on clock advance, member
suspension / removal cascades, removal eligibility."""

from datetime import timedelta

import clock
import db
from services.calc import (
    append_ledger,
    assignment_for_request,
    cancel_assignment,
)
from util import round2, touch

NON_TERMINAL_REQUEST_STATES = ("OPEN", "CLAIMED", "ASSIGNED", "IN_PROGRESS")
NON_TERMINAL_ASSIGNMENT_STATES = (
    "CONFIRMED",
    "IN_PROGRESS",
    "COMPLETED_PENDING_REVIEW",
    "DISPUTED",
)


def expire_requests():
    """OPEN requests whose expires_at the logical clock has reached move to
    EXPIRED on their own."""
    now = clock.now()
    for req in db.store["requests"].values():
        if req["status"] == "OPEN" and req["expires_at"] <= now:
            req["status"] = "EXPIRED"
            touch(req)


def _reject_pending_claims(request_id):
    for c in db.store["claims"].values():
        if c["sitting_request_id"] == request_id and c["status"] == "PENDING":
            c["status"] = "REJECTED"
            c["decided_at"] = clock.now()
            touch(c)


def _cancel_request(req, reason):
    req["status"] = "CANCELLED"
    req["cancelled_reason"] = reason
    touch(req)
    _reject_pending_claims(req["id"])


def suspend_cascade(member):
    """VETTED -> SUSPENDED cascade (PRD §3.1)."""
    mid = member["id"]
    now = clock.now()
    # Every OPEN request the member owns is cancelled with OWNER_SUSPENDED.
    for req in db.store["requests"].values():
        if req["owner_member_id"] == mid and req["status"] == "OPEN":
            _cancel_request(req, "OWNER_SUSPENDED")
    # Every PENDING claim the member has made is withdrawn.
    for c in db.store["claims"].values():
        if c["claimer_member_id"] == mid and c["status"] == "PENDING":
            c["status"] = "WITHDRAWN"
            touch(c)
    # Every CONFIRMED assignment touching the member is cancelled per role,
    # with the sitter's provisional hours reversed.
    for a in db.store["assignments"].values():
        if a["status"] != "CONFIRMED":
            continue
        if a["sitter_member_id"] == mid:
            cancel_assignment(a, "SITTER")
            req = db.store["requests"].get(a["sitting_request_id"])
            if req is not None and req["status"] in NON_TERMINAL_REQUEST_STATES:
                _cancel_request(req, "SITTER_SUSPENDED")
        elif a["owner_member_id"] == mid:
            cancel_assignment(a, "OWNER")
            req = db.store["requests"].get(a["sitting_request_id"])
            if req is not None and req["status"] in NON_TERMINAL_REQUEST_STATES:
                _cancel_request(req, "OWNER_SUSPENDED")
    _ = now  # cascade stamps come from touch()


def removal_eligible(member):
    """Eligible iff respondent on an ESCALATED_REMOVAL dispute, or >= 2
    RESOLVED_AT_FAULT incidents within the trailing 365 days (inclusive)."""
    mid = member["id"]
    for d in db.store["disputes"].values():
        if d["respondent_member_id"] == mid and d["status"] == "ESCALATED_REMOVAL":
            return True
    cutoff = clock.now() - timedelta(days=365)
    count = 0
    for i in db.store["incidents"].values():
        if (
            i["at_fault_member_id"] == mid
            and i["status"] == "RESOLVED_AT_FAULT"
            and i.get("_decided_at") is not None
            and i["_decided_at"] >= cutoff
        ):
            count += 1
    return count >= 2


def remove_cascade(member, removal_reason):
    """REMOVED cascade (PRD §3.1): zero balances with a MEDIATION_ADJUSTMENT
    offsetting entry when non-zero, deactivate pets, cancel all non-terminal
    requests and assignments with provisional reversal."""
    mid = member["id"]
    balance_before = member["credit_balance_hours"]

    for p in db.store["pets"].values():
        if p["owner_member_id"] == mid and p["active"]:
            p["active"] = False
            touch(p)

    # Cancel non-terminal requests owned by the member.
    for req in db.store["requests"].values():
        if req["owner_member_id"] == mid and req["status"] in NON_TERMINAL_REQUEST_STATES:
            _cancel_request(req, removal_reason or "OWNER_REMOVED")

    # Cancel non-terminal assignments touching the member (and their requests).
    for a in db.store["assignments"].values():
        if a["status"] not in NON_TERMINAL_ASSIGNMENT_STATES:
            continue
        if a["sitter_member_id"] == mid or a["owner_member_id"] == mid:
            by = "SITTER" if a["sitter_member_id"] == mid else "OWNER"
            cancel_assignment(a, by)
            req = db.store["requests"].get(a["sitting_request_id"])
            if req is not None and req["status"] in NON_TERMINAL_REQUEST_STATES:
                _cancel_request(req, removal_reason or "MEMBER_REMOVED")

    # Zero both balances last, after provisional reversals, appending a
    # MEDIATION_ADJUSTMENT entry equal to the negated pre-removal balance.
    if balance_before != 0:
        append_ledger(
            member,
            "MEDIATION_ADJUSTMENT",
            -balance_before,
            dispute_id=None,
            memo="Balance zeroed on member removal",
        )
    member["credit_balance_hours"] = round2(0)
    member["provisional_credit_hours"] = round2(0)
    touch(member)
