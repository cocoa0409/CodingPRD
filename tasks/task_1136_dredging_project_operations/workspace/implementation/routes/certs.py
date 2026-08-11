"""PaymentCertificate endpoints (PRD 3.9): draft -> submit (fork to
AUDIT_HOLD) -> certify/dispute/revise/void/pay with full ledger compensation."""
import uuid

from flask import Blueprint, g

from db import store
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_FINAL_ACCEPTANCE_INCOMPLETE,
    ERR_CLAIM_NOT_APPROVED,
)
from middleware import require_roles, ALL_ROLES
from response import ok
from routes.common import list_response
from services import (
    serialize_cert,
    compute_cert_snapshot,
    clear_cert_snapshot,
    RECON_TOLERANCE_PCT,
)
from util import (
    as_enum,
    as_list,
    as_str,
    check,
    get_body,
    new_entity,
    parse_dt,
    req_present,
    touch,
)

bp = Blueprint("certs", __name__)


@bp.post("/payment-certificates")
@require_roles("ContractorOps")
def create_cert():
    body = get_body()
    # Existence (class 3): project FK, then cross-project reach references fail
    # here too (a reach of another project is answered 404, PRD 2.10).
    project_id = body.get("project_id")
    if project_id is not None and project_id not in store.projects:
        raise ApiError(ERR_NOT_FOUND, "Project not found", 404)
    reach_ids_raw = body.get("reach_ids")
    if project_id is not None and isinstance(reach_ids_raw, list):
        for rid in reach_ids_raw:
            if isinstance(rid, str):
                reach = store.reaches.get(rid)
                if reach is not None and reach["project_id"] != project_id:
                    raise ApiError(
                        ERR_NOT_FOUND, "Reach belongs to a different project", 404
                    )
    # Shape (class 5).
    project_id = as_str(req_present(body, "project_id"), "project_id")
    cert_type = as_enum(
        req_present(body, "certificate_type"), "certificate_type", ["INTERIM", "FINAL"]
    )
    period_start = parse_dt(req_present(body, "period_start_utc"), "period_start_utc")
    period_end = parse_dt(req_present(body, "period_end_utc"), "period_end_utc")
    check(period_end > period_start, "period_end_utc must be > period_start_utc")
    reach_ids = as_list(req_present(body, "reach_ids"), "reach_ids")
    resolved_reach_ids = []
    for rid in reach_ids:
        rid = as_str(rid, "reach_ids element")
        if rid not in store.reaches:
            raise ApiError(
                ERR_INVALID_REQUEST, "reach_ids contains an unresolvable element", 400
            )
        resolved_reach_ids.append(rid)
    claim_ids_raw = body.get("standby_claim_ids") or []
    claim_ids = as_list(claim_ids_raw, "standby_claim_ids")
    resolved_claim_ids = []
    for cid in claim_ids:
        cid = as_str(cid, "standby_claim_ids element")
        if cid not in store.claims:
            raise ApiError(
                ERR_INVALID_REQUEST,
                "standby_claim_ids contains an unresolvable element",
                400,
            )
        resolved_claim_ids.append(cid)
    # Fiscal (class 12): each listed claim must be APPROVED, same project, not
    # already SETTLED.
    for cid in resolved_claim_ids:
        claim = store.claims[cid]
        if claim["status"] != "APPROVED" or claim["project_id"] != project_id:
            raise ApiError(
                ERR_CLAIM_NOT_APPROVED,
                "Listed standby claim must be APPROVED and belong to the project",
                422,
            )
    rec = new_entity(
        {
            "id": str(uuid.uuid4()),
            "project_id": project_id,
            "certificate_type": cert_type,
            "period_start_utc": period_start,
            "period_end_utc": period_end,
            "reach_ids": resolved_reach_ids,
            "standby_claim_ids": resolved_claim_ids,
            "quantity_cy": None,
            "quantity_amount_cents": None,
            "standby_amount_cents": None,
            "liquidated_damages_cents": None,
            "reconciliation_delta_pct": None,
            "survey_derived_total_cy": None,
            "scow_derived_total_cy": None,
            "total_amount_cents": None,
            "submitted_by_user_id": None,
            "override_note": None,
            "status": "DRAFT",
            "_line_qty": [],
        }
    )
    store.certs[rec["id"]] = rec
    return ok(serialize_cert(rec), 201)


def _get_cert(cid):
    cert = store.certs.get(cid)
    if cert is None:
        raise ApiError(ERR_NOT_FOUND, "PaymentCertificate not found", 404)
    return cert


@bp.get("/payment-certificates/<cid>")
@require_roles(*ALL_ROLES)
def get_cert(cid):
    return ok(serialize_cert(_get_cert(cid)))


@bp.get("/payment-certificates")
@require_roles(*ALL_ROLES)
def list_certs():
    return list_response(
        store.certs, serialize_cert, ["project_id", "status", "certificate_type"]
    )


@bp.post("/payment-certificates/<cid>/submit")
@require_roles("ContractorOps")
def submit_cert(cid):
    cert = _get_cert(cid)
    if cert["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, "Only a DRAFT certificate can be submitted", 409)
    # FINAL requires every listed reach ACCEPTED (class 6).
    if cert["certificate_type"] == "FINAL":
        if any(store.reaches[rid]["status"] != "ACCEPTED" for rid in cert["reach_ids"]):
            raise ApiError(
                ERR_FINAL_ACCEPTANCE_INCOMPLETE,
                "Every reach on a FINAL certificate must be ACCEPTED",
                409,
            )
    compute_cert_snapshot(cert, g.user_id)
    # Automatic fork: a FINAL whose reconciliation delta exceeds the tolerance
    # goes straight to AUDIT_HOLD, snapshot frozen exactly as on SUBMITTED.
    if (
        cert["certificate_type"] == "FINAL"
        and cert["reconciliation_delta_pct"] is not None
        and cert["reconciliation_delta_pct"] > RECON_TOLERANCE_PCT
    ):
        cert["status"] = "AUDIT_HOLD"
    else:
        cert["status"] = "SUBMITTED"
    touch(cert)
    return ok(serialize_cert(cert))


def _certify_effects(cert):
    """Ledger movement shared by SUBMITTED->CERTIFIED and AUDIT_HOLD->CERTIFIED."""
    for rid, qty in cert["_line_qty"]:
        reach = store.reaches[rid]
        reach["cumulative_certified_quantity_cy"] += qty
        touch(reach)
    for claim_id in cert["standby_claim_ids"]:
        claim = store.claims[claim_id]
        if claim["status"] == "APPROVED":
            claim["status"] = "SETTLED"
            touch(claim)
    project = store.projects[cert["project_id"]]
    project["total_certified_cents"] += cert["total_amount_cents"]
    touch(project)


@bp.post("/payment-certificates/<cid>/certify")
@require_roles("OwnerEngineer")
def certify_cert(cid):
    cert = _get_cert(cid)
    body = get_body()
    # Shape (class 5): certifying out of AUDIT_HOLD requires override_note; this
    # fires before the segregation check (PRD 3.9).
    override_note = body.get("override_note")
    if cert["status"] == "AUDIT_HOLD" and (
        override_note is None or not isinstance(override_note, str) or not override_note
    ):
        raise ApiError(
            ERR_INVALID_REQUEST,
            "override_note is required when certifying from AUDIT_HOLD",
            400,
        )
    # State gate (class 6).
    if cert["status"] not in ("SUBMITTED", "AUDIT_HOLD"):
        raise ApiError(
            ERR_INVALID_STATE,
            "Only a SUBMITTED or AUDIT_HOLD certificate can be certified",
            409,
        )
    # Segregation of duties (class 8).
    if g.user_id == cert["submitted_by_user_id"]:
        raise ApiError(
            ERR_SEGREGATION_OF_DUTIES,
            "The certificate submitter cannot certify it",
            403,
        )
    if isinstance(override_note, str) and override_note:
        cert["override_note"] = override_note
    _certify_effects(cert)
    cert["status"] = "CERTIFIED"
    touch(cert)
    return ok(serialize_cert(cert))


@bp.post("/payment-certificates/<cid>/dispute")
@require_roles("OwnerEngineer")
def dispute_cert(cid):
    cert = _get_cert(cid)
    if cert["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, "Only a SUBMITTED certificate can be disputed", 409)
    # Snapshot retained for reference; no ledger movement.
    cert["status"] = "DISPUTED"
    touch(cert)
    return ok(serialize_cert(cert))


@bp.post("/payment-certificates/<cid>/revise")
@require_roles("ContractorOps")
def revise_cert(cid):
    cert = _get_cert(cid)
    if cert["status"] != "DISPUTED":
        raise ApiError(ERR_INVALID_STATE, "Only a DISPUTED certificate can be revised", 409)
    clear_cert_snapshot(cert)
    cert["submitted_by_user_id"] = None
    cert["override_note"] = None
    cert["status"] = "DRAFT"
    touch(cert)
    return ok(serialize_cert(cert))


@bp.post("/payment-certificates/<cid>/void")
@require_roles("OwnerEngineer")
def void_cert(cid):
    cert = _get_cert(cid)
    if cert["status"] != "CERTIFIED":
        # PAID certificates cannot be voided; every other from-state is wrong.
        raise ApiError(ERR_INVALID_STATE, "Only a CERTIFIED certificate can be voided", 409)
    # Full compensation of the certification side effects.
    project = store.projects[cert["project_id"]]
    project["total_certified_cents"] -= cert["total_amount_cents"]
    touch(project)
    for rid, qty in cert["_line_qty"]:
        reach = store.reaches[rid]
        reach["cumulative_certified_quantity_cy"] -= qty
        touch(reach)
    for claim_id in cert["standby_claim_ids"]:
        claim = store.claims[claim_id]
        if claim["status"] == "SETTLED":
            claim["status"] = "APPROVED"
            touch(claim)
    cert["status"] = "VOIDED"
    touch(cert)
    return ok(serialize_cert(cert))


@bp.post("/payment-certificates/<cid>/pay")
@require_roles("OwnerEngineer")
def pay_cert(cid):
    cert = _get_cert(cid)
    if cert["status"] != "CERTIFIED":
        raise ApiError(ERR_INVALID_STATE, "Only a CERTIFIED certificate can be paid", 409)
    project = store.projects[cert["project_id"]]
    project["total_paid_cents"] += cert["total_amount_cents"]
    touch(project)
    cert["status"] = "PAID"
    touch(cert)
    return ok(serialize_cert(cert))
