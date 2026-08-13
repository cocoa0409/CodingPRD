"""Sand batches: mixing, LOI testing, reclamation, quarantine (PRD 3.8)."""

from decimal import Decimal

from flask import request

from db import all_of, get, new_record, touch
from errors import fail
from middleware import auth, paged, require_role
from response import ok_list, ok_object
from services import quarantine_cascade, recompute_posture_by_id
from util import as_nonneg_num, as_str, body_dict, q1, req

SAND_GET_ROLES = {"FoundryAdmin", "LineOperator", "QualityInspector"}


def register(app):
    @app.route("/api/sand-batches", methods=["POST"])
    def create_batch():
        auth_user, role = auth()
        require_role(role, {"LineOperator"})
        body = body_dict(request.get_json(silent=True))
        foundry_id = as_str(req(body, "foundry_id"), "foundry_id")
        virgin = as_nonneg_num(req(body, "virgin_weight_kg"), "virgin_weight_kg")
        max_loi = as_nonneg_num(req(body, "max_loi_pct"), "max_loi_pct")
        if get("foundries", foundry_id) is None:
            fail("ERR_NOT_FOUND", "foundry not found")
        rec = new_record("sand_batches", {
            "foundry_id": foundry_id,
            "virgin_weight_kg": virgin,
            "max_loi_pct": max_loi,
            "last_loi_pct": None,
            "current_weight_kg": virgin,
            "committed_weight_kg": Decimal("0"),
            "spent_weight_kg": Decimal("0"),
            "pending_reclaim_kg": Decimal("0"),
            "discarded_weight_kg": Decimal("0"),
            "status": "MIXED",
        })
        return ok_object(rec, 201)

    @app.route("/api/sand-batches/<bid>", methods=["GET"])
    def get_batch(bid):
        auth_user, role = auth()
        require_role(role, SAND_GET_ROLES)
        rec = get("sand_batches", bid)
        if rec is None:
            fail("ERR_NOT_FOUND", "sand batch not found")
        return ok_object(rec, 200)

    @app.route("/api/sand-batches", methods=["GET"])
    def list_batches():
        auth_user, role = auth()
        require_role(role, SAND_GET_ROLES)
        foundry_id = request.args.get("foundry_id")
        status = request.args.get("status")
        recs = list(all_of("sand_batches"))
        if foundry_id is not None:
            recs = [b for b in recs if b["foundry_id"] == foundry_id]
        if status is not None:
            recs = [b for b in recs if b["status"] == status]
        page, limit, offset, total = paged(recs)
        return ok_list(page, limit, offset, total)

    @app.route("/api/sand-batches/<bid>/test", methods=["POST"])
    def test_batch(bid):
        auth_user, role = auth()
        require_role(role, {"QualityInspector"})
        rec = get("sand_batches", bid)
        if rec is None:
            fail("ERR_NOT_FOUND", "sand batch not found")
        if rec["status"] == "DISCARDED":
            fail("ERR_ALREADY_TERMINAL", "sand batch is DISCARDED")
        if rec["status"] not in ("MIXED", "RECLAIMING"):
            fail("ERR_INVALID_STATE", "only MIXED or RECLAIMING batches can be tested")
        body = body_dict(request.get_json(silent=True))
        loi = as_nonneg_num(req(body, "loi_pct"), "loi_pct")

        passed = loi <= rec["max_loi_pct"]  # equality passes (PRD 3.8)
        if rec["status"] == "MIXED":
            if passed:
                rec["status"] = "IN_SERVICE"
                rec["last_loi_pct"] = loi
            else:
                rec["status"] = "DISCARDED"
                rec["discarded_weight_kg"] = rec["discarded_weight_kg"] + rec["current_weight_kg"]
                rec["current_weight_kg"] = Decimal("0")
        else:  # RECLAIMING
            if passed:
                rec["status"] = "IN_SERVICE"
                rec["current_weight_kg"] = rec["current_weight_kg"] + rec["pending_reclaim_kg"]
                rec["pending_reclaim_kg"] = Decimal("0")
                rec["last_loi_pct"] = loi
            else:
                rec["status"] = "DISCARDED"
                rec["discarded_weight_kg"] = (rec["discarded_weight_kg"]
                                              + rec["current_weight_kg"]
                                              + rec["pending_reclaim_kg"]
                                              + rec["committed_weight_kg"])
                rec["current_weight_kg"] = Decimal("0")
                rec["pending_reclaim_kg"] = Decimal("0")
                rec["committed_weight_kg"] = Decimal("0")
        touch(rec)
        if rec["status"] == "DISCARDED":
            # quarantine cascade fires on the RECLAIMING failure path
            quarantine_cascade(rec)
        recompute_posture_by_id(rec["foundry_id"])
        return ok_object(rec, 200)

    @app.route("/api/sand-batches/<bid>/reclaim", methods=["POST"])
    def reclaim_batch(bid):
        auth_user, role = auth()
        require_role(role, {"LineOperator"})
        rec = get("sand_batches", bid)
        if rec is None:
            fail("ERR_NOT_FOUND", "sand batch not found")
        if rec["status"] == "DISCARDED":
            fail("ERR_ALREADY_TERMINAL", "sand batch is DISCARDED")
        if rec["status"] != "IN_SERVICE":
            fail("ERR_INVALID_STATE", "only an IN_SERVICE batch can be reclaimed")
        if rec["spent_weight_kg"] <= 0:
            fail("ERR_INVALID_STATE", "no spent sand awaits reclamation")
        body = body_dict(request.get_json(silent=True))
        # per-event rounding to 0.1 kg BEFORE touching accumulators (pinned order)
        reclaimed = q1(as_nonneg_num(req(body, "reclaimed_weight_kg"), "reclaimed_weight_kg"))
        loss = q1(as_nonneg_num(req(body, "loss_weight_kg"), "loss_weight_kg"))
        if reclaimed + loss != rec["spent_weight_kg"]:
            fail("ERR_SAND_MASS_MISMATCH",
                 "reclaimed_weight_kg + loss_weight_kg must equal spent_weight_kg")
        rec["status"] = "RECLAIMING"
        rec["pending_reclaim_kg"] = reclaimed
        rec["discarded_weight_kg"] = rec["discarded_weight_kg"] + loss
        rec["spent_weight_kg"] = Decimal("0")
        touch(rec)
        recompute_posture_by_id(rec["foundry_id"])
        return ok_object(rec, 200)
