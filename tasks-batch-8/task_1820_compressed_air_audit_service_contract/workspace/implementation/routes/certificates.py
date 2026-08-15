"""Guarantee certificates: creation snapshots, settle/pay, dispute track."""

from flask import Blueprint, request

from auth import require_roles, check_ownership
from domain import DEADBAND_PCT, guarantee_settlement_figures
from envelope import ok_object, ok_list
from errors import (
    conflict,
    invalid_request,
    invalid_state,
    not_found,
    ERR_CERTIFICATE_EXISTS,
    ERR_CONTRACT_TIER_INELIGIBLE,
    ERR_DISPUTE_OPEN_PAYOUT_FROZEN,
    ERR_FACILITY_MISMATCH,
    ERR_MEASUREMENT_INCOMPLETE,
    ERR_NO_ACTIVE_CONTRACT,
    ERR_POSTURE_NOT_NORMAL,
)
import store
from store import new_resource, touch
from util import body_or_empty, dec, parse_pagination, public, req_num, req_str, round_half_up, sort_and_page

bp = Blueprint("certificates", __name__)

ALL_ROLES = ["DealerAdmin", "EnergyEngineer", "ServiceTech", "ContractManager", "FacilityManager"]


def _get_or_404(cert_id):
    cert = store.guarantee_certificates.get(cert_id)
    if cert is None:
        raise not_found("GuaranteeCertificate not found")
    return cert


@bp.route("/guarantee-certificates", methods=["POST"])
def create_certificate():
    require_roles(["ContractManager"])
    body = body_or_empty()
    facility_id = req_str(body, "facility_id")
    contract_id = req_str(body, "contract_id")
    savings_case_id = req_str(body, "savings_case_id")
    guaranteed_pct = req_num(body, "guaranteed_pct")

    fac = store.facilities.get(facility_id)
    if fac is None:
        raise not_found("Facility not found")

    # gates in order: contract presence/ACTIVE -> case state -> mismatch -> uniqueness -> tier
    contract = store.service_contracts.get(contract_id)
    if contract is None or contract["status"] != "ACTIVE":
        raise conflict(ERR_NO_ACTIVE_CONTRACT, "Referenced ServiceContract must be ACTIVE")

    case = store.savings_cases.get(savings_case_id)
    if case is None or case["savings_status"] not in ("MODELED", "MEASURED"):
        raise invalid_state("SavingsCase savings_status must be MODELED or MEASURED")

    if contract["facility_id"] != facility_id or case["facility_id"] != facility_id:
        raise conflict(ERR_FACILITY_MISMATCH, "Contract and savings case must belong to the facility")

    if any(c["savings_case_id"] == savings_case_id for c in store.guarantee_certificates.values()):
        raise conflict(ERR_CERTIFICATE_EXISTS, "A GuaranteeCertificate already exists for this savings case")

    if contract["tier"] != "PREMIUM":
        raise conflict(ERR_CONTRACT_TIER_INELIGIBLE, "Guarantee certificates require a PREMIUM contract")

    # snapshot the guarantee basis from deemed savings; never recomputed
    guaranteed_kwh = round_half_up(dec(case["deemed_annual_savings_kwh"]) * dec(guaranteed_pct))
    deadband_kwh = round_half_up(dec(guaranteed_kwh) * DEADBAND_PCT)

    cert = new_resource()
    cert.update(
        {
            "facility_id": facility_id,
            "contract_id": contract_id,
            "savings_case_id": savings_case_id,
            "guaranteed_pct": float(guaranteed_pct) if isinstance(guaranteed_pct, int) else guaranteed_pct,
            "guaranteed_kwh": guaranteed_kwh,
            "deadband_kwh": deadband_kwh,
            "measured_kwh_at_settlement": None,
            "shortfall_kwh": None,
            "payout_cents": None,
            "settlement_blocked": fac["posture"] != "NORMAL",
            "settlement_status": "AWAITING_MEASUREMENT",
            "dispute_status": "NONE",
            "dispute_reason": None,
        }
    )
    store.guarantee_certificates[cert["id"]] = cert
    return ok_object(public(cert), 201)


@bp.route("/guarantee-certificates", methods=["GET"])
def list_certificates():
    require_roles(ALL_ROLES)
    items = list(store.guarantee_certificates.values())
    for param in ("facility_id", "contract_id", "savings_case_id", "settlement_status"):
        value = request.args.get(param)
        if value is not None:
            items = [c for c in items if c[param] == value]
    limit, offset = parse_pagination()
    page, total = sort_and_page(items, limit, offset)
    return ok_list([public(c) for c in page], limit, offset, total)


@bp.route("/guarantee-certificates/<guaranteeCertificateId>", methods=["GET"])
def get_certificate(guaranteeCertificateId):
    user_id, role = require_roles(ALL_ROLES)
    cert = _get_or_404(guaranteeCertificateId)
    check_ownership(user_id, role, cert["facility_id"])
    return ok_object(public(cert), 200)


@bp.route("/guarantee-certificates/<guaranteeCertificateId>/settle", methods=["POST"])
def settle(guaranteeCertificateId):
    require_roles(["ContractManager"])
    cert = _get_or_404(guaranteeCertificateId)
    if cert["settlement_status"] != "AWAITING_MEASUREMENT":
        raise invalid_state("GuaranteeCertificate must be AWAITING_MEASUREMENT to settle")

    # gates in order: case MEASURED -> posture NORMAL -> no open dispute
    case = store.savings_cases.get(cert["savings_case_id"])
    if case is None or case["savings_status"] != "MEASURED":
        raise conflict(ERR_MEASUREMENT_INCOMPLETE, "Linked SavingsCase must be MEASURED")
    fac = store.facilities.get(cert["facility_id"])
    if fac is None or fac["posture"] != "NORMAL":
        raise conflict(ERR_POSTURE_NOT_NORMAL, "Facility posture must be NORMAL to settle")
    if cert["dispute_status"] == "OPEN":
        raise conflict(ERR_DISPUTE_OPEN_PAYOUT_FROZEN, "An open dispute freezes settlement")

    measured = case["measured_annual_savings_kwh"]
    shortfall, payout = guarantee_settlement_figures(cert, measured)
    cert["measured_kwh_at_settlement"] = measured
    cert["shortfall_kwh"] = shortfall
    cert["payout_cents"] = payout
    cert["settlement_status"] = "SETTLED_NO_SHORTFALL" if shortfall == 0 else "SETTLED_PAYOUT_DUE"
    touch(cert)
    return ok_object(public(cert), 200)


@bp.route("/guarantee-certificates/<guaranteeCertificateId>/pay", methods=["POST"])
def pay(guaranteeCertificateId):
    require_roles(["ContractManager"])
    cert = _get_or_404(guaranteeCertificateId)
    if cert["settlement_status"] != "SETTLED_PAYOUT_DUE":
        raise invalid_state("GuaranteeCertificate must be SETTLED_PAYOUT_DUE to pay")
    if cert["dispute_status"] == "OPEN":
        raise conflict(ERR_DISPUTE_OPEN_PAYOUT_FROZEN, "An open dispute freezes payout")
    cert["settlement_status"] = "PAID"
    touch(cert)
    return ok_object(public(cert), 200)


@bp.route("/guarantee-certificates/<guaranteeCertificateId>/dispute", methods=["POST"])
def dispute(guaranteeCertificateId):
    user_id, role = require_roles(["FacilityManager"])
    cert = _get_or_404(guaranteeCertificateId)
    body = body_or_empty()
    reason = req_str(body, "reason")
    check_ownership(user_id, role, cert["facility_id"])
    if cert["settlement_status"] not in ("SETTLED_NO_SHORTFALL", "SETTLED_PAYOUT_DUE"):
        raise invalid_state("Only a settled-but-unpaid certificate can be disputed")
    if cert["dispute_status"] != "NONE":
        raise invalid_state("dispute_status must be NONE to open a dispute")
    cert["dispute_status"] = "OPEN"
    cert["dispute_reason"] = reason
    touch(cert)
    return ok_object(public(cert), 200)


@bp.route("/guarantee-certificates/<guaranteeCertificateId>/resolve-dispute", methods=["POST"])
def resolve_dispute(guaranteeCertificateId):
    require_roles(["ContractManager"])
    cert = _get_or_404(guaranteeCertificateId)
    body = body_or_empty()
    outcome = req_str(body, "outcome")
    if outcome not in ("UPHELD", "OVERRULED"):
        raise invalid_request("outcome must be UPHELD or OVERRULED")
    # corrected_measured_kwh present iff outcome=UPHELD
    corrected = body.get("corrected_measured_kwh")
    if outcome == "UPHELD":
        if corrected is None or not isinstance(corrected, int) or isinstance(corrected, bool):
            raise invalid_request("corrected_measured_kwh is required when outcome is UPHELD")
    elif corrected is not None:
        raise invalid_request("corrected_measured_kwh is only allowed when outcome is UPHELD")

    if cert["dispute_status"] != "OPEN":
        raise invalid_state("dispute_status must be OPEN to resolve")

    if outcome == "UPHELD":
        cert["measured_kwh_at_settlement"] = corrected
        shortfall, payout = guarantee_settlement_figures(cert, corrected)
        cert["shortfall_kwh"] = shortfall
        cert["payout_cents"] = payout
        cert["settlement_status"] = "SETTLED_NO_SHORTFALL" if shortfall == 0 else "SETTLED_PAYOUT_DUE"
        cert["dispute_status"] = "RESOLVED_UPHELD"
    else:
        cert["dispute_status"] = "RESOLVED_OVERRULED"
    touch(cert)
    return ok_object(public(cert), 200)
