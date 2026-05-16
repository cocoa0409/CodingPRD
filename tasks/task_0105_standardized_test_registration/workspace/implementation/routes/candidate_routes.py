"""Candidate routes."""

from flask import Blueprint, g, request

from errors import err_insufficient_permissions, err_invalid_request
from middleware import current_user_id, current_user_role, require_roles
from response import success
from services.candidate_service import create_candidate, get_candidate_or_404
from services.common import get_json_body
from services.score_report_service import compute_super_score
from services.serializers import serialize_candidate

bp = Blueprint("candidates", __name__)


@bp.route("/candidates", methods=["POST"])
@require_roles("Candidate", "Registrar")
def create_candidate_route():
    body = get_json_body()
    c = create_candidate(body)
    return success(serialize_candidate(c), status=201)


@bp.route("/candidates/<candidate_id>", methods=["GET"])
@require_roles("Candidate", "Registrar", "AccommodationsOfficer")
def get_candidate_route(candidate_id):
    c = get_candidate_or_404(candidate_id)
    if current_user_role() == "Candidate" and current_user_id() != c["id"]:
        raise err_insufficient_permissions()
    return success(serialize_candidate(c))


@bp.route("/candidates/<candidate_id>/super-score", methods=["GET"])
@require_roles("Candidate", "Registrar")
def super_score_route(candidate_id):
    c = get_candidate_or_404(candidate_id)
    if current_user_role() == "Candidate" and current_user_id() != c["id"]:
        raise err_insufficient_permissions()
    test_type = request.args.get("test_type")
    if not test_type:
        raise err_invalid_request("test_type is required")
    reporting_mode = request.args.get("reporting_mode", "COLLEGE_BOARD_OFFICIAL")
    as_of_date = request.args.get("as_of_date")
    result = compute_super_score(candidate_id, test_type, reporting_mode, as_of_date)
    return success(result)


@bp.route("/candidates/<candidate_id>/clep-credit-awards", methods=["GET"])
@require_roles("Candidate", "Registrar", "CreditsOfficer")
def list_clep_credit_awards_route(candidate_id):
    c = get_candidate_or_404(candidate_id)
    if current_user_role() == "Candidate" and current_user_id() != c["id"]:
        raise err_insufficient_permissions()
    from services.clep_service import list_clep_credit_awards
    from services.common import paginate, parse_pagination
    from services.serializers import serialize_clep_credit_award

    limit, offset = parse_pagination()
    items = list_clep_credit_awards(candidate_id)
    page, total = paginate(items, limit, offset)
    from response import success_list

    return success_list([serialize_clep_credit_award(x) for x in page], limit, offset, total)
