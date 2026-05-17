"""Beneficiary claim routes."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from flask import Blueprint

from ..auth import ROLE_AUDITOR, ROLE_COMPLIANCE, ROLE_CUSTODIAN, ROLE_PARTICIPANT, require_roles
from ..clock import current_date
from ..errors import (
    err_invalid_state,
    err_not_found,
    err_secure_deadline_expired,
    err_validation,
)
from ..helpers import query_date, require_json_object
from ..responses import ok
from ..services.calculations import compute_rmd_amount_cents
from ..services.lookups import (
    bump_version,
    get_account_or_404,
    get_claim_or_404,
    get_participant_or_404,
    parse_iso_date_str,
)
from ..services.serialize import serialize_claim
from ..store import store

bp = Blueprint("claims", __name__)


@bp.get("/beneficiary-claims/<claim_id>")
@require_roles(ROLE_PARTICIPANT, ROLE_CUSTODIAN, ROLE_COMPLIANCE, ROLE_AUDITOR)
def read_claim(claim_id: str, **kw):
    role = kw.get("_caller_role")
    caller = kw.get("_caller_id")
    claim = get_claim_or_404(claim_id)
    if role == ROLE_PARTICIPANT and claim["beneficiary_participant_id"] != caller:
        raise err_not_found(f"BeneficiaryClaim {claim_id} not found")
    return ok(serialize_claim(claim))


@bp.post("/beneficiary-claims/<claim_id>/suspend")
@require_roles(ROLE_COMPLIANCE)
def suspend_claim(claim_id: str, **_kw):
    require_json_object()
    with store().lock:
        claim = get_claim_or_404(claim_id)
        if claim["status"] != "CLAIMED":
            raise err_invalid_state(f"Claim is {claim['status']}; must be CLAIMED")
        claim["status"] = "SUSPENDED"
        bump_version(claim)
        return ok(serialize_claim(claim))


@bp.post("/beneficiary-claims/<claim_id>/resume")
@require_roles(ROLE_COMPLIANCE)
def resume_claim(claim_id: str, **_kw):
    require_json_object()
    with store().lock:
        claim = get_claim_or_404(claim_id)
        if claim["status"] != "SUSPENDED":
            raise err_invalid_state(f"Claim is {claim['status']}; must be SUSPENDED")
        deadline = parse_iso_date_str(claim["deadline_date"])
        if deadline is None or current_date() > deadline:
            raise err_secure_deadline_expired(
                "Cannot resume a claim whose deadline has expired"
            )
        claim["status"] = "CLAIMED"
        bump_version(claim)
        return ok(serialize_claim(claim))


@bp.get("/beneficiary-claims/<claim_id>/projection")
@require_roles(ROLE_PARTICIPANT, ROLE_CUSTODIAN, ROLE_COMPLIANCE, ROLE_AUDITOR)
def project_drawdown(claim_id: str, **kw):
    role = kw.get("_caller_role")
    caller = kw.get("_caller_id")
    claim = get_claim_or_404(claim_id)
    if role == ROLE_PARTICIPANT and claim["beneficiary_participant_id"] != caller:
        raise err_not_found(f"BeneficiaryClaim {claim_id} not found")
    as_of = query_date("as_of_date", required=True)
    deadline = parse_iso_date_str(claim["deadline_date"])
    if deadline is None:
        raise err_validation("Claim missing deadline_date")

    diff_days = (deadline - as_of).days  # type: ignore[operator]
    remaining_years = max(0, diff_days // 365)

    # Compute projected per-year RMD using single-life variant against today's
    # prior_year_end_balance for the inherited account.
    account = get_account_or_404(claim["account_id"])
    participant = get_participant_or_404(account["participant_id"])
    dob = parse_iso_date_str(participant["date_of_birth"])
    inheritance_start_year = None
    if account.get("inheritance_start_date"):
        inheritance_start_year = int(account["inheritance_start_date"][:4])

    from ..clock import current_year as _cy
    projected_rmd = compute_rmd_amount_cents(
        account_type=account["account_type"],
        inherited_from_participant_id=account.get("inherited_from_participant_id"),
        prior_year_end_balance_cents=account["prior_year_end_balance_cents"],
        date_of_birth=dob,  # type: ignore[arg-type]
        tax_year=_cy(),
        inheritance_start_year=inheritance_start_year,
    )
    total = projected_rmd * remaining_years

    return ok(
        {
            "claim_id": claim_id,
            "as_of_date": as_of.isoformat(),
            "deadline_date": claim["deadline_date"],
            "remaining_years": remaining_years,
            "projected_rmd_cents": projected_rmd,
            "projected_total_drawdown_cents": total,
        }
    )
