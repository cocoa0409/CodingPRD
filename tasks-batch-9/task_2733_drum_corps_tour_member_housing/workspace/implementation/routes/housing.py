from flask import Blueprint

import find
import serialize
import services
import validators as v
from auth import endpoint
from envelope import object_response, paginate
from errors import ApiError
from store import days_between, db, new_record, sorted_records, touch

bp = Blueprint("housing", __name__)

READ_ROLES = ["CorpsDirector", "TourManager", "MembershipCoordinator", "Member"]
LIST_ROLES = ["CorpsDirector", "TourManager", "MembershipCoordinator"]


def _overlaps(a_in, a_out, b_in, b_out):
    """Half-open comparison: two stays that merely touch do not overlap."""
    return b_in < a_out and b_out > a_in


@bp.route("/housing-assignments", methods=["POST"])
@endpoint(["MembershipCoordinator"])
def create_housing():
    body = v.get_body()
    agreement_id = v.req_str(body, "facility_agreement_id")
    member_id = v.req_str(body, "member_id")
    space_index = v.req_int(body, "space_index")
    check_in_raw, check_in = v.req_date(body, "check_in_date")
    check_out_raw, check_out = v.req_date(body, "check_out_date")
    expected_version = v.req_int(body, "expected_facility_agreement_version")
    # Rung 4 -- check_out_date must be later than check_in_date.
    v.date_range(check_out > check_in, "check_out_date must be later than check_in_date.")
    # Rung 8 -- agreement then member, in declaration order.
    agreement = find.agreement(agreement_id)
    member = find.member(member_id)
    # Rung 11 -- stale-view protection on the parent agreement.
    if expected_version != agreement["version"]:
        raise ApiError(
            "ERR_STALE_AGREEMENT_VERSION",
            "expected_facility_agreement_version does not match the agreement's version.")
    # Rung 12 -- membership standing.
    if member["membership_status"] not in ("CONTRACTED", "ON_TOUR"):
        raise ApiError("ERR_INVALID_MEMBER_STATE",
                       "Only a CONTRACTED or ON_TOUR member may be given a sleeping space.")
    # Rung 18 -- SIGNED agreement whose usage_type covers the requested use.
    if agreement["status"] != "SIGNED" or agreement["usage_type"] != "SPRING_TRAINING":
        raise ApiError("ERR_AGREEMENT_NOT_SIGNED",
                       "A SPRING_TRAINING agreement in SIGNED status is required.")
    # Rung 26 -- cross-aggregate season coherence.
    if member["season_id"] != agreement["season_id"]:
        raise ApiError("ERR_SEASON_MISMATCH",
                       "The member's season does not match the agreement's season.")

    school = db.schools.get(agreement["host_school_id"])
    occupant_is_minor = member["is_minor"]
    overlap = []
    for other in sorted_records(db.housing):
        if other["status"] != "ACTIVE":
            continue
        if other["facility_agreement_id"] != agreement_id:
            continue
        if other["space_index"] != space_index:
            continue
        if _overlaps(check_in, check_out, other["_check_in_date"], other["_check_out_date"]):
            overlap.append(other)

    # Rung 31 -- minor supervision comes first and outranks capacity.
    for other in overlap:
        if other["occupant_is_minor"] != occupant_is_minor:
            raise ApiError("ERR_MINOR_ROOM_MIX",
                           "This sleeping space would mix minors and adults on overlapping nights.")
    # Rung 41 -- the whole stay must sit inside the agreement's window.
    if check_in < agreement["_start_date"] or check_out > agreement["_end_date"]:
        raise ApiError("ERR_STAY_OUTSIDE_AGREEMENT_WINDOW",
                       "The stay falls outside the agreement's window.")
    # Rung 52 -- space_index bounds.
    if school is None or space_index < 1 or space_index > school["sleeping_space_count"]:
        raise ApiError("ERR_SPACE_INDEX_OUT_OF_RANGE",
                       "space_index is outside the host school's sleeping-space range.")
    # Rung 53 -- effective capacity reserves one bunk for the chaperone
    # whenever a minor occupies the space on an overlapping night.
    minor_present = occupant_is_minor or any(o["occupant_is_minor"] for o in overlap)
    effective_capacity = school["capacity_per_space"] - (1 if minor_present else 0)
    if len(overlap) + 1 > effective_capacity:
        raise ApiError("ERR_SPACE_CAPACITY_EXCEEDED",
                       "The sleeping space has no bunk left on those nights.")
    # Rung 54 -- one member may not hold two overlapping active stays.
    for other in db.housing.values():
        if other["status"] != "ACTIVE" or other["member_id"] != member_id:
            continue
        if _overlaps(check_in, check_out, other["_check_in_date"], other["_check_out_date"]):
            raise ApiError("ERR_MEMBER_ALREADY_HOUSED",
                           "This member already holds an overlapping active stay.")

    record = new_record()
    record.update({
        "facility_agreement_id": agreement_id,
        "member_id": member_id,
        "space_index": space_index,
        "check_in_date": check_in_raw,
        "check_out_date": check_out_raw,
        "_check_in_date": check_in,
        "_check_out_date": check_out,
        # check_out is EXCLUSIVE: the check-out night itself is never occupied.
        "nights": days_between(check_in, check_out),
        "occupant_is_minor": occupant_is_minor,
        "status": "ACTIVE",
        "released_reason": None,
    })
    db.housing[record["id"]] = record
    # The agreement's own version advances as part of the same request.
    touch(agreement)
    return object_response(serialize.housing(record), 201)


@bp.route("/housing-assignments/<housing_assignment_id>", methods=["GET"])
@endpoint(READ_ROLES)
def get_housing(housing_assignment_id):
    return object_response(serialize.housing(find.housing(housing_assignment_id)))


@bp.route("/housing-assignments", methods=["GET"])
@endpoint(LIST_ROLES)
def list_housing():
    agreement_id = v.arg_str("facility_agreement_id")
    member_id = v.arg_str("member_id")
    space_index = v.arg_int("space_index")
    status = v.arg_str("status")
    records = []
    for record in sorted_records(db.housing):
        if agreement_id is not None and record["facility_agreement_id"] != agreement_id:
            continue
        if member_id is not None and record["member_id"] != member_id:
            continue
        if space_index is not None and record["space_index"] != space_index:
            continue
        if status is not None and record["status"] != status:
            continue
        records.append(record)
    return paginate(records, serialize.housing)


@bp.route("/housing-assignments/<housing_assignment_id>/release", methods=["POST"])
@endpoint(["MembershipCoordinator"])
def release_housing(housing_assignment_id):
    assignment = find.housing(housing_assignment_id)
    # Rung 19 -- a release requires the assignment to be ACTIVE.
    if assignment["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_HOUSING_STATE",
                       "Only an ACTIVE housing assignment may be released.")
    services.release_assignment(assignment, "MANUAL")
    return object_response(serialize.housing(assignment))
