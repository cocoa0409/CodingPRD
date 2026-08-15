"""Application endpoints (screening, decisions, conditions, rescreen, withdraw)."""
from flask import Blueprint

from db import DB, new_id
from errors import ApiError
from middleware import APPLICANT, AGENT, PM, auth
from response import ok, ok_list
from services import (
    get_application,
    published_offer_for,
    screening_recommendation,
    ser_application,
    sorted_created,
    stamp,
    touch,
)
from util import (
    apply_filters,
    as_enum,
    as_int,
    as_nonneg_int,
    as_str,
    body,
    pagination,
    required,
)

bp = Blueprint("applications", __name__)

STAFF = [PM, AGENT]
DECISIONS = ("APPROVED", "APPROVED_WITH_CONDITIONS", "DENIED")


def _valid_credit_score(v):
    v = as_int(v, "credit_score")
    if v < 300 or v > 850:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "credit_score must be between 300 and 850"
        )
    return v


@bp.post("/leasing/applications")
def create_application():
    auth(STAFF)
    data = body()
    inquiry_id = data.get("inquiry_id")
    waitlist_entry_id = data.get("waitlist_entry_id")
    floorplan_id = as_str(required(data, "floorplan_id"), "floorplan_id")
    applicant_name = as_str(required(data, "applicant_name"), "applicant_name")
    applicant_email = as_str(required(data, "applicant_email"), "applicant_email")
    annual_income_cents = as_nonneg_int(
        required(data, "annual_income_cents"), "annual_income_cents"
    )
    credit_score = _valid_credit_score(required(data, "credit_score"))
    if inquiry_id is not None:
        as_str(inquiry_id, "inquiry_id")
    if waitlist_entry_id is not None:
        as_str(waitlist_entry_id, "waitlist_entry_id")
    # Exactly one source reference.
    if (inquiry_id is None) == (waitlist_entry_id is None):
        raise ApiError(
            "ERR_APPLICATION_SOURCE_AMBIGUOUS",
            400,
            "Exactly one of inquiry_id / waitlist_entry_id must be supplied",
        )

    # Existence of the source and the floorplan.
    inquiry = None
    entry = None
    if inquiry_id is not None:
        inquiry = DB["inquiries"].get(inquiry_id)
        if inquiry is None:
            raise ApiError("ERR_INQUIRY_NOT_FOUND", 404, "Inquiry does not exist")
        source_floorplan_id = inquiry["floorplan_id"]
    else:
        entry = DB["waitlist_entries"].get(waitlist_entry_id)
        if entry is None:
            raise ApiError(
                "ERR_WAITLIST_ENTRY_NOT_FOUND", 404, "Waitlist entry does not exist"
            )
        source_floorplan_id = entry["floorplan_id"]
    fp = DB["floorplans"].get(floorplan_id)
    if fp is None:
        raise ApiError("ERR_FLOORPLAN_NOT_FOUND", 404, "Floorplan does not exist")

    # State gates (priority 4).
    if inquiry is not None:
        if inquiry["status"] not in ("CONTACTED", "TOUR_SCHEDULED"):
            raise ApiError(
                "ERR_INQUIRY_NOT_ACTIVE",
                409,
                "Inquiry-sourced applications require the inquiry in CONTACTED or "
                "TOUR_SCHEDULED",
            )
    else:
        if entry["status"] != "OFFERED":
            raise ApiError(
                "ERR_WAITLIST_INVALID_STATE",
                409,
                "Waitlist-sourced applications require the entry OFFERED and unexpired",
            )

    # Cross-reference integrity (priority 8).
    if floorplan_id != source_floorplan_id:
        raise ApiError(
            "ERR_APPLICATION_FLOORPLAN_MISMATCH",
            422,
            "application.floorplan_id must equal the source's floorplan_id",
        )

    offer = published_offer_for(floorplan_id)
    snapshot = (
        offer["effective_monthly_rent_cents"] if offer else fp["base_rent_cents"]
    )
    rec = {
        "id": new_id(),
        "inquiry_id": inquiry_id,
        "waitlist_entry_id": waitlist_entry_id,
        "floorplan_id": floorplan_id,
        "applicant_name": applicant_name,
        "applicant_email": applicant_email,
        "annual_income_cents": annual_income_cents,
        "credit_score": credit_score,
        "monthly_rent_snapshot_cents": snapshot,
        "recommendation": screening_recommendation(
            annual_income_cents, credit_score, snapshot
        ),
        "required_deposit_cents": None,
        "deposit_paid_cents": 0,
        "status": "SCREENING",
    }
    stamp(rec)
    DB["applications"][rec["id"]] = rec
    if entry is not None:
        entry["status"] = "CONVERTED"
        entry["linked_application_id"] = rec["id"]
        touch(entry)
    return ok(ser_application(rec), status=201)


@bp.get("/leasing/applications")
def list_applications():
    auth(STAFF)
    limit, offset = pagination()
    items = apply_filters(
        DB["applications"].values(),
        [
            ("floorplan_id", "floorplan_id"),
            ("inquiry_id", "inquiry_id"),
            ("waitlist_entry_id", "waitlist_entry_id"),
            ("status", "status"),
        ],
    )
    items = sorted_created(items)
    total = len(items)
    return ok_list(
        [ser_application(a) for a in items[offset : offset + limit]],
        total,
        limit,
        offset,
    )


@bp.get("/leasing/applications/<aid>")
def get_one_application(aid):
    auth([PM, AGENT, APPLICANT])
    return ok(ser_application(get_application(aid)))


@bp.post("/leasing/applications/<aid>/decide")
def decide_application(aid):
    auth([PM])
    app = get_application(aid)
    data = body()
    decision = as_enum(required(data, "decision"), "decision", DECISIONS)
    if app["status"] != "SCREENING":
        raise ApiError(
            "ERR_APPLICATION_INVALID_STATE",
            409,
            "Only a SCREENING application can be decided",
        )
    # Screening gate: no approval against a DENY recommendation.
    if decision in ("APPROVED", "APPROVED_WITH_CONDITIONS") and (
        app["recommendation"] == "DENY"
    ):
        raise ApiError(
            "ERR_SCREENING_BLOCKS_APPROVAL",
            422,
            "Recommendation DENY blocks an approval decision",
        )
    if decision == "APPROVED":
        app["required_deposit_cents"] = 1 * app["monthly_rent_snapshot_cents"]
    elif decision == "APPROVED_WITH_CONDITIONS":
        app["required_deposit_cents"] = 2 * app["monthly_rent_snapshot_cents"]
    app["status"] = decision
    touch(app)
    return ok(ser_application(app))


@bp.post("/leasing/applications/<aid>/rescreen")
def rescreen_application(aid):
    auth([PM])
    app = get_application(aid)
    data = body()
    annual_income_cents = as_nonneg_int(
        required(data, "annual_income_cents"), "annual_income_cents"
    )
    credit_score = _valid_credit_score(required(data, "credit_score"))
    if app["status"] != "APPROVED_WITH_CONDITIONS":
        raise ApiError(
            "ERR_APPLICATION_INVALID_STATE",
            409,
            "Only an APPROVED_WITH_CONDITIONS application can be re-screened",
        )
    app["annual_income_cents"] = annual_income_cents
    app["credit_score"] = credit_score
    # Snapshot rent is pinned at creation; re-screening does not re-resolve it.
    app["recommendation"] = screening_recommendation(
        annual_income_cents, credit_score, app["monthly_rent_snapshot_cents"]
    )
    app["required_deposit_cents"] = None
    app["deposit_paid_cents"] = 0
    app["status"] = "SCREENING"
    touch(app)
    return ok(ser_application(app))


@bp.post("/leasing/applications/<aid>/clear-conditions")
def clear_conditions(aid):
    auth([AGENT, PM])
    app = get_application(aid)
    data = body()
    payment = as_nonneg_int(required(data, "deposit_paid_cents"), "deposit_paid_cents")
    if app["status"] != "APPROVED_WITH_CONDITIONS":
        raise ApiError(
            "ERR_APPLICATION_INVALID_STATE",
            409,
            "Only an APPROVED_WITH_CONDITIONS application can clear conditions",
        )
    # Money check last: the payment must bring the total to the requirement.
    if app["deposit_paid_cents"] + payment < app["required_deposit_cents"]:
        raise ApiError(
            "ERR_DEPOSIT_INSUFFICIENT",
            402,
            "Deposit payment leaves deposit_paid_cents below required_deposit_cents",
        )
    app["deposit_paid_cents"] += payment
    app["status"] = "CONDITIONS_CLEARED"
    touch(app)
    return ok(ser_application(app))


@bp.post("/leasing/applications/<aid>/withdraw")
def withdraw_application(aid):
    auth([AGENT, PM])
    app = get_application(aid)
    if app["status"] not in ("SCREENING", "APPROVED_WITH_CONDITIONS"):
        raise ApiError(
            "ERR_APPLICATION_INVALID_STATE",
            409,
            "Only SCREENING or APPROVED_WITH_CONDITIONS applications can be withdrawn",
        )
    app["status"] = "WITHDRAWN"
    touch(app)
    return ok(ser_application(app))
