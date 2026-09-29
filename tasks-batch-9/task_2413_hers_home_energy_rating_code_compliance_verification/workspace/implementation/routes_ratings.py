"""Rating files: opening, confirming, voiding, registry submission and decisions."""

from flask import Blueprint

import calc
import validation as v
from auth import check_cert_level, check_certification_valid, endpoint, require_owner
from cascades import cascade_rating_void, create_corrective_action
from db import clock_now_iso, db, new_row, ordered, touch
from errors import ApiError
from graph import (
    LIVE_STAGES,
    builder_of_rating,
    corrective_actions_of_rating,
    governing_final,
    has_unresolved_corrective_action,
    packages_of_rating,
    plan_of_rating,
    ratings_of_home,
    require_home,
    require_rater,
    require_rating,
    subdivision_of_home,
    subdivision_of_rating,
)
from ops import check_not_locked, check_not_void, invalid_state, is_void
from response import Result
from serializers import corrective_action_out, document_package_out, rating_out

bp = Blueprint("ratings", __name__)

STAGES = ("PROJECTED", "ROUGH_IN_VERIFIED", "CONFIRMED", "REGISTERED", "VOID")
READ_ROLES = (
    "RatingProviderAdmin",
    "CertifiedRater",
    "FieldInspector",
    "QADesignee",
    "BuilderRep",
)


@bp.post("/ratings")
@endpoint(["CertifiedRater"])
def create_rating():
    data = v.body()
    home_id = v.req_str(data, "home_id")
    rater_id = v.req_str(data, "rater_id")
    supersedes_rating_id = v.opt_str(data, "supersedes_rating_id")

    home = require_home(home_id)
    require_rater(rater_id)
    predecessor = None
    if supersedes_rating_id is not None:
        predecessor = require_rating(supersedes_rating_id)

    check_certification_valid(rater_id)
    check_cert_level(rater_id, ("RATER",))

    subdivision = subdivision_of_home(home)
    plan = db.plan_models.get(home["plan_model_id"])
    if (
        plan is None
        or subdivision is None
        or plan["subdivision_id"] != home["subdivision_id"]
        or plan["status"] != "ACTIVE"
    ):
        raise ApiError("ERR_PLAN_MODEL_MISMATCH")

    for existing in ratings_of_home(home_id):
        if existing["stage"] not in LIVE_STAGES:
            continue
        replaceable = (
            predecessor is not None
            and predecessor["id"] == existing["id"]
            and (
                existing["stage"] == "VOID" or existing["qa_status"] == "QA_FAILED"
            )
        )
        if not replaceable:
            raise ApiError("ERR_DUPLICATE_ACTIVE_RATING")

    row = new_row(
        "Rating",
        {
            "home_id": home_id,
            "rater_id": rater_id,
            "plan_model_id": home["plan_model_id"],
            "supersedes_rating_id": supersedes_rating_id,
            "stage": "PROJECTED",
            "compliance_status": "UNDETERMINED",
            "qa_status": "NOT_SELECTED",
            "registry_status": "NOT_SUBMITTED",
            "projected_index": plan["projected_index"],
            "confirmed_index": None,
            "confirmed_ach50": None,
            "confirmed_duct_leakage_cfm25_per_100sqft": None,
            "eri_target": None,
            "compliance_path": "NONE",
            "submitted_index": None,
            "registry_confirmation_number": None,
            "rejection_reason": None,
            "file_locked": False,
            "confirmed_at": None,
        },
    )
    db.ratings[row["id"]] = row
    return Result(row, rating_out, status=201)


@bp.get("/ratings/<rating_id>")
@endpoint(list(READ_ROLES))
def get_rating(rating_id):
    return Result(require_rating(rating_id), rating_out)


@bp.get("/ratings")
@endpoint(list(READ_ROLES))
def list_ratings():
    limit, offset = v.pagination()
    home_id = v.query_str("home_id")
    rater_id = v.query_str("rater_id")
    plan_model_id = v.query_str("plan_model_id")
    supersedes_rating_id = v.query_str("supersedes_rating_id")
    stage = v.query_enum("stage", STAGES)

    rows = []
    for rating in db.ratings.values():
        if home_id is not None and rating["home_id"] != home_id:
            continue
        if rater_id is not None and rating["rater_id"] != rater_id:
            continue
        if plan_model_id is not None and rating["plan_model_id"] != plan_model_id:
            continue
        if (
            supersedes_rating_id is not None
            and rating["supersedes_rating_id"] != supersedes_rating_id
        ):
            continue
        if stage is not None and rating["stage"] != stage:
            continue
        rows.append(rating)
    rows = ordered(rows)
    page, total = v.paginate(rows, limit, offset)
    return Result(page, rating_out, page=(limit, offset, total))


@bp.post("/ratings/<rating_id>/confirm")
@endpoint(["CertifiedRater"])
def confirm_rating(rating_id):
    rating = require_rating(rating_id)
    require_owner(rating["rater_id"])

    # §3.8 pins the void and file-lock answers for this endpoint, so they are
    # decided before the general state admissibility check (§2.8 note on step 7).
    check_not_void(rating)
    check_not_locked(rating)

    if rating["stage"] == "CONFIRMED":
        if rating["compliance_status"] != "REMEDIATION_PENDING":
            invalid_state(
                "A CONFIRMED rating may only be re-confirmed from REMEDIATION_PENDING."
            )
    elif rating["stage"] not in ("PROJECTED", "ROUGH_IN_VERIFIED"):
        invalid_state("Confirmation is not admissible from stage %s." % rating["stage"])

    check_certification_valid(rating["rater_id"])
    check_cert_level(rating["rater_id"], ("RATER",))

    governing = governing_final(rating)
    if governing is None:
        raise ApiError("ERR_MISSING_GOVERNING_TEST")
    _inspection, blower, duct = governing

    plan = plan_of_rating(rating)
    subdivision = subdivision_of_rating(rating)

    rating["confirmed_ach50"] = blower["normalized_value"]
    rating["confirmed_duct_leakage_cfm25_per_100sqft"] = duct["normalized_value"]
    rating["confirmed_index"] = calc.confirmed_index(
        plan,
        subdivision,
        rating["confirmed_ach50"],
        rating["confirmed_duct_leakage_cfm25_per_100sqft"],
    )
    rating["eri_target"] = calc.ERI_TARGET[subdivision["code_edition"]][
        subdivision["climate_zone"]
    ]
    path, status = calc.compliance_path_selection(rating, plan, subdivision)
    rating["compliance_path"] = path
    rating["compliance_status"] = status
    rating["confirmed_at"] = clock_now_iso()
    rating["stage"] = "CONFIRMED"
    touch(rating)

    if status == "FAILING":
        create_corrective_action(rating, "THRESHOLD_FAILURE")

    home = db.homes.get(rating["home_id"])
    if home is not None and home["sampling_role"] == "TESTED":
        sample_set = db.sample_sets.get(home["sample_set_id"])
        if sample_set is not None and sample_set["status"] == "SELECTED":
            sample_set["status"] = "TESTED"
            touch(sample_set)

    return Result(rating, rating_out)


@bp.post("/ratings/<rating_id>/void")
@endpoint(["RatingProviderAdmin"])
def void_rating(rating_id):
    data = v.body()
    v.req_str(data, "reason")

    rating = require_rating(rating_id)
    if rating["stage"] == "VOID":
        invalid_state("The rating is already VOID.")

    rating["stage"] = "VOID"
    rating["compliance_status"] = "FAILING"
    rating["file_locked"] = True
    touch(rating)
    cascade_rating_void(rating)
    return Result(rating, rating_out)


@bp.post("/ratings/<rating_id>/submit-to-registry")
@endpoint(["CertifiedRater"])
def submit_to_registry(rating_id):
    rating = require_rating(rating_id)
    require_owner(rating["rater_id"])

    check_not_void(rating)
    check_not_locked(rating)

    if rating["stage"] != "CONFIRMED" or rating["registry_status"] not in (
        "NOT_SUBMITTED",
        "REJECTED",
    ):
        invalid_state("Registry submission is not admissible from this state.")

    check_certification_valid(rating["rater_id"])
    check_cert_level(rating["rater_id"], ("RATER",))

    if rating["compliance_status"] != "PASSING" or rating["qa_status"] == "QA_FAILED":
        raise ApiError("ERR_RATING_NOT_COMPLIANT")

    if has_unresolved_corrective_action(rating["id"]):
        raise ApiError("ERR_OPEN_CORRECTIVE_ACTION")

    rater = db.raters.get(rating["rater_id"])
    if rater is not None and rater["registry_hold"]:
        raise ApiError("ERR_RATER_QA_DEFICIT")

    rating["registry_status"] = "PENDING"
    rating["rejection_reason"] = None
    rating["submitted_index"] = rating["confirmed_index"]
    rating["file_locked"] = True
    touch(rating)
    return Result(rating, rating_out)


@bp.post("/ratings/<rating_id>/registry-decision")
@endpoint(["RatingProviderAdmin"])
def registry_decision(rating_id):
    data = v.body()
    outcome = v.req_enum(data, "outcome", ("ACCEPT", "REJECT"))
    confirmation_number = v.opt_str(data, "confirmation_number")
    rejection_reason = v.opt_str(data, "rejection_reason")
    if outcome == "ACCEPT" and confirmation_number is None:
        v.invalid("Field 'confirmation_number' is required when outcome is ACCEPT.")
    if outcome == "REJECT" and rejection_reason is None:
        v.invalid("Field 'rejection_reason' is required when outcome is REJECT.")

    rating = require_rating(rating_id)
    if rating["registry_status"] != "PENDING":
        invalid_state("A registry decision requires registry_status PENDING.")

    if outcome == "ACCEPT":
        rating["registry_status"] = "ACCEPTED"
        rating["registry_confirmation_number"] = confirmation_number
        if rating["stage"] == "CONFIRMED":
            rating["stage"] = "REGISTERED"
        rating["file_locked"] = True
    else:
        rating["registry_status"] = "REJECTED"
        rating["rejection_reason"] = rejection_reason
        rating["submitted_index"] = None
        rating["file_locked"] = False
    touch(rating)
    return Result(rating, rating_out)


@bp.get("/ratings/<rating_id>/corrective-actions")
@endpoint(["RatingProviderAdmin", "CertifiedRater", "QADesignee", "BuilderRep"])
def list_rating_corrective_actions(rating_id):
    limit, offset = v.pagination()
    require_rating(rating_id)
    rows = corrective_actions_of_rating(rating_id)
    page, total = v.paginate(rows, limit, offset)
    return Result(page, corrective_action_out, page=(limit, offset, total))


@bp.get("/ratings/<rating_id>/document-packages")
@endpoint(["RatingProviderAdmin", "CertifiedRater", "QADesignee", "BuilderRep"])
def list_rating_document_packages(rating_id):
    limit, offset = v.pagination()
    require_rating(rating_id)
    rows = packages_of_rating(rating_id)
    page, total = v.paginate(rows, limit, offset)
    return Result(page, document_package_out, page=(limit, offset, total))


_UNUSED = (builder_of_rating, is_void, packages_of_rating)
