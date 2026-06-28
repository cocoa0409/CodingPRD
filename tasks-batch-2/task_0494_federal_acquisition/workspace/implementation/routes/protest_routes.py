from flask import Blueprint, request

from db import db, stamp_create, touch
from errors import err
from middleware import auth
from response import object_response, list_response
from services.query import get_or_404, paginate
from services import calc
from validate import get_body, req_str, req_enum, pagination_params

bp = Blueprint("protests", __name__)


@bp.route("/protests", methods=["POST"])
def file_protest():
    user_id, _ = auth(["Vendor"])
    body = get_body()
    award_id = req_str(body, "award_id")
    protester_vendor_id = req_str(body, "protester_vendor_id")
    grounds = req_str(body, "grounds")

    award = get_or_404(db.awards, award_id)
    get_or_404(db.vendors, protester_vendor_id)

    sol = db.solicitations.get(award["solicitation_id"])

    # Protester must be a non-winning offeror of the protested solicitation
    # (priority 18): a proposal with that vendor exists and is not the winner.
    is_offeror = False
    if sol is not None:
        for p in db.proposals.values():
            if p["solicitation_id"] != sol["id"]:
                continue
            if p["vendor_id"] != protester_vendor_id:
                continue
            if p["id"] != sol.get("winning_proposal_id"):
                is_offeror = True
                break
    if not is_offeror:
        raise err("ERR_PROTESTER_NOT_OFFEROR",
                  "Protester is not a non-winning offeror of the solicitation.")

    # Filing drives the award AWARDED -> PROTESTED (requires contract, if any, ACTIVE).
    if award["status"] != "AWARDED":
        raise err("ERR_INVALID_STATE", "Award is not in AWARDED status.")
    contract = _contract_of_award(award_id)
    if contract is not None and contract["lifecycle_status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "The award's contract is not ACTIVE.")

    protest = {
        "award_id": award_id,
        "protester_vendor_id": protester_vendor_id,
        "grounds": grounds,
        "status": "FILED",
    }
    stamp_create(protest)
    db.protests[protest["id"]] = protest

    award["status"] = "PROTESTED"
    touch(award)

    return object_response(protest, status=201)


def _contract_of_award(award_id):
    for c in db.contracts.values():
        if c["award_id"] == award_id:
            return c
    return None


@bp.route("/protests/<protest_id>", methods=["GET"])
def get_protest(protest_id):
    auth(["Vendor", "ContractingOfficer", "Auditor"])
    return object_response(get_or_404(db.protests, protest_id))


@bp.route("/protests", methods=["GET"])
def list_protests():
    auth(["Vendor", "ContractingOfficer", "Auditor"])
    award = request.args.get("award_id")
    protester = request.args.get("protester_vendor_id")
    status = request.args.get("status")
    limit, offset = pagination_params()
    items = list(db.protests.values())
    if award is not None:
        items = [p for p in items if p["award_id"] == award]
    if protester is not None:
        items = [p for p in items if p["protester_vendor_id"] == protester]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    page, total = paginate(items, limit, offset)
    return list_response(page, limit, offset, total)


@bp.route("/protests/<protest_id>/begin-review", methods=["POST"])
def begin_review(protest_id):
    auth(["ContractingOfficer"])
    protest = get_or_404(db.protests, protest_id)
    if protest["status"] != "FILED":
        raise err("ERR_INVALID_STATE", "Only a FILED protest can begin review.")
    award = db.awards.get(protest["award_id"])
    if award is None or award["status"] != "PROTESTED":
        raise err("ERR_INVALID_STATE", "Parent award must be PROTESTED.")
    protest["status"] = "UNDER_REVIEW"
    touch(protest)
    return object_response(protest)


@bp.route("/protests/<protest_id>/resolve", methods=["POST"])
def resolve_protest(protest_id):
    auth(["ContractingOfficer"])
    protest = get_or_404(db.protests, protest_id)
    body = get_body()
    outcome = req_enum(body, "outcome", {"SUSTAINED", "DENIED"})
    if protest["status"] != "UNDER_REVIEW":
        raise err("ERR_INVALID_STATE", "Only a protest UNDER_REVIEW can be resolved.")

    award = db.awards.get(protest["award_id"])
    if award is None:
        raise err("ERR_NOT_FOUND", "Parent award does not exist.")

    if outcome == "DENIED":
        protest["status"] = "DENIED"
        touch(protest)
        award["status"] = "AWARDED"
        touch(award)
    else:  # SUSTAINED -> vacate + compensation cascade
        protest["status"] = "SUSTAINED"
        touch(protest)
        _sustain_cascade(award)

    return object_response(protest)


@bp.route("/protests/<protest_id>/withdraw", methods=["POST"])
def withdraw_protest(protest_id):
    user_id, _ = auth(["Vendor"])
    protest = get_or_404(db.protests, protest_id)
    if protest["status"] != "FILED":
        raise err("ERR_INVALID_STATE", "Only a FILED protest can be withdrawn.")
    # Acting vendor must be the protester.
    if user_id != protest["protester_vendor_id"]:
        raise err("ERR_FORBIDDEN_ROLE", "Only the filing vendor may withdraw the protest.")
    protest["status"] = "WITHDRAWN"
    touch(protest)
    award = db.awards.get(protest["award_id"])
    if award is not None:
        award["status"] = "AWARDED"
        touch(award)
    return object_response(protest)


def _sustain_cascade(award):
    """Deep compensation cascade on a sustained protest (PRD §3.6)."""
    sol = db.solicitations.get(award["solicitation_id"])
    awarded_proposal_id = award["proposal_id"]

    # Award -> VACATED.
    award["status"] = "VACATED"
    touch(award)

    # Previously awarded proposal reverts AWARDED -> ACCEPTABLE.
    awarded_proposal = db.proposals.get(awarded_proposal_id)
    if awarded_proposal is not None and awarded_proposal["status"] == "AWARDED":
        awarded_proposal["status"] = "ACCEPTABLE"
        touch(awarded_proposal)

    # Each sibling that had been cascaded to REJECTED reverts to ACCEPTABLE or
    # UNACCEPTABLE per its own merit.
    if sol is not None:
        for p in db.proposals.values():
            if p["id"] == awarded_proposal_id:
                continue
            if p["solicitation_id"] != sol["id"]:
                continue
            if p["status"] == "REJECTED":
                p["status"] = "ACCEPTABLE" if calc.is_acceptable(p["id"]) else "UNACCEPTABLE"
                touch(p)

    # Solicitation winning_proposal_id cleared; status reverts AWARDED -> EVALUATED.
    if sol is not None:
        sol["winning_proposal_id"] = None
        if sol["status"] == "AWARDED":
            sol["status"] = "EVALUATED"
        touch(sol)

    # Contract (if any) ACTIVE -> TERMINATED; its CLINs/invoices freeze.
    contract = _contract_of_award(award["id"])
    if contract is not None and contract["lifecycle_status"] == "ACTIVE":
        contract["lifecycle_status"] = "TERMINATED"
        touch(contract)
