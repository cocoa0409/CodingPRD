"""Supply chain nodes: registration, harvest declarations, reads."""
from decimal import Decimal

from flask import Blueprint

import common as C
import domain as D
import store as S
import validators as V
from common import dec, new_id, vol
from errors import ApiError
from response import created, listing, ok
from store import ordered, touch_once

bp = Blueprint("nodes", __name__)


@bp.post("/supply-chain-nodes")
def register_node():
    from auth import authorize
    user_id, role = authorize("CertificationOfficer", "ProducerRepresentative",
                              "BrandLicensee")
    data = V.body()
    holder_id = V.req_id(data, "holder_id")
    node_role = V.req_enum(data, "node_role", C.NODE_ROLES)
    traceability_mode = V.req_enum(data, "traceability_mode", C.TRACEABILITY_MODES)
    upstream_node_id = V.opt_id(data, "upstream_node_id")
    conversion_ratio = V.opt_number(data, "conversion_ratio", 3,
                                    default=Decimal("1.000"),
                                    minimum="0.001", maximum="1.000")

    holder = S.holder_or_404(holder_id)
    upstream = S.node_or_404(upstream_node_id) if upstream_node_id else None

    if role in ("ProducerRepresentative", "BrandLicensee") and user_id != holder_id:
        raise ApiError("ERR_HOLDER_OWNERSHIP_MISMATCH",
                       "X-User-ID does not own this certificate holder")

    if (upstream is not None
            and traceability_mode == "PHYSICAL"
            and upstream["traceability_mode"] == "MASS_BALANCE"):
        raise ApiError("ERR_TRACEABILITY_MODE_MISMATCH",
                       "a PHYSICAL node may not sit downstream of a MASS_BALANCE node")

    chain_depth = 0 if upstream is None else upstream["chain_depth"] + 1
    if chain_depth > C.MAX_CHAIN_DEPTH:
        raise ApiError("ERR_SUPPLY_CHAIN_DEPTH_EXCEEDED",
                       "chain_depth %d exceeds the ceiling of %d"
                       % (chain_depth, C.MAX_CHAIN_DEPTH))

    status = ("ACTIVE" if holder["certificate_status"] in ("CERTIFIED", "TRANSITIONING")
              else "REGISTERED")
    node = {
        "id": new_id(),
        "holder_id": holder_id,
        "upstream_node_id": upstream_node_id,
        "node_role": node_role,
        "traceability_mode": traceability_mode,
        "status": status,
        "chain_depth": chain_depth,
        "conversion_ratio": conversion_ratio,
        "certified_input_kg": vol(0),
        "reserved_output_kg": vol(0),
        "claimed_output_kg": vol(0),
        "available_credit_kg": vol(0),
    }
    S.stamp_new(node)
    S.nodes[node["id"]] = node
    return created(node)


@bp.post("/supply-chain-nodes/<node_id>/harvest-declarations")
def declare_harvest(node_id):
    from auth import authorize
    user_id, role = authorize("ProducerRepresentative")
    data = V.body()
    certified_volume_kg = V.req_number(data, "certified_volume_kg", 3, minimum=0)
    V.req_str(data, "harvest_season", 80)

    node = S.node_or_404(node_id)
    if user_id != node["holder_id"]:
        raise ApiError("ERR_HOLDER_OWNERSHIP_MISMATCH",
                       "X-User-ID does not own this node's certificate holder")
    if node["status"] != "ACTIVE":
        raise ApiError("ERR_NODE_NOT_ACTIVE",
                       "node status %s does not accept harvest declarations"
                       % node["status"])

    holder = S.holder_or_404(node["holder_id"])
    D.add_certified_input(node, certified_volume_kg)
    touch_once(node)
    holder["annual_certified_volume_kg"] = vol(
        dec(holder["annual_certified_volume_kg"]) + certified_volume_kg)
    touch_once(holder)
    return created(node)


@bp.get("/supply-chain-nodes")
def list_nodes():
    from auth import authorize
    authorize("CertificationOfficer", "Auditor", "ProducerRepresentative",
              "BrandLicensee")
    holder_id = V.str_filter("holder_id")
    upstream_node_id = V.str_filter("upstream_node_id")
    status = V.enum_filter("status", C.NODE_STATUSES)
    traceability_mode = V.enum_filter("traceability_mode", C.TRACEABILITY_MODES)
    node_role = V.enum_filter("node_role", C.NODE_ROLES)

    rows = ordered(list(S.nodes.values()))
    if holder_id:
        rows = [r for r in rows if r["holder_id"] == holder_id]
    if upstream_node_id:
        rows = [r for r in rows if r["upstream_node_id"] == upstream_node_id]
    if status:
        rows = [r for r in rows if r["status"] == status]
    if traceability_mode:
        rows = [r for r in rows if r["traceability_mode"] == traceability_mode]
    if node_role:
        rows = [r for r in rows if r["node_role"] == node_role]
    page, limit, offset, total = V.paginate(rows)
    return listing(page, limit, offset, total)


@bp.get("/supply-chain-nodes/<node_id>")
def read_node(node_id):
    from auth import authorize
    authorize("CertificationOfficer", "Auditor", "ProducerRepresentative",
              "BrandLicensee")
    return ok(S.node_or_404(node_id))
