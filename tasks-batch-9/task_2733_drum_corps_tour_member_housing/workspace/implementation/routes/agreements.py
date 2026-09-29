from flask import Blueprint

import find
import serialize
import services
import validators as v
from auth import endpoint
from envelope import object_response, paginate
from errors import ApiError
from store import days_between, db, new_record, sorted_records, touch

bp = Blueprint("agreements", __name__)

USAGE_TYPES = ("SPRING_TRAINING", "TOUR_REHEARSAL")
ROLES = ["CorpsDirector", "TourManager", "MembershipCoordinator", "BusinessManager"]
RATE_CAP_CENTS = 1500
MAX_COUNTER_ROUNDS = 2


@bp.route("/facility-agreements", methods=["POST"])
@endpoint(["TourManager"])
def create_agreement():
    body = v.get_body()
    school_id = v.req_str(body, "host_school_id")
    season_id = v.req_str(body, "season_id")
    usage_type = v.req_enum(body, "usage_type", USAGE_TYPES)
    start_raw, start = v.req_date(body, "start_date")
    end_raw, end = v.req_date(body, "end_date")
    nightly_rate = v.req_int(body, "nightly_rate_cents")
    minimum_beds = v.req_int(body, "minimum_billable_beds")
    v.check(minimum_beds >= 0, "minimum_billable_beds", "must be at least 0")
    # Rung 4 -- end_date must be later than start_date.
    v.date_range(end > start, "end_date must be later than start_date.")
    # Rung 6 -- nightly_rate_cents must be greater than 0.
    v.positive(nightly_rate > 0, "nightly_rate_cents must be greater than 0.")
    # Rung 8 -- host school then season.
    find.school(school_id)
    find.season(season_id)
    # Rung 56 -- money, last.
    if nightly_rate > RATE_CAP_CENTS:
        raise ApiError("ERR_RATE_ABOVE_CAP",
                       "The per-bed-night rate exceeds the board's cap of 1500 cents.")

    record = new_record()
    record.update({
        "host_school_id": school_id,
        "season_id": season_id,
        "usage_type": usage_type,
        "start_date": start_raw,
        "end_date": end_raw,
        "_start_date": start,
        "_end_date": end,
        # end_date is EXCLUSIVE, so the night count is end - start.
        "_nights": days_between(start, end),
        "nightly_rate_cents": nightly_rate,
        "minimum_billable_beds": minimum_beds,
        "countered_nightly_rate_cents": None,
        "counter_round": 0,
        "effective_nightly_rate_cents": None,
        "status": "DRAFT",
        "cancel_reason": None,
        "_was_signed": False,
    })
    db.agreements[record["id"]] = record
    return object_response(serialize.agreement(record), 201)


@bp.route("/facility-agreements/<facility_agreement_id>", methods=["GET"])
@endpoint(ROLES)
def get_agreement(facility_agreement_id):
    return object_response(serialize.agreement(find.agreement(facility_agreement_id)))


@bp.route("/facility-agreements", methods=["GET"])
@endpoint(ROLES)
def list_agreements():
    school_id = v.arg_str("host_school_id")
    season_id = v.arg_str("season_id")
    status = v.arg_str("status")
    usage_type = v.arg_str("usage_type")
    records = []
    for record in sorted_records(db.agreements):
        if school_id is not None and record["host_school_id"] != school_id:
            continue
        if season_id is not None and record["season_id"] != season_id:
            continue
        if status is not None and record["status"] != status:
            continue
        if usage_type is not None and record["usage_type"] != usage_type:
            continue
        records.append(record)
    return paginate(records, serialize.agreement)


@bp.route("/facility-agreements/<facility_agreement_id>/submit", methods=["POST"])
@endpoint(["TourManager"])
def submit_agreement(facility_agreement_id):
    agreement = find.agreement(facility_agreement_id)
    if agreement["status"] not in ("DRAFT", "COUNTERED"):
        raise ApiError("ERR_INVALID_AGREEMENT_STATE",
                       "Only a DRAFT or COUNTERED agreement may be submitted.")
    agreement["status"] = "SUBMITTED"
    touch(agreement)
    return object_response(serialize.agreement(agreement))


@bp.route("/facility-agreements/<facility_agreement_id>/counter", methods=["POST"])
@endpoint(["TourManager"])
def counter_agreement(facility_agreement_id):
    body = v.get_body()
    # Rung 5 -- countered_nightly_rate_cents is required on a counter-offer.
    v.conditional(v.present(body, "countered_nightly_rate_cents"),
                  "countered_nightly_rate_cents is required on a counter-offer.")
    rate = v.req_int(body, "countered_nightly_rate_cents")
    agreement = find.agreement(facility_agreement_id)
    if agreement["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_AGREEMENT_STATE",
                       "Only a SUBMITTED agreement may be countered.")
    # Rung 51 -- at most two counter rounds may be recorded.
    if agreement["counter_round"] >= MAX_COUNTER_ROUNDS:
        raise ApiError("ERR_MAX_COUNTER_ROUNDS_EXCEEDED",
                       "This agreement has exhausted its counter rounds.")
    # Rung 56 -- the cap is checked on every counter too.
    if rate > RATE_CAP_CENTS:
        raise ApiError("ERR_RATE_ABOVE_CAP",
                       "The countered per-bed-night rate exceeds the cap of 1500 cents.")
    # No rate is pinned and no billing figure is computed on this branch.
    agreement["status"] = "COUNTERED"
    agreement["countered_nightly_rate_cents"] = rate
    agreement["counter_round"] = agreement["counter_round"] + 1
    touch(agreement)
    return object_response(serialize.agreement(agreement))


@bp.route("/facility-agreements/<facility_agreement_id>/sign", methods=["POST"])
@endpoint(["CorpsDirector"])
def sign_agreement(facility_agreement_id):
    agreement = find.agreement(facility_agreement_id)
    if agreement["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_AGREEMENT_STATE",
                       "Only a SUBMITTED agreement may be signed.")
    agreement["status"] = "SIGNED"
    agreement["_was_signed"] = True
    if agreement["counter_round"] > 0:
        agreement["effective_nightly_rate_cents"] = agreement["countered_nightly_rate_cents"]
    else:
        agreement["effective_nightly_rate_cents"] = agreement["nightly_rate_cents"]
    touch(agreement)
    return object_response(serialize.agreement(agreement))


@bp.route("/facility-agreements/<facility_agreement_id>/cancel", methods=["POST"])
@endpoint(["CorpsDirector"])
def cancel_agreement(facility_agreement_id):
    body = v.get_body()
    reason = v.req_str(body, "cancel_reason")
    agreement = find.agreement(facility_agreement_id)
    if agreement["status"] == "CANCELLED":
        raise ApiError("ERR_INVALID_AGREEMENT_STATE",
                       "This agreement is already CANCELLED.")
    services.cancel_agreement(agreement, reason)
    return object_response(serialize.agreement(agreement))
