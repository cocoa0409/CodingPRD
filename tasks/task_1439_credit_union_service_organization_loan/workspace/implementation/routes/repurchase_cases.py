"""Repurchase cases and the repurchase price (PRD 3.6)."""
from datetime import timedelta

from flask import Blueprint, request

import db
import serialize as ser
from errors import (
    not_found, invalid_state, raise_err,
    ERR_NOT_OWNER, ERR_DUP_REPURCHASE, ERR_INVALID_REQUEST,
)
from middleware import (
    auth_context, require_role, body, req_enum, touch, paginate, ALL_ROLES,
)
from response import success
from services import calc
from services.cascade import (
    agreement_of_certificate, offering_of_certificate,
    certificate_maybe_reactivate, recompute_commitment_aggregates,
)

bp = Blueprint("repurchase_cases", __name__)

TRIGGER_REASONS = {"DOCUMENTATION_DEFAULT", "MATERIAL_BREACH", "FRAUD"}


def _get_case(rid):
    rc = db.repurchase_cases.get(rid)
    if rc is None:
        not_found("RepurchaseCase")
    return rc


def _own_originator_of_cert(uid, cert):
    agreement = agreement_of_certificate(cert)
    if agreement["originator_id"] != uid:
        raise_err(ERR_NOT_OWNER, "OriginatorUser must own the agreement behind the certificate")
    return agreement


@bp.post("/network/repurchase-cases")
def create_case():
    uid, role = auth_context()
    require_role(role, {"BuyerUser"})
    b = body()
    cid = b.get("certificate_id")
    if cid is not None and cid not in db.certificates:
        not_found("ParticipationCertificate")
    cert = db.certificates.get(cid) if cid is not None else None
    if cert is not None and cert["buyer_id"] != uid:
        raise_err(ERR_NOT_OWNER, "BuyerUser must own the certificate")
    if cid is None:
        raise_err(ERR_INVALID_REQUEST, "Missing required field: certificate_id")
    reason = req_enum(b, "trigger_reason", TRIGGER_REASONS)
    if cert["status"] not in ("ACTIVE", "EXCEPTION"):
        invalid_state("Repurchase cases require the certificate to be ACTIVE or EXCEPTION")
    for rc in db.repurchase_cases.values():
        if rc["certificate_id"] == cid and rc["status"] in ("TRIGGERED", "DISPUTED"):
            raise_err(ERR_DUP_REPURCHASE, "An open repurchase case already exists for this certificate")
    rc = db.insert("repurchase_case", {
        "certificate_id": cid,
        "trigger_reason": reason,
        "documentation_exception_id": None,  # set only for sweep-auto-created cases
        "repurchase_price_cents": None,
        "status": "TRIGGERED",
    })
    return success(ser.repurchase_case(rc), 201)


@bp.get("/network/repurchase-cases/<rid>")
def get_case(rid):
    uid, role = auth_context()
    require_role(role, set(ALL_ROLES))
    return success(ser.repurchase_case(_get_case(rid)))


@bp.get("/network/repurchase-cases")
def list_cases():
    uid, role = auth_context()
    require_role(role, set(ALL_ROLES))
    items = list(db.repurchase_cases.values())
    cid = request.args.get("certificate_id")
    if cid is not None:
        items = [r for r in items if r["certificate_id"] == cid]
    st = request.args.get("status")
    if st is not None:
        items = [r for r in items if r["status"] == st]
    did = request.args.get("documentation_exception_id")
    if did is not None:
        items = [r for r in items if r["documentation_exception_id"] == did]
    page, meta = paginate(items, ser.repurchase_case)
    return success(page, 200, meta)


def _repurchase_price(cert, agreement, offering, completion):
    """outstanding + accrued-but-unpaid interest from the day after the most
    recent remittance period_end (or the funded date) through completion,
    inclusive, under the agreement's day-count convention."""
    rems = [r for r in db.remittances.values() if r["certificate_id"] == cert["id"]]
    if rems:
        last_end = max(r["period_end"] for r in rems)
        start = (last_end + timedelta(days=1)).date()
    else:
        start = cert["funded_at"].date()
    end = completion.date()
    days = calc.day_count(agreement["day_count_convention"], start, end) if start <= end else 0
    accrued = calc.accrued_interest(
        cert["outstanding_principal_cents"], offering["yield_rate_bps"], days
    )
    return cert["outstanding_principal_cents"] + accrued


@bp.post("/network/repurchase-cases/<rid>/complete")
def complete_case(rid):
    uid, role = auth_context()
    require_role(role, {"OriginatorUser"})
    rc = _get_case(rid)
    cert = db.certificates[rc["certificate_id"]]
    agreement = _own_originator_of_cert(uid, cert)
    if rc["status"] not in ("TRIGGERED", "DISPUTED"):
        invalid_state("Repurchase case must be TRIGGERED or DISPUTED to complete")
    if cert["status"] not in ("ACTIVE", "EXCEPTION"):
        invalid_state("Certificate must be ACTIVE or EXCEPTION to complete a repurchase")
    now = db.clock_now()
    offering = offering_of_certificate(cert)
    rc["repurchase_price_cents"] = _repurchase_price(cert, agreement, offering, now)
    rc["status"] = "COMPLETED"
    touch("repurchase_case", rc)
    cert["status"] = "REPURCHASED"
    cert["outstanding_principal_cents"] = 0
    touch("certificate", cert)
    recompute_commitment_aggregates(offering, {cert["buyer_id"]})
    return success(ser.repurchase_case(rc))


@bp.post("/network/repurchase-cases/<rid>/dispute")
def dispute_case(rid):
    uid, role = auth_context()
    require_role(role, {"OriginatorUser"})
    rc = _get_case(rid)
    cert = db.certificates[rc["certificate_id"]]
    _own_originator_of_cert(uid, cert)
    if rc["status"] != "TRIGGERED":
        invalid_state("Repurchase case must be TRIGGERED to dispute")
    rc["status"] = "DISPUTED"
    touch("repurchase_case", rc)
    return success(ser.repurchase_case(rc))


@bp.post("/network/repurchase-cases/<rid>/withdraw")
def withdraw_case(rid):
    uid, role = auth_context()
    require_role(role, {"BuyerUser"})
    rc = _get_case(rid)
    cert = db.certificates[rc["certificate_id"]]
    if cert["buyer_id"] != uid:
        raise_err(ERR_NOT_OWNER, "BuyerUser must own the certificate")
    if rc["status"] != "DISPUTED":
        invalid_state("Repurchase case must be DISPUTED to withdraw")
    rc["status"] = "WITHDRAWN"
    touch("repurchase_case", rc)
    certificate_maybe_reactivate(cert)
    return success(ser.repurchase_case(rc))
