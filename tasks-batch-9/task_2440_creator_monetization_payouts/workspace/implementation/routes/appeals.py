"""Appeals: the cyclic state machine and the restoration cascade (PRD 3.4)."""
from flask import Blueprint, request

import calc
import rescore
import serialize
from apierrors import fail
from envelope import created, ok
from fields import F
from gate import endpoint
from listutil import filter_rows, respond
from store import db, sort_rows

bp = Blueprint("appeals", __name__)

READ_ROLES = ("Creator", "PolicyReviewer", "PlatformAdmin", "Auditor")
OPEN_STATES = ("SUBMITTED", "UNDER_REVIEW", "INFO_REQUESTED")
RESTRICTION = {"GREEN": 0, "YELLOW": 1, "RED": 2}

CREATE = (
    F("content_item_id", "str", required=True),
    F("requested_rating", "enum", required=True, enum=("GREEN", "YELLOW")),
    F("statement_text", "str", required=True, text=(1, 2000)),
)
INFO = (F("info_request", "str", required=True, text=(1, 2000)),)
RESPOND = (F("response_statement", "str", required=True, text=(1, 2000)),)
DECIDE = (
    F("decision", "enum", required=True, enum=("UPHELD", "DENIED")),
    F("rationale", "str", required=True, text=(1, 2000)),
)

PATH = (("appeal_id", "appeals"),)
OWN = lambda ctx: ctx.path["appeal_id"]["creator_id"]


@bp.route("/monetization/appeals", methods=["POST"])
@endpoint(roles=("Creator",), fields=CREATE,
          refs=(("content_item_id", "content_items"),),
          owner=lambda ctx: ctx.refs["content_item_id"]["creator_id"]
          if "content_item_id" in ctx.refs else None)
def create_appeal(ctx):
    item = ctx.refs["content_item_id"]
    if calc.MONETIZATION_STATE[item["suitability_rating"]] not in ("LIMITED",
                                                                  "DEMONETIZED"):
        fail("ERR_CONTENT_NOT_APPEALABLE",                                 # 19
             "Only LIMITED or DEMONETIZED content is appealable.")
    for row in db.rows("appeals"):                                         # 20
        if row["content_item_id"] == item["id"] and row["state"] in OPEN_STATES:
            fail("ERR_APPEAL_ALREADY_OPEN", "An appeal is already open.")
    if RESTRICTION[ctx.data["requested_rating"]] >= RESTRICTION[item["suitability_rating"]]:
        fail("ERR_APPEAL_RATING_NOT_IMPROVEMENT",                          # 56
             "requested_rating must be strictly less restrictive.")
    row = db.insert("appeals", {
        "content_item_id": item["id"],
        "creator_id": item["creator_id"],
        "requested_rating": ctx.data["requested_rating"],
        "statement_text": ctx.data["statement_text"],
        "state": "SUBMITTED",
        "revision_round": 0,
        "info_request": None,
        "response_statement": None,
        "decided_by_user_id": None,
        "decided_at": None,
        "rationale": None,
    })
    return created(serialize.appeal(row))


@bp.route("/monetization/appeals", methods=["GET"])
@endpoint(roles=READ_ROLES, listing=True)
def list_appeals(ctx):
    rows = db.rows("appeals")
    if ctx.is_creator:
        rows = [r for r in rows if r["creator_id"] == ctx.user_id]
    rows = filter_rows(rows, request.args, {
        "content_item_id": "content_item_id",
        "creator_id": "creator_id",
        "state": "state",
    })
    rows = sort_rows(rows, lambda r: (r["created_at"],))
    return respond(ctx, rows, serialize.appeal)


@bp.route("/monetization/appeals/<appeal_id>", methods=["GET"])
@endpoint(roles=READ_ROLES, path=PATH, owner=OWN)
def read_appeal(ctx, appeal_id):
    return ok(serialize.appeal(ctx.path["appeal_id"]))


@bp.route("/monetization/appeals/<appeal_id>/start-review", methods=["POST"])
@endpoint(roles=("PolicyReviewer",), path=PATH)
def start_review(ctx, appeal_id):
    row = ctx.path["appeal_id"]
    if row["state"] != "SUBMITTED":                                        # 21
        fail("ERR_APPEAL_NOT_SUBMITTED", "The appeal is not SUBMITTED.")
    row["state"] = "UNDER_REVIEW"
    db.touch(row)
    return ok(serialize.appeal(row))


@bp.route("/monetization/appeals/<appeal_id>/request-info", methods=["POST"])
@endpoint(roles=("PolicyReviewer",), path=PATH, fields=INFO)
def request_info(ctx, appeal_id):
    row = ctx.path["appeal_id"]
    if row["state"] != "UNDER_REVIEW":                                     # 22
        fail("ERR_APPEAL_NOT_UNDER_REVIEW", "The appeal is not UNDER_REVIEW.")
    row["state"] = "INFO_REQUESTED"
    row["info_request"] = ctx.data["info_request"]
    db.touch(row)
    return ok(serialize.appeal(row))


@bp.route("/monetization/appeals/<appeal_id>/respond", methods=["POST"])
@endpoint(roles=("Creator",), path=PATH, fields=RESPOND, owner=OWN)
def respond_appeal(ctx, appeal_id):
    row = ctx.path["appeal_id"]
    if row["state"] != "INFO_REQUESTED":                                   # 23
        fail("ERR_APPEAL_NOT_INFO_REQUESTED", "The appeal is not INFO_REQUESTED.")
    if row["revision_round"] >= calc.APPEAL_MAX_ROUNDS:                    # 24
        fail("ERR_APPEAL_ROUNDS_EXHAUSTED", "The appeal has no rounds left.")
    row["state"] = "SUBMITTED"
    row["revision_round"] += 1
    row["response_statement"] = ctx.data["response_statement"]
    db.touch(row)
    return ok(serialize.appeal(row))


@bp.route("/monetization/appeals/<appeal_id>/decide", methods=["POST"])
@endpoint(roles=("PolicyReviewer",), path=PATH, fields=DECIDE)
def decide_appeal(ctx, appeal_id):
    row = ctx.path["appeal_id"]
    if row["state"] != "UNDER_REVIEW":                                     # 22
        fail("ERR_APPEAL_NOT_UNDER_REVIEW", "The appeal is not UNDER_REVIEW.")
    item = db.get("content_items", row["content_item_id"])
    if item is not None and item["last_rated_by_user_id"] is not None \
            and item["last_rated_by_user_id"] == ctx.user_id:              # 45
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The reviewer who set the rating may not decide the appeal.")
    row["state"] = ctx.data["decision"]                                    # hop 1
    row["decided_by_user_id"] = ctx.user_id
    row["decided_at"] = db.now
    row["rationale"] = ctx.data["rationale"]
    db.touch(row)
    if ctx.data["decision"] == "UPHELD":
        item["suitability_rating"] = row["requested_rating"]               # hop 2
        item["rating_source"] = "APPEAL"
        item["last_rated_by_user_id"] = None
        item["last_rated_at"] = db.now
        db.touch(item)
        rescore.rescore_content(item, statuses=("REVERSED", "BELOW_MINIMUM"),
                                variant="RESTORE_ON_APPEAL")          # hops 3, 4
    return ok(serialize.appeal(row))
