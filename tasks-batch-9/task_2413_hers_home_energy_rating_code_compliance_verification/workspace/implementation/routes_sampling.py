"""The sampling protocol: windows, membership, tested-home selection and closure."""

from flask import Blueprint, g

import calc
import validation as v
from auth import check_cert_level, check_certification_valid, endpoint
from cascades import cascade_sample_set_failure
from db import db, new_row, ordered, touch
from errors import ApiError
from graph import (
    builder_of_subdivision,
    live_rating_of_home,
    members_of_sample_set,
    ratings_of_home,
    require_home,
    require_sample_set,
    require_subdivision,
    sample_sets_of_subdivision,
)
from ops import invalid_state
from response import Result
from serializers import home_out, sample_set_out

bp = Blueprint("sampling", __name__)

SAMPLE_SET_STATUSES = (
    "FORMING",
    "SELECTED",
    "TESTED",
    "CLOSED_PASS",
    "FAILED_EXPANDED",
    "VOIDED_SAMPLING",
)
LIVE_SET_STATUSES = ("FORMING", "SELECTED", "TESTED")
READ_ROLES = (
    "RatingProviderAdmin",
    "CertifiedRater",
    "FieldInspector",
    "QADesignee",
    "BuilderRep",
)


@bp.post("/sample-sets")
@endpoint(["CertifiedRater"])
def create_sample_set():
    data = v.body()
    subdivision_id = v.req_str(data, "subdivision_id")
    window_start = v.req_date(data, "window_start_date")
    window_end = v.req_date(data, "window_end_date")
    if window_end < window_start:
        v.invalid("Field 'window_end_date' must be on or after 'window_start_date'.")

    subdivision = require_subdivision(subdivision_id)

    check_certification_valid(g.user_id)
    check_cert_level(g.user_id, ("RATER",))

    if not subdivision["sampling_enabled"]:
        raise ApiError("ERR_SAMPLING_NOT_ENABLED")

    builder = builder_of_subdivision(subdivision)
    if builder is None or not builder["sampling_eligible"]:
        raise ApiError("ERR_BUILDER_SAMPLING_INELIGIBLE")

    for other in sample_sets_of_subdivision(subdivision_id):
        if other["status"] not in LIVE_SET_STATUSES:
            continue
        if window_start <= other["window_end_date"] and other[
            "window_start_date"
        ] <= window_end:
            raise ApiError("ERR_SAMPLE_WINDOW_CONFLICT")

    row = new_row(
        "SampleSet",
        {
            "subdivision_id": subdivision_id,
            "window_start_date": window_start,
            "window_end_date": window_end,
            "status": "FORMING",
            "tested_home_id": None,
            "member_count": 0,
            "tested_member_count": 0,
            "represented_member_count": 0,
            "representative_index": None,
        },
    )
    db.sample_sets[row["id"]] = row
    return Result(row, sample_set_out, status=201)


@bp.get("/sample-sets/<sample_set_id>")
@endpoint(list(READ_ROLES))
def get_sample_set(sample_set_id):
    return Result(require_sample_set(sample_set_id), sample_set_out)


@bp.get("/sample-sets")
@endpoint(["RatingProviderAdmin", "CertifiedRater", "QADesignee", "BuilderRep"])
def list_sample_sets():
    limit, offset = v.pagination()
    subdivision_id = v.query_str("subdivision_id")
    tested_home_id = v.query_str("tested_home_id")
    status = v.query_enum("status", SAMPLE_SET_STATUSES)

    rows = []
    for sample_set in db.sample_sets.values():
        if subdivision_id is not None and sample_set["subdivision_id"] != subdivision_id:
            continue
        if tested_home_id is not None and sample_set["tested_home_id"] != tested_home_id:
            continue
        if status is not None and sample_set["status"] != status:
            continue
        rows.append(sample_set)
    rows = ordered(rows)
    page, total = v.paginate(rows, limit, offset)
    return Result(page, sample_set_out, page=(limit, offset, total))


@bp.post("/sample-sets/<sample_set_id>/homes")
@endpoint(["CertifiedRater"])
def add_sample_set_home(sample_set_id):
    data = v.body()
    home_id = v.req_str(data, "home_id")
    expected_version = v.req_int(data, "expected_sample_set_version")

    sample_set = require_sample_set(sample_set_id)
    home = require_home(home_id)

    if sample_set["status"] != "FORMING":
        invalid_state("Homes may only be added to a FORMING sample set.")

    if expected_version != sample_set["version"]:
        raise ApiError("ERR_STALE_SAMPLE_SET_VERSION")

    check_certification_valid(g.user_id)
    check_cert_level(g.user_id, ("RATER",))

    if home["subdivision_id"] != sample_set["subdivision_id"]:
        raise ApiError("ERR_HOME_SUBDIVISION_MISMATCH")

    if home["individual_testing_required"]:
        raise ApiError("ERR_REPRESENTED_HOME_NOT_TESTABLE")

    subdivision = require_subdivision(sample_set["subdivision_id"])
    if not subdivision["sampling_enabled"]:
        raise ApiError("ERR_SAMPLING_NOT_ENABLED")

    if home["sample_set_id"] is not None:
        raise ApiError("ERR_HOME_ALREADY_SAMPLED")

    if not (
        sample_set["window_start_date"]
        <= home["permit_date"]
        <= sample_set["window_end_date"]
    ):
        raise ApiError("ERR_HOME_PERMIT_OUTSIDE_WINDOW")

    if len(members_of_sample_set(sample_set_id)) + 1 > calc.SAMPLE_SET_MAX_MEMBERS:
        raise ApiError("ERR_SAMPLE_SET_SIZE_INVALID")

    home["sample_set_id"] = sample_set_id
    home["sampling_role"] = "MEMBER"
    touch(home)
    touch(sample_set)
    return Result(home, home_out, status=201)


@bp.post("/sample-sets/<sample_set_id>/homes/<home_id>/withdraw")
@endpoint(["CertifiedRater"])
def withdraw_sample_set_home(sample_set_id, home_id):
    data = v.body()
    expected_version = v.req_int(data, "expected_sample_set_version")

    sample_set = require_sample_set(sample_set_id)
    home = db.homes.get(home_id)
    if home is None or home["sample_set_id"] != sample_set_id:
        raise ApiError("ERR_HOME_NOT_FOUND")

    if sample_set["status"] != "FORMING":
        invalid_state("Homes may only be withdrawn from a FORMING sample set.")

    if expected_version != sample_set["version"]:
        raise ApiError("ERR_STALE_SAMPLE_SET_VERSION")

    home["sample_set_id"] = None
    home["sampling_role"] = "UNASSIGNED"
    touch(home)
    touch(sample_set)
    return Result(home, home_out)


def _selection_candidates(sample_set):
    candidates = []
    for home in members_of_sample_set(sample_set["id"]):
        if home["individual_testing_required"]:
            continue
        rating = None
        for candidate_rating in ratings_of_home(home["id"]):
            if (
                candidate_rating["stage"] == "PROJECTED"
                and candidate_rating["registry_status"] == "NOT_SUBMITTED"
            ):
                rating = candidate_rating
                break
        if rating is None:
            continue
        plan = db.plan_models.get(home["plan_model_id"])
        cfa = plan["conditioned_floor_area_sqft"] if plan else 0
        candidates.append((home, rating, cfa))
    return candidates


@bp.post("/sample-sets/<sample_set_id>/select")
@endpoint(["RatingProviderAdmin"])
def select_tested_home(sample_set_id):
    sample_set = require_sample_set(sample_set_id)

    if sample_set["status"] != "FORMING":
        invalid_state("Only a FORMING sample set can be selected.")

    subdivision = require_subdivision(sample_set["subdivision_id"])
    if not subdivision["sampling_enabled"]:
        raise ApiError("ERR_SAMPLING_NOT_ENABLED")

    members = members_of_sample_set(sample_set_id)
    if (
        len(members) < calc.SAMPLE_SET_MIN_MEMBERS
        or len(members) > calc.SAMPLE_SET_MAX_MEMBERS
    ):
        raise ApiError("ERR_SAMPLE_SET_SIZE_INVALID")

    builder = builder_of_subdivision(subdivision)
    if builder is None or not builder["sampling_eligible"]:
        raise ApiError("ERR_BUILDER_SAMPLING_INELIGIBLE")

    candidates = _selection_candidates(sample_set)
    if not candidates:
        raise ApiError("ERR_NO_ELIGIBLE_SAMPLE_HOME")

    candidates.sort(
        key=lambda item: (
            -item[1]["projected_index"],
            -calc.dec(item[2]),
            item[0]["created_at"],
            item[0]["_seq"],
        )
    )
    tested_home = candidates[0][0]

    sample_set["tested_home_id"] = tested_home["id"]
    sample_set["status"] = "SELECTED"
    touch(sample_set)
    tested_home["sampling_role"] = "TESTED"
    touch(tested_home)
    return Result(sample_set, sample_set_out)


@bp.post("/sample-sets/<sample_set_id>/close")
@endpoint(["RatingProviderAdmin"])
def close_sample_set(sample_set_id):
    sample_set = require_sample_set(sample_set_id)

    # SELECTED is admissible as a from-state so that the empty tested-rating input
    # set reports ERR_SAMPLE_SET_NO_TESTED_RATING rather than ERR_INVALID_STATE.
    if sample_set["status"] not in ("SELECTED", "TESTED"):
        invalid_state("Only a TESTED sample set can be closed.")

    tested_home_id = sample_set["tested_home_id"]
    tested_home = db.homes.get(tested_home_id) if tested_home_id else None
    tested_rating = live_rating_of_home(tested_home_id) if tested_home else None
    if (
        tested_home is None
        or tested_rating is None
        or tested_rating["stage"] not in ("CONFIRMED", "REGISTERED")
    ):
        raise ApiError("ERR_SAMPLE_SET_NO_TESTED_RATING")

    if tested_rating["compliance_status"] == "PASSING":
        tested_indices = []
        for home in members_of_sample_set(sample_set_id):
            if home["sampling_role"] != "TESTED":
                continue
            rating = live_rating_of_home(home["id"])
            if (
                rating is not None
                and rating["stage"] == "CONFIRMED"
                and rating["compliance_status"] == "PASSING"
                and rating["confirmed_index"] is not None
            ):
                tested_indices.append(rating["confirmed_index"])
        if not tested_indices:
            raise ApiError("ERR_SAMPLE_SET_NO_TESTED_RATING")
        representative_index = max(tested_indices)

        sample_set["representative_index"] = representative_index
        sample_set["status"] = "CLOSED_PASS"
        touch(sample_set)
        for home in members_of_sample_set(sample_set_id):
            if home["id"] == tested_home_id:
                continue
            home["sampling_role"] = "REPRESENTED"
            touch(home)
            rating = live_rating_of_home(home["id"])
            if rating is not None:
                rating["confirmed_index"] = representative_index
                rating["compliance_status"] = "PASSING"
                touch(rating)
    elif tested_rating["compliance_status"] == "FAILING":
        sample_set["status"] = "FAILED_EXPANDED"
        sample_set["representative_index"] = None
        touch(sample_set)
        cascade_sample_set_failure(sample_set)
    else:
        invalid_state(
            "The tested home's rating must be PASSING or FAILING to close the set."
        )

    return Result(sample_set, sample_set_out)
