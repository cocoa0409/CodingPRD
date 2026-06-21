"""Contribution endpoints."""

from flask import Blueprint, request

import db
from calculations import contribution_limit, roth_eligibility
from errors import (
    ERR_CONTRIBUTION_CAP_EXCEEDED,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_KIND_ACCOUNT_MISMATCH,
    ERR_STALE_VERSION,
    ERR_TAX_YEAR_CLOSED,
    raise_api,
)
from helpers import (
    append_audit_event,
    get_account_or_404,
    get_contribution_or_404,
    get_json_body,
    get_pagination_params,
    paginate,
    require_enum,
    require_int,
    require_str,
)
from middleware import g, parse_auth_headers, require_owner_match, require_roles
from response import success_array, success_object
from serializers import contribution_to_json


bp = Blueprint("contributions", __name__, url_prefix="/ira/contributions")


CONTRIBUTION_KINDS = {"PRETAX", "AFTERTAX", "ROTH"}
CONTRIBUTION_STATUSES = {"PENDING", "CONFIRMED", "REJECTED", "REVERSED"}


@bp.route("", methods=["POST"])
def create_contribution():
    parse_auth_headers()
    require_roles("AccountOwner")
    body = get_json_body()
    account_id = require_str(body, "account_id")
    tax_year = require_int(body, "tax_year")
    amount_cents = require_int(body, "amount_cents")
    if amount_cents <= 0:
        raise_api(ERR_INVALID_REQUEST, "amount_cents must be > 0.")
    contribution_kind = require_enum(body, "contribution_kind", CONTRIBUTION_KINDS)

    acct = get_account_or_404(account_id)
    require_owner_match(acct["owner_id"])

    now = db.now_utc()
    c = {
        "id": db.new_id(),
        "account_id": account_id,
        "tax_year": tax_year,
        "amount_cents": amount_cents,
        "contribution_kind": contribution_kind,
        "status": "PENDING",
        "confirmed_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.contributions[c["id"]] = c
    return success_object(contribution_to_json(c), status_code=201)


@bp.route("/<contrib_id>", methods=["GET"])
def get_contribution(contrib_id):
    parse_auth_headers()
    require_roles("PlanAdministrator", "AccountOwner", "IRSAuditor")
    c = get_contribution_or_404(contrib_id)
    if g.role == "AccountOwner":
        acct = db.accounts.get(c["account_id"])
        if acct is None:
            from errors import ERR_NOT_FOUND
            raise_api(ERR_NOT_FOUND)
        require_owner_match(acct["owner_id"])
    return success_object(contribution_to_json(c))


@bp.route("", methods=["GET"])
def list_contributions():
    parse_auth_headers()
    require_roles("PlanAdministrator", "AccountOwner", "IRSAuditor")
    limit, offset = get_pagination_params()
    account_id = request.args.get("account_id")
    tax_year_str = request.args.get("tax_year")
    status = request.args.get("status")
    rows = list(db.contributions.values())
    if account_id is not None:
        rows = [c for c in rows if c["account_id"] == account_id]
    if tax_year_str is not None:
        try:
            ty = int(tax_year_str)
        except ValueError:
            raise_api(ERR_INVALID_REQUEST, "tax_year filter must be an integer.")
        rows = [c for c in rows if c["tax_year"] == ty]
    if status is not None:
        if status not in CONTRIBUTION_STATUSES:
            raise_api(ERR_INVALID_REQUEST, "status filter is not a recognized value.")
        rows = [c for c in rows if c["status"] == status]
    if g.role == "AccountOwner":
        # Restrict to contributions on the owner's own accounts.
        owned_accounts = {a["id"] for a in db.accounts.values() if a["owner_id"] == g.user_id}
        rows = [c for c in rows if c["account_id"] in owned_accounts]
    page, total = paginate(rows, limit, offset)
    return success_array([contribution_to_json(c) for c in page], limit, offset, total)


@bp.route("/<contrib_id>/confirm", methods=["POST"])
def confirm_contribution(contrib_id):
    parse_auth_headers()
    require_roles("AccountOwner")
    c = get_contribution_or_404(contrib_id)
    acct = get_account_or_404(c["account_id"])
    require_owner_match(acct["owner_id"])

    # State precondition: contribution must be PENDING
    if c["status"] != "PENDING":
        raise_api(ERR_INVALID_STATE, "Contribution is not PENDING.")

    body = get_json_body()
    expected = require_int(body, "expected_account_version")
    if expected != acct["version"]:
        raise_api(ERR_STALE_VERSION)

    # Account state must be ACTIVE.
    if acct["status"] != "ACTIVE":
        raise_api(ERR_INVALID_STATE, "Account is not ACTIVE.")

    owner = db.owners.get(acct["owner_id"])
    if owner is None:
        from errors import ERR_NOT_FOUND
        raise_api(ERR_NOT_FOUND)

    # Business validation: kind matches account type (priority 8)
    kind = c["contribution_kind"]
    if kind == "ROTH" and acct["account_type"] != "ROTH":
        raise_api(ERR_KIND_ACCOUNT_MISMATCH)
    if kind in ("PRETAX", "AFTERTAX") and acct["account_type"] != "TRADITIONAL":
        raise_api(ERR_KIND_ACCOUNT_MISMATCH)

    # Tax year matches account.tax_year_marker (priority 9)
    if c["tax_year"] != acct["tax_year_marker"]:
        raise_api(ERR_TAX_YEAR_CLOSED)

    # Contribution cap (priority 11)
    effective_limit = contribution_limit(owner, acct["account_type"], c["tax_year"])
    # ROTH kind: phase-out must return strictly > 0
    if kind == "ROTH":
        # roth_eligibility was already applied inside contribution_limit when
        # account_type is ROTH. If it returned 0, the confirm fails with cap-exceeded.
        if effective_limit == 0:
            raise_api(ERR_CONTRIBUTION_CAP_EXCEEDED)
    if acct["ytd_contribution_cents"] + c["amount_cents"] > effective_limit:
        raise_api(ERR_CONTRIBUTION_CAP_EXCEEDED)

    # Side effects
    now = db.now_utc()
    c["status"] = "CONFIRMED"
    c["confirmed_at"] = now
    c["updated_at"] = now
    c["version"] += 1
    acct["cash_balance_cents"] += c["amount_cents"]
    acct["ytd_contribution_cents"] += c["amount_cents"]
    if kind == "PRETAX":
        acct["pretax_basis_cents"] += c["amount_cents"]
    elif kind == "AFTERTAX":
        acct["aftertax_basis_cents"] += c["amount_cents"]
    # ROTH: neither pretax nor aftertax basis touched.
    acct["updated_at"] = now
    acct["version"] += 1

    append_audit_event(
        owner_id=acct["owner_id"],
        account_id=acct["id"],
        event_kind="CONTRIBUTION_CONFIRMED",
        tax_year=c["tax_year"],
        amount_cents=c["amount_cents"],
    )

    return success_object(contribution_to_json(c))


@bp.route("/<contrib_id>/reject", methods=["POST"])
def reject_contribution(contrib_id):
    parse_auth_headers()
    require_roles("PlanAdministrator")
    c = get_contribution_or_404(contrib_id)
    if c["status"] != "PENDING":
        raise_api(ERR_INVALID_STATE, "Contribution is not PENDING.")
    now = db.now_utc()
    c["status"] = "REJECTED"
    c["updated_at"] = now
    c["version"] += 1
    return success_object(contribution_to_json(c))


@bp.route("/<contrib_id>/reverse", methods=["POST"])
def reverse_contribution(contrib_id):
    parse_auth_headers()
    require_roles("PlanAdministrator")
    c = get_contribution_or_404(contrib_id)
    acct = get_account_or_404(c["account_id"])
    body = get_json_body()
    expected = require_int(body, "expected_account_version")

    if c["status"] != "CONFIRMED":
        raise_api(ERR_INVALID_STATE, "Contribution is not CONFIRMED.")
    if expected != acct["version"]:
        raise_api(ERR_STALE_VERSION)

    # Same tax year check: contribution's tax_year must equal account's current tax_year_marker.
    if c["tax_year"] != acct["tax_year_marker"]:
        raise_api(ERR_INVALID_STATE, "Contribution is not in the current tax year.")
    if acct["cash_balance_cents"] < c["amount_cents"]:
        raise_api(ERR_INVALID_STATE, "Account cash_balance_cents insufficient to reverse.")

    now = db.now_utc()
    c["status"] = "REVERSED"
    c["updated_at"] = now
    c["version"] += 1
    acct["cash_balance_cents"] -= c["amount_cents"]
    acct["ytd_contribution_cents"] -= c["amount_cents"]
    if c["contribution_kind"] == "PRETAX":
        acct["pretax_basis_cents"] -= c["amount_cents"]
    elif c["contribution_kind"] == "AFTERTAX":
        acct["aftertax_basis_cents"] -= c["amount_cents"]
    acct["updated_at"] = now
    acct["version"] += 1
    return success_object(contribution_to_json(c))
