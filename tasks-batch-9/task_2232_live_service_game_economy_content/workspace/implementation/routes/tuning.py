"""Live balance tuning and community communication (PRD 3.8)."""
from flask import Blueprint, request

import config
import db
import resolve
import validators as v
from db import ordered, serialize
from errors import fail
from middleware import authenticate
from response import list_response, object_response, touch

bp = Blueprint("tuning", __name__)

READ_ROLES = (
    config.ROLE_ECONOMY_DESIGNER,
    config.ROLE_LIVEOPS_COMMANDER,
    config.ROLE_COMPLIANCE_OFFICER,
)

NEXT_STAGE = {
    "DRAFT": "SHADOW",
    "SHADOW": "CANARY",
    "CANARY": "LIVE",
    "LIVE": "RETIRED",
    "REVERTED": "SHADOW",
}


def _refresh_comms_state(change):
    notices = [n for n in db.db.notices.values() if n["balance_change_id"] == change["id"]]
    if any(n["status"] == "PUBLISHED" for n in notices):
        change["comms_state"] = "PUBLISHED"
    elif notices:
        change["comms_state"] = "DRAFTED"
    else:
        change["comms_state"] = "MISSING"
    return change["comms_state"]


# ---------------------------------------------------------------------------
# Balance changes
# ---------------------------------------------------------------------------
@bp.post("/balance-changes")
def create_balance_change():
    user_id, _role = authenticate(config.ROLE_ECONOMY_DESIGNER)
    payload = v.body()
    season = resolve.body_fk(payload, "season_id", db.db.seasons, "ERR_SEASON_NOT_FOUND")
    v.req_string(payload, "season_id")
    target_kind = v.req_enum(payload, "target_kind", config.BALANCE_TARGET_KINDS)
    delta_bp = v.req_int(payload, "delta_bp", minimum=-3000, maximum=3000)
    if delta_bp == 0:
        v.bad("delta_bp", "may not be zero")
    rationale = v.req_string(payload, "rationale")
    canary_cohort_pct = v.opt_int(payload, "canary_cohort_pct", default=5, minimum=1, maximum=50)

    change = db.insert(
        db.db.balance_changes,
        {
            "season_id": season["id"],
            "target_kind": target_kind,
            "delta_bp": delta_bp,
            "rationale": rationale,
            "canary_cohort_pct": canary_cohort_pct,
            "stage": "DRAFT",
            "comms_state": "MISSING",
            "authored_by_user_id": user_id,
            "promoted_by_user_id": None,
            "pre_live_sink_rate_bp": None,
        },
    )
    return object_response(serialize(change), 201)


@bp.get("/balance-changes/<change_id>")
def read_balance_change(change_id):
    authenticate(*READ_ROLES)
    change = resolve.balance_change(change_id)
    return object_response(serialize(change))


@bp.get("/balance-changes")
def list_balance_changes():
    authenticate(*READ_ROLES)
    season_id = request.args.get("season_id")
    stage = v.query_enum("stage", config.BALANCE_STAGES)
    limit, offset = v.pagination()
    rows = list(db.db.balance_changes.values())
    if season_id is not None:
        rows = [c for c in rows if c["season_id"] == season_id]
    if stage is not None:
        rows = [c for c in rows if c["stage"] == stage]
    records = [serialize(c) for c in ordered(rows)]
    page, total = v.paginate(records, limit, offset)
    return list_response(page, limit, offset, total)


@bp.post("/balance-changes/<change_id>/advance")
def advance_balance_change(change_id):
    user_id, _role = authenticate(config.ROLE_LIVEOPS_COMMANDER)
    change = resolve.balance_change(change_id)
    payload = v.body()
    to_stage = v.req_enum(payload, "to_stage", config.BALANCE_STAGES)
    expected_season_version = v.req_int(payload, "expected_season_version", minimum=1)
    season = db.db.seasons.get(change["season_id"])

    if season is None or season["version"] != expected_season_version:
        fail("ERR_STALE_SEASON_VERSION", "The pinned season version is stale.")

    current = change["stage"]
    if current not in NEXT_STAGE:
        fail("ERR_BALANCE_CHANGE_INVALID_STATE", "No advance exists from the %s stage." % current)
    expected_next = NEXT_STAGE[current]

    # The gates of the available transition are evaluated before the skip test,
    # because precedence steps 9/16/17 all precede step 21.
    if expected_next == "SHADOW":
        if season["status"] != "LIVE":
            fail("ERR_SEASON_NOT_LIVE", "The season must be LIVE to promote a tuning change.")
    elif expected_next == "CANARY":
        if change["comms_state"] not in ("DRAFTED", "PUBLISHED"):
            fail("ERR_COMMS_NOTICE_REQUIRED", "A community notice must exist before the canary stage.")
    elif expected_next == "LIVE":
        if change["comms_state"] != "PUBLISHED":
            fail("ERR_COMMS_NOTICE_REQUIRED", "A published community notice is required to go live.")
        if season["economy_health"] == "INFLATED":
            fail("ERR_ECONOMY_INFLATED_BLOCK", "The season economy is INFLATED.")

    if to_stage != expected_next:
        fail("ERR_BALANCE_CHANGE_STAGE_SKIP", "The only stage available from %s is %s." % (current, expected_next))

    if expected_next == "SHADOW":
        if current == "REVERTED":
            change["pre_live_sink_rate_bp"] = None
        season["active_tuning_count"] += 1
    elif expected_next == "LIVE":
        change["pre_live_sink_rate_bp"] = season["effective_sink_rate_bp"]
        if change["target_kind"] == "SINK_RATE":
            season["effective_sink_rate_bp"] += change["delta_bp"]
    elif expected_next == "RETIRED":
        season["active_tuning_count"] = max(0, season["active_tuning_count"] - 1)

    change["stage"] = expected_next
    change["promoted_by_user_id"] = user_id
    touch(change)

    season["tuning_stage_epoch"] += 1
    touch(season)
    return object_response(serialize(change))


@bp.post("/balance-changes/<change_id>/revert")
def revert_balance_change(change_id):
    user_id, _role = authenticate(config.ROLE_LIVEOPS_COMMANDER)
    change = resolve.balance_change(change_id)
    payload = v.body()
    v.req_string(payload, "reason")
    season = db.db.seasons.get(change["season_id"])

    current = change["stage"]
    if current not in ("CANARY", "LIVE"):
        fail("ERR_BALANCE_CHANGE_INVALID_STATE", "Only a CANARY or LIVE change can be reverted.")

    if current == "LIVE" and change["target_kind"] == "SINK_RATE":
        if change["pre_live_sink_rate_bp"] is not None:
            season["effective_sink_rate_bp"] = change["pre_live_sink_rate_bp"]

    change["stage"] = "REVERTED"
    change["promoted_by_user_id"] = user_id
    touch(change)

    season["active_tuning_count"] = max(0, season["active_tuning_count"] - 1)
    season["tuning_stage_epoch"] += 1
    touch(season)
    return object_response(serialize(change))


# ---------------------------------------------------------------------------
# Community notices
# ---------------------------------------------------------------------------
@bp.post("/balance-changes/<change_id>/comms-notices")
def create_comms_notice(change_id):
    authenticate(config.ROLE_ECONOMY_DESIGNER, config.ROLE_LIVEOPS_COMMANDER)
    change = resolve.balance_change(change_id)
    payload = v.body()
    channel = v.req_enum(payload, "channel", config.COMMS_CHANNELS)
    headline = v.req_string(payload, "headline")
    body_copy = v.req_string(payload, "body")

    notice = db.insert(
        db.db.notices,
        {
            "balance_change_id": change["id"],
            "channel": channel,
            "headline": headline,
            "body": body_copy,
            "status": "DRAFT",
            "published_at": None,
            "published_by_user_id": None,
        },
    )
    _refresh_comms_state(change)
    touch(change)
    return object_response(serialize(notice), 201)


@bp.get("/balance-changes/<change_id>/comms-notices")
def list_comms_notices(change_id):
    authenticate(*READ_ROLES)
    change = resolve.balance_change(change_id)
    status = v.query_enum("status", config.COMMS_STATUSES)
    limit, offset = v.pagination()
    rows = [n for n in db.db.notices.values() if n["balance_change_id"] == change["id"]]
    if status is not None:
        rows = [n for n in rows if n["status"] == status]
    records = [serialize(n) for n in ordered(rows)]
    page, total = v.paginate(records, limit, offset)
    return list_response(page, limit, offset, total)


@bp.post("/balance-changes/<change_id>/comms-notices/<notice_id>/publish")
def publish_comms_notice(change_id, notice_id):
    user_id, _role = authenticate(config.ROLE_COMPLIANCE_OFFICER, config.ROLE_LIVEOPS_COMMANDER)
    change = resolve.balance_change(change_id)
    notice = resolve.comms_notice(change, notice_id)

    if notice["status"] != "DRAFT":
        fail("ERR_COMMS_NOTICE_INVALID_STATE", "The notice is already PUBLISHED.")
    if change["stage"] not in ("DRAFT", "SHADOW", "CANARY", "LIVE"):
        fail(
            "ERR_COMMS_NOTICE_INVALID_STATE",
            "The tuning change has already been reverted or retired.",
        )
    if user_id == change["authored_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES", "The publisher may not be the change's author.")

    notice["status"] = "PUBLISHED"
    notice["published_at"] = db.now()
    notice["published_by_user_id"] = user_id
    touch(notice)

    _refresh_comms_state(change)
    touch(change)
    return object_response(serialize(notice))
