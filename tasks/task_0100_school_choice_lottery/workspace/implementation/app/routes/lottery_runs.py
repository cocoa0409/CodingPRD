"""LotteryRun read-only audit endpoint."""
from flask import Blueprint, jsonify

from ..auth import require_auth
from ..responses import success_response
from ..services.lookups import get_lottery_run_or_404


bp = Blueprint("lottery_runs", __name__, url_prefix="/enrollment/lottery-runs")


def _serialize(lr: dict) -> dict:
    return {
        "id": lr["id"],
        "program_id": lr["program_id"],
        "seed_used": lr["seed_used"],
        "drawn_at": lr["drawn_at"],
        "applications_ranked": lr["applications_ranked"],
        "offers_issued_count": lr["offers_issued_count"],
        "created_at": lr["created_at"],
    }


@bp.route("/<lr_id>", methods=["GET"])
@require_auth("DistrictAdmin", "SystemOperator")
def get_lottery_run(lr_id):
    rec = get_lottery_run_or_404(lr_id)
    resp, code = success_response(_serialize(rec), status=200, response_type="object")
    return jsonify(resp), code
