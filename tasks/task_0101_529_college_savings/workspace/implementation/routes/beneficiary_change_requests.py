"""Beneficiary change request endpoints."""

from flask import Blueprint, g, request
from core.auth import require_roles
from core.envelope import success_object
from core.errors import raise_error
from core.store import STORE, lock
from core.validation import (
    require_body, require_field, require_enum,
)
from core.models import bcr_create, bcr_view, touch
from services.relationships import is_permissible, is_generation_skip


bp = Blueprint("bcrs", __name__)


REJECTION_REASONS = {
    "RELATIONSHIP_NOT_PERMITTED", "GENERATION_SKIP",
    "ACCOUNT_NOT_OPEN", "IDENTICAL_TO_CURRENT",
}


def _check_donor_owns_account(account):
    if g.user_role == "Donor" and account["primary_donor_id"] != g.user_id:
        raise_error("ERR_FORBIDDEN", "Donor does not own this account")


@bp.post("/accounts/<aid>/beneficiary-change-requests")
@require_roles("Donor")
def submit_bcr(aid):
    body = require_body(request)
    proposed_id = require_field(body, "proposed_beneficiary_id", kind="string")
    with lock():
        a = STORE.accounts.get(aid)
        if not a:
            raise_error("ERR_NOT_FOUND", f"Account {aid} not found")
        _check_donor_owns_account(a)
        if not STORE.beneficiaries.get(proposed_id):
            raise_error("ERR_NOT_FOUND", f"Beneficiary {proposed_id} not found")
        if a["status"] != "OPEN":
            raise_error("ERR_ACCOUNT_RESTRICTED",
                        f"Account is {a['status']}; cannot submit beneficiary change")
        bcr = bcr_create(aid, a["beneficiary_id"], proposed_id)
    return success_object(bcr_view(bcr), 201)


@bp.post("/beneficiary-change-requests/<bid>/approve")
@require_roles("PlanAdministrator")
def approve_bcr(bid):
    with lock():
        bcr = STORE.beneficiary_change_requests.get(bid)
        if not bcr:
            raise_error("ERR_NOT_FOUND", f"BeneficiaryChangeRequest {bid} not found")
        a = STORE.accounts.get(bcr["account_id"])
        if not a:
            raise_error("ERR_NOT_FOUND", "Account missing for this request")
        # Priority 6 — account state.
        if a["status"] != "OPEN":
            raise_error("ERR_ACCOUNT_RESTRICTED",
                        f"Account is {a['status']}; cannot approve change")
        # Priority 7 — request state.
        if bcr["status"] != "SUBMITTED":
            raise_error("ERR_INVALID_STATE",
                        f"Request is {bcr['status']}; only SUBMITTED may be approved")
        # Concurrency rule (scaffold): stale snapshot check.
        if a["beneficiary_id"] != bcr["current_beneficiary_id"]:
            raise_error("ERR_STALE_BENEFICIARY_SNAPSHOT",
                        "Account beneficiary has changed since this request was submitted")
        # Priority 11 — identical-to-current.
        if bcr["proposed_beneficiary_id"] == a["beneficiary_id"]:
            raise_error("ERR_BENEFICIARY_IDENTICAL_TO_CURRENT",
                        "Proposed beneficiary is identical to current")
        # Resolve current/proposed beneficiary rows.
        cur_ben = STORE.beneficiaries.get(a["beneficiary_id"])
        proposed_ben = STORE.beneficiaries.get(bcr["proposed_beneficiary_id"])
        if not cur_ben or not proposed_ben:
            raise_error("ERR_NOT_FOUND", "Beneficiary record missing")
        # Priority 12 — permissible family set.
        if not is_permissible(proposed_ben["relationship_family_code"]):
            raise_error("ERR_BENEFICIARY_RELATIONSHIP_FORBIDDEN",
                        "Proposed beneficiary relationship is not in the permissible family set")
        # Priority 13 — generation skip (safety check, fires before business-constraint).
        if is_generation_skip(cur_ben["relationship_family_code"],
                              proposed_ben["relationship_family_code"]):
            raise_error("ERR_BENEFICIARY_GENERATION_SKIP",
                        "Proposed beneficiary skips upward more than one generation")

        a["beneficiary_id"] = bcr["proposed_beneficiary_id"]
        touch(a)
        bcr["status"] = "APPROVED"
        touch(bcr)
    return success_object(bcr_view(bcr))


@bp.post("/beneficiary-change-requests/<bid>/reject")
@require_roles("PlanAdministrator")
def reject_bcr(bid):
    body = require_body(request)
    reason = require_enum(body, "rejection_reason", REJECTION_REASONS)
    with lock():
        bcr = STORE.beneficiary_change_requests.get(bid)
        if not bcr:
            raise_error("ERR_NOT_FOUND", f"BeneficiaryChangeRequest {bid} not found")
        if bcr["status"] != "SUBMITTED":
            raise_error("ERR_INVALID_STATE",
                        f"Request is {bcr['status']}; only SUBMITTED may be rejected")
        bcr["status"] = "REJECTED"
        bcr["rejection_reason"] = reason
        touch(bcr)
    return success_object(bcr_view(bcr))
