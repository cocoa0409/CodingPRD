"""Throughput reports: PROVISIONAL / FINAL scoring, publication and retraction."""

from flask import Blueprint

from constants import ALL_ROLES, REPORT_STATES, REPORT_VARIANTS
from db import base_row, db, touch
from errors import fail
from middleware import authenticate, get_report, get_restaurant, require_not_frozen
from response import ok
from routes.helpers import list_rows
from serialize import throughput_report as report_json
from services import reports as report_service
from validation import body_or_400, opt_str, q_enum, q_str, req_dt, req_enum, req_int, req_str

bp = Blueprint("reports", __name__)


def _store_of(report):
    return db.restaurants.get(report["restaurant_id"])


@bp.route("/throughput-reports", methods=["POST"])
def create_report():
    authenticate(("MarketCoach",))
    body = body_or_400()

    restaurant_id = req_str(body, "restaurant_id")
    window_start_at = req_dt(body, "window_start_at")
    window_end_at = req_dt(body, "window_end_at")
    variant = req_enum(body, "variant", REPORT_VARIANTS)
    expected_version = req_int(body, "expected_restaurant_version", minimum=0)
    supersedes_report_id = opt_str(body, "supersedes_report_id")

    restaurant = get_restaurant(restaurant_id)
    predecessor = None
    if supersedes_report_id is not None:
        predecessor = get_report(supersedes_report_id)
        if predecessor["restaurant_id"] != restaurant_id:
            fail("ERR_RESTAURANT_MISMATCH", "the superseded report belongs to another store")

    if expected_version != restaurant["version"]:
        fail("ERR_STALE_RESTAURANT_VERSION",
             "expected_restaurant_version %s does not match the store's current version %s"
             % (expected_version, restaurant["version"]))

    require_not_frozen(restaurant)

    if window_end_at <= window_start_at:
        fail("ERR_WINDOW_BOUNDS_INVALID", "window_end_at must be after window_start_at")
    if window_end_at > db.clock:
        fail("ERR_REPORT_WINDOW_FUTURE", "window_end_at may not reach into the future")

    metrics = report_service.compute(restaurant, window_start_at, window_end_at, variant)

    row = base_row()
    row.update({
        "restaurant_id": restaurant_id,
        "supersedes_report_id": supersedes_report_id,
        "window_start_at": window_start_at,
        "window_end_at": window_end_at,
        "variant": variant,
        "report_state": "DRAFT",
        "retraction_reason": None,
    })
    row.update(metrics)
    db.throughput_reports[row["id"]] = row

    touch(restaurant)
    return ok(report_json(row), 201)


@bp.route("/throughput-reports/<report_id>/publish", methods=["POST"])
def publish_report(report_id):
    authenticate(("MarketCoach",))
    report = get_report(report_id)
    restaurant = _store_of(report)
    require_not_frozen(restaurant)

    if report["report_state"] != "DRAFT":
        fail("ERR_INVALID_REPORT_STATE",
             "publication requires report_state DRAFT, found %s" % report["report_state"])

    if report["cars_served"] < 1:
        fail("ERR_REPORT_WINDOW_EMPTY", "an empty window may not be published")

    report["report_state"] = "PUBLISHED"
    touch(report)

    predecessor_id = report["supersedes_report_id"]
    if predecessor_id is not None:
        predecessor = db.throughput_reports.get(predecessor_id)
        if predecessor is not None and predecessor["report_state"] == "PUBLISHED":
            predecessor["report_state"] = "SUPERSEDED"
            touch(predecessor)

    return ok(report_json(report))


@bp.route("/throughput-reports/<report_id>/retract", methods=["POST"])
def retract_report(report_id):
    authenticate(("MarketCoach",))
    report = get_report(report_id)
    body = body_or_400()
    reason = req_str(body, "retraction_reason")

    require_not_frozen(_store_of(report))

    if report["report_state"] not in ("DRAFT", "PUBLISHED"):
        fail("ERR_INVALID_REPORT_STATE",
             "retraction requires report_state DRAFT or PUBLISHED, found %s"
             % report["report_state"])

    report["report_state"] = "RETRACTED"
    report["retraction_reason"] = reason
    touch(report)
    return ok(report_json(report))


@bp.route("/throughput-reports", methods=["GET"])
def list_reports():
    authenticate(ALL_ROLES)
    return list_rows(db.throughput_reports, report_json, (
        ("restaurant_id", q_str("restaurant_id")),
        ("supersedes_report_id", q_str("supersedes_report_id")),
        ("variant", q_enum("variant", REPORT_VARIANTS)),
        ("report_state", q_enum("report_state", REPORT_STATES)),
    ))


@bp.route("/throughput-reports/<report_id>", methods=["GET"])
def read_report(report_id):
    authenticate(ALL_ROLES)
    return ok(report_json(get_report(report_id)))
