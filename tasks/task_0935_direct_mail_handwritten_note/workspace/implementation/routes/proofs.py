"""Proofs: submission, approval, rejection, supersession and the 30-day window."""
import datetime

from flask import Blueprint, request

import derive
import envelope
import ladder
import serial
import services
import store
from errors import ApiError
from ladder import Ctx
from model import new_row, touch
from store import db

bp = Blueprint("proofs", __name__)

PROOF_READ_ROLES = ["PlatformAdmin", "AccountOwner", "CampaignManager", "ComplianceOfficer"]


def _proof_state(proof, allowed):
    if proof["status"] not in allowed:
        raise ApiError("ERR_PROOF_INVALID_STATE")


@bp.route("/mail/proofs", methods=["POST"])
def create_proof():
    ctx = Ctx(["PlatformAdmin", "AccountOwner", "CampaignManager"])
    ctx.fk("mail_job", "mail_job_id")
    ctx.fk("template", "template_id")
    ctx.scope(lambda: derive.job_account_id(ctx.get("mail_job")) if ctx.get("mail_job") else None)
    ctx.fields(required=[("mail_job_id", "str"), ("template_id", "str")])
    ctx.gate(lambda: ladder.campaign_of_job(ctx.get("mail_job")))
    ctx.run()
    row = new_row({
        "mail_job_id": ctx.body["mail_job_id"],
        "template_id": ctx.body["template_id"],
        "pinned_template_version": None,
        "status": "DRAFT",
        "submitted_by_user_id": None,
        "approved_by_user_id": None,
        "approved_at": None,
        "expires_at": None,
        "reject_reason": None,
    })
    db.proofs[row["id"]] = row
    return envelope.object_response(serial.proof(row), 201)


@bp.route("/mail/proofs/<proof_id>", methods=["GET"])
def get_proof(proof_id):
    ctx = Ctx(PROOF_READ_ROLES)
    ctx.path("proof", proof_id)
    ctx.scope(lambda: derive.job_account_id(db.mail_jobs.get(ctx.get("proof")["mail_job_id"]))
              if db.mail_jobs.get(ctx.get("proof")["mail_job_id"]) else None)
    ctx.run()
    proof = ctx.get("proof")
    # PRD 3.5: reading a proof individually materialises APPROVED -> EXPIRED.
    services.materialize_proof_expiry(proof)
    return envelope.object_response(serial.proof(proof), 200)


@bp.route("/mail/proofs", methods=["GET"])
def list_proofs():
    ctx = Ctx(PROOF_READ_ROLES)
    ctx.run()
    # Adjudication of friction 3: enumerating proofs through the COLLECTION
    # endpoint does NOT materialise APPROVED -> EXPIRED; only the single read
    # and the approval-gate evaluations do.  The endpoint table declares this
    # collection to carry no side effects, and every EXPIRED-related behaviour
    # stays reachable through the single read and through rungs 24/25.
    rows = list(db.proofs.values())
    for field in ("template_id", "mail_job_id", "status"):
        wanted = request.args.get(field)
        if wanted is not None:
            rows = [r for r in rows if r[field] == wanted]
    rows = envelope.sort_rows(rows)
    page, limit, offset, total = envelope.paginate(rows, request.args)
    return envelope.list_response([serial.proof(r) for r in page], limit, offset, total)


@bp.route("/mail/proofs/<proof_id>/submit", methods=["POST"])
def submit_proof(proof_id):
    ctx = Ctx(["PlatformAdmin", "CampaignManager"])
    ctx.path("proof", proof_id)
    ctx.gate(lambda: ladder.campaign_of_proof(ctx.get("proof")))
    ctx.at(18, lambda: _proof_state(ctx.get("proof"), ("DRAFT", "REJECTED")))
    ctx.run()
    proof = ctx.get("proof")
    template = db.templates.get(proof["template_id"])
    proof["status"] = "SUBMITTED"
    proof["pinned_template_version"] = template["version_no"] if template else None
    proof["submitted_by_user_id"] = ctx.user_id
    touch(proof)
    return envelope.object_response(serial.proof(proof), 200)


@bp.route("/mail/proofs/<proof_id>/approve", methods=["POST"])
def approve_proof(proof_id):
    ctx = Ctx(["PlatformAdmin", "AccountOwner"])
    ctx.path("proof", proof_id)
    ctx.scope(lambda: derive.job_account_id(db.mail_jobs.get(ctx.get("proof")["mail_job_id"]))
              if db.mail_jobs.get(ctx.get("proof")["mail_job_id"]) else None)
    ctx.fields(required=[("expected_template_version", "int")])
    ctx.gate(lambda: ladder.campaign_of_proof(ctx.get("proof")))
    ctx.occ("expected_template_version",
            lambda: db.templates.get(ctx.get("proof")["template_id"]))
    ctx.at(18, lambda: _proof_state(ctx.get("proof"), ("SUBMITTED",)))
    ctx.at(23, lambda: _segregation(ctx))
    ctx.run()
    proof = ctx.get("proof")
    template = db.templates.get(proof["template_id"])
    # Adjudication of friction 2: approval PROCEEDS even when the proof's
    # pinned_template_version no longer equals Template.version_no.  Rung 25 is
    # declared to guard scheduling and committing only, and letting the
    # approval stand keeps the "approval existed but is stale" path to
    # ERR_PROOF_APPROVAL_STALE reachable from this route; refusing here would
    # both widen a declared rung's scope and make that state unreachable.
    proof["status"] = "APPROVED"
    proof["approved_by_user_id"] = ctx.user_id
    proof["approved_at"] = store.now()
    proof["expires_at"] = store.now() + datetime.timedelta(days=store.PROOF_APPROVAL_VALID_DAYS)
    touch(proof)
    job = db.mail_jobs.get(proof["mail_job_id"])
    if job is not None and job["status"] == "DRAFT":
        job["status"] = "PROOFED"
        job["pinned_template_version"] = proof["pinned_template_version"]
        touch(job)
    if template is not None:
        touch(template)
    return envelope.object_response(serial.proof(proof), 200)


def _segregation(ctx):
    proof = ctx.get("proof")
    if proof["submitted_by_user_id"] is not None and ctx.user_id == proof["submitted_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")


@bp.route("/mail/proofs/<proof_id>/reject", methods=["POST"])
def reject_proof(proof_id):
    ctx = Ctx(["PlatformAdmin", "AccountOwner"])
    ctx.path("proof", proof_id)
    ctx.scope(lambda: derive.job_account_id(db.mail_jobs.get(ctx.get("proof")["mail_job_id"]))
              if db.mail_jobs.get(ctx.get("proof")["mail_job_id"]) else None)
    ctx.fields(required=[("reject_reason", "str")])
    ctx.gate(lambda: ladder.campaign_of_proof(ctx.get("proof")))
    ctx.at(18, lambda: _proof_state(ctx.get("proof"), ("SUBMITTED",)))
    ctx.run()
    proof = ctx.get("proof")
    proof["status"] = "REJECTED"
    proof["reject_reason"] = ctx.body["reject_reason"]
    touch(proof)
    return envelope.object_response(serial.proof(proof), 200)
