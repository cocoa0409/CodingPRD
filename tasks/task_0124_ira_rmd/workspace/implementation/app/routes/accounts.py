"""Account routes: open, read, freeze/unfreeze/close, excess-sweep, RMD."""
from __future__ import annotations

from datetime import date, timedelta

from flask import Blueprint

from ..auth import (
    ROLE_AUDITOR,
    ROLE_COMPLIANCE,
    ROLE_CUSTODIAN,
    ROLE_PARTICIPANT,
    require_roles,
)
from ..clock import current_date, current_year
from ..errors import (
    err_account_closed,
    err_account_frozen,
    err_forbidden,
    err_invalid_state,
    err_not_found,
    err_participant_deceased,
    err_validation,
)
from ..helpers import (
    assert_enum,
    assert_string,
    query_int,
    require_json_object,
)
from ..responses import created, ok
from ..services.calculations import compute_rmd_amount_cents
from ..services.constants import ACCOUNT_TYPES
from ..services.ledger import run_excess_sweep_for_account
from ..services.lookups import (
    bump_version,
    claim_for_account,
    get_account_or_404,
    get_account_scoped_or_404,
    get_participant_or_404,
    init_common,
    parse_iso_date_str,
)
from ..services.serialize import (
    serialize_account,
    serialize_claim,
    serialize_excess_penalty,
)
from ..store import store

bp = Blueprint("accounts", __name__)


@bp.post("/participants/<participant_id>/accounts")
@require_roles(ROLE_CUSTODIAN)
def open_account(participant_id: str, **_kw):
    body = require_json_object(allow_empty=False)
    account_type = assert_enum(body.get("account_type"), "account_type", ACCOUNT_TYPES)
    inherited_from = body.get("inherited_from_participant_id")
    if inherited_from is not None and not isinstance(inherited_from, str):
        raise err_validation("inherited_from_participant_id must be a string when supplied")

    with store().lock:
        participant = get_participant_or_404(participant_id)
        if inherited_from is not None and inherited_from == participant_id:
            raise err_validation("inherited_from_participant_id cannot be the participant themselves")

        # If inherited, validate the source participant exists too (best-effort:
        # not strictly required by scaffold but improves correctness).
        if inherited_from is not None:
            if inherited_from not in store().participants:
                raise err_not_found(f"Inherited-from participant {inherited_from} not found")

        today_iso = current_date().isoformat()
        account = init_common(
            {
                "participant_id": participant_id,
                "account_type": account_type,
                "status": "OPEN",
                "balance_cents": 0,
                "ytd_contribution_cents": 0,
                "tax_year": current_year(),
                "prior_year_end_balance_cents": 0,
                "inherited_from_participant_id": inherited_from,
                "inheritance_start_date": today_iso if inherited_from else None,
            }
        )
        store().accounts[account["id"]] = account

        if inherited_from is not None:
            today = current_date()
            deadline = date(today.year + 10, today.month, today.day) if not _is_leap_edge(today) else today + timedelta(days=10 * 365)
            claim = init_common(
                {
                    "account_id": account["id"],
                    "beneficiary_participant_id": participant_id,
                    "claim_date": today.isoformat(),
                    "deadline_date": deadline.isoformat(),
                    "status": "CLAIMED",
                    "drained_amount_cents": 0,
                }
            )
            store().claims[claim["id"]] = claim
            store().claim_by_account[account["id"]] = claim["id"]

        return created(serialize_account(account))


def _is_leap_edge(d: date) -> bool:
    """Detect Feb 29 (would not exist 10 years later in all cases)."""
    return d.month == 2 and d.day == 29


@bp.get("/participants/<participant_id>/accounts/<account_id>")
@require_roles(ROLE_CUSTODIAN, ROLE_COMPLIANCE, ROLE_AUDITOR, ROLE_PARTICIPANT)
def read_account(participant_id: str, account_id: str, **kw):
    role = kw.get("_caller_role")
    caller = kw.get("_caller_id")
    account = get_account_scoped_or_404(participant_id, account_id)
    if role == ROLE_PARTICIPANT and caller != participant_id:
        raise err_not_found(f"Account {account_id} not found for participant {participant_id}")
    return ok(serialize_account(account))


@bp.post("/accounts/<account_id>/freeze")
@require_roles(ROLE_CUSTODIAN, ROLE_COMPLIANCE)
def freeze_account(account_id: str, **_kw):
    require_json_object()
    with store().lock:
        account = get_account_or_404(account_id)
        if account["status"] == "CLOSED":
            raise err_account_closed()
        if account["status"] != "OPEN":
            raise err_invalid_state("Account must be OPEN to freeze")
        account["status"] = "FROZEN"
        bump_version(account)
        return ok(serialize_account(account))


@bp.post("/accounts/<account_id>/unfreeze")
@require_roles(ROLE_CUSTODIAN, ROLE_COMPLIANCE)
def unfreeze_account(account_id: str, **_kw):
    require_json_object()
    with store().lock:
        account = get_account_or_404(account_id)
        if account["status"] == "CLOSED":
            raise err_account_closed()
        if account["status"] != "FROZEN":
            raise err_invalid_state("Account must be FROZEN to unfreeze")
        participant = get_participant_or_404(account["participant_id"])
        if participant["is_deceased"]:
            raise err_participant_deceased()
        account["status"] = "OPEN"
        bump_version(account)
        return ok(serialize_account(account))


@bp.post("/accounts/<account_id>/close")
@require_roles(ROLE_CUSTODIAN)
def close_account(account_id: str, **_kw):
    require_json_object()
    with store().lock:
        account = get_account_or_404(account_id)
        if account["status"] == "CLOSED":
            raise err_account_closed()
        # State preconditions (only OPEN or FROZEN may close)
        if account["status"] not in ("OPEN", "FROZEN"):
            raise err_invalid_state("Account is not in a closable state")
        if account["balance_cents"] != 0:
            raise err_invalid_state("Account balance must be zero to close")
        # No PENDING ConversionRequest referencing this account as source/dest
        for cr in store().conversions.values():
            if cr["status"] != "PENDING":
                continue
            if cr["source_account_id"] == account_id or cr["destination_account_id"] == account_id:
                raise err_invalid_state(
                    "Account is referenced by a PENDING ConversionRequest"
                )
        # From OPEN: also no CLAIMED claim referencing this account
        if account["status"] == "OPEN":
            for claim in store().claims.values():
                if claim["account_id"] == account_id and claim["status"] == "CLAIMED":
                    raise err_invalid_state(
                        "Account has an active CLAIMED beneficiary claim"
                    )
        account["status"] = "CLOSED"
        bump_version(account)
        return ok(serialize_account(account))


# ---------------------------------------------------------------------------
# RMD quote (read-only)
# ---------------------------------------------------------------------------

@bp.get("/accounts/<account_id>/rmd")
@require_roles(ROLE_PARTICIPANT, ROLE_CUSTODIAN, ROLE_COMPLIANCE, ROLE_AUDITOR)
def read_rmd(account_id: str, **kw):
    role = kw.get("_caller_role")
    caller = kw.get("_caller_id")
    account = get_account_or_404(account_id)
    if role == ROLE_PARTICIPANT and caller != account["participant_id"]:
        raise err_not_found(f"Account {account_id} not found")
    tax_year = query_int("tax_year", required=True)
    participant = get_participant_or_404(account["participant_id"])
    dob = parse_iso_date_str(participant["date_of_birth"])
    inheritance_start_year = None
    if account.get("inheritance_start_date"):
        inheritance_start_year = int(account["inheritance_start_date"][:4])
    rmd = compute_rmd_amount_cents(
        account_type=account["account_type"],
        inherited_from_participant_id=account.get("inherited_from_participant_id"),
        prior_year_end_balance_cents=account["prior_year_end_balance_cents"],
        date_of_birth=dob,  # type: ignore[arg-type]
        tax_year=tax_year,  # type: ignore[arg-type]
        inheritance_start_year=inheritance_start_year,
    )
    return ok(
        {
            "account_id": account_id,
            "tax_year": tax_year,
            "required_amount_cents": rmd,
        }
    )


# ---------------------------------------------------------------------------
# Manual excess-contribution sweep
# ---------------------------------------------------------------------------

@bp.post("/accounts/<account_id>/excess-sweep")
@require_roles(ROLE_CUSTODIAN)
def excess_sweep(account_id: str, **_kw):
    require_json_object()
    with store().lock:
        account = get_account_or_404(account_id)
        if account["status"] == "CLOSED":
            raise err_account_closed()
        penalty = run_excess_sweep_for_account(account, current_year())
        if penalty is None:
            return ok(
                {
                    "account_id": account_id,
                    "tax_year": current_year(),
                    "excess_amount_cents": 0,
                    "penalty_amount_cents": 0,
                    "assessed_at": None,
                    "id": None,
                }
            )
        return ok(serialize_excess_penalty(penalty))
