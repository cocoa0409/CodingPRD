"""Disproportionality report (PRD §3.9)."""
from flask import Blueprint, request

from errors import raise_err, ERR_INVALID_REQUEST
from middleware import endpoint
from response import success
from services.calc import DEMOGRAPHIC_GROUPS, disproportionality
from util import parse_academic_year

bp = Blueprint("reports", __name__)


@bp.get("/reports/disproportionality")
@endpoint("DistrictAdmin")
def disproportionality_report(ctx):
    academic_year = request.args.get("academic_year")
    reference_group = request.args.get("reference_group")
    y1 = parse_academic_year(academic_year)
    if y1 is None:
        raise_err(ERR_INVALID_REQUEST, "academic_year must be of the form YYYY-YYYY with consecutive years")
    if reference_group not in DEMOGRAPHIC_GROUPS:
        raise_err(ERR_INVALID_REQUEST, "reference_group is not a declared demographic group")
    return success(disproportionality(y1, reference_group))
