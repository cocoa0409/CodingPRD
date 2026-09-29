"""Coaching interventions: scoring, the cyclic contest loop and dual-coach closure."""

from flask import Blueprint

from constants import ALL_ROLES, CI_MAX_REVISIONS, CI_STATES, FOCUS_SEGMENTS
from db import base_row, db, touch
from errors import fail
from middleware import (
    authenticate,
    get_coaching,
    get_report,
    get_staff,
    require_not_frozen,
    scope,
)
from response import ok
from routes.helpers import list_rows
from serialize import coaching_intervention as coaching_json
from services import coaching as coaching_service
from validation import body_or_400, q_enum, q_str, req_enum, req_str

bp = Blueprint("coaching", __name__)


def _store_of(row):
    return db.restaurants.get(row["restaurant_id"])


@bp.route("/coaching-interventions", methods=["POST"])
def create_coaching():
    authenticate(("MarketCoach",))
    body = body_or_400()

    throughput_report_id = req_str(body, "throughput_report_id")
    staff_member_id = req_str(body, "staff_member_id")
    focus_segment = req_enum(body, "focus_segment", FOCUS_SEGMENTS)

    report = get_report(throughput_report_id)
    coachee = get_staff(staff_member_id)

    if report["restaurant_id"] != coachee["restaurant_id"]:
        fail("ERR_RESTAURANT_MISMATCH", "the report and the coachee belong to different stores")

    require_not_frozen(db.restaurants.get(report["restaurant_id"]))

    if report["report_state"] != "PUBLISHED":
        fail("ERR_REPORT_NOT_PUBLISHED",
             "the referenced report is %s, not PUBLISHED" % report["report_state"])

    gap, value, tier = coaching_service.score(report, focus_segment)

    row = base_row()
    row.update({
        "restaurant_id": report["restaurant_id"],
        "throughput_report_id": throughput_report_id,
        "staff_member_id": staff_member_id,
        "issued_by_user_id": None,
        "focus_segment": focus_segment,
        "segment_gap_seconds": gap,
        "priority_score": value,
        "tier": tier,
        "revision_count": 0,
        "contest_reason": None,
        "closure_note": None,
        "ci_state": "DRAFT",
    })
    db.coaching_interventions[row["id"]] = row
    return ok(coaching_json(row), 201)


@bp.route("/coaching-interventions/<coaching_id>/issue", methods=["POST"])
def issue_coaching(coaching_id):
    actor = authenticate(("MarketCoach",))
    coaching = get_coaching(coaching_id)
    require_not_frozen(_store_of(coaching))

    if coaching["ci_state"] != "DRAFT":
        fail("ERR_INVALID_COACHING_STATE",
             "issue requires ci_state DRAFT, found %s" % coaching["ci_state"])

    report = db.throughput_reports.get(coaching["throughput_report_id"])
    if report is None or report["report_state"] != "PUBLISHED":
        fail("ERR_REPORT_NOT_PUBLISHED", "the referenced report is no longer PUBLISHED")

    gap, value, tier = coaching_service.score(report, coaching["focus_segment"])

    coaching["ci_state"] = "ISSUED"
    coaching["issued_by_user_id"] = actor.user_id
    coaching["segment_gap_seconds"] = gap
    coaching["priority_score"] = value
    coaching["tier"] = tier
    touch(coaching)
    return ok(coaching_json(coaching))


@bp.route("/coaching-interventions/<coaching_id>/acknowledge", methods=["POST"])
def acknowledge_coaching(coaching_id):
    actor = authenticate(("ShiftLeader",))
    coaching = get_coaching(coaching_id)
    scope(actor, coaching["restaurant_id"], staff_fk=coaching["staff_member_id"])
    require_not_frozen(_store_of(coaching))

    if coaching["ci_state"] != "ISSUED":
        fail("ERR_INVALID_COACHING_STATE",
             "acknowledgement requires ci_state ISSUED, found %s" % coaching["ci_state"])

    coaching["ci_state"] = "ACKNOWLEDGED"
    touch(coaching)
    return ok(coaching_json(coaching))


@bp.route("/coaching-interventions/<coaching_id>/contest", methods=["POST"])
def contest_coaching(coaching_id):
    actor = authenticate(("ShiftLeader",))
    coaching = get_coaching(coaching_id)
    scope(actor, coaching["restaurant_id"], staff_fk=coaching["staff_member_id"])
    body = body_or_400()
    reason = req_str(body, "contest_reason")

    require_not_frozen(_store_of(coaching))

    if coaching["ci_state"] != "ISSUED":
        fail("ERR_INVALID_COACHING_STATE",
             "contest requires ci_state ISSUED, found %s" % coaching["ci_state"])

    if coaching["revision_count"] > CI_MAX_REVISIONS - 1:
        fail("ERR_COACHING_REVISION_LIMIT",
             "an intervention may go round the revision loop at most %s times"
             % CI_MAX_REVISIONS)

    # ISSUED -> CONTESTED -> DRAFT completes inside this single request.
    coaching["contest_reason"] = reason
    coaching["revision_count"] = coaching["revision_count"] + 1
    coaching["ci_state"] = "DRAFT"
    touch(coaching)
    return ok(coaching_json(coaching))


@bp.route("/coaching-interventions/<coaching_id>/close", methods=["POST"])
def close_coaching(coaching_id):
    actor = authenticate(("MarketCoach",))
    coaching = get_coaching(coaching_id)
    body = body_or_400()
    note = req_str(body, "closure_note")

    require_not_frozen(_store_of(coaching))

    if coaching["ci_state"] != "ACKNOWLEDGED":
        fail("ERR_INVALID_COACHING_STATE",
             "closure requires ci_state ACKNOWLEDGED, found %s" % coaching["ci_state"])

    if actor.user_id == coaching["issued_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "the issuing coach may not close their own intervention")

    coaching["ci_state"] = "CLOSED"
    coaching["closure_note"] = note
    touch(coaching)
    return ok(coaching_json(coaching))


@bp.route("/coaching-interventions", methods=["GET"])
def list_coachings():
    authenticate(ALL_ROLES)
    return list_rows(db.coaching_interventions, coaching_json, (
        ("restaurant_id", q_str("restaurant_id")),
        ("throughput_report_id", q_str("throughput_report_id")),
        ("staff_member_id", q_str("staff_member_id")),
        ("ci_state", q_enum("ci_state", CI_STATES)),
    ))


@bp.route("/coaching-interventions/<coaching_id>", methods=["GET"])
def read_coaching(coaching_id):
    authenticate(ALL_ROLES)
    return ok(coaching_json(get_coaching(coaching_id)))
