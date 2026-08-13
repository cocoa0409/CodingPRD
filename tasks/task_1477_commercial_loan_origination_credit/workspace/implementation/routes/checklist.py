"""Document checklist items: creation and lifecycle transitions incl. waiver."""
from flask import Blueprint, g, request

import serialize
from db import STORE, new_entity, touch
from errors import (
    raise_err, ERR_VALIDATION, ERR_INVALID_STATE,
    ERR_ONLY_POLICY_OFFICER_MAY_WAIVE, ERR_CONDITION_NOT_WAIVABLE,
)
from middleware import require_roles, ALL_ROLES
from response import success_object
from routes.common import get_or_404, render_list, body_fk_exists
from services import exposure, policy
from validation import get_body, req_str, req_enum, opt_bool, opt_enum, opt_str

bp = Blueprint("checklist", __name__)

CATEGORIES = {"DOCUMENT", "CLOSING_CONDITION"}
SEVERITIES = {"STANDARD", "CRITICAL"}
TRANSITION_TARGETS = {"RECEIVED", "APPROVED", "REJECTED", "PENDING", "WAIVED"}
ITEM_CREATABLE_APP_STAGES = {"COMMITMENT", "DOCUMENTATION", "CLOSING"}

# Legal from-states per transition target.
FROM_STATES = {
    "RECEIVED": {"PENDING"},
    "APPROVED": {"RECEIVED"},
    "REJECTED": {"RECEIVED"},
    "PENDING": {"REJECTED"},
    "WAIVED": {"PENDING", "RECEIVED"},
}


@bp.post("/credit/document-checklist-items")
def create_item():
    require_roles("CreditAdministrator")
    body = get_body()
    app_id = req_str(body, "loan_application_id")
    category = req_enum(body, "category", CATEGORIES)
    label = req_str(body, "label")
    is_required = opt_bool(body, "is_required", True)
    severity = opt_enum(body, "severity", SEVERITIES, "STANDARD")
    body_fk_exists(STORE.loan_applications, app_id, "LoanApplication")

    app = STORE.loan_applications[app_id]
    if app['status'] not in ITEM_CREATABLE_APP_STAGES:
        raise_err(ERR_INVALID_STATE,
                  "Application status %s does not permit adding checklist items." % app['status'])

    item = new_entity()
    item.update({
        'loan_application_id': app_id,
        'category': category,
        'label': label,
        'is_required': is_required,
        'severity': severity,
        'status': 'PENDING',
        'waived_by_officer_id': None,
        'waiver_rationale': None,
    })
    STORE.document_checklist_items[item['id']] = item
    return success_object(serialize.document_checklist_item(item), status=201)


@bp.get("/credit/loan-applications/<aid>/document-checklist-items")
def application_items(aid):
    require_roles(*ALL_ROLES)
    get_or_404(STORE.loan_applications, aid, "LoanApplication")
    items = exposure.checklist_items_of_app(aid)
    category = request.args.get("category")
    status = request.args.get("status")
    if category is not None:
        items = [i for i in items if i['category'] == category]
    if status is not None:
        items = [i for i in items if i['status'] == status]
    return render_list(items, serialize.document_checklist_item)


@bp.post("/credit/document-checklist-items/<iid>/transition")
def transition_item(iid):
    require_roles("CreditAdministrator", "CreditPolicyOfficer")
    item = get_or_404(STORE.document_checklist_items, iid, "DocumentChecklistItem")
    body = get_body()
    to = req_enum(body, "to", TRANSITION_TARGETS)
    rationale = opt_str(body, "waiver_rationale")
    # Stage 4: rationale length where required.
    if to == 'WAIVED' and (rationale is None or len(rationale) < 20):
        raise_err(ERR_VALIDATION, "Field 'waiver_rationale' is required and must be at least 20 characters when to=WAIVED.")

    # Stage 6: transition legality.
    if item['status'] not in FROM_STATES[to]:
        raise_err(ERR_INVALID_STATE,
                  "Item status is %s; transition to %s is not permitted from it." % (item['status'], to))

    if to == 'WAIVED':
        # Operation-level restriction: only a CreditPolicyOfficer may waive.
        if g.user_role != 'CreditPolicyOfficer':
            raise_err(ERR_ONLY_POLICY_OFFICER_MAY_WAIVE,
                      "Only a CreditPolicyOfficer may waive a checklist item.")
        if item['severity'] == 'CRITICAL':
            raise_err(ERR_CONDITION_NOT_WAIVABLE, "CRITICAL severity items may never be waived.")
        item['waived_by_officer_id'] = g.user_id
        item['waiver_rationale'] = rationale
        # Waiving a required item auto-creates a LOW REQUIRED_DOC_WAIVER exception
        # unless one is already OPEN for the same item.
        if item['is_required']:
            key = "required_doc_waiver:%s" % item['id']
            if not any(e['status'] == 'OPEN' for e in policy.find_exception_by_key(item['loan_application_id'], key)):
                policy.create_exception(
                    item['loan_application_id'], "REQUIRED_DOC_WAIVER",
                    "Required checklist item %s ('%s') was waived." % (item['id'], item['label']),
                    key)

    item['status'] = to
    touch(item)
    return success_object(serialize.document_checklist_item(item))
