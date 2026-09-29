"""Remote hands, site access and decommissioning (PRD §3.6, §3.7, §3.8)."""

from datetime import timedelta

from flask import Blueprint

import refs
from auth import authorize
from billing import remote_hands_labor_charge
from errors import ApiError
from response import created, ok, ok_list, paginate, pagination, serialize
from rollups import (
    cabinets_of_row,
    cascade_power_change,
    circuits_of_cabinet,
    recompute_contract,
    recompute_row,
    row_of,
)
from routes.connect import decommission_cross_connect
from store import (
    AUTHORIZATION_STATES,
    DECOM_STATUSES,
    DECOM_STEPS,
    OPERATIONAL_CABINET_STATUSES,
    RESPONSE_TARGET_MINUTES,
    SEVERITIES,
    VISIT_PURPOSES,
    VISIT_STATUSES,
    base_row,
    now,
    store,
    touch,
)
from util import dsum, parse_dt, q3
from validate import (
    json_body,
    opt_string,
    qfilter,
    req_datetime,
    req_enum,
    req_object_list,
    req_string,
)

bp = Blueprint("ops", __name__)

TICKET_READ_ROLES = ("ProvisioningEngineer", "CustomerAdmin", "SecurityOfficer", "BillingOperator")
VISIT_READ_ROLES = ("SecurityOfficer", "CustomerAdmin", "FacilityManager")
DECOM_READ_ROLES = ("ProvisioningEngineer", "FacilityManager", "CustomerAdmin")
OCCUPYING_VISIT_STATUSES = ("SCHEDULED", "CHECKED_IN")


def _contact_authorized(contact, contract, scope):
    """Rule 6 — the contact sits on the owning customer's list and holds the
    scope the operation needs."""
    if contract is not None and contact["customer_id"] != contract["customer_id"]:
        raise ApiError(
            "ERR_CONTACT_NOT_AUTHORIZED", "the contact belongs to another customer"
        )
    if scope not in (contact.get("authorization_scopes") or []):
        raise ApiError(
            "ERR_CONTACT_NOT_AUTHORIZED", "the contact does not hold the %s scope" % scope
        )


# --------------------------------------------------------------------------
# Remote-hands tickets
# --------------------------------------------------------------------------

@bp.route("/remote-hands-tickets", methods=["POST"])
def create_ticket():
    actor = authorize("CustomerAdmin", "ProvisioningEngineer")
    body = json_body()
    contract = refs.body_fk(body, "contract_id", refs.CONTRACT)
    contact = refs.body_fk(body, "requested_by_contact_id", refs.CONTACT)
    cabinet = refs.body_fk(body, "target_cabinet_id", refs.CABINET)

    actor.require_customer()
    actor.scope_contract(contract)
    actor.scope_contact(contact)
    actor.scope_cabinet(cabinet)

    if contact is not None:
        _contact_authorized(contact, contract, "REMOTE_HANDS")

    contract_id = req_string(body, "contract_id")
    requested_by_contact_id = req_string(body, "requested_by_contact_id")
    target_cabinet_id = req_string(body, "target_cabinet_id")
    severity = req_enum(body, "severity", SEVERITIES)
    description = req_string(body, "description")

    if contract["status"] != "ACTIVE":
        raise ApiError("ERR_CONTRACT_NOT_ACTIVE", "remote hands requires an ACTIVE contract")
    if cabinet.get("contract_id") != contract_id:
        raise ApiError(
            "ERR_CABINET_NOT_ON_CONTRACT", "the target cabinet is not held by this contract"
        )
    if contract["credit_hold"]:
        raise ApiError("ERR_CREDIT_HOLD_ACTIVE", "the contract is on credit hold")

    ticket = base_row()
    ticket.update(
        {
            "contract_id": contract_id,
            "requested_by_contact_id": requested_by_contact_id,
            "target_cabinet_id": target_cabinet_id,
            "authorizing_contact_id": None,
            "severity": severity,
            "description": description,
            "authorization_state": "PENDING_AUTHORIZATION",
            "execution_state": "QUEUED",
            "authorized_at": None,
            "response_deadline_at": None,
            "dispatched_at": None,
            "completed_at": None,
            "sla_breached": False,
            "work_segments": [],
            "billable_increments": 0,
            "billed_minutes": 0,
            "included_increments_applied": 0,
            "labor_charge_usd": 0.0,
            "_created_by_user_id": actor.user_id,
        }
    )
    store.tickets[ticket["id"]] = ticket
    return created(serialize(ticket))


@bp.route("/remote-hands-tickets/<ticket_id>/authorization", methods=["POST"])
def ticket_authorization(ticket_id):
    actor = authorize("CustomerAdmin", "SecurityOfficer")
    ticket = refs.path_row(refs.TICKET, ticket_id)
    contract = store.contracts.get(ticket["contract_id"])
    actor.require_customer()
    actor.scope_contract(contract)
    body = json_body()
    contact = refs.body_fk(body, "authorizing_contact_id", refs.CONTACT)

    if contact is not None:
        _contact_authorized(contact, contract, "REMOTE_HANDS")
        # Rule 7 — a self-authorization, whether by contact reference or by an
        # X-User-ID identical to the ticket's creator.
        if contact["id"] == ticket["requested_by_contact_id"]:
            raise ApiError(
                "ERR_SELF_AUTHORIZATION_FORBIDDEN",
                "the requesting contact may not authorize its own ticket",
            )
    if actor.user_id is not None and actor.user_id == ticket.get("_created_by_user_id"):
        raise ApiError(
            "ERR_SELF_AUTHORIZATION_FORBIDDEN",
            "the operator who raised the ticket may not authorize it",
        )

    authorizing_contact_id = req_string(body, "authorizing_contact_id")
    to_state = req_enum(body, "to_state", AUTHORIZATION_STATES)
    current = ticket["authorization_state"]

    if to_state == "AUTHORIZED":
        if current != "PENDING_AUTHORIZATION":
            raise ApiError(
                "ERR_INVALID_STATE", "only a PENDING_AUTHORIZATION ticket may be authorized"
            )
        ticket["authorization_state"] = "AUTHORIZED"
        ticket["authorizing_contact_id"] = authorizing_contact_id
        ticket["authorized_at"] = now()
        ticket["response_deadline_at"] = now() + timedelta(
            minutes=RESPONSE_TARGET_MINUTES[ticket["severity"]]
        )

    elif to_state == "DENIED":
        if current != "PENDING_AUTHORIZATION":
            raise ApiError(
                "ERR_INVALID_STATE", "only a PENDING_AUTHORIZATION ticket may be denied"
            )
        ticket["authorization_state"] = "DENIED"
        ticket["authorizing_contact_id"] = authorizing_contact_id
        if ticket["execution_state"] == "QUEUED":
            ticket["execution_state"] = "CANCELLED"

    elif to_state == "REVOKED":
        if current != "AUTHORIZED":
            raise ApiError("ERR_INVALID_STATE", "only an AUTHORIZED ticket may be revoked")
        if ticket["execution_state"] == "COMPLETED":
            raise ApiError("ERR_INVALID_STATE", "completed work cannot be revoked")
        ticket["authorization_state"] = "REVOKED"
        ticket["authorizing_contact_id"] = authorizing_contact_id
        if ticket["execution_state"] in ("QUEUED", "DISPATCHED", "IN_PROGRESS"):
            ticket["execution_state"] = "CANCELLED"

    else:
        raise ApiError(
            "ERR_INVALID_STATE", "authorization cannot move from %s to %s" % (current, to_state)
        )

    touch(ticket)
    return ok(serialize(ticket))


@bp.route("/remote-hands-tickets/<ticket_id>/dispatch", methods=["POST"])
def dispatch_ticket(ticket_id):
    authorize("ProvisioningEngineer")
    ticket = refs.path_row(refs.TICKET, ticket_id)

    if ticket["execution_state"] != "QUEUED":
        raise ApiError("ERR_INVALID_STATE", "only a QUEUED ticket may be dispatched")
    if ticket["authorization_state"] != "AUTHORIZED":
        raise ApiError("ERR_TICKET_NOT_AUTHORIZED", "the ticket is not authorized")
    cabinet = store.cabinets.get(ticket["target_cabinet_id"])
    if cabinet is None or cabinet["status"] not in OPERATIONAL_CABINET_STATUSES:
        raise ApiError(
            "ERR_CABINET_NOT_OPERATIONAL", "dispatch requires an INSTALLED or ACTIVE cabinet"
        )

    ticket["execution_state"] = "DISPATCHED"
    ticket["dispatched_at"] = now()
    deadline = ticket["response_deadline_at"]
    # Strict comparison: landing exactly on the deadline has met the commitment.
    ticket["sla_breached"] = bool(deadline is not None and ticket["dispatched_at"] > deadline)
    touch(ticket)
    return ok(serialize(ticket))


@bp.route("/remote-hands-tickets/<ticket_id>/complete", methods=["POST"])
def complete_ticket(ticket_id):
    authorize("ProvisioningEngineer")
    ticket = refs.path_row(refs.TICKET, ticket_id)
    body = json_body()
    raw_segments = req_object_list(body, "work_segments")

    segments = []
    for item in raw_segments:
        started = parse_dt(item.get("started_at"))
        ended = parse_dt(item.get("ended_at"))
        if started is None or ended is None:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "each work segment needs an ISO 8601 started_at and ended_at",
            )
        segments.append({"started_at": started, "ended_at": ended})
    for segment in segments:
        if segment["ended_at"] < segment["started_at"]:
            raise ApiError(
                "ERR_BILLING_PERIOD_INVALID", "a segment may not end before it started"
            )

    if ticket["execution_state"] != "DISPATCHED":
        raise ApiError("ERR_INVALID_STATE", "only a DISPATCHED ticket may be completed")
    if ticket["authorization_state"] != "AUTHORIZED":
        raise ApiError("ERR_TICKET_NOT_AUTHORIZED", "the ticket is not authorized")

    contract = store.contracts.get(ticket["contract_id"])
    ticket["work_segments"] = segments
    remote_hands_labor_charge(ticket, contract, segments)
    ticket["execution_state"] = "COMPLETED"
    ticket["completed_at"] = now()
    touch(ticket)
    recompute_contract(contract, force=True)
    return ok(serialize(ticket))


@bp.route("/remote-hands-tickets/<ticket_id>", methods=["GET"])
def get_ticket(ticket_id):
    actor = authorize(*TICKET_READ_ROLES)
    ticket = refs.path_row(refs.TICKET, ticket_id)
    actor.scope_contract_id(ticket["contract_id"])
    return ok(serialize(ticket))


@bp.route("/remote-hands-tickets", methods=["GET"])
def list_tickets():
    actor = authorize(*TICKET_READ_ROLES)
    actor.require_customer()
    actor.scope_query(
        ("contract", "contract_id"),
        ("contact", "requested_by_contact_id"),
        ("contact", "authorizing_contact_id"),
        ("cabinet", "target_cabinet_id"),
    )
    limit, offset = pagination()
    rows = qfilter(
        list(store.tickets.values()),
        "contract_id",
        "requested_by_contact_id",
        "authorizing_contact_id",
        "target_cabinet_id",
        "authorization_state",
        "execution_state",
        "severity",
    )
    items, total = paginate(rows, limit, offset)
    return ok_list(items, limit, offset, total)


# --------------------------------------------------------------------------
# Access visits
# --------------------------------------------------------------------------

def _occupying_visits():
    return [v for v in store.visits.values() if v["status"] in OCCUPYING_VISIT_STATUSES]


@bp.route("/access-visits", methods=["POST"])
def create_visit():
    actor = authorize("CustomerAdmin", "SecurityOfficer")
    body = json_body()
    contract = refs.body_fk(body, "contract_id", refs.CONTRACT)
    contact = refs.body_fk(body, "contact_id", refs.CONTACT)
    cabinet = refs.body_fk(body, "cabinet_id", refs.CABINET)

    actor.require_customer()
    actor.scope_contract(contract)
    actor.scope_contact(contact)
    actor.scope_cabinet(cabinet)

    if contact is not None:
        _contact_authorized(contact, contract, "SITE_ACCESS")

    contract_id = req_string(body, "contract_id")
    contact_id = req_string(body, "contact_id")
    cabinet_id = req_string(body, "cabinet_id")
    purpose = req_enum(body, "purpose", VISIT_PURPOSES)
    window_start = req_datetime(body, "window_start")
    window_end = req_datetime(body, "window_end")
    if window_end <= window_start:
        raise ApiError("ERR_INVALID_REQUEST", "window_end must be strictly after window_start")

    if contract["status"] != "ACTIVE":
        raise ApiError("ERR_CONTRACT_NOT_ACTIVE", "a visit requires an ACTIVE contract")
    if cabinet["status"] not in OPERATIONAL_CABINET_STATUSES:
        raise ApiError(
            "ERR_CABINET_NOT_OPERATIONAL", "a visit requires an INSTALLED or ACTIVE cabinet"
        )
    if cabinet.get("contract_id") != contract_id:
        raise ApiError(
            "ERR_CABINET_NOT_ON_CONTRACT", "the cabinet is not held by this contract"
        )

    # Gate one — cabinet exclusivity on half-open windows; touching windows pass.
    for peer in _occupying_visits():
        if peer["cabinet_id"] != cabinet_id:
            continue
        if window_start < peer["window_end"] and peer["window_start"] < window_end:
            raise ApiError(
                "ERR_VISIT_WINDOW_CONFLICT", "the cabinet is already occupied in that window"
            )

    escort_required = (
        contact["access_level"] == "ESCORTED_ONLY"
        or purpose == "CARRIER_INSTALL"
        or cabinet["footprint_type"] == "MEET_ME"
    )

    # Gate two — row escort capacity on CLOSED intervals; touching windows do
    # consume an officer, because a handover is not instantaneous.
    if escort_required:
        row = row_of(cabinet)
        row_cabinet_ids = set(c["id"] for c in cabinets_of_row(cabinet["row_id"]))
        used = 0
        for peer in _occupying_visits():
            if peer["cabinet_id"] not in row_cabinet_ids:
                continue
            if not peer["escort_required"]:
                continue
            if window_start <= peer["window_end"] and peer["window_start"] <= window_end:
                used += 1
        if row is not None and used >= row["escort_slot_count"]:
            raise ApiError(
                "ERR_ESCORT_CAPACITY_EXCEEDED",
                "the row's %s escort slots are already committed" % row["escort_slot_count"],
            )

    visit = base_row()
    visit.update(
        {
            "contract_id": contract_id,
            "contact_id": contact_id,
            "cabinet_id": cabinet_id,
            "purpose": purpose,
            "window_start": window_start,
            "window_end": window_end,
            "escort_required": bool(escort_required),
            "escort_officer_user_id": None,
            "status": "SCHEDULED",
            "checked_in_at": None,
            "checked_out_at": None,
        }
    )
    store.visits[visit["id"]] = visit
    return created(serialize(visit))


@bp.route("/access-visits/<visit_id>/state", methods=["POST"])
def visit_state(visit_id):
    authorize("SecurityOfficer")
    visit = refs.path_row(refs.VISIT, visit_id)
    body = json_body()
    to_state = req_enum(body, "to_state", VISIT_STATUSES)
    escort_officer_user_id = opt_string(body, "escort_officer_user_id")
    current = visit["status"]

    if to_state == "CHECKED_IN":
        if current != "SCHEDULED":
            raise ApiError("ERR_INVALID_STATE", "only a SCHEDULED visit may be checked in")
        contact = store.contacts.get(visit["contact_id"])
        if contact is None or contact["biometric_state"] != "ENROLLED":
            raise ApiError(
                "ERR_BIOMETRIC_NOT_ENROLLED", "the visitor is not biometrically enrolled"
            )
        if visit["escort_required"] and not escort_officer_user_id:
            raise ApiError("ERR_ESCORT_REQUIRED", "this visit requires a named escort officer")
        if not visit["escort_required"] and escort_officer_user_id:
            raise ApiError(
                "ERR_ESCORT_REQUIRED", "this visit does not require an escort officer"
            )
        clock = now()
        if clock < visit["window_start"] or clock >= visit["window_end"]:
            raise ApiError(
                "ERR_OUTSIDE_VISIT_WINDOW", "the logical clock is outside the visit window"
            )
        visit["status"] = "CHECKED_IN"
        visit["checked_in_at"] = clock
        visit["escort_officer_user_id"] = escort_officer_user_id

    elif to_state == "CHECKED_OUT":
        if current != "CHECKED_IN":
            raise ApiError("ERR_INVALID_STATE", "only a CHECKED_IN visit may be checked out")
        visit["status"] = "CHECKED_OUT"
        visit["checked_out_at"] = now()

    elif to_state == "CANCELLED":
        if current != "SCHEDULED":
            raise ApiError("ERR_INVALID_STATE", "only a SCHEDULED visit may be cancelled")
        visit["status"] = "CANCELLED"

    else:
        raise ApiError(
            "ERR_INVALID_STATE", "visit cannot move from %s to %s" % (current, to_state)
        )

    touch(visit)
    return ok(serialize(visit))


@bp.route("/access-visits/<visit_id>", methods=["GET"])
def get_visit(visit_id):
    actor = authorize(*VISIT_READ_ROLES)
    visit = refs.path_row(refs.VISIT, visit_id)
    actor.scope_contract_id(visit["contract_id"])
    return ok(serialize(visit))


@bp.route("/access-visits", methods=["GET"])
def list_visits():
    actor = authorize(*VISIT_READ_ROLES)
    actor.require_customer()
    actor.scope_query(
        ("contract", "contract_id"), ("contact", "contact_id"), ("cabinet", "cabinet_id")
    )
    limit, offset = pagination()
    rows = qfilter(
        list(store.visits.values()), "contract_id", "contact_id", "cabinet_id", "status", "purpose"
    )
    items, total = paginate(rows, limit, offset)
    return ok_list(items, limit, offset, total)


# --------------------------------------------------------------------------
# Decommission orders
# --------------------------------------------------------------------------

@bp.route("/decommission-orders", methods=["POST"])
def create_decommission():
    actor = authorize("CustomerAdmin", "ProvisioningEngineer")
    body = json_body()
    contract = refs.body_fk(body, "contract_id", refs.CONTRACT)
    cabinet = refs.body_fk(body, "cabinet_id", refs.CABINET)
    contact = refs.body_fk(body, "requested_by_contact_id", refs.CONTACT)

    actor.require_customer()
    actor.scope_contract(contract)
    actor.scope_cabinet(cabinet)
    actor.scope_contact(contact)

    contract_id = req_string(body, "contract_id")
    cabinet_id = req_string(body, "cabinet_id")
    requested_by_contact_id = req_string(body, "requested_by_contact_id")

    if cabinet.get("contract_id") != contract_id:
        raise ApiError(
            "ERR_CABINET_NOT_ON_CONTRACT", "the cabinet is not held by this contract"
        )

    order = base_row()
    order.update(
        {
            "contract_id": contract_id,
            "cabinet_id": cabinet_id,
            "requested_by_contact_id": requested_by_contact_id,
            "status": "REQUESTED",
            "equipment_removed_at": None,
            "equipment_removed_by_user_id": None,
            "cables_reclaimed_at": None,
            "cables_reclaimed_by_user_id": None,
            "released_port_count": 0,
            "released_power_kw": 0.0,
            "_created_by_user_id": actor.user_id,
        }
    )
    store.decoms[order["id"]] = order
    return created(serialize(order))


@bp.route("/decommission-orders/<order_id>/state", methods=["POST"])
def decommission_state(order_id):
    actor = authorize("FacilityManager", "ProvisioningEngineer")
    order = refs.path_row(refs.DECOM, order_id)
    body = json_body()
    to_state = req_enum(body, "to_state", DECOM_STATUSES)
    cabinet = store.cabinets.get(order["cabinet_id"])
    current = order["status"]

    if to_state == "APPROVED":
        # Rule 8 — the approver must differ from the operator who raised it.
        if actor.user_id is not None and actor.user_id == order.get("_created_by_user_id"):
            raise ApiError(
                "ERR_SEGREGATION_OF_DUTIES",
                "the approver must differ from the operator who raised the order",
            )
        if current != "REQUESTED":
            raise ApiError("ERR_INVALID_STATE", "only a REQUESTED order may be approved")
        if cabinet is None or cabinet["status"] not in OPERATIONAL_CABINET_STATUSES:
            raise ApiError(
                "ERR_CABINET_NOT_OPERATIONAL",
                "approval requires an INSTALLED or ACTIVE cabinet",
            )
        if cabinet.get("contract_id") != order["contract_id"]:
            raise ApiError(
                "ERR_CABINET_NOT_ON_CONTRACT", "the cabinet is no longer held by the contract"
            )

        released = dsum(
            c["allocated_kw"]
            for c in circuits_of_cabinet(cabinet["id"])
            if c["status"] == "ENERGIZED"
        )
        for circuit in circuits_of_cabinet(cabinet["id"]):
            if circuit["status"] != "ENERGIZED":
                continue
            circuit["status"] = "DE_ENERGIZED"
            circuit["allocated_kw"] = 0.0
            circuit["cooling_contribution_kw"] = 0.0
            touch(circuit)
        cabinet["status"] = "DECOMMISSIONING"
        order["released_power_kw"] = q3(released)
        order["status"] = "APPROVED"
        touch(order)
        cascade_power_change(cabinet, force=True)

    elif to_state == "CANCELLED":
        if current != "REQUESTED":
            raise ApiError("ERR_INVALID_STATE", "only a REQUESTED order may be cancelled")
        order["status"] = "CANCELLED"
        touch(order)

    else:
        raise ApiError(
            "ERR_INVALID_STATE",
            "decommission order cannot move from %s to %s" % (current, to_state),
        )

    return ok(serialize(order))


@bp.route("/decommission-orders/<order_id>/record-step", methods=["POST"])
def record_step(order_id):
    actor = authorize("ProvisioningEngineer")
    order = refs.path_row(refs.DECOM, order_id)
    body = json_body()
    step_code = req_enum(body, "step_code", DECOM_STEPS)

    if step_code == "EQUIPMENT_REMOVAL":
        own_at, own_by = "equipment_removed_at", "equipment_removed_by_user_id"
        other_by = "cables_reclaimed_by_user_id"
    else:
        own_at, own_by = "cables_reclaimed_at", "cables_reclaimed_by_user_id"
        other_by = "equipment_removed_by_user_id"

    # Rule 8 — the two recorded steps belong to two different operators.
    peer = order.get(other_by)
    if peer is not None and actor.user_id is not None and actor.user_id == peer:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "the two decommission steps must be recorded by different operators",
        )
    if order["status"] not in ("APPROVED", "IN_PROGRESS"):
        raise ApiError(
            "ERR_INVALID_STATE", "steps are recorded on an APPROVED or IN_PROGRESS order"
        )
    if order.get(own_at) is not None:
        raise ApiError(
            "ERR_DECOMMISSION_STEP_ALREADY_RECORDED",
            "%s has already been recorded on this order" % step_code,
        )

    order[own_at] = now()
    order[own_by] = actor.user_id
    if order["equipment_removed_at"] is not None and order["cables_reclaimed_at"] is not None:
        # The join happens inside this same request.
        order["status"] = "READY_FOR_RELEASE"
    else:
        order["status"] = "IN_PROGRESS"
    touch(order)
    return ok(serialize(order))


@bp.route("/decommission-orders/<order_id>/release-ports", methods=["POST"])
def release_ports(order_id):
    authorize("ProvisioningEngineer")
    order = refs.path_row(refs.DECOM, order_id)
    if order["status"] != "READY_FOR_RELEASE":
        raise ApiError(
            "ERR_INVALID_STATE", "only a READY_FOR_RELEASE order may release its ports"
        )

    cabinet = store.cabinets.get(order["cabinet_id"])
    contract = store.contracts.get(order["contract_id"])

    released_ports = 0
    for cc in list(store.cc_orders.values()):
        if cc["status"] != "ACTIVE":
            continue
        if cabinet is None or cc["a_end_cabinet_id"] != cabinet["id"]:
            continue
        assigned = [
            p
            for p in store.ports.values()
            if p.get("assigned_order_id") == cc["id"] and p["status"] == "ASSIGNED"
        ]
        released_ports += len(assigned)
        decommission_cross_connect(cc, store.contracts.get(cc["contract_id"]))

    order["released_port_count"] = released_ports
    order["status"] = "CLOSED"
    touch(order)

    if cabinet is not None:
        for circuit in circuits_of_cabinet(cabinet["id"]):
            if circuit["status"] == "DE_ENERGIZED":
                circuit["status"] = "REMOVED"
                touch(circuit)
        row = row_of(cabinet)
        cabinet["status"] = "RELEASED"
        cabinet["contract_id"] = None
        touch(cabinet)
        if row is not None:
            recompute_row(row, force=True)
    recompute_contract(contract, force=True)
    return ok(serialize(order))


@bp.route("/decommission-orders/<order_id>", methods=["GET"])
def get_decommission(order_id):
    actor = authorize(*DECOM_READ_ROLES)
    order = refs.path_row(refs.DECOM, order_id)
    actor.scope_contract_id(order["contract_id"])
    return ok(serialize(order))


@bp.route("/decommission-orders", methods=["GET"])
def list_decommissions():
    actor = authorize(*DECOM_READ_ROLES)
    actor.require_customer()
    actor.scope_query(
        ("contract", "contract_id"),
        ("cabinet", "cabinet_id"),
        ("contact", "requested_by_contact_id"),
    )
    limit, offset = pagination()
    rows = qfilter(
        list(store.decoms.values()),
        "contract_id",
        "cabinet_id",
        "requested_by_contact_id",
        "status",
    )
    items, total = paginate(rows, limit, offset)
    return ok_list(items, limit, offset, total)
