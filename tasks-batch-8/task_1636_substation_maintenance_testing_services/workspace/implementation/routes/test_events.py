"""TestEvent endpoints."""
from flask import Blueprint, request

import db
from middleware import get_actor, require_roles, ALL_ROLES
from response import success_object, success_list
from errors import (
    err_validation, err_not_found, err_state_transition, err_segregation_of_duties,
    err_certification_required, err_asset_decommissioned, err_outage_not_cleared,
)
from services.common import (
    body, require_string, require_number, require_enum, optional_number,
    optional_string, optional_bool, parse_datetime_field, parse_pagination,
    paginate, get_asset, get_outage_window, get_test_event, get_policy_for_class,
)
from services.calculations import (
    evaluate_insulation_resistance, evaluate_oil_moisture, evaluate_relay_timing,
    check_certification_gate, refresh_asset_condition_and_due,
    compute_defect_due_date,
)

bp = Blueprint("test_events", __name__)

TEST_TYPES = {"INSULATION_RESISTANCE", "OIL_MOISTURE", "RELAY_TIMING"}


def test_event_view(t):
    return {
        "id": t["id"],
        "asset_id": t["asset_id"],
        "outage_window_id": t.get("outage_window_id"),
        "test_type": t["test_type"],
        "technician_id": t["technician_id"],
        "value_primary": t["value_primary"],
        "value_secondary": t.get("value_secondary"),
        "ambient_temp_c": t.get("ambient_temp_c"),
        "requires_outage": t.get("requires_outage", False),
        "measured_at": t["measured_at"],
        "status": t["status"],
        "result": t.get("result"),
        "reviewed_by": t.get("reviewed_by"),
        "review_note": t.get("review_note"),
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


@bp.post("/test-events")
def create_test_event():
    actor = get_actor()
    require_roles(actor, ["Technician"])
    payload = body()
    asset_id = require_string(payload, "asset_id")
    test_type = require_enum(payload, "test_type", TEST_TYPES)
    value_primary = require_number(payload, "value_primary")
    measured_at_raw = parse_datetime_field(payload, "measured_at", required=True)
    measured_at = db._format_iso(measured_at_raw)
    value_secondary = optional_number(payload, "value_secondary")
    ambient_temp_c = optional_number(payload, "ambient_temp_c")
    requires_outage = optional_bool(payload, "requires_outage", False)
    outage_window_id = optional_string(payload, "outage_window_id")

    # FK: asset must exist
    asset = get_asset(asset_id)

    # Decommissioned asset guard
    if asset["status"] == "DECOMMISSIONED":
        raise err_asset_decommissioned()

    # Validate test-type-specific required fields
    if test_type == "INSULATION_RESISTANCE" and ambient_temp_c is None:
        raise err_validation("ambient_temp_c is required for INSULATION_RESISTANCE")
    if test_type == "RELAY_TIMING" and value_secondary is None:
        raise err_validation("value_secondary is required for RELAY_TIMING")

    # FK: outage_window_id if provided
    if outage_window_id is not None:
        get_outage_window(outage_window_id)

    # requires_outage requires outage_window_id
    if requires_outage and outage_window_id is None:
        raise err_validation("outage_window_id is required when requires_outage is true")

    ent = {
        "id": db.new_id(),
        "asset_id": asset_id,
        "outage_window_id": outage_window_id,
        "test_type": test_type,
        "technician_id": actor.user_id,
        "value_primary": value_primary,
        "value_secondary": value_secondary,
        "ambient_temp_c": ambient_temp_c,
        "requires_outage": requires_outage,
        "measured_at": measured_at,
        "status": "DRAFT",
        "result": None,
        "reviewed_by": None,
        "review_note": None,
    }
    db.stamp_new(ent)
    db.test_events[ent["id"]] = ent
    return success_object(test_event_view(ent), status=201)


@bp.get("/test-events")
def list_test_events():
    actor = get_actor()
    require_roles(actor, ALL_ROLES)
    limit, offset = parse_pagination()
    items = list(db.test_events.values())
    asset_id = request.args.get("asset_id")
    if asset_id:
        items = [t for t in items if t["asset_id"] == asset_id]
    outage_window_id = request.args.get("outage_window_id")
    if outage_window_id:
        items = [t for t in items if t.get("outage_window_id") == outage_window_id]
    technician_id = request.args.get("technician_id")
    if technician_id:
        items = [t for t in items if t["technician_id"] == technician_id]
    test_type = request.args.get("test_type")
    if test_type:
        items = [t for t in items if t["test_type"] == test_type]
    status = request.args.get("status")
    if status:
        items = [t for t in items if t["status"] == status]
    page, total = paginate(items, limit, offset)
    return success_list([test_event_view(t) for t in page], limit, offset, total)


@bp.get("/test-events/<id>")
def get_test_event_route(id):
    actor = get_actor()
    require_roles(actor, ALL_ROLES)
    t = get_test_event(id)
    return success_object(test_event_view(t))


@bp.post("/test-events/<id>/submit")
def submit_test_event(id):
    actor = get_actor()
    require_roles(actor, ["Technician"])
    te = get_test_event(id)

    # State check
    if te["status"] not in ("DRAFT", "RETURNED"):
        raise err_state_transition("Test event is not DRAFT or RETURNED")

    # Certification gate (priority 10 — before segregation of duties at priority 11)
    if te["test_type"] == "RELAY_TIMING":
        required_cert = "NETA_LEVEL_3"
    else:
        required_cert = "NETA_LEVEL_2"
    if not check_certification_gate(actor.user_id, required_cert):
        raise err_certification_required()

    # Segregation of duties: only the creator submits
    if actor.user_id != te["technician_id"]:
        raise err_segregation_of_duties("Only the creator may submit")

    # Outage gate
    if te.get("requires_outage"):
        ow_id = te.get("outage_window_id")
        if ow_id:
            ow = db.outage_windows.get(ow_id)
            if ow and ow["status"] != "CLEARED":
                raise err_outage_not_cleared()

    # Compute result
    asset = db.assets[te["asset_id"]]
    policy = get_policy_for_class(asset["asset_class"])
    if policy is None:
        raise err_validation("No policy found for asset class")

    if te["test_type"] == "INSULATION_RESISTANCE":
        result = evaluate_insulation_resistance(te["value_primary"], te["ambient_temp_c"], policy)
    elif te["test_type"] == "OIL_MOISTURE":
        result = evaluate_oil_moisture(te["value_primary"], policy)
    elif te["test_type"] == "RELAY_TIMING":
        result = evaluate_relay_timing(te["value_primary"], te["value_secondary"], policy)
    else:
        result = "PASS"

    te["status"] = "SUBMITTED"
    te["result"] = result
    db.touch(te)
    return success_object(test_event_view(te))


@bp.post("/test-events/<id>/review")
def review_test_event(id):
    actor = get_actor()
    require_roles(actor, ["ComplianceOfficer"])
    te = get_test_event(id)
    payload = body()
    decision = require_string(payload, "decision")
    if decision not in ("ACCEPT", "RETURN"):
        raise err_validation("decision must be ACCEPT or RETURN")
    review_note = payload.get("review_note")

    if te["status"] != "SUBMITTED":
        raise err_state_transition("Test event is not SUBMITTED")

    if decision == "RETURN":
        if not review_note:
            raise err_validation("review_note is required when decision is RETURN")
        te["status"] = "RETURNED"
        te["reviewed_by"] = actor.user_id
        te["review_note"] = review_note
        db.touch(te)
        return success_object(test_event_view(te))

    # ACCEPT
    te["status"] = "ACCEPTED"
    te["reviewed_by"] = actor.user_id
    if review_note:
        te["review_note"] = review_note
    db.touch(te)

    # Cascade hop 1: recompute condition_score
    refresh_asset_condition_and_due(te["asset_id"])

    # Cascade hop 2: auto-create defect for MARGINAL/FAIL
    if te["result"] in ("MARGINAL", "FAIL"):
        severity = "C2" if te["result"] == "FAIL" else "C3"
        defect = {
            "id": db.new_id(),
            "asset_id": te["asset_id"],
            "test_event_id": te["id"],
            "title": f"Auto-created defect from {te['test_type']} test ({te['result']})",
            "description": f"Test event {te['id']} graded {te['result']}",
            "severity": severity,
            "status": "OPEN",
            "deferral_count": 0,
            "deferred_until": None,
            "due_date": None,  # computed below
        }
        db.stamp_new(defect)
        defect["due_date"] = compute_defect_due_date(defect["created_at"], severity)
        db.defects[defect["id"]] = defect

        # Cascade hop 3: re-run condition score with the new defect penalty
        refresh_asset_condition_and_due(te["asset_id"])

    return success_object(test_event_view(te))
