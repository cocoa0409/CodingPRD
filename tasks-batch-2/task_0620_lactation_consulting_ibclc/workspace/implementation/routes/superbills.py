"""Superbills and insurance reimbursement (PRD §3.9)."""
from flask import Blueprint, request

import db
from errors import (
    err,
    ERR_INVALID_REQUEST,
    ERR_CONSULT_NOT_COMPLETED,
    ERR_ACA_PREVENTIVE_DISABLED,
    ERR_SUPERBILL_NOT_SUBMITTABLE,
    ERR_SUPERBILL_NOT_SUBMITTED,
    ERR_SUPERBILL_NOT_VOIDABLE,
    ERR_STALE_CLIENT_VERSION,
)
from middleware import get_auth, require_roles
from response import object_response, array_response
from services.common import (
    init_full, touch, serialize, get_body,
    require_str, require_int, optional_int, optional_bool,
    require_enum, paginate,
)
from services.lookups import get_or_404, get_fk_or_404
from services.calculations import reimbursement_amount

bp = Blueprint("superbills", __name__)

READ_ROLES = {"PracticeAdmin", "BillingSpecialist", "Consultant", "Client"}


@bp.post("/superbills")
def create_superbill():
    # PRD §3.9 / §4: BillingSpecialist only.
    _, role = get_auth()
    require_roles(role, {"BillingSpecialist"})
    body = get_body()
    consult_id = require_str(body, "consult_id")
    # FK existence.
    consult = get_fk_or_404(db.consults, consult_id)
    # Well-formedness.
    billed = require_int(body, "billed_amount_cents")
    allowed = require_int(body, "allowed_amount_cents")
    is_aca = optional_bool(body, "is_aca_preventive", False)
    deductible_remaining = optional_int(body, "deductible_remaining_cents", 0)
    coinsurance_pct = optional_int(body, "coinsurance_pct", 0)
    if coinsurance_pct < 0 or coinsurance_pct > 100:
        raise err(ERR_INVALID_REQUEST, "coinsurance_pct must be 0..100")

    # Parent consult must be COMPLETED (priority 9, PRD §3.9).
    if consult["status"] != "COMPLETED":
        raise err(ERR_CONSULT_NOT_COMPLETED, "Parent consult is not COMPLETED")

    # ACA-preventive availability (priority 11, PRD §3.9).
    practice = db.practices[consult["practice_id"]]
    if is_aca and not practice["aca_preventive_enabled"]:
        raise err(ERR_ACA_PREVENTIVE_DISABLED,
                  "Practice does not have aca_preventive_enabled")

    record = {
        "consult_id": consult_id,
        "client_id": consult["client_id"],  # copied from consult
        "billed_amount_cents": billed,
        "allowed_amount_cents": allowed,
        "is_aca_preventive": is_aca,
        "deductible_remaining_cents": deductible_remaining,
        "coinsurance_pct": coinsurance_pct,
        "reimbursed_amount_cents": 0,
        "patient_responsibility_cents": 0,
        "status": "DRAFT",
    }
    init_full(record)
    db.superbills[record["id"]] = record
    return object_response(serialize(record), 201)


@bp.get("/superbills/<rid>")
def get_superbill(rid):
    _, role = get_auth()
    require_roles(role, READ_ROLES)
    record = get_or_404(db.superbills, rid)
    return object_response(serialize(record), 200)


@bp.get("/superbills")
def list_superbills():
    _, role = get_auth()
    require_roles(role, READ_ROLES)
    consult_id = request.args.get("consult_id")
    client_id = request.args.get("client_id")
    records = []
    for r in db.superbills.values():
        if consult_id is not None and r["consult_id"] != consult_id:
            continue
        if client_id is not None and r["client_id"] != client_id:
            continue
        records.append(r)
    items, limit, offset, total = paginate(records)
    return array_response(items, limit, offset, total, 200)


@bp.post("/superbills/<rid>/submit")
def submit_superbill(rid):
    _, role = get_auth()
    require_roles(role, {"BillingSpecialist"})
    sb = get_or_404(db.superbills, rid)
    # Submit allowed from DRAFT or DENIED (resubmit loop) (PRD §3.9).
    if sb["status"] not in ("DRAFT", "DENIED"):
        raise err(ERR_SUPERBILL_NOT_SUBMITTABLE, "Superbill is not submittable")
    # Parent consult must still be COMPLETED.
    consult = db.consults[sb["consult_id"]]
    if consult["status"] != "COMPLETED":
        raise err(ERR_CONSULT_NOT_COMPLETED, "Parent consult is not COMPLETED")
    sb["status"] = "SUBMITTED"
    touch(sb)
    return object_response(serialize(sb), 200)


@bp.post("/superbills/<rid>/adjudicate")
def adjudicate_superbill(rid):
    _, role = get_auth()
    require_roles(role, {"BillingSpecialist"})
    sb = get_or_404(db.superbills, rid)
    body = get_body()
    outcome = require_enum(body, "outcome", {"PAID", "DENIED"})
    # Must be SUBMITTED (PRD §3.9).
    if sb["status"] != "SUBMITTED":
        raise err(ERR_SUPERBILL_NOT_SUBMITTED, "Superbill is not SUBMITTED")

    if outcome == "PAID":
        practice = db.practices[db.consults[sb["consult_id"]]["practice_id"]]
        reimbursed, patient_resp = reimbursement_amount(
            sb, practice["aca_preventive_enabled"]
        )
        sb["reimbursed_amount_cents"] = reimbursed
        sb["patient_responsibility_cents"] = patient_resp
        sb["status"] = "PAID"
        # Ledger increase + client version bump (PRD §3.9).
        client = db.clients[sb["client_id"]]
        client["reimbursement_ledger_cents"] += reimbursed
        touch(client)
    else:  # DENIED
        sb["reimbursed_amount_cents"] = 0
        sb["patient_responsibility_cents"] = sb["allowed_amount_cents"]
        sb["status"] = "DENIED"
    touch(sb)
    return object_response(serialize(sb), 200)


@bp.post("/superbills/<rid>/void")
def void_superbill(rid):
    _, role = get_auth()
    require_roles(role, {"BillingSpecialist"})
    sb = get_or_404(db.superbills, rid)
    body = get_body()
    # expected_client_version is non-optional (PRD §2.9).
    expected = require_int(body, "expected_client_version")
    # Must be PAID (PRD §3.9).
    if sb["status"] != "PAID":
        raise err(ERR_SUPERBILL_NOT_VOIDABLE, "Superbill is not PAID")
    # OCC guard on Client.version (PRD §2.9).
    client = db.clients[sb["client_id"]]
    if expected != client["version"]:
        raise err(ERR_STALE_CLIENT_VERSION, "Stale client version")
    # Reverse ledger contribution; bump client version (PRD §3.9).
    client["reimbursement_ledger_cents"] -= sb["reimbursed_amount_cents"]
    touch(client)
    sb["status"] = "VOID"
    touch(sb)
    return object_response(serialize(sb), 200)
