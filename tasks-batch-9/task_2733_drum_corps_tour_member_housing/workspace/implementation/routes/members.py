from flask import Blueprint

import find
import serialize
import services
import validators as v
from auth import endpoint
from envelope import object_response, paginate
from errors import ApiError
from store import clock_date, db, minus_years, new_record, sorted_records, touch

bp = Blueprint("members", __name__)

SECTIONS = ("BRASS", "PERCUSSION", "COLOR_GUARD")
DIETARY_FLAGS = ("NONE", "VEGETARIAN", "GLUTEN_FREE", "SEVERE_ALLERGEN")
MEDICAL_STATUSES = ("CLEARED", "RESTRICTED", "SIDELINED")
DECISIONS = ("OFFER", "DECLINE")
READ_ROLES = ["CorpsDirector", "MembershipCoordinator", "TourManager", "BusinessManager", "Member"]
LIST_ROLES = ["CorpsDirector", "MembershipCoordinator", "TourManager", "BusinessManager"]
VOIDABLE_CONTRACT_STATUSES = ("ISSUED", "REVISION_REQUESTED", "SIGNED_BY_MEMBER")


@bp.route("/members", methods=["POST"])
@endpoint(["MembershipCoordinator"])
def create_member():
    body = v.get_body()
    season_id = v.req_str(body, "season_id")
    full_name = v.req_str(body, "full_name")
    email = v.req_str(body, "email")
    dob_raw, dob = v.req_date(body, "date_of_birth")
    section = v.req_enum(body, "section", SECTIONS)
    dietary_flag = v.opt_enum(body, "dietary_flag", DIETARY_FLAGS, "NONE")
    # Rung 8 -- body foreign keys, in declaration order.
    season = find.season(season_id)
    # Rung 47 -- email is unique among the members of any one season.
    for other in db.members.values():
        if other["season_id"] == season_id and other["email"] == email:
            raise ApiError("ERR_DUPLICATE_EMAIL",
                           "That email is already registered for this season.")

    # Minority is computed at registration and is not a live property.
    is_minor = dob > minus_years(season["_tour_departure_date"], 18)

    record = new_record()
    record.update({
        "season_id": season_id,
        "full_name": full_name,
        "email": email,
        "date_of_birth": dob_raw,
        "section": section,
        "dietary_flag": dietary_flag,
        "is_minor": is_minor,
        "audition_score": None,
        "membership_status": "APPLICANT",
        "medical_status": "CLEARED",
        "tuition_charged_cents": 0,
        "tuition_paid_cents": 0,
        "tuition_balance_cents": 0,
        "refund_due_cents": 0,
        "withdrawal_date": None,
        "withdrawal_obligation_cents": None,
        "withdrawal_obligation_basis": "NONE",
    })
    db.members[record["id"]] = record
    return object_response(serialize.member(record), 201)


@bp.route("/members/<member_id>", methods=["GET"])
@endpoint(READ_ROLES)
def get_member(member_id):
    return object_response(serialize.member(find.member(member_id)))


@bp.route("/members", methods=["GET"])
@endpoint(LIST_ROLES)
def list_members():
    season_id = v.arg_str("season_id")
    membership_status = v.arg_str("membership_status")
    medical_status = v.arg_str("medical_status")
    is_minor = v.arg_bool("is_minor")
    records = []
    for record in sorted_records(db.members):
        if season_id is not None and record["season_id"] != season_id:
            continue
        if membership_status is not None and record["membership_status"] != membership_status:
            continue
        if medical_status is not None and record["medical_status"] != medical_status:
            continue
        if is_minor is not None and record["is_minor"] != is_minor:
            continue
        records.append(record)
    return paginate(records, serialize.member)


@bp.route("/members/<member_id>/audition-decision", methods=["POST"])
@endpoint(["MembershipCoordinator"])
def audition_decision(member_id):
    body = v.get_body()
    decision = v.req_enum(body, "decision", DECISIONS)
    score = v.req_number(body, "audition_score")
    v.check(0 <= score <= 100, "audition_score", "must be between 0 and 100")
    member = find.member(member_id)
    # Rung 12 -- only an APPLICANT may receive an audition decision.
    if member["membership_status"] != "APPLICANT":
        raise ApiError("ERR_INVALID_MEMBER_STATE",
                       "Only an APPLICANT may receive an audition decision.")
    member["audition_score"] = score
    member["membership_status"] = "OFFERED" if decision == "OFFER" else "DECLINED"
    touch(member)
    return object_response(serialize.member(member))


@bp.route("/members/<member_id>/medical-status", methods=["POST"])
@endpoint(["MembershipCoordinator"])
def medical_status(member_id):
    body = v.get_body()
    to_status = v.req_enum(body, "to_medical_status", MEDICAL_STATUSES)
    v.opt_str(body, "note")
    member = find.member(member_id)
    # The medical dimension has no terminal state and moves in any direction;
    # membership_status is left completely untouched.
    member["medical_status"] = to_status
    touch(member)
    return object_response(serialize.member(member))


@bp.route("/members/<member_id>/withdraw", methods=["POST"])
@endpoint(["MembershipCoordinator"])
def withdraw_member(member_id):
    body = v.get_body()
    date_raw, withdrawal_date = v.req_date(body, "withdrawal_date")
    v.opt_str(body, "reason")
    member = find.member(member_id)
    season = db.seasons.get(member["season_id"])
    # Rung 12 -- state gate first.
    if member["membership_status"] not in ("OFFERED", "CONTRACTED", "ON_TOUR"):
        raise ApiError("ERR_INVALID_MEMBER_STATE",
                       "This member's membership status does not permit withdrawal.")
    # Rung 44 -- no business date later than the logical-clock date.
    if withdrawal_date > clock_date():
        raise ApiError("ERR_FUTURE_DATED_INPUT",
                       "withdrawal_date may not be later than the logical-clock date.")
    # Rung 45 -- not earlier than the season's spring_training_start_date.
    if season is not None and withdrawal_date < season["_spring_training_start_date"]:
        raise ApiError("ERR_WITHDRAWAL_DATE_OUT_OF_RANGE",
                       "withdrawal_date falls before spring training opened.")

    if member["membership_status"] == "OFFERED":
        member["withdrawal_date"] = date_raw
        member["withdrawal_obligation_cents"] = 0
        member["withdrawal_obligation_basis"] = "NONE"
        member["membership_status"] = "WITHDRAWN"
        touch(member)
        for contract in sorted_records(db.contracts):
            if (contract["member_id"] == member["id"]
                    and contract["status"] in VOIDABLE_CONTRACT_STATUSES):
                contract["status"] = "VOIDED"
                touch(contract)
    else:
        services.strike_withdrawal_obligation(member, season, date_raw, withdrawal_date)
    return object_response(serialize.member(member))
