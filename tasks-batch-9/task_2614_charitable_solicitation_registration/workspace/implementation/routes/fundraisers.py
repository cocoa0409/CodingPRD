"""The professional fundraiser registry and contract filing (PRD 3.6)."""
from flask import Blueprint, g, request

import clock
import response
import validate
from auth import endpoint, require_fundraiser_owner
from dates import add_days, fmt, parse_iso
from db import db, public, sorted_rows, stamp_new, touch_once
from errors import ApiError
from services import calc
from services.derive import recompute_disclosures_for, recompute_registry_status

bp = Blueprint("fundraisers", __name__)

FUNDRAISER_TYPES = ("PROFESSIONAL_SOLICITOR", "FUNDRAISING_COUNSEL", "COMMERCIAL_COVENTURER")
COMPENSATION_TYPES = ("FLAT_FEE", "PERCENT_OF_GROSS", "HOURLY")


def has_active_registration(fundraiser_id, state_code):
    for row in db.fundraiser_registrations.values():
        if (row["fundraiser_id"] == fundraiser_id
                and row["state_code"] == state_code
                and row["status"] == "ACTIVE"):
            return True
    return False


@bp.post("/professional-fundraisers")
@endpoint(["SystemAdmin"])
def create_fundraiser():
    body = validate.json_body()
    legal_name = validate.req_string(body, "legal_name", max_len=200)
    fundraiser_type = validate.req_enum(body, "fundraiser_type", FUNDRAISER_TYPES)
    bond_expires_at = validate.req_datetime(body, "bond_expires_at")
    bond_amount_cents = validate.opt_int(body, "bond_amount_cents", 0, minimum=0)

    fundraiser = {
        "legal_name": legal_name,
        "fundraiser_type": fundraiser_type,
        "bond_amount_cents": bond_amount_cents,
        "bond_expires_at": fmt(bond_expires_at),
        # A new firm holds no state registrations at all.
        "registry_status": "UNREGISTERED",
    }
    stamp_new(fundraiser)
    db.professional_fundraisers[fundraiser["id"]] = fundraiser
    return response.created(public(fundraiser))


@bp.get("/professional-fundraisers/<fundraiser_id>")
@endpoint(["SystemAdmin", "ComplianceOfficer", "StateRegulator", "FundraiserAgent"])
def read_fundraiser(fundraiser_id):
    return response.ok(public(validate.find_fundraiser(fundraiser_id)))


@bp.get("/professional-fundraisers/<fundraiser_id>/registrations")
@endpoint(["SystemAdmin", "ComplianceOfficer", "StateRegulator", "FundraiserAgent"])
def list_fundraiser_registrations(fundraiser_id):
    validate.find_fundraiser(fundraiser_id)
    rows = [r for r in db.fundraiser_registrations.values()
            if r["fundraiser_id"] == fundraiser_id]
    for field in ("state_code", "status"):
        wanted = request.args.get(field)
        if wanted is not None:
            rows = [r for r in rows if r[field] == wanted]
    page, limit, offset, total = response.paginate(sorted_rows(rows))
    return response.listing([public(r) for r in page], limit, offset, total)


@bp.post("/fundraiser-registrations")
@endpoint(["FundraiserAgent"])
def create_fundraiser_registration():
    """A firm may hold only one live registration per state."""
    body = validate.json_body()
    fundraiser_id = validate.req_string(body, "fundraiser_id")
    state_code = validate.req_state_code(body, "state_code")
    bond_on_file_cents = validate.req_int(body, "bond_on_file_cents", minimum=0)
    expires_at = validate.req_datetime(body, "expires_at")

    # Ladder rung 5 -- state_code resolves before fundraiser_id (PRD 2.9).
    profile = validate.find_state_profile(state_code)
    fundraiser = validate.find_fundraiser(fundraiser_id)

    # Ladder rung 6 -- an agent may register only its own firm.
    require_fundraiser_owner(fundraiser_id)

    # Ladder rung 32 -- the bond is adequate AND outlasts the registration.
    bond_expires_at = parse_iso(fundraiser["bond_expires_at"])
    if (bond_on_file_cents < profile["fundraiser_bond_minimum_cents"]
            or not (bond_expires_at > expires_at)):
        raise ApiError("ERR_BOND_INSUFFICIENT")

    # Ladder rung 33.
    if has_active_registration(fundraiser_id, state_code):
        raise ApiError("ERR_DUPLICATE_FUNDRAISER_REGISTRATION")

    registration = {
        "fundraiser_id": fundraiser_id,
        "state_code": state_code,
        "bond_on_file_cents": bond_on_file_cents,
        "expires_at": fmt(expires_at),
        "status": "ACTIVE",
    }
    stamp_new(registration)
    db.fundraiser_registrations[registration["id"]] = registration
    recompute_registry_status(fundraiser)
    return response.created(public(registration))


@bp.post("/fundraising-contracts")
@endpoint(["ComplianceOfficer"])
def create_contract():
    """filing_due_date is contract_start plus the SMALLEST window among the states."""
    body = validate.json_body()
    organization_id = validate.req_string(body, "organization_id")
    fundraiser_id = validate.req_string(body, "fundraiser_id")
    state_codes = validate.req_array(body, "state_codes", non_empty=True)
    contract_start = validate.req_datetime(body, "contract_start")
    contract_end = validate.req_datetime(body, "contract_end")
    compensation_type = validate.req_enum(body, "compensation_type", COMPENSATION_TYPES)
    percent_of_gross = validate.opt_number(body, "percent_of_gross", 0, minimum=0, maximum=1)
    flat_fee_cents = validate.opt_int(body, "flat_fee_cents", 0, minimum=0)
    if not (contract_end > contract_start):
        raise ApiError("ERR_INVALID_REQUEST",
                       "contract_end must be strictly after contract_start.")
    if compensation_type == "PERCENT_OF_GROSS" and not percent_of_gross > 0:
        raise ApiError("ERR_INVALID_REQUEST",
                       "percent_of_gross must be greater than 0 for a PERCENT_OF_GROSS contract.")
    if compensation_type == "FLAT_FEE" and not flat_fee_cents > 0:
        raise ApiError("ERR_INVALID_REQUEST",
                       "flat_fee_cents must be greater than 0 for a FLAT_FEE contract.")

    validate.find_organization(organization_id)
    profiles = validate.resolve_state_codes(state_codes)
    validate.find_fundraiser(fundraiser_id)

    contract = {
        "organization_id": organization_id,
        "fundraiser_id": fundraiser_id,
        "state_codes": state_codes,
        "contract_start": fmt(contract_start),
        "contract_end": fmt(contract_end),
        "compensation_type": compensation_type,
        "percent_of_gross": percent_of_gross,
        "flat_fee_cents": flat_fee_cents,
        "status": "DRAFT",
        "filing_due_date": fmt(calc.contract_filing_due(contract_start, profiles)),
        "filed_at": None,
        "late_filing_surcharge_cents": 0,
    }
    stamp_new(contract)
    db.fundraising_contracts[contract["id"]] = contract
    return response.created(public(contract))


@bp.post("/fundraising-contracts/<contract_id>/file")
@endpoint(["FundraiserAgent"])
def file_contract(contract_id):
    """Timeliness selects between FILED and LATE_FILED; the hard stop closes both."""
    contract = validate.find_contract(contract_id)

    # Ladder rung 6 -- an agent may file only its own firm's contracts.
    require_fundraiser_owner(contract["fundraiser_id"])
    # Ladder rung 11.
    if contract["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_CONTRACT_STATE")
    # Ladder rung 19 -- every state needs an ACTIVE registration for this firm.
    for state_code in contract["state_codes"]:
        if not has_active_registration(contract["fundraiser_id"], state_code):
            raise ApiError("ERR_FUNDRAISER_NOT_REGISTERED_IN_STATE")
    # Ladder rung 24 -- the sixty-day hard stop beyond filing_due_date.
    now = clock.now()
    due = parse_iso(contract["filing_due_date"])
    hard_stop = add_days(due, calc.CONTRACT_FILING_HARD_STOP_DAYS)
    if now > hard_stop:
        raise ApiError("ERR_CONTRACT_FILING_WINDOW_CLOSED")

    if now <= due:
        contract["status"] = "FILED"
        contract["late_filing_surcharge_cents"] = 0
    else:
        contract["status"] = "LATE_FILED"
        contract["late_filing_surcharge_cents"] = calc.LATE_CONTRACT_SURCHARGE_CENTS
    contract["filed_at"] = clock.now_iso()
    touch_once(contract, "fundraising_contract")

    # A newly filed solicitor engagement can add a required clause to material
    # that was compliant a moment earlier.
    recompute_disclosures_for(contract["organization_id"], contract["state_codes"])
    return response.ok(public(contract))


@bp.get("/fundraising-contracts")
@endpoint(["ComplianceOfficer", "StateRegulator", "SystemAdmin", "FundraiserAgent"])
def list_contracts():
    rows = list(db.fundraising_contracts.values())
    for field in ("organization_id", "fundraiser_id", "status"):
        wanted = request.args.get(field)
        if wanted is not None:
            rows = [r for r in rows if r[field] == wanted]
    state_code = request.args.get("state_code")
    if state_code is not None:
        rows = [r for r in rows if state_code in r["state_codes"]]
    page, limit, offset, total = response.paginate(sorted_rows(rows))
    return response.listing([public(r) for r in page], limit, offset, total)


@bp.get("/fundraising-contracts/<contract_id>")
@endpoint(["ComplianceOfficer", "StateRegulator", "SystemAdmin", "FundraiserAgent"])
def read_contract(contract_id):
    return response.ok(public(validate.find_contract(contract_id)))
