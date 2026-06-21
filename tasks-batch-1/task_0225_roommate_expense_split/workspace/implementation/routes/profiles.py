"""RoommateProfile endpoints (PRD §3.1). POST is unauthenticated; GETs allow all roles."""
from flask import Blueprint, request

import models
import response
import validate
from db import db
from errors import err
from middleware import authenticate, require_roles, parse_pagination, paginate

bp = Blueprint("profiles", __name__)

ALL_ROLES = {"Roommate", "DisputeMediator", "PlatformOperator"}
SLEEP = {"EARLY_BIRD", "NIGHT_OWL", "FLEXIBLE"}


def _email_taken(email):
    low = email.strip().lower()
    for p in db.roommate_profiles.values():
        if p["email"].strip().lower() == low:
            return True
    return False


@bp.route("/roommate-profiles", methods=["POST"])
def create_profile():
    with db.lock:
        # Registration is open: unauthenticated allowed (PRD §2.1).
        body = validate.get_json_body()
        email = validate.require_str(body, "email")
        full_name = validate.require_str(body, "full_name")
        income = validate.require_int(body, "monthly_income_cents", minimum=0)
        cleanliness = validate.require_int(body, "cleanliness", minimum=1, maximum=5)
        sleep = validate.require_enum(body, "sleep_schedule", SLEEP)
        smoker = validate.optional_bool(body, "smoker", False)
        pets = validate.optional_bool(body, "pets", False)
        if _email_taken(email):
            raise err("ERR_EMAIL_TAKEN", "A profile with this email already exists.")
        prof = {
            "email": email,
            "full_name": full_name,
            "monthly_income_cents": income,
            "cleanliness": cleanliness,
            "sleep_schedule": sleep,
            "smoker": smoker,
            "pets": pets,
            "net_balance_cents": 0,
        }
        models.stamp_create(prof)
        db.roommate_profiles[prof["id"]] = prof
        return response.ok(models.serialize(prof), 201)


@bp.route("/roommate-profiles/<pid>", methods=["GET"])
def get_profile(pid):
    with db.lock:
        p = authenticate()
        require_roles(p, ALL_ROLES)
        prof = db.roommate_profiles.get(pid)
        if not prof:
            raise err("ERR_NOT_FOUND", "Profile not found.")
        return response.ok(models.serialize(prof))


@bp.route("/roommate-profiles", methods=["GET"])
def list_profiles():
    with db.lock:
        p = authenticate()
        require_roles(p, ALL_ROLES)
        limit, offset = parse_pagination()
        items = models.sort_by_created(list(db.roommate_profiles.values()))
        page, meta = paginate(items, limit, offset)
        return response.ok_list(models.serialize_list(page), pagination=meta)


@bp.route("/roommate-profiles/<pid>/bill-splits", methods=["GET"])
def list_profile_bill_splits(pid):
    with db.lock:
        p = authenticate()
        require_roles(p, ALL_ROLES)
        if pid not in db.roommate_profiles:
            raise err("ERR_NOT_FOUND", "Profile not found.")
        limit, offset = parse_pagination()
        items = [s for s in db.bill_splits.values() if s["profile_id"] == pid]
        items = models.sort_by_created(items)
        page, meta = paginate(items, limit, offset)
        return response.ok_list(models.serialize_list(page), pagination=meta)


@bp.route("/roommate-profiles/<pid>/expense-shares", methods=["GET"])
def list_profile_expense_shares(pid):
    with db.lock:
        p = authenticate()
        require_roles(p, ALL_ROLES)
        if pid not in db.roommate_profiles:
            raise err("ERR_NOT_FOUND", "Profile not found.")
        limit, offset = parse_pagination()
        items = [s for s in db.expense_shares.values() if s["profile_id"] == pid]
        items = models.sort_by_created(items)
        page, meta = paginate(items, limit, offset)
        return response.ok_list(models.serialize_list(page), pagination=meta)
