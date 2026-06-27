from flask import Blueprint, request

from db import db, stamp_create, touch
from errors import err
from middleware import auth
from response import object_response, list_response
from services.query import get_or_404, paginate
from services import calc
from validate import get_body, req_str, req_int, pagination_params

bp = Blueprint("awards", __name__)


@bp.route("/awards", methods=["POST"])
def create_award():
    user_id, _ = auth(["ContractingOfficer"])
    body = get_body()
    solicitation_id = req_str(body, "solicitation_id")
    proposal_id = req_str(body, "proposal_id")
    expected_version = req_int(body, "expected_solicitation_version")

    # Existence of the named solicitation first — its recorded chair is what the
    # segregation-of-duties rule (PRD §3.8 priority 3) compares against, so we must
    # resolve it before SoD. SoD is then surfaced before proposal existence/state.
    sol = get_or_404(db.solicitations, solicitation_id)

    # Segregation of duties (priority 3): the awarding officer must not be the chair.
    if sol.get("_evaluation_chair") is not None and sol["_evaluation_chair"] == user_id:
        raise err("ERR_SEGREGATION_OF_DUTIES",
                  "The evaluation chair may not make the award.")

    # Remaining existence (priority 4).
    proposal = get_or_404(db.proposals, proposal_id)

    # OCC: a stale solicitation version is rejected on the stale version rather than
    # on a state read (SCAFFOLD §1.2.1), so it precedes the state check.
    if expected_version != sol["version"]:
        raise err("ERR_STALE_VERSION", "Solicitation version is stale.")

    # State validity (priority 5): solicitation must be EVALUATED.
    if sol["status"] != "EVALUATED":
        raise err("ERR_INVALID_STATE", "Solicitation must be EVALUATED to make an award.")

    # Business referential (priority 6): proposal belongs to solicitation & ACCEPTABLE.
    if proposal["solicitation_id"] != solicitation_id or proposal["status"] != "ACCEPTABLE":
        raise err("ERR_PROPOSAL_NOT_ELIGIBLE",
                  "Named proposal is not an eligible ACCEPTABLE proposal of the solicitation.")

    # Create the award.
    award = {
        "solicitation_id": solicitation_id,
        "proposal_id": proposal_id,
        "awarded_by_user_id": user_id,
        "status": "AWARDED",
    }
    stamp_create(award)
    db.awards[award["id"]] = award

    # Cascade (single transaction).
    sol["status"] = "AWARDED"
    sol["winning_proposal_id"] = proposal_id
    touch(sol)

    proposal["status"] = "AWARDED"
    touch(proposal)

    for p in db.proposals.values():
        if p["id"] == proposal_id:
            continue
        if p["solicitation_id"] != solicitation_id:
            continue
        if p["status"] in ("ACCEPTABLE", "UNACCEPTABLE", "SUBMITTED"):
            p["status"] = "REJECTED"
            touch(p)

    return object_response(award, status=201)


@bp.route("/awards/<award_id>", methods=["GET"])
def get_award(award_id):
    auth(["Vendor", "ContractingOfficer", "Auditor"])
    return object_response(get_or_404(db.awards, award_id))


@bp.route("/awards", methods=["GET"])
def list_awards():
    auth(["Vendor", "ContractingOfficer", "Auditor"])
    sol = request.args.get("solicitation_id")
    proposal = request.args.get("proposal_id")
    limit, offset = pagination_params()
    items = list(db.awards.values())
    if sol is not None:
        items = [a for a in items if a["solicitation_id"] == sol]
    if proposal is not None:
        items = [a for a in items if a["proposal_id"] == proposal]
    page, total = paginate(items, limit, offset)
    return list_response(page, limit, offset, total)
