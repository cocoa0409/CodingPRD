"""Benefit pool, ledger-entry, and partnership-disregard reads (PRD §3.12, §3.9)."""
from flask import Blueprint, request

from db import STORE
from middleware import authenticate, authorize
from response import object_response, array_response
from services import common, serialize, lookup, core

bp = Blueprint("benefit", __name__)


@bp.route("/policies/<rid>/benefit-pool", methods=["GET"])
def get_benefit_pool(rid):
    caller = authenticate()
    authorize(caller, ["Underwriter", "ClaimsExaminer", "Regulator", "Policyholder"])
    lookup.policy_or_404(rid)
    pool = core.pool_for_policy(rid)
    rows = [serialize.benefit_pool(pool)] if pool is not None else []
    page, limit, offset, total = common.paginate(rows)
    return array_response(page, limit, offset, total)


@bp.route("/policies/<rid>/ledger-entries", methods=["GET"])
def list_policy_ledger(rid):
    caller = authenticate()
    authorize(caller, ["Underwriter", "ClaimsExaminer", "Regulator"])
    lookup.policy_or_404(rid)
    records = [e for e in STORE.ledger_entries.values() if e["policy_id"] == rid]
    records = lookup.sorted_by_created(records)
    page, limit, offset, total = common.paginate(records)
    return array_response([serialize.ledger_entry(e) for e in page], limit, offset, total)


@bp.route("/ledger-entries/<rid>", methods=["GET"])
def get_ledger_entry(rid):
    caller = authenticate()
    authorize(caller, ["Underwriter", "ClaimsExaminer", "Regulator"])
    rec = lookup.ledger_entry_or_404(rid)
    return object_response(serialize.ledger_entry(rec), 200)


@bp.route("/ledger-entries", methods=["GET"])
def list_ledger_entries():
    caller = authenticate()
    authorize(caller, ["Underwriter", "ClaimsExaminer", "Regulator"])
    records = list(STORE.ledger_entries.values())
    policy_id = request.args.get("policy_id")
    claim_id = request.args.get("claim_id")
    if policy_id is not None:
        records = [e for e in records if e["policy_id"] == policy_id]
    if claim_id is not None:
        records = [e for e in records if e["claim_id"] == claim_id]
    records = lookup.sorted_by_created(records)
    page, limit, offset, total = common.paginate(records)
    return array_response([serialize.ledger_entry(e) for e in page], limit, offset, total)


@bp.route("/policies/<rid>/partnership-disregard", methods=["GET"])
def get_partnership_disregard(rid):
    caller = authenticate()
    authorize(caller, ["Underwriter", "Regulator", "Policyholder"])
    lookup.policy_or_404(rid)
    pd = core.partnership_for_policy(rid)
    rows = [serialize.partnership_disregard(pd)] if pd is not None else []
    page, limit, offset, total = common.paginate(rows)
    return array_response(page, limit, offset, total)
