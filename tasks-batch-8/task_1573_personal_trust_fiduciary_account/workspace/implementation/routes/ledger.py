"""LedgerEntry endpoints: manual RECEIPT/ADJUSTMENT posting; append-only guard."""

from flask import Blueprint, request

import db
from errors import (ApiError, ERR_VALIDATION, ERR_TRUST_NOT_ACTIVE,
                    ERR_RESOURCE_NOT_FOUND, ERR_LEDGER_IMMUTABLE)
from middleware import authenticate, require_role
from response import ok, ok_list
from serialize import ledger_entry_json
from services import workflow, calc
from services.workflow import find_or_404
from validation import get_body, validate, parse_pagination

bp = Blueprint("ledger", __name__)

ENTRY_KINDS = {"RECEIPT", "DISBURSEMENT", "FEE", "DISTRIBUTION", "TAX_PAYMENT",
               "INVESTMENT_PURCHASE", "INVESTMENT_SALE", "ADJUSTMENT"}
BUCKETS = {"INCOME", "PRINCIPAL"}
READ_ROLES = {"TrustOfficer", "TrustExecutive", "TrustOperationsOfficer",
              "TaxSpecialist"}


@bp.route("/trusts/ledger-entries", methods=["POST"])
def post_entry():
    _, role = authenticate()
    data = get_body()
    v = validate(data, [
        ("trust_id", "str", True),
        ("entry_kind", "str", True, ENTRY_KINDS),
        ("amount_cents", "int", True),
        ("value_date", "date", True),
        ("receipt_type", "str", False, calc.RECEIPT_TYPES),
        ("bucket", "str", False, BUCKETS),
        ("description", "str", False),
    ])
    kind = v["entry_kind"]
    if kind == "RECEIPT":
        if v["amount_cents"] <= 0:
            raise ApiError(ERR_VALIDATION, 400, "Receipt amount must be positive")
        if v.get("receipt_type") is None:
            raise ApiError(ERR_VALIDATION, 400,
                           "receipt_type is required for RECEIPT entries")
    elif kind == "ADJUSTMENT":
        if v["amount_cents"] == 0:
            raise ApiError(ERR_VALIDATION, 400, "Adjustment amount must be non-zero")
        if v.get("bucket") is None:
            raise ApiError(ERR_VALIDATION, 400,
                           "bucket is required for ADJUSTMENT entries")
    else:
        raise ApiError(ERR_VALIDATION, 400,
                       "Only RECEIPT and ADJUSTMENT entries may be posted manually")
    require_role(role, {"TrustOperationsOfficer"})
    trust = db.trusts.get(v["trust_id"])
    if trust is None:
        raise ApiError(ERR_RESOURCE_NOT_FOUND, 404,
                       "Trust not found: %s" % v["trust_id"])
    if trust["status"] not in ("ACTIVE", "TERMINATING"):
        raise ApiError(ERR_TRUST_NOT_ACTIVE, 409,
                       "Trust must be ACTIVE or TERMINATING to post ledger entries")
    created = []
    if kind == "RECEIPT":
        for bucket, amount in calc.classify_receipt(v["receipt_type"],
                                                    v["amount_cents"]):
            e = workflow.append_ledger(
                trust["id"], "RECEIPT", bucket, amount, v["value_date"],
                description=v.get("description"), receipt_type=v["receipt_type"],
                source_entity_type="MANUAL", source_entity_id=None)
            created.append(e)
    else:
        e = workflow.append_ledger(
            trust["id"], "ADJUSTMENT", v["bucket"], v["amount_cents"],
            v["value_date"], description=v.get("description"),
            source_entity_type="MANUAL", source_entity_id=None)
        created.append(e)
    workflow.bump_trust(trust)
    return ok([ledger_entry_json(e) for e in created], status=201,
              response_type="array")


@bp.route("/trusts/ledger-entries", methods=["GET"])
def list_entries():
    _, role = authenticate()
    limit, offset = parse_pagination()
    require_role(role, READ_ROLES)
    filters = []
    for param in ("trust_id", "bucket", "entry_kind"):
        val = request.args.get(param)
        if val is not None:
            filters.append((param, val))
    items, total = workflow.list_page(db.ledger_entries, filters,
                                      ledger_entry_json, limit, offset)
    return ok_list(items, limit, offset, total)


@bp.route("/trusts/ledger-entries/<eid>", methods=["GET"])
def get_entry(eid):
    _, role = authenticate()
    require_role(role, READ_ROLES)
    e = find_or_404(db.ledger_entries, eid, "LedgerEntry")
    return ok(ledger_entry_json(e))


@bp.route("/trusts/ledger-entries/<eid>", methods=["PUT", "PATCH", "DELETE"])
def modify_entry(eid):
    """The ledger is append-only: modification is always rejected (405)."""
    _, role = authenticate()
    require_role(role, {"TrustOperationsOfficer"})
    raise ApiError(ERR_LEDGER_IMMUTABLE, 405,
                   "Ledger entries are append-only and cannot be modified")
