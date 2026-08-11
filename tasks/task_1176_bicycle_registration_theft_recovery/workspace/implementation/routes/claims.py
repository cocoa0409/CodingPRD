"""Ownership claims and the claim-approval cascade (PRD §3.6)."""
from flask import Blueprint, g, request

import db
from errors import fail
from middleware import body, require_roles
from models import claim_view
from response import list_response, ok_object
from routes.common import field, load

bp = Blueprint("claims", __name__)


@bp.post("/registry/claims")
@require_roles("Owner")
def create_claim():
    data = body()
    recovery_intake_id = field(data, "recovery_intake_id", "string", required=True)
    match_id = field(data, "match_id", "string", required=True)
    proof_text = field(data, "proof_text", "string", required=True)

    intake = load(db.intakes, recovery_intake_id, "ERR_RECOVERY_INTAKE_NOT_FOUND")
    match = load(db.matches, match_id, "ERR_MATCH_NOT_FOUND")

    # The match must belong to the same intake the claim names.
    if match["recovery_intake_id"] != intake["id"]:
        fail("ERR_INVALID_REQUEST", "match_id does not belong to the named recovery intake")
    # The match's theft report must belong to the claiming owner.
    report = db.theft_reports.get(match["theft_report_id"])
    if report is None or report["owner_id"] != g.user_id:
        fail("ERR_FORBIDDEN_RESOURCE_ACCESS", "The match's theft report belongs to another owner")
    if match["status"] != "NOTIFIED":
        fail("ERR_MATCH_NOT_OPEN", "Claims require a NOTIFIED match")
    if any(c["match_id"] == match["id"] and c["status"] == "UNDER_REVIEW"
           for c in db.claims.values()):
        fail("ERR_CLAIM_ALREADY_EXISTS", "An under-review claim already exists for this match")

    rec = db.new_record({
        "recovery_intake_id": intake["id"],
        "match_id": match["id"],
        "owner_id": g.user_id,
        "proof_text": proof_text,
        "status": "UNDER_REVIEW",
        "reason_text": None,
    })
    db.claims[rec["id"]] = rec
    return ok_object(claim_view(rec), status=201)


@bp.get("/registry/claims")
@require_roles("Owner", "Partner", "Registrar", "Admin")
def list_claims():
    recs = list(db.claims.values())
    if g.role == "Owner":
        recs = [c for c in recs if c["owner_id"] == g.user_id]
    for param, key in (("recovery_intake_id", "recovery_intake_id"),
                       ("owner_id", "owner_id"), ("match_id", "match_id"),
                       ("status", "status")):
        value = request.args.get(param)
        if value is not None:
            recs = [c for c in recs if c[key] == value]
    return list_response(recs, claim_view)


@bp.get("/registry/claims/<claim_id>")
@require_roles("Owner", "Partner", "Registrar", "Admin")
def read_claim(claim_id):
    rec = load(db.claims, claim_id, "ERR_CLAIM_NOT_FOUND")
    if g.role == "Owner" and rec["owner_id"] != g.user_id:
        fail("ERR_FORBIDDEN_RESOURCE_ACCESS", "Owners may read only their own claims")
    return ok_object(claim_view(rec))


@bp.post("/registry/claims/<claim_id>/approve")
@require_roles("Registrar")
def approve_claim(claim_id):
    rec = load(db.claims, claim_id, "ERR_CLAIM_NOT_FOUND")
    intake = db.intakes.get(rec["recovery_intake_id"])
    match = db.matches.get(rec["match_id"])
    bicycle = db.bicycles.get(match["bicycle_id"]) if match else None

    # Stage 9 merge guard precedes stage-10 from-state checks.
    if bicycle is not None and bicycle["integrity_status"] == "MERGED":
        fail("ERR_BICYCLE_MERGED", "Merged bicycles accept no further operations")
    if rec["status"] != "UNDER_REVIEW":
        fail("ERR_CLAIM_NOT_REVIEWABLE", "Claim is not under review")
    if intake is None or intake["status"] != "INTAKE":
        fail("ERR_RECOVERY_NOT_ACTIONABLE", "The intake has already moved on")
    if match is None or match["status"] != "NOTIFIED":
        fail("ERR_MATCH_NOT_OPEN", "The referenced match is no longer NOTIFIED")
    if bicycle is not None and bicycle["integrity_status"] == "DUPLICATE_SUSPECT":
        fail("ERR_DUPLICATE_HOLD", "Matched bicycle is under a duplicate-suspect hold")

    # Deepest cascade (PRD §3.6): match -> intake -> bicycle -> report -> siblings.
    match["status"] = "CONFIRMED"
    db.bump(match)

    intake["status"] = "CLAIM_PENDING"
    db.bump(intake)

    if bicycle is not None:
        bicycle["registry_status"] = "RECOVERED"
        db.bump(bicycle)

    report = db.theft_reports.get(match["theft_report_id"])
    if report is not None and report["status"] == "FLAGGED":
        report["status"] = "CLOSED_RECOVERED"
        db.bump(report)

    for sibling in db.matches.values():
        if (sibling["recovery_intake_id"] == intake["id"] and sibling["id"] != match["id"]
                and sibling["status"] in ("PROPOSED", "NOTIFIED")):
            sibling["status"] = "EXPIRED"
            db.bump(sibling)

    db.notify(rec["owner_id"], "CLAIM_APPROVED",
              "Your ownership claim has been approved.",
              related_entity_type="OwnerClaim", related_entity_id=rec["id"])
    rec["status"] = "APPROVED"
    db.bump(rec)
    return ok_object(claim_view(rec))


@bp.post("/registry/claims/<claim_id>/reject")
@require_roles("Registrar")
def reject_claim(claim_id):
    reason_text = field(body(), "reason_text", "string", required=True)
    rec = load(db.claims, claim_id, "ERR_CLAIM_NOT_FOUND")
    if rec["status"] != "UNDER_REVIEW":
        fail("ERR_CLAIM_NOT_REVIEWABLE", "Claim is not under review")
    rec["reason_text"] = reason_text
    rec["status"] = "REJECTED"
    db.bump(rec)
    db.notify(rec["owner_id"], "CLAIM_REJECTED",
              "Your ownership claim has been rejected.",
              related_entity_type="OwnerClaim", related_entity_id=rec["id"])
    return ok_object(claim_view(rec))


@bp.post("/registry/claims/<claim_id>/withdraw")
@require_roles("Owner")
def withdraw_claim(claim_id):
    rec = load(db.claims, claim_id, "ERR_CLAIM_NOT_FOUND")
    if rec["owner_id"] != g.user_id:
        fail("ERR_FORBIDDEN_RESOURCE_ACCESS", "Only the claim's owner may withdraw it")
    if rec["status"] != "UNDER_REVIEW":
        fail("ERR_CLAIM_NOT_REVIEWABLE", "Claim is not under review")
    rec["status"] = "WITHDRAWN"
    db.bump(rec)
    return ok_object(claim_view(rec))
