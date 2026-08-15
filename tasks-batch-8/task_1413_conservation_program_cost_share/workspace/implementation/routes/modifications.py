"""ContractModification: read, list, approve, reject (OCC-guarded)."""
from datetime import timedelta

from flask import Blueprint

import serializers
from db import STORE
from errors import ApiError
from helpers import (
    apply_filters, body, get_applicant, get_contract, get_item, get_modification,
    paginate, req_field, sorted_created, touch,
)
from middleware import ANY_ROLE, require_roles
from response import ok, ok_list
from services import calc, ledger

bp = Blueprint("modifications", __name__)

CANCELLABLE = ("PLANNED", "INSTALLED", "CERTIFICATION_FAILED")


def _check_adjudication(mod, data):
    """Shared gates for approve/reject: REQUESTED, contract MODIFICATION_PENDING,
    then the expected_contract_version OCC guard."""
    if mod["status"] != "REQUESTED":
        raise ApiError(
            "ERR_MODIFICATION_NOT_REQUESTED", 409,
            "the modification is not in REQUESTED",
        )
    contract = get_contract(mod["contract_id"])
    if contract["status"] != "MODIFICATION_PENDING":
        raise ApiError(
            "ERR_CONTRACT_NOT_MODIFIABLE", 409,
            "the contract is not under modification review",
        )
    expected = req_field(data, "expected_contract_version")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise ApiError("ERR_INVALID_REQUEST", 400, "expected_contract_version must be an integer")
    if expected != contract["version"]:
        raise ApiError(
            "ERR_STALE_CONTRACT_VERSION", 412,
            "expected_contract_version does not match the contract's current version",
        )
    return contract


@bp.get("/eqip/modifications/<mid>")
@require_roles(*ANY_ROLE)
def get_one_modification(mid, _uid, _role):
    return ok(serializers.modification(get_modification(mid)))


@bp.get("/eqip/modifications")
@require_roles(*ANY_ROLE)
def list_modifications(_uid, _role):
    items = apply_filters(
        sorted_created(STORE.modifications.values()),
        [("contract_id", "contract_id"), ("practice_item_id", "practice_item_id"),
         ("kind", "kind"), ("status", "status")],
    )
    page, meta = paginate(items)
    return ok_list([serializers.modification(m) for m in page], meta)


@bp.post("/eqip/modifications/<mid>/approve")
@require_roles("ProgramAdmin")
def approve_modification(mid, _uid, _role):
    mod = get_modification(mid)
    data = body()
    contract = _check_adjudication(mod, data)
    pool = STORE.pools.get(contract["pool_id"])

    if mod["kind"] == "EXTEND_DEADLINE":
        item = get_item(mod["practice_item_id"])
        if item["certification_status"] not in CANCELLABLE:
            raise ApiError(
                "ERR_ITEM_NOT_EXTENDABLE", 409,
                "EXTEND_DEADLINE requires item PLANNED, INSTALLED or CERTIFICATION_FAILED",
            )
        if STORE.clock > item["implementation_deadline"]:
            raise ApiError(
                "ERR_EXTENSION_WINDOW_CLOSED", 409,
                "the current implementation deadline has already passed",
            )
        if mod["new_deadline"] <= item["implementation_deadline"] or \
                mod["new_deadline"] > item["implementation_deadline"] + timedelta(days=365):
            raise ApiError(
                "ERR_EXTENSION_TOO_LONG", 422,
                "new_deadline must be after the current deadline and within +365 days",
            )
        item["implementation_deadline"] = mod["new_deadline"]
        touch(item)

    elif mod["kind"] == "ADD_PRACTICE":
        applicant_row = get_applicant(contract["applicant_id"])
        program = STORE.programs[contract["program_id"]]
        from routes.contracts import _make_item  # shared item builder
        # Compute the new scheduled amount first for the pool-fit gate.
        rate_row = calc.rate_for_code(contract["program_id"], mod["new_practice_code"])
        if rate_row is None:
            raise ApiError(
                "ERR_RATE_NOT_FOUND", 422,
                f"No payment schedule rate for {mod['new_practice_code']} in this program",
            )
        applicable = calc.applicable_rate_cents(rate_row, applicant_row)
        scheduled = calc.scheduled_amount_cents(mod["new_quantity"], applicable)
        if pool is not None and scheduled > ledger.pool_available(pool):
            raise ApiError(
                "ERR_POOL_INSUFFICIENT_FUNDS", 402,
                "the new practice's scheduled amount exceeds the pool's available balance",
            )
        _make_item(contract, mod["new_practice_code"], mod["new_quantity"],
                   mod["new_deadline"], applicant_row, program)
        if pool is not None:
            pool["obligated_cents"] += scheduled
            touch(pool)
        calc.recompute_contract_obligated(contract)

    elif mod["kind"] == "DROP_PRACTICE":
        item = get_item(mod["practice_item_id"])
        if item["certification_status"] in CANCELLABLE:
            ledger.cancel_item(item, pool, release=True)
        calc.recompute_contract_obligated(contract)

    mod["status"] = "APPROVED"
    touch(mod)
    contract["status"] = "OBLIGATED"
    touch(contract)
    return ok(serializers.modification(mod))


@bp.post("/eqip/modifications/<mid>/reject")
@require_roles("ProgramAdmin")
def reject_modification(mid, _uid, _role):
    mod = get_modification(mid)
    data = body()
    contract = _check_adjudication(mod, data)
    mod["status"] = "REJECTED"
    touch(mod)
    contract["status"] = "OBLIGATED"
    touch(contract)
    return ok(serializers.modification(mod))
