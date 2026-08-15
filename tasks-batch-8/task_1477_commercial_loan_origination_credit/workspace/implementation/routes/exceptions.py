"""Policy exceptions: per-application listing and waiver."""
from flask import Blueprint, g, request

import serialize
from db import STORE, touch
from errors import raise_err, ERR_INVALID_STATE, ERR_VALIDATION
from middleware import require_roles, ALL_ROLES
from response import success_object
from routes.common import get_or_404, render_list
from services import exposure
from validation import get_body, req_str

bp = Blueprint("exceptions", __name__)


@bp.get("/credit/loan-applications/<aid>/policy-exceptions")
def list_application_exceptions(aid):
    require_roles(*ALL_ROLES)
    get_or_404(STORE.loan_applications, aid, "LoanApplication")
    items = exposure.exceptions_of_app(aid)
    status = request.args.get("status")
    rule_code = request.args.get("rule_code")
    if status is not None:
        items = [e for e in items if e['status'] == status]
    if rule_code is not None:
        items = [e for e in items if e['rule_code'] == rule_code]
    return render_list(items, serialize.policy_exception)


@bp.post("/credit/policy-exceptions/<eid>/waive")
def waive_exception(eid):
    require_roles("CreditPolicyOfficer")
    exc = get_or_404(STORE.policy_exceptions, eid, "PolicyException")
    body = get_body()
    # Stage 4 (schema, incl. rationale length) runs before stage 6 (state).
    rationale = req_str(body, "waiver_rationale")
    if len(rationale) < 20:
        raise_err(ERR_VALIDATION, "Field 'waiver_rationale' must be at least 20 characters.")
    if exc['status'] != 'OPEN':
        raise_err(ERR_INVALID_STATE, "Exception status is %s; waive requires OPEN." % exc['status'])
    exc['status'] = 'WAIVED'
    exc['waived_by_officer_id'] = g.user_id
    exc['waiver_rationale'] = rationale
    touch(exc)
    return success_object(serialize.policy_exception(exc))
