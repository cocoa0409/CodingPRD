"""Escrow accounting (PRD §2.6, §3.4). Three distinct counters per submitter:

  escrow_balance_cents   (settled)   = escrow_deposited_total_cents
                                       - sum(CAPTURED ESCROW Payment.amount_cents)
  escrow_held_cents      (hold)      = sum(FeeAssessment.total_due_cents for this
                                       submitter's packages whose assessment is
                                       FINALIZED and package status == ASSESSED)
  escrow_available_cents (spendable) = escrow_balance_cents - escrow_held_cents

These are derived fields: recomputed on assessment finalize/void, on payment
capture, and on escrow deposit. We recompute from live rows so the counters
always equal their definition."""
from db import db


def recompute(submitter):
    """Recompute the three derived escrow counters for one submitter from the
    live Payment / FeeAssessment / DocumentPackage rows (PRD §3.4)."""
    sid = submitter["id"]

    # Settled balance: deposited total minus CAPTURED escrow-method payments
    # over this submitter's packages.
    captured_escrow = 0
    for pay in db.payments.values():
        if pay["status"] != "CAPTURED" or pay["method"] != "ESCROW":
            continue
        pkg = db.packages.get(pay["package_id"])
        if pkg is not None and pkg["submitter_id"] == sid:
            captured_escrow += pay["amount_cents"]
    balance = submitter["escrow_deposited_total_cents"] - captured_escrow

    # Forward-looking hold: FINALIZED assessments on this submitter's ASSESSED
    # packages.
    held = 0
    for pkg in db.packages.values():
        if pkg["submitter_id"] != sid or pkg["status"] != "ASSESSED":
            continue
        for a in db.assessments.values():
            if a["package_id"] == pkg["id"] and a["status"] == "FINALIZED":
                held += a["total_due_cents"]

    submitter["escrow_balance_cents"] = balance
    submitter["escrow_held_cents"] = held
    submitter["escrow_available_cents"] = balance - held
