"""Family + Guardian + Child routes."""

from datetime import timedelta

from flask import Blueprint, request

from clock import clock, parse_iso_date
from config import (
    CHILD_NAME_MAX,
    CHILD_NAME_MIN,
    GUARDIAN_NAME_MAX,
    GUARDIAN_NAME_MIN,
    GUARDIAN_RELATIONSHIPS,
    HOUSEHOLD_NAME_MAX,
    HOUSEHOLD_NAME_MIN,
    PHONE_MAX,
    PHONE_MIN,
    RESIDENCY_STATUSES,
    ROLE_GUARDIAN,
    ROLE_PROGRAM_ADMIN,
)
from db import db, init_common_fields, touch
from errors import APIError
from middleware import get_json_body, require_auth
from response import empty_response, list_response, success_response
from services.lookups import (
    acting_guardian_family_id,
    assert_family_scope,
    get_family,
)
from services.pagination import paginate, parse_pagination
from services.projection import (
    project_child_auth_statuses,
    recount_emergency_contacts,
)
from services.serializers import (
    serialize_child,
    serialize_enrollment,
    serialize_family,
    serialize_guardian,
)
from services.validators import (
    optional_bool,
    optional_enum,
    optional_string,
    require_enum,
    require_int,
    require_string,
)


family_bp = Blueprint("family", __name__)


# ---------- Families ----------

@family_bp.route("/families", methods=["POST"])
@require_auth({ROLE_PROGRAM_ADMIN})
def create_family():
    body = get_json_body()
    household_name = require_string(body, "household_name", min_len=HOUSEHOLD_NAME_MIN, max_len=HOUSEHOLD_NAME_MAX)
    primary_email = require_string(body, "primary_email", min_len=1)
    residency = optional_enum(body, "residency_status", RESIDENCY_STATUSES, default="STANDARD")
    email_lc = primary_email.strip().lower()
    if not email_lc:
        raise APIError("ERR_VALIDATION", "primary_email must be non-empty.")
    if email_lc in db.family_emails:
        raise APIError("ERR_VALIDATION", "primary_email already exists.")
    fam = init_common_fields({
        "household_name": household_name,
        "primary_email": email_lc,
        "residency_status": residency,
        "archived": False,
    })
    db.families[fam["id"]] = fam
    db.family_emails[email_lc] = fam["id"]
    return success_response(serialize_family(fam), status=201)


@family_bp.route("/families/<family_id>", methods=["GET"])
@require_auth({ROLE_PROGRAM_ADMIN, ROLE_GUARDIAN})
def read_family(family_id):
    fam = get_family(family_id)
    assert_family_scope(fam["id"])
    return success_response(serialize_family(fam))


@family_bp.route("/families/<family_id>", methods=["PATCH"])
@require_auth({ROLE_PROGRAM_ADMIN})
def patch_family(family_id):
    fam = get_family(family_id)
    body = get_json_body()
    # OCC: if version supplied, must match
    if "version" in body and body["version"] is not None:
        if not isinstance(body["version"], int) or isinstance(body["version"], bool):
            raise APIError("ERR_VALIDATION", "version must be an integer.")
        if body["version"] != fam["version"]:
            raise APIError("ERR_STALE_VERSION")

    if "household_name" in body and body["household_name"] is not None:
        fam["household_name"] = require_string(
            body, "household_name", min_len=HOUSEHOLD_NAME_MIN, max_len=HOUSEHOLD_NAME_MAX
        )

    if "primary_email" in body and body["primary_email"] is not None:
        new_email = require_string(body, "primary_email", min_len=1).strip().lower()
        if not new_email:
            raise APIError("ERR_VALIDATION", "primary_email must be non-empty.")
        if new_email != fam["primary_email"]:
            if new_email in db.family_emails:
                raise APIError("ERR_VALIDATION", "primary_email already exists.")
            old = fam["primary_email"]
            if old in db.family_emails:
                del db.family_emails[old]
            db.family_emails[new_email] = fam["id"]
            fam["primary_email"] = new_email

    if "residency_status" in body and body["residency_status"] is not None:
        fam["residency_status"] = require_enum(body, "residency_status", RESIDENCY_STATUSES)

    touch(fam)
    return success_response(serialize_family(fam))


@family_bp.route("/families/<family_id>", methods=["DELETE"])
@require_auth({ROLE_PROGRAM_ADMIN})
def delete_family(family_id):
    fam = get_family(family_id)
    # ERR_FAMILY_HAS_FUTURE_ENROLLMENTS: any CONFIRMED enrollment in this family
    # in a future/current week (week_start + 7*week_index > now).
    from datetime import datetime, timezone, time as dtime
    now = clock.now()
    for e in db.enrollments.values():
        if e["status"] != "CONFIRMED":
            continue
        child = db.children.get(e["child_id"])
        if not child or child["family_id"] != family_id:
            continue
        session = db.sessions.get(e["session_id"])
        if not session:
            continue
        ws = parse_iso_date(session["week_start"])
        cmp_dt = datetime.combine(
            ws + timedelta(days=7 * e["week_index"] + 7),
            dtime.min,
            tzinfo=timezone.utc,
        )
        if cmp_dt > now:
            raise APIError("ERR_FAMILY_HAS_FUTURE_ENROLLMENTS")
    fam["archived"] = True
    # Remove from email uniqueness index (archived families don't compete).
    if fam["primary_email"] in db.family_emails:
        del db.family_emails[fam["primary_email"]]
    touch(fam)
    return empty_response()


@family_bp.route("/families/<family_id>/invoice", methods=["GET"])
@require_auth({ROLE_PROGRAM_ADMIN, ROLE_GUARDIAN})
def family_invoice(family_id):
    fam = get_family(family_id)
    assert_family_scope(fam["id"])
    week_start_raw = request.args.get("week_start")
    if not week_start_raw:
        raise APIError("ERR_VALIDATION", "week_start query parameter is required.")
    target_week_start = parse_iso_date(week_start_raw)
    # Iterate CONFIRMED enrollments for this family whose session-week aligns
    line_items = []
    total = 0
    for e in db.enrollments.values():
        if e["status"] != "CONFIRMED":
            continue
        child = db.children.get(e["child_id"])
        if not child or child["family_id"] != family_id:
            continue
        session = db.sessions.get(e["session_id"])
        if not session:
            continue
        ws = parse_iso_date(session["week_start"])
        if ws + timedelta(days=7 * e["week_index"]) == target_week_start:
            line_items.append(serialize_enrollment(e))
            total += e["final_fee_cents"]
    return success_response({
        "family_id": family_id,
        "week_start": target_week_start.isoformat(),
        "invoice_total_cents": total,
        "line_items": line_items,
    })


# ---------- Guardians ----------

@family_bp.route("/families/<family_id>/guardians", methods=["POST"])
@require_auth({ROLE_PROGRAM_ADMIN, ROLE_GUARDIAN})
def create_guardian(family_id):
    fam = get_family(family_id)
    assert_family_scope(fam["id"])
    body = get_json_body()
    full_name = require_string(body, "full_name", min_len=GUARDIAN_NAME_MIN, max_len=GUARDIAN_NAME_MAX)
    phone = require_string(body, "phone", min_len=PHONE_MIN, max_len=PHONE_MAX)
    relationship = require_enum(body, "relationship", GUARDIAN_RELATIONSHIPS)
    is_primary = optional_bool(body, "is_primary", default=False)
    # Demote existing primary if needed
    if is_primary:
        for g in db.guardians.values():
            if g["family_id"] == family_id and g.get("is_primary"):
                g["is_primary"] = False
                touch(g)
    row = init_common_fields({
        "family_id": family_id,
        "full_name": full_name,
        "phone": phone,
        "relationship": relationship,
        "is_primary": is_primary,
    })
    db.guardians[row["id"]] = row
    return success_response(serialize_guardian(row), status=201)


@family_bp.route("/families/<family_id>/guardians", methods=["GET"])
@require_auth({ROLE_PROGRAM_ADMIN, ROLE_GUARDIAN})
def list_guardians(family_id):
    fam = get_family(family_id)
    assert_family_scope(fam["id"])
    limit, offset = parse_pagination()
    rows = [g for g in db.guardians.values() if g["family_id"] == family_id]
    window, total = paginate(rows, limit, offset)
    return list_response([serialize_guardian(g) for g in window], total, limit, offset)


# ---------- Children ----------

@family_bp.route("/families/<family_id>/children", methods=["POST"])
@require_auth({ROLE_PROGRAM_ADMIN, ROLE_GUARDIAN})
def create_child(family_id):
    fam = get_family(family_id)
    assert_family_scope(fam["id"])
    body = get_json_body()
    full_name = require_string(body, "full_name", min_len=CHILD_NAME_MIN, max_len=CHILD_NAME_MAX)
    dob_str = require_string(body, "date_of_birth", min_len=10, max_len=10)
    dob = parse_iso_date(dob_str)
    # must be in the past relative to current clock
    today = clock.now().date()
    if dob >= today:
        raise APIError("ERR_VALIDATION", "date_of_birth must be in the past.")
    child = init_common_fields({
        "family_id": family_id,
        "full_name": full_name,
        "date_of_birth": dob.isoformat(),
        "medical_authorization_status": "NONE",
        "pickup_authorization_status": "NONE",
        "emergency_contact_count": 0,
    })
    db.children[child["id"]] = child
    return success_response(serialize_child(child), status=201)


@family_bp.route("/children/<child_id>", methods=["GET"])
@require_auth({ROLE_PROGRAM_ADMIN, ROLE_GUARDIAN})
def read_child(child_id):
    child = db.children.get(child_id)
    if not child:
        raise APIError("ERR_RESOURCE_NOT_FOUND", f"Child {child_id} not found.")
    assert_family_scope(child["family_id"])
    project_child_auth_statuses(child, persist=True)
    recount_emergency_contacts(child)
    return success_response(serialize_child(child))
