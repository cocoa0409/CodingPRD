"""Appeal services: submit, assign-arbiter, decide."""

import db
from errors import (
    raise_error,
    ERR_APPEAL_STATE_INVALID,
    ERR_INSPECTION_STATE_INVALID,
    ERR_NOT_PACKAGE_OWNER,
    ERR_NO_ELIGIBLE_ARBITER,
    ERR_NOT_ASSIGNED_ARBITER,
    ERR_INVALID_PARAMETER,
    ERR_PACKAGE_STATE_INVALID,
)
from config import (
    PENALTY_APPEAL_REJECTED_CENTS,
    REPEATED_DISPUTE_THRESHOLD,
)
from services.audit import write_audit, queue_event
from services.ledger import add_entry as add_ledger_entry
from services.calculations import piece_rate_amount
from services.annotator import (
    apply_suspension_cascade,
    push_dispute_history,
    trailing_rejected_appeals,
)
from services.package import select_arbiter, _audit_package_status


def submit_appeal(pkg, project, inspection, annotator, reason: str):
    # Inspection must be terminal (PASS / FAIL / DISPUTED). PRD §3.8: if appeal
    # is created before inspection finalizes, the finalize is rejected.
    # Here we allow appeals against non-finalized inspections too — that
    # interlock is enforced in finalize_inspection.
    # Submitter must be the package owner.
    if pkg.get("assigned_annotator_id") != annotator["id"]:
        raise_error(ERR_NOT_PACKAGE_OWNER, "Only the package owner may appeal.")

    appeal = db.insert("appeals", {
        "package_id": pkg["id"],
        "inspection_id": inspection["id"],
        "annotator_id": annotator["id"],
        "reason": reason,
        "arbiter_id": None,
        "decision": None,
        "status": "SUBMITTED",
    })
    return appeal


def assign_arbiter(appeal: dict):
    if appeal.get("status") != "SUBMITTED":
        raise_error(ERR_APPEAL_STATE_INVALID, "Appeal not in SUBMITTED state.")
    pkg = db.find_by_id("task_packages", appeal["package_id"])
    arbiter = select_arbiter(pkg, appeal_annotator_id=appeal["annotator_id"])
    if not arbiter:
        raise_error(ERR_NO_ELIGIBLE_ARBITER, "No eligible arbiter available.")
    db.update("appeals", appeal["id"], {
        "arbiter_id": arbiter["id"],
        "status": "UNDER_REVIEW",
    })
    return db.find_by_id("appeals", appeal["id"])


def decide(appeal: dict, arbiter: dict, decision: str):
    if appeal.get("status") != "UNDER_REVIEW":
        raise_error(ERR_APPEAL_STATE_INVALID, "Appeal not in UNDER_REVIEW.")
    if appeal.get("arbiter_id") != arbiter["id"]:
        raise_error(ERR_NOT_ASSIGNED_ARBITER,
                    "Acting annotator is not the assigned arbiter.")
    if decision not in {"UPHOLD", "REJECT"}:
        raise_error(ERR_INVALID_PARAMETER, "decision must be UPHOLD or REJECT.")

    pkg = db.find_by_id("task_packages", appeal["package_id"])
    inspection = db.find_by_id("inspections", appeal["inspection_id"])
    submitter = db.find_by_id("annotators", appeal["annotator_id"])

    if decision == "UPHOLD":
        db.update("appeals", appeal["id"], {
            "status": "UPHELD",
            "decision": "UPHELD",
        })
        db.update("inspections", inspection["id"], {"outcome": "DISPUTED"})

        # Reverse penalty entries booked from this inspection.
        penalty_entries = [
            e for e in db.all_rows("ledger_entries")
            if e.get("inspection_id") == inspection["id"] and e.get("kind") == "PENALTY"
        ]
        for pe in penalty_entries:
            offset = -pe["gross_amount_cents"]
            adj = add_ledger_entry(
                annotator_id=pe["annotator_id"],
                package_id=pe.get("package_id"),
                kind="ADJUSTMENT_UPHELD",
                gross_amount_cents=offset,
                settlement_state="WITHHELD",
            )
            db.update("ledger_entries", adj["id"],
                      {"inspection_id": inspection["id"]}, bump=False)

        # If package was REJECTED, promote to APPROVED and create the piece-rate
        # entry (which the rejection path had withheld).
        if pkg.get("status") == "REJECTED":
            prev = pkg["status"]
            db.update("task_packages", pkg["id"], {"status": "APPROVED"})
            _audit_package_status(pkg["id"], prev, "APPROVED")
            project = db.find_by_id("projects", pkg["project_id"])
            gross = piece_rate_amount(
                base_unit_price_cents=project["unit_price_cents"],
                item_count=pkg["item_count"],
                difficulty=project["difficulty"],
                tier=submitter["tier"],
            )
            pr_entry = add_ledger_entry(
                annotator_id=submitter["id"], package_id=pkg["id"],
                kind="PIECE_RATE", gross_amount_cents=gross,
                settlement_state="WITHHELD",
            )
            db.update("ledger_entries", pr_entry["id"],
                      {"inspection_id": inspection["id"]}, bump=False)

        push_dispute_history(submitter["id"], rejected=False)
        queue_event("IM", "appeal.upheld", appeal["id"])
    else:
        # Reject the appeal
        db.update("appeals", appeal["id"], {
            "status": "REJECTED",
            "decision": "REJECTED",
        })
        adj = add_ledger_entry(
            annotator_id=submitter["id"], package_id=pkg["id"],
            kind="ADJUSTMENT_REJECTED",
            gross_amount_cents=-PENALTY_APPEAL_REJECTED_CENTS,
            settlement_state="WITHHELD",
        )
        db.update("ledger_entries", adj["id"],
                  {"inspection_id": inspection["id"]}, bump=False)

        push_dispute_history(submitter["id"], rejected=True)

        # Repeated dispute pattern → suspend
        if trailing_rejected_appeals(submitter["id"]) >= REPEATED_DISPUTE_THRESHOLD:
            apply_suspension_cascade(submitter, write_log_fn=_audit_package_status)

        queue_event("IM", "appeal.rejected", appeal["id"])

    return db.find_by_id("appeals", appeal["id"])
