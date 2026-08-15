"""Cross-aggregate cascades per PRD section 2.7 and scaffold section 1.2."""

from . import calc
from .store import STORE, touch


def terminate_contributor(c):
    """ACTIVE/SUSPENDED -> TERMINATED; supersede agreements; kill DRAFT/OFFERED assignments."""
    c["status"] = "TERMINATED"
    touch(c)
    for ra in STORE.rate_agreements.values():
        if ra["contributor_id"] == c["id"] and ra["status"] == "ACTIVE":
            ra["status"] = "SUPERSEDED"
            touch(ra)
    for a in STORE.assignments.values():
        if a["contributor_id"] == c["id"] and a["editorial_status"] in ("DRAFT", "OFFERED"):
            a["editorial_status"] = "KILLED"
            a["kill_fee_tier"] = "PRE_DELIVERY"
            a["final_fee_cents"] = calc.fee_kill(a)
            touch(a)


def reject_after_flag(assignment):
    """Depth-3 cascade on CONFIRMED_VIOLATION (PRD section 3.5)."""
    a = assignment
    if a["editorial_status"] == "UNDER_VERIFICATION":
        a["editorial_status"] = "REJECTED_AFTER_FLAG"
    a["final_fee_cents"] = 0
    a["payment_status"] = "VOID"
    touch(a)
    for claim in STORE.expense_claims.values():
        if claim["assignment_id"] == a["id"] and claim["status"] in (
            "PRE_APPROVAL_REQUESTED",
            "APPROVED",
            "SUBMITTED",
        ):
            claim["status"] = "DENIED"
            claim["reimbursable_cents"] = 0
            touch(claim)
    for rp in STORE.rights_purchases.values():
        if rp["assignment_id"] == a["id"] and rp["status"] == "ACTIVE":
            rp["status"] = "REVERTED"
            touch(rp)
    for inv in STORE.invoices.values():
        if inv["assignment_id"] == a["id"] and inv["status"] in ("SUBMITTED", "VERIFIED"):
            inv["status"] = "VOID"
            touch(inv)
    contributor = STORE.contributors.get(a["contributor_id"])
    if contributor is not None and contributor["status"] != "TERMINATED":
        if contributor["status"] != "SUSPENDED":
            contributor["status"] = "SUSPENDED"
            touch(contributor)


def recompute_batch_totals(batch):
    members = [
        i for i in STORE.invoices.values()
        if i["payment_batch_id"] == batch["id"] and i["status"] == "BATCHED"
    ]
    batch["total_gross_cents"] = sum(i["gross_cents"] for i in members)
    batch["total_withholding_cents"] = sum(i["withholding_cents"] for i in members)
    batch["total_net_cents"] = sum(
        i["net_payable_cents"] + i["late_fee_cents"] for i in members
    )


def batch_members(batch):
    return [
        i for i in STORE.invoices.values()
        if i["payment_batch_id"] == batch["id"] and i["status"] == "BATCHED"
    ]


def release_batch(batch):
    """LOCKED -> RELEASED settlement: late fees, ledger postings, PAID cascades, YTD sync."""
    contributors_touched = {}
    for inv in batch_members(batch):
        assignment = STORE.assignments.get(inv["assignment_id"])
        contributor_id = assignment["contributor_id"] if assignment else None

        inv["late_fee_cents"] = calc.late_fee_cents(inv, batch["scheduled_pay_date"])

        calc.post_ledger(inv["id"], contributor_id, "FEE_CREDIT", inv["fee_claim_cents"])
        calc.post_ledger(inv["id"], contributor_id, "EXPENSE_CREDIT", inv["expense_claim_cents"])
        calc.post_ledger(inv["id"], contributor_id, "WITHHOLDING_DEBIT", -inv["withholding_cents"])
        if inv["late_fee_cents"] > 0:
            calc.post_ledger(inv["id"], contributor_id, "LATE_FEE_CREDIT", inv["late_fee_cents"])

        inv["status"] = "PAID"
        touch(inv)

        if assignment is not None:
            if assignment["payment_status"] != "PAID":
                assignment["payment_status"] = "PAID"
                touch(assignment)
            for claim in STORE.expense_claims.values():
                if claim["assignment_id"] == assignment["id"] and claim["status"] == "REIMBURSABLE":
                    claim["status"] = "PAID"
                    touch(claim)
            if contributor_id is not None:
                contributor = STORE.contributors.get(contributor_id)
                if contributor is not None:
                    contributors_touched[contributor_id] = contributor

    for contributor in contributors_touched.values():
        calc.sync_ytd(contributor)

    batch["status"] = "RELEASED"
    touch(batch)
