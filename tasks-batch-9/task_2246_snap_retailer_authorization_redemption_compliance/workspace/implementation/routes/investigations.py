"""Investigation endpoints."""
from flask import Blueprint

import calc
import serial
import services
from core import (actor, bad_request, db, ensure_object, fail, filter_str,
                  get_body, mark, now, ok, ok_list, opt_str, ordered, paginate,
                  req_dt, req_enum, req_str, require_auth, resolve_body_ref,
                  resolve_path, stamp_new)
from guards import ANALYST_ADMIN, validate_evidence_items

bp = Blueprint("investigations", __name__)

OPENED_REASONS = ("ANOMALY_FLAG_L3", "TIP", "ALE_REFERRAL")
VIOLATIONS = ("TRAFFICKING", "INELIGIBLE_ITEM_SALES", "NONE")
INVESTIGATION_READ_ROLES = ("FnsAdmin", "FnsAnalyst", "AdminReviewOfficer")
INVESTIGATION_LIST_ROLES = ("FnsAdmin", "FnsAnalyst", "AdminReviewOfficer",
                            "RetailerOwner")
LIVE_STATUSES = ("OPEN", "EVIDENCE_REVIEW")


@bp.post("/investigations")
def create_investigation():
    require_auth(ANALYST_ADMIN)
    body = get_body()
    ensure_object(body)
    store = resolve_body_ref(body, "store_id", db.stores, "ERR_STORE_NOT_FOUND")
    period = resolve_body_ref(body, "trigger_period_id", db.redemption_periods,
                             "ERR_REDEMPTION_PERIOD_NOT_FOUND", optional=True)
    opened_reason = req_enum(body, "opened_reason", OPENED_REASONS)
    items = validate_evidence_items(body, "evidence_items")
    if store is None:
        req_str(body, "store_id")
    if opened_reason == "ANOMALY_FLAG_L3":
        if period is None:
            bad_request("Field 'trigger_period_id' is required when "
                        "opened_reason is ANOMALY_FLAG_L3.")
    elif body.get("trigger_period_id") is not None:
        bad_request("Field 'trigger_period_id' must be null unless "
                    "opened_reason is ANOMALY_FLAG_L3.")
    if period is not None:
        if period["store_id"] != store["id"] or period["status"] != "CLOSED" \
                or period.get("flag_level") != "FLAG_L3":
            fail("ERR_TRIGGER_PERIOD_NOT_FLAGGED")
    row = stamp_new({
        "store_id": store["id"],
        "trigger_period_id": None if period is None else period["id"],
        "opened_reason": opened_reason,
        "evidence_items": items if items is not None else [],
        "trafficking_confidence_score": 0,
        "substantiated_violation": None,
        "opened_by_user_id": actor(),
        "concluded_by_user_id": None,
        "concluded_at": None,
        "status": "OPEN",
    })
    db.investigations[row["id"]] = row
    services.open_investigation_cascade(store)
    services.commit()
    return ok(serial.investigation(row), 201)


@bp.get("/investigations/<investigation_id>")
def get_investigation(investigation_id):
    require_auth(INVESTIGATION_READ_ROLES)
    row = resolve_path(db.investigations, investigation_id,
                       "ERR_INVESTIGATION_NOT_FOUND")
    return ok(serial.investigation(row))


@bp.get("/investigations")
def list_investigations():
    require_auth(INVESTIGATION_LIST_ROLES)
    rows = ordered(list(db.investigations.values()))
    for name in ("store_id", "trigger_period_id", "status", "opened_reason"):
        value = filter_str(name)
        if value is not None:
            rows = [r for r in rows if r.get(name) == value]
    data, pagination = paginate(rows, serial.investigation)
    return ok_list(data, pagination)


@bp.post("/investigations/<investigation_id>/evidence")
def append_evidence(investigation_id):
    require_auth(ANALYST_ADMIN)
    row = resolve_path(db.investigations, investigation_id,
                       "ERR_INVESTIGATION_NOT_FOUND")
    body = get_body()
    ensure_object(body)
    evidence_type = req_enum(body, "evidence_type", calc.EVIDENCE_TYPES)
    observed_at = req_dt(body, "observed_at")
    note = opt_str(body, "note")
    if row["status"] not in LIVE_STATUSES:
        fail("ERR_INVALID_STATE")
    items = list(row.get("evidence_items") or [])
    items.append({
        "evidence_type": evidence_type,
        "observed_at": observed_at,
        "note": note,
    })
    row["evidence_items"] = items
    row["status"] = "EVIDENCE_REVIEW"
    row["trafficking_confidence_score"] = calc.trafficking_score(items, now())
    mark(row)
    services.commit()
    return ok(serial.investigation(row))


@bp.post("/investigations/<investigation_id>/conclude")
def conclude_investigation(investigation_id):
    require_auth(ANALYST_ADMIN)
    row = resolve_path(db.investigations, investigation_id,
                       "ERR_INVESTIGATION_NOT_FOUND")
    if actor() == row.get("opened_by_user_id"):
        fail("ERR_SEGREGATION_OF_DUTIES")
    body = get_body()
    ensure_object(body)
    violation = req_enum(body, "substantiated_violation", VIOLATIONS)
    if violation == "NONE":
        if row["status"] not in LIVE_STATUSES:
            fail("ERR_INVALID_STATE")
    elif row["status"] != "EVIDENCE_REVIEW":
        fail("ERR_INVALID_STATE")
    items = row.get("evidence_items") or []
    current = now()
    if violation == "TRAFFICKING":
        score = row.get("trafficking_confidence_score") or 0
        if score < calc.SUBSTANTIATION_MIN_SCORE or \
                not calc.has_live_anchor(items, current):
            fail("ERR_INSUFFICIENT_EVIDENCE")
    elif violation == "INELIGIBLE_ITEM_SALES":
        if not calc.has_live_item(items, current):
            fail("ERR_INSUFFICIENT_EVIDENCE")
    row["substantiated_violation"] = violation
    row["concluded_at"] = current
    row["concluded_by_user_id"] = actor()
    row["status"] = "SUBSTANTIATED" if violation != "NONE" else "UNSUBSTANTIATED"
    mark(row)
    if violation == "NONE":
        store = db.stores.get(row["store_id"])
        if store is not None and store["sanction_status"] == "UNDER_INVESTIGATION" \
                and not services.store_has_live_investigation(store["id"],
                                                              exclude_id=row["id"]):
            services.update_row(store, {"sanction_status": "NONE"})
    services.commit()
    return ok(serial.investigation(row))
