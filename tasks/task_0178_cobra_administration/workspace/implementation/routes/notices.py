"""Election-notice endpoints + elect transition."""
from flask import Blueprint, request, g

from db import store
from errors import ApiError
from middleware import require_role
from models import serialize, NOTICE_FIELDS, ENROLLMENT_FIELDS
from response import object_response, array_response
from services import lifecycle
from services.lookup import get_or_404, paginate, sorted_by_creation

bp = Blueprint("notices", __name__)


@bp.get("/notices/<nid>")
@require_role({"PlanAdministrator", "BillingAgent", "QualifiedBeneficiary"})
def get_notice(nid):
    notice = get_or_404(store.notices, nid)
    return object_response(serialize(notice, NOTICE_FIELDS))


@bp.get("/notices")
@require_role({"PlanAdministrator", "BillingAgent"})
def list_notices():
    event_id = request.args.get("event_id")
    beneficiary_id = request.args.get("beneficiary_id")
    items = list(store.notices.values())
    if event_id is not None:
        items = [n for n in items if n["event_id"] == event_id]
    if beneficiary_id is not None:
        items = [n for n in items if n["beneficiary_id"] == beneficiary_id]
    items = sorted_by_creation(items)
    page, limit, offset, total = paginate(request.args, items)
    return array_response([serialize(n, NOTICE_FIELDS) for n in page],
                          limit, offset, total)


@bp.post("/notices/<nid>/elect")
@require_role({"QualifiedBeneficiary"})
def elect(nid):
    notice = get_or_404(store.notices, nid)
    # Ownership (403) before body/state: QB may act only on its own notice.
    if notice["beneficiary_id"] != g.user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER",
                       "Caller does not own the targeted notice")
    # State (409) before business window.
    if notice["status"] != "OUTSTANDING":
        raise ApiError("ERR_INVALID_STATE", "Notice is not OUTSTANDING")
    now = store.now()
    if now > notice["election_deadline"]:
        raise ApiError("ERR_ELECTION_WINDOW_CLOSED",
                       "Election attempted after the election deadline")
    event = store.events.get(notice["event_id"])
    beneficiary = store.beneficiaries.get(notice["beneficiary_id"])
    plan = store.plans.get(event["plan_id"]) if event else None
    enrollment = lifecycle.perform_election(notice, event, plan, beneficiary)
    return object_response(serialize(enrollment, ENROLLMENT_FIELDS), status=201)
