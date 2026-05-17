"""Conversion request lifecycle."""
from __future__ import annotations

from flask import Blueprint

from ..auth import ROLE_AUDITOR, ROLE_COMPLIANCE, ROLE_CUSTODIAN, ROLE_PARTICIPANT, require_roles
from ..clock import current_year
from ..errors import (
    err_account_closed,
    err_account_frozen,
    err_backdoor_precondition_violated,
    err_cross_participant_conversion,
    err_forbidden,
    err_insufficient_balance,
    err_invalid_conversion_pair,
    err_invalid_state,
    err_not_found,
    err_participant_deceased,
    err_segregation_violation,
    err_validation,
)
from ..helpers import assert_bool, assert_integer, assert_string, require_json_object
from ..responses import created, ok
from ..services.calculations import compute_federal_withholding
from ..services.ledger import issue_form_for_conversion, issue_form_for_distribution
from ..services.lookups import (
    bump_version,
    get_account_or_404,
    get_conversion_or_404,
    get_participant_or_404,
    init_common,
    init_event,
    parse_iso_date_str,
    ts,
)
from ..services.serialize import serialize_conversion
from ..store import store

bp = Blueprint("conversions", __name__)


@bp.post("/conversion-requests")
@require_roles(ROLE_PARTICIPANT)
def create_conversion(**kw):
    caller = kw["_caller_id"]
    body = require_json_object(allow_empty=False)
    source_id = assert_string(body.get("source_account_id"), "source_account_id")
    dest_id = assert_string(body.get("destination_account_id"), "destination_account_id")
    amount = assert_integer(body.get("amount_cents"), "amount_cents", minimum=1)
    backdoor = body.get("backdoor_flag", False)
    if backdoor is None:
        backdoor = False
    if not isinstance(backdoor, bool):
        raise err_validation("backdoor_flag must be a boolean")

    with store().lock:
        # Participant must exist (this is the caller's record)
        participant = get_participant_or_404(caller)

        # Priority 9: participant deceased
        if participant["is_deceased"]:
            raise err_participant_deceased()

        # Existence for source/dest
        if source_id not in store().accounts:
            raise err_not_found(f"Source account {source_id} not found")
        if dest_id not in store().accounts:
            raise err_not_found(f"Destination account {dest_id} not found")
        source = store().accounts[source_id]
        dest = store().accounts[dest_id]

        # Priority 12: type pairing
        if source["account_type"] != "TRADITIONAL" or dest["account_type"] != "ROTH":
            raise err_invalid_conversion_pair()

        # Priority 13: same participant + matches caller
        if source["participant_id"] != caller or dest["participant_id"] != caller:
            raise err_cross_participant_conversion()

        cr = init_common(
            {
                "participant_id": caller,
                "source_account_id": source_id,
                "destination_account_id": dest_id,
                "amount_cents": amount,
                "backdoor_flag": backdoor,
                "status": "PENDING",
                "approver_role_id": None,
                "completed_distribution_id": None,
            }
        )
        store().conversions[cr["id"]] = cr
        return created(serialize_conversion(cr))


@bp.get("/conversion-requests/<conversion_id>")
@require_roles(ROLE_PARTICIPANT, ROLE_CUSTODIAN, ROLE_COMPLIANCE, ROLE_AUDITOR)
def read_conversion(conversion_id: str, **kw):
    role = kw.get("_caller_role")
    caller = kw.get("_caller_id")
    cr = get_conversion_or_404(conversion_id)
    if role == ROLE_PARTICIPANT and cr["participant_id"] != caller:
        raise err_not_found(f"ConversionRequest {conversion_id} not found")
    return ok(serialize_conversion(cr))


@bp.post("/conversion-requests/<conversion_id>/approve")
@require_roles(ROLE_CUSTODIAN)
def approve_conversion(conversion_id: str, **kw):
    caller = kw["_caller_id"]
    require_json_object()
    with store().lock:
        cr = get_conversion_or_404(conversion_id)
        if cr["status"] != "PENDING":
            raise err_invalid_state(f"ConversionRequest is {cr['status']}; must be PENDING")
        # PRD §2.7 priority 5: account posture (FROZEN before CLOSED) precedes
        # workflow-state preconditions (priority 6).
        source = get_account_or_404(cr["source_account_id"])
        dest = get_account_or_404(cr["destination_account_id"])
        if source["status"] == "FROZEN" or dest["status"] == "FROZEN":
            raise err_account_frozen()
        if source["status"] == "CLOSED" or dest["status"] == "CLOSED":
            raise err_account_closed()
        # PRD §3.7: both accounts must be OPEN. After the posture checks above,
        # any non-OPEN status here is an unexpected workflow violation.
        if source["status"] != "OPEN" or dest["status"] != "OPEN":
            raise err_invalid_state("Both source and destination accounts must be OPEN")
        # Participant alive
        participant = get_participant_or_404(cr["participant_id"])
        if participant["is_deceased"]:
            raise err_participant_deceased()
        # Segregation: custodian X-User-ID == participant id is forbidden
        if caller == cr["participant_id"]:
            raise err_segregation_violation()
        # Backdoor precondition
        if cr["backdoor_flag"]:
            clock_year = current_year()
            posted_backdoor = [
                c
                for c in store().contributions.values()
                if c["account_id"] == source["id"]
                and c["status"] == "POSTED"
                and c["tax_year"] == clock_year
                and c["contribution_type"] == "BACKDOOR_NONDEDUCTIBLE"
            ]
            backdoor_sum = sum(c["amount_cents"] for c in posted_backdoor)

            non_backdoor_posted = [
                c
                for c in store().contributions.values()
                if c["account_id"] == source["id"]
                and c["status"] == "POSTED"
                and c["tax_year"] == clock_year
                and c["contribution_type"] != "BACKDOOR_NONDEDUCTIBLE"
            ]
            if non_backdoor_posted:
                raise err_backdoor_precondition_violated(
                    "Source has non-BACKDOOR POSTED contributions for current tax_year"
                )
            if source["balance_cents"] != backdoor_sum:
                raise err_backdoor_precondition_violated(
                    "Source balance does not equal sum of BACKDOOR contributions (earnings present)"
                )

        cr["status"] = "APPROVED"
        cr["approver_role_id"] = caller
        bump_version(cr)
        return ok(serialize_conversion(cr))


@bp.post("/conversion-requests/<conversion_id>/reject")
@require_roles(ROLE_CUSTODIAN)
def reject_conversion(conversion_id: str, **_kw):
    require_json_object()
    with store().lock:
        cr = get_conversion_or_404(conversion_id)
        if cr["status"] != "PENDING":
            raise err_invalid_state(f"ConversionRequest is {cr['status']}; must be PENDING")
        cr["status"] = "REJECTED"
        bump_version(cr)
        return ok(serialize_conversion(cr))


@bp.post("/conversion-requests/<conversion_id>/cancel")
@require_roles(ROLE_PARTICIPANT)
def cancel_conversion(conversion_id: str, **kw):
    caller = kw["_caller_id"]
    require_json_object()
    with store().lock:
        cr = get_conversion_or_404(conversion_id)
        # Scope: participant must own
        if cr["participant_id"] != caller:
            # Treat as not-found per cross-tenant rule
            raise err_not_found(f"ConversionRequest {conversion_id} not found")
        if cr["status"] != "PENDING":
            raise err_invalid_state(f"ConversionRequest is {cr['status']}; must be PENDING")
        cr["status"] = "CANCELED"
        bump_version(cr)
        return ok(serialize_conversion(cr))


@bp.post("/conversion-requests/<conversion_id>/complete")
@require_roles(ROLE_CUSTODIAN)
def complete_conversion(conversion_id: str, **_kw):
    require_json_object()
    with store().lock:
        cr = get_conversion_or_404(conversion_id)
        if cr["status"] != "APPROVED":
            raise err_invalid_state(f"ConversionRequest is {cr['status']}; must be APPROVED")
        source = get_account_or_404(cr["source_account_id"])
        dest = get_account_or_404(cr["destination_account_id"])
        if source["status"] == "CLOSED" or dest["status"] == "CLOSED":
            raise err_account_closed()
        amount = cr["amount_cents"]
        if source["balance_cents"] < amount:
            raise err_insufficient_balance(
                f"Source balance {source['balance_cents']} is less than amount {amount}"
            )

        # Cascade depth 1: create the DistributionEvent
        clock_year = current_year()
        distribution = init_event(
            {
                "account_id": source["id"],
                "gross_amount_cents": amount,
                "distribution_reason": "CONVERSION",
                "federal_withholding_cents": 0,
                "net_amount_cents": amount,
                "tax_year": clock_year,
                "settled_at": ts(),
            }
        )
        store().distributions[distribution["id"]] = distribution

        # Cascade depth 2: debit source, credit destination
        source["balance_cents"] -= amount
        dest["balance_cents"] += amount
        bump_version(source)
        bump_version(dest)

        # Cascade depth 3: 1099-R with CONVERSION
        issue_form_for_conversion(cr)

        cr["status"] = "COMPLETED"
        cr["completed_distribution_id"] = distribution["id"]
        bump_version(cr)
        return ok(serialize_conversion(cr))
