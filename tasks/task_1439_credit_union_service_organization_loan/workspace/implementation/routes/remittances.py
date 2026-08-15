"""Remittance lifecycle and delinquency management (PRD 3.5)."""
from datetime import datetime, timezone

from flask import Blueprint, request

import db
import serialize as ser
from errors import (
    not_found, invalid_state, raise_err,
    ERR_NOT_OWNER, ERR_REMIT_OVERLAP, ERR_COLLECTIONS,
)
from middleware import (
    auth_context, require_role, body, req_int, req_dt, touch, paginate, ALL_ROLES,
)
from response import success
from services import calc
from services.cascade import (
    agreement_of_certificate, offering_of_certificate, agreement_maybe_reinstate,
)

bp = Blueprint("remittances", __name__)


def _get_remittance(rid):
    r = db.remittances.get(rid)
    if r is None:
        not_found("Remittance")
    return r


def _own_originator(uid, cert):
    agreement = agreement_of_certificate(cert)
    if agreement["originator_id"] != uid:
        raise_err(ERR_NOT_OWNER, "OriginatorUser must own the agreement behind the certificate")
    return agreement


def _due_at(agreement, period_end):
    """remittance_due_day of the month following period_end's month, 00:00:00Z."""
    year = period_end.year
    month = period_end.month + 1
    if month > 12:
        month = 1
        year += 1
    return datetime(year, month, agreement["remittance_due_day"], tzinfo=timezone.utc)


@bp.post("/network/remittances")
def create_remittance():
    uid, role = auth_context()
    require_role(role, {"OriginatorUser"})
    b = body()
    cid = b.get("certificate_id")
    if cid is not None and cid not in db.certificates:
        not_found("ParticipationCertificate")
    cert = db.certificates.get(cid) if cid is not None else None
    if cert is not None:
        agreement = _own_originator(uid, cert)
    if cid is None:
        from errors import ERR_INVALID_REQUEST
        raise_err(ERR_INVALID_REQUEST, "Missing required field: certificate_id")
    period_start = req_dt(b, "period_start")
    period_end = req_dt(b, "period_end")
    if period_end < period_start:
        from errors import ERR_INVALID_REQUEST
        raise_err(ERR_INVALID_REQUEST, "period_end must not be earlier than period_start")
    collections = req_int(b, "collections_cents", minimum=0)
    # state (priority 7): remittances are scheduled for an ACTIVE certificate
    if cert["status"] != "ACTIVE":
        invalid_state("Certificate must be ACTIVE to schedule a remittance")
    # closed-period overlap per certificate (priority 10), REVERSED excluded
    for r in db.remittances.values():
        if r["certificate_id"] == cid and r["status"] != "REVERSED":
            if period_start <= r["period_end"] and r["period_start"] <= period_end:
                raise_err(
                    ERR_REMIT_OVERLAP,
                    "Remittance period overlaps another non-REVERSED remittance of this certificate",
                )
    # settlement split (pinned order): beginning outstanding -> fee -> interest -> principal
    o = offering_of_certificate(cert)
    days = calc.day_count(agreement["day_count_convention"], period_start.date(), period_end.date())
    beginning = cert["outstanding_principal_cents"]
    fee = calc.servicing_fee(beginning, agreement["servicing_fee_bps"], days)
    interest = calc.accrued_interest(beginning, o["yield_rate_bps"], days)
    if collections < interest + fee:
        raise_err(ERR_COLLECTIONS, "collections_cents is below interest plus servicing fee")
    principal = collections - interest - fee
    r = db.insert("remittance", {
        "certificate_id": cid,
        "period_start": period_start,
        "period_end": period_end,
        "collections_cents": collections,
        "due_at": _due_at(agreement, period_end),
        "interest_portion_cents": interest,
        "servicing_fee_cents": fee,
        "principal_portion_cents": principal,
        "penalty_cents": 0,
        "status": "SCHEDULED",
        "paid_at": None,
    })
    return success(ser.remittance(r), 201)


@bp.get("/network/remittances/<rid>")
def get_remittance(rid):
    uid, role = auth_context()
    require_role(role, set(ALL_ROLES))
    return success(ser.remittance(_get_remittance(rid)))


@bp.get("/network/remittances")
def list_remittances():
    uid, role = auth_context()
    require_role(role, set(ALL_ROLES))
    items = list(db.remittances.values())
    cid = request.args.get("certificate_id")
    if cid is not None:
        items = [r for r in items if r["certificate_id"] == cid]
    st = request.args.get("status")
    if st is not None:
        items = [r for r in items if r["status"] == st]
    page, meta = paginate(items, ser.remittance)
    return success(page, 200, meta)


@bp.post("/network/remittances/<rid>/pay")
def pay_remittance(rid):
    uid, role = auth_context()
    require_role(role, {"OriginatorUser"})
    r = _get_remittance(rid)
    cert = db.certificates[r["certificate_id"]]
    agreement = _own_originator(uid, cert)
    if r["status"] not in ("SCHEDULED", "LATE_UNPAID"):
        invalid_state("Remittance must be SCHEDULED or LATE_UNPAID to pay")
    if cert["status"] != "ACTIVE":
        invalid_state("Certificate must be ACTIVE to pay a remittance")
    now = db.clock_now()
    was_late_unpaid = r["status"] == "LATE_UNPAID"
    if r["status"] == "SCHEDULED" and now <= r["due_at"]:
        r["status"] = "PAID"
        r["penalty_cents"] = 0
    else:
        r["status"] = "PAID_LATE"
        days_late = (now.date() - r["due_at"].date()).days
        r["penalty_cents"] = calc.late_penalty(
            r["interest_portion_cents"], r["principal_portion_cents"], days_late
        )
    r["paid_at"] = now
    touch("remittance", r)
    if was_late_unpaid:
        agreement["late_remittance_count"] -= 1
        touch("agreement", agreement)
        agreement_maybe_reinstate(agreement)
    cert["outstanding_principal_cents"] -= r["principal_portion_cents"]
    cert["cumulative_interest_cents"] += r["interest_portion_cents"]
    if cert["outstanding_principal_cents"] == 0:
        cert["status"] = "PAID_OFF"
    touch("certificate", cert)
    return success(ser.remittance(r))


@bp.post("/network/remittances/<rid>/reverse")
def reverse_remittance(rid):
    uid, role = auth_context()
    require_role(role, {"NetworkAdmin"})
    r = _get_remittance(rid)
    if r["status"] not in ("PAID", "PAID_LATE"):
        invalid_state("Only a PAID or PAID_LATE remittance can be reversed")
    r["status"] = "REVERSED"
    touch("remittance", r)
    cert = db.certificates[r["certificate_id"]]
    cert["outstanding_principal_cents"] += r["principal_portion_cents"]
    cert["cumulative_interest_cents"] -= r["interest_portion_cents"]
    if cert["status"] == "PAID_OFF":
        cert["status"] = "ACTIVE"
    touch("certificate", cert)
    return success(ser.remittance(r))
