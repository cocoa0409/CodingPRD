"""Volunteer and BackgroundCheck endpoints (PRD §3.1, §3.2)."""
from flask import Blueprint

import calc
import clock
import db
import domain
import serialize
import store
from errors import err
from middleware import require
from response import array_response, object_response
from store import create, get_or_404, paginate, sort_key, touch
import validate as V

bp = Blueprint("volunteers", __name__)

GENDERS = {"MALE", "FEMALE", "NONBINARY"}
CHECK_TYPES = ["CRIMINAL", "DMV", "CHILD_ABUSE_REGISTRY"]


# --- Volunteer ---
@bp.route("/volunteers", methods=["POST"])
@require("Coordinator", "MatchSpecialist")
def create_volunteer():
    body = V.get_body()
    full_name = V.require_str(body, "full_name")
    email = V.require_str(body, "email")
    gender = V.require_enum(body, "gender", GENDERS)
    home_zip = V.require_zip(body, "home_zip")
    interest_tags = V.require_string_array(body, "interest_tags")
    max_weekly_hours = V.require_int(body, "max_weekly_hours", minimum=1)
    rec = create(
        {
            "full_name": full_name,
            "email": email,
            "gender": gender,
            "home_zip": home_zip,
            "interest_tags": interest_tags,
            "max_weekly_hours": max_weekly_hours,
            "status": "APPLIED",
            "active_match_count": 0,
            "cleared_check_id": None,
        },
        db.volunteers,
        "Volunteer",
    )
    return object_response(serialize.volunteer(rec), 201)


@bp.route("/volunteers/<vid>", methods=["GET"])
@require("Coordinator", "MatchSpecialist", "BackgroundScreener", "Supervisor")
def get_volunteer(vid):
    rec = get_or_404(db.volunteers, vid, "Volunteer")
    return object_response(serialize.volunteer(rec))


@bp.route("/volunteers", methods=["GET"])
@require("Coordinator", "MatchSpecialist", "BackgroundScreener", "Supervisor")
def list_volunteers():
    from flask import request

    limit, offset = V.parse_pagination(request.args)
    status = request.args.get("status")
    items = list(db.volunteers.values())
    if status is not None:
        items = [r for r in items if r["status"] == status]
    window, total = paginate(items, limit, offset)
    return array_response([serialize.volunteer(r) for r in window], limit, offset, total)


@bp.route("/volunteers/<vid>/submit-screening", methods=["POST"])
@require("BackgroundScreener")
def submit_screening(vid):
    rec = get_or_404(db.volunteers, vid, "Volunteer")
    # State precondition: APPLIED (initial) or ELIGIBLE (re-screen).
    if rec["status"] not in ("APPLIED", "ELIGIBLE"):
        err("ERR_INVALID_STATE", "Volunteer must be APPLIED or ELIGIBLE to submit screening")
    if rec["status"] == "ELIGIBLE":
        # Re-screen requires no active match.
        domain.recompute_volunteer_active_match_count(rec)
        if rec["active_match_count"] != 0:
            err("ERR_INVALID_STATE", "Cannot re-screen a volunteer with an active match")
    now = clock.now()
    for ct in CHECK_TYPES:
        create(
            {
                "volunteer_id": rec["id"],
                "check_type": ct,
                "submitted_at": now,
                "valid_until": None,
                "adjudicated_at": None,
                "adverse_findings": 0,
                "status": "PENDING",
            },
            db.background_checks,
            "BackgroundCheck",
        )
    rec["status"] = "SCREENING"
    rec["cleared_check_id"] = None
    touch(rec)
    return object_response(serialize.volunteer(rec))


@bp.route("/volunteers/<vid>/deactivate", methods=["POST"])
@require("MatchSpecialist")
def deactivate_volunteer(vid):
    rec = get_or_404(db.volunteers, vid, "Volunteer")
    if rec["status"] != "ELIGIBLE":
        err("ERR_INVALID_STATE", "Only an ELIGIBLE volunteer may be deactivated")
    domain.recompute_volunteer_active_match_count(rec)
    if rec["active_match_count"] != 0:
        err("ERR_INVALID_STATE", "Cannot deactivate a volunteer with an active match")
    rec["status"] = "INACTIVE"
    touch(rec)
    return object_response(serialize.volunteer(rec))


@bp.route("/volunteers/<vid>/background-checks", methods=["GET"])
@require("Coordinator", "MatchSpecialist", "BackgroundScreener", "Supervisor")
def list_volunteer_checks(vid):
    get_or_404(db.volunteers, vid, "Volunteer")
    items = domain.checks_for_volunteer(vid)
    # Reverse-reachability lists carry no pagination params in the endpoint table;
    # emit all rows ordered by created_at.
    ordered = sorted(items, key=sort_key)
    return array_response(
        [serialize.background_check(r) for r in ordered], 10, 0, len(ordered)
    )


# --- BackgroundCheck ---
@bp.route("/background-checks/<cid>", methods=["GET"])
@require("Coordinator", "BackgroundScreener", "MatchSpecialist", "Supervisor")
def get_check(cid):
    rec = get_or_404(db.background_checks, cid, "BackgroundCheck")
    return object_response(serialize.background_check(rec))


@bp.route("/background-checks/<cid>/adjudicate", methods=["POST"])
@require("BackgroundScreener")
def adjudicate_check(cid):
    rec = get_or_404(db.background_checks, cid, "BackgroundCheck")
    body = V.get_body()
    decision = V.require_enum(body, "decision", {"CLEAR", "FLAG"})
    adverse_findings = V.require_int(body, "adverse_findings", minimum=0)
    # State precondition.
    if rec["status"] != "PENDING":
        err("ERR_INVALID_STATE", "Only a PENDING check may be adjudicated")
    now = clock.now()
    volunteer = db.volunteers.get(rec["volunteer_id"])
    if decision == "CLEAR":
        tolerance = calc.DMV_ADVERSE_TOLERANCE if rec["check_type"] == "DMV" else 0
        if adverse_findings > tolerance:
            err(
                "ERR_ADVERSE_FINDING_BLOCKS_CLEAR",
                "adverse_findings %d exceed tolerance %d for %s"
                % (adverse_findings, tolerance, rec["check_type"]),
            )
        rec["adverse_findings"] = adverse_findings
        rec["status"] = "CLEARED"
        rec["adjudicated_at"] = now
        from util import add_months

        rec["valid_until"] = add_months(now, calc.VALIDITY_MONTHS)
        touch(rec)
        if volunteer is not None:
            domain.on_check_cleared(volunteer)
    else:  # FLAG
        rec["adverse_findings"] = adverse_findings
        rec["status"] = "FLAGGED"
        rec["adjudicated_at"] = now
        rec["valid_until"] = None
        touch(rec)
        if volunteer is not None:
            domain.on_check_flagged(volunteer)
    return object_response(serialize.background_check(rec))
