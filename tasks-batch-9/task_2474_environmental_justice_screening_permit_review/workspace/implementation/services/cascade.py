"""Derived-field recomputation and the downstream cascades of PRD 2.8.

Every row a cascade touches is a real mutation of that row: updated_at is
refreshed and version increases by exactly 1 (once per request, per PRD 2.4).
"""
from datetime import timedelta
from decimal import Decimal

import constants as C
from db import (clock_date, clock_minus_days, clock_year, db, iso_ts, new_row,
                touch)
from services import calc, repo

ZERO = Decimal("0.00")


# ---------------------------------------------------------------- screening area
def qualifying_indicators(area):
    year = clock_year()
    low = year - C.INDICATOR_VALIDITY_YEARS
    return [
        row
        for row in repo.indicators_of(area["id"])
        if row["status"] == "ACTIVE" and low <= row["vintage_year"] <= year
    ]


def rescore_area(area, cascade=True):
    """Recompute both ej_screen_score variants, then re-evaluate designation."""
    rows = qualifying_indicators(area)
    points = area["enforcement_burden_points"]
    statewide, pollution, health, demographic = calc.ej_screen_score(
        rows, "statewide_percentile", points
    )
    county, _, _, _ = calc.ej_screen_score(rows, "county_percentile", points)

    area["pollution_component_statewide"] = pollution
    area["health_component_statewide"] = health
    area["demographic_component_statewide"] = demographic
    area["ej_screen_score_statewide"] = statewide
    area["ej_screen_score_county"] = county
    area["active_indicator_count"] = len(rows)
    area["translation_required"] = calc.translation_required_for(
        area["limited_english_pct"]
    )

    previous = area["designation"]
    area["designation"] = calc.designation_for(statewide)
    touch(area)

    if not cascade:
        return

    if area["designation"] != previous and area["designation"] != "UNDESIGNATED":
        escalate_standard_applications(area)
        recompute_area_plan_days(area)
    rescore_area_complaints(area)


def escalate_standard_applications(area):
    """Designation escalation drags STANDARD_REVIEW applications onto the enhanced track."""
    for application in repo.applications_in_area(area["id"]):
        if application["status"] != "STANDARD_REVIEW":
            continue
        facility = repo.facility_of_application(application)
        codes = calc.applicability_trigger_codes(facility, area, application)
        if "DESIGNATION" not in codes:
            codes.append("DESIGNATION")
        determination = write_determination(application, area, codes, "system")
        application["review_track"] = "ENHANCED"
        application["status"] = "ENHANCED_REVIEW"
        plan = repo.live_plan_of(application["id"])
        if plan is None:
            create_plan(application, area)
        else:
            recompute_plan_days(plan, area)
        touch(application)
        determination["application_version_after"] = application["version"]


def recompute_area_plan_days(area):
    for application in repo.applications_in_area(area["id"]):
        plan = repo.live_plan_of(application["id"])
        if plan is not None and plan["status"] in ("PLANNED", "OPEN", "EXTENDED"):
            recompute_plan_days(plan, area)


def rescore_area_complaints(area):
    for complaint in repo.complaints_in_area(area["id"]):
        if complaint["status"] in ("RECEIVED", "TRIAGED"):
            rescore_complaint(complaint, area)


# ------------------------------------------------------- applicability determination
def write_determination(application, area, codes, user_id):
    row = new_row(full_audit=False)
    row.update(
        {
            "permit_application_id": application["id"],
            "result": "ENHANCED_REQUIRED" if codes else "STANDARD",
            "trigger_codes": list(codes),
            "area_designation_snapshot": area["designation"],
            "ej_screen_score_snapshot": area["ej_screen_score_statewide"],
            "revision_round": application["revision_round"],
            "determined_by_user_id": user_id,
            "application_version_after": application["version"],
        }
    )
    db.applicability_determinations[row["id"]] = row
    return row


# ------------------------------------------------------------- governing assessment
def governing_assessment(application):
    candidates = [
        row
        for row in repo.assessments_of(application["id"])
        if row["status"] in ("ACCEPTED", "DRAFT", "SUBMITTED_FOR_QA", "RETURNED")
    ]
    if not candidates:
        return None
    # created_at DESC, then version DESC (stable secondary pass keeps rank first).
    candidates.sort(key=lambda r: (r["created_at"], r["version"], r["_seq"]),
                    reverse=True)
    candidates.sort(key=lambda r: 0 if r["status"] == "ACCEPTED" else 1)
    return candidates[0]


def governing_index(application):
    governing = governing_assessment(application)
    return governing["cumulative_impact_index"] if governing else None


def recompute_residual(application):
    application["residual_impact_index"] = calc.residual_impact_index(
        application["pre_mitigation_index"],
        application["total_mitigation_credit_tpy"],
        application["proposed_emissions_tpy"],
    )


def recompute_indices(application):
    governing = governing_assessment(application)
    application["pre_mitigation_index"] = (
        governing["cumulative_impact_index"] if governing else ZERO
    )
    recompute_residual(application)


def recompute_credit(application):
    active = [
        row
        for row in repo.conditions_of(application["id"])
        if row["status"] == "ACTIVE"
    ]
    active.sort(key=lambda r: (r["created_at"], r["version"], r["_seq"]))
    application["total_mitigation_credit_tpy"] = calc.total_mitigation_credit(active)
    recompute_residual(application)


def transition_assessments(application, from_statuses, to_status):
    """Move every assessment of the application out of from_statuses; returns moved rows."""
    moved = []
    for row in repo.assessments_of(application["id"]):
        if row["status"] in from_statuses:
            row["status"] = to_status
            touch(row)
            moved.append(row)
    return moved


def stamp_assessments(rows, application):
    for row in rows:
        row["application_version_after"] = application["version"]


# ----------------------------------------------------------------- participation
def create_plan(application, area):
    row = new_row()
    row.update(
        {
            "permit_application_id": application["id"],
            "required_comment_days": calc.required_comment_days(
                area["designation"],
                area["translation_required"],
                governing_index(application),
            ),
            "granted_extension_days": 0,
            "comment_start_date": None,
            "comment_end_date": None,
            "translated_languages": [],
            "materials_translated": False,
            "meeting_count": 0,
            "comment_count": 0,
            "adequacy_status": "PENDING",
            "deficiency_codes": [],
            "status": "PLANNED",
        }
    )
    db.participation_plans[row["id"]] = row
    return row


def recompute_plan_days(plan, area):
    """Rewrites required_comment_days ONLY; comment_end_date is never moved here."""
    application = db.permit_applications[plan["permit_application_id"]]
    plan["required_comment_days"] = calc.required_comment_days(
        area["designation"], area["translation_required"], governing_index(application)
    )
    touch(plan)


def reopen_plan(plan, area):
    added = calc.reopen_added_days(
        plan["required_comment_days"], plan["granted_extension_days"]
    )
    plan["granted_extension_days"] = plan["granted_extension_days"] + added
    anchor = plan["comment_end_date"] or clock_date()
    plan["comment_end_date"] = max(clock_date(), anchor) + timedelta(days=added)
    plan["adequacy_status"] = "PENDING"
    plan["deficiency_codes"] = []
    plan["status"] = "OPEN"
    touch(plan)
    area["open_plan_count"] = area["open_plan_count"] + 1
    touch(area)


def cancel_plan_cascade(application, area):
    plan = repo.live_plan_of(application["id"])
    if plan is None or plan["status"] not in ("PLANNED", "OPEN", "EXTENDED", "CLOSED"):
        return
    previous = plan["status"]
    for meeting in repo.meetings_of_plan(plan["id"]):
        if meeting["status"] != "SCHEDULED":
            continue
        meeting["status"] = "CANCELLED"
        touch(meeting)
        venue = db.venues[meeting["venue_id"]]
        venue["booked_meeting_count"] = venue["booked_meeting_count"] - 1
        touch(venue)
        plan["meeting_count"] = plan["meeting_count"] - 1
    plan["status"] = "CANCELLED"
    touch(plan)
    if previous in ("OPEN", "EXTENDED"):
        area["open_plan_count"] = area["open_plan_count"] - 1
        touch(area)


def participation_adequacy(plan, area):
    codes = []
    window_days = (plan["comment_end_date"] - plan["comment_start_date"]).days + 1
    if window_days < plan["required_comment_days"]:
        codes.append("SHORT_COMMENT_PERIOD")

    now = db.clock
    accessible = 0
    for meeting in repo.meetings_of_plan(plan["id"]):
        if (
            meeting["status"] == "SCHEDULED"
            and meeting["accessibility_verified"]
            and meeting["_ends_at"] <= now
        ):
            accessible += 1
    if accessible == 0:
        codes.append("NO_ACCESSIBLE_MEETING")

    if area["translation_required"]:
        missing = any(
            code not in plan["translated_languages"]
            for code in area["required_translation_languages"]
        )
        if not plan["materials_translated"] or missing:
            codes.append("MISSING_TRANSLATION")

    if any(
        not comment["in_required_language"]
        for comment in repo.comments_of_plan(plan["id"])
    ):
        codes.append("LANGUAGE_ACCESS_GAP")

    plan["deficiency_codes"] = codes
    plan["adequacy_status"] = "COMPLIANT" if not codes else "DEFICIENT"


def area_engagement_conflicts(plan, area, start_date, end_date):
    """Closed date intervals: a shared endpoint day DOES collide."""
    count = 0
    for other in db.participation_plans.values():
        if other["id"] == plan["id"]:
            continue
        if other["status"] not in ("OPEN", "EXTENDED"):
            continue
        application = db.permit_applications.get(other["permit_application_id"])
        if application is None:
            continue
        if repo.area_of_application(application)["id"] != area["id"]:
            continue
        if other["comment_start_date"] is None or other["comment_end_date"] is None:
            continue
        if other["comment_start_date"] <= end_date and start_date <= other["comment_end_date"]:
            count += 1
    return count


def engagement_cap(area):
    if area["designation"] == "SEVERELY_OVERBURDENED":
        return C.MAX_CONCURRENT_OPEN_PLANS_SEVERE
    return C.MAX_CONCURRENT_OPEN_PLANS_DEFAULT


# ---------------------------------------------------------------------- meetings
def venue_slot_conflict(venue_id, starts_at, ends_at):
    """Half-open geometry with a symmetric 60-minute turnover buffer."""
    buffer_delta = timedelta(minutes=C.VENUE_TURNOVER_BUFFER_MINUTES)
    candidate_start = starts_at - buffer_delta
    candidate_end = ends_at + buffer_delta
    for meeting in db.public_meetings.values():
        if meeting["venue_id"] != venue_id or meeting["status"] != "SCHEDULED":
            continue
        if candidate_start < meeting["_ends_at"] and meeting["_starts_at"] < candidate_end:
            return True
    return False


# -------------------------------------------------------------------- complaints
def repeat_count_180d(complaint):
    cutoff = iso_ts(clock_minus_days(C.REPEAT_WINDOW_DAYS))
    count = 0
    for other in db.community_complaints.values():
        if other["id"] == complaint["id"]:
            continue
        if other["screening_area_id"] != complaint["screening_area_id"]:
            continue
        if other["complaint_type"] != complaint["complaint_type"]:
            continue
        if other["status"] == "DISMISSED":
            continue
        if other["created_at"] < cutoff:
            continue
        if other["created_at"] >= complaint["created_at"]:
            continue
        count += 1
    return count


def rescore_complaint(complaint, area):
    repeats = repeat_count_180d(complaint)
    facility = None
    if complaint["facility_id"] is not None:
        facility = db.facilities.get(complaint["facility_id"])
    violation = facility is not None and facility["compliance_status"] == "VIOLATION_ON_RECORD"
    score = calc.inspection_priority_score(
        area["ej_screen_score_county"],
        complaint["severity"],
        repeats,
        violation,
        area["designation"] == "SEVERELY_OVERBURDENED",
    )
    complaint["repeat_count_180d"] = repeats
    complaint["priority_score"] = score
    complaint["priority_tier"] = calc.priority_tier_for(score)
    touch(complaint)


# ------------------------------------------------------- enforcement stale cascade
def stale_data_cascade(area):
    """Link 3 and link 4 of the confirmed-violation cascade."""
    for application in repo.applications_in_area(area["id"]):
        invalidated = transition_assessments(application, ("ACCEPTED",), "INVALIDATED")
        if not invalidated:
            continue
        application["screening_stale_flag"] = True
        if (
            application["status"] == "PENDING_DECISION"
            and application["review_track"] == "ENHANCED"
        ):
            application["status"] = "ENHANCED_REVIEW"
        recompute_indices(application)
        touch(application)
        stamp_assessments(invalidated, application)
