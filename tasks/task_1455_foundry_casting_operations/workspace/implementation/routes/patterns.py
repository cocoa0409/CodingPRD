"""Pattern tooling, shrink allowance, qualification, retirement (PRD 3.2)."""

from decimal import Decimal

from flask import request

from db import all_of, get, new_record, touch
from errors import fail
from middleware import auth, paged, require_role
from response import ok_list, ok_object
from services import MA_CAP, QUALIFY_TOL_MM, SHRINK
from util import (D, as_enum, as_pos_int, as_nonneg_num, as_str, body_dict,
                  opt, q1, req)

PATTERN_GET_ROLES = {"FoundryAdmin", "PatternMaker", "LineOperator", "Customer"}


def _compute_pattern_dimensions(finish_dims, machining_allowance, shrink_class, process):
    """pattern_dimensions rule: per-axis round_half_up to 1 dp; never round sums."""
    eff_ma = min(machining_allowance, MA_CAP[process])
    shrink = SHRINK[(shrink_class, process)]
    return [q1((D(f) + eff_ma) * (Decimal("1") + shrink)) for f in finish_dims]


def register(app):
    @app.route("/api/patterns", methods=["POST"])
    def create_pattern():
        auth_user, role = auth()
        require_role(role, {"PatternMaker"})
        body = body_dict(request.get_json(silent=True))
        foundry_id = as_str(req(body, "foundry_id"), "foundry_id")
        part_number = as_str(req(body, "part_number"), "part_number")
        shrink_class = as_enum(req(body, "alloy_shrink_class"), "alloy_shrink_class",
                               {"FERROUS", "ALUMINUM"})
        process = as_enum(req(body, "mold_process"), "mold_process",
                          {"SAND", "INVESTMENT"})
        finish = req(body, "finish_dimensions_mm")
        if (not isinstance(finish, list) or not (1 <= len(finish) <= 5)
                or any(isinstance(x, bool) or not isinstance(x, (int, float)) for x in finish)):
            fail("ERR_INVALID_REQUEST",
                 "finish_dimensions_mm must be an array of 1..5 numbers")
        finish = [D(x, "finish_dimensions_mm") for x in finish]
        if any(x < 0 for x in finish):
            fail("ERR_INVALID_REQUEST", "finish_dimensions_mm must not be negative")
        ma = as_nonneg_num(req(body, "machining_allowance_mm"), "machining_allowance_mm")
        impressions = as_pos_int(req(body, "impressions"), "impressions")
        parent_id = opt(body, "parent_pattern_id")

        if get("foundries", foundry_id) is None:
            fail("ERR_NOT_FOUND", "foundry not found")
        if parent_id is not None:
            if not isinstance(parent_id, str):
                fail("ERR_INVALID_REQUEST", "parent_pattern_id must be a string")
            parent = get("patterns", parent_id)
            # cross-foundry references resolve as not found (PRD 2.11)
            if parent is None or parent["foundry_id"] != foundry_id:
                fail("ERR_NOT_FOUND", "parent pattern not found")
            # parent already has an ACTIVE child revision -> reject creation
            for p in all_of("patterns"):
                if (p["parent_pattern_id"] == parent_id and p["status"] == "ACTIVE"):
                    fail("ERR_ACTIVE_REVISION_EXISTS",
                         "parent pattern already has an ACTIVE child revision")

        rec = new_record("patterns", {
            "foundry_id": foundry_id,
            "parent_pattern_id": parent_id,
            "part_number": part_number,
            "alloy_shrink_class": shrink_class,
            "mold_process": process,
            "finish_dimensions_mm": finish,
            "machining_allowance_mm": ma,
            "impressions": impressions,
            "pattern_dimensions_mm": _compute_pattern_dimensions(
                finish, ma, shrink_class, process),
            "qualification_attempts": 0,
            "status": "DRAFT",
        })
        return ok_object(rec, 201)

    @app.route("/api/patterns/<pid>", methods=["GET"])
    def get_pattern(pid):
        auth_user, role = auth()
        require_role(role, PATTERN_GET_ROLES)
        rec = get("patterns", pid)
        if rec is None:
            fail("ERR_NOT_FOUND", "pattern not found")
        return ok_object(rec, 200)

    @app.route("/api/patterns", methods=["GET"])
    def list_patterns():
        auth_user, role = auth()
        require_role(role, PATTERN_GET_ROLES)
        foundry_id = request.args.get("foundry_id")
        parent_id = request.args.get("parent_pattern_id")
        status = request.args.get("status")
        recs = list(all_of("patterns"))
        if foundry_id is not None:
            recs = [p for p in recs if p["foundry_id"] == foundry_id]
        if parent_id is not None:
            recs = [p for p in recs if p["parent_pattern_id"] == parent_id]
        if status is not None:
            recs = [p for p in recs if p["status"] == status]
        page, limit, offset, total = paged(recs)
        return ok_list(page, limit, offset, total)

    @app.route("/api/patterns/<pid>/qualify", methods=["POST"])
    def qualify_pattern(pid):
        auth_user, role = auth()
        require_role(role, {"PatternMaker"})
        rec = get("patterns", pid)
        if rec is None:
            fail("ERR_NOT_FOUND", "pattern not found")
        if rec["status"] in ("SUPERSEDED", "RETIRED"):
            fail("ERR_ALREADY_TERMINAL", "pattern is in a terminal state")
        if rec["status"] != "DRAFT":
            fail("ERR_INVALID_STATE", "only a DRAFT pattern can be qualified")
        body = body_dict(request.get_json(silent=True))
        measured = req(body, "measured_dimensions_mm")
        if (not isinstance(measured, list)
                or len(measured) != len(rec["finish_dimensions_mm"])
                or any(isinstance(x, bool) or not isinstance(x, (int, float)) for x in measured)):
            fail("ERR_INVALID_REQUEST",
                 "measured_dimensions_mm must match finish_dimensions_mm axes")

        rec["qualification_attempts"] += 1
        # QUALIFICATION is transient; evaluate immediately (PRD 3.2)
        passed = all(
            abs(D(m) - pd) <= QUALIFY_TOL_MM
            for m, pd in zip(measured, rec["pattern_dimensions_mm"])
        )
        if passed:
            parent = get("patterns", rec["parent_pattern_id"]) if rec["parent_pattern_id"] else None
            # guard 1: parent (if any) must still be ACTIVE at this moment
            if rec["parent_pattern_id"] is not None and (
                    parent is None or parent["status"] != "ACTIVE"):
                touch(rec)
                fail("ERR_ACTIVE_REVISION_EXISTS",
                     "parent revision is no longer ACTIVE")
            # guard 2: no other ACTIVE pattern for the same part_number (same foundry)
            for p in all_of("patterns"):
                if (p["id"] != rec["id"] and p["id"] != rec["parent_pattern_id"]
                        and p["status"] == "ACTIVE"
                        and p["foundry_id"] == rec["foundry_id"]
                        and p["part_number"] == rec["part_number"]):
                    touch(rec)
                    fail("ERR_ACTIVE_REVISION_EXISTS",
                         "an ACTIVE pattern already exists for this part_number")
            rec["status"] = "ACTIVE"
            touch(rec)
            if parent is not None and parent["status"] == "ACTIVE":
                parent["status"] = "SUPERSEDED"
                touch(parent)
        else:
            rec["status"] = "DRAFT"
            touch(rec)
        return ok_object(rec, 200)

    @app.route("/api/patterns/<pid>/retire", methods=["POST"])
    def retire_pattern(pid):
        auth_user, role = auth()
        require_role(role, {"PatternMaker"})
        rec = get("patterns", pid)
        if rec is None:
            fail("ERR_NOT_FOUND", "pattern not found")
        if rec["status"] in ("SUPERSEDED", "RETIRED"):
            fail("ERR_ALREADY_TERMINAL", "pattern is in a terminal state")
        if rec["status"] != "ACTIVE":
            fail("ERR_INVALID_STATE", "only an ACTIVE pattern can be retired")
        for m in all_of("molds"):
            if m["pattern_id"] == rec["id"] and m["status"] in ("ASSEMBLED", "POURED", "COOLED"):
                fail("ERR_PATTERN_HAS_OPEN_MOLDS", "pattern has open molds")
        rec["status"] = "RETIRED"
        touch(rec)
        return ok_object(rec, 200)
