"""ScoreReport posting + CLEP credit posting."""

from flask import Blueprint, request

from errors import err_score_report_not_found
from middleware import current_user_id, current_user_role, require_roles
from response import success, success_list
from services.clep_service import post_clep_credit
from services.common import get_json_body, paginate, parse_pagination
from services.score_report_service import (
    get_score_report_or_404,
    list_score_reports,
    post_score_report,
)
from services.serializers import serialize_clep_credit_award, serialize_score_report
import db

bp = Blueprint("scores", __name__)


@bp.route("/test-events/<test_event_id>/registrations/<registration_id>/score-reports", methods=["POST"])
@require_roles("Registrar")
def post_score_report_route(test_event_id, registration_id):
    body = get_json_body()
    s = post_score_report(test_event_id, registration_id, body)
    return success(serialize_score_report(s), status=201)


@bp.route("/test-events/<test_event_id>/registrations/<registration_id>/score-reports", methods=["GET"])
@require_roles("Candidate", "Registrar", "CreditsOfficer")
def list_score_reports_route(test_event_id, registration_id):
    limit, offset = parse_pagination()
    items = list_score_reports(test_event_id, registration_id, current_user_role(), current_user_id())
    page, total = paginate(items, limit, offset)
    return success_list([serialize_score_report(x) for x in page], limit, offset, total)


@bp.route(
    "/test-events/<test_event_id>/registrations/<registration_id>/score-reports/<score_report_id>/clep-credit",
    methods=["POST"],
)
@require_roles("CreditsOfficer")
def post_clep_credit_route(test_event_id, registration_id, score_report_id):
    # Hierarchical existence: testEventId → registrationId → scoreReportId, left to right.
    # Verify the scoreReport exists separately so left-to-right ordering on 404 is preserved.
    if db.score_reports.get(score_report_id) is None:
        # First make sure the prior segments resolve.
        from services.registration_service import get_scoped_registration_or_404
        get_scoped_registration_or_404(test_event_id, registration_id)
        raise err_score_report_not_found()

    award = post_clep_credit(test_event_id, registration_id, score_report_id, current_user_id())
    return success(serialize_clep_credit_award(award), status=201)
