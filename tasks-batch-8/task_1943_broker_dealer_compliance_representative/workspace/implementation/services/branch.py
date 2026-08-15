"""Branch derived-field recomputation (PRD 2.7, 3.1, 3.2) and finding/inspection cascades.

All recomputation is atomic with the triggering request. BranchOffice.version is
incremented by the caller exactly once per triggering event when the branch
record was mutated (or unconditionally where the state machine pins the bump).
"""
from db import db
from util import add_days, add_months, parse_date, today

COUNTED_STATUSES = ("OPEN", "OVERDUE", "REMEDIATION_SUBMITTED")
SCORED_STATUSES = ("OPEN", "OVERDUE")

HIGH_FINDING_THRESHOLD = 2
ESCALATION_WINDOW_DAYS = 90
RISK_HIGH_W = 15
RISK_MEDIUM_W = 5
RISK_LOW_W = 2
RISK_SD_BONUS = 20
RISK_CAP = 100
ACCELERATED_CYCLE_MONTHS = 6


def branch_inspections(branch_id):
    return [i for i in db["inspections"].values() if i["branch_id"] == branch_id]


def branch_findings(branch_id):
    insp_ids = {i["id"] for i in branch_inspections(branch_id)}
    return [f for f in db["findings"].values() if f["inspection_id"] in insp_ids]


def recompute_inspection_counts(insp):
    """Each inspection maintains open/high counts over its own findings in
    {OPEN, OVERDUE, REMEDIATION_SUBMITTED} (PRD 2.7). Returns True if mutated."""
    findings = [f for f in db["findings"].values() if f["inspection_id"] == insp["id"]]
    open_ct = sum(1 for f in findings if f["status"] in COUNTED_STATUSES)
    high_ct = sum(1 for f in findings
                  if f["status"] in COUNTED_STATUSES and f["severity"] == "HIGH")
    changed = (insp["open_findings_count"] != open_ct
               or insp["high_severity_open_count"] != high_ct)
    insp["open_findings_count"] = open_ct
    insp["high_severity_open_count"] = high_ct
    return changed


def last_closed_inspection(branch_id):
    """Most recently CLOSED inspection by completed_date; tie-break: earliest
    creation wins (created_at ASC, first-created)."""
    closed = [i for i in branch_inspections(branch_id) if i["status"] == "CLOSED"]
    best = None
    for i in closed:
        if best is None or i["completed_date"] > best["completed_date"]:
            best = i
        elif i["completed_date"] == best["completed_date"] and i["_seq"] < best["_seq"]:
            best = i
    return best


def compute_due_date(branch, sd_count):
    """branch_inspection_due_date (SCAFFOLD 1.3): base + applicable cycle."""
    last = last_closed_inspection(branch["id"])
    if last is not None and last.get("completed_date"):
        base = parse_date(last["completed_date"])
    else:
        base = parse_date(branch["created_at"][:10])
    cycle = ACCELERATED_CYCLE_MONTHS if sd_count >= 1 else branch["inspection_cycle_months"]
    return add_months(base, cycle).isoformat()


def recompute_branch(branch, recompute_due=False):
    """Recompute open/high counts, sd_rep_count, risk_score, posture, and
    (optionally) next_inspection_due_date. Returns True if any field mutated.

    Posture pull-in applies ONLY on the upward transition into
    REMEDIATION_REQUIRED; falling back to NORMAL never restores the due date.
    """
    changed = False
    inspections = branch_inspections(branch["id"])
    findings = branch_findings(branch["id"])

    open_ct = sum(1 for f in findings if f["status"] in COUNTED_STATUSES)
    high_ct = sum(1 for f in findings
                  if f["status"] in COUNTED_STATUSES and f["severity"] == "HIGH")
    sd_ct = sum(1 for r in db["representatives"].values()
                if r["branch_id"] == branch["id"]
                and r["is_statutorily_disqualified"] and r["status"] != "TERMINATED")

    raw = (RISK_HIGH_W * sum(1 for f in findings
                             if f["status"] in SCORED_STATUSES and f["severity"] == "HIGH")
           + RISK_MEDIUM_W * sum(1 for f in findings
                                 if f["status"] in SCORED_STATUSES and f["severity"] == "MEDIUM")
           + RISK_LOW_W * sum(1 for f in findings
                              if f["status"] in SCORED_STATUSES and f["severity"] == "LOW"))
    if sd_ct >= 1:
        raw += RISK_SD_BONUS
    risk = min(RISK_CAP, raw)

    for key, val in (("open_findings_count", open_ct),
                     ("high_severity_open_count", high_ct),
                     ("sd_rep_count", sd_ct),
                     ("risk_score", risk)):
        if branch[key] != val:
            branch[key] = val
            changed = True

    # Due date recomputation happens only at the pinned triggers: branch
    # creation, inspection CLOSED, and SD-cascade cycle acceleration.
    if recompute_due:
        due = compute_due_date(branch, sd_ct)
        if branch["next_inspection_due_date"] != due:
            branch["next_inspection_due_date"] = due
            changed = True

    # Posture: per-inspection HIGH findings in the counting statuses.
    any_high = any(
        sum(1 for f in db["findings"].values()
            if f["inspection_id"] == i["id"]
            and f["status"] in COUNTED_STATUSES and f["severity"] == "HIGH")
        >= HIGH_FINDING_THRESHOLD
        for i in inspections
    )
    if any_high:
        if branch["posture"] != "REMEDIATION_REQUIRED":
            branch["posture"] = "REMEDIATION_REQUIRED"
            changed = True
            candidate = add_days(today(), ESCALATION_WINDOW_DAYS)
            current = branch.get("next_inspection_due_date")
            if current is None or candidate < parse_date(current):
                branch["next_inspection_due_date"] = candidate.isoformat()
                changed = True
    else:
        if branch["posture"] != "NORMAL":
            branch["posture"] = "NORMAL"
            changed = True

    return changed
