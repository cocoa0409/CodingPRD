"""Documentation posture, mandated support windows, obligation status and model rollup."""
import db
from db import setf, touch
from util import add_years, days, end_of_day

ELIGIBLE_DECISIONS = ("ELIGIBLE", "ELIGIBLE_WITH_TOOL_RENTAL")


# --------------------------------------------------------------------------
# compatibility window helpers
# --------------------------------------------------------------------------

def in_window(compat, at):
    """Half-open [effective_from, effective_until) containment."""
    if compat["effective_from"] > at:
        return False
    until = compat.get("effective_until")
    if until is not None and at >= until:
        return False
    return True


def compat_rows(part_id=None, model_id=None):
    rows = db.db.compats.all()
    if part_id is not None:
        rows = [r for r in rows if r["part_id"] == part_id]
    if model_id is not None:
        rows = [r for r in rows if r["model_id"] == model_id]
    return db.ordered(rows)


def select_compat(part_id, model_id, at):
    """The in-window row with the latest effective_from; ties broken by created_at ASC."""
    candidates = [r for r in compat_rows(part_id, model_id) if in_window(r, at)]
    if not candidates:
        return None
    best = None
    for row in candidates:
        if best is None or row["effective_from"] > best["effective_from"]:
            best = row
    return best


def published_revision(model_id, doc_type):
    for rev in db.ordered(db.db.revisions.all()):
        if (
            rev["model_id"] == model_id
            and rev["doc_type"] == doc_type
            and rev["status"] == "PUBLISHED"
        ):
            return rev
    return None


def published_parts_in_window(model_id, at):
    """Every PUBLISHED part holding an in-window compatibility row for the model."""
    out = []
    for compat in compat_rows(model_id=model_id):
        if not in_window(compat, at):
            continue
        part = db.db.parts.get(compat["part_id"])
        if part is not None and part["status"] == "PUBLISHED" and part not in out:
            out.append(part)
    return out


# --------------------------------------------------------------------------
# documentation_posture_rollup
# --------------------------------------------------------------------------

def rollup_documentation_posture(model, coverage_only=False):
    """Recompute coverage_gap_sku_count and (unless coverage_only) the model posture."""
    at = db.now()
    guide = published_revision(model["id"], "DISASSEMBLY_GUIDE")
    sheet = published_revision(model["id"], "SAFETY_SHEET")

    if guide is None:
        if not coverage_only:
            setf(model, "published_disassembly_revision_number", None)
            setf(model, "published_safety_sheet_revision_number",
                 sheet["revision_number"] if sheet else None)
            setf(model, "documentation_posture", "MISSING")
        return

    required = set(p["sku"] for p in published_parts_in_window(model["id"], at))
    gap = required - set(guide.get("covered_part_skus") or [])
    setf(guide, "coverage_gap_sku_count", len(gap))

    if coverage_only:
        return

    setf(model, "published_disassembly_revision_number", guide["revision_number"])
    setf(model, "published_safety_sheet_revision_number",
         sheet["revision_number"] if sheet else None)

    if len(gap) > 0:
        posture = "STALE"
    elif (
        model.get("last_hardware_change_date") is not None
        and guide.get("effective_from") is not None
        and guide["effective_from"] < model["last_hardware_change_date"]
    ):
        posture = "STALE"
    else:
        posture = "CURRENT"
    setf(model, "documentation_posture", posture)


def refresh_revision_coverage(revision):
    """Recompute a single revision's coverage_gap_sku_count against today's catalogue."""
    at = db.now()
    required = set(p["sku"] for p in published_parts_in_window(revision["model_id"], at))
    gap = required - set(revision.get("covered_part_skus") or [])
    setf(revision, "coverage_gap_sku_count", len(gap))
    return len(gap)


# --------------------------------------------------------------------------
# mandated_support_window
# --------------------------------------------------------------------------

def apply_mandated_window(obligation, model, profile):
    eop = model.get("end_of_production_date")
    if eop is None:
        setf(obligation, "deadline_basis", "PRODUCTION_ACTIVE")
        setf(obligation, "parts_available_until", None)
        setf(obligation, "documentation_available_until", None)
        return
    setf(obligation, "deadline_basis", "END_OF_PRODUCTION")
    parts_until = end_of_day(add_years(eop, profile["min_parts_availability_years"]))
    doc_until = end_of_day(add_years(eop, profile["min_documentation_years"]))
    if doc_until < parts_until:
        doc_until = parts_until
    setf(obligation, "parts_available_until", parts_until)
    setf(obligation, "documentation_available_until", doc_until)


# --------------------------------------------------------------------------
# obligation_status_evaluation
# --------------------------------------------------------------------------

def evaluate_obligation(obligation, model=None, force_touch=False):
    if model is None:
        model = db.db.models.get(obligation["model_id"])
    at = db.now()
    basis = obligation.get("deadline_basis")
    parts_until = obligation.get("parts_available_until")
    doc_until = obligation.get("documentation_available_until")

    if (
        basis == "END_OF_PRODUCTION"
        and parts_until is not None
        and doc_until is not None
        and at > parts_until
        and at > doc_until
    ):
        status = "CLOSED"
    elif not published_parts_in_window(obligation["model_id"], at):
        status = "BREACHED_PARTS"
    elif model is not None and model.get("documentation_posture") == "MISSING":
        status = "BREACHED_DOCUMENTATION"
    elif (
        basis == "END_OF_PRODUCTION"
        and parts_until is not None
        and at >= parts_until - days(90)
    ) or (model is not None and model.get("documentation_posture") == "STALE"):
        status = "AT_RISK"
    else:
        status = "OPEN"

    if status in ("BREACHED_PARTS", "BREACHED_DOCUMENTATION"):
        setf(obligation, "breach_count", obligation.get("breach_count", 0) + 1)
    setf(obligation, "status", status)
    if force_touch:
        touch(obligation)
    return status


def obligations_for_model(model_id):
    return db.ordered([o for o in db.db.obligations.all() if o["model_id"] == model_id])


# --------------------------------------------------------------------------
# model_compliance_posture_rollup
# --------------------------------------------------------------------------

def rollup_model_posture(model):
    rows = obligations_for_model(model["id"])
    statuses = [o["status"] for o in rows]
    if any(s in ("BREACHED_PARTS", "BREACHED_DOCUMENTATION") for s in statuses):
        posture = "ORDER_RESTRICTED"
    elif "AT_RISK" in statuses:
        posture = "WATCH"
    else:
        posture = "OPEN"
    setf(model, "compliance_posture", posture)
    setf(model, "open_obligation_count",
         sum(1 for s in statuses if s in ("OPEN", "AT_RISK", "ATTESTED")))
    return posture


def reevaluate_model_obligations(model, force_touch=False):
    for obligation in obligations_for_model(model["id"]):
        evaluate_obligation(obligation, model, force_touch=force_touch)
    rollup_model_posture(model)


def revoke_valid_assessments_for_provider(provider_id):
    revoked = []
    for assessment in db.ordered(db.db.assessments.all()):
        if assessment.get("provider_id") == provider_id and assessment["status"] == "VALID":
            setf(assessment, "status", "REVOKED_BY_SAFETY")
            revoked.append(assessment)
    return revoked
