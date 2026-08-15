"""EvidenceDocument endpoints: attach under a claim, delete by id. Each
attachment/removal recomputes the assembly score on the referenced response
(or the claim's latest DRAFT) and bumps the claim's version (§3.4)."""
from flask import Blueprint

from db import STORE
from errors import err, ERR_CROSS_PARENT_REFERENCE
from middleware import require_roles
from response import success
from services.core import find_or_404, new_record, serialize, sorted_created, touch
from services.scoring import assembly_score, doc_contribution
from util import as_bool, as_dt, as_str, body_json, check_enum, opt, req

bp = Blueprint("evidence", __name__)

DOC_CATEGORIES = (
    "WRITTEN_WARNING",
    "SIGNED_POLICY",
    "FINAL_INCIDENT_REPORT",
    "ATTENDANCE_RECORD",
    "PERFORMANCE_REVIEW",
    "RESIGNATION_LETTER",
    "OTHER",
)


def _score_target_response(claim_id, response_id):
    """The response whose completeness_score is recomputed: the referenced
    one, or — when response_id is omitted — the claim's latest DRAFT."""
    if response_id is not None:
        return STORE.responses.get(response_id)
    drafts = [
        r for r in sorted_created(STORE.responses.values())
        if r["claim_id"] == claim_id and r["status"] == "DRAFT"
    ]
    return drafts[-1] if drafts else None


def _rescore(claim, response_id):
    target = _score_target_response(claim["id"], response_id)
    if target is not None:
        target["completeness_score"] = assembly_score(claim)
        touch(target)


@bp.post("/ui/claims/<cid>/evidence")
def attach_evidence(cid):
    require_roles("ClaimsAnalyst", "TpaAgent")
    body = body_json()
    doc_category = check_enum(
        as_str(req(body, "doc_category"), "doc_category"), DOC_CATEGORIES, "doc_category"
    )
    doc_date = as_dt(req(body, "doc_date"), "doc_date")
    authenticated = as_bool(req(body, "authenticated"), "authenticated")
    response_id = opt(body, "response_id")
    if response_id is not None:
        response_id = as_str(response_id, "response_id")

    claim = find_or_404(STORE.claims, cid, "claim")
    if response_id is not None:
        resp = find_or_404(STORE.responses, response_id, "response")
        if resp["claim_id"] != cid:
            raise err(
                ERR_CROSS_PARENT_REFERENCE,
                422,
                "response belongs to a different claim than the path scope",
            )

    rec = new_record({
        "claim_id": cid,
        "response_id": response_id,
        "doc_category": doc_category,
        "doc_date": doc_date,
        "authenticated": authenticated,
        "weight_points": 0,
    })
    rec["weight_points"] = doc_contribution(rec, claim)
    STORE.evidence[rec["id"]] = rec

    _rescore(claim, response_id)
    # the claim's evidentiary posture changed — submission's OCC observes this
    touch(claim)
    return success(serialize(rec), 201)


@bp.delete("/ui/evidence/<rid>")
def delete_evidence(rid):
    require_roles("ClaimsAnalyst")
    doc = find_or_404(STORE.evidence, rid, "evidence document")
    claim = STORE.claims.get(doc["claim_id"])
    response_id = doc["response_id"]
    del STORE.evidence[rid]
    if claim is not None:
        _rescore(claim, response_id)
        touch(claim)
    return "", 204
