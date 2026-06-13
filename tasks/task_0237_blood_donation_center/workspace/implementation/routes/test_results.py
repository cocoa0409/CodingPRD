"""Test results: reads only (creation lives under donations/test-results)."""
from flask import Blueprint, request

import db
import lookup
from common import paginate
from middleware import require_roles
from response import success, success_list
from services.serialize import serialize_test_result

bp = Blueprint("test_results", __name__)


@bp.route("/blood-bank/test-results", methods=["GET"])
@require_roles("CenterAdmin", "LabTechnician", "InventoryManager")
def list_test_results():
    donation_id = request.args.get("donation_id")
    donor_id = request.args.get("donor_id")
    panel_outcome = request.args.get("panel_outcome")
    with db.lock:
        rows = list(db.test_results.values())
        if donation_id is not None:
            rows = [t for t in rows if t["donation_id"] == donation_id]
        if donor_id is not None:
            rows = [t for t in rows if t["donor_id"] == donor_id]
        if panel_outcome is not None:
            rows = [t for t in rows if t["panel_outcome"] == panel_outcome]
        page, limit, offset, total = paginate(rows)
        return success_list([serialize_test_result(t) for t in page], limit, offset, total)


@bp.route("/blood-bank/test-results/<test_result_id>", methods=["GET"])
@require_roles("CenterAdmin", "LabTechnician", "InventoryManager")
def get_test_result(test_result_id):
    with db.lock:
        test_result = lookup.test_result(test_result_id)
        return success(serialize_test_result(test_result))
