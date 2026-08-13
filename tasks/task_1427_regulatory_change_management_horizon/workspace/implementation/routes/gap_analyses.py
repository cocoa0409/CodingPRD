"""Gap analyses: review lifecycle and freeze-on-confirm (PRD §3.5)."""

from flask import Blueprint, request

from db import now_clock, store, touch
from errors import invalid_state
from middleware import auth_context, get_or_404, require_roles
from response import paginate, success_object
from serializers import created_sorted, gap_to_api
from services.audit import append_audit
from services.cascades import recompute_gap

bp = Blueprint("gap_analyses", __name__)


@bp.get("/compliance/gap-analyses")
def list_gaps():
    auth_context()
    items = created_sorted(store.gap_analyses.values())
    for param in ("impact_assessment_id", "obligation_id", "status"):
        value = request.args.get(param)
        if value is not None:
            items = [g for g in items if g[param] == value]
    return paginate(items, gap_to_api)


@bp.get("/compliance/gap-analyses/<gap_id>")
def get_gap(gap_id):
    auth_context()
    gap = get_or_404(store.gap_analyses, gap_id, "gap analysis")
    return success_object(gap_to_api(gap))


@bp.post("/compliance/gap-analyses/<gap_id>/begin-review")
def begin_review(gap_id):
    user_id, role = auth_context()
    require_roles(role, ("ComplianceOfficer",))
    gap = get_or_404(store.gap_analyses, gap_id, "gap analysis")
    if gap["status"] != "OPEN":
        raise invalid_state("begin-review requires status OPEN")
    gap["status"] = "IN_REVIEW"
    touch(gap)
    append_audit(user_id, role, "POST /compliance/gap-analyses/{id}/begin-review",
                 "GapAnalysis", gap["id"])
    return success_object(gap_to_api(gap))


@bp.post("/compliance/gap-analyses/<gap_id>/confirm")
def confirm_gap(gap_id):
    user_id, role = auth_context()
    require_roles(role, ("ComplianceOfficer",))
    gap = get_or_404(store.gap_analyses, gap_id, "gap analysis")
    if gap["status"] != "IN_REVIEW":
        raise invalid_state("confirm requires status IN_REVIEW")
    # Final recompute, then frozen permanently.
    recompute_gap(gap)
    gap["status"] = "CONFIRMED"
    gap["confirmed_by_user_id"] = user_id
    gap["confirmed_at"] = now_clock()
    touch(gap)
    append_audit(user_id, role, "POST /compliance/gap-analyses/{id}/confirm",
                 "GapAnalysis", gap["id"])
    return success_object(gap_to_api(gap))
