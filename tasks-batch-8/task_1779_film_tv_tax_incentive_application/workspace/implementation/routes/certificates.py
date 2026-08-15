"""CreditCertificate endpoints: list, get, redeem."""
from flask import Blueprint, request

from errors import (
    raise_error,
    ERR_AMOUNT_EXCEEDS_REMAINING,
    ERR_CERTIFICATE_EXPIRED,
    ERR_INVALID_STATE_TRANSITION,
)
from helpers import (
    check_producer_owns,
    company_id_of_certificate,
    get_one,
    list_query,
    public,
)
from middleware import authorized
from response import success_object
from services.core import touch
from util import CLOCK, parse_dt
from validate import get_body, reject_unknown_fields, req_int, require_path_resource

bp = Blueprint("certificates", __name__)


@bp.get("/certificates")
def list_certificates():
    return list_query("certificates", {
        "application_id": request.args.get("application_id"),
        "status": request.args.get("status"),
    })


@bp.get("/certificates/<certificateId>")
def get_certificate(certificateId):
    return get_one("certificates", certificateId)


@bp.post("/certificates/<certificateId>/redeem")
def redeem_certificate(certificateId):
    caller = authorized(["Producer"])
    cert = require_path_resource("certificates", certificateId)
    body = get_body()
    reject_unknown_fields(body, {"redeem_amount_cents"})
    redeem_amount_cents = req_int(body, "redeem_amount_cents", positive=True)
    # Ownership (4): caller owns the certificate's production company.
    check_producer_owns(caller, company_id_of_certificate(cert))
    # State (5).
    if cert["status"] not in ("ISSUED", "PARTIALLY_TRANSFERRED"):
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"redeem is not declared from certificate status {cert['status']}")
    # Temporal (9): redeem at or before expires_at.
    if CLOCK.now() > parse_dt(cert["expires_at"]):
        raise_error(ERR_CERTIFICATE_EXPIRED, "the certificate has expired")
    # Fiscal (12): amount must not exceed the remaining balance.
    if redeem_amount_cents > int(cert["remaining_amount_cents"]):
        raise_error(ERR_AMOUNT_EXCEEDS_REMAINING,
                    "redeem_amount_cents exceeds the certificate's remaining balance")
    cert["remaining_amount_cents"] = int(cert["remaining_amount_cents"]) - redeem_amount_cents
    cert["redeemed_total_cents"] = int(cert["redeemed_total_cents"]) + redeem_amount_cents
    if int(cert["remaining_amount_cents"]) == 0:
        cert["status"] = "REDEEMED"
    touch(cert)
    return success_object(public(cert))
