"""LadderCriterion endpoints."""

from flask import Blueprint, request

from clock import clock
from db import db
from errors import (err_criterion_window_overlap, err_differential_monotonicity,
                    err_invalid_request, err_not_found)
from middleware import require_roles
from response import success_list, success_object, parse_pagination
from serializers import criterion_view
from util import parse_datetime, require_fields, require_int, require_enum

bp = Blueprint("criteria", __name__)

CRITERION_LEVELS = {"CN_II", "CN_III", "CN_IV"}
CERT_TRACKS = {"NONE", "BASIC", "SPECIALTY", "ADVANCED"}


def _windows_overlap(a_from, a_until, b_from, b_until):
    """Half-open interval overlap; adjacency (a.until == b.from) is NOT overlap."""
    a_end = a_until  # None = infinity
    b_end = b_until
    if a_end is not None and a_end <= b_from:
        return False
    if b_end is not None and b_end <= a_from:
        return False
    return True


@bp.route("/clinical-ladder/ladder-criteria", methods=["POST"])
def create_criterion():
    require_roles("ProgramAdmin")
    payload = request.get_json(silent=True)
    require_fields(payload, ["target_level", "min_portfolio_score", "min_participation_points",
                             "required_certification_track", "differential_monthly_cents",
                             "effective_from"])
    target_level = require_enum(payload, "target_level", CRITERION_LEVELS)
    min_portfolio_score = require_int(payload, "min_portfolio_score")
    min_participation_points = require_int(payload, "min_participation_points")
    required_track = require_enum(payload, "required_certification_track", CERT_TRACKS)
    differential = require_int(payload, "differential_monthly_cents")
    effective_from = parse_datetime(payload.get("effective_from"), "effective_from")
    effective_until_raw = payload.get("effective_until")
    effective_until = None
    if effective_until_raw is not None:
        effective_until = parse_datetime(effective_until_raw, "effective_until")

    if not (1 <= min_portfolio_score <= 400):
        raise err_invalid_request("min_portfolio_score must be between 1 and 400")
    if not (0 <= min_participation_points <= 200):
        raise err_invalid_request("min_participation_points must be between 0 and 200")
    if differential < 0:
        raise err_invalid_request("differential_monthly_cents must be >= 0")
    if effective_until is not None and effective_until <= effective_from:
        raise err_invalid_request("effective_until must be strictly greater than effective_from")

    # Business rule 1: window overlap for same target_level (half-open; adjacency ok)
    for c in db.ladder_criteria.values():
        if c["target_level"] != target_level:
            continue
        if _windows_overlap(effective_from, effective_until, c["effective_from"], c["effective_until"]):
            raise err_criterion_window_overlap()

    # Business rule 2: differential monotonicity across simultaneously-active sets
    now = clock.now()
    active = {c["target_level"]: c["differential_monthly_cents"]
              for c in db.ladder_criteria.values()
              if c["effective_from"] <= now and (c["effective_until"] is None or now < c["effective_until"])}
    active[target_level] = differential
    if "CN_III" in active and "CN_II" in active and not active["CN_III"] > active["CN_II"]:
        raise err_differential_monotonicity()
    if "CN_IV" in active and "CN_III" in active and not active["CN_IV"] > active["CN_III"]:
        raise err_differential_monotonicity()

    criterion = {
        "id": db.new_id(),
        "target_level": target_level,
        "min_portfolio_score": min_portfolio_score,
        "min_participation_points": min_participation_points,
        "required_certification_track": required_track,
        "differential_monthly_cents": differential,
        "effective_from": effective_from,
        "effective_until": effective_until,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.ladder_criteria[criterion["id"]] = criterion
    return success_object(criterion_view(criterion), status=201)


@bp.route("/clinical-ladder/ladder-criteria", methods=["GET"])
def list_criteria():
    require_roles("ProgramAdmin", "Nurse")
    limit, offset = parse_pagination(request.args)
    target_level = request.args.get("target_level")
    rows = sorted(db.ladder_criteria.values(), key=lambda c: c["created_at"])
    if target_level is not None:
        rows = [c for c in rows if c["target_level"] == target_level]
    total = len(rows)
    page = rows[offset:offset + limit]
    return success_list([criterion_view(c) for c in page], limit, offset, total)


@bp.route("/clinical-ladder/ladder-criteria/<cid>", methods=["GET"])
def get_criterion(cid):
    require_roles("ProgramAdmin", "Nurse")
    criterion = db.ladder_criteria.get(cid)
    if criterion is None:
        raise err_not_found("LadderCriterion not found")
    return success_object(criterion_view(criterion))
