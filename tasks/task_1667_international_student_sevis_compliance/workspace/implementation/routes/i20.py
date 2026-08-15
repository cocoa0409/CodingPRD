"""I-20 forms and travel endorsements (PRD §3.2, §3.6)."""

from flask import Blueprint, request

import db
import services
from db import add_months, clock_date, new_id, parse_date, stamp_new, touch
from errors import (
    ERR_ENDORSEMENT_WINDOW_OVERLAP,
    ERR_I20_NOT_DRAFT,
    ERR_I20_NOT_ISSUED,
    ERR_INSUFFICIENT_VERIFIED_FUNDING,
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
    ERR_RECORD_NOT_ACTIVE,
    ERR_RESOURCE_NOT_OWNED,
    ERR_STALE_VERSION,
    raise_error,
)
from helpers import (
    body, get_or_404, get_student_or_404, list_response, occ_token, opt_date,
    opt_str, req_date, req_int, req_str,
)
from middleware import ALL_ROLES, STAFF_ROLES, require_roles
from response import success_object
from serializers import i20_form_out, travel_endorsement_out

bp = Blueprint("i20", __name__)


# ---------------------------------------------------------------------------
# I-20 forms
# ---------------------------------------------------------------------------

@bp.route("/sevis/students/<sid>/i20-forms", methods=["POST"])
def create_i20_form(sid):
    require_roles(STAFF_ROLES)
    student = get_student_or_404(sid)
    data = body()
    sevis_record_id = req_str(data, "sevis_record_id")
    program_name = req_str(data, "program_name")
    program_start_date = opt_date(data, "program_start_date")
    program_end_date = opt_date(data, "program_end_date")
    tuition = req_int(data, "tuition_cents", min_value=0)
    living = req_int(data, "living_cents", min_value=0)
    insurance = req_int(data, "insurance_cents", min_value=0)
    other = req_int(data, "other_cents", min_value=0)
    supersedes_id = opt_str(data, "supersedes_i20_form_id")

    record = db.sevis_records.get(sevis_record_id)
    if record is None or record["student_id"] != student["id"]:
        raise_error(ERR_NOT_FOUND, "SevisRecord not found for this student")
    if supersedes_id is not None:
        prior = db.i20_forms.get(supersedes_id)
        if prior is None or prior["student_id"] != student["id"]:
            raise_error(ERR_NOT_FOUND, "supersedes_i20_form_id does not name a known I-20 form")

    form = {
        "id": new_id(),
        "student_id": student["id"],
        "sevis_record_id": record["id"],
        "program_name": program_name,
        "program_start_date": program_start_date or record["program_start_date"],
        "program_end_date": program_end_date or record["program_end_date"],
        "tuition_cents": tuition,
        "living_cents": living,
        "insurance_cents": insurance,
        "other_cents": other,
        "verified_funding_cents": 0,
        "provisional_funding_cents": 0,
        "supersedes_i20_form_id": supersedes_id,
        "status": "DRAFT",
    }
    stamp_new(form)
    db.i20_forms[form["id"]] = form
    return success_object(i20_form_out(form), 201)


@bp.route("/sevis/i20-forms", methods=["GET"])
def list_i20_forms():
    user_id, role = require_roles(ALL_ROLES)
    student_filter = request.args.get("student_id")
    if role == "Student":
        if student_filter is not None and student_filter != user_id:
            raise_error(ERR_RESOURCE_NOT_OWNED, "Students may only list their own resources")
        student_filter = user_id
    filters = {
        "student_id": student_filter,
        "sevis_record_id": request.args.get("sevis_record_id"),
        "supersedes_i20_form_id": request.args.get("supersedes_i20_form_id"),
        "status": request.args.get("status"),
    }
    return list_response(list(db.i20_forms.values()), i20_form_out, filters)


@bp.route("/sevis/i20-forms/<fid>", methods=["GET"])
def get_i20_form(fid):
    user_id, role = require_roles(ALL_ROLES)
    form = get_or_404(db.i20_forms, fid, "I20Form")
    if role == "Student" and form["student_id"] != user_id:
        raise_error(ERR_RESOURCE_NOT_OWNED, "Students may only read their own resources")
    return success_object(i20_form_out(form), 200)


@bp.route("/sevis/i20-forms/<fid>/issue", methods=["POST"])
def issue_i20_form(fid):
    require_roles(STAFF_ROLES)
    form = get_or_404(db.i20_forms, fid, "I20Form")
    # State precondition (priority 5).
    if form["status"] != "DRAFT":
        raise_error(ERR_I20_NOT_DRAFT, "I-20 must be DRAFT to issue")
    # Structural preconditions (priority 6): parent record state, then the
    # supersede source must currently be ISSUED (PRD §3.2 order).
    record = db.sevis_records.get(form["sevis_record_id"])
    if record is None or record["status"] not in ("DRAFT", "INITIAL", "ACTIVE"):
        raise_error(ERR_RECORD_NOT_ACTIVE, "Record must be DRAFT, INITIAL, or ACTIVE to issue")
    prior = None
    if form["supersedes_i20_form_id"] is not None:
        prior = db.i20_forms.get(form["supersedes_i20_form_id"])
        if prior is None or prior["status"] != "ISSUED":
            raise_error(ERR_I20_NOT_ISSUED, "The form named in supersedes_i20_form_id must be ISSUED")
    # Funding gate (priority 9): verified fresh funding covers the total.
    verified, provisional = services.funding_cents(form["student_id"])
    estimated = (
        form["tuition_cents"] + form["living_cents"]
        + form["insurance_cents"] + form["other_cents"]
    )
    if verified < estimated:
        raise_error(
            ERR_INSUFFICIENT_VERIFIED_FUNDING,
            "Verified fresh funding does not cover estimated_total_cents",
        )
    form["verified_funding_cents"] = verified
    form["provisional_funding_cents"] = provisional
    form["status"] = "ISSUED"
    touch(form)
    if prior is not None:
        services.supersede_form(prior)
    return success_object(i20_form_out(form), 200)


# ---------------------------------------------------------------------------
# Travel endorsements (PRD §3.6): OCC on I20Form.version; closed-interval
# window overlap; issuance reprints the form (version + 1).
# ---------------------------------------------------------------------------

@bp.route("/sevis/i20-forms/<fid>/travel-endorsements", methods=["POST"])
def create_travel_endorsement(fid):
    require_roles(STAFF_ROLES)
    form = get_or_404(db.i20_forms, fid, "I20Form")
    data = body()
    expected_version = occ_token(data, "expected_i20_form_version")
    departure = req_date(data, "travel_departure_date")
    return_date = req_date(data, "travel_return_date")
    if parse_date(return_date) < parse_date(departure):
        raise_error(ERR_INVALID_REQUEST, "travel_return_date must be on or after travel_departure_date")
    # OCC runs before any business validation (PRD §2.8).
    if expected_version != form["version"]:
        raise_error(ERR_STALE_VERSION, "expected_i20_form_version does not match the form's current version")
    if form["status"] != "ISSUED":
        raise_error(ERR_I20_NOT_ISSUED, "Travel endorsements require an ISSUED I-20")
    dep_d = parse_date(departure)
    ret_d = parse_date(return_date)
    for existing in services.endorsements_of_form(form["id"]):
        if existing["status"] != "ACTIVE":
            continue
        ex_dep = parse_date(existing["travel_departure_date"])
        ex_ret = parse_date(existing["travel_return_date"])
        # Closed-interval semantics: any intersection, including touching
        # endpoints, counts as overlap.
        if dep_d <= ex_ret and ex_dep <= ret_d:
            raise_error(
                ERR_ENDORSEMENT_WINDOW_OVERLAP,
                "Travel window intersects an existing ACTIVE endorsement window",
            )
    months = services.endorsement_valid_months(form["student_id"])
    endorsement = {
        "id": new_id(),
        "i20_form_id": form["id"],
        "travel_departure_date": departure,
        "travel_return_date": return_date,
        "valid_until": add_months(clock_date(), months).isoformat(),
        "status": "ACTIVE",
    }
    stamp_new(endorsement)
    db.travel_endorsements[endorsement["id"]] = endorsement
    # Issuance is a reprint of the form (PRD §3.6).
    touch(form)
    return success_object(travel_endorsement_out(endorsement), 201)


@bp.route("/sevis/i20-forms/<fid>/travel-endorsements", methods=["GET"])
def list_travel_endorsements(fid):
    user_id, role = require_roles(ALL_ROLES)
    form = get_or_404(db.i20_forms, fid, "I20Form")
    if role == "Student" and form["student_id"] != user_id:
        raise_error(ERR_RESOURCE_NOT_OWNED, "Students may only read their own resources")
    items = services.endorsements_of_form(form["id"])
    return list_response(items, travel_endorsement_out)
