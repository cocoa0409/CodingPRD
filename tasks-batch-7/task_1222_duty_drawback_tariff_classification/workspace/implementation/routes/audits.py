"""Audit case endpoints: open, advance workflow, penalty exposure (PRD §3.8)."""
from fractions import Fraction

from flask import Blueprint, request

from calc import (
    CULPABILITY_RATE_BPS,
    mint_entity,
    recompute_client_aggregates,
    touch,
)
from db import STORE, logical_now
from errors import (
    ERR_ALREADY_TERMINAL,
    ERR_CROSS_CLIENT_REFERENCE,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_RESPONSE_PAST_DUE,
    raise_err,
)
from middleware import (
    authenticate,
    get_body,
    req_dt,
    req_enum,
    req_str,
    require_client_scope,
    require_role,
)
from response import paginate, success_object
from serializers import serialize, sorted_by_creation
from util import rhu

bp = Blueprint("audits", __name__)

ALL_ROLES = {"FirmAdmin", "Analyst", "LicensedBroker", "ComplianceManager", "ClientContact"}
OPENED_REASONS = {"CF28", "FOCUSED_ASSESSMENT", "POST_PAYMENT_AUDIT"}
CULPABILITY_LEVELS = {"NONE", "NEGLIGENCE", "GROSS_NEGLIGENCE", "FRAUD"}
ACTIONS = {"START_EVIDENCE", "FILE_RESPONSE", "REQUEST_MORE", "CLOSE_REFUTED", "CLOSE_SUSTAINED"}
TERMINAL = {"CLOSED_REFUTED", "CLOSED_SUSTAINED"}


def get_audit_or_404(audit_id):
    audit = STORE["audit_cases"].get(audit_id)
    if audit is None:
        raise_err(ERR_NOT_FOUND, f"Audit case {audit_id} not found")
    return audit


@bp.route("/customs/audit-cases", methods=["POST"])
def create_audit():
    _, role = authenticate()
    require_role(role, {"FirmAdmin"})
    body = get_body()
    client_id = req_str(body, "client_id")
    opened_reason = req_enum(body, "opened_reason", OPENED_REASONS)
    due_date = req_dt(body, "due_date")
    claim_id = body.get("claim_id")

    client = STORE["clients"].get(client_id)
    if client is None:
        raise_err(ERR_NOT_FOUND, f"Client {client_id} not found")
    if claim_id is not None:
        if not isinstance(claim_id, str):
            raise_err(ERR_INVALID_REQUEST, "claim_id must be a string")
        claim = STORE["claims"].get(claim_id)
        if claim is None:
            raise_err(ERR_NOT_FOUND, f"Claim {claim_id} not found")
        if claim["client_id"] != client_id:
            raise_err(ERR_CROSS_CLIENT_REFERENCE, "Claim belongs to a different client")

    audit = mint_entity()
    audit.update({
        "client_id": client_id,
        "claim_id": claim_id,
        "opened_reason": opened_reason,
        "due_date": due_date,
        "status": "OPENED",
        "culpability_level": None,
        "penalty_exposure_cents": 0,
    })
    STORE["audit_cases"][audit["id"]] = audit
    recompute_client_aggregates(client)
    return success_object(serialize(audit), 201)


@bp.route("/customs/audit-cases/<audit_id>", methods=["GET"])
def get_audit(audit_id):
    user_id, role = authenticate()
    require_role(role, ALL_ROLES)
    audit = get_audit_or_404(audit_id)
    require_client_scope(user_id, role, audit["client_id"])
    return success_object(serialize(audit))


@bp.route("/customs/audit-cases", methods=["GET"])
def list_audits():
    user_id, role = authenticate()
    require_role(role, ALL_ROLES)
    items = sorted_by_creation(STORE["audit_cases"].values())
    if role == "ClientContact":
        items = [a for a in items if a["client_id"] == user_id]
    client_id = request.args.get("client_id")
    if client_id is not None:
        items = [a for a in items if a["client_id"] == client_id]
    claim_id = request.args.get("claim_id")
    if claim_id is not None:
        items = [a for a in items if a["claim_id"] == claim_id]
    status = request.args.get("status")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    return paginate([serialize(a) for a in items])


@bp.route("/customs/audit-cases/<audit_id>/advance", methods=["POST"])
def advance_audit(audit_id):
    _, role = authenticate()
    require_role(role, {"ComplianceManager"})
    audit = get_audit_or_404(audit_id)
    body = get_body()
    action = req_enum(body, "action", ACTIONS)
    culpability_level = None
    if action == "CLOSE_SUSTAINED":
        if body.get("culpability_level") is None:
            raise_err(ERR_INVALID_REQUEST, "CLOSE_SUSTAINED requires culpability_level")
        culpability_level = req_enum(body, "culpability_level", CULPABILITY_LEVELS)
    elif body.get("culpability_level") is not None:
        req_enum(body, "culpability_level", CULPABILITY_LEVELS)

    if audit["status"] in TERMINAL:
        raise_err(ERR_ALREADY_TERMINAL, f"Audit case is {audit['status']} (terminal)")

    current = audit["status"]
    client = STORE["clients"][audit["client_id"]]

    if action == "START_EVIDENCE":
        if current != "OPENED":
            raise_err(ERR_INVALID_STATE, f"START_EVIDENCE requires OPENED (got {current})")
        audit["status"] = "EVIDENCE_GATHERING"
    elif action == "FILE_RESPONSE":
        if current != "EVIDENCE_GATHERING":
            raise_err(ERR_INVALID_STATE, f"FILE_RESPONSE requires EVIDENCE_GATHERING (got {current})")
        if logical_now() > audit["due_date"]:
            raise_err(ERR_RESPONSE_PAST_DUE, "Response deadline (due_date) has passed")
        audit["status"] = "RESPONSE_FILED"
    elif action == "REQUEST_MORE":
        if current != "RESPONSE_FILED":
            raise_err(ERR_INVALID_STATE, f"REQUEST_MORE requires RESPONSE_FILED (got {current})")
        audit["status"] = "EVIDENCE_GATHERING"
    elif action == "CLOSE_REFUTED":
        if current != "RESPONSE_FILED":
            raise_err(ERR_INVALID_STATE, f"CLOSE_REFUTED requires RESPONSE_FILED (got {current})")
        audit["status"] = "CLOSED_REFUTED"
    else:  # CLOSE_SUSTAINED
        if current != "RESPONSE_FILED":
            raise_err(ERR_INVALID_STATE, f"CLOSE_SUSTAINED requires RESPONSE_FILED (got {current})")
        audit["status"] = "CLOSED_SUSTAINED"
        audit["culpability_level"] = culpability_level
        # Penalty scope: the linked PAID claim, else all of the client's PAID claims.
        scope_paid_total = 0
        linked = STORE["claims"].get(audit["claim_id"]) if audit["claim_id"] else None
        if linked is not None and linked["status"] == "PAID":
            scope_paid_total = linked["paid_duty_cents"] or 0
        else:
            scope_paid_total = sum(
                c["paid_duty_cents"] or 0
                for c in STORE["claims"].values()
                if c["client_id"] == audit["client_id"] and c["status"] == "PAID"
            )
        rate_bps = CULPABILITY_RATE_BPS[culpability_level]
        audit["penalty_exposure_cents"] = rhu(Fraction(scope_paid_total * rate_bps, 10000))

    touch(audit)
    recompute_client_aggregates(client)
    return success_object(serialize(audit))
