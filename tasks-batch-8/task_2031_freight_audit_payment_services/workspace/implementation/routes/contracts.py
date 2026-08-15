"""RateContract endpoints: draft, activation with OCC + supersede cascade."""

from flask import request

from db import STORE, create_entity, touch, public, sort_default, now_iso
from errors import (ApiError, ERR_INVALID_STATE, ERR_STALE_VERSION,
                    ERR_CONTRACT_WINDOW_INVALID, ERR_CONTRACT_WINDOW_OVERLAP,
                    ERR_WEIGHT_BREAK_INVALID, ERR_NOT_FOUND,
                    ERR_INVALID_REQUEST)
from middleware import (authenticate, require_roles, guard_read_scope,
                        in_read_scope, require_client_active, resolve,
                        READ_ROLES)
from response import success_object, success_list
from services import (check_contract_overlap, check_weight_breaks,
                      supersede_cascade)
from validate import get_body, check_shape, parse_pagination


def serialize_contract(contract):
    return public(contract)


def _occ_expected_version(body, field, current):
    if field not in body or not isinstance(body[field], int) \
            or isinstance(body[field], bool):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "Missing or invalid field: %s" % field)
    if body[field] != current:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected version does not match the current version")


def register(app):

    @app.route("/fap/carriers/<carrier_id>/rate-contracts", methods=["POST"])
    def create_contract(carrier_id):
        uid, role = authenticate()
        require_roles(role, {"FapAdmin"})
        carrier = resolve(STORE.carriers, carrier_id)
        body = get_body(allow_empty=False)
        # Body FK existence (stage 3): supersedes_contract_id must exist and
        # belong to the same client.
        supersedes_id = body.get("supersedes_contract_id")
        if supersedes_id is not None:
            target = STORE.contracts.get(supersedes_id)
            if target is None or target["client_id"] != carrier["client_id"]:
                raise ApiError(ERR_NOT_FOUND, 404,
                               "Referenced supersedes_contract_id does not exist")
        require_client_active(STORE.clients.get(carrier["client_id"]))
        check_shape(body, {
            "name": {"kind": "string", "required": True},
            "currency": {"kind": "string", "required": True},
            "lanes": {"kind": "array", "required": True},
            "effective_from": {"kind": "date", "required": True},
            "effective_to": {"kind": "date", "required": True},
            "supersedes_contract_id": {"kind": "string", "required": False},
        })
        if not (body["effective_from"] < body["effective_to"]):
            raise ApiError(ERR_CONTRACT_WINDOW_INVALID, 422,
                           "effective_from >= effective_to")
        contract = create_entity(STORE.contracts, {
            "client_id": carrier["client_id"],
            "carrier_id": carrier_id,
            "name": body["name"],
            "currency": body["currency"],
            "lanes": body["lanes"],
            "effective_from": body["effective_from"],
            "effective_to": body["effective_to"],
            "supersedes_contract_id": supersedes_id,
            "status": "DRAFT",
            "activated_at": None,
        })
        return success_object(serialize_contract(contract), status=201)

    @app.route("/fap/rate-contracts/<contract_id>", methods=["GET"])
    def get_contract(contract_id):
        uid, role = authenticate()
        require_roles(role, READ_ROLES)
        contract = guard_read_scope(role, uid, "contract",
                                    STORE.contracts.get(contract_id))
        return success_object(serialize_contract(contract))

    @app.route("/fap/rate-contracts", methods=["GET"])
    def list_contracts():
        uid, role = authenticate()
        require_roles(role, READ_ROLES)
        limit, offset = parse_pagination()
        rows = list(STORE.contracts.values())
        rows = [c for c in rows if in_read_scope(role, uid, "contract", c)]
        for param in ("client_id", "carrier_id", "supersedes_contract_id", "status"):
            value = request.args.get(param)
            if value is not None:
                rows = [c for c in rows if str(c.get(param)) == value]
        rows = sort_default(rows)
        total = len(rows)
        page = rows[offset:offset + limit]
        return success_list([serialize_contract(c) for c in page], limit, offset, total)

    @app.route("/fap/rate-contracts/<contract_id>/activate", methods=["POST"])
    def activate_contract(contract_id):
        uid, role = authenticate()
        require_roles(role, {"FapAdmin"})
        contract = resolve(STORE.contracts, contract_id)
        body = get_body(allow_empty=False)
        # Stage 4: optimistic concurrency on expected_rate_contract_version.
        _occ_expected_version(body, "expected_rate_contract_version",
                              contract["version"])
        # Stage 5: client lifecycle gate.
        client = STORE.clients.get(contract["client_id"])
        require_client_active(client)
        # Stage 6: request shape, then state legality.
        check_shape(body, {
            "expected_rate_contract_version": {"kind": "integer", "required": True},
        })
        if contract["status"] != "DRAFT":
            raise ApiError(ERR_INVALID_STATE, 409,
                           "Contract cannot be activated from %s" % contract["status"])
        # Stage 8: temporal — window sanity, then overlap.
        if not (contract["effective_from"] < contract["effective_to"]):
            raise ApiError(ERR_CONTRACT_WINDOW_INVALID, 422,
                           "effective_from >= effective_to")
        if check_contract_overlap(contract) is not None:
            raise ApiError(ERR_CONTRACT_WINDOW_OVERLAP, 409,
                           "Activating contract's window intersects another ACTIVE contract")
        # Stage 9: structural — weight-break ordering.
        if not check_weight_breaks(contract):
            raise ApiError(ERR_WEIGHT_BREAK_INVALID, 422,
                           "Lane weight_breaks not strictly ascending by min_kg")
        contract["status"] = "ACTIVE"
        contract["activated_at"] = now_iso()
        touch(contract)
        supersede_cascade(contract, client)
        return success_object(serialize_contract(contract))

    @app.route("/fap/rate-contracts/<contract_id>/discard", methods=["POST"])
    def discard_contract(contract_id):
        uid, role = authenticate()
        require_roles(role, {"FapAdmin"})
        contract = resolve(STORE.contracts, contract_id)
        require_client_active(STORE.clients.get(contract["client_id"]))
        body = get_body()
        check_shape(body, {})
        if contract["status"] != "DRAFT":
            raise ApiError(ERR_INVALID_STATE, 409,
                           "Contract cannot be discarded from %s" % contract["status"])
        contract["status"] = "DISCARDED"
        touch(contract)
        return success_object(serialize_contract(contract))
