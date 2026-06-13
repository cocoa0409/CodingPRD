"""Disposition endpoints: get, decide (drives the Summons transition), and the
requested-deferral-term filtered list.

decide ordering (PRD §4 / §1.4 priorities): auth/RBAC -> existence ->
ERR_DISPOSITION_ROLE_MISMATCH (priority 12, auth) -> ERR_INVALID_STATE
(priority 21, state) -> DEFER target-term + deferral-limit business checks ->
body validation. The role-mismatch check therefore precedes the state check so a
wrong-office decision on an already-decided disposition surfaces the mismatch.
"""
from flask import Blueprint, request

import db
import errors
import helpers
import serializers
from middleware import get_identity, require_roles
from response import success
from services import core

bp = Blueprint("dispositions", __name__)


# ---------------------------------------------------------------------------
# GET /dispositions/{id}
# ---------------------------------------------------------------------------
@bp.route("/dispositions/<disposition_id>", methods=["GET"])
def get_disposition(disposition_id):
    _, role = get_identity()
    require_roles(role, {"JuryAdministrator", "CourtClerk", "Juror"})

    d = core.get_disposition(disposition_id)
    if d is None:
        raise errors.err("ERR_NOT_FOUND", "Disposition not found")
    return success(serializers.disposition(d), status=200)


# ---------------------------------------------------------------------------
# GET /dispositions
# ---------------------------------------------------------------------------
@bp.route("/dispositions", methods=["GET"])
def list_dispositions():
    _, role = get_identity()
    require_roles(role, {"JuryAdministrator", "CourtClerk"})

    requested_term_id = request.args.get("requested_term_id")
    decision = request.args.get("decision")

    rows = list(db.dispositions.values())
    if requested_term_id is not None:
        rows = [d for d in rows if d["requested_term_id"] == requested_term_id]
    if decision is not None:
        rows = [d for d in rows if d["decision"] == decision]

    data, meta = helpers.paginate(rows, serializers.disposition)
    return success(data, status=200, pagination=meta)


# ---------------------------------------------------------------------------
# POST /dispositions/{id}/decide
# ---------------------------------------------------------------------------
@bp.route("/dispositions/<disposition_id>/decide", methods=["POST"])
def decide(disposition_id):
    _, role = get_identity()
    # Either office may reach this endpoint; the kind-specific office is enforced
    # by the role-mismatch check below.
    require_roles(role, {"CourtClerk", "JuryAdministrator"})

    d = core.get_disposition(disposition_id)
    if d is None:
        raise errors.err("ERR_NOT_FOUND", "Disposition not found")

    # priority 12 (auth): DEFER decided only by JuryAdministrator; EXCUSE/EXEMPT
    # only by CourtClerk. This precedes the state check.
    if d["kind"] == "DEFER":
        if role != "JuryAdministrator":
            raise errors.err("ERR_DISPOSITION_ROLE_MISMATCH", "DEFER must be decided by a JuryAdministrator")
    else:  # EXCUSE / EXEMPT
        if role != "CourtClerk":
            raise errors.err("ERR_DISPOSITION_ROLE_MISMATCH", "EXCUSE/EXEMPT must be decided by a CourtClerk")

    summons = db.summonses.get(d["summons_id"])

    # priority 21 (state): disposition still PENDING and summons QUALIFIED_PENDING.
    if d["decision"] != "PENDING":
        raise errors.err("ERR_INVALID_STATE", "Disposition is already decided")
    if summons is None or summons["status"] != "QUALIFIED_PENDING":
        raise errors.err("ERR_INVALID_STATE", "Summons is not in QUALIFIED_PENDING")

    body = helpers.get_body()
    decision = helpers.require_enum(body, "decision", {"GRANTED", "DENIED"})

    if decision == "DENIED":
        d["decision"] = "DENIED"
        d["decided_by_role"] = role
        core.touch(d)
        # Summons stays QUALIFIED_PENDING.
        return success(serializers.disposition(d), status=200)

    # GRANTED — drive the summons by kind.
    if d["kind"] == "EXCUSE":
        d["decision"] = "GRANTED"
        d["decided_by_role"] = role
        core.touch(d)
        summons["status"] = "EXCUSED"
        core.touch(summons)
        return success(serializers.disposition(d), status=200)

    if d["kind"] == "EXEMPT":
        d["decision"] = "GRANTED"
        d["decided_by_role"] = role
        core.touch(d)
        summons["status"] = "EXEMPT"
        core.touch(summons)
        return success(serializers.disposition(d), status=200)

    # DEFER (granted): target term must be DRAFT or OPEN; deferral_count < 2.
    target = db.service_terms.get(d["requested_term_id"])
    if target is None:
        raise errors.err("ERR_NOT_FOUND", "Requested deferral term not found")
    if target["status"] not in ("DRAFT", "OPEN"):
        raise errors.err("ERR_INVALID_STATE", "Requested deferral term must be DRAFT or OPEN")

    # priority 40 (business): max two deferrals — deferral_count < 2 to grant.
    if summons["deferral_count"] >= 2:
        raise errors.err("ERR_DEFERRAL_LIMIT", "Summons has already been deferred the maximum number of times")

    d["decision"] = "GRANTED"
    d["decided_by_role"] = role
    core.touch(d)

    summons["deferred_to_term_id"] = target["id"]
    summons["status"] = "DEFERRED"
    core.touch(summons)

    # Cascade: re-issue a fresh SUMMONED summons on the target term for the same
    # juror, badge minted on that term, deferral_count = old + 1.
    core.create_summons(
        target["id"], summons["juror_id"], deferral_count=summons["deferral_count"] + 1
    )

    return success(serializers.disposition(d), status=200)
