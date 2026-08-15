from datetime import timedelta

from flask import Blueprint

import db
import errors
import serializers
import services
from middleware import ALL_ROLES, require_roles
from response import ok_list, ok_object
from util import (get_body, paginate, parse_dt, require_enum, require_fields)

bp = Blueprint("applications", __name__)

COORD = "MedicalStaffCoordinator"
CHAIR = "CredentialsCommitteeChair"

APP_KINDS = ("INITIAL", "REAPPOINTMENT")


@bp.route("/mso/applications", methods=["POST"])
@require_roles(COORD)
def create_application():
    body = get_body()
    # Rung 3: existence of body FKs (when present).
    member_id = body.get("member_id")
    member = None
    if member_id is not None:
        member = db.members.get(member_id)
        if member is None:
            errors.raise_err(errors.ERR_NOT_FOUND,
                             "MedicalStaffMember not found")
    supersedes = None
    supersedes_id = body.get("supersedes_application_id")
    if supersedes_id is not None:
        supersedes = db.applications.get(supersedes_id)
        if supersedes is None:
            errors.raise_err(errors.ERR_NOT_FOUND,
                             "supersedes_application_id does not exist")
    # Rung 4: OCC on the member's version.
    if member is not None and "expected_member_version" in body \
            and body["expected_member_version"] is not None:
        if body["expected_member_version"] != member["version"]:
            errors.raise_err(errors.ERR_STALE_VERSION,
                             "expected_member_version does not match the "
                             "member's current version")
    # Rung 10: cross-reference coherence — superseded application must
    # belong to the same member.
    if supersedes is not None and member is not None \
            and supersedes["member_id"] != member["id"]:
        errors.raise_err(errors.ERR_PRIVILEGE_LINE_UNKNOWN,
                         "supersedes_application_id must reference an "
                         "application of the same member")
    # Rung 11: input shape.
    require_fields(body, ["member_id", "application_kind",
                          "expected_member_version"])
    require_enum(body, "application_kind", APP_KINDS)
    if not isinstance(body["member_id"], str):
        errors.raise_err(errors.ERR_INVALID_REQUEST,
                         "member_id must be a string")
    if not isinstance(body["expected_member_version"], int) \
            or isinstance(body["expected_member_version"], bool):
        errors.raise_err(errors.ERR_INVALID_REQUEST,
                         "expected_member_version must be an integer")
    if supersedes_id is not None and not isinstance(supersedes_id, str):
        errors.raise_err(errors.ERR_INVALID_REQUEST,
                         "supersedes_application_id must be a string")

    rec = services.base_record()
    rec.update({
        "member_id": member_id,
        "application_kind": body["application_kind"],
        "application_status": "DRAFT",
        "submitted_at": None,
        "verification_complete_count": 0,
        "verification_required_count": 0,
        "supersedes_application_id": supersedes_id,
        "decision_reason": None,
    })
    db.applications[rec["id"]] = rec
    # Side effect: supersede marker — the member's version advances.
    services.touch(member)
    return ok_object(serializers.application(rec), 201)


@bp.route("/mso/applications", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_applications():
    items, limit, offset, total = paginate(
        db.applications.values(), serializers.application,
        ["member_id", "application_status", "application_kind",
         "supersedes_application_id"])
    return ok_list(items, limit, offset, total)


@bp.route("/mso/applications/<aid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_application(aid):
    rec = db.applications.get(aid)
    if rec is None:
        errors.raise_err(errors.ERR_NOT_FOUND,
                         "AppointmentApplication not found")
    return ok_object(serializers.application(rec))


@bp.route("/mso/applications/<aid>/submit", methods=["POST"])
@require_roles(COORD)
def submit_application(aid):
    get_body()
    app = db.applications.get(aid)
    if app is None:
        errors.raise_err(errors.ERR_NOT_FOUND,
                         "AppointmentApplication not found")
    # Rung 5: state.
    if app["application_status"] != "DRAFT":
        errors.raise_err(errors.ERR_APPLICATION_NOT_IN_DRAFT,
                         "Application is not in DRAFT")
    member = db.members.get(app["member_id"])
    # Rung 8: temporal — reappointment window [term_end-180d, term_end).
    if app["application_kind"] == "REAPPOINTMENT":
        term_end_raw = member.get("current_term_end") if member else None
        in_window = False
        if term_end_raw:
            term_end = parse_dt(term_end_raw)
            window_open = term_end - timedelta(
                days=services.REAPPOINTMENT_WINDOW_DAYS)
            now = db.clock_now()
            in_window = window_open <= now < term_end
        if not in_window:
            errors.raise_err(
                errors.ERR_OUTSIDE_REAPPOINTMENT_WINDOW,
                "Reappointment submission is outside the window "
                "[current_term_end - 180d, current_term_end)")
    # Rung 9: structural — verification items must exist.
    items = services.app_items(app["id"])
    if not items:
        errors.raise_err(errors.ERR_NO_VERIFICATION_ITEMS,
                         "At least one verification item is required")
    # Rung 9 (business): pending-application guard for INITIAL.
    if app["application_kind"] == "INITIAL":
        for other in db.applications.values():
            if (other["member_id"] == app["member_id"]
                    and other["id"] != app["id"]
                    and other["application_status"]
                    in services.IN_FLIGHT_APP_STATES
                    and other["id"] != app.get("supersedes_application_id")):
                errors.raise_err(
                    errors.ERR_PENDING_APPLICATION_EXISTS,
                    "Another application is already in flight for the member")
    # Transition.
    now_iso = services.now_iso()
    app["application_status"] = "SUBMITTED"
    app["submitted_at"] = now_iso
    services.touch(app)
    for item in items:
        if item["item_status"] == "PENDING":
            item["item_status"] = "REQUESTED"
            item["requested_at"] = now_iso
            services.touch(item)
    services.recompute_verification_counts(app)
    if member is not None:
        services.touch(member)
    return ok_object(serializers.application(app))


@bp.route("/mso/applications/<aid>/advance-to-committee", methods=["POST"])
@require_roles(CHAIR)
def advance_to_committee(aid):
    get_body()
    app = db.applications.get(aid)
    if app is None:
        errors.raise_err(errors.ERR_NOT_FOUND,
                         "AppointmentApplication not found")
    if app["application_status"] != "PSV_COMPLETE":
        errors.raise_err(errors.ERR_PSV_NOT_COMPLETE,
                         "Application has not reached PSV_COMPLETE")
    for d in db.delineations.values():
        if (d["application_id"] == aid
                and d["delineation_status"] not in
                ("CRITERIA_MET", "CRITERIA_UNMET")):
            errors.raise_err(errors.ERR_DELINEATIONS_UNEVALUATED,
                             "Every delineation must be evaluated first")
    app["application_status"] = "COMMITTEE_REVIEW"
    services.touch(app)
    services.create_agenda_item_for_application(app)
    return ok_object(serializers.application(app))


@bp.route("/mso/applications/<aid>/withdraw", methods=["POST"])
@require_roles(COORD)
def withdraw_application(aid):
    get_body()
    app = db.applications.get(aid)
    if app is None:
        errors.raise_err(errors.ERR_NOT_FOUND,
                         "AppointmentApplication not found")
    if app["application_status"] not in ("DRAFT", "SUBMITTED",
                                         "PSV_IN_PROGRESS"):
        errors.raise_err(errors.ERR_APPLICATION_NOT_WITHDRAWABLE,
                         "Application cannot be withdrawn from its state")
    app["application_status"] = "WITHDRAWN"
    services.touch(app)
    for item in services.app_items(aid):
        if item["item_status"] in ("PENDING", "REQUESTED", "RECEIVED",
                                   "DISCREPANCY"):
            item["item_status"] = "WAIVED"
            item["waiver_justification"] = "application withdrawn"
            services.touch(item)
    services.recompute_verification_counts(app)
    return ok_object(serializers.application(app))
