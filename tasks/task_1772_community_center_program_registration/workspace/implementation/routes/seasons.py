"""Season endpoints (PRD 3.1)."""
from flask import Blueprint

import clock
import services
import store
from auth import ALL_ROLES, authenticate, authorize
from errors import raise_err
from util import (
    body_json,
    bump,
    check_int_range,
    get_or_404,
    new_record,
    opt_int,
    req_datetime,
    req_str,
    serialize,
    success_object,
)

bp = Blueprint("seasons", __name__)

FIELDS = [
    "id",
    "name",
    "start_date",
    "end_date",
    "resident_opens_at",
    "general_opens_at",
    "registration_closes_at",
    "family_discount_threshold",
    "family_discount_pct",
    "scholarship_budget_cents",
    "scholarship_committed_cents",
    "status",
    "created_at",
    "updated_at",
    "version",
]


def season_out(rec):
    return serialize(rec, FIELDS)


@bp.route("/seasons", methods=["POST"])
def create_season():
    _, role = authenticate()
    authorize(role, ["ProgramCoordinator"])
    body = body_json()
    name = req_str(body, "name")
    start_date = req_datetime(body, "start_date")
    end_date = req_datetime(body, "end_date")
    resident_opens_at = req_datetime(body, "resident_opens_at")
    general_opens_at = req_datetime(body, "general_opens_at")
    registration_closes_at = req_datetime(body, "registration_closes_at")
    threshold = opt_int(body, "family_discount_threshold", 3)
    pct = opt_int(body, "family_discount_pct", 10)
    budget = opt_int(body, "scholarship_budget_cents", 0)
    if end_date <= start_date:
        raise_err("ERR_INVALID_REQUEST", "end_date must be later than start_date")
    if not (resident_opens_at <= general_opens_at <= registration_closes_at):
        raise_err(
            "ERR_INVALID_REQUEST",
            "resident_opens_at <= general_opens_at <= registration_closes_at is required",
        )
    check_int_range(threshold, 2, None, "family_discount_threshold")
    check_int_range(pct, 0, 100, "family_discount_pct")
    check_int_range(budget, 0, None, "scholarship_budget_cents")
    rec = new_record()
    rec.update(
        name=name,
        start_date=start_date,
        end_date=end_date,
        resident_opens_at=resident_opens_at,
        general_opens_at=general_opens_at,
        registration_closes_at=registration_closes_at,
        family_discount_threshold=threshold,
        family_discount_pct=pct,
        scholarship_budget_cents=budget,
        scholarship_committed_cents=0,
        status="DRAFT",
    )
    store.seasons[rec["id"]] = rec
    return success_object(season_out(rec), 201)


@bp.route("/seasons/<season_id>", methods=["GET"])
def get_season(season_id):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    rec = get_or_404(store.seasons, season_id, "Season")
    return success_object(season_out(rec), 200)


@bp.route("/seasons/<season_id>/publish", methods=["POST"])
def publish_season(season_id):
    _, role = authenticate()
    authorize(role, ["ProgramCoordinator"])
    rec = get_or_404(store.seasons, season_id, "Season")
    if rec["status"] != "DRAFT":
        raise_err("ERR_INVALID_STATE", "Only a DRAFT season can be published")
    rec["status"] = "PUBLISHED"
    bump(rec)
    return success_object(season_out(rec), 200)


@bp.route("/seasons/<season_id>/close", methods=["POST"])
def close_season(season_id):
    _, role = authenticate()
    authorize(role, ["ProgramCoordinator"])
    rec = get_or_404(store.seasons, season_id, "Season")
    if rec["status"] != "PUBLISHED":
        raise_err("ERR_INVALID_STATE", "Only a PUBLISHED season can be closed")
    if clock.now() < rec["registration_closes_at"]:
        raise_err("ERR_INVALID_STATE", "Season cannot be closed before registration_closes_at")
    rec["status"] = "CLOSED"
    bump(rec)
    return success_object(season_out(rec), 200)


@bp.route("/seasons/<season_id>/sweeps", methods=["POST"])
def sweep_season(season_id):
    _, role = authenticate()
    authorize(role, ["ProgramCoordinator"])
    rec = get_or_404(store.seasons, season_id, "Season")
    summary = services.run_sweep(rec)
    return success_object(summary, 200)
