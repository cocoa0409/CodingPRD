"""Project lifecycle cascades (PRD §3.5 handoff, §3.9 cancellation)."""
from db import db
from services.ledger import (
    project_milestones, project_invoices, project_licenses,
    project_change_orders,
)


def handoff_license_cascade(project):
    """DELIVERY->HANDOFF forward cascade (PRD §3.5, §3.7): every license in
    RESERVED or CLEARED transitions to BILLED. Each touched independently."""
    for lc in project_licenses(project["id"]):
        if lc["status"] in ("RESERVED", "CLEARED"):
            lc["status"] = "BILLED"
            db.touch(lc)


def complete_waive_cascade(project):
    """HANDOFF->COMPLETED closing cascade (PRD §3.5): every milestone still in
    PENDING whose amount_cents is 0 transitions to WAIVED."""
    for ms in project_milestones(project["id"]):
        if ms["status"] == "PENDING" and ms["amount_cents"] == 0:
            ms["status"] = "WAIVED"
            db.touch(ms)


def cancellation_cascade(project, from_stage):
    """Unwind cascade for project cancellation (PRD §3.9).

    DRAFT: nothing. DISCOVERY: moodboards + concepts + change-orders + invoices
    + licenses. CONCEPT: concepts + change-orders + invoices + licenses (no
    moodboards). Each entity mutated independently (updated_at + version)."""
    pid = project["id"]

    if from_stage == "DISCOVERY":
        # Every moodboard not currently in DRAFT or SUBMITTED -> REJECTED
        # (PRD §3.9, literal). Already-REJECTED moodboards are a no-op (no state
        # change), so only APPROVED (and any non-resting) are flipped.
        for mb in db.moodboards.values():
            if mb["project_id"] != pid:
                continue
            if mb["status"] in ("DRAFT", "SUBMITTED"):
                continue
            if mb["status"] != "REJECTED":
                mb["status"] = "REJECTED"
                db.touch(mb)

    if from_stage in ("DISCOVERY", "CONCEPT"):
        # Every concept that is neither APPROVED nor REJECTED -> REJECTED.
        for cp in db.concepts.values():
            if cp["project_id"] != pid:
                continue
            if cp["status"] not in ("APPROVED", "REJECTED"):
                cp["status"] = "REJECTED"
                db.touch(cp)

        # Every PROPOSED change order -> REJECTED.
        for co in project_change_orders(pid):
            if co["status"] == "PROPOSED":
                co["status"] = "REJECTED"
                db.touch(co)

        # Every ISSUED/OVERDUE invoice -> VOID; revert INVOICED milestone -> PENDING.
        for iv in project_invoices(pid):
            if iv["status"] in ("ISSUED", "OVERDUE"):
                iv["status"] = "VOID"
                db.touch(iv)
                ms = db.milestones.get(iv["milestone_id"])
                if ms is not None and ms["status"] == "INVOICED":
                    ms["status"] = "PENDING"
                    db.touch(ms)

        # Every RESERVED/CLEARED license -> VOIDED.
        for lc in project_licenses(pid):
            if lc["status"] in ("RESERVED", "CLEARED"):
                lc["status"] = "VOIDED"
                db.touch(lc)
