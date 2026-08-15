"""JurisdictionProgram endpoints: create, list, get, amend (OCC), transition."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE_TRANSITION,
    ERR_PROGRAM_WINDOW_OVERLAP,
    ERR_STALE_PROGRAM_VERSION,
)
from helpers import get_one, list_query, public
from middleware import authorized
from response import success_object
from services.core import new_record, touch
from util import parse_dt
from validate import (
    get_body,
    reject_unknown_fields,
    req_int,
    req_number,
    opt_int,
    opt_number,
    opt_datetime,
    req_datetime,
    req_str,
    opt_str,
    require_path_resource,
    version_field,
)

bp = Blueprint("jurisdiction_programs", __name__)

PROGRAM_STATUSES = {"DRAFT", "OPEN", "SUSPENDED", "CLOSED"}

CREATE_FIELDS = {
    "jurisdiction_code", "program_name", "fiscal_year",
    "window_opens_at", "window_closes_at",
    "annual_cap_cents", "minimum_qualified_spend_cents",
    "base_rate_standard", "base_rate_elevated", "elevated_tier_threshold_cents",
    "atl_cap_pct", "resident_uplift_pct", "transfer_price_floor_pct",
    "vendor_verification_validity_days", "appeal_window_days",
    "daily_interest_rate", "credit_validity_days", "transfer_proposal_validity_days",
}

AMENDABLE_FIELDS = {
    "window_opens_at", "window_closes_at",
    "annual_cap_cents", "minimum_qualified_spend_cents",
    "base_rate_standard", "base_rate_elevated", "elevated_tier_threshold_cents",
    "atl_cap_pct", "resident_uplift_pct", "transfer_price_floor_pct",
    "vendor_verification_validity_days", "appeal_window_days",
    "daily_interest_rate", "credit_validity_days", "transfer_proposal_validity_days",
}

AMEND_ALLOWED = AMENDABLE_FIELDS | {"expected_program_version"}

NUMERIC_FIELDS = {
    "base_rate_standard", "base_rate_elevated", "atl_cap_pct",
    "resident_uplift_pct", "transfer_price_floor_pct", "daily_interest_rate",
}
INT_FIELDS = {
    "annual_cap_cents", "minimum_qualified_spend_cents",
    "elevated_tier_threshold_cents", "vendor_verification_validity_days",
    "appeal_window_days", "credit_validity_days", "transfer_proposal_validity_days",
}
WINDOW_FIELDS = {"window_opens_at", "window_closes_at"}


def _window_overlaps(jurisdiction_code, opens_at, closes_at, exclude_id=None):
    """Half-open [opens, closes) overlap against every non-CLOSED program of
    the same jurisdiction_code; touching boundaries do not overlap."""
    o = parse_dt(opens_at)
    c = parse_dt(closes_at)
    for other in db["jurisdiction_programs"].values():
        if other["jurisdiction_code"] != jurisdiction_code:
            continue
        if other["status"] == "CLOSED":
            continue
        if exclude_id is not None and other["id"] == exclude_id:
            continue
        oo = parse_dt(other["window_opens_at"])
        oc = parse_dt(other["window_closes_at"])
        if o < oc and oo < c:
            return True
    return False


@bp.post("/jurisdiction-programs")
def create_program():
    authorized(["FilmOfficeAdmin"])
    body = get_body()
    reject_unknown_fields(body, CREATE_FIELDS)
    jurisdiction_code = req_str(body, "jurisdiction_code")
    program_name = req_str(body, "program_name")
    fiscal_year = req_str(body, "fiscal_year")
    window_opens_at = req_datetime(body, "window_opens_at")
    window_closes_at = req_datetime(body, "window_closes_at")
    annual_cap_cents = req_int(body, "annual_cap_cents", positive=True)
    minimum_qualified_spend_cents = req_int(body, "minimum_qualified_spend_cents", non_negative=True)
    base_rate_standard = req_number(body, "base_rate_standard")
    base_rate_elevated = req_number(body, "base_rate_elevated")
    elevated_tier_threshold_cents = req_int(body, "elevated_tier_threshold_cents", non_negative=True)
    atl_cap_pct = req_number(body, "atl_cap_pct")
    resident_uplift_pct = req_number(body, "resident_uplift_pct")
    transfer_price_floor_pct = req_number(body, "transfer_price_floor_pct")
    vendor_verification_validity_days = req_int(body, "vendor_verification_validity_days", non_negative=True)
    appeal_window_days = req_int(body, "appeal_window_days", non_negative=True)
    daily_interest_rate = req_number(body, "daily_interest_rate")
    credit_validity_days = req_int(body, "credit_validity_days", non_negative=True)
    transfer_proposal_validity_days = req_int(body, "transfer_proposal_validity_days", non_negative=True)
    if not parse_dt(window_opens_at) < parse_dt(window_closes_at):
        raise_error(ERR_INVALID_REQUEST, "window_opens_at must be strictly before window_closes_at")
    # Structural (priority 10): half-open window overlap per jurisdiction.
    if _window_overlaps(jurisdiction_code, window_opens_at, window_closes_at):
        raise_error(ERR_PROGRAM_WINDOW_OVERLAP,
                    "window overlaps another non-CLOSED program for this jurisdiction_code")
    rec = new_record("jurisdiction_programs", {
        "jurisdiction_code": jurisdiction_code,
        "program_name": program_name,
        "fiscal_year": fiscal_year,
        "window_opens_at": window_opens_at,
        "window_closes_at": window_closes_at,
        "annual_cap_cents": annual_cap_cents,
        "minimum_qualified_spend_cents": minimum_qualified_spend_cents,
        "base_rate_standard": base_rate_standard,
        "base_rate_elevated": base_rate_elevated,
        "elevated_tier_threshold_cents": elevated_tier_threshold_cents,
        "atl_cap_pct": atl_cap_pct,
        "resident_uplift_pct": resident_uplift_pct,
        "transfer_price_floor_pct": transfer_price_floor_pct,
        "vendor_verification_validity_days": vendor_verification_validity_days,
        "appeal_window_days": appeal_window_days,
        "daily_interest_rate": daily_interest_rate,
        "credit_validity_days": credit_validity_days,
        "transfer_proposal_validity_days": transfer_proposal_validity_days,
        "status": "DRAFT",
        "allocated_credit_cents": 0,
        "remaining_cap_cents": annual_cap_cents,
    })
    return success_object(public(rec), status=201)


@bp.get("/jurisdiction-programs")
def list_programs():
    return list_query("jurisdiction_programs", {
        "status": request.args.get("status"),
        "jurisdiction_code": request.args.get("jurisdiction_code"),
        "fiscal_year": request.args.get("fiscal_year"),
    })


@bp.get("/jurisdiction-programs/<programId>")
def get_program(programId):
    return get_one("jurisdiction_programs", programId)


@bp.post("/jurisdiction-programs/<programId>/amend")
def amend_program(programId):
    authorized(["FilmOfficeAdmin"])
    # Path identifiers resolve before any further validation runs (PRD 2.10).
    program = require_path_resource("jurisdiction_programs", programId)
    body = get_body()
    reject_unknown_fields(body, AMEND_ALLOWED)
    expected = version_field(body, "expected_program_version")
    # Field-level shape for provided values.
    updates = {}
    for f in WINDOW_FIELDS:
        if f in body and body[f] is not None:
            updates[f] = req_datetime(body, f)
    for f in INT_FIELDS:
        if f in body and body[f] is not None:
            if f == "annual_cap_cents":
                updates[f] = req_int(body, f, positive=True)
            else:
                updates[f] = req_int(body, f, non_negative=True)
    for f in NUMERIC_FIELDS:
        if f in body and body[f] is not None:
            updates[f] = req_number(body, f)
    for f in body:
        if f in AMENDABLE_FIELDS and body[f] is None:
            raise_error(ERR_INVALID_REQUEST, f"field {f} must not be null")

    # State (priority 5): amend declared only from DRAFT or OPEN.
    if program["status"] not in ("DRAFT", "OPEN"):
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"cannot amend a program in status {program['status']}")
    # OCC (priority 7).
    if expected != int(program["version"]):
        raise_error(ERR_STALE_PROGRAM_VERSION,
                    "expected_program_version does not match the program's current version")

    new_opens = updates.get("window_opens_at", program["window_opens_at"])
    new_closes = updates.get("window_closes_at", program["window_closes_at"])
    if not parse_dt(new_opens) < parse_dt(new_closes):
        raise_error(ERR_INVALID_REQUEST, "window_opens_at must be strictly before window_closes_at")
    # Window changes re-run the half-open overlap check (priority 10).
    if ("window_opens_at" in updates or "window_closes_at" in updates):
        if _window_overlaps(program["jurisdiction_code"], new_opens, new_closes, exclude_id=program["id"]):
            raise_error(ERR_PROGRAM_WINDOW_OVERLAP,
                        "amended window overlaps another non-CLOSED program for this jurisdiction_code")

    for k, v in updates.items():
        program[k] = v
    # A change to annual_cap_cents resizes the remaining cap (PRD 2.7).
    if "annual_cap_cents" in updates:
        program["remaining_cap_cents"] = int(program["annual_cap_cents"]) - int(program["allocated_credit_cents"])
    touch(program)
    return success_object(public(program))


@bp.post("/jurisdiction-programs/<programId>/transition")
def transition_program(programId):
    authorized(["FilmOfficeAdmin"])
    program = require_path_resource("jurisdiction_programs", programId)
    body = get_body()
    reject_unknown_fields(body, {"to_state"})
    to_state = req_str(body, "to_state")
    if to_state not in PROGRAM_STATUSES:
        raise_error(ERR_INVALID_REQUEST, f"invalid to_state: {to_state}")

    current = program["status"]
    declared = {
        ("DRAFT", "OPEN"),
        ("OPEN", "SUSPENDED"),
        ("SUSPENDED", "OPEN"),
        ("OPEN", "CLOSED"),
        ("SUSPENDED", "CLOSED"),
    }
    if (current, to_state) not in declared:
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"transition {current} -> {to_state} is not declared")
    if to_state == "OPEN":
        # DRAFT -> OPEN re-validates the window geometry; every entry into
        # OPEN (including from SUSPENDED) re-runs the overlap check.
        if not parse_dt(program["window_opens_at"]) < parse_dt(program["window_closes_at"]):
            raise_error(ERR_INVALID_REQUEST, "window_opens_at must be strictly before window_closes_at")
        if _window_overlaps(program["jurisdiction_code"], program["window_opens_at"],
                            program["window_closes_at"], exclude_id=program["id"]):
            raise_error(ERR_PROGRAM_WINDOW_OVERLAP,
                        "window overlaps another non-CLOSED program for this jurisdiction_code")
    program["status"] = to_state
    touch(program)
    return success_object(public(program))
