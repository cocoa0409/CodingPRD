"""Visits, evidence, deficiencies (nested), audits, visit ledger (PRD §3.3-3.6)."""
from datetime import timedelta

from flask import Blueprint, request

import errors as E
from errors import ApiError
from db import store, new_common_fields, new_append_fields, touch, parse_dt, now, fmt_ts
from middleware import (auth, require_role, require_technician_identity, body,
                        v_str, v_int, v_enum, paginate)
from response import ok_object, ok_list
from services.core import (get_batch, get_unit, get_template, get_asset, get_plan,
                           get_visit, property_of_visit, require_active_property,
                           estimated_visit_cost, actual_visit_cost)
from services.compliance import (add_ledger_entry, maybe_execute_batch,
                                 recompute_asset_compliance)
from services.serializers import (visit_view, evidence_view, deficiency_view,
                                  audit_view, ledger_view)

bp = Blueprint("visits", __name__)

PM = ("PropertyManager",)
TECH = ("Technician",)
ALL = ("PropertyManager", "Technician", "ComplianceAuditor")
LEDGER_READ = ("PropertyManager", "ComplianceAuditor")
EVIDENCE_TYPES = ("FILTER_REPLACEMENT", "DETECTOR_TEST", "BATTERY_REPLACEMENT")
SEVERITIES = ("LOW", "MEDIUM", "HIGH", "EMERGENCY")


def _unit_overlaps(unit_id, start_dt, template, exclude_visit_id=None):
    """Half-open interval intersection for a unit's non-CANCELLED visits."""
    new_end = start_dt + timedelta(minutes=template["estimated_labor_minutes"])
    for v in store.visits.values():
        if v["unit_id"] != unit_id or v["visit_status"] == "CANCELLED":
            continue
        if exclude_visit_id is not None and v["id"] == exclude_visit_id:
            continue
        tpl = store.templates.get(v["template_id"])
        if tpl is None:
            continue
        v_start = v["_sched_dt"]
        v_end = v_start + timedelta(minutes=tpl["estimated_labor_minutes"])
        if start_dt < v_end and v_start < new_end:
            return True
    return False


def _release_visit_commit(visit, prop, template, reason):
    est = estimated_visit_cost(template, prop)
    add_ledger_entry(
        visit["plan_id"], "VISIT_RELEASE", -est,
        source_visit_id=visit["id"],
        memo="VISIT_RELEASE (release-of-commit) for visit %s: %s" % (visit["id"], reason))


# ------------------------------- CRUD --------------------------------------

@bp.route("/pm/visits", methods=["POST"])
def create_visit():
    _, role = auth()
    require_role(role, PM)
    data = body()
    # Stage 3: body refs in declared input order.
    batch = unit = template = asset = plan = None
    if data.get("batch_id") is not None:
        batch = get_batch(data["batch_id"])
    if data.get("unit_id") is not None:
        unit = get_unit(data["unit_id"])
    if data.get("template_id") is not None:
        template = get_template(data["template_id"])
        if template["retired_at"] is not None:
            raise ApiError(E.ERR_TEMPLATE_NOT_FOUND, 404,
                           "Template %s is retired" % template["id"])
    if data.get("asset_id") is not None:
        asset = get_asset(data["asset_id"])
    if data.get("plan_id") is not None:
        plan = get_plan(data["plan_id"])
    # Stage 4: property must be ACTIVE.
    if batch is not None:
        prop = store.properties.get(batch["property_id"])
        require_active_property(prop)
    # Stage 5: decommissioned assets are excluded from PM scheduling.
    if asset is not None and asset["operational_status"] == "DECOMMISSIONED":
        raise ApiError(E.ERR_INVALID_STATE, 409,
                       "Asset %s is DECOMMISSIONED and excluded from scheduling"
                       % asset["id"])
    # Stage 8: batch mutability, then window membership.
    sched_raw = data.get("scheduled_start")
    sched_dt = None
    if sched_raw is not None:
        try:
            sched_dt, _ = parse_dt(sched_raw) if isinstance(sched_raw, str) else (None, None)
        except ValueError:
            sched_dt = None
    if batch is not None:
        if batch["status"] != "DRAFT":
            raise ApiError(E.ERR_BATCH_NOT_MUTABLE, 409,
                           "Visits may only be added to a DRAFT batch")
        if sched_dt is not None and not (batch["_window_start"] <= sched_dt < batch["_window_end"]):
            raise ApiError(E.ERR_VISIT_OUTSIDE_WINDOW, 409,
                           "scheduled_start outside batch [window_start, window_end)")
    # Stage 9: unit entry overlap.
    if unit is not None and template is not None and sched_dt is not None:
        if _unit_overlaps(unit["id"], sched_dt, template):
            raise ApiError(E.ERR_UNIT_ENTRY_OVERLAP, 409,
                           "Visit interval overlaps another visit for the unit")
    # Stage 10: referential coherence.
    if asset is not None and template is not None \
            and asset["component_type"] != template["component_type"]:
        raise ApiError(E.ERR_COMPONENT_MISMATCH, 422,
                       "Asset component_type does not match template component_type")
    if batch is not None and unit is not None and template is not None \
            and asset is not None and plan is not None:
        pid = batch["property_id"]
        b_unit = store.buildings.get(unit["building_id"])
        a_unit = store.units.get(asset["unit_id"])
        b_asset = store.buildings.get(a_unit["building_id"]) if a_unit else None
        refs = [b_unit["property_id"] if b_unit else None,
                template["property_id"],
                b_asset["property_id"] if b_asset else None,
                plan["property_id"]]
        if any(r != pid for r in refs):
            raise ApiError(E.ERR_CROSS_PROPERTY_REFERENCE, 422,
                           "Visit references must all belong to one property")
    # Stage 15: field shape, declared input order.
    bid = v_str(data, "batch_id")
    uid = v_str(data, "unit_id")
    tid = v_str(data, "template_id")
    aid = v_str(data, "asset_id")
    plid = v_str(data, "plan_id")
    sched_raw = v_str(data, "scheduled_start")
    tech = v_str(data, "technician_id")
    try:
        sched_dt, _ = parse_dt(sched_raw)
    except ValueError:
        raise ApiError(E.ERR_INVALID_REQUEST, 400,
                       "scheduled_start is not a valid ISO 8601 datetime")
    # Resolve anything skipped above (fields absent earlier).
    batch = batch or get_batch(bid)
    unit = unit or get_unit(uid)
    if template is None:
        template = get_template(tid)
        if template["retired_at"] is not None:
            raise ApiError(E.ERR_TEMPLATE_NOT_FOUND, 404, "Template is retired")
    asset = asset or get_asset(aid)
    plan = plan or get_plan(plid)
    rec = new_common_fields()
    rec.update({
        "batch_id": batch["id"],
        "unit_id": unit["id"],
        "template_id": template["id"],
        "asset_id": asset["id"],
        "plan_id": plan["id"],
        "scheduled_start": sched_raw,
        "_sched_dt": sched_dt,
        "technician_id": tech,
        "actual_minutes": None,
        "condition_score_recorded": None,
        "visit_status": "SCHEDULED",
        "visit_cost_cents": 0,
    })
    store.visits[rec["id"]] = rec
    # Visit roster is part of the batch's mutable state.
    touch(batch)
    return ok_object(visit_view(rec), 201)


@bp.route("/pm/visits/<visit_id>", methods=["GET"])
def get_visit_route(visit_id):
    _, role = auth()
    require_role(role, ALL)
    v = get_visit(visit_id)
    return ok_object(visit_view(v), 200)


@bp.route("/pm/visits", methods=["GET"])
def list_visits():
    _, role = auth()
    require_role(role, ALL)
    rows = list(store.visits.values())
    for param, field in (("batch_id", "batch_id"), ("unit_id", "unit_id"),
                         ("template_id", "template_id"), ("asset_id", "asset_id"),
                         ("plan_id", "plan_id"), ("visit_status", "visit_status")):
        val = request.args.get(param)
        if val is not None:
            rows = [v for v in rows if v[field] == val]
    page, limit, offset, total = paginate(rows)
    return ok_list([visit_view(v) for v in page], limit, offset, total)


# --------------------------- Execution actions ------------------------------

@bp.route("/pm/visits/<visit_id>/start", methods=["POST"])
def start_visit(visit_id):
    uid, role = auth()
    require_role(role, TECH)
    v = get_visit(visit_id)
    require_technician_identity(uid, v["technician_id"])
    prop = property_of_visit(v)
    require_active_property(prop)
    if v["visit_status"] != "NOTIFIED":
        raise ApiError(E.ERR_INVALID_STATE, 409,
                       "Visit in %s cannot be started" % v["visit_status"])
    clock = now()
    if clock < v["_sched_dt"]:
        raise ApiError(E.ERR_VISIT_TOO_EARLY, 409,
                       "Current time is before scheduled_start")
    unit = store.units.get(v["unit_id"])
    if unit is not None and unit["occupancy_status"] == "OCCUPIED":
        batch = store.batches.get(v["batch_id"])
        earliest = batch["_notice_dt"] + timedelta(hours=prop["notice_lead_hours"])
        if clock < earliest:
            raise ApiError(E.ERR_NOTICE_LEAD_VIOLATION, 409,
                           "Resident notice lead time has not elapsed")
    v["visit_status"] = "IN_PROGRESS"
    touch(v)
    return ok_object(visit_view(v), 200)


@bp.route("/pm/visits/<visit_id>/complete", methods=["POST"])
def complete_visit(visit_id):
    uid, role = auth()
    require_role(role, TECH)
    v = get_visit(visit_id)
    require_technician_identity(uid, v["technician_id"])
    prop = property_of_visit(v)
    require_active_property(prop)
    if v["visit_status"] != "IN_PROGRESS":
        raise ApiError(E.ERR_INVALID_STATE, 409,
                       "Visit in %s cannot be completed" % v["visit_status"])
    template = store.templates[v["template_id"]]
    # Stage 11: evidence requirement.
    if template["requires_evidence"]:
        has_ev = any(e for e in store.evidence.values() if e["visit_id"] == v["id"])
        if not has_ev:
            raise ApiError(E.ERR_EVIDENCE_REQUIRED, 422,
                           "Template requires at least one compliance evidence row")
    data = body()
    # Stage 15: payload shape.
    minutes = v_int(data, "actual_minutes", minv=1)
    score = v_int(data, "condition_score_recorded", minv=1, maxv=5)
    # Side effects.
    v["actual_minutes"] = minutes
    v["condition_score_recorded"] = score
    v["visit_status"] = "COMPLETED"
    v["visit_cost_cents"] = actual_visit_cost(minutes, prop)
    touch(v)
    _release_visit_commit(v, prop, template, "completion releases committed estimate")
    add_ledger_entry(
        v["plan_id"], "VISIT_SETTLE", v["visit_cost_cents"],
        source_visit_id=v["id"],
        memo="VISIT_SETTLE for visit %s at completion" % v["id"])
    asset = store.assets.get(v["asset_id"])
    if asset is not None:
        asset["condition_score"] = score
        touch(asset)
        recompute_asset_compliance(asset, bump=False)
    batch = store.batches.get(v["batch_id"])
    if batch is not None:
        maybe_execute_batch(batch)
    return ok_object(visit_view(v), 200)


@bp.route("/pm/visits/<visit_id>/no-access", methods=["POST"])
def no_access_visit(visit_id):
    uid, role = auth()
    require_role(role, TECH)
    v = get_visit(visit_id)
    require_technician_identity(uid, v["technician_id"])
    prop = property_of_visit(v)
    require_active_property(prop)
    if v["visit_status"] != "NOTIFIED":
        raise ApiError(E.ERR_INVALID_STATE, 409,
                       "Visit in %s cannot be recorded NO_ACCESS" % v["visit_status"])
    if now() < v["_sched_dt"]:
        raise ApiError(E.ERR_VISIT_TOO_EARLY, 409,
                       "Current time is before scheduled_start")
    v["visit_status"] = "NO_ACCESS"
    touch(v)
    template = store.templates[v["template_id"]]
    _release_visit_commit(v, prop, template, "no access; failed entry releases estimate")
    batch = store.batches.get(v["batch_id"])
    if batch is not None:
        maybe_execute_batch(batch)
    return ok_object(visit_view(v), 200)


@bp.route("/pm/visits/<visit_id>/reschedule", methods=["POST"])
def reschedule_visit(visit_id):
    _, role = auth()
    require_role(role, PM)
    v = get_visit(visit_id)
    data = body()
    target = None
    if data.get("target_batch_id") is not None:
        target = get_batch(data["target_batch_id"])
    prop = property_of_visit(v)
    require_active_property(prop)
    if v["visit_status"] != "NO_ACCESS":
        raise ApiError(E.ERR_INVALID_STATE, 409,
                       "Only a NO_ACCESS visit can be rescheduled")
    # Stage 8: target window membership, then target batch mutability.
    sched_raw = data.get("new_scheduled_start")
    sched_dt = None
    if isinstance(sched_raw, str):
        try:
            sched_dt, _ = parse_dt(sched_raw)
        except ValueError:
            sched_dt = None
    if target is not None:
        if sched_dt is not None and not (target["_window_start"] <= sched_dt < target["_window_end"]):
            raise ApiError(E.ERR_VISIT_OUTSIDE_WINDOW, 409,
                           "new_scheduled_start outside target batch window")
        if target["status"] not in ("DRAFT", "PUBLISHED"):
            raise ApiError(E.ERR_BATCH_NOT_MUTABLE, 409,
                           "Target batch in %s is not mutable" % target["status"])
    # Stage 9: overlap against the unit's other visits.
    if sched_dt is not None:
        template = store.templates[v["template_id"]]
        if _unit_overlaps(v["unit_id"], sched_dt, template, exclude_visit_id=v["id"]):
            raise ApiError(E.ERR_UNIT_ENTRY_OVERLAP, 409,
                           "Rescheduled interval overlaps another visit for the unit")
    # Stage 15: field shape.
    tbid = v_str(data, "target_batch_id")
    sched_raw = v_str(data, "new_scheduled_start")
    try:
        sched_dt, _ = parse_dt(sched_raw)
    except ValueError:
        raise ApiError(E.ERR_INVALID_REQUEST, 400,
                       "new_scheduled_start is not a valid ISO 8601 datetime")
    target = target or get_batch(tbid)
    v["batch_id"] = target["id"]
    v["scheduled_start"] = sched_raw
    v["_sched_dt"] = sched_dt
    if target["status"] == "PUBLISHED":
        v["visit_status"] = "NOTIFIED"
        touch(v)
        tprop = store.properties.get(target["property_id"])
        template = store.templates[v["template_id"]]
        est = estimated_visit_cost(template, tprop)
        add_ledger_entry(
            v["plan_id"], "VISIT_COMMIT", est,
            source_visit_id=v["id"],
            memo="VISIT_COMMIT for visit %s on reschedule into published batch %s"
                 % (v["id"], target["id"]))
    else:
        v["visit_status"] = "SCHEDULED"
        touch(v)
    return ok_object(visit_view(v), 200)


@bp.route("/pm/visits/<visit_id>/cancel", methods=["POST"])
def cancel_visit(visit_id):
    _, role = auth()
    require_role(role, PM)
    v = get_visit(visit_id)
    prop = property_of_visit(v)
    require_active_property(prop)
    if v["visit_status"] not in ("SCHEDULED", "NOTIFIED"):
        raise ApiError(E.ERR_INVALID_STATE, 409,
                       "Visit in %s cannot be cancelled" % v["visit_status"])
    batch = store.batches.get(v["batch_id"])
    if batch is not None and batch["status"] in ("LOCKED", "EXECUTED", "CANCELLED"):
        raise ApiError(E.ERR_BATCH_NOT_MUTABLE, 409,
                       "Containing batch in %s is not mutable" % batch["status"])
    was_committed = v["visit_status"] == "NOTIFIED"
    v["visit_status"] = "CANCELLED"
    touch(v)
    if was_committed:
        template = store.templates[v["template_id"]]
        _release_visit_commit(v, prop, template, "cancellation releases committed estimate")
    if batch is not None:
        maybe_execute_batch(batch)
    return ok_object(visit_view(v), 200)


# --------------------------- Evidence / audit -------------------------------

@bp.route("/pm/visits/<visit_id>/evidence", methods=["POST"])
def create_evidence(visit_id):
    uid, role = auth()
    require_role(role, TECH)
    v = get_visit(visit_id)
    require_active_property(property_of_visit(v))
    data = body()
    etype = v_enum(data, "evidence_type", EVIDENCE_TYPES)
    serial = v_str(data, "serial_or_lot")
    notes = data.get("notes", "")
    if notes is None:
        notes = ""
    if not isinstance(notes, str):
        raise ApiError(E.ERR_INVALID_REQUEST, 400, "notes must be a string")
    rec = new_append_fields()
    rec.update({
        "visit_id": v["id"],
        "evidence_type": etype,
        "serial_or_lot": serial,
        "notes": notes,
        "recorded_by": uid,
    })
    store.evidence[rec["id"]] = rec
    return ok_object(evidence_view(rec), 201)


@bp.route("/pm/visits/<visit_id>/evidence", methods=["GET"])
def list_evidence(visit_id):
    _, role = auth()
    require_role(role, ALL)
    v = get_visit(visit_id)
    rows = [e for e in store.evidence.values() if e["visit_id"] == v["id"]]
    page, limit, offset, total = paginate(rows)
    return ok_list([evidence_view(e) for e in page], limit, offset, total)


@bp.route("/pm/visits/<visit_id>/audit", methods=["POST"])
def create_audit(visit_id):
    uid, role = auth()
    require_role(role, ("ComplianceAuditor",))
    v = get_visit(visit_id)
    require_active_property(property_of_visit(v))
    if v["visit_status"] != "COMPLETED":
        raise ApiError(E.ERR_INVALID_STATE, 409,
                       "Only a COMPLETED visit can be audited")
    if any(a for a in store.audits.values() if a["visit_id"] == v["id"]):
        raise ApiError(E.ERR_INVALID_STATE, 409,
                       "Visit already has a completion audit")
    # Stage 12: segregation of duties.
    if uid == v["technician_id"]:
        raise ApiError(E.ERR_SEGREGATION_OF_DUTIES, 422,
                       "Auditor may not certify their own work")
    data = body()
    outcome = v_enum(data, "outcome", ("PASS", "FAIL"))
    fail_reason = data.get("fail_reason")
    if outcome == "FAIL":
        if not isinstance(fail_reason, str) or not fail_reason.strip():
            raise ApiError(E.ERR_INVALID_REQUEST, 400,
                           "fail_reason is required when outcome is FAIL")
    rec = new_append_fields()
    rec.update({
        "visit_id": v["id"],
        "auditor_id": uid,
        "outcome": outcome,
        "fail_reason": fail_reason if outcome == "FAIL" else None,
        "audited_at": fmt_ts(now()),
    })
    store.audits[rec["id"]] = rec
    asset = store.assets.get(v["asset_id"])
    if asset is not None:
        if outcome == "FAIL":
            asset["compliance_status"] = "NON_COMPLIANT"
            touch(asset)
        else:
            recompute_asset_compliance(asset)
    return ok_object(audit_view(rec), 201)


@bp.route("/pm/visits/<visit_id>/audit", methods=["GET"])
def get_audit(visit_id):
    _, role = auth()
    require_role(role, ALL)
    v = get_visit(visit_id)
    rows = [a for a in store.audits.values() if a["visit_id"] == v["id"]]
    page, limit, offset, total = paginate(rows)
    return ok_list([audit_view(a) for a in page], limit, offset, total)


# ------------------------------ Visit ledger --------------------------------

@bp.route("/pm/visits/<visit_id>/ledger-entries", methods=["GET"])
def visit_ledger(visit_id):
    _, role = auth()
    require_role(role, LEDGER_READ)
    v = get_visit(visit_id)
    rows = [e for e in store.ledger.values() if e["source_visit_id"] == v["id"]]
    page, limit, offset, total = paginate(rows)
    return ok_list([ledger_view(e) for e in page], limit, offset, total)
