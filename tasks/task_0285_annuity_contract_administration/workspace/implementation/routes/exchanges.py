"""Exchange1035 endpoints (PRD §3.10).

Cyclic revision loop (SUBMITTED <-> REVISION_REQUESTED), segregation of duties
(submitter X-User-ID != approver X-User-ID), and OCC on approve.
"""

from flask import Blueprint, request

import errors
import validation as v
from clock import iso8601
from db import store
from middleware import authenticate, authorize
from response import object_response, array_response
from services import contract as contract_svc
from services import lookups

bp = Blueprint("exchanges", __name__)

# 1035 list/detail visible only to ContractAdmin and ComplianceOfficer.
EXCHANGE_READ_ROLES = {"ContractAdmin", "ComplianceOfficer"}
DIRECTIONS = {"INBOUND", "OUTBOUND"}


def serialize(e):
    return {
        "id": e["id"],
        "direction": e["direction"],
        "source_contract_id": e["source_contract_id"],
        "target_contract_id": e["target_contract_id"],
        "external_carrier": e["external_carrier"],
        "transfer_amount_cents": e["transfer_amount_cents"],
        "cost_basis_cents": e["cost_basis_cents"],
        "revision_count": e["revision_count"],
        "status": e["status"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def _invalid_basis():
    return errors.ApiError(
        errors.ERR_INVALID_COST_BASIS,
        422,
        "cost_basis_cents must be between 0 and transfer_amount_cents.",
    )


@bp.post("/exchanges-1035")
def create_exchange():
    _, role = authenticate()
    authorize(role, {"ContractAdmin"})
    body = v.get_json_body()

    direction = v.require_enum(body, "direction", DIRECTIONS)
    transfer_amount = v.require_int(body, "transfer_amount_cents", minimum=1)
    cost_basis = v.require_int(body, "cost_basis_cents", minimum=0)
    source_contract_id = v.optional_string(body, "source_contract_id")
    target_contract_id = v.optional_string(body, "target_contract_id")
    external_carrier = v.optional_string(body, "external_carrier")

    # FK existence for provided contract references.
    if source_contract_id is not None:
        lookups.ref_contract(source_contract_id)
    if target_contract_id is not None:
        lookups.ref_contract(target_contract_id)

    # Basis integrity (0 .. transfer).
    if cost_basis > transfer_amount:
        raise _invalid_basis()

    now = store.clock.now()
    eid = store.new_id()
    exchange = {
        "id": eid,
        "direction": direction,
        "source_contract_id": source_contract_id,
        "target_contract_id": target_contract_id,
        "external_carrier": external_carrier,
        "transfer_amount_cents": transfer_amount,
        "cost_basis_cents": cost_basis,
        "revision_count": 0,
        "status": "DRAFT",
        "_submitter_user_id": None,
        "created_at": iso8601(now),
        "updated_at": iso8601(now),
        "version": 1,
        "_seq": store.next_seq(),
    }
    store.exchanges[eid] = exchange
    return object_response(serialize(exchange), 201, now)


@bp.get("/exchanges-1035")
def list_exchanges():
    _, role = authenticate()
    authorize(role, EXCHANGE_READ_ROLES)
    limit, offset = v.parse_pagination()
    status_filter = request.args.get("status")
    source_filter = request.args.get("source_contract_id")
    target_filter = request.args.get("target_contract_id")

    rows = lookups.sorted_by_creation(list(store.exchanges.values()))
    if status_filter is not None:
        rows = [e for e in rows if e["status"] == status_filter]
    if source_filter is not None:
        rows = [e for e in rows if e["source_contract_id"] == source_filter]
    if target_filter is not None:
        rows = [e for e in rows if e["target_contract_id"] == target_filter]
    page, total = lookups.paginate(rows, limit, offset)
    return array_response(
        [serialize(e) for e in page], total, limit, offset, store.clock.now()
    )


@bp.get("/exchanges-1035/<rid>")
def get_exchange(rid):
    _, role = authenticate()
    authorize(role, EXCHANGE_READ_ROLES)
    exchange = lookups.path_exchange(rid)
    return object_response(serialize(exchange), 200, store.clock.now())


@bp.post("/exchanges-1035/<rid>/submit")
def submit_exchange(rid):
    user_id, role = authenticate()
    authorize(role, {"ContractAdmin"})
    exchange = lookups.path_exchange(rid)

    if exchange["status"] not in ("DRAFT", "REVISION_REQUESTED"):
        raise errors.invalid_state("Exchange is not in a submittable state.")

    # Re-validate basis on submit.
    if exchange["cost_basis_cents"] > exchange["transfer_amount_cents"]:
        raise _invalid_basis()

    now = store.clock.now()
    from_revision = exchange["status"] == "REVISION_REQUESTED"
    exchange["status"] = "SUBMITTED"
    exchange["_submitter_user_id"] = user_id
    if from_revision:
        exchange["revision_count"] += 1
    exchange["version"] += 1
    exchange["updated_at"] = iso8601(now)
    return object_response(serialize(exchange), 200, now)


@bp.post("/exchanges-1035/<rid>/request-revision")
def request_revision(rid):
    _, role = authenticate()
    authorize(role, {"ComplianceOfficer"})
    exchange = lookups.path_exchange(rid)
    if exchange["status"] != "SUBMITTED":
        raise errors.invalid_state("Exchange is not SUBMITTED.")
    now = store.clock.now()
    exchange["status"] = "REVISION_REQUESTED"
    exchange["version"] += 1
    exchange["updated_at"] = iso8601(now)
    return object_response(serialize(exchange), 200, now)


@bp.post("/exchanges-1035/<rid>/approve")
def approve_exchange(rid):
    user_id, role = authenticate()
    authorize(role, {"ComplianceOfficer"})
    exchange = lookups.path_exchange(rid)
    body = v.get_json_body()
    expected_version = v.require_int(body, "expected_exchange_version")

    # OCC (priority 6) before state legality (priority 7).
    if expected_version != exchange["version"]:
        raise errors.ApiError(
            errors.ERR_STALE_EXCHANGE_VERSION, 412, "Stale exchange version."
        )

    if exchange["status"] != "SUBMITTED":
        raise errors.invalid_state("Exchange is not SUBMITTED.")

    # Segregation of duties (priority 8).
    if user_id == exchange["_submitter_user_id"]:
        raise errors.ApiError(
            errors.ERR_SEGREGATION_OF_DUTIES,
            409,
            "The approver must differ from the submitter.",
        )

    now = store.clock.now()
    exchange["status"] = "APPROVED"
    exchange["version"] += 1
    exchange["updated_at"] = iso8601(now)
    return object_response(serialize(exchange), 200, now)


@bp.post("/exchanges-1035/<rid>/reject")
def reject_exchange(rid):
    _, role = authenticate()
    authorize(role, {"ComplianceOfficer"})
    exchange = lookups.path_exchange(rid)
    if exchange["status"] != "SUBMITTED":
        raise errors.invalid_state("Exchange is not SUBMITTED.")
    now = store.clock.now()
    exchange["status"] = "REJECTED"
    exchange["version"] += 1
    exchange["updated_at"] = iso8601(now)
    return object_response(serialize(exchange), 200, now)


@bp.post("/exchanges-1035/<rid>/settle")
def settle_exchange(rid):
    _, role = authenticate()
    authorize(role, {"ComplianceOfficer"})
    exchange = lookups.path_exchange(rid)
    if exchange["status"] != "APPROVED":
        raise errors.invalid_state("Exchange is not APPROVED.")

    if exchange["direction"] == "INBOUND":
        # Require a CLEARED premium on the target referencing this exchange.
        target_id = exchange["target_contract_id"]
        ok = any(
            p["source_exchange_id"] == exchange["id"]
            and p["contract_id"] == target_id
            and p["status"] == "CLEARED"
            for p in store.premiums.values()
        )
        if not ok:
            raise errors.invalid_state(
                "INBOUND settle requires a CLEARED premium referencing this exchange."
            )

    now = store.clock.now()

    if exchange["direction"] == "OUTBOUND":
        # Trigger a tax-free full surrender on the source contract (charge waived).
        source = store.contracts.get(exchange["source_contract_id"])
        if source is not None and source["status"] == "ACTIVE":
            source["status"] = "SURRENDERED"
            contract_svc.liquidate_allocations(source)
            contract_svc.bump(source)

    exchange["status"] = "SETTLED"
    exchange["version"] += 1
    exchange["updated_at"] = iso8601(now)
    return object_response(serialize(exchange), 200, now)
