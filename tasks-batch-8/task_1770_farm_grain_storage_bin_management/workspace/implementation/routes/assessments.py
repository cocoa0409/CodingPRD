"""Monthly assessment epoch endpoint (PRD 3.7)."""
import re

from flask import Blueprint

import db
from errors import ApiError
from middleware import require_roles
from response import ok
from services import core
from util import as_str, body, required

bp = Blueprint("assessments", __name__)

_PERIOD_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


@bp.route("/grain/assessments", methods=["POST"])
def create_assessment():
    require_roles("SiteManager")
    data = body()
    # shape (6): period is a YYYY-MM month string
    period = as_str(required(data, "period"), "period")
    if not _PERIOD_RE.match(period):
        raise ApiError("ERR_VALIDATION", 400, "period must be a YYYY-MM month string")
    # uniqueness (26): the period is the idempotency key for the epoch
    for a in db.assessments.values():
        if a["period"] == period:
            raise ApiError("ERR_ASSESSMENT_EXISTS", 409,
                           "an assessment for this period has already run")

    rec = core.run_assessment(period)
    return ok(core.assessment_view(rec), 201)
