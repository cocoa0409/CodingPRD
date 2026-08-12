from flask import Blueprint, g, request

import serializers
from envelope import object_response
from errors import ApiError
from lookups import path_row
from store import db

bp = Blueprint("chr", __name__)


def _include_detail():
    raw = request.args.get("include_detail")
    if raw is None:
        return False
    return raw.strip().lower() in ("true", "1")


@bp.get("/livescan/chr-responses/<id>")
def read_chr_response(id):
    response = path_row("chr_responses", id)
    include_detail = _include_detail()

    if include_detail:
        submission = db.submissions[response["submission_id"]]
        tier = db.oris[submission["ori_id"]]["dissemination_tier"]
        if not (g.role == "AgencyAdjudicator" and tier == "FULL_CHR"):
            raise ApiError(
                "ERR_DISSEMINATION_NOT_ENTITLED",
                "the caller is not entitled to the full criminal-history detail",
            )

    return object_response(serializers.project_chr_response(response, g.role, include_detail))
