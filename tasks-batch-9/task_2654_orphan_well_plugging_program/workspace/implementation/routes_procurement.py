"""Contractors, solicitations, bids, award and unit-cost contracts (PRD 3.6)."""
from flask import Blueprint

import calc
import validate as v
from auth import (AWARD_AUTHORITY, CONTRACTOR, FIELD_INSPECTOR,
                  FUNDING_OFFICER, PROCUREMENT_OFFICER, PROGRAM_ADMIN,
                  endpoint, not_owner, role, sod, user_id)
from envelope import filter_value, object_response, paginated
from errors import ApiError, invalid
from lookup import (collect, get_bid, get_contract, get_contractor,
                    get_solicitation)
from store import clock, db, new_row, touch

bp = Blueprint("procurement", __name__)

ELIGIBILITY_ACTIONS = ("SUSPEND_LICENSE", "REINSTATE", "DEBAR")
LIFECYCLE_ACTIONS = ("OPEN", "CLOSE", "REOPEN", "CANCEL")
EVALUATION_OUTCOMES = ("RESPONSIVE", "NONRESPONSIVE")
MAX_REOPEN_ROUNDS = 1
LIVE_BID_STATUSES = ("SUBMITTED", "RESPONSIVE", "NONRESPONSIVE", "AWARDED")
SWEEPABLE_BID_STATUSES = ("SUBMITTED", "RESPONSIVE", "NONRESPONSIVE")

CONTRACTOR_READ_ONE = (PROGRAM_ADMIN, PROCUREMENT_OFFICER, AWARD_AUTHORITY,
                       FUNDING_OFFICER, FIELD_INSPECTOR, CONTRACTOR)
CONTRACTOR_READ_MANY = (PROGRAM_ADMIN, PROCUREMENT_OFFICER, AWARD_AUTHORITY,
                        FUNDING_OFFICER, FIELD_INSPECTOR)
SOLICITATION_READERS = (PROGRAM_ADMIN, PROCUREMENT_OFFICER, AWARD_AUTHORITY,
                        FUNDING_OFFICER, CONTRACTOR)
BID_READERS = (PROGRAM_ADMIN, PROCUREMENT_OFFICER, AWARD_AUTHORITY,
               FUNDING_OFFICER, CONTRACTOR)
CONTRACT_READ_ONE = (PROGRAM_ADMIN, PROCUREMENT_OFFICER, AWARD_AUTHORITY,
                     FUNDING_OFFICER, FIELD_INSPECTOR, CONTRACTOR)
CONTRACT_READ_MANY = (PROGRAM_ADMIN, PROCUREMENT_OFFICER, AWARD_AUTHORITY,
                      FUNDING_OFFICER, FIELD_INSPECTOR)


def bad_transition(message):
    return ApiError("ERR_INVALID_STATE_TRANSITION", message)


# ------------------------------------------------------------------ Contractor
@bp.route("/contractors", methods=["POST"])
@endpoint((PROCUREMENT_OFFICER, PROGRAM_ADMIN))
def create_contractor():
    data = v.body()
    name = v.str_field(data, "name")
    license_number = v.str_field(data, "license_number")
    bond = v.int_field(data, "bond_amount_cents", minimum=0)
    performance_score = v.num_field(data, "performance_score", minimum=0,
                                    maximum=100)

    for existing in db.contractors.values():
        if existing["license_number"] == license_number:
            raise invalid("license_number %s is already registered."
                          % license_number)

    row = new_row()
    row.update({
        "name": name,
        "license_number": license_number,
        "bond_amount_cents": bond,
        "performance_score": performance_score,
        "license_status": "GOOD_STANDING",
        "suspended_at": None,
    })
    db.contractors[row["id"]] = row
    return object_response(row, 201)


@bp.route("/contractors/<contractor_id>", methods=["GET"])
@endpoint(CONTRACTOR_READ_ONE)
def fetch_contractor(contractor_id):
    return object_response(get_contractor(contractor_id))


@bp.route("/contractors", methods=["GET"])
@endpoint(CONTRACTOR_READ_MANY)
def list_contractors():
    license_status = filter_value("license_status")

    def keep(row):
        if license_status is not None and row["license_status"] != license_status:
            return False
        return True

    return paginated(collect(db.contractors, keep))


@bp.route("/contractors/<contractor_id>/eligibility", methods=["POST"])
@endpoint((PROGRAM_ADMIN,))
def contractor_eligibility(contractor_id):
    contractor = get_contractor(contractor_id)
    data = v.body()
    action = v.enum_field(data, "action", ELIGIBILITY_ACTIONS)
    v.str_field(data, "reason", required=False, allow_empty=True)

    standing = contractor["license_status"]
    if action == "SUSPEND_LICENSE":
        if standing != "GOOD_STANDING":
            raise bad_transition(
                "SUSPEND_LICENSE is not an edge out of %s." % standing
            )
        contractor["license_status"] = "SUSPENDED"
        contractor["suspended_at"] = clock()
        calc.suspend_contractor_contracts(contractor_id)
    elif action == "REINSTATE":
        if standing != "SUSPENDED":
            raise bad_transition("REINSTATE is not an edge out of %s." % standing)
        contractor["license_status"] = "GOOD_STANDING"
        contractor["suspended_at"] = None
        calc.restore_contractor_contracts(contractor_id)
    else:
        if standing not in ("GOOD_STANDING", "SUSPENDED"):
            raise bad_transition("DEBAR is not an edge out of %s." % standing)
        if standing == "GOOD_STANDING":
            contractor["license_status"] = "DEBARRED"
            contractor["suspended_at"] = clock()
            calc.suspend_contractor_contracts(contractor_id)
        else:
            contractor["license_status"] = "DEBARRED"

    touch(contractor)
    return object_response(contractor)


# ---------------------------------------------------------------- Solicitation
@bp.route("/solicitations", methods=["POST"])
@endpoint((PROCUREMENT_OFFICER,), needs_user_id=True)
def create_solicitation():
    data = v.body()
    region_code = v.region_field(data, "region_code")
    scope_description = v.str_field(data, "scope_description")
    bid_due_at = v.datetime_field(data, "bid_due_at")
    ceiling_cents = v.int_field(data, "ceiling_cents", exclusive_minimum=0)
    min_technical_score = v.num_field(data, "min_technical_score", minimum=0,
                                      maximum=100)

    row = new_row()
    row.update({
        "region_code": region_code,
        "scope_description": scope_description,
        "bid_due_at": bid_due_at,
        "ceiling_cents": ceiling_cents,
        "min_technical_score": min_technical_score,
        "status": "DRAFT",
        "reopen_round": 0,
        "created_by_user_id": user_id(),
    })
    db.solicitations[row["id"]] = row
    return object_response(row, 201)


@bp.route("/solicitations/<solicitation_id>", methods=["GET"])
@endpoint(SOLICITATION_READERS)
def fetch_solicitation(solicitation_id):
    return object_response(get_solicitation(solicitation_id))


@bp.route("/solicitations", methods=["GET"])
@endpoint(SOLICITATION_READERS)
def list_solicitations():
    region_code = filter_value("region_code")
    status = filter_value("status")

    def keep(row):
        if region_code is not None and row["region_code"] != region_code:
            return False
        if status is not None and row["status"] != status:
            return False
        return True

    return paginated(collect(db.solicitations, keep))


def _solicitation_bids(solicitation_id):
    return [b for b in db.bids.values() if b["solicitation_id"] == solicitation_id]


@bp.route("/solicitations/<solicitation_id>/lifecycle", methods=["POST"])
@endpoint((PROCUREMENT_OFFICER,))
def solicitation_lifecycle(solicitation_id):
    solicitation = get_solicitation(solicitation_id)
    data = v.body()
    action = v.enum_field(data, "action", LIFECYCLE_ACTIONS)
    new_bid_due_at = v.datetime_field(data, "new_bid_due_at", required=False)

    status = solicitation["status"]
    if action == "OPEN":
        if status != "DRAFT":
            raise bad_transition("OPEN is not an edge out of %s." % status)
        if not clock() < solicitation["bid_due_at"]:
            raise bad_transition(
                "The bid deadline has already passed; this solicitation cannot "
                "be opened."
            )
        solicitation["status"] = "OPEN"
    elif action == "CLOSE":
        if status != "OPEN":
            raise bad_transition("CLOSE is not an edge out of %s." % status)
        solicitation["status"] = "EVALUATING"
    elif action == "REOPEN":
        if status != "EVALUATING":
            raise bad_transition("REOPEN is not an edge out of %s." % status)
        responsive = [b for b in _solicitation_bids(solicitation_id)
                      if b["status"] == "RESPONSIVE"]
        if len(responsive) > 0:
            raise bad_transition(
                "A solicitation with responsive bids cannot be reopened."
            )
        if solicitation["reopen_round"] >= MAX_REOPEN_ROUNDS:
            raise ApiError(
                "ERR_REOPEN_LIMIT_EXCEEDED",
                "A solicitation may be reopened at most %d time(s)."
                % MAX_REOPEN_ROUNDS,
            )
        if new_bid_due_at is None:
            raise invalid("new_bid_due_at is required to reopen a solicitation.")
        if not new_bid_due_at > clock():
            raise bad_transition(
                "new_bid_due_at must be strictly after the logical clock."
            )
        solicitation["reopen_round"] += 1
        solicitation["bid_due_at"] = new_bid_due_at
        solicitation["status"] = "OPEN"
    else:
        if status not in ("DRAFT", "OPEN", "EVALUATING"):
            raise bad_transition("CANCEL is not an edge out of %s." % status)
        solicitation["status"] = "CANCELLED"
        for bid in sorted(_solicitation_bids(solicitation_id),
                          key=lambda b: b["_seq"]):
            if bid["status"] in SWEEPABLE_BID_STATUSES:
                bid["status"] = "NOT_AWARDED"
                touch(bid)

    touch(solicitation)
    return object_response(solicitation)
