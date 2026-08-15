"""Retirement endpoints with purpose-role match and eligibility gating."""

from flask import Blueprint, request

from errors import raise_err, ERR_VALIDATION, ERR_ACCOUNT_NOT_ACTIVE, \
    ERR_CERTIFICATE_NOT_ACTIVE, ERR_OBLIGATION_NOT_OPEN, \
    ERR_VINTAGE_INELIGIBLE, ERR_REGION_INELIGIBLE, ERR_TECHNOLOGY_INELIGIBLE, \
    ERR_DUPLICATE_CLAIM_REFERENCE, ERR_MARKET_CLASS_MISMATCH
from store import STORE, new_id, next_seq, now_ts, clock_now
from util import auth, require_role, forbidden, ok_object, body_json, req_str, \
    opt_str, req_enum, get_or_404
from services import touch
from routes.generators import list_with_serializer

bp = Blueprint("retirements", __name__)

PURPOSE_ROLE = {
    "VOLUNTARY_PROGRAM": "ProgramManager",
    "COMPLIANCE": "ComplianceOfficer",
    "WHOLESALE_CLAIM": "BrokerTrader",
}


def serialize_retirement(r):
    return {k: v for k, v in r.items() if not k.startswith("_")}


@bp.post("/greenpower/retirements")
def create_retirement():
    uid, role = auth()
    require_role(role, "ProgramManager", "ComplianceOfficer", "BrokerTrader")
    body = body_json()
    purpose = body.get("purpose")
    # Purpose-role match is an authorization-stage check when determinable.
    if purpose in PURPOSE_ROLE and role != PURPOSE_ROLE[purpose]:
        forbidden("Retirement purpose %s requires role %s"
                  % (purpose, PURPOSE_ROLE[purpose]))
    certificate_id = req_str(body, "certificate_id")
    purpose = req_enum(body, "purpose", set(PURPOSE_ROLE))
    program_id = None
    obligation_id = None
    external_claim_reference = None
    if purpose == "VOLUNTARY_PROGRAM":
        program_id = req_str(body, "program_id")
    elif purpose == "COMPLIANCE":
        obligation_id = req_str(body, "obligation_id")
    elif purpose == "WHOLESALE_CLAIM":
        external_claim_reference = req_str(body, "external_claim_reference")

    cert = get_or_404(STORE["certificates"], certificate_id, "Certificate")
    program = None
    obligation = None
    if program_id is not None:
        program = get_or_404(STORE["programs"], program_id, "Program")
    if obligation_id is not None:
        obligation = get_or_404(STORE["obligations"], obligation_id,
                                "ComplianceObligation")

    # WHOLESALE_CLAIM ownership: the caller must be the certificate holder.
    if purpose == "WHOLESALE_CLAIM" and uid != cert["account_id"]:
        forbidden("A BrokerTrader may only wholesale-claim certificates they hold")

    holder = STORE["accounts"].get(cert["account_id"])
    if holder is None or holder["status"] != "ACTIVE":
        raise_err(ERR_ACCOUNT_NOT_ACTIVE, "The holder account is not ACTIVE")
    if cert["status"] != "ACTIVE":
        raise_err(ERR_CERTIFICATE_NOT_ACTIVE,
                  "Only an ACTIVE certificate may be retired")
    if purpose == "COMPLIANCE" and obligation["status"] != "OPEN":
        raise_err(ERR_OBLIGATION_NOT_OPEN,
                  "Compliance retirements require an OPEN obligation")

    # Eligibility gates, fixed order: vintage, then region, then technology.
    if purpose == "VOLUNTARY_PROGRAM":
        now = clock_now()
        vy, vm = int(cert["vintage_month"][:4]), int(cert["vintage_month"][5:7])
        months_between = (now.year - vy) * 12 + (now.month - vm)
        if not (0 <= months_between <= program["vintage_window_months"] - 1):
            raise_err(ERR_VINTAGE_INELIGIBLE,
                      "Certificate vintage is outside the program month window")
    elif purpose == "COMPLIANCE":
        vintage_year = int(cert["vintage_month"][:4])
        if not (obligation["year"] - 2 <= vintage_year <= obligation["year"]):
            raise_err(ERR_VINTAGE_INELIGIBLE,
                      "Certificate vintage year is outside the obligation window")

    if purpose == "VOLUNTARY_PROGRAM":
        if cert["region_code"] not in program["eligible_region_codes"]:
            raise_err(ERR_REGION_INELIGIBLE,
                      "Certificate region is not eligible for this program")
    elif purpose == "COMPLIANCE":
        if cert["region_code"] != obligation["region_code"]:
            raise_err(ERR_REGION_INELIGIBLE,
                      "Certificate region does not match the obligation region")

    if purpose == "VOLUNTARY_PROGRAM":
        if cert["technology"] not in program["eligible_technologies"]:
            raise_err(ERR_TECHNOLOGY_INELIGIBLE,
                      "Certificate technology is not eligible for this program")

    if purpose == "WHOLESALE_CLAIM":
        for other in STORE["retirements"].values():
            if other.get("external_claim_reference") == external_claim_reference:
                raise_err(ERR_DUPLICATE_CLAIM_REFERENCE,
                          "external_claim_reference is already in use")

    if purpose == "VOLUNTARY_PROGRAM" and program["market_class"] != "VOLUNTARY":
        raise_err(ERR_MARKET_CLASS_MISMATCH,
                  "Voluntary retirements are only permitted into VOLUNTARY programs")

    now = now_ts()
    retirement = {
        "id": new_id(),
        "created_at": now,
        "certificate_id": certificate_id,
        "account_id": cert["account_id"],
        "purpose": purpose,
        "program_id": program_id,
        "obligation_id": obligation_id,
        "external_claim_reference": external_claim_reference,
        "quantity_mwh": cert["quantity_mwh"],
        "vintage_month": cert["vintage_month"],
        "region_code": cert["region_code"],
        "technology": cert["technology"],
        "claimed_in_report_id": None,
        "_created_dt": clock_now(),
        "_seq": next_seq(),
    }
    STORE["retirements"][retirement["id"]] = retirement
    cert["status"] = "RETIRED"
    touch(cert)
    if purpose == "COMPLIANCE":
        # Coverage mutation plus a possible OPEN -> MET flip are one atomic
        # obligation mutation: exactly one version bump for the request.
        from services import obligation_covered_mwh
        if obligation_covered_mwh(obligation["id"]) >= obligation["required_mwh"]:
            obligation["status"] = "MET"
        touch(obligation)
    return ok_object(serialize_retirement(retirement), 201)


@bp.get("/greenpower/retirements")
def list_retirements():
    auth()
    filters = {
        "certificate_id": request.args.get("certificate_id"),
        "account_id": request.args.get("account_id"),
        "program_id": request.args.get("program_id"),
        "obligation_id": request.args.get("obligation_id"),
        "purpose": request.args.get("purpose"),
    }
    return list_with_serializer(list(STORE["retirements"].values()), filters,
                                serialize_retirement)


@bp.get("/greenpower/retirements/<rid>")
def get_retirement(rid):
    auth()
    rec = get_or_404(STORE["retirements"], rid, "Retirement")
    return ok_object(serialize_retirement(rec))
