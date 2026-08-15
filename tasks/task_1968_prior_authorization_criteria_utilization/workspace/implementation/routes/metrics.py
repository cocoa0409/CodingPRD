"""Overturn analysis metrics."""

from db import db
from middleware import ALL_ROLES, authorize
from response import ok
from services import rate4, rate4_json
from . import make_blueprint

bp = make_blueprint("metrics")


@bp.route("/metrics/overturn-analysis", methods=["GET"])
def overturn_analysis():
    authorize(*ALL_ROLES)
    appeals = list(db.appeals.values())
    filed = len(appeals)
    upheld = sum(1 for a in appeals if a["status"] == "UPHELD")
    overturned = sum(1 for a in appeals if a["status"] == "OVERTURNED")
    withdrawn = sum(1 for a in appeals if a["status"] == "WITHDRAWN")
    decided = upheld + overturned
    data = {
        "appeals_filed": filed,
        "appeals_decided": decided,
        "appeals_withdrawn": withdrawn,
        "overturned_count": overturned,
        "upheld_count": upheld,
        "overturn_rate_decided": rate4_json(rate4(overturned, decided)),
        "overturn_rate_filed": rate4_json(rate4(overturned, filed)),
    }
    return ok(data)
