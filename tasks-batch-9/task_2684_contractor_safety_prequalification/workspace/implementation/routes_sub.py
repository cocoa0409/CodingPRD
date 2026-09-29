"""Subcontractor edges: DAG maintenance, depth limits and flow-down coverage."""
from flask import Blueprint

import auth
import calc
import derive
import response
import serialize
import store
import validators as V
from errors import fail
from store import S, insert, touch

bp = Blueprint("sub", __name__)


def _forward_reachable(prequalification_id, start_contractor_id):
    """Contractors reachable by following ACTIVE edges forward from start."""
    edges = derive.active_links(prequalification_id)
    seen = set()
    frontier = [start_contractor_id]
    while frontier:
        current = frontier.pop()
        for edge in edges:
            if edge["parent_contractor_id"] == current and edge["child_contractor_id"] not in seen:
                seen.add(edge["child_contractor_id"])
                frontier.append(edge["child_contractor_id"])
    return seen


@bp.route("/subcontractor-links", methods=["POST"])
def create_link():
    user_id, role = auth.authenticate([auth.ROLE_CONTRACTOR_ADMIN])
    body = V.parse_body(
        [
            ("parent_contractor_id", "string", True),
            ("child_contractor_id", "string", True),
            ("prequalification_id", "string", True),
            ("scope_of_work", "array", True),
        ]
    )
    scope_of_work = V.check_subset("scope_of_work", body["scope_of_work"], calc.TRADE_CODES)

    parent = V.get_contractor(body["parent_contractor_id"])
    child = V.get_contractor(body["child_contractor_id"])
    preq = V.get_prequalification(body["prequalification_id"])

    if role == auth.ROLE_CONTRACTOR_ADMIN and user_id != preq["contractor_id"]:
        fail(
            "ERR_NOT_RESOURCE_OWNER",
            "Only the prime contractor of the prequalification may create an edge.",
        )

    if not set(scope_of_work).issubset(set(child["scope_of_work"])):
        fail("ERR_INVALID_FIELD_VALUE", "scope_of_work must be a subset of the child's trades.")

    prime = S.contractors[preq["contractor_id"]]
    client = S.clients[preq["client_id"]]
    if prime["status"] != "ACTIVE":
        fail("ERR_CONTRACTOR_NOT_ACTIVE", "The acting contractor is not ACTIVE.")
    if preq["status"] not in ("APPROVED", "CONDITIONAL"):
        fail("ERR_PREQUAL_NOT_ACTIVE", "The prime prequalification is not in active standing.")

    if parent["id"] == child["id"]:
        fail("ERR_SUBCONTRACTOR_CYCLE", "A contractor may not subcontract to itself.")
    if parent["id"] in _forward_reachable(preq["id"], child["id"]):
        fail("ERR_SUBCONTRACTOR_CYCLE", "The proposed edge would close a loop.")
    connected = parent["id"] == preq["contractor_id"] or any(
        edge["child_contractor_id"] == parent["id"] for edge in derive.active_links(preq["id"])
    )
    if not connected:
        fail("ERR_SUBCONTRACTOR_CYCLE", "The parent is not connected to the prime.")

    depth = derive.link_depth(preq["id"], parent["id"], preq["contractor_id"])
    if depth is None or depth > client["cascade_depth_limit"]:
        fail("ERR_CASCADE_DEPTH_EXCEEDED", "The computed depth exceeds the client's limit.")

    flow_down_ok = False
    for cert in derive.live_certificates(child["id"], "GL"):
        if cert["each_occurrence_limit"] >= calc.FLOW_DOWN_GL_OCCURRENCE_FLOOR:
            flow_down_ok = True
            break
    if not flow_down_ok:
        fail(
            "ERR_COVERAGE_LIMIT_INSUFFICIENT",
            "The child lacks adequate flow-down general-liability coverage.",
        )

    row = store.base_row()
    row.update(
        {
            "parent_contractor_id": parent["id"],
            "child_contractor_id": child["id"],
            "prequalification_id": preq["id"],
            "scope_of_work": scope_of_work,
            "depth": depth,
            "flow_down_status": "PENDING",
            "status": "ACTIVE",
        }
    )
    insert(S.subcontractor_links, row)
    row["flow_down_status"] = derive.flow_down_status(row)
    return response.created(serialize.subcontractor_link(row))


@bp.route("/subcontractor-links/<link_id>/terminate", methods=["POST"])
def terminate_link(link_id):
    user_id, role = auth.authenticate(
        [auth.ROLE_CONTRACTOR_ADMIN, auth.ROLE_CLIENT_SAFETY_MANAGER]
    )
    V.no_body()
    row = V.get_leaf(S.subcontractor_links, link_id)
    preq = S.prequalifications[row["prequalification_id"]]
    auth.check_owner_any_contractor(
        role,
        user_id,
        [preq["contractor_id"], row["parent_contractor_id"]],
        client_id=preq["client_id"],
    )

    if row["status"] != "ACTIVE":
        fail("ERR_TRANSITION_NOT_ALLOWED", "Only an ACTIVE edge may be terminated.")
    for edge in derive.active_links(preq["id"]):
        if edge["parent_contractor_id"] == row["child_contractor_id"]:
            fail(
                "ERR_TRANSITION_NOT_ALLOWED",
                "A middle tier may not be cut out from under a tier below it.",
            )

    descendants = []
    reachable = _forward_reachable(preq["id"], row["child_contractor_id"])
    for edge in derive.active_links(preq["id"]):
        if edge["id"] == row["id"]:
            continue
        if edge["parent_contractor_id"] in reachable or (
            edge["parent_contractor_id"] == row["child_contractor_id"]
        ):
            descendants.append(edge)

    row["status"] = "TERMINATED"
    touch(row)
    descendants.sort(key=lambda r: (r["depth"], r["created_at"], r["_seq"]))
    for edge in descendants:
        edge["status"] = "TERMINATED"
        touch(edge)
    return response.ok(serialize.subcontractor_link(row))
