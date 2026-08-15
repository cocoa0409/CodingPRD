from flask import Blueprint, request

import db
import errors
import middleware as mw
from response import success
from services import posture
from services.common import touch
from services.pagination import get_pagination, paginate
from services.serialize import assessment as ser_assessment
from services.validate import body_json, require_fields, req_str

bp = Blueprint("covenants", __name__)


@bp.get("/loans/<lid>/covenant-assessments")
def list_assessments(lid):
    actor = mw.authenticate()
    mw.authorize(actor, ["MasterServicer", "SpecialServicer", "Borrower"])
    loan = db.loans.get(lid)
    if not mw.read_scope_allows(actor, "loan", loan):
        raise errors.not_found("Loan not found")
    limit, offset = get_pagination()
    items = [a for a in db.covenant_assessments.values() if a["loan_id"] == lid]
    atype = request.args.get("assessment_type")
    status = request.args.get("status")
    if atype is not None:
        items = [a for a in items if a["assessment_type"] == atype]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    # Newest assessed_at first.
    items.sort(key=lambda a: (a["assessed_at"], a["id"]), reverse=True)
    page, pg = paginate([ser_assessment(a) for a in items], limit, offset)
    return success(page, pagination=pg, is_array=True)


@bp.post("/covenant-assessments/<aid>/waive")
def waive_assessment(aid):
    actor = mw.authenticate()
    mw.authorize(actor, ["SpecialServicer"])
    a = db.covenant_assessments.get(aid)
    if a is None:
        raise errors.not_found("CovenantAssessment not found")
    data = body_json()
    require_fields(data, ["waiver_reason"])
    req_str(data, "waiver_reason")
    if a["status"] != "OPEN":
        raise errors.invalid_state("Only an OPEN assessment can be waived")
    # SoD (priority 12)
    if a["assessment_type"] == "DSCR":
        src = db.financial_statements.get(a.get("statement_id"))
        anchor = src["reviewed_by_user_id"] if src else None
    else:
        # LTV: compare against the appraising operator of the loan's property
        anchor = None
        for p in db.properties.values():
            if p["loan_id"] == a["loan_id"] and p.get("appraised_by_user_id"):
                anchor = p["appraised_by_user_id"]
                break
    if anchor is not None and actor["user_id"] == anchor:
        raise errors.ApiError(
            errors.ERR_SEGREGATION_OF_DUTIES,
            "Waiver user must differ from the original reviewer/appraiser", 403)
    a["status"] = "WAIVED"
    a["waived_by_user_id"] = actor["user_id"]
    a["waiver_reason"] = data["waiver_reason"]
    touch(a)
    loan = db.loans.get(a["loan_id"])
    posture.reevaluate_servicing(loan)
    return success(ser_assessment(a))
