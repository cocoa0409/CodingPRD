"""BoardElection and Ballot endpoints."""
from flask import Blueprint, request

from middleware import get_context, require_roles, get_json_body
from response import ok, created, paginate
from errors import ApiError
from services import election as elec_svc

bp = Blueprint("elections", __name__)


# =============================================================================
# BoardElection
# =============================================================================

@bp.route("/coop/board-elections", methods=["POST"])
def create_election():
    uid, role = get_context()
    require_roles(["BoardSecretary"])
    body = get_json_body()
    result = elec_svc.create_election(body)
    return created(result)


@bp.route("/coop/board-elections/<election_id>", methods=["GET"])
def get_election(election_id):
    uid, role = get_context()
    require_roles(["BoardSecretary", "BoardDirector", "MemberServicesRep"])
    result = elec_svc.get_election(election_id)
    return ok(result)


@bp.route("/coop/board-elections", methods=["GET"])
def list_elections():
    uid, role = get_context()
    require_roles(["BoardSecretary", "BoardDirector", "MemberServicesRep"])
    cooperative_id = request.args.get("cooperative_id")
    status = request.args.get("status")
    rows = elec_svc.list_elections(cooperative_id, status)
    p = paginate()
    page = p(rows)
    return ok(page, rtype="array", pagination=p)


@bp.route("/coop/board-elections/<election_id>/open-nominations", methods=["POST"])
def open_nominations(election_id):
    uid, role = get_context()
    require_roles(["BoardSecretary"])
    result = elec_svc.open_nominations(election_id)
    return ok(result)


@bp.route("/coop/board-elections/<election_id>/close-nominations", methods=["POST"])
def close_nominations(election_id):
    uid, role = get_context()
    require_roles(["BoardSecretary"])
    body = get_json_body()
    result = elec_svc.close_nominations(election_id, body)
    return ok(result)


@bp.route("/coop/board-elections/<election_id>/open-voting", methods=["POST"])
def open_voting(election_id):
    uid, role = get_context()
    require_roles(["BoardSecretary"])
    body = get_json_body()
    result = elec_svc.open_voting(election_id, body)
    return ok(result)


@bp.route("/coop/board-elections/<election_id>/close-voting", methods=["POST"])
def close_voting(election_id):
    uid, role = get_context()
    require_roles(["BoardSecretary"])
    result = elec_svc.close_voting(election_id)
    return ok(result)


@bp.route("/coop/board-elections/<election_id>/certify", methods=["POST"])
def certify_election(election_id):
    uid, role = get_context()
    require_roles(["BoardSecretary"])
    result = elec_svc.certify_election(election_id)
    return ok(result)


@bp.route("/coop/board-elections/<election_id>/void", methods=["POST"])
def void_election(election_id):
    uid, role = get_context()
    require_roles(["BoardSecretary"])
    result = elec_svc.void_election(election_id)
    return ok(result)


# =============================================================================
# Ballot
# =============================================================================

@bp.route("/coop/ballots", methods=["POST"])
def cast_ballot():
    uid, role = get_context()
    require_roles(["Member"])
    body = get_json_body()
    result = elec_svc.cast_ballot(body, uid)
    return created(result)


@bp.route("/coop/ballots/<ballot_id>", methods=["GET"])
def get_ballot(ballot_id):
    uid, role = get_context()
    require_roles(["BoardSecretary"])
    result = elec_svc.get_ballot(ballot_id)
    return ok(result)


@bp.route("/coop/ballots", methods=["GET"])
def list_ballots():
    uid, role = get_context()
    require_roles(["BoardSecretary"])
    election_id = request.args.get("election_id")
    district = request.args.get("district")
    member_id = request.args.get("member_id")
    rows = elec_svc.list_ballots(election_id, district, member_id)
    p = paginate()
    page = p(rows)
    return ok(page, rtype="array", pagination=p)
