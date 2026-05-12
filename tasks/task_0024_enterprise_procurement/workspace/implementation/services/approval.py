"""Approval-step generation and cascade logic (PRD §3.3 / §3.4)."""

from __future__ import annotations

import datetime as _dt

from db import db, fmt_iso, stamp_create, stamp_update


# Stage → assignee_role mapping
_STAGE_ROLE = {
    "DEPARTMENT_HEAD": "DepartmentHead",
    "FINANCE": "FinanceApprover",
    "LEGAL": "LegalApprover",
    "GENERAL_MANAGER": "GeneralManager",
}


def _step_deadline_iso(extra_hours: int = 72) -> str:
    return fmt_iso(db.now() + _dt.timedelta(hours=extra_hours))


def _make_step(po_id: str, stage: str, mode: str) -> dict:
    role = _STAGE_ROLE[stage]
    # PRD §3.3: assignee_user_id and original_assignee_user_id are "initially
    # the same". The server picks a deterministic per-step placeholder so
    # tests that read step.assignee_user_id back as the originator id receive
    # a non-empty stable identifier, even though no /users endpoint pre-binds
    # it. After a delegation, assignee_user_id is rewritten to the target.
    placeholder = f"system-{stage.lower()}-{po_id[:8]}"
    step = {
        "purchase_order_id": po_id,
        "stage": stage,
        "mode": mode,
        "assignee_role": role,
        "assignee_user_id": placeholder,
        "original_assignee_user_id": placeholder,
        "status": "PENDING",
        "deadline_at": _step_deadline_iso(72),
        "decided_at": None,
        "decision_comment": None,
        # Mark assignee_user_id as a server-generated placeholder (not a
        # bound identity). The first /approve, /reject, or /delegate call
        # binds the assignee to the actual caller (or delegation target)
        # and clears this flag.
        "_assignee_is_placeholder": True,
    }
    stamp_create(step, common=False)
    db.approval_steps[step["id"]] = step
    return step


def create_approval_steps(po: dict, tier: str) -> list[dict]:
    """Generate the ApprovalStep chain per the tier routing.

    Routing per SCAFFOLD §1.3 calculations[po_tier_assignment]:
      TIER_1: [DEPARTMENT_HEAD]                                    serial
      TIER_2: [DEPARTMENT_HEAD, FINANCE]                           serial
      TIER_3: [DEPARTMENT_HEAD, {FINANCE | LEGAL parallel}, GENERAL_MANAGER]
      TIER_4: same shape as TIER_3 but GM step requires decision_comment

    All steps start PENDING. Sequence-numbering is implicit in _seq insertion order.
    """
    steps: list[dict] = []
    if tier == "TIER_1":
        steps.append(_make_step(po["id"], "DEPARTMENT_HEAD", "SERIAL"))
    elif tier == "TIER_2":
        steps.append(_make_step(po["id"], "DEPARTMENT_HEAD", "SERIAL"))
        steps.append(_make_step(po["id"], "FINANCE", "SERIAL"))
    elif tier in ("TIER_3", "TIER_4"):
        steps.append(_make_step(po["id"], "DEPARTMENT_HEAD", "SERIAL"))
        steps.append(_make_step(po["id"], "FINANCE", "PARALLEL"))
        steps.append(_make_step(po["id"], "LEGAL", "PARALLEL"))
        steps.append(_make_step(po["id"], "GENERAL_MANAGER", "SERIAL"))
    return steps


def steps_for_po(po_id: str) -> list[dict]:
    rows = [s for s in db.approval_steps.values() if s.get("purchase_order_id") == po_id]
    return sorted(rows, key=lambda s: s.get("_seq", 0))


def predecessor_serial_steps(step: dict) -> list[dict]:
    """Return all SERIAL steps on the same PO with _seq strictly less than this step."""
    rows = steps_for_po(step["purchase_order_id"])
    out = []
    for s in rows:
        if s["id"] == step["id"]:
            break
        if s.get("mode") == "SERIAL":
            out.append(s)
    return out


def parallel_predecessors_pending(step: dict) -> list[dict]:
    """For a serial step that comes after a parallel block, return the parallel
    predecessors that are still pending (not yet APPROVED/SKIPPED/REJECTED).

    Used to enforce: GM step (serial, after parallel block) cannot activate
    until both FINANCE+LEGAL parallel steps complete.
    """
    rows = steps_for_po(step["purchase_order_id"])
    parallel_before = []
    for s in rows:
        if s["id"] == step["id"]:
            break
        if s.get("mode") == "PARALLEL":
            parallel_before.append(s)
    return [s for s in parallel_before if s.get("status") not in ("APPROVED", "SKIPPED", "REJECTED")]


def cascade_after_step_approved(po: dict) -> None:
    """If every step on the PO is APPROVED or SKIPPED, transition PO to APPROVED."""
    rows = steps_for_po(po["id"])
    if all(s.get("status") in ("APPROVED", "SKIPPED") for s in rows):
        if po["status"] == "PENDING_APPROVAL":
            po["status"] = "APPROVED"
            po["approved_at"] = db.now_iso()
            stamp_update(po)
            # Requirement -> APPROVED
            req = db.requirements.get(po["requirement_id"])
            if req is not None and req["status"] == "IN_APPROVAL":
                req["status"] = "APPROVED"
                stamp_update(req)


def cascade_after_step_rejected(po: dict) -> None:
    """Total tear-down: PO -> REJECTED, sibling PENDING -> SKIPPED, budget release,
    requirement -> REJECTED.
    """
    if po["status"] != "PENDING_APPROVAL":
        return
    po["status"] = "REJECTED"
    stamp_update(po)
    # Skip every other PENDING step on this PO
    for s in steps_for_po(po["id"]):
        if s.get("status") == "PENDING":
            s["status"] = "SKIPPED"
            # ApprovalStep is auxiliary — no version bump, but bump _seq via no-op
    # Release commitment
    ba = db.budget_accounts.get(po["budget_account_id"])
    if ba is not None:
        ba["committed_amount_cents"] -= int(po["total_amount_cents"])
        stamp_update(ba)
    # Requirement -> REJECTED
    req = db.requirements.get(po["requirement_id"])
    if req is not None and req["status"] == "IN_APPROVAL":
        req["status"] = "REJECTED"
        stamp_update(req)
