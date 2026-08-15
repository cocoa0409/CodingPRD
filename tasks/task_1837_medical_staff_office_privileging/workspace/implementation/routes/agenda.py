from flask import Blueprint, g

import db
import errors
import serializers
import services
from middleware import ALL_ROLES, require_roles
from response import ok_list, ok_object
from util import get_body, is_int, paginate, require_enum, require_fields

bp = Blueprint("agenda", __name__)

COORD = "MedicalStaffCoordinator"
CHAIR = "CredentialsCommitteeChair"
MEC = "MedicalExecutiveCommitteeChair"
BOARD = "BoardMember"

ITEM_KINDS = ("APPLICATION_APPROVAL", "PRIVILEGE_GRANT", "ADVERSE_ACTION",
              "POLICY_CHANGE")
REF_FIELD = {
    "APPLICATION_APPROVAL": "ref_application_id",
    "PRIVILEGE_GRANT": "ref_delineation_id",
    "ADVERSE_ACTION": "ref_case_id",
    "POLICY_CHANGE": None,
}
REF_STORE = {
    "ref_application_id": "applications",
    "ref_delineation_id": "delineations",
    "ref_case_id": "cases",
}


def _get_item(iid):
    rec = db.agenda_items.get(iid)
    if rec is None:
        errors.raise_err(errors.ERR_NOT_FOUND,
                         "CommitteeAgendaItem not found")
    return rec


@bp.route("/mso/agenda-items", methods=["POST"])
@require_roles(COORD, CHAIR)
def create_agenda_item():
    body = get_body()
    # Rung 3: existence of any populated reference.
    for field, store_name in REF_STORE.items():
        ref = body.get(field)
        if ref is not None:
            store = getattr(db, store_name)
            if ref not in store:
                errors.raise_err(errors.ERR_NOT_FOUND,
                                 f"{field} does not exist")
    # Rung 10: kind must agree with the populated reference field.
    kind = body.get("item_kind")
    if kind in REF_FIELD:
        expected = REF_FIELD[kind]
        for field in REF_STORE:
            present = body.get(field) is not None
            if field == expected and not present:
                errors.raise_err(
                    errors.ERR_AGENDA_REF_MISMATCH,
                    f"item_kind {kind} requires {field}")
            if field != expected and present:
                errors.raise_err(
                    errors.ERR_AGENDA_REF_MISMATCH,
                    f"item_kind {kind} must not populate {field}")
    # Rung 11: input shape.
    require_fields(body, ["item_kind"])
    require_enum(body, "item_kind", ITEM_KINDS)

    if kind == "ADVERSE_ACTION":
        quorum = services.quorum_required_for_case(body.get("ref_case_id"))
    else:
        quorum = services.COMMITTEE_QUORUM
    rec = services.base_record()
    rec.update({
        "item_kind": kind,
        "ref_application_id": body.get("ref_application_id"),
        "ref_delineation_id": body.get("ref_delineation_id"),
        "ref_case_id": body.get("ref_case_id"),
        "committee_status": "AGENDA",
        "committee_votes_for": 0,
        "committee_votes_against": 0,
        "quorum_required": quorum,
        "mec_voter_ids": [],
        "board_voter_id": None,
    })
    db.agenda_items[rec["id"]] = rec
    return ok_object(serializers.agenda_item(rec), 201)


@bp.route("/mso/agenda-items", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_agenda_items():
    items, limit, offset, total = paginate(
        db.agenda_items.values(), serializers.agenda_item,
        ["item_kind", "committee_status", "ref_application_id",
         "ref_delineation_id", "ref_case_id"])
    return ok_list(items, limit, offset, total)


@bp.route("/mso/agenda-items/<iid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_agenda_item(iid):
    return ok_object(serializers.agenda_item(_get_item(iid)))


@bp.route("/mso/agenda-items/<iid>/committee-vote", methods=["POST"])
@require_roles(CHAIR)
def committee_vote(iid):
    body = get_body()
    item = _get_item(iid)
    # Rung 5: state.
    if item["committee_status"] not in ("AGENDA", "DEFERRED"):
        errors.raise_err(errors.ERR_ITEM_NOT_VOTABLE,
                         "Item is not in AGENDA or DEFERRED")
    votes_for = body.get("votes_for")
    votes_against = body.get("votes_against")
    if not is_int(votes_for) or votes_for < 0 \
            or not is_int(votes_against) or votes_against < 0:
        errors.raise_err(errors.ERR_INVALID_REQUEST,
                         "votes_for and votes_against must be non-negative "
                         "integers")
    # Rung 9: the batch must push a tally to quorum (atomic — check first).
    new_for = item["committee_votes_for"] + votes_for
    new_against = item["committee_votes_against"] + votes_against
    quorum = item["quorum_required"]
    approved = new_for >= quorum
    rejected = new_against >= quorum
    if not approved and not rejected:
        errors.raise_err(errors.ERR_COMMITTEE_QUORUM_UNMET,
                         "Vote batch does not reach quorum_required")
    if item["item_kind"] == "ADVERSE_ACTION":
        case = db.cases.get(item.get("ref_case_id"))
        if case is None or case["case_status"] not in (
                "HEARING_HELD", "MEC_ENDORSED"):
            errors.raise_err(errors.ERR_CASE_NOT_READY_FOR_COMMITTEE,
                             "Referenced case is not in HEARING_HELD or "
                             "MEC_ENDORSED")
    item["committee_votes_for"] = new_for
    item["committee_votes_against"] = new_against
    # Approval wins when both thresholds are crossed (scaffold order).
    item["committee_status"] = ("COMMITTEE_APPROVED" if approved
                                else "COMMITTEE_REJECTED")
    services.touch(item)
    return ok_object(serializers.agenda_item(item))


@bp.route("/mso/agenda-items/<iid>/defer", methods=["POST"])
@require_roles(CHAIR)
def defer_item(iid):
    get_body()
    item = _get_item(iid)
    if item["committee_status"] != "AGENDA":
        errors.raise_err(errors.ERR_ITEM_NOT_DEFERRABLE,
                         "Item is not in AGENDA")
    item["committee_status"] = "DEFERRED"
    services.touch(item)
    return ok_object(serializers.agenda_item(item))


@bp.route("/mso/agenda-items/<iid>/reagenda", methods=["POST"])
@require_roles(CHAIR)
def reagenda_item(iid):
    get_body()
    item = _get_item(iid)
    if item["committee_status"] != "DEFERRED":
        errors.raise_err(errors.ERR_ITEM_NOT_REAGENDABLE,
                         "Item is not in DEFERRED")
    item["committee_status"] = "AGENDA"
    services.touch(item)
    return ok_object(serializers.agenda_item(item))


@bp.route("/mso/agenda-items/<iid>/mec-endorse", methods=["POST"])
@require_roles(MEC)
def mec_endorse(iid):
    body = get_body()
    item = _get_item(iid)
    if item["committee_status"] != "COMMITTEE_APPROVED":
        errors.raise_err(errors.ERR_ITEM_NOT_COMMITTEE_APPROVED,
                         "Item is not COMMITTEE_APPROVED")
    voter_id = body.get("voter_id")
    if not isinstance(voter_id, str) or not voter_id:
        errors.raise_err(errors.ERR_INVALID_REQUEST,
                         "voter_id is required")
    if voter_id in item["mec_voter_ids"]:
        errors.raise_err(errors.ERR_DUPLICATE_MEC_VOTE,
                         "voter_id has already voted on this item")
    item["mec_voter_ids"].append(voter_id)
    item["committee_status"] = "MEC_ENDORSED"
    services.touch(item)
    if item["item_kind"] == "APPLICATION_APPROVAL":
        app = db.applications.get(item.get("ref_application_id"))
        if app is not None and app["application_status"] == "COMMITTEE_REVIEW":
            app["application_status"] = "BOARD_REVIEW"
            services.touch(app)
    return ok_object(serializers.agenda_item(item))


def _board_action(item, ratify):
    if item["committee_status"] != "MEC_ENDORSED":
        errors.raise_err(errors.ERR_ITEM_NOT_MEC_ENDORSED,
                         "Item is not MEC_ENDORSED")
    if g.user_id in item["mec_voter_ids"]:
        errors.raise_err(errors.ERR_SOD_BOARD_CONFLICT,
                         "A MEC voter may not cast the board vote on the "
                         "same item")
    item["board_voter_id"] = g.user_id
    item["committee_status"] = ("BOARD_RATIFIED" if ratify
                                else "BOARD_DECLINED")
    services.touch(item)
    kind = item["item_kind"]
    if kind == "APPLICATION_APPROVAL":
        app = db.applications.get(item.get("ref_application_id"))
        if app is not None and app["application_status"] == "BOARD_REVIEW":
            if ratify:
                services.approve_application(app)
            else:
                services.deny_application(app, item)
    elif kind == "PRIVILEGE_GRANT" and ratify:
        delineation = db.delineations.get(item.get("ref_delineation_id"))
        if delineation is not None:
            delineation["delineation_status"] = "GRANTED"
            services.touch(delineation)
            app = db.applications.get(delineation["application_id"])
            member = db.members.get(app["member_id"]) if app else None
            if member is not None:
                services.create_grant(member, delineation)
    # ADVERSE_ACTION ratification: the case is decided via the hearing
    # track (§3.8); no additional case mutation here.


@bp.route("/mso/agenda-items/<iid>/board-ratify", methods=["POST"])
@require_roles(BOARD)
def board_ratify(iid):
    get_body()
    item = _get_item(iid)
    _board_action(item, ratify=True)
    return ok_object(serializers.agenda_item(item))


@bp.route("/mso/agenda-items/<iid>/board-decline", methods=["POST"])
@require_roles(BOARD)
def board_decline(iid):
    get_body()
    item = _get_item(iid)
    _board_action(item, ratify=False)
    return ok_object(serializers.agenda_item(item))
