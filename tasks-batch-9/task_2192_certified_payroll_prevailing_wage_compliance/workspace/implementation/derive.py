"""Derived counters, compliance posture, debarment risk and the cascade
discipline of PRD 2.9. A recompute advances a row's version exactly when it
actually mutates one of that row's stored values."""

import calc
import db

NON_TERMINAL = calc.NON_TERMINAL_FINDING_STATUSES


# ---------------------------------------------------------------------------
# Graph navigation
# ---------------------------------------------------------------------------
def submission_assignment(submission):
    return db.contract_assignments.get(submission["contract_assignment_id"])


def submission_project(submission):
    assignment = submission_assignment(submission)
    if assignment is None:
        return None
    return db.projects.get(assignment["project_id"])


def submission_contractor(submission):
    assignment = submission_assignment(submission)
    if assignment is None:
        return None
    return db.contractors.get(assignment["contractor_id"])


def finding_submission(finding):
    return db.payroll_submissions.get(finding["payroll_submission_id"])


def finding_assignment(finding):
    submission = finding_submission(finding)
    return submission_assignment(submission) if submission else None


def finding_contractor(finding):
    assignment = finding_assignment(finding)
    return db.contractors.get(assignment["contractor_id"]) if assignment else None


def findings_citing(submission_id):
    return db.ordered(db.findings, lambda f: f["payroll_submission_id"] == submission_id)


def findings_of_contractor(contractor_id):
    out = []
    for finding in db.ordered(db.findings):
        assignment = finding_assignment(finding)
        if assignment is not None and assignment["contractor_id"] == contractor_id:
            out.append(finding)
    return out


def findings_of_assignment(assignment_id):
    out = []
    for finding in db.ordered(db.findings):
        submission = finding_submission(finding)
        if submission is not None and submission["contract_assignment_id"] == assignment_id:
            out.append(finding)
    return out


def submissions_of_assignment(assignment_id):
    return db.ordered(
        db.payroll_submissions, lambda s: s["contract_assignment_id"] == assignment_id
    )


def submissions_of_project(project_id):
    out = []
    for assignment in assignments_of_project(project_id):
        out.extend(submissions_of_assignment(assignment["id"]))
    out.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return out


def lines_of_submission(submission_id):
    return db.ordered(db.payroll_lines, lambda l: l["payroll_submission_id"] == submission_id)


def assignments_of_project(project_id):
    return db.ordered(db.contract_assignments, lambda a: a["project_id"] == project_id)


def assignments_of_contractor(contractor_id):
    return db.ordered(db.contract_assignments, lambda a: a["contractor_id"] == contractor_id)


def _apply(row, values):
    """Write values, advancing version only when something actually changed."""
    changed = False
    for key, value in values.items():
        if row.get(key) != value:
            row[key] = value
            changed = True
    if changed:
        db.touch(row)
    return changed


# ---------------------------------------------------------------------------
# calculations.project_posture (+ the project's derived counters)
# ---------------------------------------------------------------------------
def posture_of(open_critical, outstanding, open_count, suspended):
    if open_critical >= 1:
        return "FROZEN"
    if outstanding > calc.POSTURE_FROZEN_RESTITUTION_CENTS:
        return "FROZEN"
    if open_count >= calc.POSTURE_RESTRICTED_FINDING_COUNT:
        return "RESTRICTED"
    if suspended >= 1:
        return "RESTRICTED"
    return "OPEN"


def recompute_project(project):
    if project is None:
        return False
    live = [
        f
        for f in db.findings.values()
        if f["project_id"] == project["id"] and f["status"] in NON_TERMINAL
    ]
    open_count = len(live)
    open_critical = len([f for f in live if f["severity"] == "CRITICAL"])
    outstanding = sum(f["restitution_outstanding_cents"] for f in live)
    suspended = len([a for a in assignments_of_project(project["id"]) if a["status"] == "SUSPENDED"])
    values = {
        "open_finding_count": open_count,
        "open_critical_finding_count": open_critical,
        "outstanding_restitution_cents": outstanding,
        "suspended_assignment_count": suspended,
    }
    if project["status"] != "CLOSED":
        values["posture"] = posture_of(open_critical, outstanding, open_count, suspended)
    return _apply(project, values)


def recompute_assignment(assignment):
    if assignment is None:
        return False
    open_count = len(
        [f for f in findings_of_assignment(assignment["id"]) if f["status"] in NON_TERMINAL]
    )
    return _apply(assignment, {"open_finding_count": open_count})


# ---------------------------------------------------------------------------
# calculations.debarment_risk_score
# ---------------------------------------------------------------------------
def compute_risk_score(contractor, outstanding):
    live = [f for f in findings_of_contractor(contractor["id"]) if f["status"] in NON_TERMINAL]
    raw = (
        calc.CRITICAL_WEIGHT * len([f for f in live if f["severity"] == "CRITICAL"])
        + calc.MAJOR_WEIGHT * len([f for f in live if f["severity"] == "MAJOR"])
        + calc.MINOR_WEIGHT * len([f for f in live if f["severity"] == "MINOR"])
    )
    if outstanding >= calc.RESTITUTION_FLAG_THRESHOLD_CENTS:
        raw += calc.RESTITUTION_FLAG_WEIGHT
    if contractor["last_finding_at"] is None:
        decay = 0
    else:
        elapsed = db.now() - contractor["last_finding_at"]
        period = db.days(calc.DECAY_PERIOD_DAYS)
        periods = int(elapsed.total_seconds() // period.total_seconds())
        if periods < 0:
            periods = 0
        decay = calc.DECAY_PER_PERIOD * periods
    return max(0, min(100, raw - decay))


def recompute_contractor(contractor):
    """Refresh contractor counters + risk score, then run its state machine."""
    if contractor is None:
        return False
    all_findings = findings_of_contractor(contractor["id"])
    open_critical = len(
        [f for f in all_findings if f["severity"] == "CRITICAL" and f["status"] in NON_TERMINAL]
    )
    outstanding = sum(
        f["restitution_outstanding_cents"] for f in all_findings if f["status"] != "WITHDRAWN"
    )
    score = compute_risk_score(contractor, outstanding)
    changed = _apply(
        contractor,
        {
            "open_critical_finding_count": open_critical,
            "outstanding_restitution_cents": outstanding,
            "debarment_risk_score": score,
        },
    )
    changed = run_debarment_machine(contractor) or changed
    return changed


def run_debarment_machine(contractor):
    """CLEAR <-> PROPOSED driven by the risk score threshold (inclusive at 70)."""
    score = contractor["debarment_risk_score"]
    if contractor["debarment_status"] == "CLEAR" and score >= calc.DEBARMENT_PROPOSAL_THRESHOLD:
        contractor["debarment_status"] = "PROPOSED"
        db.touch(contractor)
        for assignment in assignments_of_contractor(contractor["id"]):
            if assignment["status"] == "ACTIVE":
                suspend_assignment(assignment)
        return True
    if contractor["debarment_status"] == "PROPOSED" and score < calc.DEBARMENT_PROPOSAL_THRESHOLD:
        contractor["debarment_status"] = "CLEAR"
        db.touch(contractor)
        return True
    return False


def suspend_assignment(assignment):
    """ContractAssignment ACTIVE -> SUSPENDED, cascading to the parent project."""
    if assignment["status"] != "ACTIVE":
        return False
    assignment["status"] = "SUSPENDED"
    db.touch(assignment)
    recompute_project(db.projects.get(assignment["project_id"]))
    return True


# ---------------------------------------------------------------------------
# PayrollSubmission compliance axis (axis 2)
# ---------------------------------------------------------------------------
def compliance_on_finding_open(submission):
    if submission is None:
        return False
    if submission["compliance_status"] in ("COMPLIANT", "REMEDIED"):
        submission["compliance_status"] = "DEFICIENT"
        db.touch(submission)
        return True
    return False


def compliance_maybe_remedied(submission):
    if submission is None:
        return False
    if submission["compliance_status"] not in ("DEFICIENT", "RESTITUTION_PENDING"):
        return False
    cited = findings_citing(submission["id"])
    if not cited:
        return False
    for finding in cited:
        if finding["status"] not in ("RESPONSE_ACCEPTED", "WITHDRAWN"):
            return False
    if sum(f["restitution_outstanding_cents"] for f in cited) != 0:
        return False
    submission["compliance_status"] = "REMEDIED"
    db.touch(submission)
    return True


def compliance_on_partial_disbursement(submission):
    if submission is None:
        return False
    if submission["compliance_status"] == "DEFICIENT":
        submission["compliance_status"] = "RESTITUTION_PENDING"
        db.touch(submission)
        return True
    return False


def compliance_after_reversal(submission):
    """Back to RESTITUTION_PENDING when a DISBURSED payment remains on any
    finding citing the submission, otherwise back to DEFICIENT."""
    if submission is None:
        return False
    has_disbursed = False
    for finding in findings_citing(submission["id"]):
        for payment in db.restitution_payments.values():
            if payment["finding_id"] == finding["id"] and payment["status"] == "DISBURSED":
                has_disbursed = True
                break
        if has_disbursed:
            break
    target = "RESTITUTION_PENDING" if has_disbursed else "DEFICIENT"
    if submission["compliance_status"] != target:
        submission["compliance_status"] = target
        db.touch(submission)
        return True
    return False


# ---------------------------------------------------------------------------
# Full fan-out after any finding / restitution mutation
# ---------------------------------------------------------------------------
def cascade_finding_change(finding):
    """Recompute assignment, contractor and project exposure for a finding."""
    assignment = finding_assignment(finding)
    recompute_assignment(assignment)
    if assignment is not None:
        recompute_contractor(db.contractors.get(assignment["contractor_id"]))
    recompute_project(db.projects.get(finding["project_id"]))
