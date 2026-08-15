"""Annual attestations: list / get / attest."""

from flask import Blueprint, g, request

from db import store, touch, audit, clock_now
from errors import (ApiError, ERR_ATTESTATION_NOT_PENDING, ERR_PLAN_NOT_CLOSED,
                    ERR_OWNERSHIP_REQUIRED)
from middleware import require_roles, actor, json_body, require_fields
from response import success, paginate
from services import get_or_404, by_seq
from util import require_str, view

bp = Blueprint("attestations", __name__)

ANY = ("TrainingAdmin", "ComplianceOfficer", "RegisteredRep", "Auditor")


@bp.get("/attestations")
@require_roles(*ANY)
def list_attestations():
    items = by_seq(store.attestations.values())
    for param in ("rep_id", "plan_id", "attestation_status"):
        value = request.args.get(param)
        if value is not None:
            items = [a for a in items if a[param] == value]
    items = sorted(items, key=lambda a: (a["created_at"], a["_seq"]))
    page, pagination = paginate(items)
    return success([view(a) for a in page], is_list=True, pagination=pagination)


@bp.get("/attestations/<attestationId>")
@require_roles(*ANY)
def get_attestation(attestationId):
    rec = get_or_404(store.attestations, attestationId, "AnnualAttestation")
    return success(view(rec))


@bp.post("/attestations/<attestationId>/attest")
@require_roles("RegisteredRep")
def attest(attestationId):
    rec = get_or_404(store.attestations, attestationId, "AnnualAttestation")
    body = json_body()
    require_fields(body, "attestation_statement")
    statement = require_str(body["attestation_statement"],
                            "attestation_statement")
    if rec["attestation_status"] != "PENDING":
        raise ApiError(ERR_ATTESTATION_NOT_PENDING, 409,
                       "attest requires attestation_status == PENDING")
    plan = store.plans.get(rec["plan_id"])
    if plan is None or plan["plan_status"] != "CLOSED":
        raise ApiError(ERR_PLAN_NOT_CLOSED, 409,
                       "attest requires the parent plan to be CLOSED")
    if g.actor_user_id != plan["rep_id"]:
        raise ApiError(ERR_OWNERSHIP_REQUIRED, 403,
                       "A RegisteredRep may attest only their own attestation")
    rec["attestation_status"] = "ATTESTED"
    rec["attestation_statement"] = statement
    rec["attested_at"] = clock_now()
    touch(rec)
    a = actor()
    audit("ATTESTATION_ATTESTED", "AnnualAttestation", rec["id"], a[0], a[1],
          "attestation_status: PENDING -> ATTESTED")
    return success(view(rec))
