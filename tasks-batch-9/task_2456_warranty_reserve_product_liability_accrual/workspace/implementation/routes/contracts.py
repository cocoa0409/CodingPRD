"""ServiceContract endpoints — the extended-service-contract revenue ledger."""

from flask import Blueprint

import lookups
import store
from auth import authenticate
from errors import fail
from response import list_response, object_response
from serialize import dump, dump_many
from services import calc
from validation import Field, no_body, paginate, pagination, query_filter, validate_body

bp = Blueprint("contracts", __name__)

READ_ROLES = ("WarrantyAnalyst", "ReserveController", "Actuary")
RECOGNITION_METHODS = ("STRAIGHT_LINE", "CLAIMS_PATTERN")


@bp.post("/warranty/service-contracts")
def create_contract():
    authenticate(("WarrantyAnalyst",))
    values, _ = validate_body(
        [
            Field("family_id", "id"),
            Field("contract_number", "str"),
            Field("sold_date", "date"),
            Field("term_months", "int", minimum=1),
            Field("total_contract_price_cents", "int", minimum=1),
            Field("recognition_method", "enum", enum=RECOGNITION_METHODS),
        ]
    )
    family = lookups.require_family(values["family_id"])
    for existing in store.all_rows("service_contracts"):
        if existing["contract_number"] == values["contract_number"]:
            fail("ERR_DUPLICATE_CODE")
    if values["sold_date"] < family["launch_date"]:
        fail("ERR_CONTRACT_PRECEDES_LAUNCH")

    row = store.insert(
        "service_contracts",
        {
            "_kind": "ServiceContract",
            "family_id": values["family_id"],
            "contract_number": values["contract_number"],
            "sold_date": values["sold_date"],
            "term_months": values["term_months"],
            "total_contract_price_cents": values["total_contract_price_cents"],
            "recognition_method": values["recognition_method"],
            "status": "ACTIVE",
            "months_elapsed": 0,
            "recognized_revenue_cents": 0,
            "deferred_revenue_cents": 0,
            "refunded_revenue_cents": 0,
            "cancelled_at": None,
        },
    )
    calc.apply_contract_recognition(row)
    if row["months_elapsed"] >= row["term_months"]:
        row["status"] = "EXPIRED"
        row["recognized_revenue_cents"] = row["total_contract_price_cents"]
        row["deferred_revenue_cents"] = 0
    return object_response(dump(row), 201)


@bp.get("/warranty/service-contracts/<contract_id>")
def read_contract(contract_id):
    authenticate(READ_ROLES)
    return object_response(dump(lookups.require("service_contracts", contract_id)))


@bp.get("/warranty/service-contracts")
def list_contracts():
    authenticate(READ_ROLES)
    limit, offset = pagination()
    rows = store.all_rows("service_contracts")
    family_id = query_filter("family_id")
    if family_id is not None:
        rows = [r for r in rows if r["family_id"] == family_id]
    status = query_filter("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return list_response(dump_many(paginate(rows, limit, offset)), limit, offset, len(rows))


@bp.post("/warranty/service-contracts/<contract_id>/cancel")
def cancel_contract(contract_id):
    authenticate(("WarrantyAnalyst",))
    contract = lookups.require("service_contracts", contract_id)
    no_body()
    if contract["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE_TRANSITION")

    # Recognition is re-evaluated at the current logical clock immediately before the
    # transition, and the refund is exactly the unearned balance at that instant.
    calc.apply_contract_recognition(contract)
    contract["refunded_revenue_cents"] = contract["deferred_revenue_cents"]
    contract["deferred_revenue_cents"] = 0
    contract["status"] = "CANCELLED"
    contract["cancelled_at"] = store.logical_now_iso()
    store.touch(contract)
    return object_response(dump(contract))
