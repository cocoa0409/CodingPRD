"""Participation certificates / buyer commitments (PRD 3.4)."""
from decimal import Decimal

from flask import Blueprint, request

import db
import serialize as ser
from errors import (
    not_found, invalid_state, raise_err,
    ERR_NOT_OWNER, ERR_AGREEMENT_NOT_ACTIVE, ERR_OFFERING_NOT_OPEN,
    ERR_CU_NOT_ACTIVE, ERR_WINDOW_CLOSED, ERR_SELF_PARTICIPATION,
    ERR_DUP_COMMITMENT, ERR_MIN_SHARE, ERR_POOL_EXHAUSTED, ERR_CONCENTRATION,
)
from middleware import (
    auth_context, require_role, body, req_int, touch, paginate, ALL_ROLES,
)
from response import success
from serialize import OPEN_CERT_STATUSES
from services import calc
from services.cascade import recompute_commitment_aggregates

bp = Blueprint("commitments", __name__)

# terminal for the duplicate-commitment rule: DECLINED, RESCINDED, REPURCHASED
TERMINAL_CERT_STATUSES = {"DECLINED", "RESCINDED", "REPURCHASED"}


def _get_certificate(cid):
    c = db.certificates.get(cid)
    if c is None:
        not_found("ParticipationCertificate")
    return c


def _own_certificate(uid, cert):
    if cert["buyer_id"] != uid:
        raise_err(ERR_NOT_OWNER, "BuyerUser must own the certificate")


@bp.post("/network/commitments")
def create_commitment():
    uid, role = auth_context()
    require_role(role, {"BuyerUser"})
    b = body()
    # existence (priority 4): the offering and the buyer credit union
    oid = b.get("offering_id")
    if oid is not None and oid not in db.offerings:
        not_found("ParticipationOffering")
    buyer = db.credit_unions.get(uid)
    if buyer is None:
        not_found("CreditUnion")
    # shape (priority 5)
    if oid is None:
        raise_err_missing("offering_id")
    amount = req_int(b, "committed_amount_cents", minimum=1)
    o = db.offerings[oid]
    agreement = db.agreements[o["servicing_agreement_id"]]
    originator_id = agreement["originator_id"]
    # buyer_id is always set from the caller's X-User-ID; payload value ignored
    # concentration cap (priority 8)
    exposure = sum(
        c["committed_amount_cents"]
        for c in db.certificates.values()
        if c["buyer_id"] == uid and c["status"] in OPEN_CERT_STATUSES
        and _originator_of(c) == originator_id
    )
    cap = calc.concentration_cap(buyer["net_worth_cents"], buyer["concentration_cap_pct"])
    if exposure + amount > cap:
        raise_err(ERR_CONCENTRATION, "Commitment exceeds the buyer's concentration cap for this originator")
    # linked-entity state (priority 9)
    if agreement["status"] != "ACTIVE":
        raise_err(ERR_AGREEMENT_NOT_ACTIVE, "Servicing agreement must be ACTIVE for commitments")
    if o["status"] != "OPEN":
        raise_err(ERR_OFFERING_NOT_OPEN, "Offering must be OPEN for commitments")
    if buyer["status"] != "ACTIVE":
        raise_err(ERR_CU_NOT_ACTIVE, "Buyer credit union must be ACTIVE to commit")
    # commitment window (priority 10), inclusive on both ends
    now = db.clock_now()
    if now < o["open_at"] or now > o["close_at"]:
        raise_err(ERR_WINDOW_CLOSED, "Commitment is outside the offering's [open_at, close_at] window")
    # domain constraints (priority 11)
    if uid == originator_id:
        raise_err(ERR_SELF_PARTICIPATION, "Buyer must not be the offering's originator")
    for c in db.certificates.values():
        if (
            c["offering_id"] == oid
            and c["buyer_id"] == uid
            and c["status"] not in TERMINAL_CERT_STATUSES
        ):
            raise_err(ERR_DUP_COMMITMENT, "Buyer already holds a non-terminal certificate in this offering")
    min_required = Decimal(str(o["min_share_pct"])) * Decimal(o["pool_principal_cents"])
    if Decimal(amount) < min_required:
        raise_err(ERR_MIN_SHARE, "committed_amount_cents is below the offering's minimum share")
    # funds (priority 12)
    remaining = o["pool_principal_cents"] - ser.offering_committed(oid)
    if amount > remaining:
        raise_err(ERR_POOL_EXHAUSTED, "committed_amount_cents exceeds the offering's remaining principal")
    cert = db.insert("certificate", {
        "offering_id": oid,
        "buyer_id": uid,
        "committed_amount_cents": amount,
        "status": "PENDING_DILIGENCE",
        "funded_amount_cents": 0,
        "outstanding_principal_cents": 0,
        "cumulative_interest_cents": 0,
        "cumulative_loss_cents": 0,
        "diligence_decision_at": None,
        "funded_at": None,
    })
    recompute_commitment_aggregates(o, {uid})
    return success(ser.certificate(cert), 201)


def _originator_of(cert):
    off = db.offerings.get(cert["offering_id"])
    if off is None:
        return None
    agr = db.agreements.get(off["servicing_agreement_id"])
    return agr["originator_id"] if agr else None


def raise_err_missing(field):
    from errors import ERR_INVALID_REQUEST
    raise_err(ERR_INVALID_REQUEST, "Missing required field: %s" % field)


@bp.get("/network/commitments/<cid>")
def get_commitment(cid):
    uid, role = auth_context()
    require_role(role, set(ALL_ROLES))
    return success(ser.certificate(_get_certificate(cid)))


@bp.get("/network/commitments")
def list_commitments():
    uid, role = auth_context()
    require_role(role, set(ALL_ROLES))
    items = list(db.certificates.values())
    oid = request.args.get("offering_id")
    if oid is not None:
        items = [c for c in items if c["offering_id"] == oid]
    bid = request.args.get("buyer_id")
    if bid is not None:
        items = [c for c in items if c["buyer_id"] == bid]
    st = request.args.get("status")
    if st is not None:
        items = [c for c in items if c["status"] == st]
    page, meta = paginate(items, ser.certificate)
    return success(page, 200, meta)


@bp.post("/network/commitments/<cid>/approve-diligence")
def approve_diligence(cid):
    uid, role = auth_context()
    require_role(role, {"BuyerUser"})
    cert = _get_certificate(cid)
    _own_certificate(uid, cert)
    if cert["status"] != "PENDING_DILIGENCE":
        invalid_state("Certificate must be PENDING_DILIGENCE to approve diligence")
    cert["status"] = "COMMITTED"
    cert["diligence_decision_at"] = db.clock_now()
    touch("certificate", cert)
    return success(ser.certificate(cert))


@bp.post("/network/commitments/<cid>/decline")
def decline(cid):
    uid, role = auth_context()
    require_role(role, {"BuyerUser"})
    cert = _get_certificate(cid)
    _own_certificate(uid, cert)
    if cert["status"] != "PENDING_DILIGENCE":
        invalid_state("Certificate must be PENDING_DILIGENCE to decline")
    cert["status"] = "DECLINED"
    cert["diligence_decision_at"] = db.clock_now()
    touch("certificate", cert)
    recompute_commitment_aggregates(db.offerings[cert["offering_id"]], {cert["buyer_id"]})
    return success(ser.certificate(cert))


@bp.post("/network/commitments/<cid>/fund")
def fund(cid):
    uid, role = auth_context()
    require_role(role, {"BuyerUser"})
    cert = _get_certificate(cid)
    _own_certificate(uid, cert)
    if cert["status"] != "COMMITTED":
        invalid_state("Certificate must be COMMITTED to fund")
    o = db.offerings[cert["offering_id"]]
    if o["status"] != "OPEN":
        raise_err(ERR_OFFERING_NOT_OPEN, "Offering must be OPEN to fund")
    cert["status"] = "ACTIVE"
    cert["funded_amount_cents"] = cert["committed_amount_cents"]
    cert["outstanding_principal_cents"] = cert["committed_amount_cents"]
    cert["funded_at"] = db.clock_now()
    touch("certificate", cert)
    # auto-close: fires only when the pool is fully committed and every
    # commitment has been funded (no PENDING_DILIGENCE/COMMITTED remain)
    committed_total = ser.offering_committed(o["id"])
    unfunded_left = any(
        c["offering_id"] == o["id"] and c["status"] in ("PENDING_DILIGENCE", "COMMITTED")
        for c in db.certificates.values()
    )
    if (
        o["status"] == "OPEN"
        and o["pool_principal_cents"] - committed_total == 0
        and not unfunded_left
    ):
        o["status"] = "CLOSED"
        touch("offering", o)
    return success(ser.certificate(cert))


@bp.post("/network/commitments/<cid>/rescind")
def rescind(cid):
    uid, role = auth_context()
    require_role(role, {"BuyerUser"})
    cert = _get_certificate(cid)
    _own_certificate(uid, cert)
    if cert["status"] != "COMMITTED":
        invalid_state("Certificate must be COMMITTED to rescind")
    cert["status"] = "RESCINDED"
    touch("certificate", cert)
    recompute_commitment_aggregates(db.offerings[cert["offering_id"]], {cert["buyer_id"]})
    return success(ser.certificate(cert))
