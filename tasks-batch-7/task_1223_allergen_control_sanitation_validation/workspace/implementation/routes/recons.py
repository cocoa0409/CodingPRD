from flask import Blueprint, g, request

from db import db, new_entity, public, touch
from errors import ApiError
from logic import create_auto_incident, get_or_404, recompute_posture
from middleware import require_roles
from response import ok, ok_list
from util import body, req_int, req_list_str, req_str

bp = Blueprint("recons", __name__)

READ_ROLES = ("QaManager", "QaSupervisor", "QaTechnician", "Auditor")


def _compute_verdict(product, expected_revision, printed_revision, declared):
    missing = sorted(set(product["allergen_set"]) - set(declared))
    extra = sorted(set(declared) - set(product["allergen_set"]))
    if missing:
        verdict = "UNDECLARED_ALLERGEN"
    elif printed_revision != expected_revision:
        verdict = "REVISION_MISMATCH"
    elif extra:
        verdict = "OVER_DECLARED"
    else:
        verdict = "MATCH"
    return missing, extra, verdict


@bp.post("/qa/label-reconciliations")
@require_roles("QaTechnician", "QaSupervisor")
def create_recon():
    b = body()
    run = get_or_404("runs", req_str(b, "run_id"))
    printed = req_int(b, "printed_label_revision")
    declared = req_list_str(b, "declared_allergens_on_label")
    product = get_or_404("products", run["product_id"])
    expected = run["label_revision_snapshot"]
    missing, extra, verdict = _compute_verdict(product, expected, printed, declared)
    ent = new_entity({
        "run_id": run["id"],
        "expected_label_revision": expected,
        "printed_label_revision": printed,
        "declared_allergens_on_label": declared,
        "missing_allergens": missing,
        "extra_allergens": extra,
        "verdict": verdict,
        "status": "OPEN",
        "_created_by": g.user_id,
    })
    db["recons"][ent["id"]] = ent
    return ok(public(ent), 201)


@bp.get("/qa/label-reconciliations")
@require_roles(*READ_ROLES)
def list_recons():
    items = list(db["recons"].values())
    for param in ("run_id", "verdict", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [r for r in items if r.get(param) == v]
    return ok_list(items)


@bp.get("/qa/label-reconciliations/<reconId>")
@require_roles(*READ_ROLES)
def get_recon(reconId):
    return ok(public(get_or_404("recons", reconId)))


@bp.post("/qa/label-reconciliations/<reconId>/resolve")
@require_roles("QaSupervisor")
def resolve_recon(reconId):
    rec = get_or_404("recons", reconId)
    if rec["status"] != "OPEN":
        raise ApiError("ERR_RECON_NOT_OPEN", 409, "Reconciliation is not OPEN")
    if rec["verdict"] != "MATCH":
        raise ApiError("ERR_RECON_NOT_MATCH", 409,
                       "Only MATCH verdicts can be resolved directly")
    rec["status"] = "RESOLVED"
    touch(rec)
    return ok(public(rec))


@bp.post("/qa/label-reconciliations/<reconId>/escalate")
@require_roles("QaSupervisor")
def escalate_recon(reconId):
    rec = get_or_404("recons", reconId)
    if rec["status"] != "OPEN":
        raise ApiError("ERR_RECON_NOT_OPEN", 409, "Reconciliation is not OPEN")
    run = db["runs"].get(rec["run_id"])
    if rec["missing_allergens"]:
        incident_type, severity = "UNDECLARED_ALLERGEN", "CRITICAL"
    else:
        incident_type, severity = "LABEL_MISMATCH", "HIGH"
    rec["status"] = "ESCALATED"
    touch(rec)
    create_auto_incident(
        incident_type, severity,
        line_id=run["line_id"] if run is not None else None,
        product_id=run["product_id"] if run is not None else None,
        source_label_reconciliation_id=rec["id"],
        description=f"Escalated label reconciliation {rec['id']}",
        trigger_user_ids=[rec.get("_created_by")] if rec.get("_created_by") else [])
    if run is not None:
        line = db["lines"].get(run["line_id"])
        if line is not None:
            recompute_posture(line)
    return ok(public(rec))
