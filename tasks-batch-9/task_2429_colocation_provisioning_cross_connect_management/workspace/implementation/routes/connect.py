"""Patch-panel ports and the cross-connect order lifecycle (PRD §3.5)."""

from datetime import timedelta

from flask import Blueprint

import refs
from auth import authorize
from billing import cross_connect_decommission_credit
from errors import ApiError
from response import created, ok, ok_list, paginate, pagination, serialize
from rollups import recompute_contract
from store import (
    CC_MEDIA_MRC_USD,
    CC_STATUSES,
    MAX_ROUTE_REVISIONS,
    MEDIA_TYPES,
    OPERATIONAL_CABINET_STATUSES,
    PORT_QUARANTINE_HOURS,
    base_row,
    now,
    store,
    touch,
)
from util import q2
from validate import (
    json_body,
    opt_id,
    qfilter,
    req_enum,
    req_int,
    req_string,
    req_string_list,
)

bp = Blueprint("connect", __name__)

PORT_ROLES = ("FacilityManager", "ProvisioningEngineer", "CustomerAdmin")
CC_READ_ROLES = ("ProvisioningEngineer", "FacilityManager", "BillingOperator", "CustomerAdmin")
HELD_PORT_STATUSES = ("RESERVED", "ASSIGNED")
ABORTABLE = ("SUBMITTED", "ROUTE_PROPOSED", "CHANGES_REQUESTED", "APPROVED")
CAP_COUNTED = ("SUBMITTED", "ROUTE_PROPOSED", "CHANGES_REQUESTED", "APPROVED", "INSTALLED", "ACTIVE")


# --------------------------------------------------------------------------
# Patch panel ports
# --------------------------------------------------------------------------

@bp.route("/patch-panel-ports", methods=["POST"])
def create_port():
    authorize("FacilityManager", "ProvisioningEngineer")
    body = json_body()
    refs.body_fk(body, "row_id", refs.ROW)

    row_id = req_string(body, "row_id")
    panel_code = req_string(body, "panel_code")
    port_number = req_int(body, "port_number", minimum=1)
    media_type = req_enum(body, "media_type", MEDIA_TYPES)

    for existing in store.ports.values():
        if (
            existing["row_id"] == row_id
            and existing["panel_code"] == panel_code
            and existing["port_number"] == port_number
        ):
            raise ApiError(
                "ERR_INVALID_REQUEST", "port_number must be unique for the row and panel"
            )

    port = base_row()
    port.update(
        {
            "row_id": row_id,
            "panel_code": panel_code,
            "port_number": port_number,
            "media_type": media_type,
            "status": "FREE",
            "assigned_order_id": None,
            "quarantine_until": None,
        }
    )
    store.ports[port["id"]] = port
    return created(serialize(port))


@bp.route("/patch-panel-ports/<port_id>", methods=["GET"])
def get_port(port_id):
    actor = authorize(*PORT_ROLES)
    actor.require_customer()
    port = refs.path_row(refs.PORT, port_id)
    return ok(serialize(port))


@bp.route("/patch-panel-ports", methods=["GET"])
def list_ports():
    actor = authorize(*PORT_ROLES)
    actor.require_customer()
    limit, offset = pagination()
    rows = qfilter(
        list(store.ports.values()),
        "row_id",
        "panel_code",
        "media_type",
        "status",
        "assigned_order_id",
    )
    items, total = paginate(rows, limit, offset)
    return ok_list(items, limit, offset, total)


# --------------------------------------------------------------------------
# Cross-connect orders
# --------------------------------------------------------------------------

@bp.route("/cross-connect-orders", methods=["POST"])
def create_order():
    actor = authorize("CustomerAdmin", "ProvisioningEngineer")
    body = json_body()

    # Rules 3 and 4 — body references resolve in declaration order.
    contract = refs.body_fk(body, "contract_id", refs.CONTRACT)
    contact = refs.body_fk(body, "requested_by_contact_id", refs.CONTACT)
    a_cabinet = refs.body_fk(body, "a_end_cabinet_id", refs.CABINET)
    refs.body_fk(body, "z_end_cabinet_id", refs.CABINET)
    refs.body_fk(body, "parent_order_id", refs.CC_ORDER)

    # Rule 5 — the far side is deliberately exempt from customer scoping.
    actor.require_customer()
    actor.scope_contract(contract)
    actor.scope_contact(contact)
    actor.scope_cabinet(a_cabinet)

    # Rule 9 — the contract's optimistic-concurrency guard.
    expected = req_int(body, "expected_contract_version")
    if contract is not None and expected != contract["version"]:
        raise ApiError(
            "ERR_STALE_CONTRACT_VERSION",
            "expected_contract_version %s does not match the contract's current version %s"
            % (expected, contract["version"]),
        )

    contract_id = req_string(body, "contract_id")
    requested_by_contact_id = req_string(body, "requested_by_contact_id")
    a_end_cabinet_id = req_string(body, "a_end_cabinet_id")
    z_end_cabinet_id = req_string(body, "z_end_cabinet_id")
    cable_type = req_enum(body, "cable_type", MEDIA_TYPES)
    parent_order_id = opt_id(body, "parent_order_id")

    if contract["status"] != "ACTIVE":
        raise ApiError("ERR_CONTRACT_NOT_ACTIVE", "a cross-connect requires an ACTIVE contract")
    if a_cabinet["status"] not in OPERATIONAL_CABINET_STATUSES:
        raise ApiError(
            "ERR_CABINET_NOT_OPERATIONAL",
            "the A-end cabinet must be INSTALLED or ACTIVE",
        )
    if a_cabinet.get("contract_id") != contract_id:
        raise ApiError(
            "ERR_CABINET_NOT_ON_CONTRACT", "the A-end cabinet is not held by this contract"
        )
    if contract["credit_hold"]:
        raise ApiError("ERR_CREDIT_HOLD_ACTIVE", "the contract is on credit hold")

    live = [
        o
        for o in store.cc_orders.values()
        if o["contract_id"] == contract_id and o["status"] in CAP_COUNTED
    ]
    if len(live) + 1 > contract["cross_connect_cap"]:
        raise ApiError(
            "ERR_CROSS_CONNECT_CAP_EXCEEDED",
            "the contract's cross_connect_cap is a hard cap",
        )

    order = base_row()
    order.update(
        {
            "contract_id": contract_id,
            "requested_by_contact_id": requested_by_contact_id,
            "a_end_cabinet_id": a_end_cabinet_id,
            "z_end_cabinet_id": z_end_cabinet_id,
            "parent_order_id": parent_order_id,
            "cable_type": cable_type,
            "a_end_port_id": None,
            "z_end_port_id": None,
            "path_hops": [],
            "revision_count": 0,
            "status": "SUBMITTED",
            # Pinned from the media at creation and never re-derived.
            "mrc_usd": q2(CC_MEDIA_MRC_USD[cable_type]),
            "proposed_by_user_id": None,
            "approved_by_user_id": None,
            "activated_at": None,
            "_created_by_user_id": actor.user_id,
        }
    )
    store.cc_orders[order["id"]] = order
    # §2.6 — an accepted create bumps the guarded parent's version.
    touch(contract)
    return created(serialize(order))


@bp.route("/cross-connect-orders/<order_id>/propose-route", methods=["POST"])
def propose_route(order_id):
    actor = authorize("ProvisioningEngineer")
    order = refs.path_row(refs.CC_ORDER, order_id)
    body = json_body()

    a_port = refs.body_fk(body, "a_end_port_id", refs.PORT)
    z_port = refs.body_fk(body, "z_end_port_id", refs.PORT)
    req_string(body, "a_end_port_id")
    req_string(body, "z_end_port_id")
    hops = req_string_list(body, "path_hops", non_empty=False)

    if order["status"] not in ("SUBMITTED", "CHANGES_REQUESTED"):
        raise ApiError(
            "ERR_INVALID_STATE",
            "only a SUBMITTED or CHANGES_REQUESTED order may be routed",
        )

    for port in (a_port, z_port):
        if port["status"] in HELD_PORT_STATUSES:
            raise ApiError("ERR_PORT_UNAVAILABLE", "port %s is already held" % port["id"])
    for port in (a_port, z_port):
        until = port.get("quarantine_until")
        if until is not None and until > now():
            raise ApiError(
                "ERR_PORT_IN_QUARANTINE", "port %s is still cooling down" % port["id"]
            )
    for port in (a_port, z_port):
        if port["media_type"] != order["cable_type"]:
            raise ApiError(
                "ERR_MEDIA_TYPE_MISMATCH",
                "port media %s does not match cable type %s"
                % (port["media_type"], order["cable_type"]),
            )

    if (
        len(hops) == 0
        or hops[0] != a_port["panel_code"]
        or hops[-1] != z_port["panel_code"]
        or len(set(hops)) != len(hops)
    ):
        raise ApiError(
            "ERR_PATH_ROUTE_INVALID",
            "path_hops must run from the A-side panel to the Z-side panel without repeats",
        )

    a_cabinet = store.cabinets.get(order["a_end_cabinet_id"])
    z_cabinet = store.cabinets.get(order["z_end_cabinet_id"])
    if a_cabinet is not None and a_port["row_id"] != a_cabinet["row_id"]:
        raise ApiError(
            "ERR_PORT_ROW_MISMATCH", "the A-side port is not in the A-end cabinet's row"
        )
    if z_cabinet is not None and z_port["row_id"] != z_cabinet["row_id"]:
        raise ApiError(
            "ERR_PORT_ROW_MISMATCH", "the Z-side port is not in the Z-end cabinet's row"
        )

    for port in (a_port, z_port):
        port["status"] = "RESERVED"
        port["assigned_order_id"] = order["id"]
        touch(port)

    order["a_end_port_id"] = a_port["id"]
    order["z_end_port_id"] = z_port["id"]
    order["path_hops"] = list(hops)
    order["proposed_by_user_id"] = actor.user_id
    order["status"] = "ROUTE_PROPOSED"
    touch(order)
    return ok(serialize(order))


@bp.route("/cross-connect-orders/<order_id>/request-changes", methods=["POST"])
def request_changes(order_id):
    actor = authorize("FacilityManager", "CustomerAdmin")
    order = refs.path_row(refs.CC_ORDER, order_id)
    actor.require_customer()
    actor.scope_contract_id(order["contract_id"])
    body = json_body()
    req_string(body, "reason")

    if order["status"] != "ROUTE_PROPOSED":
        raise ApiError("ERR_INVALID_STATE", "only a ROUTE_PROPOSED order may be sent back")
    if order["revision_count"] >= MAX_ROUTE_REVISIONS:
        raise ApiError(
            "ERR_REVISION_LIMIT_REACHED",
            "the order has exhausted its %s route revisions" % MAX_ROUTE_REVISIONS,
        )

    # The port pool is conserved rather than leaked.
    _free_ports(order, ("RESERVED",))
    order["revision_count"] = order["revision_count"] + 1
    order["a_end_port_id"] = None
    order["z_end_port_id"] = None
    order["path_hops"] = []
    order["status"] = "CHANGES_REQUESTED"
    touch(order)
    return ok(serialize(order))


def _free_ports(order, statuses):
    freed = 0
    for port in store.ports.values():
        if port.get("assigned_order_id") != order["id"]:
            continue
        if port["status"] not in statuses:
            continue
        port["status"] = "FREE"
        port["assigned_order_id"] = None
        touch(port)
        freed += 1
    return freed


def quarantine_ports(order):
    """Reclamation cools a port down rather than freeing it immediately."""
    until = now() + timedelta(hours=PORT_QUARANTINE_HOURS)
    count = 0
    for port in store.ports.values():
        if port.get("assigned_order_id") != order["id"]:
            continue
        if port["status"] not in HELD_PORT_STATUSES:
            continue
        port["status"] = "QUARANTINED"
        port["quarantine_until"] = until
        port["assigned_order_id"] = None
        touch(port)
        count += 1
    return count


def decommission_cross_connect(order, contract):
    """ACTIVE → DECOMMISSIONED with its port quarantine and credit line."""
    order["status"] = "DECOMMISSIONED"
    touch(order)
    released = quarantine_ports(order)
    if contract is not None:
        cross_connect_decommission_credit(contract, order)
        recompute_contract(contract, force=True)
    return released


@bp.route("/cross-connect-orders/<order_id>/state", methods=["POST"])
def order_state(order_id):
    actor = authorize("ProvisioningEngineer", "FacilityManager")
    order = refs.path_row(refs.CC_ORDER, order_id)
    body = json_body()
    to_state = req_enum(body, "to_state", CC_STATUSES)
    contract = store.contracts.get(order["contract_id"])
    current = order["status"]

    if to_state == "APPROVED":
        # Rule 8 — an order may not be approved by the X-User-ID that raised it.
        if actor.user_id is not None and actor.user_id == order.get("_created_by_user_id"):
            raise ApiError(
                "ERR_SEGREGATION_OF_DUTIES",
                "the approver must differ from the operator who raised the order",
            )
        if current != "ROUTE_PROPOSED":
            raise ApiError("ERR_INVALID_STATE", "only a ROUTE_PROPOSED order may be approved")
        if contract is None or contract["status"] != "ACTIVE":
            raise ApiError("ERR_CONTRACT_NOT_ACTIVE", "approval requires an ACTIVE contract")
        for port_id in (order["a_end_port_id"], order["z_end_port_id"]):
            port = store.ports.get(port_id)
            if (
                port is None
                or port["status"] != "RESERVED"
                or port.get("assigned_order_id") != order["id"]
            ):
                raise ApiError(
                    "ERR_PORT_UNAVAILABLE", "the pinned route no longer holds both ports"
                )
        if contract["credit_hold"]:
            raise ApiError("ERR_CREDIT_HOLD_ACTIVE", "the contract is on credit hold")
        order["approved_by_user_id"] = actor.user_id
        order["status"] = "APPROVED"
        touch(order)

    elif to_state == "INSTALLED":
        if current != "APPROVED":
            raise ApiError("ERR_INVALID_STATE", "only an APPROVED order may be installed")
        for port_id in (order["a_end_port_id"], order["z_end_port_id"]):
            port = store.ports.get(port_id)
            if port is not None and port["status"] == "RESERVED":
                port["status"] = "ASSIGNED"
                touch(port)
        order["status"] = "INSTALLED"
        touch(order)

    elif to_state == "ACTIVE":
        if current != "INSTALLED":
            raise ApiError("ERR_INVALID_STATE", "only an INSTALLED order may be activated")
        if contract is None or contract["status"] != "ACTIVE":
            raise ApiError("ERR_CONTRACT_NOT_ACTIVE", "activation requires an ACTIVE contract")
        order["status"] = "ACTIVE"
        order["activated_at"] = now()
        touch(order)
        recompute_contract(contract, force=True)

    elif to_state == "DECOMMISSIONED":
        if current != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE", "only an ACTIVE order may be decommissioned")
        decommission_cross_connect(order, contract)

    elif to_state == "ABORTED":
        if current not in ABORTABLE:
            raise ApiError(
                "ERR_INVALID_STATE",
                "an INSTALLED or ACTIVE order must be retired through a decommission order",
            )
        _free_ports(order, HELD_PORT_STATUSES)
        order["status"] = "ABORTED"
        touch(order)

    else:
        raise ApiError(
            "ERR_INVALID_STATE", "order cannot move from %s to %s" % (current, to_state)
        )

    return ok(serialize(order))


@bp.route("/cross-connect-orders/<order_id>", methods=["GET"])
def get_order(order_id):
    actor = authorize(*CC_READ_ROLES)
    order = refs.path_row(refs.CC_ORDER, order_id)
    actor.scope_contract_id(order["contract_id"])
    return ok(serialize(order))


@bp.route("/cross-connect-orders", methods=["GET"])
def list_orders():
    actor = authorize(*CC_READ_ROLES)
    actor.require_customer()
    actor.scope_query(
        ("contract", "contract_id"),
        ("contact", "requested_by_contact_id"),
        ("cabinet", "a_end_cabinet_id"),
    )
    limit, offset = pagination()
    rows = qfilter(
        list(store.cc_orders.values()),
        "contract_id",
        "requested_by_contact_id",
        "a_end_cabinet_id",
        "z_end_cabinet_id",
        "a_end_port_id",
        "z_end_port_id",
        "parent_order_id",
        "status",
        "cable_type",
    )
    items, total = paginate(rows, limit, offset)
    return ok_list(items, limit, offset, total)
