"""Collection lookups.  Each family raises its own 404 code (PRD 2.9)."""
from db import db, ordered
from errors import ApiError


def _get(collection, row_id, error_id):
    row = collection.get(row_id)
    if row is None:
        raise ApiError(error_id)
    return row


def get_area(row_id):
    return _get(db.screening_areas, row_id, "ERR_SCREENING_AREA_NOT_FOUND")


def get_facility(row_id):
    return _get(db.facilities, row_id, "ERR_FACILITY_NOT_FOUND")


def get_application(row_id):
    return _get(db.permit_applications, row_id, "ERR_APPLICATION_NOT_FOUND")


def get_assessment(row_id):
    return _get(db.assessments, row_id, "ERR_ASSESSMENT_NOT_FOUND")


def get_plan(row_id):
    return _get(db.participation_plans, row_id, "ERR_PLAN_NOT_FOUND")


def get_venue(row_id):
    return _get(db.venues, row_id, "ERR_VENUE_NOT_FOUND")


def get_meeting(row_id):
    return _get(db.public_meetings, row_id, "ERR_MEETING_NOT_FOUND")


def get_condition(row_id):
    return _get(db.permit_conditions, row_id, "ERR_CONDITION_NOT_FOUND")


def get_decision(row_id):
    return _get(db.permit_decisions, row_id, "ERR_DECISION_NOT_FOUND")


def get_complaint(row_id):
    return _get(db.community_complaints, row_id, "ERR_COMPLAINT_NOT_FOUND")


def get_inspection(row_id):
    return _get(db.inspections, row_id, "ERR_INSPECTION_NOT_FOUND")


# ------------------------------------------------------------------ selections
def indicators_of(area_id):
    return ordered([r for r in db.burden_indicators.values()
                    if r["screening_area_id"] == area_id])


def facilities_of(area_id):
    return ordered([r for r in db.facilities.values()
                    if r["screening_area_id"] == area_id])


def applications_of_facility(facility_id):
    return ordered([r for r in db.permit_applications.values()
                    if r["facility_id"] == facility_id])


def applications_in_area(area_id):
    facility_ids = {f["id"] for f in db.facilities.values()
                    if f["screening_area_id"] == area_id}
    return ordered([r for r in db.permit_applications.values()
                    if r["facility_id"] in facility_ids])


def determinations_of(application_id):
    return [r for r in db.applicability_determinations.values()
            if r["permit_application_id"] == application_id]


def assessments_of(application_id):
    return ordered([r for r in db.assessments.values()
                    if r["permit_application_id"] == application_id])


def plans_of(application_id):
    return ordered([r for r in db.participation_plans.values()
                    if r["permit_application_id"] == application_id])


def meetings_of_plan(plan_id):
    return ordered([r for r in db.public_meetings.values()
                    if r["participation_plan_id"] == plan_id])


def meetings_of_venue(venue_id):
    return ordered([r for r in db.public_meetings.values()
                    if r["venue_id"] == venue_id])


def comments_of_plan(plan_id):
    return ordered([r for r in db.public_comments.values()
                    if r["participation_plan_id"] == plan_id])


def conditions_of(application_id):
    return ordered([r for r in db.permit_conditions.values()
                    if r["permit_application_id"] == application_id])


def decisions_of(application_id):
    return ordered([r for r in db.permit_decisions.values()
                    if r["permit_application_id"] == application_id])


def complaints_in_area(area_id):
    return ordered([r for r in db.community_complaints.values()
                    if r["screening_area_id"] == area_id])


def inspections_of_complaint(complaint_id):
    return ordered([r for r in db.inspections.values()
                    if r["community_complaint_id"] == complaint_id])


def inspections_of_facility(facility_id):
    return ordered([r for r in db.inspections.values()
                    if r["facility_id"] == facility_id])


def facility_of_application(application):
    return db.facilities[application["facility_id"]]


def area_of_application(application):
    facility = db.facilities[application["facility_id"]]
    return db.screening_areas[facility["screening_area_id"]]


def area_of_facility(facility):
    return db.screening_areas[facility["screening_area_id"]]


def live_plan_of(application_id):
    """The application's single non-CANCELLED participation plan, or None."""
    for plan in plans_of(application_id):
        if plan["status"] != "CANCELLED":
            return plan
    return None
