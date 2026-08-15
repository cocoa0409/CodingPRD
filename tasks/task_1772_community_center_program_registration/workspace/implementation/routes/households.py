"""Household endpoints (PRD 3.4)."""
from flask import Blueprint

import store
from auth import authenticate, authorize
from util import body_json, bump, get_or_404, new_record, req_enum, req_str, serialize, success_object

bp = Blueprint("households", __name__)

FIELDS = [
    "id",
    "account_name",
    "residency_status",
    "account_credit_cents",
    "created_at",
    "updated_at",
    "version",
]

READ_ROLES = ["HouseholdManager", "FrontDeskStaff", "ProgramCoordinator", "FinanceOfficer"]


def household_out(rec):
    return serialize(rec, FIELDS)


@bp.route("/households", methods=["POST"])
def create_household():
    # Self-service: the server-minted id becomes the caller's X-User-ID.
    _, role = authenticate()
    authorize(role, ["HouseholdManager"])
    body = body_json()
    account_name = req_str(body, "account_name")
    rec = new_record()
    rec.update(account_name=account_name, residency_status="PENDING", account_credit_cents=0)
    store.households[rec["id"]] = rec
    return success_object(household_out(rec), 201)


@bp.route("/households/<household_id>", methods=["GET"])
def get_household(household_id):
    _, role = authenticate()
    authorize(role, READ_ROLES)
    rec = get_or_404(store.households, household_id, "Household")
    return success_object(household_out(rec), 200)


@bp.route("/households/<household_id>/verify-residency", methods=["POST"])
def verify_residency(household_id):
    _, role = authenticate()
    authorize(role, ["FrontDeskStaff"])
    body = body_json()
    residency_status = req_enum(body, "residency_status", ["RESIDENT", "NONRESIDENT"])
    rec = get_or_404(store.households, household_id, "Household")
    # Re-verification is allowed in both directions; existing registrations
    # keep their pinned fee basis (PRD 3.4).
    rec["residency_status"] = residency_status
    bump(rec)
    return success_object(household_out(rec), 200)
