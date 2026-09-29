"""Bid solicitations, sealed bids, tabulation and award (PRD 3.5)."""

from flask import Blueprint

import clock
import db
import errors
import middleware
import paging
import response
import validation
from errors import fail
from routes import API_PREFIX
from services import calc, domain, serializers
from services import constants as C

bp = Blueprint("solicitations", __name__)

READ_ROLES = middleware.STAFF_ROLES + (middleware.CONTRACTOR,)


# ---------------------------------------------------------------------------
# solicitations
# ---------------------------------------------------------------------------


@bp.post(API_PREFIX + "/bid-solicitations")
@middleware.roles(middleware.REHAB_SPECIALIST)
def create_solicitation():
    body = validation.json_body()
    application = validation.body_fk(
        body, "application_id", db.applications, errors.ERR_APPLICATION_NOT_FOUND
    )
    validation.field_id(body, "application_id")
    write_up = validation.body_fk(
        body, "write_up_id", db.write_ups, errors.ERR_WRITE_UP_NOT_FOUND
    )
    validation.field_id(body, "write_up_id")
    bid_due_at = validation.field_datetime(body, "bid_due_at")
    min_bids_required = validation.field_int(
        body, "min_bids_required", required=False, default=2, minimum=1, maximum=5
    )

    if application["workflow_state"] != "WRITEUP_APPROVED":
        fail(errors.ERR_INVALID_STATE, "The case has no approved scope awaiting solicitation.")
    if write_up["application_id"] != application["id"]:
        fail(errors.ERR_INVALID_STATE, "The write-up does not belong to the addressed case.")
    if write_up["state"] != "APPROVED":
        fail(errors.ERR_INVALID_STATE, "The referenced write-up is not approved.")
    if write_up["priority_repair_total_cents"] <= 0:
        fail(errors.ERR_PRIORITY_REPAIRS_NOT_ADDRESSED)

    ice = write_up["total_estimate_cents"]
    ceiling, floor = calc.responsive_band(ice)

    row = db.new_row()
    row.update(
        {
            "application_id": application["id"],
            "write_up_id": write_up["id"],
            "award_bid_id": None,
            "bid_due_at": bid_due_at,
            "min_bids_required": min_bids_required,
            "independent_cost_estimate_cents": ice,
            "responsive_ceiling_cents": ceiling,
            "responsive_floor_cents": floor,
            "status": "OPEN",
            "bid_count": 0,
            "responsive_bid_count": 0,
            "reopen_count": 0,
            "awarded_by_user_id": None,
        }
    )
    db.solicitations[row["id"]] = row

    application["workflow_state"] = "BID_OPEN"
    db.touch(application)

    return response.object_response(serializers.solicitation(row), 201)


@bp.post(API_PREFIX + "/bid-solicitations/<solicitation_id>/tabulate")
@middleware.roles(middleware.REHAB_SPECIALIST)
def tabulate(solicitation_id):
    row = validation.path_row(
        db.solicitations, solicitation_id, errors.ERR_SOLICITATION_NOT_FOUND
    )
    if row["status"] != "OPEN":
        fail(errors.ERR_INVALID_STATE, "Only an open solicitation may be tabulated.")
    if row["bid_count"] < row["min_bids_required"]:
        fail(errors.ERR_INSUFFICIENT_BIDS)

    application = db.applications.get(row["application_id"])
    bids = domain.bids_of(row["id"])

    for bid in bids:
        if bid["status"] != "SUBMITTED":
            continue
        contractor = db.contractors.get(bid["contractor_id"])
        reason = calc.classify_bid(bid, row, application, contractor)
        if reason is None:
            bid["status"] = "RESPONSIVE"
            bid["non_responsive_reason"] = None
        else:
            bid["status"] = "NON_RESPONSIVE"
            bid["non_responsive_reason"] = reason
            bid["rank"] = None
        db.touch(bid)

    def _score_of(bid):
        contractor = db.contractors.get(bid["contractor_id"])
        return domain.performance_score(contractor) if contractor else 0

    responsive = [bid for bid in bids if bid["status"] == "RESPONSIVE"]
    responsive.sort(key=lambda bid: calc.rank_key(bid, _score_of(bid)))
    for index, bid in enumerate(responsive, start=1):
        bid["rank"] = index

    domain.recompute_solicitation_counts(row)

    if responsive:
        row["status"] = "TABULATED"
        db.touch(row)
    else:
        row["status"] = "FAILED"
        db.touch(row)
        if application is not None and application["workflow_state"] == "BID_OPEN":
            application["workflow_state"] = "BID_FAILED"
            db.touch(application)

    return response.object_response(serializers.solicitation(row))


def _inflated_window(bid):
    start = clock.add_days(bid["proposed_start_date"], -C.CREW_TURNOVER_BUFFER_DAYS)
    end = clock.add_days(bid["proposed_end_date"], C.CREW_TURNOVER_BUFFER_DAYS)
    return start, end


def _capacity_conflict(candidate):
    start, end = _inflated_window(candidate)
    overlaps = 0
    for other in db.ordered(list(db.bids.values())):
        if other["id"] == candidate["id"]:
            continue
        if other["contractor_id"] != candidate["contractor_id"]:
            continue
        if other["status"] != "AWARDED":
            continue
        solicitation = db.solicitations.get(other["solicitation_id"])
        if solicitation is None:
            continue
        application = db.applications.get(solicitation["application_id"])
        if application is None or application["workflow_state"] == "CLOSED":
            continue
        if start <= other["proposed_end_date"] and other["proposed_start_date"] <= end:
            overlaps += 1
    return overlaps >= C.MAX_CONCURRENT_AWARDS


@bp.post(API_PREFIX + "/bid-solicitations/<solicitation_id>/award")
@middleware.roles(middleware.PROGRAM_MANAGER)
def award(solicitation_id):
    row = validation.path_row(
        db.solicitations, solicitation_id, errors.ERR_SOLICITATION_NOT_FOUND
    )
    body = validation.json_body()
    bid = validation.body_fk(body, "bid_id", db.bids, errors.ERR_BID_NOT_FOUND)
    validation.field_id(body, "bid_id")

    if row["status"] != "TABULATED":
        fail(errors.ERR_INVALID_STATE, "Only a tabulated solicitation may be awarded.")

    if _capacity_conflict(bid):
        fail(errors.ERR_CONTRACTOR_CAPACITY_CONFLICT)

    if bid["status"] != "RESPONSIVE" or bid["solicitation_id"] != row["id"]:
        fail(errors.ERR_BID_NOT_RESPONSIVE)

    contractor = db.contractors.get(bid["contractor_id"])
    if contractor is None or contractor["approved_list_status"] != "APPROVED":
        fail(errors.ERR_CONTRACTOR_NOT_APPROVED)

    application = db.applications.get(row["application_id"])
    if application is not None and application["lead_review_required"]:
        if not contractor["lead_safe_certified"]:
            fail(errors.ERR_CONTRACTOR_NOT_LEAD_CERTIFIED)

    row["status"] = "AWARDED"
    row["award_bid_id"] = bid["id"]
    row["awarded_by_user_id"] = middleware.user_id()
    db.touch(row)

    bid["status"] = "AWARDED"
    db.touch(bid)

    for other in domain.bids_of(row["id"]):
        if other["id"] == bid["id"]:
            continue
        if other["status"] in ("RESPONSIVE", "NON_RESPONSIVE"):
            other["status"] = "REJECTED"
            db.touch(other)

    if application is not None:
        application["awarded_contractor_id"] = contractor["id"]
        if application["workflow_state"] == "BID_OPEN":
            application["workflow_state"] = "AWARDED"
        db.touch(application)

    db.touch(contractor)

    return response.object_response(serializers.solicitation(row))


@bp.post(API_PREFIX + "/bid-solicitations/<solicitation_id>/reopen")
@middleware.roles(middleware.PROGRAM_MANAGER)
def reopen(solicitation_id):
    row = validation.path_row(
        db.solicitations, solicitation_id, errors.ERR_SOLICITATION_NOT_FOUND
    )
    body = validation.json_body()
    new_bid_due_at = validation.field_datetime(body, "new_bid_due_at")

    if row["status"] != "FAILED":
        fail(errors.ERR_INVALID_STATE, "Only a failed solicitation may be reopened.")
    if new_bid_due_at <= clock.now():
        fail(
            errors.ERR_INVALID_STATE,
            "The new bid due instant must be strictly after the current instant.",
        )

    for bid in domain.bids_of(row["id"]):
        if bid["status"] in ("RESPONSIVE", "NON_RESPONSIVE"):
            bid["status"] = "REJECTED"
            db.touch(bid)

    row["status"] = "OPEN"
    row["bid_due_at"] = new_bid_due_at
    row["reopen_count"] += 1
    row["bid_count"] = 0
    row["responsive_bid_count"] = 0
    db.touch(row)

    application = db.applications.get(row["application_id"])
    if application is not None and application["workflow_state"] == "BID_FAILED":
        application["workflow_state"] = "BID_OPEN"
        db.touch(application)

    return response.object_response(serializers.solicitation(row))


@bp.get(API_PREFIX + "/bid-solicitations/<solicitation_id>")
@middleware.roles(*READ_ROLES)
def read_solicitation(solicitation_id):
    row = validation.path_row(
        db.solicitations, solicitation_id, errors.ERR_SOLICITATION_NOT_FOUND
    )
    return response.object_response(serializers.solicitation(row))


@bp.get(API_PREFIX + "/bid-solicitations")
@middleware.roles(*READ_ROLES)
def list_solicitations():
    application_id = validation.filter_str("application_id")
    write_up_id = validation.filter_str("write_up_id")
    award_bid_id = validation.filter_str("award_bid_id")
    status = validation.filter_enum("status", C.SOLICITATION_STATUSES)
    rows = []
    for row in db.solicitations.values():
        if application_id is not None and row["application_id"] != application_id:
            continue
        if write_up_id is not None and row["write_up_id"] != write_up_id:
            continue
        if award_bid_id is not None and row["award_bid_id"] != award_bid_id:
            continue
        if status is not None and row["status"] != status:
            continue
        rows.append(row)
    return paging.collection(rows, serializers.solicitation)


# ---------------------------------------------------------------------------
# bids
# ---------------------------------------------------------------------------


@bp.post(API_PREFIX + "/bids")
@middleware.roles(middleware.CONTRACTOR)
def create_bid():
    body = validation.json_body()
    middleware.scope_body_contractor(body)

    solicitation = validation.body_fk(
        body, "solicitation_id", db.solicitations, errors.ERR_SOLICITATION_NOT_FOUND
    )
    validation.field_id(body, "solicitation_id")
    contractor = validation.body_fk(
        body, "contractor_id", db.contractors, errors.ERR_CONTRACTOR_NOT_FOUND
    )
    validation.field_id(body, "contractor_id")
    amount = validation.field_int(body, "amount_cents", minimum=1)
    start = validation.field_datetime(body, "proposed_start_date")
    end = validation.field_datetime(body, "proposed_end_date")
    if end < start:
        fail(
            errors.ERR_INVALID_REQUEST,
            "Field 'proposed_end_date' may not precede 'proposed_start_date'.",
        )

    if clock.now() >= solicitation["bid_due_at"]:
        fail(errors.ERR_BID_WINDOW_CLOSED)

    for existing in db.bids.values():
        if existing["solicitation_id"] != solicitation["id"]:
            continue
        if existing["contractor_id"] != contractor["id"]:
            continue
        if existing["status"] in ("SUBMITTED", "RESPONSIVE", "NON_RESPONSIVE", "AWARDED"):
            fail(errors.ERR_DUPLICATE_BID)

    row = db.new_row()
    row.update(
        {
            "solicitation_id": solicitation["id"],
            "contractor_id": contractor["id"],
            "amount_cents": amount,
            "proposed_start_date": start,
            "proposed_end_date": end,
            "submitted_at": clock.now(),
            "status": "SUBMITTED",
            "non_responsive_reason": None,
            "rank": None,
        }
    )
    db.bids[row["id"]] = row

    solicitation["bid_count"] += 1
    db.touch(solicitation)

    return response.object_response(serializers.bid(row), 201)


@bp.get(API_PREFIX + "/bids/<bid_id>")
@middleware.roles(*READ_ROLES)
def read_bid(bid_id):
    row = validation.path_row(db.bids, bid_id, errors.ERR_BID_NOT_FOUND)
    return response.object_response(serializers.bid(row))


@bp.get(API_PREFIX + "/bids")
@middleware.roles(*READ_ROLES)
def list_bids():
    solicitation_id = validation.filter_str("solicitation_id")
    contractor_id = validation.filter_str("contractor_id")
    status = validation.filter_enum("status", C.BID_STATUSES)
    rows = []
    for row in db.bids.values():
        if solicitation_id is not None and row["solicitation_id"] != solicitation_id:
            continue
        if contractor_id is not None and row["contractor_id"] != contractor_id:
            continue
        if status is not None and row["status"] != status:
            continue
        rows.append(row)
    return paging.collection(rows, serializers.bid)
