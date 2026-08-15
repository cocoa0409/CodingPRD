"""Supply-chain node endpoints (PRD §3.2): an append-only hop chain."""

from flask import Blueprint, request

from db import store
from errors import (
    not_found, unauthorized, invalid_request, ApiError,
    ERR_SUPPLY_CHAIN_NOT_TAIL, ERR_SUPPLY_CHAIN_TOO_DEEP,
)
from middleware import require_roles, ALL_ROLES, ROLE_PUBLISHER_MANAGER
from response import success_object, success_list, paginate
from util import get_body, req_str, opt_str
from services.core import (
    MAX_CHAIN_HOPS, MAX_CHAIN_FEE_BPS, base_record_light, serialize_node, _sorted,
)

bp = Blueprint("supply_chain", __name__)


@bp.route("/supply-chain-nodes", methods=["POST"])
def create_node():
    role, user_id = require_roles([ROLE_PUBLISHER_MANAGER])
    body = get_body()
    package_id = req_str(body, "package_id")
    seller_domain = req_str(body, "seller_domain")
    # fee_bps: type and negativity are stage-3; the 9000-bps ceiling is the
    # stage-13 capacity rule (ERR_SUPPLY_CHAIN_TOO_DEEP), checked below.
    fee_bps = body.get("fee_bps")
    if isinstance(fee_bps, bool) or not isinstance(fee_bps, int):
        raise invalid_request("fee_bps is required and must be an integer")
    if fee_bps < 0:
        raise invalid_request("fee_bps must be >= 0")
    parent_node_id = opt_str(body, "parent_node_id")
    # existence, left to right: package, then parent node
    pkg = store.packages.get(package_id)
    if pkg is None:
        raise not_found("InventoryPackage not found")
    parent = None
    if parent_node_id is not None:
        parent = store.nodes.get(parent_node_id)
        if parent is None:
            raise not_found("SupplyChainNode not found")
    # ownership (stage 6)
    if pkg["publisher_id"] != user_id:
        raise unauthorized("Package belongs to a different publisher")
    # tail integrity (stage 12): a named parent must be the current tail of
    # the same package; omitting the parent is only legal for the first hop
    package_nodes = [n for n in store.nodes.values() if n["package_id"] == package_id]
    if parent is not None:
        if parent["package_id"] != package_id or not parent["is_tail"]:
            raise ApiError(ERR_SUPPLY_CHAIN_NOT_TAIL, 409,
                           "parent_node_id is not the current tail of the same package")
    else:
        if package_nodes:
            raise ApiError(ERR_SUPPLY_CHAIN_NOT_TAIL, 409,
                           "parent_node_id must name the current tail of the package chain")
    # depth and per-hop fee capacity (stage 13)
    hop_index = parent["hop_index"] + 1 if parent is not None else 0
    if hop_index + 1 > MAX_CHAIN_HOPS or fee_bps > MAX_CHAIN_FEE_BPS:
        raise ApiError(ERR_SUPPLY_CHAIN_TOO_DEEP, 422,
                       "Chain would exceed 10 hops or fee_bps exceeds 9000")
    node = base_record_light()
    node.update({
        "package_id": package_id,
        "parent_node_id": parent_node_id,
        "seller_domain": seller_domain,
        "fee_bps": fee_bps,
        "hop_index": hop_index,
        "is_tail": True,
    })
    # the append atomically flips the parent's is_tail (nodes carry no
    # version — they are never mutated in any other way)
    if parent is not None:
        parent["is_tail"] = False
    store.nodes[node["id"]] = node
    return success_object(serialize_node(node), 201)


@bp.route("/supply-chain-nodes", methods=["GET"])
def list_nodes():
    require_roles(ALL_ROLES)
    package_id = request.args.get("package_id")
    parent_node_id = request.args.get("parent_node_id")
    items = list(store.nodes.values())
    if package_id is not None:
        items = [n for n in items if n["package_id"] == package_id]
    if parent_node_id is not None:
        items = [n for n in items if n["parent_node_id"] == parent_node_id]
    page, limit, offset, total = paginate(_sorted(items), request.args)
    return success_list([serialize_node(n) for n in page], limit, offset, total)


@bp.route("/supply-chain-nodes/<nodeId>", methods=["GET"])
def get_node(nodeId):
    require_roles(ALL_ROLES)
    n = store.nodes.get(nodeId)
    if n is None:
        raise not_found("SupplyChainNode not found")
    return success_object(serialize_node(n))
