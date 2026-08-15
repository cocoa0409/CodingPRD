"""Foundry site commissioning and the ops epoch (PRD 3.1)."""

from decimal import Decimal

from flask import request

from db import get, new_record
from errors import fail
from middleware import ALL_ROLES, auth, require_role
from response import ok_object
from services import run_ops_sweep
from util import as_int, as_str, body_dict, req


def register(app):
    @app.route("/api/foundries", methods=["POST"])
    def create_foundry():
        auth_user, role = auth()
        require_role(role, {"FoundryAdmin"})
        body = body_dict(request.get_json(silent=True))
        rec = new_record("foundries", {
            "name": as_str(req(body, "name"), "name"),
            "sand_available_kg": Decimal("0"),
            "alloy_available_kg": Decimal("0"),
            "posture": "EMBARGO",
            "ops_run_index": 0,
        })
        return ok_object(rec, 201)

    @app.route("/api/foundries/<fid>", methods=["GET"])
    def get_foundry(fid):
        auth_user, role = auth()
        require_role(role, set(ALL_ROLES))
        rec = get("foundries", fid)
        if rec is None:
            fail("ERR_NOT_FOUND", "foundry not found")
        return ok_object(rec, 200)

    @app.route("/api/foundries/<fid>/run-ops", methods=["POST"])
    def run_ops(fid):
        auth_user, role = auth()
        require_role(role, {"FoundryAdmin"})
        rec = get("foundries", fid)
        if rec is None:
            fail("ERR_NOT_FOUND", "foundry not found")
        body = body_dict(request.get_json(silent=True))
        expected = as_int(req(body, "expected_foundry_version"), "expected_foundry_version")
        # OCC (PRD 2.6): stale observed foundry version -> 412
        if expected != rec["version"]:
            fail("ERR_STALE_VERSION", "foundry version mismatch; re-read the foundry")
        run_ops_sweep(rec)
        return ok_object(rec, 200)
