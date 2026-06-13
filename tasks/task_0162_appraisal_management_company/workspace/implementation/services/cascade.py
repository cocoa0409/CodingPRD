"""Multi-resource cascades (PRD §2.5, §3.5)."""
import db
from services import domain


def _assignment_for_report(report):
    return db.assignments.get(report.get("assignment_id"))


def open_revision_cascade(report):
    """Head-of-cascade for a revision being opened (compliance FAIL or manual):
       Report -> REVISION_REQUESTED
       Assignment ACCEPTED -> REVISION (revision_round += 1)
       Order IN_QC -> IN_PROGRESS
       FeeSplit revision penalty recompute.
    Each affected resource bumps its own updated_at / version.
    """
    report["status"] = "REVISION_REQUESTED"
    db.touch(report)

    assignment = _assignment_for_report(report)
    if assignment is not None and assignment["status"] == "ACCEPTED":
        assignment["status"] = "REVISION"
        assignment["revision_round"] = assignment.get("revision_round", 0) + 1
        db.touch(assignment)

        order = db.orders.get(assignment.get("order_id"))
        if order is not None and order["status"] == "IN_QC":
            order["status"] = "IN_PROGRESS"
            db.touch(order)

        # FeeSplit penalty recompute (keeps current variant).
        if order is not None:
            fee_split = domain.fee_split_for_order(order["id"])
            if fee_split is not None:
                domain.recompute_fee_split(order, fee_split, fee_split["variant"])
                db.touch(fee_split)


def deliver_cascade(report):
    """PASS/CONDITIONAL: Report -> ACCEPTED, Order IN_QC -> DELIVERED, set
    appraised_value_cents = opinion_of_value_cents, bump order version."""
    report["status"] = "ACCEPTED"
    db.touch(report)

    assignment = _assignment_for_report(report)
    if assignment is not None:
        order = db.orders.get(assignment.get("order_id"))
        if order is not None and order["status"] == "IN_QC":
            order["status"] = "DELIVERED"
            order["appraised_value_cents"] = report["opinion_of_value_cents"]
            db.touch(order)
