"""Disclosure routes — APR snapshot, TRID recompute, CD redisclose, OCC."""
from __future__ import annotations

from decimal import Decimal

from flask import Blueprint, request

import db
import response
from errors import (
    ApiError,
    ERR_APPLICANT_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_STALE_VERSION,
)
from middleware import require_auth
from services import calculations
from services.common import (
    bump,
    get_json_body,
    new_common_fields,
    paginate,
    parse_pagination,
    require_enum,
    require_int,
    require_str,
    sorted_by_created_at,
)
from services.lookup import get_subresource_or_404

bp = Blueprint("disclosures", __name__)

DISCLOSURE_TYPES = {"LOAN_ESTIMATE", "CLOSING_DISCLOSURE"}


def disc_to_dict(d: dict) -> dict:
    def _dec(v):
        if isinstance(v, Decimal):
            return float(v)
        return v

    return {
        "id": d["id"],
        "application_id": d["application_id"],
        "disclosure_type": d["disclosure_type"],
        "status": d["status"],
        "delivered_at": d.get("delivered_at"),
        "acknowledged_at": d.get("acknowledged_at"),
        "apr_at_issuance": _dec(d.get("apr_at_issuance")),
        "change_requires_redisclose": d.get("change_requires_redisclose", False),
        "earliest_consummation_at": d.get("earliest_consummation_at"),
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


@bp.post("/disclosures")
@require_auth(roles=["LoanOfficer"])
def create_disclosure():
    body = get_json_body()
    application_id = require_str(body, "application_id")
    if application_id not in db.loan_applications:
        raise ApiError(ERR_APPLICANT_NOT_FOUND, "application_id does not refer to a known loan application.")
    la = db.loan_applications[application_id]
    disclosure_type = require_enum(body, "disclosure_type", DISCLOSURE_TYPES)

    expected = body.get("expected_application_version")
    if expected is None or isinstance(expected, bool) or not isinstance(expected, int):
        raise ApiError(ERR_INVALID_REQUEST, "expected_application_version (int) is required.")
    if expected != la["version"]:
        raise ApiError(ERR_STALE_VERSION, "expected_application_version does not match.")

    with db.lock:
        d = {
            **new_common_fields(),
            "application_id": application_id,
            "disclosure_type": disclosure_type,
            "status": "DRAFT",
            "delivered_at": None,
            "acknowledged_at": None,
            "apr_at_issuance": None,
            "change_requires_redisclose": False,
            "earliest_consummation_at": None,
        }
        db.disclosures[d["id"]] = d
        # Side effect: bump LoanApplication.version.
        bump(la)
    return response.ok(disc_to_dict(d), status=201)


@bp.get("/disclosures/<d_id>")
@require_auth(roles=["LoanOfficer", "Underwriter", "Closer", "Applicant"])
def read_disclosure(d_id: str):
    d = get_subresource_or_404(db.disclosures, d_id)
    return response.ok(disc_to_dict(d))


@bp.get("/disclosures")
@require_auth(roles=["LoanOfficer", "Underwriter", "Closer", "Applicant"])
def list_disclosures():
    limit, offset = parse_pagination()
    application_id = request.args.get("application_id")
    disclosure_type = request.args.get("disclosure_type")
    status = request.args.get("status")
    items = list(db.disclosures.values())
    if application_id is not None:
        items = [x for x in items if x["application_id"] == application_id]
    if disclosure_type is not None:
        items = [x for x in items if x["disclosure_type"] == disclosure_type]
    if status is not None:
        items = [x for x in items if x["status"] == status]
    items = sorted_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return response.list_ok([disc_to_dict(x) for x in page], limit, offset, total)


@bp.post("/disclosures/<d_id>/deliver")
@require_auth(roles=["LoanOfficer"])
def deliver_disclosure(d_id: str):
    d = get_subresource_or_404(db.disclosures, d_id)
    with db.lock:
        if d["status"] != "DRAFT":
            raise ApiError(ERR_INVALID_STATE, "Disclosure is not in DRAFT.")
        la = db.loan_applications.get(d["application_id"])
        if la is None:
            raise ApiError(ERR_INVALID_STATE, "Parent application no longer exists.")
        # LE: app must be in PREQUALIFIED|UNDER_REVIEW|APPROVED.
        # CD: app must be in UNDER_REVIEW|APPROVED, AND there must be a prior DELIVERED/ACKNOWLEDGED LE.
        if d["disclosure_type"] == "LOAN_ESTIMATE":
            if la["status"] not in ("PREQUALIFIED", "UNDER_REVIEW", "APPROVED"):
                raise ApiError(
                    ERR_INVALID_STATE,
                    "LOAN_ESTIMATE may only be delivered while parent in PREQUALIFIED/UNDER_REVIEW/APPROVED.",
                )
        else:
            if la["status"] not in ("UNDER_REVIEW", "APPROVED"):
                raise ApiError(
                    ERR_INVALID_STATE,
                    "CLOSING_DISCLOSURE may only be delivered while parent in UNDER_REVIEW/APPROVED.",
                )
            has_le = any(
                x["application_id"] == la["id"]
                and x["disclosure_type"] == "LOAN_ESTIMATE"
                and x["status"] in ("DELIVERED", "ACKNOWLEDGED")
                for x in db.disclosures.values()
            )
            if not has_le:
                raise ApiError(
                    ERR_INVALID_STATE,
                    "CLOSING_DISCLOSURE requires a prior DELIVERED/ACKNOWLEDGED LOAN_ESTIMATE.",
                )

        # Compute APR snapshot for the disclosure & update LoanApplication.
        if d["disclosure_type"] == "LOAN_ESTIMATE":
            apr = calculations.compute_apr_percent(la, variant="provisional")
            d["apr_at_issuance"] = apr
            la["provisional_apr"] = apr
        else:
            apr = calculations.compute_apr_percent(la, variant="final")
            d["apr_at_issuance"] = apr
            la["final_apr"] = apr

        # Stamp delivered_at.
        d["delivered_at"] = db.fmt_ts(db.utcnow())
        d["status"] = "DELIVERED"

        # CD redisclose check — done on THIS disclosure's apr vs prior CD's apr.
        if d["disclosure_type"] == "CLOSING_DISCLOSURE":
            d["change_requires_redisclose"] = calculations.cd_redisclose_check(
                la["id"], apr if apr is not None else Decimal("0"), current_id=d["id"]
            )

        # Supersede any prior DELIVERED/ACKNOWLEDGED of the SAME type for this application.
        for other in db.disclosures.values():
            if other["id"] == d["id"]:
                continue
            if other["application_id"] != la["id"]:
                continue
            if other["disclosure_type"] != d["disclosure_type"]:
                continue
            if other["status"] in ("DELIVERED", "ACKNOWLEDGED"):
                other["status"] = "SUPERSEDED"
                bump(other)

        # Recompute LoanApplication.earliest_consummation_at AFTER status set.
        la["earliest_consummation_at"] = calculations.trid_earliest_consummation(la["id"])
        # Snapshot earliest_consummation_at onto this Disclosure.
        d["earliest_consummation_at"] = la["earliest_consummation_at"]

        bump(d)
        bump(la)
    return response.ok(disc_to_dict(d))


@bp.post("/disclosures/<d_id>/acknowledge")
@require_auth(roles=["Applicant"])
def acknowledge_disclosure(d_id: str):
    from flask import g

    d = get_subresource_or_404(db.disclosures, d_id)
    with db.lock:
        if d["status"] != "DELIVERED":
            raise ApiError(ERR_INVALID_STATE, "Disclosure is not DELIVERED.")
        la = db.loan_applications.get(d["application_id"])
        if la is None:
            raise ApiError(ERR_INVALID_STATE, "Parent application no longer exists.")
        if la["status"] in ("CLOSED", "DENIED", "WITHDRAWN"):
            raise ApiError(ERR_INVALID_STATE, "Parent application is in a terminal state.")
        # Ownership: Applicant's X-User-ID must equal the application's applicant_id.
        if g.user_id != la["applicant_id"]:
            from errors import ERR_UNAUTHORIZED
            raise ApiError(ERR_UNAUTHORIZED, "Applicant may only acknowledge their own application's disclosures.")
        d["acknowledged_at"] = db.fmt_ts(db.utcnow())
        d["status"] = "ACKNOWLEDGED"
        bump(d)
    return response.ok(disc_to_dict(d))
