"""Violation endpoints: record, appeal, accept-review, decide, list, read."""

from __future__ import annotations

import datetime as dt

from flask import Blueprint, g, jsonify, request

from db import db
from errors import (
    ERR_APPEAL_WINDOW_EXPIRED,
    ERR_FORBIDDEN,
    ERR_INVALID_STATE,
    ERR_VALIDATION,
    ERR_VIOLATION_REAPPEAL_LIMIT,
    raise_api_error,
)
from middleware import require_roles
from response import list_response, success_response
from services.calculations import (
    compute_violation_deduction,
    count_repeat_in_window,
)
from services.common import (
    check_version,
    get_json_body,
    iso_z,
    paginate,
    parse_iso8601_utc,
    parse_pagination,
    require_datetime,
    require_enum,
    require_str,
)
from services.ledger import append_audit_log, append_transaction
from services.lookup import (
    get_community,
    get_resident_by_id,
    get_violation,
)
from services.ranking_invalidate import invalidate_periods_overlapping

bp = Blueprint("violations", __name__)

VIOLATION_TYPES = {"MIS_SORTING", "LITTERING", "NO_CLASSIFICATION"}
APPEAL_WINDOW_DAYS = 14


@bp.post("/communities/<community_id>/violations")
@require_roles("CommunityAdmin")
def record_violation(community_id: str):
    get_community(community_id)
    body = get_json_body()
    resident_id = require_str(body, "resident_id", min_len=1, max_len=200)
    violation_type = require_enum(body, "violation_type", VIOLATION_TYPES)
    occurred_at = require_datetime(body, "occurred_at")
    evidence_uri = require_str(body, "evidence_uri", min_len=1, max_len=500)

    resident = db.residents.get(resident_id)
    if resident is None:
        from errors import ERR_NOT_FOUND
        raise_api_error(ERR_NOT_FOUND, f"Resident {resident_id} not found.")

    household = db.households.get(resident["household_id"])
    if household is None or household["community_id"] != community_id:
        from errors import ERR_NOT_FOUND
        raise_api_error(ERR_NOT_FOUND, "Resident does not belong to this community.")

    # Note: scaffold says "not ARCHIVED" — ARCHIVED is the only Resident
    # terminal-state mentioned. Currently there's no transition to ARCHIVED
    # in the public API, so this check is conservative.
    if resident.get("identity_status") == "ARCHIVED":
        raise_api_error(ERR_INVALID_STATE, "Resident is archived.")

    if occurred_at > db.now():
        raise_api_error(ERR_VALIDATION, "occurred_at must be <= now().")

    # First, create the entity so the repeat-count can include itself
    from db import gen_id

    vid = gen_id()
    appeal_deadline_at = occurred_at + dt.timedelta(days=APPEAL_WINDOW_DAYS)

    obj = {
        "id": vid,
        "resident_id": resident_id,
        "household_id": household["id"],
        "community_id": community_id,
        "violation_type": violation_type,
        "occurred_at": iso_z(occurred_at),
        "evidence_uri": evidence_uri,
        "base_deduction_points": 0,
        "repeat_count_in_window": 0,
        "escalation_multiplier": 1.0,
        "final_deduction_points": 0,
        "status": "NEW",
        "appeal_filed_at": None,
        "appeal_deadline_at": iso_z(appeal_deadline_at),
        "appeal_round": 0,
    }
    obj["created_at"] = db.now_iso()
    obj["updated_at"] = obj["created_at"]
    obj["version"] = 1
    db.violations[vid] = obj

    # Now compute repeat count (the new violation is in the DB now,
    # so it is included by count_repeat_in_window).
    repeat = count_repeat_in_window(
        resident_id=resident_id,
        violation_type=violation_type,
        occurred_at_utc=occurred_at,
        include_this_id=vid,
    )
    deduction = compute_violation_deduction(
        violation_type=violation_type, repeat_count=repeat,
    )

    obj["repeat_count_in_window"] = repeat
    obj["base_deduction_points"] = deduction["base_deduction_points"]
    obj["escalation_multiplier"] = deduction["escalation_multiplier"]
    obj["final_deduction_points"] = deduction["final_deduction_points"]

    # Apply deduction (may drive balance negative — explicitly allowed)
    household["points_balance"] -= obj["final_deduction_points"]
    db.stamp_update(household)
    append_transaction(
        household,
        kind="VIOLATION_DEBIT",
        amount=-int(obj["final_deduction_points"]),
        related_entity_kind="VIOLATION",
        related_entity_id=vid,
    )

    append_audit_log(
        actor_role=g.user_role,
        actor_id=g.user_id,
        action="VIOLATION_RECORDED",
        subject_kind="VIOLATION",
        subject_id=vid,
        before={},
        after={
            "final_deduction_points": obj["final_deduction_points"],
            "escalation_multiplier": obj["escalation_multiplier"],
            "repeat_count_in_window": obj["repeat_count_in_window"],
        },
        reason=None,
    )

    return jsonify(success_response(obj)), 201


@bp.post("/communities/<community_id>/violations/<violation_id>/appeal")
@require_roles("Resident")
def appeal_violation(community_id: str, violation_id: str):
    violation = get_violation(community_id, violation_id)
    body = get_json_body()
    check_version(body, violation)
    reason = require_str(body, "reason", min_len=1, max_len=500)

    # Ownership
    if violation["resident_id"] != g.user_id:
        raise_api_error(ERR_FORBIDDEN, "Resident may only appeal their own violations.")

    # Priority 6 — ERR_INVALID_STATE (must be NEW or UPHELD)
    if violation["status"] not in ("NEW", "UPHELD"):
        raise_api_error(ERR_INVALID_STATE, "Violation must be NEW or UPHELD to be appealed.")

    # Priority 7 — ERR_APPEAL_WINDOW_EXPIRED (fires BEFORE the reappeal-limit business check)
    deadline = parse_iso8601_utc(violation["appeal_deadline_at"])
    if db.now() >= deadline:
        raise_api_error(ERR_APPEAL_WINDOW_EXPIRED, "Appeal window has expired.")

    # Reappeal limit
    if violation["appeal_round"] >= 2:
        raise_api_error(ERR_VIOLATION_REAPPEAL_LIMIT, "Maximum appeal rounds reached.")

    # Transition
    if violation["status"] == "NEW":
        violation["status"] = "APPEALED"
        violation["appeal_round"] = 1
    else:  # UPHELD
        if violation["appeal_round"] != 1:
            raise_api_error(ERR_VIOLATION_REAPPEAL_LIMIT, "Re-appeal allowed only once after UPHELD.")
        violation["status"] = "APPEALED"
        violation["appeal_round"] = 2
    violation["appeal_filed_at"] = db.now_iso()
    db.stamp_update(violation)
    return jsonify(success_response(violation)), 200


@bp.post("/communities/<community_id>/violations/<violation_id>/accept-review")
@require_roles("AppealReviewer")
def accept_review(community_id: str, violation_id: str):
    violation = get_violation(community_id, violation_id)
    body = get_json_body()
    check_version(body, violation)
    if violation["status"] != "APPEALED":
        raise_api_error(ERR_INVALID_STATE, "Violation must be APPEALED to be accepted for review.")
    violation["status"] = "UNDER_REVIEW"
    db.stamp_update(violation)
    return jsonify(success_response(violation)), 200


def _cascade_overturn(violation: dict, household: dict):
    """When a violation is OVERTURNED, walk every later violation with same
    (resident_id, violation_type) and status in {NEW,APPEALED,UNDER_REVIEW,UPHELD}.
    Recompute their repeat_count excluding this overturned violation,
    recompute final_deduction_points, and emit MISJUDGMENT_ADJUSTMENT
    transactions for the delta (old - new), adjusting household balance.
    """
    occurred_at = parse_iso8601_utc(violation["occurred_at"])
    later = []
    for v in db.violations.values():
        if v["id"] == violation["id"]:
            continue
        if v["resident_id"] != violation["resident_id"]:
            continue
        if v["violation_type"] != violation["violation_type"]:
            continue
        if v["status"] not in ("NEW", "APPEALED", "UNDER_REVIEW", "UPHELD"):
            continue
        v_occ = parse_iso8601_utc(v["occurred_at"])
        if v_occ > occurred_at:
            later.append(v)

    later.sort(key=lambda x: parse_iso8601_utc(x["occurred_at"]))
    for v in later:
        v_occ = parse_iso8601_utc(v["occurred_at"])
        new_repeat = count_repeat_in_window(
            resident_id=v["resident_id"],
            violation_type=v["violation_type"],
            occurred_at_utc=v_occ,
            include_this_id=v["id"],
            exclude_ids={violation["id"]},
        )
        new_deduction = compute_violation_deduction(
            violation_type=v["violation_type"], repeat_count=new_repeat,
        )
        old_final = int(v["final_deduction_points"])
        new_final = int(new_deduction["final_deduction_points"])
        delta = old_final - new_final  # positive when new is smaller -> credit back

        v["repeat_count_in_window"] = new_repeat
        v["base_deduction_points"] = new_deduction["base_deduction_points"]
        v["escalation_multiplier"] = new_deduction["escalation_multiplier"]
        v["final_deduction_points"] = new_final
        db.stamp_update(v)

        # Balance adjustment: re-baselining the deduction
        if delta != 0:
            household["points_balance"] += delta
            db.stamp_update(household)
            append_transaction(
                household,
                kind="MISJUDGMENT_ADJUSTMENT",
                amount=int(delta),
                related_entity_kind="VIOLATION",
                related_entity_id=v["id"],
            )


@bp.post("/communities/<community_id>/violations/<violation_id>/decide")
@require_roles("AppealReviewer")
def decide_appeal(community_id: str, violation_id: str):
    violation = get_violation(community_id, violation_id)
    body = get_json_body()
    check_version(body, violation)
    decision = require_enum(body, "decision", {"UPHOLD", "OVERTURN"})
    reason = require_str(body, "reason", min_len=1, max_len=500)

    if violation["status"] != "UNDER_REVIEW":
        raise_api_error(ERR_INVALID_STATE, "Violation must be UNDER_REVIEW to decide.")

    if decision == "UPHOLD":
        violation["status"] = "UPHELD"
        db.stamp_update(violation)
        append_audit_log(
            actor_role=g.user_role,
            actor_id=g.user_id,
            action="VIOLATION_APPEAL_DECISION",
            subject_kind="VIOLATION",
            subject_id=violation["id"],
            before={"status": "UNDER_REVIEW"},
            after={"status": "UPHELD"},
            reason=reason,
        )
        return jsonify(success_response(violation)), 200

    # OVERTURN
    household = db.households.get(violation["household_id"])
    if household is None:
        raise_api_error(ERR_INVALID_STATE, "Household not found.")
    final_ded = int(violation["final_deduction_points"])
    household["points_balance"] += final_ded
    db.stamp_update(household)
    append_transaction(
        household,
        kind="VIOLATION_REVERSAL",
        amount=final_ded,
        related_entity_kind="VIOLATION",
        related_entity_id=violation["id"],
    )

    violation["status"] = "OVERTURNED"
    db.stamp_update(violation)

    _cascade_overturn(violation, household)

    invalidate_periods_overlapping(
        community_id=community_id,
        affected_time_utc=parse_iso8601_utc(violation["occurred_at"]),
    )

    append_audit_log(
        actor_role=g.user_role,
        actor_id=g.user_id,
        action="VIOLATION_APPEAL_DECISION",
        subject_kind="VIOLATION",
        subject_id=violation["id"],
        before={"status": "UNDER_REVIEW"},
        after={"status": "OVERTURNED"},
        reason=reason,
    )
    return jsonify(success_response(violation)), 200


@bp.get("/communities/<community_id>/violations/<violation_id>")
@require_roles("CommunityAdmin", "AppealReviewer", "Resident")
def read_violation(community_id: str, violation_id: str):
    v = get_violation(community_id, violation_id)
    if g.user_role == "Resident":
        if v["resident_id"] != g.user_id:
            raise_api_error(ERR_FORBIDDEN, "Resident may only read their own violations.")
    return jsonify(success_response(v)), 200


@bp.get("/communities/<community_id>/violations")
@require_roles("CommunityAdmin", "AppealReviewer")
def list_violations(community_id: str):
    get_community(community_id)
    limit, offset = parse_pagination()
    status_filter = request.args.get("status")
    vtype = request.args.get("violation_type")
    resident_id = request.args.get("resident_id")
    items = []
    for v in db.violations.values():
        if v["community_id"] != community_id:
            continue
        if status_filter is not None and v["status"] != status_filter:
            continue
        if vtype is not None and v["violation_type"] != vtype:
            continue
        if resident_id is not None and v["resident_id"] != resident_id:
            continue
        items.append(v)
    items.sort(key=lambda x: x["created_at"])
    page, total = paginate(items, limit, offset)
    return jsonify(list_response(page, limit, offset, total)), 200
