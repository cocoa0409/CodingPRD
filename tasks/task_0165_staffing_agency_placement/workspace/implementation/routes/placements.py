"""Placement routes (PRD 3.4, 3.5, 3.7)."""

from flask import Blueprint, request

import db
import errors
from errors import ApiError
from middleware import (
    get_user_context, require_role, get_json_body, parse_pagination, paginate,
)
from response import object_response, array_response
from services import common, serialize, recompute, ownership
from services import calc

bp = Blueprint("placements", __name__)


def _ranges_overlap_closed(s1, e1, s2, e2):
    """Closed-interval overlap: shared endpoints conflict (PRD 3.4).
    [s1,e1] and [s2,e2] overlap iff s1 <= e2 and s2 <= e1."""
    return s1 <= e2 and s2 <= e1


def _end_assignment_side_effects(placement):
    """Shared ACTIVE -> ENDED side effects (PRD 3.5).

    1. Client.open_exposure recomputed (this placement's bill drops out — its
       assignment_status is set to ENDED before calling this).
    2. JobOrder.filled_count -= 1; FILLED -> OPEN if it drops below openings.
    3. Candidate -> AVAILABLE if it now has no remaining ACTIVE placements.
    """
    client_id = placement.get("client_id")
    jo = db.job_orders.get(placement["job_order_id"])

    # PRD 3.5: filled_count is decreased by one; if that drops it below
    # openings while the order is FILLED, the order returns FILLED -> OPEN.
    if jo is not None:
        jo["filled_count"] = jo["filled_count"] - 1
        common.touch(jo)
        if jo["status"] == "FILLED" and jo["filled_count"] < jo["openings"]:
            jo["status"] = "OPEN"
            common.touch(jo)

    # Candidate release.
    recompute.maybe_release_candidate(placement["candidate_id"])

    # Client exposure recompute (this placement no longer ACTIVE).
    if client_id is not None:
        recompute.recompute_open_exposure(client_id)


@bp.route("/staffing/placements", methods=["POST"])
def create_placement():
    _, role = get_user_context()
    require_role(role, {"Recruiter"})
    body = get_json_body()

    submission_id = common.require_str(body, "submission_id")
    start_date = common.require_str(body, "start_date")
    end_date = common.require_str(body, "end_date")
    expected_version = common.require_int(body, "expected_job_order_version")
    standard_weekly_hours = common.optional_int(body, "standard_weekly_hours", 40)
    predecessor_placement_id = common.optional_str(body, "predecessor_placement_id", None)

    # Priority 3 existence (before priority-4 range checks): submission FK,
    # then optional predecessor FK, validated left-to-right.
    sub = common.get_or_404(db.submissions, submission_id, errors.ERR_SUBMISSION_NOT_FOUND)
    if predecessor_placement_id is not None:
        common.get_or_404(db.placements, predecessor_placement_id, errors.ERR_PLACEMENT_NOT_FOUND)

    # Priority 4 structural checks.
    start_dt = common._parse_dt(start_date)
    end_dt = common._parse_dt(end_date)
    if not (end_dt > start_dt):
        raise ApiError(errors.ERR_VALIDATION, 422, "end_date must be after start_date.")
    if standard_weekly_hours < 1:
        raise ApiError(errors.ERR_VALIDATION, 422, "standard_weekly_hours must be >= 1.")

    jo = db.job_orders.get(sub["job_order_id"])
    cand = db.candidates.get(sub["candidate_id"])
    client = db.clients.get(jo["client_id"]) if jo else None

    # Precondition order (PRD 3.4):
    # 1) submission OFFER_EXTENDED
    if sub["status"] != "OFFER_EXTENDED":
        raise ApiError(errors.ERR_SUBMISSION_NOT_OFFER_EXTENDED, 409, "Submission is not OFFER_EXTENDED.")
    # 2) job order OPEN
    if jo is None or jo["status"] != "OPEN":
        raise ApiError(errors.ERR_JOB_ORDER_NOT_OPEN, 409, "Job order is not OPEN.")
    # 3) candidate not INACTIVE
    if cand is None or cand["status"] == "INACTIVE":
        raise ApiError(errors.ERR_CANDIDATE_INACTIVE, 409, "Candidate is INACTIVE.")
    # 4) date-range overlap vs candidate's ACTIVE/PENDING_START placements (closed interval)
    for p in db.placements.values():
        if p["candidate_id"] == cand["id"] and p["assignment_status"] in ("ACTIVE", "PENDING_START"):
            p_s = common._parse_dt(p["start_date"])
            p_e = common._parse_dt(p["end_date"])
            if _ranges_overlap_closed(start_dt, end_dt, p_s, p_e):
                raise ApiError(errors.ERR_PLACEMENT_DATE_OVERLAP, 409, "Placement dates overlap.")
    # 5) remaining openings (filled_count < openings)
    if jo["filled_count"] >= jo["openings"]:
        raise ApiError(errors.ERR_NO_OPENINGS_REMAINING, 409, "No openings remaining.")
    # 6) OCC: expected_job_order_version == jo.version
    if expected_version != jo["version"]:
        raise ApiError(errors.ERR_STALE_JOB_ORDER_VERSION, 412, "Stale job order version.")
    # 7) credit gate
    placement_type = jo["employment_type"]
    bill_rate_cents = jo["bill_rate_cents"]
    pay_rate_cents = sub["submitted_pay_rate_cents"]
    proj_bill = calc.projected_weekly_bill(bill_rate_cents, standard_weekly_hours, placement_type)
    proj_margin = calc.projected_weekly_margin(bill_rate_cents, pay_rate_cents, standard_weekly_hours, placement_type)
    if client is not None:
        projected = client["open_exposure_cents"] + proj_bill + client["outstanding_balance_cents"]
        if projected > client["credit_limit_cents"]:
            raise ApiError(errors.ERR_CREDIT_LIMIT_EXCEEDED, 402, "Credit limit exceeded.")

    # --- all preconditions pass: create placement + cascade ---
    is_direct = placement_type == "DIRECT"
    assignment_status = "ENDED" if is_direct else "PENDING_START"

    rec = common.init_mutable({
        "submission_id": sub["id"],
        "job_order_id": sub["job_order_id"],
        "candidate_id": sub["candidate_id"],
        "client_id": jo["client_id"],  # internal: drives client exposure rollups
        "predecessor_placement_id": predecessor_placement_id,
        "placement_type": placement_type,
        "bill_rate_cents": bill_rate_cents,
        "pay_rate_cents": pay_rate_cents,
        "standard_weekly_hours": standard_weekly_hours,
        "start_date": start_date,
        "end_date": end_date,
        "projected_weekly_bill_cents": proj_bill,
        "projected_weekly_margin_cents": proj_margin,
        "actual_margin_cents": 0,
        "assignment_status": assignment_status,
        "conversion_status": "NONE",
    })
    db.placements[rec["id"]] = rec

    # Side effect: submission OFFER_EXTENDED -> PLACED.
    sub["status"] = "PLACED"
    common.touch(sub)

    # Side effect: candidate AVAILABLE -> ON_ASSIGNMENT (only if AVAILABLE).
    if cand["status"] == "AVAILABLE":
        cand["status"] = "ON_ASSIGNMENT"
        common.touch(cand)

    # Side effect: fill cascade on the job order (PRD 3.4). The order's
    # filled_count is increased by one and its version incremented by one. A
    # placement occupies its seat from creation (PENDING_START), and even a
    # DIRECT placement — born ENDED — consumes a seat at create time per the
    # prose's unconditional "increased by one". If this brings filled_count to
    # equal openings, the order goes OPEN -> FILLED and sweeps still-open
    # submissions to REJECTED with reason ORDER_FILLED.
    jo["filled_count"] = jo["filled_count"] + 1
    common.touch(jo)
    if jo["status"] == "OPEN" and jo["filled_count"] == jo["openings"]:
        jo["status"] = "FILLED"
        common.touch(jo)
        recompute.cascade_reject_open_submissions(jo["id"], "ORDER_FILLED")

    # Side effect: DIRECT placement bills an immediate conversion fee.
    if is_direct:
        weeks_worked = 0
        fee_cents = calc.conversion_fee(
            jo["annual_salary_cents"], client["conversion_fee_pct"] if client else 0,
            "DIRECT", weeks_worked,
        )
        fee = common.init_mutable({
            "placement_id": rec["id"],
            "client_id": jo["client_id"],
            "annual_salary_cents": jo["annual_salary_cents"],
            "fee_cents": fee_cents,
            "status": "BILLED",
        })
        db.conversion_fees[fee["id"]] = fee

    # Side effect: client open_exposure recomputed.
    if client is not None:
        recompute.recompute_open_exposure(client["id"])

    return object_response(serialize.placement(rec), 201)


@bp.route("/staffing/placements", methods=["GET"])
def list_placements():
    user_id, role = get_user_context()
    require_role(role, {"AccountManager", "Recruiter", "Client", "Candidate"})
    limit, offset = parse_pagination()

    rows = list(db.placements.values())
    for key, field in (
        ("job_order_id", "job_order_id"),
        ("candidate_id", "candidate_id"),
        ("submission_id", "submission_id"),
        ("predecessor_placement_id", "predecessor_placement_id"),
        ("assignment_status", "assignment_status"),
    ):
        val = request.args.get(key)
        if val is not None:
            rows = [r for r in rows if r.get(field) == val]

    if role == "Client":
        rows = [r for r in rows if ownership.placement_client(r) == user_id]
    elif role == "Candidate":
        rows = [r for r in rows if r["candidate_id"] == user_id]

    page, total = paginate(rows, limit, offset)
    return array_response([serialize.placement(r) for r in page], limit, offset, total)


@bp.route("/staffing/placements/<pid>", methods=["GET"])
def get_placement(pid):
    user_id, role = get_user_context()
    require_role(role, {"AccountManager", "Recruiter", "Client", "Candidate"})
    rec = common.get_or_404(db.placements, pid, errors.ERR_PLACEMENT_NOT_FOUND)
    if role == "Client":
        ownership.client_owns(user_id, ownership.placement_client(rec))
    elif role == "Candidate":
        ownership.candidate_owns_placement(user_id, rec)
    return object_response(serialize.placement(rec), 200)


@bp.route("/staffing/placements/<pid>/timesheets", methods=["GET"])
def list_placement_timesheets(pid):
    user_id, role = get_user_context()
    require_role(role, {"AccountManager", "Recruiter", "Client", "Candidate"})
    rec = common.get_or_404(db.placements, pid, errors.ERR_PLACEMENT_NOT_FOUND)
    if role == "Client":
        ownership.client_owns(user_id, ownership.placement_client(rec))
    elif role == "Candidate":
        ownership.candidate_owns_placement(user_id, rec)
    limit, offset = parse_pagination()

    rows = [ts for ts in db.timesheets.values() if ts["placement_id"] == rec["id"]]
    page, total = paginate(rows, limit, offset)
    return array_response([serialize.timesheet(r) for r in page], limit, offset, total)


@bp.route("/staffing/placements/<pid>", methods=["PATCH"])
def patch_placement(pid):
    _, role = get_user_context()
    require_role(role, {"Recruiter"})
    rec = common.get_or_404(db.placements, pid, errors.ERR_PLACEMENT_NOT_FOUND)
    body = get_json_body()
    target = common.require_enum(body, "target_assignment_status", {"ACTIVE", "ENDED"})

    client_id = rec.get("client_id")

    if target == "ACTIVE":
        # PENDING_START -> ACTIVE; only TEMP / TEMP_TO_PERM (DIRECT born ENDED).
        if rec["assignment_status"] != "PENDING_START":
            raise ApiError(errors.ERR_PLACEMENT_NOT_PENDING_START, 409, "Placement is not PENDING_START.")
        rec["assignment_status"] = "ACTIVE"
        common.touch(rec)
        # PRD 3.5: starting the engagement recomputes the client's
        # open_exposure_cents (this placement's projected_weekly_bill now
        # counts toward active exposure). filled_count is unchanged on start —
        # the seat was already consumed at placement create.
        if client_id is not None:
            recompute.recompute_open_exposure(client_id)

    elif target == "ENDED":
        if rec["assignment_status"] != "ACTIVE":
            raise ApiError(errors.ERR_PLACEMENT_NOT_ACTIVE, 409, "Placement is not ACTIVE.")
        rec["assignment_status"] = "ENDED"
        common.touch(rec)
        _end_assignment_side_effects(rec)

    return object_response(serialize.placement(rec), 200)


@bp.route("/staffing/placements/<pid>/convert", methods=["POST"])
def convert_placement(pid):
    _, role = get_user_context()
    require_role(role, {"AccountManager"})
    rec = common.get_or_404(db.placements, pid, errors.ERR_PLACEMENT_NOT_FOUND)
    body = get_json_body()
    annual_salary_cents = common.require_int(body, "annual_salary_cents")
    waive = common.optional_bool(body, "waive", False)

    # Preconditions (PRD 3.7):
    if rec["placement_type"] != "TEMP_TO_PERM":
        raise ApiError(errors.ERR_PLACEMENT_NOT_CONVERTIBLE, 409, "Placement is not TEMP_TO_PERM.")
    if rec["conversion_status"] != "NONE":
        raise ApiError(errors.ERR_PLACEMENT_ALREADY_CONVERTED, 409, "Placement already converted.")
    if rec["assignment_status"] != "ACTIVE":
        raise ApiError(errors.ERR_PLACEMENT_NOT_ACTIVE, 409, "Placement is not ACTIVE.")

    jo = db.job_orders.get(rec["job_order_id"])
    client = db.clients.get(rec.get("client_id"))

    # weeks_worked = count of APPROVED/INVOICED timesheets on this placement.
    weeks_worked = sum(
        1 for ts in db.timesheets.values()
        if ts["placement_id"] == rec["id"] and ts["status"] in ("APPROVED", "INVOICED")
    )
    fee_cents = calc.conversion_fee(
        annual_salary_cents,
        client["conversion_fee_pct"] if client else 0,
        "TEMP_TO_PERM",
        weeks_worked,
    )

    # Side effect 1: ConversionFee created (BILLED, or WAIVED if waive=true).
    fee = common.init_mutable({
        "placement_id": rec["id"],
        "client_id": rec.get("client_id"),
        "annual_salary_cents": annual_salary_cents,
        "fee_cents": fee_cents,
        "status": "WAIVED" if waive else "BILLED",
    })
    db.conversion_fees[fee["id"]] = fee

    # Side effect 2: conversion_status NONE -> CONVERTED.
    rec["conversion_status"] = "CONVERTED"
    common.touch(rec)

    # Side effect 3: assignment ACTIVE -> ENDED with the standard end effects.
    rec["assignment_status"] = "ENDED"
    common.touch(rec)
    _end_assignment_side_effects(rec)

    return object_response(serialize.placement(rec), 200)
