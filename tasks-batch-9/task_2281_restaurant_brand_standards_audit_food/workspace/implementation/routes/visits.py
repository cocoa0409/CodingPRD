"""The audit calendar: visit scheduling, scoring, submission, rescore,
finalization and voids, plus the scored-item reads.
"""

from decimal import Decimal

from flask import Blueprint, g

import db
import serializers
from common import days, hours, hours_between, minutes, q2, touch
from errors import fail
from middleware import (
    begin,
    body,
    filter_enum,
    filter_value,
    listing,
    lookup,
    opt_id,
    opt_str,
    req_dt,
    req_enum,
    req_id,
    req_int,
    require,
    resolve_identity,
)
from response import object_response
from services import calc, cascade

bp = Blueprint("visits", __name__)

VISIT_TYPES = ("ANNOUNCED", "UNANNOUNCED", "SHADOW")
VISIT_STATUSES = ("SCHEDULED", "IN_PROGRESS", "SUBMITTED", "FINALIZED", "VOIDED")
VOID_REASONS = ("AUDITOR_SUSPENDED", "RUBRIC_DEFECT", "SCHEDULING_ERROR")
SCORED_ITEM_STATUSES = ("SCORED", "UNDER_DISPUTE", "AMENDED", "UPHELD")
SEVERITIES = ("NONE", "STANDARD", "CRITICAL")

MIN_ANNOUNCED_NOTICE_HOURS = Decimal("72.00")
TRAVEL_BUFFER = minutes(60)
START_GRACE = minutes(60)
QUOTA_WINDOW_DAYS = 7
QUOTA_MAX_UNANNOUNCED = 2
MIX_WINDOW_DAYS = 182
MIX_STATUSES = ("SCHEDULED", "IN_PROGRESS", "SUBMITTED", "FINALIZED")
CRITICAL_DUE_HOURS = 72
STANDARD_DUE_DAYS = 14


def _own_visit(visit):
    """Step 5: the acting auditor must be the visit's own auditor."""
    if visit["auditor_id"] != g.user_id:
        fail("ERR_NOT_RESOURCE_OWNER", "The acting auditor is not assigned to this visit.")


def _has_open_dispute(visit_id):
    for scored in calc.scored_items_of(visit_id):
        if scored["status"] == "UNDER_DISPUTE":
            return True
    return False


def _visits_of_auditor(auditor_id):
    return [v for v in db.store.audit_visits.values() if v["auditor_id"] == auditor_id]


def _visits_of_location(location_id):
    return [v for v in db.store.audit_visits.values() if v["location_id"] == location_id]


# --------------------------------------------------------------------------
# POST /audit-visits
# --------------------------------------------------------------------------

@bp.route("/audit-visits", methods=["POST"])
def schedule_visit():
    begin("BrandAdmin")
    resolve_identity()
    payload = body()
    location_id = req_id(payload, "location_id")
    auditor_id = req_id(payload, "auditor_id")
    rubric_version_id = req_id(payload, "rubric_version_id")
    visit_type = req_enum(payload, "visit_type", VISIT_TYPES)
    scheduled_start_at = req_dt(payload, "scheduled_start_at")
    scheduled_end_at = req_dt(payload, "scheduled_end_at")
    shadow_of_visit_id = opt_id(payload, "shadow_of_visit_id")

    # 7: body foreign keys, left to right.
    location = require("location", location_id)
    auditor = require("auditor", auditor_id)
    rubric_version = require("rubric_version", rubric_version_id)
    shadow_target = None
    if shadow_of_visit_id is not None:
        shadow_target = require("visit", shadow_of_visit_id)

    # 9: the pinned rubric must be PUBLISHED at creation.
    if rubric_version["status"] != "PUBLISHED":
        fail(
            "ERR_RUBRIC_VERSION_NOT_PUBLISHED",
            "The rubric version is %s, not PUBLISHED." % rubric_version["status"],
        )

    # 12: the bound auditor may not be suspended.
    if auditor["status"] == "SUSPENDED":
        fail("ERR_AUDITOR_SUSPENDED", "The assigned auditor is SUSPENDED.")

    # 14: a shadow visit may not be assigned to the shadowed auditor.
    if visit_type == "SHADOW" and shadow_target is not None \
            and shadow_target["auditor_id"] == auditor_id:
        fail(
            "ERR_SEGREGATION_OF_DUTIES",
            "A shadow visit may not be assigned to the auditor it shadows.",
        )

    # 18: shadow_of_visit_id present exactly when visit_type is SHADOW.
    if visit_type == "SHADOW":
        if shadow_of_visit_id is None:
            fail("ERR_SHADOW_LINK_MISMATCH", "A SHADOW visit must name shadow_of_visit_id.")
    elif shadow_of_visit_id is not None:
        fail(
            "ERR_SHADOW_LINK_MISMATCH",
            "shadow_of_visit_id may only be supplied for a SHADOW visit.",
        )

    # 19: the shadow target must be a valid, non-shadow, non-voided sibling.
    if shadow_target is not None:
        if shadow_target["visit_type"] == "SHADOW" \
                or shadow_target["status"] == "VOIDED" \
                or shadow_target["location_id"] != location_id \
                or shadow_target["rubric_version_id"] != rubric_version_id:
            fail("ERR_SHADOW_TARGET_INVALID", "The shadow target visit is not eligible.")

    # 22: non-degenerate window.
    if not scheduled_end_at > scheduled_start_at:
        fail(
            "ERR_INVALID_VISIT_WINDOW",
            "scheduled_end_at must be strictly after scheduled_start_at.",
        )

    # 23: announced notice.
    announced_notice_hours = None
    if visit_type == "ANNOUNCED":
        announced_notice_hours = hours_between(db.store.clock, scheduled_start_at)
        if announced_notice_hours < MIN_ANNOUNCED_NOTICE_HOURS:
            fail(
                "ERR_ANNOUNCED_NOTICE_TOO_SHORT",
                "An ANNOUNCED visit needs at least 72.00 hours of notice, got %s."
                % announced_notice_hours,
            )

    # 24: the rubric is effective for the scheduled date.
    if rubric_version["effective_from"] > scheduled_start_at:
        fail(
            "ERR_RUBRIC_NOT_EFFECTIVE",
            "The rubric version is not yet effective for the scheduled start.",
        )

    # 26: auditor occupation, with a 60-minute travel buffer at both ends.
    for existing in _visits_of_auditor(auditor_id):
        if existing["status"] == "VOIDED":
            continue
        buffered_start = existing["scheduled_start_at"] - TRAVEL_BUFFER
        buffered_end = existing["scheduled_end_at"] + TRAVEL_BUFFER
        if scheduled_start_at < buffered_end and buffered_start < scheduled_end_at:
            fail(
                "ERR_AUDITOR_SCHEDULE_CONFLICT",
                "The auditor already has a visit inside the buffered window.",
            )

    # 27: location unannounced density quota.
    quota_low = scheduled_start_at - days(QUOTA_WINDOW_DAYS)
    quota_high = scheduled_start_at + days(QUOTA_WINDOW_DAYS)
    quota_count = 1 if visit_type == "UNANNOUNCED" else 0
    for existing in _visits_of_location(location_id):
        if existing["status"] == "VOIDED" or existing["visit_type"] != "UNANNOUNCED":
            continue
        if quota_low <= existing["scheduled_start_at"] <= quota_high:
            quota_count += 1
    if quota_count > QUOTA_MAX_UNANNOUNCED:
        fail(
            "ERR_LOCATION_VISIT_WINDOW_QUOTA",
            "At most 2 unannounced visits may fall in the 14-day window.",
        )

    # 29: the resulting unannounced mix must clear the brand minimum.  A shadow
    # audit is a supervision exercise and never appears on either side of the
    # fraction, so a SHADOW candidate is not evaluated.
    if visit_type != "SHADOW":
        brand = db.store.brands.get(location["brand_id"])
        minimum = brand["unannounced_min_ratio_pct"] if brand is not None else 0
        mix_low = scheduled_start_at - days(MIX_WINDOW_DAYS)
        mix_high = scheduled_start_at + days(MIX_WINDOW_DAYS)
        denominator = 1
        numerator = 1 if visit_type == "UNANNOUNCED" else 0
        for existing in _visits_of_location(location_id):
            if existing["visit_type"] not in ("ANNOUNCED", "UNANNOUNCED"):
                continue
            if existing["status"] not in MIX_STATUSES:
                continue
            if not (mix_low <= existing["scheduled_start_at"] <= mix_high):
                continue
            denominator += 1
            if existing["visit_type"] == "UNANNOUNCED":
                numerator += 1
        ratio = q2(Decimal(numerator) / Decimal(denominator) * Decimal(100))
        if ratio < Decimal(minimum):
            fail(
                "ERR_UNANNOUNCED_MIX_BELOW_MINIMUM",
                "The resulting unannounced ratio %s is below the brand minimum %s."
                % (ratio, minimum),
            )

    record = db.new_record()
    record.update({
        "location_id": location_id,
        "auditor_id": auditor_id,
        "rubric_version_id": rubric_version_id,
        "shadow_of_visit_id": shadow_of_visit_id,
        "linked_health_inspection_id": None,
        "visit_type": visit_type,
        "scheduled_start_at": scheduled_start_at,
        "scheduled_end_at": scheduled_end_at,
        "announced_notice_hours": announced_notice_hours,
        "status": "SCHEDULED",
        "started_at": None,
        "submitted_at": None,
        "finalized_at": None,
        "food_safety_percent": None,
        "brand_standards_percent": None,
        "facility_percent": None,
        "critical_violation_count": 0,
        "critical_penalty_points": Decimal("0.00"),
        "health_component_percent": None,
        "composite_score": None,
        "composite_variant": None,
        "grade": None,
        "rescore_count": 0,
        "void_reason": None,
    })
    db.store.audit_visits[record["id"]] = record
    return object_response(serializers.audit_visit(record), 201)


# --------------------------------------------------------------------------
# Visit reads
# --------------------------------------------------------------------------

@bp.route("/audit-visits/<visit_id>", methods=["GET"])
def read_visit(visit_id):
    begin("BrandAdmin", "Auditor", "CalibrationReviewer", "Franchisee")
    visit = require("visit", visit_id)
    resolve_identity()
    return object_response(serializers.audit_visit(visit))


@bp.route("/audit-visits", methods=["GET"])
def list_visits():
    begin("BrandAdmin", "Auditor", "CalibrationReviewer", "Franchisee")
    resolve_identity()
    location_id = filter_value("location_id")
    auditor_id = filter_value("auditor_id")
    rubric_version_id = filter_value("rubric_version_id")
    shadow_of_visit_id = filter_value("shadow_of_visit_id")
    linked_health_inspection_id = filter_value("linked_health_inspection_id")
    status = filter_enum("status", VISIT_STATUSES)
    visit_type = filter_enum("visit_type", VISIT_TYPES)

    records = []
    for visit in db.store.audit_visits.values():
        if location_id is not None and visit["location_id"] != location_id:
            continue
        if auditor_id is not None and visit["auditor_id"] != auditor_id:
            continue
        if rubric_version_id is not None and visit["rubric_version_id"] != rubric_version_id:
            continue
        if shadow_of_visit_id is not None and visit["shadow_of_visit_id"] != shadow_of_visit_id:
            continue
        if linked_health_inspection_id is not None \
                and visit["linked_health_inspection_id"] != linked_health_inspection_id:
            continue
        if status is not None and visit["status"] != status:
            continue
        if visit_type is not None and visit["visit_type"] != visit_type:
            continue
        records.append(visit)
    return listing(records, serializers.audit_visit)


@bp.route("/audit-visits/<visit_id>/calibration-records", methods=["GET"])
def list_visit_calibration_records(visit_id):
    begin("BrandAdmin", "CalibrationReviewer")
    require("visit", visit_id)
    resolve_identity()
    records = [
        r for r in db.store.calibration_records.values()
        if r["shadow_visit_id"] == visit_id or r["primary_visit_id"] == visit_id
    ]
    return listing(records, serializers.calibration_record)


@bp.route("/audit-visits/<visit_id>/escalation-events", methods=["GET"])
def list_visit_escalation_events(visit_id):
    begin("BrandAdmin")
    require("visit", visit_id)
    resolve_identity()
    records = [
        e for e in db.store.escalation_events.values()
        if e["audit_visit_id"] == visit_id
    ]
    return listing(records, serializers.escalation_event)


# --------------------------------------------------------------------------
# POST /audit-visits/{id}/start
# --------------------------------------------------------------------------

@bp.route("/audit-visits/<visit_id>/start", methods=["POST"])
def start_visit(visit_id):
    begin("Auditor")
    visit = require("visit", visit_id)
    resolve_identity()
    _own_visit(visit)
    body()

    if visit["status"] != "SCHEDULED":
        fail("ERR_INVALID_VISIT_STATE", "Only a SCHEDULED visit may be started.")

    auditor = g.actor
    if auditor["status"] == "SUSPENDED":
        fail("ERR_AUDITOR_SUSPENDED", "A SUSPENDED auditor may not start a visit.")
    if auditor["status"] != "CERTIFIED":
        fail("ERR_AUDITOR_NOT_CERTIFIED", "Only a CERTIFIED auditor may start a visit.")

    if db.store.clock < visit["scheduled_start_at"] - START_GRACE:
        fail(
            "ERR_VISIT_WINDOW_NOT_OPEN",
            "A visit may start no earlier than 60 minutes before scheduled_start_at.",
        )

    visit["status"] = "IN_PROGRESS"
    visit["started_at"] = db.store.clock
    touch(visit)
    return object_response(serializers.audit_visit(visit))


# --------------------------------------------------------------------------
# POST /audit-visits/{id}/scored-items
# --------------------------------------------------------------------------

@bp.route("/audit-visits/<visit_id>/scored-items", methods=["POST"])
def score_item(visit_id):
    begin("Auditor")
    visit = require("visit", visit_id)
    resolve_identity()
    _own_visit(visit)
    payload = body()
    rubric_item_id = req_id(payload, "rubric_item_id")
    points_awarded = req_int(payload, "points_awarded")
    note = opt_str(payload, "note", 0, 500)

    rubric_item = require("rubric_item", rubric_item_id)

    if visit["status"] != "IN_PROGRESS":
        fail("ERR_INVALID_VISIT_STATE", "Only an IN_PROGRESS visit may be scored.")

    if rubric_item["rubric_version_id"] != visit["rubric_version_id"]:
        fail(
            "ERR_RUBRIC_ITEM_NOT_IN_VISIT_RUBRIC",
            "The rubric item does not belong to the visit's pinned rubric version.",
        )

    if points_awarded < 0 or points_awarded > rubric_item["max_points"]:
        fail(
            "ERR_POINTS_EXCEED_MAX",
            "points_awarded must be between 0 and %s inclusive." % rubric_item["max_points"],
        )

    for existing in calc.scored_items_of(visit_id):
        if existing["rubric_item_id"] == rubric_item_id:
            fail("ERR_ITEM_ALREADY_SCORED", "The rubric item is already scored on this visit.")

    record = db.new_record()
    record.update({
        "visit_id": visit_id,
        "rubric_item_id": rubric_item_id,
        "points_awarded": points_awarded,
        "original_points_awarded": points_awarded,
        "amended_points_awarded": None,
        "effective_points_awarded": points_awarded,
        "is_violation": False,
        "severity": "NONE",
        "status": "SCORED",
        "note": note,
    })
    calc.derive_scored_item(record)
    db.store.scored_items[record["id"]] = record
    return object_response(serializers.scored_item(record), 201)


# --------------------------------------------------------------------------
# POST /audit-visits/{id}/submit
# --------------------------------------------------------------------------

@bp.route("/audit-visits/<visit_id>/submit", methods=["POST"])
def submit_visit(visit_id):
    begin("Auditor")
    visit = require("visit", visit_id)
    resolve_identity()
    _own_visit(visit)
    body()

    if visit["status"] != "IN_PROGRESS":
        fail("ERR_INVALID_VISIT_STATE", "Only an IN_PROGRESS visit may be submitted.")

    scored_item_ids = set(s["rubric_item_id"] for s in calc.scored_items_of(visit_id))
    for item in calc.rubric_items_of(visit["rubric_version_id"]):
        if item["is_critical"] and item["id"] not in scored_item_ids:
            fail(
                "ERR_CRITICAL_ITEMS_UNSCORED",
                "Every critical rubric item must be scored before submission.",
            )

    visit["status"] = "SUBMITTED"
    visit["submitted_at"] = db.store.clock
    touch(visit)
    calc.recompute_visit_scores(visit, "PROVISIONAL")
    return object_response(serializers.audit_visit(visit))


# --------------------------------------------------------------------------
# POST /audit-visits/{id}/rescore
# --------------------------------------------------------------------------

@bp.route("/audit-visits/<visit_id>/rescore", methods=["POST"])
def rescore_visit(visit_id):
    begin("Auditor")
    visit = require("visit", visit_id)
    resolve_identity()
    _own_visit(visit)
    payload = body()
    scored_item_id = req_id(payload, "scored_item_id")
    points_awarded = req_int(payload, "points_awarded")
    expected_visit_version = req_int(payload, "expected_visit_version", 0)

    scored = db.store.scored_items.get(scored_item_id)
    if scored is None or scored["visit_id"] != visit_id:
        fail("ERR_SCORED_ITEM_NOT_FOUND", "Scored item does not exist on this visit.")

    if visit["status"] != "SUBMITTED":
        fail("ERR_INVALID_VISIT_STATE", "Only a SUBMITTED visit may be rescored.")

    if expected_visit_version != visit["version"]:
        fail(
            "ERR_STALE_VISIT_VERSION",
            "expected_visit_version %s does not match the visit's current version %s."
            % (expected_visit_version, visit["version"]),
        )

    if _has_open_dispute(visit_id):
        fail("ERR_UNRESOLVED_DISPUTE", "A scored item of this visit is UNDER_DISPUTE.")

    rubric_item = db.store.rubric_items.get(scored["rubric_item_id"])
    max_points = rubric_item["max_points"] if rubric_item is not None else 0
    if points_awarded < 0 or points_awarded > max_points:
        fail(
            "ERR_POINTS_EXCEED_MAX",
            "points_awarded must be between 0 and %s inclusive." % max_points,
        )

    if visit["rescore_count"] >= 2:
        fail("ERR_RESCORE_LIMIT_REACHED", "At most two rescores are accepted per visit.")

    scored["points_awarded"] = points_awarded
    calc.derive_scored_item(scored)
    touch(scored)

    visit["rescore_count"] = visit["rescore_count"] + 1
    touch(visit)
    calc.recompute_visit_scores(visit, "PROVISIONAL")
    return object_response(serializers.audit_visit(visit))


# --------------------------------------------------------------------------
# POST /audit-visits/{id}/finalize
# --------------------------------------------------------------------------

def _create_corrective_actions(visit, location):
    created = []
    for scored in calc.scored_items_of(visit["id"]):
        if not scored["is_violation"]:
            continue
        if scored["severity"] == "CRITICAL":
            due_at = visit["finalized_at"] + hours(CRITICAL_DUE_HOURS)
        else:
            due_at = visit["finalized_at"] + days(STANDARD_DUE_DAYS)
        action = db.new_record()
        action.update({
            "scored_item_id": scored["id"],
            "location_id": location["id"],
            "assigned_franchisee_id": location["franchisee_id"],
            "severity": scored["severity"],
            "due_at": due_at,
            "status": "ASSIGNED",
            "submission_count": 0,
            "rejection_count": 0,
            "evidence_photo_count": 0,
            "submitted_at": None,
            "verified_at": None,
            "escalated_at": None,
        })
        db.store.corrective_actions[action["id"]] = action
        created.append(action)
    return created


@bp.route("/audit-visits/<visit_id>/finalize", methods=["POST"])
def finalize_visit(visit_id):
    begin("BrandAdmin")
    visit = require("visit", visit_id)
    resolve_identity()
    body()

    if visit["status"] != "SUBMITTED":
        fail("ERR_INVALID_VISIT_STATE", "Only a SUBMITTED visit may be finalized.")

    if visit["shadow_of_visit_id"] is not None:
        target = db.store.audit_visits.get(visit["shadow_of_visit_id"])
        if target is None or target["status"] != "FINALIZED":
            fail(
                "ERR_INVALID_VISIT_STATE",
                "The shadowed visit must be FINALIZED before its shadow visit.",
            )

    if _has_open_dispute(visit_id):
        fail("ERR_UNRESOLVED_DISPUTE", "A scored item of this visit is UNDER_DISPUTE.")

    visit["status"] = "FINALIZED"
    visit["finalized_at"] = db.store.clock
    touch(visit)

    inspection_id, health_percent = calc.select_health_component(visit)
    visit["linked_health_inspection_id"] = inspection_id
    visit["health_component_percent"] = health_percent
    calc.recompute_visit_scores(visit, "FINAL")

    location = db.store.locations.get(visit["location_id"])
    auditor = db.store.auditors.get(visit["auditor_id"])

    if location is not None:
        _create_corrective_actions(visit, location)

    if auditor is not None:
        cascade.recompute_auditor_finalized_count(auditor)

    if location is not None:
        cascade.recompute_open_action_count(location)

        # Repeat-violation accounting, then one REPEAT_CRITICAL entry per rubric
        # item that this very visit pushed to its second critical violation.
        hits = calc.repeat_hits(location["id"])
        calc.recompute_repeat_violation_count(location)
        this_visit_criticals = calc.critical_item_ids_of_visit(visit["id"])
        for rubric_item_id in sorted(this_visit_criticals):
            if hits.get(rubric_item_id, 0) == 2:
                cascade.append_escalation_event(
                    location,
                    "REPEAT_CRITICAL",
                    audit_visit_id=visit["id"],
                )

        calc.recompute_standing_score(location)

        franchisee = db.store.franchisees.get(location["franchisee_id"])
        if franchisee is not None:
            cascade.recompute_franchisee(franchisee)
        brand = db.store.brands.get(location["brand_id"])
        if brand is not None:
            cascade.recompute_brand_counts(brand)
            cascade.recompute_brand_risk(brand)

    return object_response(serializers.audit_visit(visit))


# --------------------------------------------------------------------------
# POST /audit-visits/{id}/void
# --------------------------------------------------------------------------

def _actions_created_by_visit(visit_id):
    scored_ids = set(s["id"] for s in calc.scored_items_of(visit_id))
    actions = [
        a for a in db.store.corrective_actions.values()
        if a["scored_item_id"] in scored_ids
    ]
    actions.sort(key=db.sort_key)
    return actions


@bp.route("/audit-visits/<visit_id>/void", methods=["POST"])
def void_visit(visit_id):
    begin("BrandAdmin")
    visit = require("visit", visit_id)
    resolve_identity()
    payload = body()
    void_reason = req_enum(payload, "void_reason", VOID_REASONS)

    previous_status = visit["status"]
    if previous_status == "VOIDED":
        fail("ERR_INVALID_VISIT_STATE", "The visit is already VOIDED.")

    if previous_status in ("SUBMITTED", "FINALIZED") and _has_open_dispute(visit_id):
        fail("ERR_UNRESOLVED_DISPUTE", "A scored item of this visit is UNDER_DISPUTE.")

    actions = _actions_created_by_visit(visit_id)
    if previous_status == "FINALIZED":
        for action in actions:
            if action["status"] == "VERIFIED":
                fail(
                    "ERR_VERIFIED_ACTION_BLOCKS_VOID",
                    "A verified corrective action blocks the void of this visit.",
                )

    visit["status"] = "VOIDED"
    visit["void_reason"] = void_reason
    touch(visit)

    if previous_status in ("SUBMITTED", "FINALIZED"):
        visit["composite_score"] = None
        visit["composite_variant"] = None
        visit["grade"] = None
    if previous_status == "FINALIZED":
        visit["health_component_percent"] = None

    if previous_status != "FINALIZED":
        return object_response(serializers.audit_visit(visit))

    auditor = db.store.auditors.get(visit["auditor_id"])
    if auditor is not None:
        cascade.recompute_auditor_finalized_count(auditor)

    location = db.store.locations.get(visit["location_id"])
    if location is not None:
        for action in actions:
            cascade.void_corrective_action(action, location)

        for _ in cascade.repeat_critical_events_of_visit(visit["id"]):
            cascade.append_escalation_event(
                location,
                "VOID_REVERSAL",
                audit_visit_id=visit["id"],
            )

        cascade.recompute_open_action_count(location)
        calc.recompute_repeat_violation_count(location)
        calc.recompute_standing_score(location)

        franchisee = db.store.franchisees.get(location["franchisee_id"])
        if franchisee is not None:
            cascade.recompute_franchisee(franchisee)
        brand = db.store.brands.get(location["brand_id"])
        if brand is not None:
            cascade.recompute_brand_counts(brand)
            cascade.recompute_brand_risk(brand)

    return object_response(serializers.audit_visit(visit))


# --------------------------------------------------------------------------
# Scored items
# --------------------------------------------------------------------------

@bp.route("/scored-items/<scored_item_id>", methods=["GET"])
def read_scored_item(scored_item_id):
    begin("BrandAdmin", "Auditor", "Franchisee")
    scored = require("scored_item", scored_item_id)
    resolve_identity()
    return object_response(serializers.scored_item(scored))


@bp.route("/scored-items", methods=["GET"])
def list_scored_items():
    begin("BrandAdmin", "Auditor", "Franchisee")
    resolve_identity()
    visit_id = filter_value("visit_id")
    rubric_item_id = filter_value("rubric_item_id")
    status = filter_enum("status", SCORED_ITEM_STATUSES)
    severity = filter_enum("severity", SEVERITIES)

    records = []
    for scored in db.store.scored_items.values():
        if visit_id is not None and scored["visit_id"] != visit_id:
            continue
        if rubric_item_id is not None and scored["rubric_item_id"] != rubric_item_id:
            continue
        if status is not None and scored["status"] != status:
            continue
        if severity is not None and scored["severity"] != severity:
            continue
        records.append(scored)
    return listing(records, serializers.scored_item)
