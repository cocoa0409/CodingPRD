"""Corrective work orders: creation (OCC-guarded), review doorway, execution,
verification with clawback (PRD §3.5, §3.6)."""
from flask import Blueprint, request

import errors as E
from errors import ApiError
from db import store, new_common_fields, touch
from middleware import (auth, require_role, require_technician_identity, body,
                        v_str, v_int, v_bool, v_enum, paginate)
from response import ok_object, ok_list
from services.core import (get_deficiency, get_plan, get_work_order, get_asset,
                           property_of_deficiency, property_of_work_order,
                           require_active_property)
from services.compliance import add_ledger_entry, committed_cents
from services.serializers import work_order_view, ledger_view

bp = Blueprint("work_orders", __name__)

PM = ("PropertyManager",)
TECH = ("Technician",)
AUDIT = ("ComplianceAuditor",)
ALL = ("PropertyManager", "Technician", "ComplianceAuditor")
LEDGER_READ = ("PropertyManager", "ComplianceAuditor")


@bp.route("/pm/work-orders", methods=["POST"])
def create_work_order():
    _, role = auth()
    require_role(role, PM)
    data = body()
    # Stage 3: body refs in declared input order (deficiency_id, plan_id).
    deficiency = plan = None
    if data.get("deficiency_id") is not None:
        deficiency = get_deficiency(data["deficiency_id"])
    if data.get("plan_id") is not None:
        plan = get_plan(data["plan_id"])
    # Stage 4: owning property must be ACTIVE.
    if deficiency is not None:
        require_active_property(property_of_deficiency(deficiency))
    # Stage 5: deficiency must be TRIAGED and not already bound to a live WO.
    if deficiency is not None:
        if deficiency["status"] != "TRIAGED":
            raise ApiError(E.ERR_INVALID_STATE, 409,
                           "Deficiency in %s cannot be converted" % deficiency["status"])
        if deficiency["work_order_id"] is not None:
            existing = store.work_orders.get(deficiency["work_order_id"])
            if existing is not None and existing["status"] != "REJECTED":
                raise ApiError(E.ERR_INVALID_STATE, 409,
                               "Deficiency already has a corrective work order")
    # Stage 6: OCC on the deficiency version.
    if "expected_deficiency_version" not in data or data["expected_deficiency_version"] is None:
        raise ApiError(E.ERR_INVALID_REQUEST, 400,
                       "expected_deficiency_version is required")
    if not isinstance(data["expected_deficiency_version"], int) \
            or isinstance(data["expected_deficiency_version"], bool):
        raise ApiError(E.ERR_INVALID_REQUEST, 400,
                       "expected_deficiency_version must be an integer")
    if deficiency is not None and data["expected_deficiency_version"] != deficiency["version"]:
        raise ApiError(E.ERR_STALE_VERSION, 412,
                       "expected_deficiency_version does not match the deficiency's version")
    # Stage 15: field shape.
    did = v_str(data, "deficiency_id")
    plid = v_str(data, "plan_id")
    est = v_int(data, "estimated_cost_cents", minv=1)
    tech = v_str(data, "assigned_technician_id")
    replace = v_bool(data, "replace_asset", required=False, default=False)
    deficiency = deficiency or get_deficiency(did)
    plan = plan or get_plan(plid)
    visit = store.visits.get(deficiency["visit_id"])
    batch = store.batches.get(visit["batch_id"]) if visit else None
    rec = new_common_fields()
    rec.update({
        "property_id": batch["property_id"] if batch else None,
        "deficiency_id": deficiency["id"],
        "plan_id": plan["id"],
        "asset_id": deficiency["asset_id"],
        "estimated_cost_cents": est,
        "actual_cost_cents": None,
        "assigned_technician_id": tech,
        "replace_asset": replace,
        "status": "OPEN",
        "revision_count": 0,
        "_commit_outstanding": False,
    })
    store.work_orders[rec["id"]] = rec
    # Deep transitive coupling: link set + version bump; status stays TRIAGED.
    deficiency["work_order_id"] = rec["id"]
    touch(deficiency)
    return ok_object(work_order_view(rec), 201)


@bp.route("/pm/work-orders/<wo_id>", methods=["GET"])
def get_work_order_route(wo_id):
    _, role = auth()
    require_role(role, ALL)
    wo = get_work_order(wo_id)
    return ok_object(work_order_view(wo), 200)


@bp.route("/pm/work-orders", methods=["GET"])
def list_work_orders():
    _, role = auth()
    require_role(role, ALL)
    rows = list(store.work_orders.values())
    for param, field in (("property_id", "property_id"), ("deficiency_id", "deficiency_id"),
                         ("plan_id", "plan_id"), ("asset_id", "asset_id"),
                         ("status", "status")):
        val = request.args.get(param)
        if val is not None:
            rows = [w for w in rows if w[field] == val]
    page, limit, offset, total = paginate(rows)
    return ok_list([work_order_view(w) for w in page], limit, offset, total)


@bp.route("/pm/work-orders/<wo_id>/submit-review", methods=["POST"])
def submit_review(wo_id):
    uid, role = auth()
    require_role(role, TECH)
    wo = get_work_order(wo_id)
    require_technician_identity(uid, wo["assigned_technician_id"])
    require_active_property(property_of_work_order(wo))
    if wo["status"] != "OPEN":
        raise ApiError(E.ERR_INVALID_STATE, 409,
                       "Work order in %s cannot be submitted for review" % wo["status"])
    wo["status"] = "IN_REVIEW"
    touch(wo)
    return ok_object(work_order_view(wo), 200)


@bp.route("/pm/work-orders/<wo_id>/approve", methods=["POST"])
def approve(wo_id):
    _, role = auth()
    require_role(role, PM)
    wo = get_work_order(wo_id)
    require_active_property(property_of_work_order(wo))
    if wo["status"] != "IN_REVIEW":
        raise ApiError(E.ERR_INVALID_STATE, 409,
                       "Work order in %s cannot be approved" % wo["status"])
    # Stage 13: plan adoption checked before budget headroom.
    plan = store.plans.get(wo["plan_id"])
    if plan is None or plan["status"] != "ADOPTED":
        raise ApiError(E.ERR_PLAN_NOT_ADOPTED, 402,
                       "Plan must be ADOPTED before approval")
    if committed_cents(plan["id"]) + wo["estimated_cost_cents"] > plan["budget_cents"]:
        raise ApiError(E.ERR_BUDGET_EXCEEDED, 402,
                       "Plan budget would be exceeded by this approval")
    wo["status"] = "APPROVED"
    wo["_commit_outstanding"] = True
    touch(wo)
    add_ledger_entry(
        wo["plan_id"], "WO_COMMIT", wo["estimated_cost_cents"],
        source_work_order_id=wo["id"],
        memo="WO_COMMIT for work order %s at approval" % wo["id"])
    return ok_object(work_order_view(wo), 200)


@bp.route("/pm/work-orders/<wo_id>/return-rework", methods=["POST"])
def return_rework(wo_id):
    _, role = auth()
    require_role(role, PM)
    wo = get_work_order(wo_id)
    require_active_property(property_of_work_order(wo))
    if wo["status"] != "IN_REVIEW":
        raise ApiError(E.ERR_INVALID_STATE, 409,
                       "Work order in %s cannot be returned for rework" % wo["status"])
    wo["status"] = "OPEN"
    wo["revision_count"] += 1
    touch(wo)
    return ok_object(work_order_view(wo), 200)


@bp.route("/pm/work-orders/<wo_id>/reject", methods=["POST"])
def reject(wo_id):
    _, role = auth()
    require_role(role, PM)
    wo = get_work_order(wo_id)
    require_active_property(property_of_work_order(wo))
    if wo["status"] != "IN_REVIEW":
        raise ApiError(E.ERR_INVALID_STATE, 409,
                       "Work order in %s cannot be rejected" % wo["status"])
    wo["status"] = "REJECTED"
    touch(wo)
    deficiency = store.deficiencies.get(wo["deficiency_id"])
    if deficiency is not None:
        deficiency["status"] = "TRIAGED"
        touch(deficiency)
    return ok_object(work_order_view(wo), 200)


@bp.route("/pm/work-orders/<wo_id>/start", methods=["POST"])
def start_wo(wo_id):
    uid, role = auth()
    require_role(role, TECH)
    wo = get_work_order(wo_id)
    require_technician_identity(uid, wo["assigned_technician_id"])
    require_active_property(property_of_work_order(wo))
    if wo["status"] != "APPROVED":
        raise ApiError(E.ERR_INVALID_STATE, 409,
                       "Work order in %s cannot be started" % wo["status"])
    wo["status"] = "IN_PROGRESS"
    touch(wo)
    asset = store.assets.get(wo["asset_id"])
    if asset is not None:
        asset["operational_status"] = "OUT_OF_SERVICE"
        touch(asset)
    return ok_object(work_order_view(wo), 200)


@bp.route("/pm/work-orders/<wo_id>/complete", methods=["POST"])
def complete_wo(wo_id):
    uid, role = auth()
    require_role(role, TECH)
    wo = get_work_order(wo_id)
    require_technician_identity(uid, wo["assigned_technician_id"])
    data = body()
    # Stage 3 (conditional reference): new_asset_id when replace_asset.
    new_asset = None
    if wo["replace_asset"]:
        raw_new = data.get("new_asset_id")
        if raw_new is None:
            raise ApiError(E.ERR_ASSET_NOT_FOUND, 404,
                           "new_asset_id is required when replace_asset is true")
        new_asset = get_asset(raw_new)
    elif data.get("new_asset_id") is not None:
        new_asset = get_asset(data["new_asset_id"])
    require_active_property(property_of_work_order(wo))
    if wo["status"] != "IN_PROGRESS":
        raise ApiError(E.ERR_INVALID_STATE, 409,
                       "Work order in %s cannot be completed" % wo["status"])
    if wo["replace_asset"] and new_asset is not None:
        old_asset = store.assets.get(wo["asset_id"])
        if new_asset["operational_status"] != "IN_SERVICE" \
                or old_asset is None or new_asset["unit_id"] != old_asset["unit_id"]:
            raise ApiError(E.ERR_INVALID_STATE, 409,
                           "new_asset_id must reference an IN_SERVICE asset in the same unit")
    actual = v_int(data, "actual_cost_cents", minv=0)
    # Side effects.
    wo["actual_cost_cents"] = actual
    wo["status"] = "COMPLETED"
    touch(wo)
    if wo["_commit_outstanding"]:
        add_ledger_entry(
            wo["plan_id"], "WO_RELEASE", -wo["estimated_cost_cents"],
            source_work_order_id=wo["id"],
            memo="WO_RELEASE (release-of-commit) for work order %s at completion" % wo["id"])
        wo["_commit_outstanding"] = False
    add_ledger_entry(
        wo["plan_id"], "WO_SETTLE", actual,
        source_work_order_id=wo["id"],
        memo="WO_SETTLE for work order %s at completion" % wo["id"])
    asset = store.assets.get(wo["asset_id"])
    if asset is not None:
        if wo["replace_asset"]:
            asset["operational_status"] = "DECOMMISSIONED"
            asset["superseded_by_asset_id"] = new_asset["id"] if new_asset else None
        else:
            asset["operational_status"] = "IN_SERVICE"
        touch(asset)
    deficiency = store.deficiencies.get(wo["deficiency_id"])
    if deficiency is not None:
        deficiency["status"] = "CONVERTED"
        touch(deficiency)
    return ok_object(work_order_view(wo), 200)


@bp.route("/pm/work-orders/<wo_id>/verify", methods=["POST"])
def verify_wo(wo_id):
    uid, role = auth()
    require_role(role, AUDIT)
    wo = get_work_order(wo_id)
    require_active_property(property_of_work_order(wo))
    if wo["status"] != "COMPLETED":
        raise ApiError(E.ERR_INVALID_STATE, 409,
                       "Work order in %s cannot be verified" % wo["status"])
    # Stage 12: segregation of duties.
    if uid == wo["assigned_technician_id"]:
        raise ApiError(E.ERR_SEGREGATION_OF_DUTIES, 422,
                       "Auditor may not verify their own work")
    data = body()
    outcome = v_enum(data, "outcome", ("PASS", "FAIL"))
    if outcome == "PASS":
        wo["status"] = "VERIFIED"
        touch(wo)
    else:
        wo["status"] = "IN_PROGRESS"
        touch(wo)
        add_ledger_entry(
            wo["plan_id"], "WO_RELEASE", -(wo["actual_cost_cents"] or 0),
            source_work_order_id=wo["id"],
            memo="WO_RELEASE (release-of-settle) for work order %s: verification failed clawback"
                 % wo["id"])
        asset = store.assets.get(wo["asset_id"])
        if asset is not None:
            asset["operational_status"] = "OUT_OF_SERVICE"
            touch(asset)
        deficiency = store.deficiencies.get(wo["deficiency_id"])
        if deficiency is not None:
            deficiency["status"] = "TRIAGED"
            touch(deficiency)
    return ok_object(work_order_view(wo), 200)


@bp.route("/pm/work-orders/<wo_id>/ledger-entries", methods=["GET"])
def wo_ledger(wo_id):
    _, role = auth()
    require_role(role, LEDGER_READ)
    wo = get_work_order(wo_id)
    rows = [e for e in store.ledger.values() if e["source_work_order_id"] == wo["id"]]
    page, limit, offset, total = paginate(rows)
    return ok_list([ledger_view(e) for e in page], limit, offset, total)
