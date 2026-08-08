"""Routes: asset components and QRE line items."""
from flask import request
from core import (db, ApiError, ok, ok_list, require_role, get_body,
                  require_fields, paginate, sort_key, base_fields, touch)
from serializers import ser_component, ser_qre
from calc import RECOVERY_PERIOD, qre_qualified_amount
from routes_core import get_or_404, is_int, is_number

ASSET_CLASSES = {"FIVE_YEAR", "SEVEN_YEAR", "FIFTEEN_YEAR", "THIRTY_NINE_YEAR"}
QRE_CATEGORIES = {"WAGES", "SUPPLIES", "CONTRACT_RESEARCH"}


def register(app):
    # ---------------- AssetComponent ----------------
    @app.route("/studies/<sid>/asset-components", methods=["POST"])
    def add_component(sid):
        require_role("Engineer")
        s = get_or_404(db.studies, sid)
        if s["study_type"] != "COST_SEGREGATION":
            raise ApiError("ERR_STUDY_TYPE_MISMATCH", 409, "Study is not COST_SEGREGATION")
        body = get_body()
        require_fields(body, "component_name", "asset_class", "allocated_cost_cents")
        if body["asset_class"] not in ASSET_CLASSES:
            raise ApiError("ERR_VALIDATION", 400, "Invalid asset_class")
        cost = body["allocated_cost_cents"]
        if not is_int(cost):
            raise ApiError("ERR_VALIDATION", 400, "allocated_cost_cents must be an integer")
        if cost <= 0:
            raise ApiError("ERR_INVALID_AMOUNT", 422, "allocated_cost_cents must be > 0")
        c = base_fields()
        c.update({
            "study_id": s["id"],
            "component_name": body["component_name"],
            "asset_class": body["asset_class"],
            "allocated_cost_cents": cost,
            "recovery_period_years": RECOVERY_PERIOD[body["asset_class"]],
            "status": "PROPOSED",
        })
        db.asset_components[c["id"]] = c
        return ok(ser_component(c), 201)

    @app.route("/studies/<sid>/asset-components", methods=["GET"])
    def list_components(sid):
        require_role("StudyManager", "Engineer", "Reviewer", "CPA")
        get_or_404(db.studies, sid)
        limit, offset = paginate(request.args)
        items = [c for c in db.asset_components.values() if c["study_id"] == sid]
        items.sort(key=sort_key)
        total = len(items)
        page = items[offset:offset + limit]
        return ok_list([ser_component(c) for c in page], limit, offset, total)

    @app.route("/asset-components/<cid>/allocate", methods=["POST"])
    def allocate_component(cid):
        require_role("Engineer")
        c = get_or_404(db.asset_components, cid)
        s = db.studies.get(c["study_id"])
        if s is None or s["status"] != "ENGINEERING":
            raise ApiError("ERR_INVALID_STATE", 409, "Parent study not in ENGINEERING")
        if c["status"] != "PROPOSED":
            raise ApiError("ERR_INVALID_STATE", 409, "Component not PROPOSED")
        prop = db.properties.get(s.get("property_id"))
        basis = prop["depreciable_basis_cents"] if prop else 0
        if s["total_allocated_cost_cents"] + c["allocated_cost_cents"] > basis:
            raise ApiError("ERR_ALLOCATION_EXCEEDS_BASIS", 409, "Allocation exceeds basis")
        c["status"] = "ALLOCATED"
        touch(c)
        s["total_allocated_cost_cents"] += c["allocated_cost_cents"]
        touch(s)
        return ok(ser_component(c))

    @app.route("/asset-components/<cid>/exclude", methods=["POST"])
    def exclude_component(cid):
        require_role("Engineer")
        c = get_or_404(db.asset_components, cid)
        if c["status"] == "EXCLUDED":
            raise ApiError("ERR_INVALID_STATE", 409, "Component already EXCLUDED")
        was_allocated = c["status"] == "ALLOCATED"
        c["status"] = "EXCLUDED"
        touch(c)
        if was_allocated:
            s = db.studies.get(c["study_id"])
            if s is not None:
                s["total_allocated_cost_cents"] -= c["allocated_cost_cents"]
                touch(s)
        return ok(ser_component(c))

    # ---------------- QreLineItem ----------------
    @app.route("/studies/<sid>/qre-line-items", methods=["POST"])
    def add_qre(sid):
        require_role("Engineer")
        s = get_or_404(db.studies, sid)
        if s["study_type"] != "RD_CREDIT":
            raise ApiError("ERR_STUDY_TYPE_MISMATCH", 409, "Study is not RD_CREDIT")
        body = get_body()
        require_fields(body, "qre_category", "gross_amount_cents", "qualified_percent")
        if body["qre_category"] not in QRE_CATEGORIES:
            raise ApiError("ERR_VALIDATION", 400, "Invalid qre_category")
        gross = body["gross_amount_cents"]
        pct = body["qualified_percent"]
        if not is_int(gross):
            raise ApiError("ERR_VALIDATION", 400, "gross_amount_cents must be an integer")
        if not is_number(pct):
            raise ApiError("ERR_VALIDATION", 400, "qualified_percent must be a number")
        if gross <= 0:
            raise ApiError("ERR_INVALID_AMOUNT", 422, "gross_amount_cents must be > 0")
        if pct <= 0 or pct > 1:
            raise ApiError("ERR_INVALID_AMOUNT", 422, "qualified_percent out of range")
        q = base_fields()
        q.update({
            "study_id": s["id"],
            "qre_category": body["qre_category"],
            "gross_amount_cents": gross,
            "qualified_percent": pct,
            "qualified_amount_cents": 0,
            "status": "DRAFT",
        })
        db.qre_line_items[q["id"]] = q
        return ok(ser_qre(q), 201)

    @app.route("/studies/<sid>/qre-line-items", methods=["GET"])
    def list_qre(sid):
        require_role("StudyManager", "Engineer", "Reviewer", "CPA")
        get_or_404(db.studies, sid)
        limit, offset = paginate(request.args)
        items = [q for q in db.qre_line_items.values() if q["study_id"] == sid]
        items.sort(key=sort_key)
        total = len(items)
        page = items[offset:offset + limit]
        return ok_list([ser_qre(q) for q in page], limit, offset, total)

    @app.route("/qre-line-items/<qid>/qualify", methods=["POST"])
    def qualify_qre(qid):
        require_role("Engineer")
        q = get_or_404(db.qre_line_items, qid)
        s = db.studies.get(q["study_id"])
        if s is None or s["status"] != "ENGINEERING":
            raise ApiError("ERR_INVALID_STATE", 409, "Parent study not in ENGINEERING")
        if q["status"] != "DRAFT":
            raise ApiError("ERR_INVALID_STATE", 409, "Line not DRAFT")
        q["qualified_amount_cents"] = qre_qualified_amount(q)
        q["status"] = "QUALIFIED"
        touch(q)
        return ok(ser_qre(q))
