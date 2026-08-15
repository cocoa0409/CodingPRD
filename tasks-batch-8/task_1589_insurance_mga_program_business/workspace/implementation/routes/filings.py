"""Rate filings: draft -> submit -> approve/disapprove -> effective, with the
revision loop and effectivity supersession cascade (PRD section 3.3)."""
from flask import Blueprint, request

import serialize
from db import STORE, new_entity, touch, now_dt
from errors import (
    raise_err, err, ERR_INVALID_STATE, ERR_FILING_WINDOW_OVERLAP,
    ERR_FILING_NOT_YET_EFFECTIVE, ERR_INVALID_REQUEST,
)
from middleware import require_roles, require_carrier_owner, ALL_ROLES
from response import success_object
from routes.common import get_or_404, render_list, filter_query
from routes.programs import require_program_not_terminal
from services import cascades
from validation import get_body, req_str, req_enum, req_dict, req_int_nonneg, req_datetime

bp = Blueprint("filings", __name__)

FILING_TYPES = {"RATE", "RULE", "FORM"}


def _validate_base_rates(body):
    base_rates = req_dict(body, "base_rates")
    for k, v in base_rates.items():
        if not isinstance(k, str) or not k:
            raise err(ERR_INVALID_REQUEST, "Field 'base_rates' keys must be non-empty strings.")
        if isinstance(v, bool) or not isinstance(v, int) or v < 0:
            raise err(ERR_INVALID_REQUEST, "Field 'base_rates' values must be non-negative integer cents.")
    return base_rates


@bp.post("/mga/programs/<programId>/rate-filings")
def create_filing(programId):
    require_roles("MGAUnderwriter")
    program = get_or_404(STORE.programs, programId, "Program")
    body = get_body()
    state_code = req_str(body, "state_code")
    filing_type = req_enum(body, "filing_type", FILING_TYPES)
    base_rates = _validate_base_rates(body)
    policy_fee_cents = req_int_nonneg(body, "policy_fee_cents")
    effective_from = req_datetime(body, "effective_from")
    effective_to = req_datetime(body, "effective_to")
    if effective_from >= effective_to:
        raise_err(ERR_INVALID_REQUEST, "effective_from must be strictly before effective_to.")
    require_program_not_terminal(program)
    # version_seq: per program+state sequence, assigned in creation order, 1-based.
    seq = 1 + sum(
        1 for f in STORE.rate_filings.values()
        if f["program_id"] == program["id"] and f["state_code"] == state_code
    )
    f = new_entity()
    f.update({
        "program_id": program["id"],
        "state_code": state_code,
        "filing_type": filing_type,
        "base_rates": dict(base_rates),
        "policy_fee_cents": policy_fee_cents,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "status": "DRAFT",
        "version_seq": seq,
        "submitted_at": None,
        "approved_at": None,
    })
    STORE.rate_filings[f["id"]] = f
    return success_object(serialize.filing(f), status=201)


@bp.get("/mga/programs/<programId>/rate-filings")
def list_program_filings(programId):
    require_roles(*ALL_ROLES)
    get_or_404(STORE.programs, programId, "Program")
    items = filter_query(
        [f for f in STORE.rate_filings.values() if f["program_id"] == programId],
        state_code=request.args.get("state_code"),
        status=request.args.get("status"),
    )
    return render_list(items, serialize.filing)


@bp.get("/mga/rate-filings/<filingId>")
def get_filing(filingId):
    require_roles(*ALL_ROLES)
    f = get_or_404(STORE.rate_filings, filingId, "RateFiling")
    return success_object(serialize.filing(f))


@bp.get("/mga/rate-filings")
def list_filings():
    require_roles(*ALL_ROLES)
    items = filter_query(
        list(STORE.rate_filings.values()),
        program_id=request.args.get("program_id"),
        state_code=request.args.get("state_code"),
        status=request.args.get("status"),
    )
    return render_list(items, serialize.filing)


@bp.post("/mga/rate-filings/<filingId>/submit")
def submit_filing(filingId):
    require_roles("MGAUnderwriter")
    f = get_or_404(STORE.rate_filings, filingId, "RateFiling")
    if f["status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE, "Only a DRAFT filing can be submitted.")
    if not f["base_rates"]:
        raise_err(ERR_INVALID_REQUEST, "base_rates must be non-empty at submission.")
    if f["effective_from"] >= f["effective_to"]:
        raise_err(ERR_INVALID_REQUEST, "effective_from must be strictly before effective_to.")
    f["status"] = "SUBMITTED"
    f["submitted_at"] = now_dt()
    touch(f)
    return success_object(serialize.filing(f))


@bp.post("/mga/rate-filings/<filingId>/approve")
def approve_filing(filingId):
    require_roles("CarrierUnderwriter")
    f = get_or_404(STORE.rate_filings, filingId, "RateFiling")
    program = STORE.programs[f["program_id"]]
    require_carrier_owner(program)
    if f["status"] != "SUBMITTED":
        raise_err(ERR_INVALID_STATE, "Only a SUBMITTED filing can be approved.")
    # Half-open window exclusivity within program+state: adjacency is NOT an
    # intersection (this.from == other.to or this.to == other.from is allowed).
    for o in STORE.rate_filings.values():
        if (
            o["id"] != f["id"]
            and o["program_id"] == f["program_id"]
            and o["state_code"] == f["state_code"]
            and o["status"] in ("APPROVED", "EFFECTIVE")
            and f["effective_from"] < o["effective_to"]
            and o["effective_from"] < f["effective_to"]
        ):
            raise_err(
                ERR_FILING_WINDOW_OVERLAP,
                "Window overlaps another APPROVED/EFFECTIVE filing of the same program and state.",
            )
    f["status"] = "APPROVED"
    f["approved_at"] = now_dt()
    touch(f)
    return success_object(serialize.filing(f))


@bp.post("/mga/rate-filings/<filingId>/disapprove")
def disapprove_filing(filingId):
    require_roles("CarrierUnderwriter")
    f = get_or_404(STORE.rate_filings, filingId, "RateFiling")
    program = STORE.programs[f["program_id"]]
    require_carrier_owner(program)
    if f["status"] != "SUBMITTED":
        raise_err(ERR_INVALID_STATE, "Only a SUBMITTED filing can be disapproved.")
    f["status"] = "DISAPPROVED"
    touch(f)
    return success_object(serialize.filing(f))


@bp.post("/mga/rate-filings/<filingId>/revise")
def revise_filing(filingId):
    require_roles("MGAUnderwriter")
    f = get_or_404(STORE.rate_filings, filingId, "RateFiling")
    if f["status"] != "DISAPPROVED":
        raise_err(ERR_INVALID_STATE, "Only a DISAPPROVED filing can be revised back to DRAFT.")
    f["status"] = "DRAFT"
    f["submitted_at"] = None
    f["approved_at"] = None
    touch(f)
    return success_object(serialize.filing(f))


@bp.post("/mga/rate-filings/<filingId>/mark-effective")
def mark_effective_filing(filingId):
    require_roles("CarrierUnderwriter")
    f = get_or_404(STORE.rate_filings, filingId, "RateFiling")
    program = STORE.programs[f["program_id"]]
    require_carrier_owner(program)
    if f["status"] != "APPROVED":
        raise_err(ERR_INVALID_STATE, "Only an APPROVED filing can be marked effective.")
    if now_dt() < f["effective_from"]:
        raise_err(ERR_FILING_NOT_YET_EFFECTIVE, "The filing's effective_from has not been reached.")
    cascades.supersede_prior_effective_filings(f)
    f["status"] = "EFFECTIVE"
    touch(f)
    return success_object(serialize.filing(f))
