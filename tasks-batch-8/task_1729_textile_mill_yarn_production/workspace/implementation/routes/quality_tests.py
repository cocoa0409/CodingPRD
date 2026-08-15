"""QualityTest PATCH endpoint (final shrinkage after conditioning).

Patching shrinkage_pct_final re-derives grade via the final variant — it may
upgrade or downgrade the earlier provisional grade.
"""

from db import db
from errors import err_not_found
from middleware import require_roles
from response import success_object
from serializers import serialize_quality_test
from services.calculations import compute_grade
from services.workflows import touch
from validators import get_json_body, req_decimal, round2

from flask import Blueprint

bp = Blueprint("quality_tests", __name__)


@bp.patch("/mill/quality-tests/<tid>")
def update_quality_test(tid):
    require_roles("QualityInspector")
    record = db.quality_tests.get(tid)
    if record is None:
        raise err_not_found("Quality test not found")
    body = get_json_body()
    final = req_decimal(body, "shrinkage_pct_final", min_value=0, max_value=100)
    record["shrinkage_pct_final"] = round2(final)
    record["grade"] = compute_grade(
        record["shrinkage_pct_provisional"], record["shrinkage_pct_final"], record["hand_score"]
    )
    touch(record)
    return success_object(serialize_quality_test(record))
