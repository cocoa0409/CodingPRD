"""PRD 3.6-3.7 — drafting and issuing the determination, and the read-only
trip-by-trip condition evaluation."""

from flask import Blueprint

import lookups
import mirrors
import serializers
import shapes
from auth import actor_id, require
from envelope import created, ok
from errors import ApiError
from store import base_record, date_of, db, iso, now, ordered, plus_days, touch

bp = Blueprint("determinations", __name__)

REFERRAL_RESPONSE_WINDOW_DAYS = 14
NUMERIC_CONDITION_TYPES = ("HEAT_INDEX_ABOVE", "COLD_BELOW", "DISTANCE_OVER_METERS")


def _signed_off_assessment(app_rec):
    """PRD 3.6: the packet must own exactly one assessment whose attendance
    reads ATTENDED and whose scoring has reached SIGNED_OFF."""
    matches = [
        a
        for a in lookups.assessments_of_application(app_rec["id"])
        if a["attendance_status"] == "ATTENDED" and a["scoring_status"] == "SIGNED_OFF"
    ]
    return matches[0] if len(matches) == 1 else None


def _validate_conditions(payload):
    entries = shapes.opt_array(payload, "trip_conditions", None)
    if entries is None:
        return None
    cleaned = []
    for entry in entries:
        if not isinstance(entry, dict):
            shapes.bad("Each trip_conditions entry must be an object.")
        condition_type = shapes.req_enum(entry, "condition_type", shapes.CONDITION_TYPES)
        comparator = shapes.req_enum(entry, "comparator", shapes.COMPARATORS)
        threshold = shapes.opt_number(entry, "threshold_value", None, minimum=0)
        note = shapes.opt_str(entry, "note", None)
        # PRD 3.6: threshold_value is required whenever comparator is anything
        # other than IS_TRUE and must be null when comparator is IS_TRUE.
        if comparator == "IS_TRUE":
            if threshold is not None:
                shapes.bad("threshold_value must be null when comparator is IS_TRUE.")
            # PRD 3.7: IS_TRUE is never valid on a numeric condition type.
            if condition_type in NUMERIC_CONDITION_TYPES:
                shapes.bad("IS_TRUE is not valid on a numeric condition type.")
        elif threshold is None:
            shapes.bad("threshold_value is required when comparator is not IS_TRUE.")
        cleaned.append(
            {
                "condition_type": condition_type,
                "comparator": comparator,
                "threshold_value": threshold,
                "note": note,
            }
        )
    return cleaned


# ---------------------------------------------------------------------------
# POST /applications/{id}/determinations
# ---------------------------------------------------------------------------

@bp.post("/applications/<application_id>/determinations")
@require(("EligibilitySpecialist",))
def draft_determination(application_id):
    app_rec = lookups.application(application_id)
    payload = shapes.body()
    expected_version = shapes.req_int(payload, "expected_application_version")
    category = shapes.req_enum(payload, "category", shapes.CATEGORIES)
    effective_date = shapes.req_iso_date(payload, "effective_date")
    rationale = shapes.req_str(payload, "rationale")
    conditions = _validate_conditions(payload)

    if app_rec["status"] != "ASSESSMENT_COMPLETE":
        raise ApiError("ERR_INVALID_APPLICATION_STATE")
    if expected_version != app_rec["version"]:
        raise ApiError("ERR_STALE_APPLICATION_VERSION")
    if _signed_off_assessment(app_rec) is None:
        raise ApiError("ERR_ASSESSMENT_NOT_SIGNED_OFF")

    count = 0 if conditions is None else len(conditions)
    if category == "CONDITIONAL" and count < 1:
        raise ApiError("ERR_CONDITIONAL_REQUIRES_CONDITIONS")
    if category in ("UNCONDITIONAL", "INELIGIBLE") and count > 0:
        raise ApiError("ERR_UNCONDITIONAL_FORBIDS_CONDITIONS")

    rec = base_record()
    rec.update(
        {
            "application_id": app_rec["id"],
            "applicant_id": app_rec["applicant_id"],
            "category": category,
            "status": "DRAFT",
            "effective_date": effective_date,
            "term_days": None,
            "expires_at": None,
            "rationale": rationale,
            "determined_by_user_id": actor_id(),
            "issued_at": None,
            "under_appeal": False,
            "origin": "SPECIALIST_DETERMINATION",
            "trip_condition_count": count,
            "fixed_route_competency_confirmed": False,
        }
    )
    db.determinations[rec["id"]] = rec

    for entry in conditions or []:
        cond = base_record(with_version=False)
        cond.update({"determination_id": rec["id"]})
        cond.update(entry)
        db.trip_conditions[cond["id"]] = cond

    touch(app_rec)
    return created(serializers.determination(rec))


# ---------------------------------------------------------------------------
# POST /determinations/{id}/issue
# ---------------------------------------------------------------------------

@bp.post("/determinations/<determination_id>/issue")
@require(("EligibilitySpecialist",), identity_required=True)
def issue_determination(determination_id):
    rec = lookups.determination(determination_id)
    shapes.body()
    app_rec = db.applications.get(rec["application_id"])

    # PRD 2.5 stage 11 screens the state of the entity being driven — here the
    # determination's own issuance status. PRD 3.6 states the two
    # ERR_DETERMINATION_ALREADY_ISSUED triggers first, and the parent packet's
    # ASSESSMENT_COMPLETE requirement is a cross-entity referential
    # requirement, which PRD 2.5 places in stage 13.
    if rec["status"] != "DRAFT":
        raise ApiError("ERR_DETERMINATION_ALREADY_ISSUED")
    for other in lookups.determinations_of_application(rec["application_id"]):
        if other["id"] != rec["id"] and other["status"] == "ISSUED":
            raise ApiError("ERR_DETERMINATION_ALREADY_ISSUED")
    if app_rec is None or app_rec["status"] != "ASSESSMENT_COMPLETE":
        raise ApiError("ERR_INVALID_APPLICATION_STATE")
    if _signed_off_assessment(app_rec) is None:
        raise ApiError("ERR_ASSESSMENT_NOT_SIGNED_OFF")

    category = rec["category"]
    count = rec["trip_condition_count"]
    if category == "CONDITIONAL" and count < 1:
        raise ApiError("ERR_CONDITIONAL_REQUIRES_CONDITIONS")
    if category in ("UNCONDITIONAL", "INELIGIBLE") and count > 0:
        raise ApiError("ERR_UNCONDITIONAL_FORBIDS_CONDITIONS")

    instant = now()
    rec["issued_at"] = instant
    rec["term_days"] = mirrors.term_days_for(category)
    rec["expires_at"] = mirrors.expires_at_for(category, rec["effective_date"])
    rec["status"] = "ISSUED"
    touch(rec)

    # Every other determination of the same rider that was ISSUED is superseded.
    for other in lookups.determinations_of_applicant(rec["applicant_id"]):
        if other["id"] != rec["id"] and other["status"] == "ISSUED":
            other["status"] = "SUPERSEDED"
            touch(other)

    applicant = db.applicants.get(rec["applicant_id"])
    if applicant is not None:
        status = "INELIGIBLE" if category == "INELIGIBLE" else "ELIGIBLE"
        mirrors.set_eligibility(applicant, status, category, rec["id"])

    app_rec["status"] = "DETERMINED"
    statutory, net = serializers.pending_days(app_rec)
    app_rec["_frozen_pending"] = (statutory, net)
    touch(app_rec)

    if category == "CONDITIONAL":
        _create_auto_referral(rec)

    mirrors.supersede_visitor_records(rec["applicant_id"])
    return ok(serializers.determination(rec))


def _create_auto_referral(determination):
    """PRD 3.6 / 3.8 hop 4: a CONDITIONAL grant auto-creates a referral."""
    ref = base_record()
    ref.update(
        {
            "applicant_id": determination["applicant_id"],
            "determination_id": determination["id"],
            "referral_reason": "CONDITIONAL_ELIGIBILITY_AUTO",
            "status": "REFERRED",
            "referral_response_deadline_date": plus_days(
                date_of(now()), REFERRAL_RESPONSE_WINDOW_DAYS
            ),
            "fixed_route_competency_score": None,
            "completed_at": None,
            "withdrawal_reason": None,
        }
    )
    db.referrals[ref["id"]] = ref
    return ref


# ---------------------------------------------------------------------------
# POST /determinations/{id}/trip-eligibility-check
# ---------------------------------------------------------------------------

def _compare(value, comparator, threshold):
    if value is None or threshold is None:
        return False
    if comparator == "GTE":
        return value >= threshold
    if comparator == "GT":
        return value > threshold
    if comparator == "LTE":
        return value <= threshold
    if comparator == "LT":
        return value < threshold
    return False


@bp.post("/determinations/<determination_id>/trip-eligibility-check")
@require(("Applicant", "IntakeClerk", "EligibilitySpecialist", "AccessibilityOfficeAdmin"))
def trip_eligibility_check(determination_id):
    rec = lookups.determination(determination_id)
    payload = shapes.body()
    trip_date = shapes.req_iso_date(payload, "trip_date")
    heat_index = shapes.opt_number(payload, "forecast_heat_index_f", None)
    precipitation = shapes.opt_bool(payload, "precipitation_flag", None)
    path_barrier = shapes.opt_bool(payload, "path_barrier_flag", None)
    is_night = shapes.opt_bool(payload, "is_night_trip", None)
    familiarity = shapes.opt_enum(payload, "route_familiarity", shapes.ROUTE_FAMILIARITY, None)
    distance = shapes.opt_number(payload, "origin_distance_to_stop_meters", None)

    if rec["status"] != "ISSUED":
        raise ApiError("ERR_DETERMINATION_NOT_ACTIVE")

    category = rec["category"]
    if category == "INELIGIBLE":
        return ok(_answer(False, [], "CATEGORY_INELIGIBLE", 0, category))
    if category == "UNCONDITIONAL":
        return ok(_answer(True, [], None, 0, category))
    if rec["expires_at"] is not None and trip_date > rec["expires_at"]:
        return ok(_answer(False, [], "TERM_EXPIRED", 0, category))

    conditions = ordered(lookups.conditions_of(rec["id"]))
    applied = []
    for cond in conditions:
        kind = cond["condition_type"]
        comparator = cond["comparator"]
        threshold = cond["threshold_value"]
        if kind in ("HEAT_INDEX_ABOVE", "COLD_BELOW"):
            hit = _compare(heat_index, comparator, threshold)
        elif kind == "DISTANCE_OVER_METERS":
            hit = _compare(distance, comparator, threshold)
        elif kind == "PRECIPITATION":
            hit = precipitation is True
        elif kind == "PATH_OF_TRAVEL_BARRIER":
            hit = path_barrier is True
        elif kind == "NIGHT_TRAVEL":
            hit = is_night is True
        elif kind == "COGNITIVE_UNFAMILIAR_ROUTE":
            hit = familiarity == "UNFAMILIAR" and rec["fixed_route_competency_confirmed"] is False
        else:
            hit = False
        if hit:
            applied.append(cond["id"])

    eligible = len(applied) >= 1
    return ok(
        _answer(eligible, applied, None if eligible else "NO_CONDITION_MET", len(conditions), category)
    )


def _answer(eligible, applied, denial_reason, evaluated, category):
    return {
        "eligible": eligible,
        "applied_condition_ids": applied,
        "denial_reason": denial_reason,
        "evaluated_condition_count": evaluated,
        "category": category,
    }
