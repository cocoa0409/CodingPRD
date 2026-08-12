"""Flat filtered listings: billing cycles and cash-value ledger entries."""
from flask import Blueprint, request

import domain
import errors
from db import store
from middleware import require_auth, parse_pagination, ALL_ROLES
from response import ok_object, ok_list
from routes.policies import get_policy_or_404, _paged

bp = Blueprint("listings", __name__)


@bp.route("/premium-billing-cycles", methods=["GET"])
def list_all_cycles():
    require_auth(ALL_ROLES)
    records = list(store.billing_cycles.values())
    policy_id = request.args.get("policy_id")
    if policy_id is not None:
        records = [c for c in records if c["policy_id"] == policy_id]
    limit, offset = parse_pagination()
    ordered = domain.sorted_by_creation(records)
    return ok_list([domain.serialize_cycle(c) for c in ordered[offset:offset + limit]],
                   limit, offset, len(ordered))


@bp.route("/premium-billing-cycles/<row_id>", methods=["GET"])
def get_cycle_flat(row_id):
    require_auth(ALL_ROLES)
    row = store.billing_cycles.get(row_id)
    if row is None:
        raise errors.not_found(errors.ERR_CYCLE_NOT_FOUND, "billing cycle")
    return ok_object(domain.serialize_cycle(row))


@bp.route("/cash-value-ledger-entries", methods=["GET"])
def list_all_ledger_entries():
    require_auth(ALL_ROLES)
    records = list(store.ledger_entries.values())
    policy_id = request.args.get("policy_id")
    if policy_id is not None:
        records = [e for e in records if e["policy_id"] == policy_id]
    return _paged(records, domain.serialize_ledger_entry)


@bp.route("/cash-value-ledger-entries/<row_id>", methods=["GET"])
def get_ledger_entry_flat(row_id):
    require_auth(ALL_ROLES)
    row = store.ledger_entries.get(row_id)
    if row is None:
        raise errors.not_found(errors.ERR_NOT_FOUND, "cash value ledger entry")
    return ok_object(domain.serialize_ledger_entry(row))


@bp.route("/policies/<policy_id>/cash-value-ledger", methods=["GET"])
def list_policy_ledger(policy_id):
    require_auth(ALL_ROLES)
    policy = get_policy_or_404(policy_id)
    # Strictly chronological: created_at ASC, ties broken by creation order
    records = [e for e in store.ledger_entries.values() if e["policy_id"] == policy["id"]]
    return _paged(records, domain.serialize_ledger_entry)
