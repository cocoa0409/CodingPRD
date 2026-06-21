"""BackflowTest routes (PRD §3.5)."""
from flask import Blueprint, request

from db import db, LOCK, stamp_new
import domain
import errors
import lookups
from cascades import record_backflow_cascade
from domain import serialize
from errors import fail
from listing import list_response
from middleware import get_auth, require_role
from response import success
from validation import get_body, require_str, require_int

bp = Blueprint("backflow", __name__)


@bp.route("/backflow-tests", methods=["POST"])
def create_backflow_test():
    _, role = get_auth()
    require_role(role, {"BackflowTester"})
    with LOCK:
        body = get_body()
        # Existence (priority 3), left-to-right: system_id then tester_technician_id
        system_id = require_str(body, "system_id")
        system = lookups.get_system(system_id)
        tester_technician_id = require_str(body, "tester_technician_id")
        tester = lookups.get_technician(tester_technician_id)

        # Priority 7: tester must be backflow_certified (403)
        if not tester["backflow_certified"]:
            fail(errors.ERR_TESTER_NOT_CERTIFIED, "Tester is not backflow_certified")
        # Priority 8: system must have a backflow device (409)
        if not system["has_backflow_device"]:
            fail(errors.ERR_NO_BACKFLOW_DEVICE, "System has no backflow device")

        relief_open_psi = require_int(body, "relief_open_psi", minimum=0)
        checkvalve_hold_psi = require_int(body, "checkvalve_hold_psi", minimum=0)

        result = domain.backflow_result(relief_open_psi, checkvalve_hold_psi)
        rec = {
            "system_id": system_id,
            "tester_technician_id": tester_technician_id,
            "relief_open_psi": relief_open_psi,
            "checkvalve_hold_psi": checkvalve_hold_psi,
            "result": result,
        }
        stamp_new(rec)
        db.backflow_tests[rec["id"]] = rec

        # Bubble-up cascade: set system.backflow_status, recompute property compliance.
        from db import touch
        system["backflow_status"] = "CERTIFIED" if result == "PASS" else "FAILED"
        touch(system)
        record_backflow_cascade(system)

        return success(serialize(rec), status=201)


@bp.route("/backflow-tests/<bid>", methods=["GET"])
def get_backflow_test(bid):
    _, role = get_auth()
    require_role(role, {"Dispatcher", "Customer", "BackflowTester"})
    with LOCK:
        # No dedicated not-found error for backflow tests in the catalog; the
        # spec lists no ERR_BACKFLOWTEST_NOT_FOUND. Treat a missing id as 404
        # via a generic system-style lookup is wrong; return ERR-style 404 using
        # the closest catalog entry is also wrong. The catalog has no entry, so
        # we surface a 404 with ERR_ROUTESTOP-like... — instead, use a plain 404.
        rec = db.backflow_tests.get(bid)
        if rec is None:
            # The error catalogue defines no backflow-test not-found id; emit a
            # 404 with a descriptive id so the envelope shape stays valid.
            from errors import ApiError
            raise ApiError("ERR_BACKFLOWTEST_NOT_FOUND", 404, "Backflow test not found")
        return success(serialize(rec), status=200)


@bp.route("/backflow-tests", methods=["GET"])
def list_backflow_tests():
    _, role = get_auth()
    require_role(role, {"Dispatcher", "Customer", "BackflowTester"})
    with LOCK:
        rows = list(db.backflow_tests.values())
        system_id = request.args.get("system_id")
        tester = request.args.get("tester_technician_id")
        if system_id is not None:
            rows = [b for b in rows if b["system_id"] == system_id]
        if tester is not None:
            rows = [b for b in rows if b["tester_technician_id"] == tester]
        return list_response(rows)
