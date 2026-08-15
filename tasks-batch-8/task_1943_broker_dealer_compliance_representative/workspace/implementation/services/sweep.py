"""Clock-set sweeps (PRD 2.5). Applied atomically with every clock change.

1. Finding OPEN -> OVERDUE when due_date < clock date
2. CorrespondenceItem PENDING_REVIEW -> OVERDUE when review_deadline < clock time
3. Attestation PENDING -> OVERDUE when attest_deadline < clock date
4. ExamDocumentRequest OPEN -> OVERDUE when due_date < clock date
5. HeightenedSupervisionPlan ACTIVE -> COMPLETED when end_date <= clock date

Deadline boundaries are strict in the direction stated; the plan completion is
inclusive (on or before).
"""
from db import db
from services.branch import recompute_branch
from services.core import touch
from util import parse_date, parse_datetime, CLOCK


def run_sweeps():
    now = CLOCK.now()
    today = now.date()

    # 1. Findings OPEN past due_date -> OVERDUE
    affected_branches = set()
    for f in db["findings"].values():
        if f["status"] == "OPEN" and parse_date(f["due_date"]) < today:
            f["status"] = "OVERDUE"
            touch(f)
            insp = db["inspections"].get(f["inspection_id"])
            if insp is not None:
                affected_branches.add(insp["branch_id"])

    # 2. Correspondence PENDING_REVIEW past review_deadline -> OVERDUE
    for c in db["correspondence_items"].values():
        if c["status"] == "PENDING_REVIEW" and parse_datetime(c["review_deadline"]) < now:
            c["status"] = "OVERDUE"
            touch(c)

    # 3. Attestations PENDING past attest_deadline -> OVERDUE
    for a in db["attestations"].values():
        if a["status"] == "PENDING" and parse_date(a["attest_deadline"]) < today:
            a["status"] = "OVERDUE"
            touch(a)

    # 4. Exam requests OPEN past due_date -> OVERDUE
    for e in db["exam_requests"].values():
        if e["status"] == "OPEN" and parse_date(e["due_date"]) < today:
            e["status"] = "OVERDUE"
            touch(e)

    # 5. Plans ACTIVE whose end_date has been reached -> COMPLETED
    for p in db["supervision_plans"].values():
        if p["status"] == "ACTIVE" and parse_date(p["end_date"]) <= today:
            p["status"] = "COMPLETED"
            touch(p)

    # Finding sweeps trigger branch risk recomputation (scored set membership is
    # unchanged by OPEN->OVERDUE, so this normally mutates nothing; bump only on
    # real change per PRD 2.7).
    for branch_id in affected_branches:
        branch = db["branches"].get(branch_id)
        if branch is not None and recompute_branch(branch):
            touch(branch)
