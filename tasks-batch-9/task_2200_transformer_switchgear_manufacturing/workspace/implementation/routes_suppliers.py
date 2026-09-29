"""Suppliers and long-lead components (PRD 3.4, 3.9)."""
from flask import Blueprint

import calc
import clock
import common
import envelope
import posture
import rbac
import store
import validation
from errors import ApiError
from validation import INTEGER, STRING, f

bp = Blueprint("suppliers", __name__)

REGIONS = ["NA", "EU", "APAC", "LATAM"]
CATEGORIES = ["HV_BUSHING", "VACUUM_INTERRUPTER", "TAP_CHANGER", "CT_VT",
              "CORE_STEEL_COIL", "BREAKER_FRAME"]
POLICIES = ["PREEMPTIBLE", "PROTECTED"]


def apply_probation_cycle(supplier):
    """The trailing index drives APPROVED <-> PROBATION automatically (PRD 3.9)."""
    trailing = supplier.get("quality_index_trailing")
    if trailing is None:
        return supplier
    if supplier.get("status") == "APPROVED" and trailing < 70.00:
        supplier["status"] = "PROBATION"
        supplier["probation_entered_at"] = clock.now_str()
    elif supplier.get("status") == "PROBATION" and trailing >= 70.00:
        supplier["status"] = "APPROVED"
        supplier["probation_entered_at"] = None
    return supplier


def check_supplier_active(supplier):
    """Rung 53."""
    if supplier is not None and supplier.get("status") == "SUSPENDED":
        raise ApiError("ERR_SUPPLIER_SUSPENDED", "the vendor is suspended")


def check_component_usable(component, as_target=True):
    """Rungs 34 and 52 for a component that must be ACTIVE.

    ``as_target`` is true when the component is the row the request targets, so a
    terminal OBSOLETE row is a terminal-state rejection. On the reservation path
    the component is a body-borne reference and PRD 3.4 pins the outcome: "A
    component that is QUARANTINED or OBSOLETE is rejected with
    ERR_COMPONENT_QUARANTINED".
    """
    status = component.get("status")
    if status == "ACTIVE":
        return
    if status == "OBSOLETE" and as_target:
        raise ApiError("ERR_TERMINAL_STATE", "the component is obsolete")
    raise ApiError("ERR_COMPONENT_QUARANTINED", "the component is %s" % status)


# --------------------------------------------------------------------------- #
# suppliers
# --------------------------------------------------------------------------- #

@bp.route("/suppliers", methods=["POST"])
def create_supplier():
    rbac.authenticate("POST /suppliers")
    payload = validation.body()
    data = validation.validate(payload, [
        f("supplier_code", STRING, required=True),
        f("legal_name", STRING, required=True),
        f("region", STRING, required=True, enum=REGIONS),
    ])
    for s in store.all_rows("supplier"):
        if s.get("supplier_code") == data["supplier_code"]:
            raise ApiError("ERR_DUPLICATE_CODE", "supplier_code already exists")
    supplier = dict(data)
    supplier.update({
        "status": "APPROVED",
        "quality_index_trailing": 100,
        "quality_index_lifetime": 100,
        "attributed_failure_count": 0,
        "receipt_event_count": 0,
        "probation_entered_at": None,
    })
    store.insert("supplier", supplier)
    return envelope.created(store.public(supplier))


@bp.route("/suppliers", methods=["GET"])
def list_suppliers():
    rbac.authenticate("GET /suppliers")
    limit, offset = envelope.pagination()
    rows = common.apply_filters(store.all_rows("supplier"), {
        "status": common.qstr("status"),
        "region": common.qstr("region"),
    })
    return envelope.listing(store.public_list(rows), limit, offset)


@bp.route("/suppliers/<sid>", methods=["GET"])
def get_supplier(sid):
    rbac.authenticate("GET /suppliers/{id}")
    return envelope.ok(store.public(common.resolve("supplier", sid)))


@bp.route("/suppliers/<sid>/receipt-events", methods=["POST"])
def create_receipt_event(sid):
    rbac.authenticate("POST /suppliers/{id}/receipt-events")
    supplier = common.resolve("supplier", sid)
    payload = validation.body()
    data = validation.validate(payload, [f("event_count", INTEGER, minimum=1, default=1)])
    common.check_state("supplier", supplier, ("APPROVED", "PROBATION"))
    supplier["receipt_event_count"] = (supplier.get("receipt_event_count") or 0) + data["event_count"]
    calc.refresh_supplier_indices(supplier)
    apply_probation_cycle(supplier)
    store.touch("supplier", supplier)
    return envelope.ok(store.public(supplier))


@bp.route("/suppliers/<sid>/suspend", methods=["POST"])
def suspend_supplier(sid):
    rbac.authenticate("POST /suppliers/{id}/suspend")
    supplier = common.resolve("supplier", sid)
    payload = validation.body()
    validation.validate(payload, [f("reason", STRING)])
    common.check_state("supplier", supplier, ("APPROVED", "PROBATION"))
    if (supplier.get("quality_index_lifetime") or 0) >= 60.00:
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "quality_index_lifetime must be strictly below 60.00 to suspend")
    supplier["status"] = "SUSPENDED"
    if "reason" in payload and isinstance(payload.get("reason"), str):
        supplier["suspension_reason"] = payload["reason"]
    store.touch("supplier", supplier)
    for comp in store.where("component", supplier_id=sid):
        if comp.get("status") != "ACTIVE":
            continue
        comp["status"] = "QUARANTINED"
        comp["quarantine_reason"] = "SUPPLIER_SUSPENDED"
        store.touch("component", comp)
        common.release_component_reservations(comp)
    return envelope.ok(store.public(supplier))


@bp.route("/suppliers/<sid>/quality-summary", methods=["GET"])
def supplier_quality_summary(sid):
    rbac.authenticate("GET /suppliers/{id}/quality-summary")
    supplier = common.resolve("supplier", sid)
    return envelope.ok(store.public(supplier))


# --------------------------------------------------------------------------- #
# long-lead components
# --------------------------------------------------------------------------- #

@bp.route("/suppliers/<sid>/long-lead-components", methods=["POST"])
def create_component(sid):
    rbac.authenticate("POST /suppliers/{id}/long-lead-components")
    supplier = common.resolve("supplier", sid)
    payload = validation.body()
    data = validation.validate(payload, [
        f("part_number", STRING, required=True),
        f("category", STRING, required=True, enum=CATEGORIES),
        f("lead_time_days", INTEGER, required=True, minimum=1),
        f("quantity_on_hand", INTEGER, required=True, minimum=0),
        f("allocation_policy", STRING, enum=POLICIES, default="PREEMPTIBLE"),
    ])
    for c in store.where("component", supplier_id=sid):
        if c.get("part_number") == data["part_number"]:
            raise ApiError("ERR_DUPLICATE_CODE", "part_number already exists for this supplier")
    check_supplier_active(supplier)
    component = dict(data)
    component.update({
        "supplier_id": sid,
        "status": "ACTIVE",
        "quantity_reserved": 0,
        "quantity_committed": 0,
        "quantity_consumed": 0,
        "quantity_available": data["quantity_on_hand"],
        "quarantine_reason": None,
    })
    store.insert("component", component)
    return envelope.created(store.public(component))


@bp.route("/suppliers/<sid>/long-lead-components", methods=["GET"])
def list_supplier_components(sid):
    rbac.authenticate("GET /suppliers/{id}/long-lead-components")
    common.resolve("supplier", sid)
    limit, offset = envelope.pagination()
    rows = common.apply_filters(store.where("component", supplier_id=sid), {
        "status": common.qstr("status"),
        "category": common.qstr("category"),
    })
    return envelope.listing(store.public_list(rows), limit, offset)


@bp.route("/long-lead-components", methods=["GET"])
def list_components():
    rbac.authenticate("GET /long-lead-components")
    limit, offset = envelope.pagination()
    rows = common.apply_filters(store.all_rows("component"), {
        "supplier_id": common.qstr("supplier_id"),
        "status": common.qstr("status"),
        "category": common.qstr("category"),
        "allocation_policy": common.qstr("allocation_policy"),
    })
    return envelope.listing(store.public_list(rows), limit, offset)


@bp.route("/long-lead-components/<cid>", methods=["GET"])
def get_component(cid):
    rbac.authenticate("GET /long-lead-components/{id}")
    return envelope.ok(store.public(common.resolve("component", cid)))


@bp.route("/long-lead-components/<cid>/receipts", methods=["POST"])
def receive_component(cid):
    rbac.authenticate("POST /long-lead-components/{id}/receipts")
    component = common.resolve("component", cid)
    payload = validation.body()
    data = validation.validate(payload, [f("quantity", INTEGER, required=True, minimum=1)])
    check_component_usable(component, as_target=False)
    check_supplier_active(store.get("supplier", component.get("supplier_id")))
    component["quantity_on_hand"] = (component.get("quantity_on_hand") or 0) + data["quantity"]
    calc.refresh_component_buckets(component)
    store.touch("component", component)
    return envelope.ok(store.public(component))


@bp.route("/long-lead-components/<cid>/release-quarantine", methods=["POST"])
def release_quarantine(cid):
    rbac.authenticate("POST /long-lead-components/{id}/release-quarantine")
    component = common.resolve("component", cid)
    common.check_state("component", component, ("QUARANTINED",))
    for claim in store.where("claim", suspect_component_id=cid):
        for report in store.where("failure_report", warranty_claim_id=claim["id"]):
            if report.get("status") == "PUBLISHED" and report.get("quarantine_recommended"):
                raise ApiError("ERR_INVALID_STATE_TRANSITION",
                               "a published failure analysis still recommends quarantine")
    component["status"] = "ACTIVE"
    component["quarantine_reason"] = None
    calc.refresh_component_buckets(component)
    store.touch("component", component)
    return envelope.ok(store.public(component))


@bp.route("/long-lead-components/<cid>/obsolete", methods=["POST"])
def obsolete_component(cid):
    rbac.authenticate("POST /long-lead-components/{id}/obsolete")
    component = common.resolve("component", cid)
    payload = validation.body()
    validation.validate(payload, [f("reason", STRING)])
    common.check_state("component", component, ("ACTIVE", "QUARANTINED"))
    for a in store.where("allocation", long_lead_component_id=cid):
        if a.get("status") in ("RESERVED", "COMMITTED"):
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "the component still carries live allocations")
    component["status"] = "OBSOLETE"
    if isinstance(payload.get("reason"), str):
        component["obsolete_reason"] = payload["reason"]
    store.touch("component", component)
    return envelope.ok(store.public(component))
