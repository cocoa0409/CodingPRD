"""Contribution posting + reversal."""
from __future__ import annotations

from flask import Blueprint

from ..auth import ROLE_CUSTODIAN, ROLE_PARTICIPANT, require_roles
from ..clock import current_year
from ..errors import (
    err_account_closed,
    err_account_frozen,
    err_catchup_age_ineligible,
    err_contribution_cap_exceeded,
    err_forbidden,
    err_invalid_state,
    err_not_found,
    err_participant_deceased,
    err_validation,
)
from ..helpers import assert_enum, assert_integer, require_json_object
from ..responses import created, ok
from ..services.calculations import (
    applicable_contribution_cap_cents,
    is_catchup_eligible,
)
from ..services.constants import (
    CONTRIBUTION_TYPES,
    PER_CALL_CONTRIBUTION_CAP_CENTS,
)
from ..services.lookups import (
    bump_version,
    get_account_or_404,
    get_contribution_or_404,
    get_participant_or_404,
    init_event,
    parse_iso_date_str,
    ts,
)
from ..services.serialize import serialize_contribution
from ..store import store

bp = Blueprint("contributions", __name__)


@bp.post("/accounts/<account_id>/contributions")
@require_roles(ROLE_PARTICIPANT, ROLE_CUSTODIAN)
def post_contribution(account_id: str, **kw):
    role = kw.get("_caller_role")
    caller = kw.get("_caller_id")
    body = require_json_object(allow_empty=False)
    amount = assert_integer(
        body.get("amount_cents"),
        "amount_cents",
        minimum=1,
        maximum=PER_CALL_CONTRIBUTION_CAP_CENTS,
    )
    contribution_type = assert_enum(
        body.get("contribution_type"), "contribution_type", CONTRIBUTION_TYPES
    )

    with store().lock:
        account = get_account_or_404(account_id)
        # Cross-tenant scope for Participant role
        if role == ROLE_PARTICIPANT and caller != account["participant_id"]:
            raise err_not_found(f"Account {account_id} not found")

        participant = get_participant_or_404(account["participant_id"])

        # Priority 6 (state): account frozen -> ERR_ACCOUNT_FROZEN (non-RMD)
        if account["status"] == "FROZEN":
            raise err_account_frozen()
        # Priority 7: closed
        if account["status"] == "CLOSED":
            raise err_account_closed()

        # Priority 9: participant deceased
        if participant["is_deceased"]:
            raise err_participant_deceased()

        # Inherited account: contributions not normally allowed; not covered
        # by any explicit error in scaffold; treat per default as allowed (cap
        # check will run normally). Skip stricter check to avoid over-stepping.

        dob = parse_iso_date_str(participant["date_of_birth"])
        clock_year = current_year()
        cap = applicable_contribution_cap_cents(dob, clock_year)  # type: ignore[arg-type]

        # Priority 15: cap check (equality permitted)
        if account["ytd_contribution_cents"] + amount > cap:
            raise err_contribution_cap_exceeded(
                f"Posting {amount} would push YTD to "
                f"{account['ytd_contribution_cents'] + amount}, exceeding cap {cap}"
            )

        # Priority 16: catch-up eligibility
        if contribution_type == "CATCHUP" and not is_catchup_eligible(dob, clock_year):  # type: ignore[arg-type]
            raise err_catchup_age_ineligible(
                "Participant must be at least 50 on Dec 31 of clock year for CATCHUP"
            )

        contribution = init_event(
            {
                "account_id": account_id,
                "amount_cents": amount,
                "contribution_type": contribution_type,
                "tax_year": clock_year,
                "status": "POSTED",
                "reversed_at": None,
            }
        )
        store().contributions[contribution["id"]] = contribution

        account["ytd_contribution_cents"] += amount  # type: ignore[operator]
        account["balance_cents"] += amount  # type: ignore[operator]
        bump_version(account)

        return created(serialize_contribution(contribution))


@bp.post("/contributions/<contribution_id>/reverse")
@require_roles(ROLE_CUSTODIAN)
def reverse_contribution(contribution_id: str, **_kw):
    require_json_object()
    with store().lock:
        contribution = get_contribution_or_404(contribution_id)
        if contribution["status"] != "POSTED":
            raise err_invalid_state("Contribution is not POSTED")

        account = get_account_or_404(contribution["account_id"])
        # Reversal is permitted on FROZEN accounts (custodian remediation),
        # but not on CLOSED accounts.
        if account["status"] == "CLOSED":
            raise err_account_closed()

        amount = contribution["amount_cents"]
        contribution["status"] = "REVERSED"
        contribution["reversed_at"] = ts()

        account["ytd_contribution_cents"] -= amount
        account["balance_cents"] -= amount
        bump_version(account)

        # Create offsetting EXCESS_REMOVAL distribution
        from ..clock import current_year as _cy

        distribution = init_event(
            {
                "account_id": account["id"],
                "gross_amount_cents": amount,
                "distribution_reason": "EXCESS_REMOVAL",
                "federal_withholding_cents": 0,
                "net_amount_cents": amount,
                "tax_year": _cy(),
                "settled_at": ts(),
            }
        )
        store().distributions[distribution["id"]] = distribution

        return ok(serialize_contribution(contribution))
