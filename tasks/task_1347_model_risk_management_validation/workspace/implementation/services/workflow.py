"""State-machine cascades and the logical-clock sweep (PRD §2.5, §3.6-§3.8)."""
from datetime import timedelta

from db import store
from services import risk
from utils import new_id


def mutate(entity):
    """Stamp a resource mutation: version increments and updated_at is set."""
    entity["version"] += 1
    entity["updated_at"] = store.now()


def metrics_of(model_id):
    return [m for m in store.metrics.values() if m["model_id"] == model_id]


def findings_of(model_id):
    return [f for f in store.findings.values() if f["model_id"] == model_id]


def open_findings_of(model_id):
    return [
        f
        for f in store.findings.values()
        if f["model_id"] == model_id and f["status"] in risk.OPEN_FINDING_STATES
    ]


def create_finding(model, severity, title, source, raised_by):
    """Shared finding-creation path for manual (VALIDATION) and auto-raised
    (MONITORING) findings. The tier used for the deadline is pinned BEFORE the
    new finding is counted into the model's findings penalty."""
    now = store.now()
    pinned_tier = model["risk_tier"]
    finding = {
        "id": new_id(),
        "model_id": model["id"],
        "source": source,
        "severity": severity,
        "title": title,
        "raised_by_user_id": raised_by,
        "status": "OPEN",
        "remediation_due_at": now
        + timedelta(days=risk.deadline_days(severity, pinned_tier, source)),
        "escalated_at": None,
        "closed_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": store.next_seq(),
    }
    store.findings[finding["id"]] = finding
    risk.recompute_risk(model)
    mutate(model)
    return finding


def suspend_model(model):
    """APPROVED_FOR_USE -> SUSPENDED; every ACTIVE metric is PAUSED."""
    model["status"] = "SUSPENDED"
    mutate(model)
    for mt in metrics_of(model["id"]):
        if mt["status"] == "ACTIVE":
            mt["status"] = "PAUSED"
            mutate(mt)


def auto_resume_check(model):
    """After a finding closes: resume a SUSPENDED model when no OPEN/OVERDUE/
    ESCALATED HIGH|CRITICAL finding remains. Mutates the model at most once."""
    if model["status"] != "SUSPENDED":
        return
    blocking = any(
        f["severity"] in ("HIGH", "CRITICAL") for f in open_findings_of(model["id"])
    )
    if blocking:
        return
    model["status"] = "APPROVED_FOR_USE"
    for mt in metrics_of(model["id"]):
        if mt["status"] == "PAUSED":
            mt["status"] = "ACTIVE"
            mutate(mt)


def run_sweep():
    """Clock sweep (PRD §2.5): OPEN -> OVERDUE past deadline; OVERDUE ->
    ESCALATED past deadline + 7d grace (escalation can suspend a TIER_1 model
    and pause its metrics); CURRENT vendor assessments past valid_until ->
    EXPIRED. All comparisons are strict: at exactly the boundary, nothing fires."""
    now = store.now()
    ordered_findings = sorted(
        store.findings.values(), key=lambda f: (f["created_at"], f["_seq"])
    )
    for f in ordered_findings:
        if f["status"] == "OPEN" and now > f["remediation_due_at"]:
            f["status"] = "OVERDUE"
            mutate(f)
    for f in ordered_findings:
        if (
            f["status"] == "OVERDUE"
            and now > f["remediation_due_at"] + timedelta(days=risk.ESCALATION_GRACE_DAYS)
        ):
            f["status"] = "ESCALATED"
            f["escalated_at"] = now
            mutate(f)
            model = store.models.get(f["model_id"])
            if (
                model is not None
                and f["severity"] in ("HIGH", "CRITICAL")
                and model["risk_tier"] == "TIER_1"
                and model["status"] == "APPROVED_FOR_USE"
            ):
                suspend_model(model)
    for a in store.assessments.values():
        if a["status"] == "CURRENT" and now > a["valid_until"]:
            a["status"] = "EXPIRED"
            mutate(a)
