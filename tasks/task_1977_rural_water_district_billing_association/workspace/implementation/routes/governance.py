"""Rate schedules, board resolutions and votes, annexation petitions."""
from flask import Blueprint, request

import db
from errors import ApiError
from middleware import (ALL_ROLES, body, get_district, get_scoped, opt_dict,
                        opt_int, req_enum, req_int, req_str, require_roles)
from response import ok_list, ok_object, paginate
from services import (annexation_fee_split, bump_district, new_common,
                      post_reserve_entry, recompute_reserve,
                      ser_resolution, ser_schedule, touch,
                      QUORUM_FOR, QUORUM_AGAINST,
                      WITHDRAWAL_FLOOR_NUM, WITHDRAWAL_FLOOR_DEN)

bp = Blueprint("governance", __name__)

RESOLUTION_TYPES = ["RATE_ADOPTION", "RESERVE_WITHDRAWAL", "ANNEXATION_RATIFICATION", "LOAN_AMENDMENT"]


# ------------------------------------------------------------ rate schedules

@bp.post("/districts/<district_id>/rate-schedules")
@require_roles(["BoardDirector"])
def create_schedule(user_id, role, district_id):
    b = body()
    label = req_str(b, "schedule_label")
    base_min = req_int(b, "base_minimum_cents", minimum=0)
    included = req_int(b, "included_gallons", minimum=0)
    tier2_rate = req_int(b, "tier2_rate_cents_per_kgal")
    tier2_cap = req_int(b, "tier2_cap_gallons")
    tier3_rate = req_int(b, "tier3_rate_cents_per_kgal")
    tap_fees = b.get("tap_fee_schedule")
    if not isinstance(tap_fees, dict):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Field 'tap_fee_schedule' is required and must be an object")
    reconnect = req_int(b, "reconnect_fee_cents", minimum=0)
    d = get_district(district_id)
    if tier2_cap <= included or tier2_rate <= 0 or tier3_rate <= 0:
        raise ApiError("ERR_RATE_SCHEDULE_INVALID", 422,
                       "tier2_cap_gallons must exceed included_gallons and all rates must be positive")
    s = new_common()
    s.update({
        "district_id": d["id"],
        "schedule_label": label,
        "base_minimum_cents": base_min,
        "included_gallons": included,
        "tier2_rate_cents_per_kgal": tier2_rate,
        "tier2_cap_gallons": tier2_cap,
        "tier3_rate_cents_per_kgal": tier3_rate,
        "tap_fee_schedule": tap_fees,
        "reconnect_fee_cents": reconnect,
        "status": "DRAFT",
    })
    db.rate_schedules[s["id"]] = s
    return ok_object(ser_schedule(s), 201)


@bp.get("/districts/<district_id>/rate-schedules")
@require_roles(ALL_ROLES)
def list_schedules(user_id, role, district_id):
    d = get_district(district_id)
    items = [s for s in db.rate_schedules.values() if s["district_id"] == d["id"]]
    st = request.args.get("status")
    if st is not None:
        items = [s for s in items if s["status"] == st]
    page, limit, offset, total = paginate(items, request.args)
    return ok_list([ser_schedule(s) for s in page], limit, offset, total)


@bp.get("/districts/<district_id>/rate-schedules/<schedule_id>")
@require_roles(ALL_ROLES)
def get_schedule(user_id, role, district_id, schedule_id):
    d = get_district(district_id)
    s = get_scoped(db.rate_schedules, schedule_id, d["id"], "ERR_SCHEDULE_NOT_FOUND", "RateSchedule")
    return ok_object(ser_schedule(s))


# ---------------------------------------------------------- board resolutions

@bp.post("/districts/<district_id>/board-resolutions")
@require_roles(["BoardDirector"])
def create_resolution(user_id, role, district_id):
    b = body()
    rtype = req_enum(b, "resolution_type", RESOLUTION_TYPES)
    subject_id = req_str(b, "subject_id")
    payload = opt_dict(b, "payload")
    expected = opt_int(b, "expected_district_version")
    # Type-specific payload shape.
    if rtype == "RESERVE_WITHDRAWAL":
        w = payload.get("withdrawal_amount_cents")
        if not isinstance(w, int) or isinstance(w, bool) or w < 0:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "payload.withdrawal_amount_cents is required and must be a non-negative integer")
    elif rtype == "LOAN_AMENDMENT":
        n = payload.get("new_annual_debt_service_cents")
        if not isinstance(n, int) or isinstance(n, bool) or n <= 0:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "payload.new_annual_debt_service_cents is required and must be a positive integer")
    d = get_district(district_id)
    # Polymorphic subject existence.
    if rtype == "RATE_ADOPTION":
        get_scoped(db.rate_schedules, subject_id, d["id"], "ERR_SCHEDULE_NOT_FOUND", "RateSchedule")
    elif rtype == "ANNEXATION_RATIFICATION":
        get_scoped(db.petitions, subject_id, d["id"], "ERR_PETITION_NOT_FOUND", "AnnexationPetition")
    else:
        if subject_id != d["id"]:
            raise ApiError("ERR_DISTRICT_NOT_FOUND", 404,
                           "subject_id must be the district itself for %s" % rtype)
    # OCC guard: stale observation of the district is rejected.
    if expected is not None and expected != d["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_district_version does not match the district's current version")
    r = new_common()
    r.update({
        "district_id": d["id"],
        "resolution_type": rtype,
        "subject_id": subject_id,
        "payload": payload,
        "votes_for": 0,
        "votes_against": 0,
        "status": "PROPOSED",
        "_proposed_by": user_id,
        "_voters": set(),
    })
    db.resolutions[r["id"]] = r
    bump_district(d)
    return ok_object(ser_resolution(r), 201)


@bp.get("/districts/<district_id>/board-resolutions")
@require_roles(ALL_ROLES)
def list_resolutions(user_id, role, district_id):
    d = get_district(district_id)
    items = [r for r in db.resolutions.values() if r["district_id"] == d["id"]]
    rt = request.args.get("resolution_type")
    if rt is not None:
        items = [r for r in items if r["resolution_type"] == rt]
    st = request.args.get("status")
    if st is not None:
        items = [r for r in items if r["status"] == st]
    page, limit, offset, total = paginate(items, request.args)
    return ok_list([ser_resolution(r) for r in page], limit, offset, total)


def _adopt(res, d):
    """Execute the subject action atomically. May raise on covenant breach."""
    rtype = res["resolution_type"]
    if rtype == "RATE_ADOPTION":
        sched = db.rate_schedules.get(res["subject_id"])
        if sched is not None:
            for other in db.rate_schedules.values():
                if (other["district_id"] == d["id"] and other["id"] != sched["id"]
                        and other["status"] == "ADOPTED"):
                    other["status"] = "SUPERSEDED"
                    touch(other)
            if sched["status"] == "DRAFT":
                sched["status"] = "ADOPTED"
                touch(sched)
            d["active_rate_schedule_id"] = sched["id"]
            bump_district(d)
    elif rtype == "RESERVE_WITHDRAWAL":
        w = res["payload"].get("withdrawal_amount_cents", 0)
        # Withdrawal floor: balance - w >= target * 0.75 (exact rational).
        if (d["reserve_balance_cents"] - w) * WITHDRAWAL_FLOOR_DEN < d["reserve_target_cents"] * WITHDRAWAL_FLOOR_NUM:
            raise ApiError("ERR_RESERVE_COVENANT_BREACH", 409,
                           "Withdrawal would drop the reserve below 75% of target")
        post_reserve_entry(d["id"], "WITHDRAWAL_AUTH", -w, None)
        recompute_reserve(d)
    elif rtype == "ANNEXATION_RATIFICATION":
        pet = db.petitions.get(res["subject_id"])
        if pet is not None and pet["status"] == "APPROVED_PENDING_VOTE":
            fee, refund = annexation_fee_split(pet["deposit_cents"])
            pet["feasibility_fee_cents"] = fee
            pet["refund_cents"] = refund
            pet["status"] = "RATIFIED"
            touch(pet)
            a = new_common()
            a.update({
                "district_id": d["id"],
                "area_name": pet["petitioner_name"],
                "boundary_acres": pet["parcel_acres"],
                "status": "ANNEXED_IN",
            })
            db.service_areas[a["id"]] = a
            bump_district(d)
    elif rtype == "LOAN_AMENDMENT":
        d["annual_debt_service_cents"] = res["payload"]["new_annual_debt_service_cents"]
        d["reserve_target_cents"] = d["annual_debt_service_cents"]
        recompute_reserve(d)


@bp.post("/districts/<district_id>/board-resolutions/<resolution_id>/record-vote")
@require_roles(["BoardDirector"])
def record_vote(user_id, role, district_id, resolution_id):
    b = body()
    vote = req_enum(b, "vote", ["FOR", "AGAINST"])
    d = get_district(district_id)
    res = get_scoped(db.resolutions, resolution_id, d["id"], "ERR_RESOLUTION_NOT_FOUND", "BoardResolution")
    if res["status"] != "PROPOSED":
        raise ApiError("ERR_RESOLUTION_NOT_PROPOSED", 409, "Voting requires a PROPOSED resolution")
    if user_id in res["_voters"]:
        raise ApiError("ERR_DUPLICATE_VOTE", 409, "Board member has already voted on this resolution")
    # Determine whether this vote is the deciding one.
    if vote == "FOR":
        deciding = (res["votes_for"] + 1) >= QUORUM_FOR and (res["votes_for"] + 1) > res["votes_against"]
    else:
        deciding = (res["votes_against"] + 1) >= QUORUM_AGAINST and (res["votes_against"] + 1) >= res["votes_for"]
    # Segregation of duties: the proposer may not record the deciding vote.
    if deciding and res["_proposed_by"] == user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 403,
                       "The proposing BoardDirector may not record the deciding vote")
    # Covenant floor is evaluated at adoption time against live district fields;
    # a breaching withdrawal is rejected before any vote is recorded.
    if deciding and vote == "FOR" and res["resolution_type"] == "RESERVE_WITHDRAWAL":
        w = res["payload"].get("withdrawal_amount_cents", 0)
        if (d["reserve_balance_cents"] - w) * WITHDRAWAL_FLOOR_DEN < d["reserve_target_cents"] * WITHDRAWAL_FLOOR_NUM:
            raise ApiError("ERR_RESERVE_COVENANT_BREACH", 409,
                           "Withdrawal would drop the reserve below 75% of target")
    if vote == "FOR":
        res["votes_for"] += 1
    else:
        res["votes_against"] += 1
    res["_voters"].add(user_id)
    touch(res)
    if deciding and vote == "FOR":
        _adopt(res, d)  # may raise ERR_RESERVE_COVENANT_BREACH before mutating
        res["status"] = "ADOPTED"
        touch(res)
        bump_district(d)
    elif deciding and vote == "AGAINST":
        res["status"] = "FAILED"
        touch(res)
        if res["resolution_type"] == "ANNEXATION_RATIFICATION":
            pet = db.petitions.get(res["subject_id"])
            if pet is not None and pet["status"] == "APPROVED_PENDING_VOTE":
                pet["status"] = "REJECTED"
                touch(pet)
    return ok_object(ser_resolution(res))
