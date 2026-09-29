"""Sterile processing: stage logs, second-person attestation and the quarantine cascade."""

from flask import Blueprint, g

import constants
import db
import response
import validate
from db import store
from errors import ApiError
from middleware import ALL, authenticate
from services import query, serialize

bp = Blueprint("reprocessing", __name__)

STAGES = constants.REPROCESSING_STAGES


def _log(log_id):
    row = store.get("reprocessing_logs", log_id)
    if row is None:
        raise ApiError("ERR_REPROCESSING_LOG_NOT_FOUND")
    return row


def _closed_passing_logs(scope_id):
    return [
        row
        for row in store.all_rows("reprocessing_logs")
        if row["scope_asset_id"] == scope_id
        and row["log_status"] == "CLOSED"
        and row["outcome"] == "PASS"
    ]


def _expected_stage(scope):
    """The immediate successor of the scope's last closed passing stage."""
    passing = _closed_passing_logs(scope["id"])
    if not passing:
        return STAGES[0]
    last = passing[-1]
    index = STAGES.index(last["stage"])
    if index + 1 >= len(STAGES):
        return None
    return STAGES[index + 1]


@bp.route("/reprocessing-logs", methods=["POST"])
@authenticate([constants.ROLE_STERILE_TECH])
def open_log():
    body = validate.get_body()
    scope_asset_id = validate.str_field(body, "scope_asset_id")
    stage = validate.enum_field(body, "stage", STAGES)
    performed_by_provider_id = validate.str_field(body, "performed_by_provider_id")
    case_id = validate.str_field(body, "case_id", required=False, default=None)

    # Priority 10 — in the order the fields are listed.
    scope = store.get("scopes", scope_asset_id)
    if scope is None:
        raise ApiError("ERR_SCOPE_NOT_FOUND")
    performer = store.get("providers", performed_by_provider_id)
    if performer is None:
        raise ApiError("ERR_PROVIDER_NOT_FOUND")
    if case_id is not None and store.get("cases", case_id) is None:
        raise ApiError("ERR_CASE_NOT_FOUND")
    # Priority 14.
    if performed_by_provider_id != g.user_id:
        raise ApiError("ERR_ACTOR_IDENTITY_MISMATCH")

    # Priority 22 — QUARANTINED is terminal; no log may be opened against it.
    if scope["status"] == "QUARANTINED":
        raise ApiError("ERR_INVALID_REPROCESSING_TRANSITION")
    # Priority 53 — the performer's certification.
    if stage == "HIGH_LEVEL_DISINFECT" and not performer["hld_certified"]:
        raise ApiError("ERR_HLD_CERTIFICATION_REQUIRED")
    # Priority 56 — successor of the last closed passing stage, plus two standing exceptions.
    allowed = stage == _expected_stage(scope)
    if stage == "LEAK_TEST" and scope["leak_test_required"]:
        allowed = True
    if stage == "PRECLEAN" and scope["status"] == "SOILED":
        allowed = True
    if not allowed:
        raise ApiError("ERR_REPROCESSING_STAGE_OUT_OF_ORDER")
    # Priority 57.
    for row in store.all_rows("reprocessing_logs"):
        if row["scope_asset_id"] == scope["id"] and row["log_status"] == "OPEN":
            raise ApiError("ERR_REPROCESSING_LOG_ALREADY_OPEN")

    # Opening a log changes nothing about the scope.
    row = db.new_row(
        "reprocessing_logs",
        {
            "scope_asset_id": scope_asset_id,
            "case_id": case_id,
            "stage": stage,
            "performed_by_provider_id": performed_by_provider_id,
            "attested_by_provider_id": None,
            "started_at": store.now(),
            "completed_at": None,
            "outcome": None,
            "log_status": "OPEN",
        },
    )
    return response.created_response(serialize.dump("reprocessing_logs", row))


def _hld_covers_current_cycle(scope):
    """A dry-store may not launder a cycle whose disinfection belongs to an earlier one."""
    soiled_at = scope.get("_soiled_at")
    for row in _closed_passing_logs(scope["id"]):
        if row["stage"] != "HIGH_LEVEL_DISINFECT":
            continue
        if soiled_at is None or row["completed_at"] >= soiled_at:
            return True
    return False


def _apply_scope_effect(scope, log):
    """The stage-and-outcome pair decides the whole scope-side consequence."""
    if log["outcome"] == "FAIL":
        # The quarantine cascade: three linked hops, one version increment.
        scope["status"] = "QUARANTINED"
        scope["leak_test_required"] = True
        scope["reprocess_due_at"] = None
        db.touch(scope)
        return

    stage = log["stage"]
    if stage == "PRECLEAN":
        if scope["status"] == "SOILED":
            scope["status"] = "REPROCESSING"
            db.touch(scope)
    elif stage == "LEAK_TEST":
        # The only path from a leak-test debt back to a clean slate; status untouched.
        scope["cycles_since_leak_test"] = 0
        scope["leak_test_required"] = False
        db.touch(scope)
    elif stage == "MANUAL_CLEAN":
        # Closes its own log and drives no scope-side change at all.
        pass
    elif stage == "HIGH_LEVEL_DISINFECT":
        scope["hld_pass_at"] = log["completed_at"]
        db.touch(scope)
    elif stage == "DRY_STORE":
        if scope["status"] == "REPROCESSING" and _hld_covers_current_cycle(scope):
            scope["status"] = "AVAILABLE"
            scope["reprocess_due_at"] = None
            db.touch(scope)


@bp.route("/reprocessing-logs/<log_id>/complete", methods=["POST"])
@authenticate([constants.ROLE_STERILE_TECH])
def complete_log(log_id):
    body = validate.get_body()
    outcome = validate.enum_field(body, "outcome", constants.REPROCESSING_OUTCOMES)
    attested_by_provider_id = validate.str_field(body, "attested_by_provider_id")
    log = _log(log_id)
    # Priority 10.
    attester = store.get("providers", attested_by_provider_id)
    if attester is None:
        raise ApiError("ERR_PROVIDER_NOT_FOUND")
    # Priority 16 — one person may not both perform and attest.
    if (
        attested_by_provider_id == log["performed_by_provider_id"]
        or attested_by_provider_id != g.user_id
    ):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    # Priority 22.
    if log["log_status"] != "OPEN":
        raise ApiError("ERR_INVALID_REPROCESSING_TRANSITION")
    # Priority 53 — for HLD the certification binds both sides.
    if log["stage"] == "HIGH_LEVEL_DISINFECT":
        performer = store.get("providers", log["performed_by_provider_id"])
        if performer is None or not performer["hld_certified"] or not attester["hld_certified"]:
            raise ApiError("ERR_HLD_CERTIFICATION_REQUIRED")

    log["log_status"] = "CLOSED"
    log["completed_at"] = store.now()
    log["outcome"] = outcome
    log["attested_by_provider_id"] = attested_by_provider_id
    db.touch(log)

    scope = store.get("scopes", log["scope_asset_id"])
    if scope is not None:
        _apply_scope_effect(scope, log)
    return response.object_response(serialize.dump("reprocessing_logs", log))


@bp.route("/reprocessing-logs/<log_id>", methods=["GET"])
@authenticate(ALL)
def get_log(log_id):
    return response.object_response(serialize.dump("reprocessing_logs", _log(log_id)))


@bp.route("/reprocessing-logs", methods=["GET"])
@authenticate(ALL)
def list_logs():
    return query.collection(
        "reprocessing_logs",
        {
            "scope_asset_id": validate.query_str("scope_asset_id"),
            "case_id": validate.query_str("case_id"),
            "performed_by_provider_id": validate.query_str("performed_by_provider_id"),
            "attested_by_provider_id": validate.query_str("attested_by_provider_id"),
            "stage": validate.query_enum("stage", STAGES),
            "log_status": validate.query_enum("log_status", constants.REPROCESSING_LOG_STATUSES),
            "outcome": validate.query_enum("outcome", constants.REPROCESSING_OUTCOMES),
        },
    )
