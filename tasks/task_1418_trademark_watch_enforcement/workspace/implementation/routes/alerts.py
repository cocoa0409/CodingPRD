"""WatchAlert endpoints (PRD 3.3, 3.4) plus nested takedown/referral creates."""

from decimal import Decimal

from flask import Blueprint

import db
from errors import (
    raise_error, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_STALE_VERSION,
    ERR_OPPOSITION_WINDOW_CLOSED, ERR_SCORE_BELOW_THRESHOLD,
    ERR_SCORE_ABOVE_DISMISS_CAP, ERR_REFERRAL_THRESHOLD_NOT_MET,
    ERR_VALIDATION,
)
from middleware import require_roles, enforce_client_scope
from response import success
from services import domain
from services.domain import (
    ser_watch_alert, ser_enforcement_matter, ser_takedown_filing,
    ser_counterfeit_referral, provisional_score, tier_of, confusion_score,
    confirmed_counterfeit_count, statutory_damages_cents, active_matter_of_alert,
    PLATFORM_FEE_CENTS,
)
from util import (
    get_payload, reject_unknown_fields, require_string, require_enum,
    require_int, require_number, require_class_array, require_array,
    coerce_version, stamp_new, touch, parse_dt,
)
from routes.common import do_list

bp = Blueprint("watch_alerts", __name__)

READ_ROLES = ("Paralegal", "AssociateAttorney", "PartnerAttorney", "ClientContact")
SOURCES = ("WATCH_SERVICE", "MANUAL", "MARKETPLACE_SWEEP")
MATTER_TYPES = ("OPPOSITION", "CANCELLATION", "INFRINGEMENT", "COUNTERFEIT")
PLATFORMS = ("AMAZON", "EBAY", "ALIBABA", "META", "DOMAIN_REGISTRAR")
BASES = ("TRADEMARK", "COUNTERFEIT")
REFERRAL_CHANNELS = ("LAW_ENFORCEMENT", "CUSTOMS_SEIZE", "PLATFORM_ESCROW")

ASSESS_FIELDS = {"weight_mark", "weight_goods", "weight_channels", "fame_adjustment",
                 "rationale", "expected_watch_alert_version"}


def _get_alert(alert_id):
    alert = db.watch_alerts.get(alert_id)
    if alert is None:
        raise_error(ERR_NOT_FOUND, "WatchAlert not found")
    return alert


@bp.route("/brand/watch-alerts", methods=["POST"])
def create_alert():
    user_id, role = require_roles("WatchService", "Paralegal")
    body = get_payload()
    reject_unknown_fields(body, {"trademark_record_id", "source", "conflicting_mark_text",
                                 "conflicting_owner", "conflicting_classes", "similarity_mark",
                                 "similarity_goods", "similarity_channels"})
    record_id = require_string(body, "trademark_record_id")
    source = require_enum(body, "source", SOURCES)
    conflicting_mark_text = require_string(body, "conflicting_mark_text")
    conflicting_owner = require_string(body, "conflicting_owner")
    conflicting_classes = require_class_array(body, "conflicting_classes")
    similarity_mark = require_int(body, "similarity_mark", minimum=0, maximum=100)
    similarity_goods = require_int(body, "similarity_goods", minimum=0, maximum=100)
    similarity_channels = require_int(body, "similarity_channels", minimum=0, maximum=100)
    if record_id not in db.trademark_records:
        raise_error(ERR_NOT_FOUND, "TrademarkRecord not found")
    # Intake computes the provisional score with fixed 0.5/0.3/0.2 weights,
    # no fame adjustment; identical-presumption floor applies (PRD 3.3).
    pscore = provisional_score(similarity_mark, similarity_goods, similarity_channels)
    alert = {
        "trademark_record_id": record_id,
        "source": source,
        "conflicting_mark_text": conflicting_mark_text,
        "conflicting_owner": conflicting_owner,
        "conflicting_classes": list(conflicting_classes),
        "similarity_mark": similarity_mark,
        "similarity_goods": similarity_goods,
        "similarity_channels": similarity_channels,
        "provisional_score": float(pscore),
        "provisional_tier": tier_of(pscore),
        "final_score": None,
        "final_tier": None,
        "assessment_round": 0,
        "escalation_level": "STANDARD",
        "referral_auto_created": False,
        "status": "NEW",
    }
    stamp_new(alert)
    db.watch_alerts[alert["id"]] = alert
    return success(ser_watch_alert(alert), 201)


@bp.route("/brand/watch-alerts", methods=["GET"])
def list_alerts():
    user_id, role = require_roles(*READ_ROLES)
    return do_list(db.watch_alerts.values(), ser_watch_alert,
                   [("trademark_record_id", "trademark_record_id", None),
                    ("status", "status", None),
                    ("final_tier", "final_tier", None)],
                   user_id, role, "watch_alert")


@bp.route("/brand/watch-alerts/<alert_id>", methods=["GET"])
def get_alert(alert_id):
    user_id, role = require_roles(*READ_ROLES)
    alert = _get_alert(alert_id)
    enforce_client_scope(user_id, role, domain.client_id_of_alert(alert))
    return success(ser_watch_alert(alert), 200)


@bp.route("/brand/watch-alerts/<alert_id>/triage", methods=["POST"])
def triage_alert(alert_id):
    user_id, role = require_roles("Paralegal")
    body = get_payload()
    reject_unknown_fields(body, set())
    alert = _get_alert(alert_id)
    if alert["status"] != "NEW":
        raise_error(ERR_INVALID_STATE, "triage is declared only from NEW")
    alert["status"] = "TRIAGED"
    touch(alert)
    return success(ser_watch_alert(alert), 200)


@bp.route("/brand/watch-alerts/<alert_id>/assess", methods=["POST"])
def assess_alert(alert_id):
    user_id, role = require_roles("AssociateAttorney")
    body = get_payload()
    reject_unknown_fields(body, ASSESS_FIELDS)
    weight_mark = require_number(body, "weight_mark")
    weight_goods = require_number(body, "weight_goods")
    weight_channels = require_number(body, "weight_channels")
    fame_adjustment = require_int(body, "fame_adjustment", minimum=-20, maximum=20)
    require_string(body, "rationale")
    expected_version = coerce_version(body, "expected_watch_alert_version")
    # Attorney weights must sum to 1.0 within a tolerance of 0.0001.
    total = Decimal(str(weight_mark)) + Decimal(str(weight_goods)) + Decimal(str(weight_channels))
    if abs(total - Decimal(1)) > Decimal("0.0001"):
        raise_error(ERR_VALIDATION, "assess weights must sum to 1.0")
    alert = _get_alert(alert_id)
    if alert["status"] not in ("TRIAGED", "UNDER_ASSESSMENT", "MONITORING"):
        raise_error(ERR_INVALID_STATE,
                    "assess is declared only from TRIAGED, UNDER_ASSESSMENT, MONITORING")
    # OCC: the expected version must match the alert's current version.
    if expected_version != alert["version"]:
        raise_error(ERR_STALE_VERSION, "expected_watch_alert_version does not match alert version")
    score = confusion_score(alert["similarity_mark"], alert["similarity_goods"],
                            alert["similarity_channels"],
                            weight_mark, weight_goods, weight_channels, fame_adjustment)
    alert["final_score"] = float(score)
    alert["final_tier"] = tier_of(score)
    alert["assessment_round"] += 1
    alert["status"] = "UNDER_ASSESSMENT"
    touch(alert)
    return success(ser_watch_alert(alert), 200)


@bp.route("/brand/watch-alerts/<alert_id>/escalate", methods=["POST"])
def escalate_alert(alert_id):
    user_id, role = require_roles("AssociateAttorney")
    body = get_payload()
    reject_unknown_fields(body, {"matter_type"})
    matter_type = require_enum(body, "matter_type", MATTER_TYPES)
    alert = _get_alert(alert_id)
    if alert["status"] != "UNDER_ASSESSMENT":
        raise_error(ERR_INVALID_STATE, "escalate is declared only from UNDER_ASSESSMENT")
    record = db.trademark_records.get(alert["trademark_record_id"])
    # Record-state admissibility per matter_type (state priority).
    if matter_type == "OPPOSITION":
        if record["status"] != "PUBLISHED":
            raise_error(ERR_INVALID_STATE, "OPPOSITION requires record status PUBLISHED")
    elif matter_type == "CANCELLATION":
        if record["status"] != "REGISTERED":
            raise_error(ERR_INVALID_STATE, "CANCELLATION requires record status REGISTERED")
    else:
        if record["status"] == "CANCELLED":
            raise_error(ERR_INVALID_STATE, "Record is CANCELLED")
    # Temporal: the opposition window must not have passed.
    if matter_type == "OPPOSITION":
        if db.clock.now() > parse_dt(record["opposition_due_at"]):
            raise_error(ERR_OPPOSITION_WINDOW_CLOSED,
                        "current_utc is past the record's opposition_due_at")
    # Score gate: escalation requires final_score >= 70.
    if alert["final_score"] is None or Decimal(str(alert["final_score"])) < Decimal(70):
        raise_error(ERR_SCORE_BELOW_THRESHOLD, "escalate requires final_score >= 70")
    matter = {
        "client_id": record["client_id"],
        "trademark_record_id": record["id"],
        "watch_alert_id": alert["id"],
        "matter_type": matter_type,
        "status": "ACTIVE",
        "resolution_outcome": None,
    }
    stamp_new(matter)
    db.enforcement_matters[matter["id"]] = matter
    alert["status"] = "ESCALATED"
    touch(alert)
    # Record challenge cascade (PRD 3.2).
    if matter_type == "OPPOSITION" and record["status"] == "PUBLISHED":
        record["status"] = "UNDER_CHALLENGE"
        touch(record)
    elif matter_type == "CANCELLATION" and record["status"] == "REGISTERED":
        record["status"] = "UNDER_CHALLENGE"
        touch(record)
    # Exposure index / watch posture are derived from live matter state.
    return success(ser_enforcement_matter(matter), 201)


@bp.route("/brand/watch-alerts/<alert_id>/monitor", methods=["POST"])
def monitor_alert(alert_id):
    user_id, role = require_roles("AssociateAttorney")
    body = get_payload()
    reject_unknown_fields(body, set())
    alert = _get_alert(alert_id)
    if alert["status"] != "UNDER_ASSESSMENT":
        raise_error(ERR_INVALID_STATE, "monitor is declared only from UNDER_ASSESSMENT")
    score = alert["final_score"]
    if score is None or not (Decimal(40) <= Decimal(str(score)) < Decimal(70)):
        raise_error(ERR_INVALID_STATE, "monitor requires 40 <= final_score < 70")
    alert["status"] = "MONITORING"
    touch(alert)
    return success(ser_watch_alert(alert), 200)


@bp.route("/brand/watch-alerts/<alert_id>/dismiss", methods=["POST"])
def dismiss_alert(alert_id):
    user_id, role = require_roles("AssociateAttorney")
    body = get_payload()
    reject_unknown_fields(body, {"dismiss_reason"})
    require_string(body, "dismiss_reason")
    alert = _get_alert(alert_id)
    if alert["status"] != "UNDER_ASSESSMENT":
        raise_error(ERR_INVALID_STATE, "dismiss is declared only from UNDER_ASSESSMENT")
    score = alert["final_score"]
    if score is None or not (Decimal(str(score)) < Decimal(40)):
        raise_error(ERR_SCORE_ABOVE_DISMISS_CAP, "dismiss requires final_score < 40")
    alert["status"] = "DISMISSED"
    touch(alert)
    return success(ser_watch_alert(alert), 200)


# ---------------------------------------------------------------------------
# Nested: POST /brand/watch-alerts/{id}/takedown-filings (PRD 3.7)
# ---------------------------------------------------------------------------

@bp.route("/brand/watch-alerts/<alert_id>/takedown-filings", methods=["POST"])
def create_takedown(alert_id):
    user_id, role = require_roles("Paralegal")
    body = get_payload()
    reject_unknown_fields(body, {"platform", "listing_url", "basis"})
    platform = require_enum(body, "platform", PLATFORMS)
    listing_url = require_string(body, "listing_url")
    basis = require_enum(body, "basis", BASES)
    alert = _get_alert(alert_id)
    filing = {
        "watch_alert_id": alert["id"],
        "platform": platform,
        "listing_url": listing_url,
        "basis": basis,
        # The platform fee is computed onto fee_cents at draft time (PRD 2.6).
        "fee_cents": PLATFORM_FEE_CENTS[platform],
        "appeal_count": 0,
        "status": "DRAFT",
    }
    stamp_new(filing)
    db.takedown_filings[filing["id"]] = filing
    return success(ser_takedown_filing(filing), 201)


# ---------------------------------------------------------------------------
# Nested: POST /brand/watch-alerts/{id}/counterfeit-referrals (PRD 3.7)
# ---------------------------------------------------------------------------

def validate_seizure_lines(body):
    lines = require_array(body, "seizure_lines")
    validated = []
    for line in lines:
        if not isinstance(line, dict):
            raise_error(ERR_VALIDATION, "seizure_lines entries must be objects")
        for key in line:
            if key not in ("units", "unit_value_cents"):
                raise_error(ERR_VALIDATION, "Unknown seizure line field: %s" % key)
        if "units" not in line or "unit_value_cents" not in line:
            raise_error(ERR_VALIDATION, "seizure_lines entries require units and unit_value_cents")
        units = line["units"]
        value = line["unit_value_cents"]
        if isinstance(units, bool) or not isinstance(units, int) or units <= 0:
            raise_error(ERR_VALIDATION, "seizure line units must be a positive integer")
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise_error(ERR_VALIDATION, "seizure line unit_value_cents must be a positive integer")
        validated.append({"units": units, "unit_value_cents": value})
    return validated


@bp.route("/brand/watch-alerts/<alert_id>/counterfeit-referrals", methods=["POST"])
def create_referral(alert_id):
    user_id, role = require_roles("AssociateAttorney")
    body = get_payload()
    reject_unknown_fields(body, {"referral_channel", "seizure_lines"})
    channel = require_enum(body, "referral_channel", REFERRAL_CHANNELS)
    lines = validate_seizure_lines(body)
    alert = _get_alert(alert_id)
    # Manual referral requires confirmed_counterfeit_count >= 3.
    if confirmed_counterfeit_count(alert["id"]) < 3:
        raise_error(ERR_REFERRAL_THRESHOLD_NOT_MET,
                    "manual referral requires confirmed_counterfeit_count >= 3")
    matter = active_matter_of_alert(alert) if alert["status"] == "ESCALATED" else None
    referral = {
        "watch_alert_id": alert["id"],
        "enforcement_matter_id": matter["id"] if matter else None,
        "referral_channel": channel,
        "seizure_lines": lines,
        "estimated_damages_cents": statutory_damages_cents(lines),
        "auto_created": False,
        "status": "DRAFT",
    }
    stamp_new(referral)
    db.counterfeit_referrals[referral["id"]] = referral
    return success(ser_counterfeit_referral(referral), 201)
