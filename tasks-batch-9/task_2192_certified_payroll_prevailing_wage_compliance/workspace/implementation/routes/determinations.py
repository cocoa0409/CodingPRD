"""Wage determinations and their rate schedules."""

from flask import Blueprint, request

import db
import derive
import engine
import serializers as s
import validators as v
from auth import ALL_ROLES, authenticate
from errors import ApiError
from response import created, ok, paginated, pagination

bp = Blueprint("determinations", __name__)

ZONES = ("BASE", "ZONE1", "ZONE2")


def get_determination(determination_id):
    return v.lookup(db.wage_determinations, determination_id, "ERR_DETERMINATION_NOT_FOUND")


@bp.route("/wage-determinations", methods=["POST"])
def create_determination():
    authenticate(["PortalAdmin"])
    payload = v.body()
    decision_number = v.req_string(payload, "decision_number", min_len=1)
    modification_number = v.opt_int(payload, "modification_number", default=0, minimum=0)
    locality_code = v.req_string(payload, "locality_code", min_len=4, max_len=24, upper=True)
    effective_date = v.req_instant(payload, "effective_date")
    expiry_date = v.opt_instant(payload, "expiry_date")
    if expiry_date is not None and expiry_date <= effective_date:
        v.bad("expiry_date must fall strictly after effective_date.")

    v.unique_or_reject(
        db.wage_determinations,
        lambda r: r["decision_number"] == decision_number
        and r["modification_number"] == modification_number,
        "decision_number and modification_number must be unique together.",
    )

    row = db.base_row()
    row.update(
        {
            "decision_number": decision_number,
            "modification_number": modification_number,
            "locality_code": locality_code,
            "effective_date": effective_date,
            "expiry_date": expiry_date,
            "status": "DRAFT",
            "superseded_by_id": None,
            "rate_count": 0,
        }
    )
    db.wage_determinations[row["id"]] = row
    return created(s.determination(row))


@bp.route("/wage-determinations", methods=["GET"])
def list_determinations():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    locality = request.args.get("locality_code")
    status = request.args.get("status")
    successor = request.args.get("superseded_by_id")

    def keep(row):
        if locality is not None and row["locality_code"] != locality:
            return False
        if status is not None and row["status"] != status:
            return False
        if successor is not None and row["superseded_by_id"] != successor:
            return False
        return True

    return paginated(db.ordered(db.wage_determinations, keep), s.determination, limit, offset)


@bp.route("/wage-determinations/<determination_id>", methods=["GET"])
def read_determination(determination_id):
    authenticate(ALL_ROLES)
    return ok(s.determination(get_determination(determination_id)))


@bp.route("/wage-determinations/<determination_id>/wage-rates", methods=["POST"])
def create_wage_rate(determination_id):
    authenticate(["PortalAdmin"])
    determination = get_determination(determination_id)
    payload = v.body()
    classification_code = v.req_string(payload, "classification_code", min_len=1, upper=True)
    trade_code = v.req_string(payload, "trade_code", min_len=2, max_len=12, upper=True)
    zone_code = v.opt_enum(payload, "zone_code", ZONES, default="BASE")
    base_hourly_rate_cents = v.req_int(payload, "base_hourly_rate_cents", minimum=1)
    fringe_hourly_rate_cents = v.req_int(payload, "fringe_hourly_rate_cents", minimum=0)
    zone_adjustment_cents = v.opt_int(payload, "zone_adjustment_cents", default=0, minimum=0)
    scale = v.req_int_array(
        payload, "apprentice_scale_pct", 1, 8, 30, 100, non_decreasing=True
    )

    if determination["status"] != "DRAFT":
        raise ApiError(
            "ERR_INVALID_DETERMINATION_STATE",
            "Rate rows may only be attached to a DRAFT determination.",
        )

    v.unique_or_reject(
        db.wage_rates,
        lambda r: r["wage_determination_id"] == determination["id"]
        and r["classification_code"] == classification_code
        and r["zone_code"] == zone_code,
        "classification_code and zone_code must be unique within the determination.",
    )

    row = db.base_row(versioned=False)
    row.update(
        {
            "wage_determination_id": determination["id"],
            "classification_code": classification_code,
            "trade_code": trade_code,
            "zone_code": zone_code,
            "base_hourly_rate_cents": base_hourly_rate_cents,
            "fringe_hourly_rate_cents": fringe_hourly_rate_cents,
            "zone_adjustment_cents": zone_adjustment_cents,
            "apprentice_scale_pct": scale,
        }
    )
    db.wage_rates[row["id"]] = row
    determination["rate_count"] = determination["rate_count"] + 1
    db.touch(determination)
    return created(s.wage_rate(row))


@bp.route("/wage-determinations/<determination_id>/wage-rates", methods=["GET"])
def list_wage_rates(determination_id):
    authenticate(ALL_ROLES)
    determination = get_determination(determination_id)
    limit, offset = pagination()
    classification = request.args.get("classification_code")
    zone = request.args.get("zone_code")

    def keep(row):
        if row["wage_determination_id"] != determination["id"]:
            return False
        if classification is not None and row["classification_code"] != classification:
            return False
        if zone is not None and row["zone_code"] != zone:
            return False
        return True

    return paginated(db.ordered(db.wage_rates, keep), s.wage_rate, limit, offset)


def _intersects(a_start, a_end, b_start, b_end):
    """Half-open [start, end) intersection; None end means +infinity."""
    if a_end is not None and b_start >= a_end:
        return False
    if b_end is not None and a_start >= b_end:
        return False
    return True


@bp.route("/wage-determinations/<determination_id>/activate", methods=["POST"])
def activate_determination(determination_id):
    authenticate(["PortalAdmin"])
    determination = get_determination(determination_id)
    payload = v.body()
    predecessor = v.resolve_fk(
        payload, "supersedes_determination_id", db.wage_determinations, "ERR_DETERMINATION_NOT_FOUND"
    )

    # Rung 8 -- state legality
    if determination["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_DETERMINATION_STATE", "Only a DRAFT determination may be activated.")
    if determination["rate_count"] < 1:
        raise ApiError(
            "ERR_INVALID_DETERMINATION_STATE",
            "A determination with no rate rows cannot be activated.",
        )
    if predecessor is not None:
        if (
            predecessor["status"] != "ACTIVE"
            or predecessor["locality_code"] != determination["locality_code"]
            or predecessor["effective_date"] >= determination["effective_date"]
        ):
            raise ApiError(
                "ERR_INVALID_DETERMINATION_STATE",
                "The named predecessor is not an ACTIVE, same-locality, strictly earlier determination.",
            )

    # Rung 25 -- governing period occupation on the locality
    for other in db.ordered(db.wage_determinations):
        if other["id"] == determination["id"]:
            continue
        if other["locality_code"] != determination["locality_code"]:
            continue
        if other["status"] not in ("ACTIVE", "SUPERSEDED"):
            continue
        if predecessor is not None and other["id"] == predecessor["id"]:
            continue
        if _intersects(
            determination["effective_date"],
            determination["expiry_date"],
            other["effective_date"],
            other["expiry_date"],
        ):
            raise ApiError(
                "ERR_DETERMINATION_PERIOD_OVERLAP",
                "The governing period intersects another determination in this locality.",
            )

    determination["status"] = "ACTIVE"
    db.touch(determination)

    if predecessor is not None:
        _supersede(predecessor, determination)

    return ok(s.determination(determination))


def _supersede(predecessor, successor):
    """Hop 1: ACTIVE -> SUPERSEDED. Hop 2: re-point AWARDED projects.
    Hop 3: redo the wage arithmetic on their unfiled payrolls."""
    predecessor["status"] = "SUPERSEDED"
    predecessor["superseded_by_id"] = successor["id"]
    predecessor["expiry_date"] = successor["effective_date"]
    db.touch(predecessor)

    for project in db.ordered(db.projects):
        if project["wage_determination_id"] != predecessor["id"]:
            continue
        if project["status"] != "AWARDED":
            continue
        project["wage_determination_id"] = successor["id"]
        db.touch(project)
        for submission in derive.submissions_of_project(project["id"]):
            if submission["workflow_status"] in ("DRAFT", "PENDING_CERTIFICATION"):
                engine.recompute_after_supersede(submission, project)
