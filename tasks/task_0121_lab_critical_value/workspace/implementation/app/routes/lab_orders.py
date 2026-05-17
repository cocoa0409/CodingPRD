"""LabOrder endpoints + child create endpoints (specimens, results)."""
from __future__ import annotations

from flask import Blueprint, request

from ..auth import (
    ROLE_LAB_DIRECTOR,
    ROLE_LAB_TECH,
    ROLE_ORDERING_PROVIDER,
    require_roles,
)
from ..clock import now
from ..errors import (
    err_clia_complexity_violation,
    err_clinician_inactive,
    err_forbidden,
    err_invalid_state,
    err_measurements_incomplete,
    err_not_found,
    err_specimen_already_exists,
    err_time_order_invalid,
    err_validation,
)
from ..helpers import (
    assert_array,
    assert_enum,
    assert_string,
    occ_check,
    paginate,
    parse_iso8601,
    parse_pagination,
    require_json_object,
)
from ..responses import created, listing, ok
from ..services import calculations as calc
from ..services.audit import write_audit_event
from ..services.lookups import (
    get_clinician,
    get_lab_order,
    get_patient,
    get_test_panel,
)
from ..services.serialize import lab_order_view, lab_result_view, specimen_view
from ..services.workflows import (
    bump,
    create_common_fields,
    create_lab_order,
)
from ..store import store

bp = Blueprint("lab_orders", __name__)

PRIORITY_VALUES = ["ROUTINE", "STAT"]
LAB_ORDER_STATUSES = [
    "ORDERED",
    "COLLECTED",
    "IN_TRANSIT",
    "RECEIVED",
    "RESULTED",
    "RELEASED",
    "CANCELED",
    "REJECTED",
]


# ===========================================================================
# Lab order CRUD
# ===========================================================================

@bp.route("/lab-orders", methods=["POST"])
@require_roles(ROLE_ORDERING_PROVIDER)
def place_order(_caller_id=None, _caller_role=None, **_):
    body = require_json_object()
    patient_id = assert_string(body.get("patient_id"), "patient_id")
    op_id = assert_string(body.get("ordering_provider_id"), "ordering_provider_id")
    panel_id = assert_string(body.get("panel_id"), "panel_id")
    priority = assert_enum(body.get("priority"), "priority", PRIORITY_VALUES, required=False) or "ROUTINE"

    with store().lock:
        # Body FK existence (priority 4)
        get_patient(patient_id)
        op = get_clinician(op_id)
        get_test_panel(panel_id)

        # ordering provider must be ORDERING_PROVIDER role_kind (PRD §3.2)
        if op["role_kind"] != "ORDERING_PROVIDER":
            raise err_validation("ordering_provider_id must reference a Clinician with role_kind=ORDERING_PROVIDER")
        # active check (priority 14)
        if not op.get("active", True):
            raise err_clinician_inactive("ordering provider is inactive")

        row = create_lab_order(
            patient_id=patient_id,
            ordering_provider_id=op_id,
            panel_id=panel_id,
            priority=priority,
        )
        write_audit_event(
            event_type="ORDER_PLACED",
            lab_order_id=row["id"],
            actor_id=_caller_id,
            payload={"priority": priority, "panel_id": panel_id, "patient_id": patient_id},
        )
    return created(lab_order_view(row))


@bp.route("/lab-orders/<oid>", methods=["GET"])
@require_roles(ROLE_ORDERING_PROVIDER, ROLE_LAB_TECH, ROLE_LAB_DIRECTOR)
def fetch_order(oid, **_):
    row = get_lab_order(oid)
    return ok(lab_order_view(row))


@bp.route("/lab-orders", methods=["GET"])
@require_roles(ROLE_ORDERING_PROVIDER, ROLE_LAB_TECH, ROLE_LAB_DIRECTOR)
def list_orders(**_):
    limit, offset = parse_pagination()
    status_f = request.args.get("status")
    patient_f = request.args.get("patient_id")
    panel_f = request.args.get("panel_id")
    items = list(store().lab_orders.values())
    if status_f:
        items = [r for r in items if r["status"] == status_f]
    if patient_f:
        items = [r for r in items if r["patient_id"] == patient_f]
    if panel_f:
        items = [r for r in items if r["panel_id"] == panel_f]
    items.sort(key=lambda r: r["created_at"])
    total = len(items)
    page = paginate(items, limit, offset)
    return listing([lab_order_view(r) for r in page], total, limit, offset)


@bp.route("/lab-orders/<oid>/cancel", methods=["POST"])
@require_roles(ROLE_ORDERING_PROVIDER)
def cancel_order(oid, _caller_id=None, **_):
    body = require_json_object()
    with store().lock:
        row = get_lab_order(oid)
        # Per PRD §3.2: actor must be the order's ordering_provider — reported on role-permission rule
        if row["ordering_provider_id"] != _caller_id:
            raise err_forbidden("OrderingProvider may only cancel their own orders")
        if row["status"] != "ORDERED":
            raise err_invalid_state(f"LabOrder must be ORDERED to cancel (was {row['status']})")
        occ_check(body.get("version"), row["version"])
        row["status"] = "CANCELED"
        bump(row)
    return ok(lab_order_view(row))


# ===========================================================================
# Specimen creation (child of LabOrder)
# ===========================================================================

@bp.route("/lab-orders/<oid>/specimens", methods=["POST"])
@require_roles(ROLE_LAB_TECH)
def create_specimen(oid, **_):
    body = require_json_object()
    cb_id = assert_string(body.get("collected_by_id"), "collected_by_id")
    collected_at = parse_iso8601(body.get("collected_at"), "collected_at")

    with store().lock:
        order = get_lab_order(oid)
        # Body FK
        cb = get_clinician(cb_id)
        # Uniqueness — PRD §3.3 cross-references §2.12: a second specimen-creation
        # request is the §2.12 concurrency case, ERR_SPECIMEN_ALREADY_EXISTS.
        if oid in store().specimen_by_lab_order:
            raise err_specimen_already_exists()
        # State (priority 5)
        if order["status"] != "ORDERED":
            raise err_invalid_state(f"LabOrder must be ORDERED to add a specimen (was {order['status']})")
        # Time order (priority 11): collected_at <= now()
        if collected_at > now():
            raise err_time_order_invalid("collected_at must not be in the future")
        # Clinician active (priority 14)
        if cb["role_kind"] != "LAB_TECH":
            raise err_validation("collected_by_id must reference a Clinician with role_kind=LAB_TECH")
        if not cb.get("active", True):
            raise err_clinician_inactive("collecting LabTech is inactive")

        specimen = {
            **create_common_fields(),
            "lab_order_id": oid,
            "collected_by_id": cb_id,
            "collected_at": collected_at,
            "received_at": None,
            "rejected_reason": None,
            "status": "COLLECTED",
        }
        store().specimens[specimen["id"]] = specimen
        store().specimen_by_lab_order[oid] = specimen["id"]
        # LabOrder cascade
        order["status"] = "COLLECTED"
        bump(order)
    return created(specimen_view(specimen))


# ===========================================================================
# LabResult creation (child of LabOrder)
# ===========================================================================

def _validate_measurements(measurements_raw, panel: dict) -> list[dict]:
    if not isinstance(measurements_raw, list):
        raise err_validation("measurements must be an array")
    # Coverage check
    panel_codes = [a["analyte_code"] for a in panel["analytes"]]
    panel_unit = {a["analyte_code"]: a["unit"] for a in panel["analytes"]}
    seen: dict[str, dict] = {}
    out: list[dict] = []
    for i, m in enumerate(measurements_raw):
        if not isinstance(m, dict):
            raise err_measurements_incomplete(f"measurements[{i}] must be an object")
        code = m.get("analyte_code")
        unit = m.get("unit")
        value = m.get("value")
        if not isinstance(code, str) or code not in panel_codes:
            raise err_measurements_incomplete(f"measurements[{i}]: analyte_code '{code}' not on panel")
        if code in seen:
            raise err_measurements_incomplete(f"measurements[{i}]: analyte_code '{code}' duplicated")
        if not isinstance(unit, str) or unit != panel_unit[code]:
            raise err_measurements_incomplete(f"measurements[{i}]: unit '{unit}' does not match panel unit '{panel_unit[code]}'")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise err_measurements_incomplete(f"measurements[{i}]: value must be a number")
        seen[code] = m
        out.append({"analyte_code": code, "value": value, "unit": unit})
    missing = [c for c in panel_codes if c not in seen]
    if missing:
        raise err_measurements_incomplete(f"missing analytes: {missing}")
    if len(out) != len(panel_codes):
        raise err_measurements_incomplete("measurements length does not match panel analytes count")
    return out


@bp.route("/lab-orders/<oid>/results", methods=["POST"])
@require_roles(ROLE_LAB_TECH, ROLE_LAB_DIRECTOR)
def create_result(oid, **_):
    body = require_json_object()
    rb_id = assert_string(body.get("resulted_by_id"), "resulted_by_id")
    measurements_raw = body.get("measurements")
    if measurements_raw is None:
        raise err_validation("measurements is required")

    with store().lock:
        order = get_lab_order(oid)
        rb = get_clinician(rb_id)
        # State (priority 5): order must be RECEIVED, specimen must exist & be RECEIVED
        if order["status"] != "RECEIVED":
            raise err_invalid_state(f"LabOrder must be RECEIVED to resultate (was {order['status']})")
        specimen_id = store().specimen_by_lab_order.get(oid)
        if not specimen_id:
            raise err_invalid_state("Order has no specimen")
        specimen = store().specimens.get(specimen_id)
        if not specimen or specimen["status"] != "RECEIVED":
            raise err_invalid_state("Specimen must be RECEIVED")

        panel = get_test_panel(order["panel_id"])

        # CLIA complexity (priority 7)
        if panel["clia_complexity"] == "HIGH" and rb["role_kind"] != "LAB_DIRECTOR":
            raise err_clia_complexity_violation("HIGH complexity panels require LAB_DIRECTOR")
        if panel["clia_complexity"] in ("WAIVED", "MODERATE") and rb["role_kind"] not in ("LAB_TECH", "LAB_DIRECTOR"):
            raise err_clia_complexity_violation("resulted_by_id must be LAB_TECH or LAB_DIRECTOR")

        # Measurement coverage (priority 13)
        measurements = _validate_measurements(measurements_raw, panel)

        # Clinician active (priority 14)
        if not rb.get("active", True):
            raise err_clinician_inactive("resulted_by clinician is inactive")

        # Create result
        critical_flags = calc.compute_critical_flags(measurements, panel)
        severity = calc.severity_score_provisional(critical_flags)
        result = {
            **create_common_fields(),
            "lab_order_id": oid,
            "resulted_by_id": rb_id,
            "released_by_id": None,
            "measurements": measurements,
            "critical_flags": critical_flags,
            "severity_score": severity,
            "status": "DRAFT",
            "resulted_at": now(),
            "released_at": None,
        }
        store().lab_results[result["id"]] = result
        # Cascade order
        order["status"] = "RESULTED"
        bump(order)
    return created(lab_result_view(result))
