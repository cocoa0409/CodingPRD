"""Conversion endpoints (Backdoor Roth)."""

from flask import Blueprint, request

import db
from calculations import backdoor_roth_pro_rata
from errors import (
    ERR_INVALID_CONVERSION_PAIR,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_STALE_VERSION,
    raise_api,
)
from helpers import (
    append_audit_event,
    get_account_or_404,
    get_conversion_or_404,
    get_json_body,
    get_pagination_params,
    optional_bool,
    paginate,
    require_int,
    require_str,
)
from middleware import g, parse_auth_headers, require_owner_match, require_roles
from response import success_array, success_object
from serializers import conversion_to_json


bp = Blueprint("conversions", __name__, url_prefix="/ira/conversions")


CONVERSION_STATUSES = {"INITIATED", "COMPLETED", "REVERSED"}


@bp.route("", methods=["POST"])
def create_conversion():
    parse_auth_headers()
    require_roles("AccountOwner")
    body = get_json_body()
    source_id = require_str(body, "source_account_id")
    target_id = require_str(body, "target_account_id")
    gross = require_int(body, "gross_amount_cents")
    if gross <= 0:
        raise_api(ERR_INVALID_REQUEST, "gross_amount_cents must be > 0.")
    aggregate_basis = optional_bool(body, "aggregate_basis", default=False)

    source = get_account_or_404(source_id)
    target = get_account_or_404(target_id)

    # Owner-scope: caller must own the source.
    require_owner_match(source["owner_id"])

    # Referential symmetry (priority 7): source TRADITIONAL, target ROTH, same owner.
    if source["account_type"] != "TRADITIONAL":
        raise_api(ERR_INVALID_CONVERSION_PAIR)
    if target["account_type"] != "ROTH":
        raise_api(ERR_INVALID_CONVERSION_PAIR)
    if source["owner_id"] != target["owner_id"]:
        raise_api(ERR_INVALID_CONVERSION_PAIR)

    # State: source must be ACTIVE.
    if source["status"] != "ACTIVE":
        raise_api(ERR_INVALID_STATE, "Source account is not ACTIVE.")

    # Sufficient balance
    if source["cash_balance_cents"] < gross:
        raise_api(ERR_INVALID_STATE, "Source account has insufficient cash_balance_cents for conversion.")

    now = db.now_utc()
    conv = {
        "id": db.new_id(),
        "source_account_id": source_id,
        "target_account_id": target_id,
        "gross_amount_cents": gross,
        "taxable_amount_cents": 0,
        "nontaxable_amount_cents": 0,
        "status": "INITIATED",
        "completed_at": None,
        "aggregate_basis": aggregate_basis,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.conversions[conv["id"]] = conv

    # Side effects: source -> CONVERSION_IN_PROGRESS
    source["status"] = "CONVERSION_IN_PROGRESS"
    source["updated_at"] = now
    source["version"] += 1

    return success_object(conversion_to_json(conv), status_code=201)


@bp.route("/<conv_id>", methods=["GET"])
def get_conversion(conv_id):
    parse_auth_headers()
    require_roles("PlanAdministrator", "AccountOwner", "IRSAuditor")
    conv = get_conversion_or_404(conv_id)
    if g.role == "AccountOwner":
        source = db.accounts.get(conv["source_account_id"])
        if source is None:
            from errors import ERR_NOT_FOUND
            raise_api(ERR_NOT_FOUND)
        require_owner_match(source["owner_id"])
    return success_object(conversion_to_json(conv))


@bp.route("", methods=["GET"])
def list_conversions():
    parse_auth_headers()
    require_roles("PlanAdministrator", "AccountOwner", "IRSAuditor")
    limit, offset = get_pagination_params()
    source_id = request.args.get("source_account_id")
    target_id = request.args.get("target_account_id")
    status = request.args.get("status")
    rows = list(db.conversions.values())
    if source_id is not None:
        rows = [c for c in rows if c["source_account_id"] == source_id]
    if target_id is not None:
        rows = [c for c in rows if c["target_account_id"] == target_id]
    if status is not None:
        if status not in CONVERSION_STATUSES:
            raise_api(ERR_INVALID_REQUEST, "status filter is not a recognized value.")
        rows = [c for c in rows if c["status"] == status]
    if g.role == "AccountOwner":
        owned_accounts = {a["id"] for a in db.accounts.values() if a["owner_id"] == g.user_id}
        rows = [c for c in rows if c["source_account_id"] in owned_accounts]
    page, total = paginate(rows, limit, offset)
    return success_array([conversion_to_json(c) for c in page], limit, offset, total)


@bp.route("/<conv_id>/complete", methods=["POST"])
def complete_conversion(conv_id):
    parse_auth_headers()
    require_roles("AccountOwner")
    conv = get_conversion_or_404(conv_id)
    source = get_account_or_404(conv["source_account_id"])
    target = get_account_or_404(conv["target_account_id"])
    require_owner_match(source["owner_id"])

    if conv["status"] != "INITIATED":
        raise_api(ERR_INVALID_STATE, "Conversion is not INITIATED.")

    body = get_json_body()
    expected = require_int(body, "expected_source_account_version")
    if expected != source["version"]:
        raise_api(ERR_STALE_VERSION)

    if source["status"] != "CONVERSION_IN_PROGRESS":
        raise_api(ERR_INVALID_STATE, "Source account is not CONVERSION_IN_PROGRESS.")
    if target["status"] != "ACTIVE":
        raise_api(ERR_INVALID_STATE, "Target account is not ACTIVE.")

    # Pro-rata split
    if conv.get("aggregate_basis", False):
        # Sum pretax/aftertax across all TRADITIONAL accounts of the owner.
        owner_id = source["owner_id"]
        pretax = sum(
            a["pretax_basis_cents"]
            for a in db.accounts.values()
            if a["owner_id"] == owner_id and a["account_type"] == "TRADITIONAL"
        )
        aftertax = sum(
            a["aftertax_basis_cents"]
            for a in db.accounts.values()
            if a["owner_id"] == owner_id and a["account_type"] == "TRADITIONAL"
        )
    else:
        pretax = source["pretax_basis_cents"]
        aftertax = source["aftertax_basis_cents"]
    taxable, nontaxable = backdoor_roth_pro_rata(conv["gross_amount_cents"], pretax, aftertax)

    now = db.now_utc()
    conv["taxable_amount_cents"] = taxable
    conv["nontaxable_amount_cents"] = nontaxable
    conv["status"] = "COMPLETED"
    conv["completed_at"] = now
    conv["updated_at"] = now
    conv["version"] += 1

    # Source account: decrement cash and bases proportional to split.
    source["cash_balance_cents"] -= conv["gross_amount_cents"]
    # Decrement bases proportional to taxable vs nontaxable shares — i.e.,
    # nontaxable comes from aftertax basis, taxable comes from pretax basis.
    source["pretax_basis_cents"] = max(0, source["pretax_basis_cents"] - taxable)
    source["aftertax_basis_cents"] = max(0, source["aftertax_basis_cents"] - nontaxable)
    source["status"] = "ACTIVE"
    source["updated_at"] = now
    source["version"] += 1

    # Target ROTH account: increment cash balance by gross.
    target["cash_balance_cents"] += conv["gross_amount_cents"]
    target["updated_at"] = now
    target["version"] += 1

    # Form 1099-R with code G
    f = {
        "id": db.new_id(),
        "distribution_id": None,
        "conversion_id": conv["id"],
        "tax_year": db.system_clock["current_tax_year"],
        "gross_distribution_cents": conv["gross_amount_cents"],
        "taxable_amount_cents": taxable,
        "federal_withholding_cents": 0,
        "distribution_code": "G",
        "ira_sep_simple_flag": True,
        "created_at": now,
    }
    db.forms_1099r[f["id"]] = f

    append_audit_event(
        owner_id=source["owner_id"],
        account_id=source["id"],
        event_kind="CONVERSION_COMPLETED",
        tax_year=db.system_clock["current_tax_year"],
        amount_cents=conv["gross_amount_cents"],
    )

    return success_object(conversion_to_json(conv))


@bp.route("/<conv_id>/reverse", methods=["POST"])
def reverse_conversion(conv_id):
    parse_auth_headers()
    require_roles("AccountOwner")
    conv = get_conversion_or_404(conv_id)
    source = get_account_or_404(conv["source_account_id"])
    require_owner_match(source["owner_id"])

    if conv["status"] != "INITIATED":
        raise_api(ERR_INVALID_STATE, "Conversion is not INITIATED.")

    body = get_json_body()
    expected = require_int(body, "expected_source_account_version")
    if expected != source["version"]:
        raise_api(ERR_STALE_VERSION)

    # No Form1099R yet generated for this conversion.
    for f in db.forms_1099r.values():
        if f["conversion_id"] == conv["id"]:
            raise_api(ERR_INVALID_STATE, "Form 1099-R already exists for this conversion.")

    now = db.now_utc()
    conv["status"] = "REVERSED"
    conv["updated_at"] = now
    conv["version"] += 1
    source["status"] = "ACTIVE"
    source["updated_at"] = now
    source["version"] += 1
    return success_object(conversion_to_json(conv))
