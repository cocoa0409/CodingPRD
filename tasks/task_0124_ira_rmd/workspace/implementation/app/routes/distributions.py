"""Distribution posting."""
from __future__ import annotations

from flask import Blueprint

from ..auth import ROLE_CUSTODIAN, ROLE_PARTICIPANT, require_roles
from ..clock import current_date, current_year
from ..errors import (
    err_account_closed,
    err_account_frozen,
    err_inherited_claim_forfeited,
    err_insufficient_balance,
    err_invalid_state,
    err_not_found,
    err_rmd_already_taken,
    err_rmd_amount_mismatch,
    err_rmd_period_closed,
    err_secure_deadline_expired,
    err_validation,
)
from ..helpers import assert_enum, assert_integer, require_json_object
from ..responses import created
from ..services.calculations import (
    compute_federal_withholding,
    compute_rmd_amount_cents,
)
from ..services.constants import DISTRIBUTION_REASONS
from ..services.ledger import issue_form_for_distribution
from ..services.lookups import (
    bump_version,
    claim_for_account,
    get_account_or_404,
    get_participant_or_404,
    init_event,
    parse_iso_date_str,
    ts,
)
from ..services.serialize import serialize_distribution
from ..store import store

bp = Blueprint("distributions", __name__)


# Reasons that may be created directly by clients (PRD §3.4 reserves CONVERSION
# and EXCESS_REMOVAL for system-issued cascades).
_CLIENT_DISTRIBUTION_REASONS = {"NORMAL", "EARLY", "RMD", "DEATH"}


@bp.post("/accounts/<account_id>/distributions")
@require_roles(ROLE_PARTICIPANT, ROLE_CUSTODIAN)
def post_distribution(account_id: str, **kw):
    role = kw.get("_caller_role")
    caller = kw.get("_caller_id")
    body = require_json_object(allow_empty=False)
    gross = assert_integer(body.get("gross_amount_cents"), "gross_amount_cents", minimum=1)
    reason = assert_enum(body.get("distribution_reason"), "distribution_reason", DISTRIBUTION_REASONS)

    if reason not in _CLIENT_DISTRIBUTION_REASONS:
        # Per PRD §3.4 these reasons are reserved for system-issued cascades.
        raise err_validation(
            f"distribution_reason '{reason}' is reserved for system-issued events"
        )

    with store().lock:
        account = get_account_or_404(account_id)

        # Cross-tenant scope for Participant role
        if role == ROLE_PARTICIPANT and caller != account["participant_id"]:
            raise err_not_found(f"Account {account_id} not found")

        # Priority 6: account frozen for non-RMD distributions
        if account["status"] == "FROZEN" and reason != "RMD":
            raise err_account_frozen()
        # Priority 7: closed
        if account["status"] == "CLOSED":
            raise err_account_closed()

        participant = get_participant_or_404(account["participant_id"])

        # Priority 9: participant deceased for non-RMD/non-DEATH
        if participant["is_deceased"] and reason not in ("RMD", "DEATH"):
            from ..errors import err_participant_deceased
            raise err_participant_deceased()

        is_inherited = account.get("inherited_from_participant_id") is not None
        claim = claim_for_account(account_id)

        if is_inherited and claim is not None:
            # Priority 10: forfeited claim
            if claim["status"] == "FORFEITED":
                raise err_inherited_claim_forfeited()
            # Priority 10 (extension): suspended claim blocks new distributions (PRD §3.6)
            if claim["status"] == "SUSPENDED":
                raise err_invalid_state(
                    "Beneficiary claim is SUSPENDED; new distributions blocked"
                )
            # Priority 11: deadline expired
            deadline = parse_iso_date_str(claim["deadline_date"])
            if deadline is not None and current_date() > deadline:
                raise err_secure_deadline_expired()

        # Priority 17: insufficient balance
        if gross > account["balance_cents"]:
            raise err_insufficient_balance(
                f"gross_amount_cents {gross} exceeds balance {account['balance_cents']}"
            )

        clock_year = current_year()

        # Priority 18: RMD amount must equal computed amount
        if reason == "RMD":
            # Priority 20: RMD for tax_year < clock_year (period closed)
            # Default tax_year for RMD distribution is current clock_year (we
            # don't accept tax_year as a body field for distributions — captured
            # by system). Hence period_closed is not reachable from this route
            # for the simple submission case. We still check whether a previous
            # year's RMD is allowed: the scaffold ties tax_year to system clock.
            # Hence we only enforce the RMD-already-taken check below.

            # Per-RMD-per-year (concurrency rule)
            for d in store().distributions.values():
                if (
                    d["account_id"] == account_id
                    and d["distribution_reason"] == "RMD"
                    and d["tax_year"] == clock_year
                ):
                    raise err_rmd_already_taken()

            dob = parse_iso_date_str(participant["date_of_birth"])
            inheritance_start_year = None
            if account.get("inheritance_start_date"):
                inheritance_start_year = int(account["inheritance_start_date"][:4])
            required = compute_rmd_amount_cents(
                account_type=account["account_type"],
                inherited_from_participant_id=account.get("inherited_from_participant_id"),
                prior_year_end_balance_cents=account["prior_year_end_balance_cents"],
                date_of_birth=dob,  # type: ignore[arg-type]
                tax_year=clock_year,
                inheritance_start_year=inheritance_start_year,
            )
            if gross != required:
                raise err_rmd_amount_mismatch(
                    f"RMD gross_amount_cents {gross} must equal required {required}"
                )

        # Compute withholding
        dob = parse_iso_date_str(participant["date_of_birth"])
        withholding = compute_federal_withholding(
            gross_amount_cents=gross,  # type: ignore[arg-type]
            distribution_reason=reason,  # type: ignore[arg-type]
            date_of_birth=dob,  # type: ignore[arg-type]
            clock_year=clock_year,
        )

        distribution = init_event(
            {
                "account_id": account_id,
                "gross_amount_cents": gross,
                "distribution_reason": reason,
                "federal_withholding_cents": withholding,
                "net_amount_cents": gross - withholding,  # type: ignore[operator]
                "tax_year": clock_year,
                "settled_at": ts(),
            }
        )
        store().distributions[distribution["id"]] = distribution

        # Debit balance
        account["balance_cents"] -= gross  # type: ignore[operator]
        bump_version(account)

        # Issue 1099-R
        issue_form_for_distribution(distribution, account)

        # Inherited account drained
        if is_inherited and claim is not None and account["balance_cents"] == 0:
            if claim["status"] == "CLAIMED":
                claim["status"] = "DRAINED"
                claim["drained_amount_cents"] += gross  # type: ignore[operator]
                bump_version(claim)

        return created(serialize_distribution(distribution))
